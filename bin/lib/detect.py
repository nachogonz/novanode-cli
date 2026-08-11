import config as nnconfig
from pbx import PBX


def run_detect(cfg=None, quiet=False):
    cfg = cfg or nnconfig.load_config()
    pbx = PBX(cfg)
    p = cfg["pbx"]

    if not p.get("ssh_host") and not p.get("via_ssh"):
        print()
        print("  nn pbx detect requires pbx.ssh_host — run `nn pbx setup` first.")
        print()
        return 1

    def show(title, value):
        if quiet:
            return
        print(f"  {title:<18} {value}")

    if not quiet:
        print()
        print("  NovaNode · live box detection")
        print(f"  {nnconfig.pbx_label(cfg)}")
        print()

    version = pbx.core_version()
    show("core version", version or "n/a")
    if version == "n/a":
        if not quiet:
            print("\n  Detection failed: Asterisk is unreachable over SSH.\n")
        return 1

    modules = ["res_pjsip.so", "res_pjsip_registrar.so", "res_pjsip_authenticator_digest.so", "chan_pjsip.so"]
    loaded = [m for m in modules if pbx.module_loaded(m)]
    show("pjsip modules", f"{len(loaded)}/{len(modules)} loaded")

    transp = pbx.transports()
    if transp and not quiet:
        print("  transports:")
        for t in transp:
            print(f"      {t['type']:<6} {t['bind']}")
    else:
        show("transports", "none returned")

    eps = pbx.endpoints_long()
    if eps and not quiet:
        print("  endpoints:")
        for e in eps:
            print(f"      {e['name']:<12} user={e['username'] or '—':<10} {e['state'] or ''}")
    else:
        show("endpoints", "none returned")

    regs = pbx.registrations()
    if regs and not quiet:
        print("  registrations:")
        for r in regs:
            print(f"      {r['obj']:<16} {r['state']}")
    else:
        show("registrations", "none returned")

    try:
        ctx = pbx.contexts("from-nn")
        show("dialplan [from-nn]", f"{len(ctx)} lines")
    except Exception:
        show("dialplan [from-nn]", "n/a")

    if not quiet:
        print()
        print("  Next: nn pbx doctor · nn pbx setup · nn pbx phone")
        print()
    return 0
