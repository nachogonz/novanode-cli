import socket

import config as nnconfig
from pbx import PBX


class Check:
    def __init__(self, section, name, ok, detail, notes=None):
        self.section = section
        self.name = name
        self.ok = ok
        self.detail = detail
        self.notes = notes or []


def tcp_open(host, port, timeout=3):
    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
        return True
    except OSError:
        return False


def run_doctor(cfg=None, quiet=False):
    cfg = cfg or nnconfig.load_config()
    pbx = PBX(cfg)
    checks = []

    version = pbx.core_version()
    checks.append(Check(
        "1 · Fedora + Asterisk",
        "Asterisk core",
        version != "n/a",
        version if version != "n/a" else "unreachable over SSH",
        ["PBX VM is Debian 13 behind the Fedora KVM host"],
    ))
    pjsip_loaded = pbx.module_loaded("res_pjsip.so") and pbx.module_loaded("chan_pjsip.so")
    checks.append(Check(
        "1 · Fedora + Asterisk",
        "chan_pjsip stack",
        pjsip_loaded,
        "res_pjsip + chan_pjsip running" if pjsip_loaded else "required modules not confirmed",
    ))

    transports = pbx.transports()
    transport_text = " ".join(f"{item['name']} {item['type']} {item['bind']}" for item in transports).lower()
    expected = (("transport-tls", "5061"), ("transport-udp-local", "5060"), ("transport-tls-livekit", "5062"))
    transports_ok = all(name in transport_text and port in transport_text for name, port in expected)
    checks.append(Check(
        "2 · SIP configuration",
        "PJSIP transports",
        transports_ok,
        ", ".join(f"{item['name']}={item['bind']}" for item in transports) or "none returned",
    ))

    endpoints = pbx.endpoints_long()
    endpoint_names = {item["name"] for item in endpoints}
    required_names = set(cfg["endpoints"].get("names", []))
    endpoints_ok = required_names.issubset(endpoint_names)
    checks.append(Check(
        "2 · SIP configuration",
        "PJSIP endpoints",
        endpoints_ok,
        ", ".join(sorted(endpoint_names)) or "none returned",
        ["expected phone1, phone2, agent, livekit"],
    ))

    try:
        endpoint_detail = "\n".join(pbx.runner.run("pjsip show endpoint phone1")).lower()
    except Exception:
        endpoint_detail = ""
    media_tokens = ("g722", "ulaw", "rfc4733", "sdes")
    media_ok = all(token in endpoint_detail for token in media_tokens)
    checks.append(Check(
        "2 · SIP configuration",
        "media policy",
        media_ok,
        "g722 + ulaw · RFC4733 · SDES-SRTP" if media_ok else "could not confirm endpoint media settings",
        ["LiveKit SIP leg must remain ulaw; Opus belongs inside the room"],
    ))

    registrations = pbx.registrations()
    registration_text = " ".join(item["obj"] + " " + item["state"] for item in registrations).lower()
    livekit_registered = any(
        "livekit" in item["obj"].lower() and item["state"].split()[0].lower() == "registered"
        for item in registrations
    )
    checks.append(Check(
        "3 · LiveKit integration",
        "outbound LiveKit trunk",
        livekit_registered,
        registration_text or "no registration returned",
        ["outbound-only is expected; inbound from-livekit is intentionally refused"],
    ))

    tls_open = tcp_open(cfg["pbx"]["host"], 5061)
    checks.append(Check(
        "4 · Network",
        "network-facing SIP TLS",
        tls_open,
        f"{cfg['pbx']['host']}:5061 " + ("reachable" if tls_open else "filtered/unreachable"),
        [f"RTP policy {cfg['sip']['rtp_start']}-{cfg['sip']['rtp_end']}/udp; validate UDP from a real call/capture"],
    ))

    secret = nnconfig.ami_secret(cfg)
    ami_ok = bool(secret) and pbx.connect_ami(secret)
    checks.append(Check(
        "5 · Asterisk management",
        "restricted loopback AMI",
        ami_ok,
        "authenticated through SSH tunnel" if ami_ok else (pbx.last_error or "AMI secret/account not configured"),
        ["127.0.0.1:5038 only; no ARI/HTTP exposure"],
    ))
    pbx.close()

    context = "\n".join(pbx.contexts("from-nn")).lower()
    ready = "3000" in context and "livekit" in context and endpoints_ok and livekit_registered
    checks.append(Check(
        "6 · Ready for a test call",
        "3000 → LiveKit agent",
        ready,
        "[from-nn] routes 3000 to the LiveKit trunk" if ready else "dialplan/trunk/endpoints not all confirmed",
        ["run `nn pbx test-call` once baresip ctrl_tcp is ready"],
    ))

    if not quiet:
        print_report(cfg, checks)
    return all(check.ok for check in checks)


def print_report(cfg, checks):
    print()
    print("  NovaNode PBX · doctor report")
    print(f"  {nnconfig.pbx_label(cfg)}")
    current = None
    for check in checks:
        if check.section != current:
            current = check.section
            print(f"\n  \033[1m{current}\033[0m")
        mark = "\033[38;5;82m✓\033[0m" if check.ok else "\033[38;5;196m✗\033[0m"
        print(f"  {mark} {check.name:<28} {check.detail}")
        for note in check.notes:
            print(f"      {note}")
    healthy = all(check.ok for check in checks)
    result = "\033[38;5;82mREADY FOR A TEST CALL\033[0m" if healthy else "\033[38;5;208mACTION REQUIRED\033[0m"
    print(f"\n  Result: {result}")
    print("  Commands: nn pbx detect · nn pbx setup · nn pbx phone · nn pbx test-call\n")
