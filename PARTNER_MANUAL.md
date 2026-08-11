# NovaNode Telephony DevKit: Partner Manual

This manual explains how to install, configure, operate, test, and publish the NovaNode `nn` terminal toolkit.

## 1. What This Tool Controls

NovaNode is an adapter-based TUI for the current telephony lab:

```text
Operator workstation
        |
        | SSH
        v
Fedora 44 host (192.168.0.23)
  - KVM/libvirt
  - baresip softphone
  - PipeWire netmic/netagent audio bridge
        |
        | libvirt network
        v
nn-pbx VM (192.168.122.223)
  - Debian 13
  - Asterisk 22.10.1
  - chan_pjsip
        |
        | outbound TLS/SRTP
        v
LiveKit Cloud SIP → room → bbva-lab-local agent
```

The known-good test path is:

```text
baresip → nn-pbx:5061/TLS → extension 3000
        → PJSIP/+15555550100@livekit
        → LiveKit SIP inbound trunk
        → dispatch rule → room → bbva-lab-local agent
```

## 2. Security Model

The toolkit preserves the lab security boundaries:

- Network SIP uses TLS on `5061/tcp`.
- Local test SIP uses `127.0.0.1:5060/udp` only.
- LiveKit uses the outbound-only TLS transport on `5062`.
- RTP stays in `20000-20999/udp` and is anchored on Asterisk.
- AMI stays on `127.0.0.1:5038` and is reached through SSH forwarding.
- ARI and the Asterisk HTTP interface remain disabled.
- The setup command does not change PJSIP endpoints, transports, RTP, LiveKit, or `[from-nn]`.
- Credentials are never included in the npm package or Git repository.

## 3. Prerequisites

On the machine running `nn`:

- Python 3.9 or newer
- OpenSSH client
- A terminal at least `60x18`
- SSH key access to Fedora and the `nn-pbx` VM

Check them with:

```bash
python3 --version
ssh -V
```

For npm installation, Node.js 18 or newer is also required:

```bash
node --version
npm --version
```

## 4. Recommended SSH Configuration

The PBX VM is behind the Fedora libvirt network. From Kali, macOS, or another operator workstation, define SSH aliases in `~/.ssh/config`:

```sshconfig
Host nn-fedora
  HostName 192.168.0.23
  User YOUR_FEDORA_USER
  IdentityFile ~/.ssh/id_ed25519

Host nn-pbx
  HostName 192.168.122.223
  User root
  ProxyJump nn-fedora
  IdentityFile ~/.ssh/id_ed25519
```

Replace `YOUR_FEDORA_USER` with the real Fedora account. Test both routes:

```bash
ssh nn-fedora true
ssh nn-pbx 'asterisk -rx "core show version"'
```

If the PBX SSH user is not root, it needs passwordless permission for the limited setup commands used by `nn`:

```text
asterisk, cat, cp, install, stat, test
```

Do not place SSH passwords in the project.

## 5. Prepare baresip on Fedora

The phone tab controls the already-running Fedora baresip process through its loopback TCP controller. In the baresip config, enable:

```text
module_app              ctrl_tcp.so
ctrl_tcp_listen         127.0.0.1:4444
```

Restart baresip using the same method currently used by the lab, then verify:

```bash
pgrep -a baresip
ss -ltn | grep 4444
```

Port `4444` must remain loopback-only. `nn` reaches it through an SSH tunnel.

The existing baresip account remains the source of SIP credentials. NovaNode does not rewrite that account or copy its password into the package.

## 6. Run Directly From the Repository

From the repository root, do not use `sudo`:

```bash
./bin/nn --help
./bin/nn pbx setup
./bin/nn pbx detect
./bin/nn pbx doctor
./bin/nn pbx
```

To use `nn` without the `./bin/` prefix for the current shell:

```bash
export PATH="$PWD/bin:$PATH"
nn pbx
```

Using `sudo` is discouraged because it changes `$HOME`, SSH keys, and the location of NovaNode configuration and secrets.

## 7. Install From npm

After version `1.1.0` is published:

```bash
npm install -g @nakdev-npm/novanode
nn --version
nn pbx --help
```

The package installs four commands:

```text
nn          primary command
nn-pbx      alias for nn pbx
nn-usage    standalone Claude/Codex dashboard
novanode    compatibility alias for nn
```

## 8. First-Time PBX Setup

Run:

```bash
nn pbx setup
```

Recommended answers for this lab:

| Prompt | Value |
|---|---|
| PBX name | `nn-pbx` |
| PBX host | `192.168.122.223` |
| PBX SSH host | `nn-pbx` |
| PBX SSH user | `root` or the approved admin user |
| Phone extension | `1001` |
| SIP username | `1001` |
| Preferred codec | `g722` |
| Fedora baresip SSH host | `nn-fedora` |
| Fedora SSH user | Fedora account name |

Setup performs this sequence:

1. Detects Asterisk, PJSIP transports, endpoints, registrations, and modules.
2. Shows a proposal before changing anything.
3. Requests confirmation.
4. Backs up `/etc/asterisk/manager.conf` to `manager.conf.novanode-bak`.
5. Enables AMI on `127.0.0.1:5038` only.
6. Adds `#include manager_novanode.conf`.
7. Creates a restricted, read-only `[novanode-tui]` AMI account.
8. Reloads the Asterisk manager subsystem.
9. Stores the local AMI secret in `~/.config/novanode/secrets.json` with mode `0600`.

Local non-secret configuration is stored in:

```text
~/.config/novanode/pbx.json
```

To avoid storing the AMI secret on disk, export it before running `nn`:

```bash
export NOVANODE_AMI_SECRET='value-from-the-approved-secret-store'
```

## 9. Detect and Diagnose

### Topology detection

```bash
nn pbx detect
```

Expected discoveries:

- Asterisk 22.10.1
- `res_pjsip` and `chan_pjsip`
- `transport-tls` on `5061`
- `transport-udp-local` on `5060`
- `transport-tls-livekit` on `5062`
- endpoints `phone1`, `phone2`, `agent`, and `livekit`

### Six-section doctor

```bash
nn pbx doctor
```

Doctor checks:

1. Fedora/KVM and Asterisk stack accessibility
2. PJSIP transports, endpoints, codecs, RFC4733, and SDES-SRTP policy
3. Outbound LiveKit registration
4. Network-facing SIP TLS and documented RTP range
5. Restricted AMI authentication through SSH
6. The `3000 → LiveKit` dialplan path

A nonzero exit status means at least one required check failed.

## 10. Using the TUI

Open the main PBX view:

```bash
nn pbx
```

Navigation:

| Key | Action |
|---|---|
| `Tab` | Next tab |
| `1`–`6` | Jump to a tab |
| `r` | Refresh current PBX data |
| `F5` | Force refresh |
| `F4` | Open the SSH tunnel to loopback AMI |
| `q` | Quit |

Tabs:

- `USAGE`: Claude Code and Codex CLI plan windows
- `PBX`: version, uptime, transports, endpoints, and channels
- `PHONE`: baresip controller and keypad
- `CALLS`: active Asterisk channels
- `TRUNKS`: outbound registration state
- `DEBUG`: adapter status, AMI events, and `[from-nn]` readiness

## 11. Making Calls

Open the phone directly:

```bash
nn pbx phone
```

Phone keys:

| Key | Action |
|---|---|
| `0`–`9`, `*`, `#`, `+` | Enter destination |
| `Enter` or `c` | Dial |
| `h` | Hang up |
| `a` | Answer an incoming call |
| `d` | Decline an incoming call |
| `m` | Toggle microphone mute |
| `s` | Toggle the TUI audio monitor indicator |
| Backspace | Delete a digit |
| Escape | Clear destination |

Important lab destinations:

```text
1001  softphone 1
1002  softphone 2
2000  agent endpoint
3000  LiveKit room/AI agent path
*43   diagnostic extension
*44   diagnostic extension
*65   diagnostic extension
```

For the main end-to-end test, enter `3000` and press Enter.

## 12. Automated Test Call

Run:

```bash
nn pbx test-call
```

The test refuses to pass in simulation mode. It requires:

- real baresip registration
- the `[from-nn]` `3000` route
- a new originating channel
- a new LiveKit PJSIP leg
- both channels in `Up`
- a shared Asterisk bridge ID

After signalling and bridge validation, confirm audio manually or with an RTP capture. The command deliberately does not claim audio quality from signalling alone.

## 13. Usage Dashboard

Standalone commands:

```bash
nn-usage
nn-usage --summary-tsv
nn-usage --json
```

The dashboard queries Claude Code and Codex CLI only.

## 14. Troubleshooting

### `./bin/nn: permission denied`

From the repository root:

```bash
chmod +x bin/nn bin/nn-pbx bin/nn-usage bin/novanode
```

Do not prefix the normal command with `sudo`.

### PBX is unreachable

```bash
ssh nn-pbx 'asterisk -rx "core show version"'
ssh nn-pbx 'asterisk -rx "pjsip show transports"'
```

Check the `ProxyJump` route if running outside Fedora.

### AMI authentication fails

On the PBX:

```bash
ssh nn-pbx 'grep -n "enabled\|bindaddr\|novanode" /etc/asterisk/manager.conf /etc/asterisk/manager_novanode.conf'
ssh nn-pbx 'asterisk -rx "manager show users"'
```

Then rerun:

```bash
nn pbx setup
nn pbx doctor
```

### Phone says baresip control is unavailable

```bash
ssh nn-fedora 'pgrep -a baresip'
ssh nn-fedora 'ss -ltn | grep 4444'
```

Verify `ctrl_tcp.so` is loaded and bound to `127.0.0.1:4444`.

### LiveKit is unregistered

```bash
ssh nn-pbx 'asterisk -rx "pjsip show registrations"'
ssh nn-pbx 'asterisk -rx "pjsip show endpoint livekit"'
```

Confirm TLS trust, LiveKit domain, digest authentication, and outbound transport `5062`.

### Call connects but has no audio

Check:

- Fedora PipeWire `netmic` and `netagent` sources
- the raw-TCP audio bridge
- nftables `20000-20999/udp`
- SDES-SRTP negotiation
- `direct_media=no`
- LiveKit SIP codec pinned to ulaw

Do not enable Opus on the LiveKit SIP trunk.

### TUI drawing problems

Use a terminal of at least `60x18`, with a valid `$TERM`:

```bash
echo "$TERM"
printf '\e[8;32;110t'
```

## 15. Publishing Version 1.1.0 to npm

The npm registry currently has `@nakdev-npm/novanode@1.0.11`. This workspace is `1.1.0`, so `1.1.0` is the next intended release.

If npm reports `EACCES` under `~/.npm`, do not publish with `sudo`. Repair the user cache or temporarily select a user-owned cache:

```bash
sudo chown -R "$(id -u):$(id -g)" "$HOME/.npm"
# or, without changing the existing cache:
export npm_config_cache="${TMPDIR:-/tmp}/npm-cache-$USER"
```

### Recommended: GitHub Actions release

The repository workflow publishes when a `v*` tag is pushed and verifies that the tag matches `package.json`.

#### One-time npm/GitHub setup

1. Sign in to npm and confirm access to the scope:

   ```bash
   npm login
   npm whoami
   npm access list packages @nakdev-npm
   ```

2. Create a granular npm automation token with read/write access to `@nakdev-npm/novanode`.
3. Add it to the GitHub repository as the Actions secret `NPM_TOKEN`.

Keep the automation token only in GitHub Secrets. Never place it in a project `.npmrc`, source file, commit, screenshot, or chat. A user-level `~/.npmrc` created by `npm login` is acceptable only for the direct local fallback.

#### Verify the package

From the repository root:

```bash
npm run check
npm pack --dry-run
npm publish --dry-run --access public
```

Confirm that the package contains `bin/nn`, `bin/nn-pbx`, `bin/nn-usage`, `bin/lib`, `README.md`, and this manual.

#### Commit and tag 1.1.0

Review the worktree and commit the release normally:

```bash
git status
git diff --check
git add README.md PARTNER_MANUAL.md package.json .github/workflows/release.yml bin
git commit -m "release telephony devkit 1.1.0"
git push origin main
git tag v1.1.0
git push origin v1.1.0
```

The tag push starts `.github/workflows/release.yml`, which:

1. checks out the tagged commit
2. verifies `v1.1.0` equals package version `1.1.0`
3. runs the package checks
4. publishes the public npm package
5. creates a GitHub release

Watch it with:

```bash
gh run watch
```

Verify publication:

```bash
npm view @nakdev-npm/novanode version
npm install -g @nakdev-npm/novanode@1.1.0
nn --version
```

### Direct npm publication fallback

Use this only if GitHub Actions is intentionally not being used:

```bash
npm login
npm run check
npm publish --access public
```

If you publish directly, do not then push `v1.1.0` while the release workflow is enabled, because the workflow will attempt to publish the same immutable npm version again.

### Future versions

After `1.1.0`, start from a clean branch and let npm create the version commit and tag:

```bash
npm version patch   # or minor / major
git push origin main --follow-tags
```

The GitHub Action will publish the version represented by that tag.

## 16. Release Checklist

- [ ] No credentials or lab secrets in `git diff`
- [ ] `npm run check` passes
- [ ] `npm pack --dry-run` lists only intended files
- [ ] `nn pbx detect` succeeds against the live lab
- [ ] `nn pbx doctor` reaches ready state
- [ ] Manual call to `3000` works both ways
- [ ] `nn pbx test-call` validates the shared LiveKit bridge
- [ ] Package version matches Git tag
- [ ] `NPM_TOKEN` exists only in GitHub Secrets
- [ ] Published `nn --version` matches the release
