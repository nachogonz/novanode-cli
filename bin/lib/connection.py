import os
import shlex
import shutil
import subprocess
import threading
import time


class CommandError(Exception):
    pass


class Runner:
    """Runs Asterisk core commands on the box (SSH or local)."""

    def __init__(self, ssh_host="", ssh_user="", sudo=False, timeout=15):
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.sudo = sudo
        self.timeout = timeout

    @property
    def remote(self):
        return bool(self.ssh_host)

    @property
    def privilege(self):
        if not self.sudo:
            return ""
        if self.remote and self.ssh_user == "root":
            return ""
        if not self.remote and os.geteuid() == 0:
            return ""
        return "sudo -n "

    def run(self, cmd):
        if self.remote:
            if not shutil.which("ssh"):
                raise CommandError("ssh not available")
            target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
            asterisk = self.privilege + "asterisk"
            full = f"{asterisk} -rx {shlex.quote(cmd)}"
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", target, full],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                raise CommandError((proc.stderr or "").strip() or f"ssh {target} failed")
            return proc.stdout.splitlines()
        if not shutil.which("asterisk"):
            raise CommandError("asterisk not on PATH locally")
        try:
            command = ["asterisk", "-rx", cmd]
            if self.privilege:
                command = ["sudo", "-n"] + command
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise CommandError("asterisk not found")
        if proc.returncode != 0:
            raise CommandError((proc.stderr or "").strip())
        return proc.stdout.splitlines()

    def read_remote_file(self, path):
        if not self.remote:
            try:
                with open(path) as fh:
                    return fh.read()
            except OSError as e:
                raise CommandError(str(e))
        target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target, f"{self.privilege}cat {shlex.quote(path)}"],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if proc.returncode != 0:
            raise CommandError((proc.stderr or "").strip())
        return proc.stdout

    def write_remote_file(self, path, contents, new_owner="root", new_group="asterisk", new_mode="0640"):
        target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
        if self.remote:
            quoted = shlex.quote(path)
            privilege = self.privilege
            script = (
                "set -eu; tmp=$(mktemp /tmp/novanode.XXXXXX); "
                "trap 'rm -f \"$tmp\"' EXIT; cat > \"$tmp\"; "
                f"if {privilege}test -e {quoted}; then "
                f"{privilege}cp -p {quoted} {shlex.quote(path + '.novanode-bak')}; "
                f"owner=$({privilege}stat -c %u {quoted}); group=$({privilege}stat -c %g {quoted}); "
                f"mode=$({privilege}stat -c %a {quoted}); "
                f"else owner={shlex.quote(str(new_owner))}; group={shlex.quote(str(new_group))}; mode={shlex.quote(str(new_mode))}; fi; "
                f"{privilege}install -o \"$owner\" -g \"$group\" -m \"$mode\" \"$tmp\" {quoted}"
            )
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", target, script],
                input=contents,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                raise CommandError((proc.stderr or "").strip())
        else:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                backup = path + ".novanode-bak"
                if os.path.exists(path):
                    shutil.copy2(path, backup)
                with open(path, "w") as fh:
                    fh.write(contents)
            except OSError as e:
                raise CommandError(str(e))

    def remote_file_exists(self, path):
        if not self.remote:
            return os.path.exists(path)
        target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
        quoted = shlex.quote(path)
        script = (
            f"if {self.privilege}test -e {quoted}; then echo exists; "
            f"elif {self.privilege}test ! -e {quoted}; then echo missing; "
            "else exit 2; fi"
        )
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target, script],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        state = result.stdout.strip()
        if result.returncode != 0 or state not in ("exists", "missing"):
            raise CommandError((result.stderr or "could not determine remote file state").strip())
        return state == "exists"

    def run_remote_shell(self, script):
        if not self.remote:
            import os

            if os.system(script) == 0:
                return
            raise CommandError("local shell script failed")
        target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", target, script],
            capture_output=True,
            text=True,
            timeout=self.timeout * 2,
        )
        if proc.returncode != 0:
            raise CommandError((proc.stderr or "").strip())


class Tunnel:
    """ssh -L port-forward so a loopback-only AMI on the box becomes reachable."""

    def __init__(self, ssh_host, ssh_user, remote_port=5038, local_port=0):
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.remote_port = remote_port
        self.local_port = local_port
        self.proc = None
        self._ready = threading.Event()

    def start(self):
        if not self.ssh_host:
            self.local_port = self.remote_port
            self._ready.set()
            return self
        self.local_port = self._free_port()
        target = self.ssh_user + "@" + self.ssh_host if self.ssh_user else self.ssh_host
        args = [
            "ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-L", f"127.0.0.1:{self.local_port}:127.0.0.1:{self.remote_port}", target,
        ]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and self.proc.poll() is None:
            if self._port_open(self.local_port):
                self._ready.set()
                return self
            time.sleep(0.3)
        try:
            self.proc.kill()
        except Exception:
            pass
        self.local_port = 0
        raise CommandError(f"could not open ssh tunnel to {target}:{self.remote_port}")

    def _free_port(self):
        import socket

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _port_open(self, port):
        import socket

        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
            s.close()
            return True
        except OSError:
            return False

    def stop(self):
        if self.proc:
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=2)
                except Exception:
                    self.proc.kill()
            except Exception:
                pass
            self.proc = None
