import time

import config as nnconfig
from pbx import PBX
from phone import Phone


def run_test_call(cfg=None, target=None, wait=25):
    cfg = cfg or nnconfig.load_config()
    target = target or cfg["phone"].get("test_dial", "3000")
    print(f"\n  NovaNode · baresip → nn-pbx → LiveKit test ({target})\n")

    pbx = PBX(cfg)
    phone = Phone(cfg)
    if pbx.core_version() == "n/a":
        print("  ✗ PBX is unreachable; run `nn pbx doctor`.")
        return 1
    context = "\n".join(pbx.contexts("from-nn")).lower()
    if target not in context or "livekit" not in context:
        print(f"  ✗ [from-nn] does not expose the expected {target} LiveKit route.")
        return 1
    if not phone.start() or phone._simulated:
        print(f"  ✗ {phone.last_event}")
        print("    Enable baresip ctrl_tcp on Fedora; simulation cannot pass this test.")
        return 1

    before = {channel.get("unique_id") for channel in pbx.channels()}
    try:
        if not phone.dial(target):
            print(f"  ✗ {phone.last_event}")
            return 1
        print(f"  • {phone.last_event}")
        deadline = time.monotonic() + wait
        observed = []
        while time.monotonic() < deadline:
            current = pbx.channels()
            observed = [channel for channel in current if channel.get("unique_id") not in before]
            livekit = [
                channel
                for channel in observed
                if "livekit" in channel.get("channel", "").lower()
                or "livekit" in channel.get("context", "").lower()
                or "livekit" in channel.get("data", "").lower()
            ]
            origins = [channel for channel in observed if target == channel.get("exten") and channel not in livekit]
            live_bridges = {channel.get("bridge") for channel in livekit if channel.get("bridge")}
            origin_bridges = {channel.get("bridge") for channel in origins if channel.get("bridge")}
            shared_bridges = live_bridges & origin_bridges
            if (
                livekit
                and origins
                and shared_bridges
                and all(channel.get("state", "").lower() == "up" for channel in livekit + origins)
            ):
                print("  ✓ New correlated channels reached Up state.")
                print(f"  ✓ Shared bridge IDs: {', '.join(sorted(shared_bridges))}")
                print("  • Hold 5 seconds for packet capture / human audio confirmation.")
                time.sleep(5)
                print("\n  PASS: signalling and bridge established.")
                print("  Audio quality still requires RTP capture or operator confirmation.\n")
                return 0
            time.sleep(1)
        print("  ✗ No correlated LiveKit bridge reached Up state.")
        if observed:
            for channel in observed:
                print(f"    {channel['channel']} {channel['state']} {channel['context']}/{channel['exten']}")
        return 2
    finally:
        phone.hangup()
        phone.stop()
