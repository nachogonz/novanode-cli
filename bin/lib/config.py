import json
import os
import stat
import tempfile

CONFIG_PATH = os.path.expanduser("~/.config/novanode/pbx.json")
SECRETS_PATH = os.path.expanduser("~/.config/novanode/secrets.json")

DEFAULTS = {
    "pbx": {
        "name": "nn-pbx",
        "host": "192.168.122.223",
        "ami_host": "127.0.0.1",
        "ami_port": 5038,
        "ami_user": "novanode-tui",
        "ssh_host": "",
        "ssh_user": "root",
        "ssh_sudo": True,
        "via_ssh": False,
    },
    "sip": {
        "transport_tls": "0.0.0.0:5061",
        "transport_local": "127.0.0.1:5060",
        "transport_livekit": "0.0.0.0:5062",
        "codecs": ["g722", "ulaw"],
        "dtmf": "rfc4733",
        "media_encryption": "sdes",
        "direct_media": "no",
        "rtp_timeout": 30,
        "rtp_start": 20000,
        "rtp_end": 20999,
    },
    "endpoints": {
        "names": ["phone1", "phone2", "agent", "livekit"],
        "locals": ["1001", "1002"],
        "agent": "2000",
        "livekit": "3000",
        "livekit_outbound": "PJSIP/+15555550100@livekit",
    },
    "livekit": {
        "enabled": True,
        "mode": "outbound",
        "domain": "*.sip.livekit.cloud",
        "trunk": "nn-pbx-lab-inbound",
        "agent": "bbva-lab-local",
    },
    "phone": {
        "extension": "1001",
        "display_name": "NOVA PHONE",
        "sip_user": "1001",
        "codec": "g722",
        "transport": "tls",
        "backend": "baresip-ssh",
        "ssh_host": "192.168.0.23",
        "ssh_user": "",
        "control_host": "127.0.0.1",
        "control_port": 4444,
        "test_dial": "3000",
    },
}


def load_config(path=None):
    path = path or CONFIG_PATH
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(path) as fh:
            user = json.load(fh)
    except (OSError, ValueError):
        user = {}
    if not isinstance(user, dict):
        user = {}
    for section, values in user.items():
        if section in cfg and isinstance(values, dict):
            cfg[section].update(values)
        elif isinstance(values, dict):
            cfg[section] = values
    return cfg


def save_config(cfg, path=None):
    path = path or CONFIG_PATH
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    data = json.loads(json.dumps(cfg))
    data.get("phone", {}).pop("sip_secret", None)
    fd, tmp = tempfile.mkstemp(prefix=".pbx-", dir=parent, text=True)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def has_config(path=None):
    return os.path.isfile(path or CONFIG_PATH)


def pbx_label(cfg):
    host = cfg["pbx"]["host"]
    name = cfg["pbx"].get("name", "PBX")
    return f"{name} · {host}" if host else name


# ── secrets (never in git) ──────────────────────────────────────────
def load_secrets(path=None):
    path = path or SECRETS_PATH
    try:
        with open(path) as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_secrets(secrets, path=None):
    path = path or SECRETS_PATH
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".secrets-", dir=parent, text=True)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w") as fh:
            json.dump(secrets, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def ami_secret(cfg=None):
    cfg = cfg or load_config()
    env = os.environ.get("NOVANODE_AMI_SECRET", "")
    if env:
        return env
    return load_secrets().get("ami_secret", "")

