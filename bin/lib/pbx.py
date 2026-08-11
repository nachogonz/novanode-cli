import time

import config as nnconfig
from ami import AMIClient, AMIError
from connection import Runner, Tunnel


class PBX:
    def __init__(self, cfg=None):
        self.cfg = cfg or nnconfig.load_config()
        p = self.cfg["pbx"]
        self.runner = Runner(
            ssh_host=p.get("ssh_host") or (p["host"] if p.get("via_ssh") else ""),
            ssh_user=p["ssh_user"],
            sudo=p.get("ssh_sudo", True),
        )
        self.tunnel = None
        self.client = None
        self.last_error = None
        self.connected_at = 0

    # ── AMI (optional, via tunnel so loopback-only stays loopback) ─
    def connect_ami(self, secret=None):
        self.close()
        p = self.cfg["pbx"]
        secret = secret or nnconfig.ami_secret(self.cfg)
        try:
            self.tunnel = Tunnel(
                p.get("ssh_host") or (p["host"] if p.get("via_ssh") else ""),
                p["ssh_user"],
                remote_port=int(p["ami_port"]),
            ).start()
        except Exception as e:
            self.last_error = f"tunnel: {e}"
            return False
        ami_host = "127.0.0.1" if self.tunnel and self.tunnel.proc else (p["ami_host"] or "127.0.0.1")
        ami_port = self.tunnel.local_port if self.tunnel and self.tunnel.proc else int(p["ami_port"])
        self.client = AMIClient(ami_host, ami_port, p["ami_user"], secret)
        try:
            self.client.connect()
        except (AMIError, OSError, TimeoutError, ConnectionError) as e:
            self.last_error = str(e)
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            self._stop_tunnel()
            return False
        self.connected_at = time.monotonic()
        self.last_error = None
        try:
            self.client.listen()
        except Exception:
            pass
        return True

    def _stop_tunnel(self):
        if self.tunnel:
            try:
                self.tunnel.stop()
            except Exception:
                pass
            self.tunnel = None

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self._stop_tunnel()

    @property
    def connected(self):
        return self.client is not None

    # ── ssh-based core commands (the doctor path) ──────────────────
    def core_version(self):
        try:
            lines = self.runner.run("core show version")
            return lines[0].strip() if lines else "n/a"
        except Exception:
            return "n/a"

    def uptime_seconds(self):
        try:
            lines = self.runner.run("core show uptime")
            system_line = next((line for line in lines if line.lower().startswith("system uptime:")), "")
            text = system_line.lower()
            seconds = 0
            parts = text.split()
            for i, tok in enumerate(parts):
                if "day" in tok:
                    seconds += int(parts[i - 1]) * 86400
                elif "hour" in tok:
                    seconds += int(parts[i - 1]) * 3600
                elif "minute" in tok:
                    seconds += int(parts[i - 1]) * 60
                elif "second" in tok:
                    seconds += int(parts[i - 1])
            return seconds
        except Exception:
            return 0

    def transports(self):
        try:
            lines = self.runner.run("pjsip show transports")
        except Exception:
            return []
        out = []
        for line in lines:
            stripped = line.strip()
            if not stripped.lower().startswith("transport:"):
                continue
            parts = stripped.split()
            if len(parts) >= 6 and not parts[1].startswith("<"):
                out.append({"name": parts[1], "type": parts[2].lower(), "bind": parts[-1]})
        return out

    def endpoints(self):
        return self.endpoints_long()

    def endpoints_long(self):
        try:
            lines = self.runner.run("pjsip show endpoints")
        except Exception:
            return []
        eps = []
        for line in lines:
            stripped = line.strip()
            if not stripped.lower().startswith("endpoint:"):
                continue
            fields = stripped.split()
            if len(fields) < 3 or fields[1].startswith("<"):
                continue
            endpoint = fields[1]
            name, _, username = endpoint.partition("/")
            channels = fields[-1] if fields[-1].isdigit() else ""
            state_fields = fields[2:-1] if channels else fields[2:]
            eps.append({"name": name, "username": username, "state": " ".join(state_fields)})
        return eps

    def _strip_quot(self, s):
        if isinstance(s, str):
            return s.strip('"<>() ')
        return s

    def registrations(self):
        try:
            lines = self.runner.run("pjsip show registrations")
        except Exception:
            return []
        out = []
        for line in lines:
            stripped = line.strip()
            if not any(state in stripped for state in ("Registered", "Unregistered", "Rejected", "Failed")):
                continue
            parts = stripped.split()
            if not parts or parts[0].startswith("<"):
                continue
            state_index = next((i for i, part in enumerate(parts) if part in ("Registered", "Unregistered", "Rejected", "Failed")), -1)
            if state_index > 0:
                out.append({"index": str(len(out) + 1), "obj": parts[0], "state": " ".join(parts[state_index:])})
        return out

    def channels(self):
        try:
            lines = self.runner.run("core show channels concise")
        except Exception:
            return []
        chans = []
        for line in lines:
            cols = line.split("!")
            if len(cols) >= 12:
                chans.append({
                    "channel": cols[0],
                    "context": cols[1],
                    "exten": cols[2],
                    "state": cols[4],
                    "application": cols[5],
                    "data": cols[6],
                    "caller": cols[7],
                    "duration": cols[11],
                    "bridge": cols[12] if len(cols) > 12 else "",
                    "unique_id": cols[13] if len(cols) > 13 else "",
                })
        return chans

    def contexts(self, pattern=""):
        try:
            lines = self.runner.run(f"dialplan show {'like ' + pattern if pattern else ''}".rstrip())
        except Exception:
            return []
        return [l for l in lines]

    def module_loaded(self, name):
        if not all(ch.isalnum() or ch in "_.-" for ch in name):
            return False
        try:
            lines = self.runner.run(f"module show like {name}")
            wanted = name.lower()
            return any(
                line.split() and line.split()[0].lower() == wanted and "running" in line.lower()
                for line in lines
            )
        except Exception:
            return False

    def recent_events(self):
        if not self.connected:
            return []
        return self.client.drain_events()
