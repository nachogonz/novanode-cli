import os
import json
import re
import socket
import threading
import time

import config as nnconfig
from connection import Tunnel


class PhoneError(Exception):
    pass


class Phone:
    STATE_IDLE = "idle"
    STATE_REGISTERING = "registering"
    STATE_REGISTERED = "registered"
    STATE_DIALING = "dialing"
    STATE_RINGING = "ringing"
    STATE_IN_CALL = "in_call"
    STATE_INCOMING = "incoming"
    STATE_ERROR = "error"

    def __init__(self, cfg=None):
        self.cfg = cfg or nnconfig.load_config()
        phone = self.cfg["phone"]
        self.state = self.STATE_IDLE
        self.registered = False
        self.extension = phone["extension"]
        self.display_name = phone["display_name"]
        self.dial_buffer = ""
        self.remote = ""
        self.codec = phone["codec"]
        self.jitter_ms = None
        self.loss_pct = None
        self.call_started_at = None
        self.incoming_caller = ""
        self.direction = None
        self.mic_muted = False
        self.audio_on = True
        self.client_name = "baresip@ssh"
        self._simulated = False
        self.sim_timer = 0.0
        self.last_event = ""
        self.tunnel = None
        self.control = None
        self.reader = None
        self.stop_event = threading.Event()
        self.events = []
        self.lock = threading.Lock()

    def start(self):
        if os.environ.get("NOVANODE_PHONE_SIMULATE") == "1":
            self._simulated = True
            self.registered = True
            self.state = self.STATE_REGISTERED
            self.last_event = "explicit simulation mode"
            return True

        phone = self.cfg["phone"]
        if phone.get("backend") != "baresip-ssh":
            return self._fail(f"unsupported phone backend: {phone.get('backend')}")
        ssh_host = phone.get("ssh_host")
        if not ssh_host:
            return self._fail("configure the Fedora baresip host with `nn pbx setup`")
        try:
            self.state = self.STATE_REGISTERING
            self.tunnel = Tunnel(
                ssh_host,
                phone.get("ssh_user", ""),
                remote_port=int(phone.get("control_port", 4444)),
            ).start()
            self.control = socket.create_connection(("127.0.0.1", self.tunnel.local_port), timeout=3)
            self.control.settimeout(0.5)
            self.stop_event.clear()
            self.reader = threading.Thread(target=self._read_events, daemon=True)
            self.reader.start()
            self._send_control("reginfo", token="register-probe")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and self.state == self.STATE_REGISTERING:
                time.sleep(0.05)
            if not self.registered:
                self.stop()
                return self._fail("baresip ctrl_tcp is reachable, but SIP registration was not confirmed")
            self.last_event = f"baresip registered on {ssh_host}"
            return True
        except Exception as exc:
            self.stop()
            return self._fail(f"baresip control unavailable: {exc}")

    def _fail(self, message):
        self.state = self.STATE_ERROR
        self.last_event = message
        return False

    def _read_events(self):
        buffer = b""
        while not self.stop_event.is_set() and self.control:
            try:
                chunk = self.control.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while True:
                colon = buffer.find(b":")
                if colon < 1:
                    break
                try:
                    size = int(buffer[:colon])
                except ValueError:
                    buffer = buffer[colon + 1 :]
                    continue
                end = colon + 1 + size
                if len(buffer) < end + 1:
                    break
                if buffer[end : end + 1] != b",":
                    buffer = buffer[end + 1 :]
                    continue
                raw = buffer[colon + 1 : end]
                buffer = buffer[end + 1 :]
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeError, ValueError):
                    continue
                if isinstance(message, dict):
                    self._handle_message(message)

    def _handle_message(self, message):
        raw = json.dumps(message, separators=(",", ":"))
        with self.lock:
            self.events.append(raw)
            self.events = self.events[-200:]
        if message.get("response"):
            if message.get("token") == "register-probe":
                data = re.sub(r"\x1b\[[0-9;]*m", "", str(message.get("data", "")))
                account = str(self.cfg["phone"].get("sip_user") or self.extension)
                account_lines = [line for line in data.splitlines() if account in line]
                registration_ok = any(re.search(r"\bOK\b", line) for line in account_lines)
                if message.get("ok") and registration_ok:
                    self.registered = True
                    self.state = self.STATE_REGISTERED
                elif not message.get("ok") or "unregistered" in data.lower():
                    self.registered = False
                    self.state = self.STATE_ERROR
            return
        event_type = str(message.get("type", "")).upper()
        if event_type in ("UNREGISTERING", "REGISTER_FAIL"):
            self.registered = False
            self.state = self.STATE_ERROR
            self.last_event = "baresip registration failed"
            return
        if event_type == "REGISTER_OK":
            self.registered = True
            if self.state in (self.STATE_REGISTERING, self.STATE_IDLE, self.STATE_ERROR):
                self.state = self.STATE_REGISTERED
            return
        if event_type == "CALL_INCOMING":
            peer = str(message.get("peeruri") or message.get("param") or "")
            match = re.search(r"sip:([^@> ;]+)", peer, re.IGNORECASE)
            self.incoming_caller = match.group(1) if match else "unknown"
            self.remote = self.incoming_caller
            self.direction = "in"
            self.state = self.STATE_INCOMING
            self.last_event = f"incoming call from {self.incoming_caller}"
        elif event_type in ("CALL_RINGING", "CALL_PROGRESS"):
            self.state = self.STATE_RINGING
            self.last_event = f"ringing {self.remote}"
        elif event_type == "CALL_ESTABLISHED":
            self.state = self.STATE_IN_CALL
            self.call_started_at = time.monotonic()
            self.last_event = "call established"
        elif event_type == "CALL_CLOSED":
            self._reset_call()

    def _send_control(self, command, params=None, token=None):
        if "\n" in command or "\r" in command:
            raise PhoneError("invalid baresip command")
        if not self.control:
            raise PhoneError("baresip control is not connected")
        message = {"command": command}
        if params is not None:
            message["params"] = params
        if token is not None:
            message["token"] = token
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
        frame = str(len(payload)).encode("ascii") + b":" + payload + b","
        try:
            self.control.sendall(frame)
        except OSError as exc:
            raise PhoneError(str(exc)) from exc

    def stop(self):
        self.stop_event.set()
        if self.control:
            try:
                self.control.close()
            except OSError:
                pass
            self.control = None
        if self.tunnel:
            self.tunnel.stop()
            self.tunnel = None

    def dial(self, number=None):
        if number is not None:
            self.dial_buffer = number.strip()
        number = self.dial_buffer.strip()
        if not re.fullmatch(r"[0-9*#+]+", number):
            self.last_event = "destination must contain digits, *, #, or +"
            return False
        if not self.registered:
            self.last_event = "baresip is not registered"
            return False
        self.remote = number
        self.direction = "out"
        self.state = self.STATE_DIALING
        if self._simulated:
            self.sim_timer = time.monotonic()
        else:
            pbx_host = self.cfg["pbx"]["host"]
            if not re.fullmatch(r"[A-Za-z0-9.:-]+", pbx_host):
                return self._fail("invalid PBX host")
            try:
                self._send_control("dial", f"sip:{number}@{pbx_host};transport=tls")
            except PhoneError as exc:
                return self._fail(str(exc))
        self.last_event = f"dial command sent to {number}"
        return True

    def answer(self):
        if not self._simulated:
            try:
                self._send_control("accept")
            except PhoneError as exc:
                self.last_event = str(exc)
                return False
        self.state = self.STATE_IN_CALL
        self.call_started_at = time.monotonic()
        self.incoming_caller = ""
        self.last_event = "answer command sent"
        return True

    def hangup(self):
        if not self._simulated and self.control:
            try:
                self._send_control("hangup")
            except PhoneError as exc:
                self.last_event = str(exc)
                return False
        self._reset_call()
        return True

    def _reset_call(self):
        self.state = self.STATE_REGISTERED if self.registered else self.STATE_IDLE
        self.remote = ""
        self.call_started_at = None
        self.incoming_caller = ""
        self.direction = None
        self.last_event = "call ended"

    def dtmf(self, digit):
        if self.state != self.STATE_IN_CALL or not re.fullmatch(r"[0-9*#]", digit):
            return False
        if not self._simulated:
            self._send_control("sndcode", digit)
        self.last_event = f"DTMF {digit}"
        return True

    def toggle_mic(self):
        if not self._simulated:
            try:
                self._send_control("mute")
            except PhoneError as exc:
                self.last_event = str(exc)
                return
        self.mic_muted = not self.mic_muted
        self.last_event = "mic muted" if self.mic_muted else "mic unmuted"

    def toggle_audio(self):
        self.audio_on = not self.audio_on
        self.last_event = "audio monitor on" if self.audio_on else "audio monitor off"

    def tick(self):
        if not self._simulated or self.state not in (self.STATE_DIALING, self.STATE_RINGING):
            return
        elapsed = time.monotonic() - self.sim_timer
        if self.state == self.STATE_DIALING and elapsed >= 1:
            self.state = self.STATE_RINGING
        if elapsed >= 3:
            self.state = self.STATE_IN_CALL
            self.call_started_at = time.monotonic()

    def simulate_incoming(self, caller="9000"):
        if self._simulated and self.state in (self.STATE_IDLE, self.STATE_REGISTERED):
            self.state = self.STATE_INCOMING
            self.incoming_caller = caller
            self.last_event = f"incoming call from {caller}"

    def duration_str(self):
        if not self.call_started_at:
            return "00:00"
        total = int(time.monotonic() - self.call_started_at)
        return f"{total // 60:02d}:{total % 60:02d}"
