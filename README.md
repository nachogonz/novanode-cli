# NovaNode Telephony DevKit

See [PARTNER_MANUAL.md](./PARTNER_MANUAL.md) for the complete lab setup, operation, troubleshooting, and npm release guide.

`nn` is a terminal development station for the NovaNode Asterisk lab. It combines PBX status, a baresip controller, calls, trunks, AMI events, diagnostics, automated test calls, and Claude/Codex usage in one TUI.

The old NovaNode chat has been removed. The usage dashboard contains Claude Code and Codex CLI only.

## Run From This Repo

No installation or `sudo` is required:

```sh
./bin/nn --help
./bin/nn pbx detect
./bin/nn pbx doctor
./bin/nn pbx
./bin/nn pbx phone
```

Run the first operational lab test with:

```sh
./bin/nn pbx test-call
```

This exercises the established route: baresip → nn-pbx TLS `5061` → extension `3000` → LiveKit SIP → room → `bbva-lab-local` agent.

To make `nn` available in the current shell:

```sh
export PATH="$PWD/bin:$PATH"
nn pbx doctor
```

Or link it into a user-owned bin directory:

```sh
mkdir -p "$HOME/.local/bin"
ln -sf "$PWD/bin/nn" "$HOME/.local/bin/nn"
export PATH="$HOME/.local/bin:$PATH"
```

## Commands

```text
nn                       Open the PBX TUI
nn usage                 Open the usage tab
nn pbx                   Open the PBX tab
nn pbx setup             Detect, propose, back up, confirm, and configure AMI
nn pbx detect            Inspect Asterisk/PJSIP over SSH
nn pbx doctor            Validate the six lab sections
nn pbx phone             Control baresip on Fedora
nn pbx test-call         Test extension 3000 through LiveKit
nn calls                 Show active channels
nn trunks                Show outbound registrations
nn debug                 Show AMI/debug state
```

`nn-pbx` is a convenience alias for `nn pbx`. `novanode` remains only as a compatibility alias to `nn`; it no longer contains chat functionality.

## Lab Model

- Fedora Workstation hosts KVM and baresip.
- The `nn-pbx` Debian VM runs Asterisk 22.10.1 with `chan_pjsip`.
- Network SIP enters on TLS `5061`; UDP `5060` is loopback-only.
- LiveKit uses outbound TLS transport `5062` and an ulaw SIP leg.
- RTP is anchored on Asterisk in `20000-20999/udp` with SDES-SRTP.
- Local endpoints are `1001`, `1002`, and `2000`; `3000` routes to LiveKit.
- AMI is restricted to `127.0.0.1:5038` and reached through an SSH tunnel.
- ARI remains disabled.

## Setup Safety

`nn pbx setup` detects before changing anything. It shows a proposal, requires confirmation, backs up `manager.conf` to `manager.conf.novanode-bak`, and writes a separate `manager_novanode.conf` include owned by NovaNode.

It does not modify PJSIP transports, endpoints, the `[from-nn]` dialplan, RTP settings, or LiveKit configuration.

Secrets are never stored in this repository. Local credentials use `~/.config/novanode/secrets.json` with mode `0600`, or these environment variables:

```sh
export NOVANODE_AMI_SECRET='...'
```

The baresip phone adapter expects a running baresip process on Fedora with `ctrl_tcp` listening on loopback port `4444`. Configure its Fedora SSH host during `nn pbx setup`.

## Usage Dashboard

```sh
./bin/nn-usage
./bin/nn-usage --summary-tsv
./bin/nn-usage --json
```

Only Claude Code and Codex CLI are queried.

## Requirements

- Python 3.9+
- OpenSSH client and key-based access to the lab hosts
- A terminal with curses support
- baresip with loopback-only `ctrl_tcp` for real phone controls

## Install

```sh
npm install -g @nakdev-npm/novanode
```

Homebrew releases also install `nn`, `nn-pbx`, `nn-usage`, and the `novanode` compatibility alias.

## License

MIT. See [LICENSE](./LICENSE).
