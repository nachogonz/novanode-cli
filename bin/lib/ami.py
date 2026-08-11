import socket
import threading
import time
from collections import deque


class AMIError(Exception):
    pass


class AMIClient:
    def __init__(self, host, port, user, secret, timeout=5):
        self.host = host
        self.port = int(port)
        self.user = user
        self.secret = secret
        self.timeout = timeout
        self.sock = None
        self.buffer = b""
        self.events = deque(maxlen=500)
        self._lock = threading.Lock()
        self._reader = None
        self._stop = threading.Event()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        resp = self._action_raw(
            {"Action": "Login", "Username": self.user, "Secret": self.secret, "Events": "on"}
        )
        if not any(b.get("Response") == "Success" for b in resp):
            raise AMIError(self._error_text(resp))

    def _error_text(self, blocks):
        for b in blocks:
            msg = b.get("Message")
            if msg:
                return msg
        return "AMI login failed"

    def _read_blocks(self, deadline):
        blocks = []
        while time.monotonic() < deadline:
            try:
                self.sock.settimeout(max(0.05, deadline - time.monotonic()))
                data = self.sock.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            self.buffer += data
            while True:
                idx = self.buffer.find(b"\r\n\r\n")
                if idx == -1:
                    break
                block = self.buffer[:idx]
                self.buffer = self.buffer[idx + 4:]
                try:
                    text = block.decode("utf-8", "replace")
                except Exception:
                    continue
                headers = {}
                for line in text.split("\r\n"):
                    if not line:
                        continue
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    if key in headers:
                        existing = headers[key]
                        headers[key] = existing + "\n" + value
                    else:
                        headers[key] = value
                if headers.get("Response") == "Success" and headers.get("ActionID"):
                    blocks.append(headers)
                    return blocks
                if headers.get("Event"):
                    with self._lock:
                        self.events.append(headers)
                    continue
                blocks.append(headers)
                if headers.get("Response"):
                    return blocks
        return blocks

    def _action_raw(self, params):
        if not self.sock:
            raise AMIError("not connected")
        params = dict(params)
        if any("\r" in str(value) or "\n" in str(value) for value in params.values()):
            raise AMIError("AMI values may not contain newlines")
        params["ActionID"] = f"nn-{time.monotonic_ns()}"
        payload = "".join(f"{k}: {v}\r\n" for k, v in params.items()) + "\r\n"
        self.sock.sendall(payload.encode("utf-8"))
        deadline = time.monotonic() + self.timeout
        return self._read_blocks(deadline)

    def action(self, action, **params):
        blocks = self._action_raw(dict(params, Action=action))
        for b in blocks:
            if b.get("Response") == "Error":
                raise AMIError(b.get("Message") or f"{action} failed")
        if not blocks:
            raise AMIError(f"no response to {action}")
        return blocks

    def command(self, cmd):
        blocks = self._action_raw({"Action": "Command", "Command": cmd})
        out = []
        for b in blocks:
            if b.get("Response") == "Error":
                raise AMIError(b.get("Message") or "command failed")
            out.extend(b.get("Output", "").splitlines())
        return out

    def listen(self):
        def loop():
            while not self._stop.is_set():
                deadline = time.monotonic() + 0.5
                try:
                    self._read_blocks(deadline)
                except Exception:
                    break

        self._stop.clear()
        self._reader = threading.Thread(target=loop, daemon=True)
        self._reader.start()

    def drain_events(self):
        with self._lock:
            out = list(self.events)
            self.events.clear()
        return out

    def close(self):
        self._stop.set()
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
