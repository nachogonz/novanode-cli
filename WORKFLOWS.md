# nnop workflows

Two-sided team sync for client project secrets. Owner sets up once,
teammates get a working `.env` in seconds. No secret ever leaves 1Password
unless someone explicitly asks for a plaintext `.env`.

- [Owner: first-time setup for a client project](#owner-first-time-setup)
- [Teammate: joining an existing project](#teammate-joining-an-existing-project)
- [Everyday updates](#everyday-updates)
- [What is / isn't stored](#security-model)
- [Cheat sheet](#cheat-sheet)

---

## Owner: first-time setup

You're the first person to wire the repo. You have the current `.env`
locally and want the team to share the same secrets going forward.

```sh
cd ~/work/client-x
nnop
```

You see the connection hub. The directory has no `.novanode.yml` yet:

```
  nn-op  ·  Secrets & envs
  ✗ not signed in
  Secrets stay in 1Password · nn-op is a wrapper around `op`
  no .novanode.yml in this tree
  ────────────────────────────────────────────────────

  ▸ Not a NovaNode project yet
    Choose a starting point below.

    G · Initialise this directory
      Creates .novanode.yml and links a 1Password vault
    List existing projects

    Sign in to 1Password
    Status / doctor

    Quit

  ↑↓ nav · Enter · G init · Q quit
```

Press **G**. `nn-op project init` walks you through:

```
Vault name       [client-x]          <- becomes the 1Password vault
Apps             [web api]           <- one item per app-env in the vault
Envs             [dev staging prod]
Default app      [web]
Default env      [dev]
```

That writes three files:

```
.novanode.yml       # project → vault mapping, apps, envs   (commit this)
.novanode.local     # your current app/env selection        (git-ignored)
.env.template       # every var re-expressed as op:// refs  (safe to commit)
```

You return to the dashboard, now signed in and pointing at the new
vault. Import your existing `.env`:

```
[press I]
Import path [./.env]: ↵
✓ Imported 12 secrets into client-x / web-dev
```

Commit the shape of the project (no secrets):

```sh
git add .novanode.yml .env.template .gitignore
git commit -m "wire NovaNode secret sync"
git push
```

Now invite teammates to the `client-x` vault in the 1Password web UI.
That's it — the team can bootstrap themselves.

---

## Teammate: joining an existing project

You cloned a repo that already has `.novanode.yml`. You've been invited
to the `client-x` vault. You want a working `.env`.

```sh
git clone git@github.com:acme/client-x.git
cd client-x
nnop
```

You see the dashboard already scoped to `client-x / web · dev`. If you're
not signed in to 1Password yet, press **L** to launch sign-in. Once
signed in, the fields appear:

```
  nn-op  ·  Secrets & envs
  ✓ 1Password · you@acme.com
  Secrets stay in 1Password · nn-op is a wrapper around `op`
  client-x / web · dev  (.)
  ─────────────────────────────────────────────────

  ▸ web-dev
    12 field(s) · Enter reveals · C copies to clipboard

    DATABASE_URL              ••••••••••••••••
    STRIPE_SECRET_KEY         ••••••••••••••••
    NEXT_PUBLIC_APP_URL       https://dev.client-x.com
    ...

    A · Add secret
    I · Import a .env file
  ▸ P · Pull to .env  (⚠ plaintext on disk)
    T · Write .env.template with op:// refs
    ...

  ↑↓ nav · Enter · A add · P pull · I import · T template · C copy · R refresh · Q quit
```

Press **P**. That runs `nn-op env pull --materialize`:

```
This will write plaintext to ./.env — continue? [y/N]: y
✓ Wrote .env (12 secrets)
```

Now `npm run dev` (or whatever your dev command is) works with the shared
secrets. `.env` is git-ignored — never commit it.

If you'd rather not materialise plaintext at all, use `op run` instead:

```sh
nn-op run -- npm run dev
```

This injects the secrets into the child process environment for the
lifetime of that command and never touches disk.

---

## Everyday updates

### Adding a new secret

From any teammate's machine:

```
[in the dashboard, press A]
Variable name: SENDGRID_API_KEY
Value (hidden): •••••••••••••••••••••••
✓ Saved SENDGRID_API_KEY to client-x / web-dev
```

Everyone else on the team runs `nnop`, presses **P**, and their `.env`
picks up the new value.

### Copying a secret out of the dashboard

Highlight the row with ↑/↓, press **C**. It's on your clipboard — paste it
into a dashboard, a chat, or wherever you need. No plaintext file created.

### Switching between environments

```
[press U in the dashboard]
Which app?  [web]
Which env?  [staging]
```

That updates `.novanode.local` (your per-clone state) and the dashboard
now reflects `web · staging`. Press **P** to pull the staging `.env`.

### Copying an env between apps or projects

```
nn-op env copy web dev api dev            # web/dev → api/dev, same project
nn-op env copy client-x/web/prod backup-x/web/prod   # cross-project
```

---

## Security model

- `nn-op` **never** writes a secret to disk unless you explicitly run
  `env pull --materialize`. Add / Import stream the value into `op` over
  stdin and forget it.
- OAuth tokens, session cookies, and the Keychain entry all belong to the
  official 1Password app and CLI. `nn-op` does not read, cache, or copy
  them.
- `.novanode.local` records `{app, env}` selection only — no secrets. It
  is git-ignored by default.
- `.env.template` is safe to commit: every value is an `op://` reference
  that 1Password resolves at runtime.
- Clipboard copy uses `pbcopy` / `xclip` / `wl-copy` directly. No
  intermediate file.
- `nn-op env pull --materialize` is the one command that writes plaintext
  to disk; the UI labels the action ⚠ plaintext so it's hard to trigger
  by accident.
- Revoking someone: remove them from the 1Password vault. Their local
  `.env` (if they materialised one) keeps working until they rotate
  values — plan for rotation, not deletion, when someone leaves.

---

## Cheat sheet

Hotkey inside the `nnop` dashboard:

| Key      | Action                                                     |
| -------- | ---------------------------------------------------------- |
| `↑` `↓`  | Move the highlight                                         |
| `Enter`  | Reveal the highlighted secret (or run the highlighted row) |
| `A`      | Add a secret (KEY + hidden VALUE)                          |
| `I`      | Import a `.env` file into the current vault item           |
| `P`      | Pull the current env to a plaintext `.env` (⚠)             |
| `T`      | Write a `.env.template` full of `op://` references         |
| `U`      | Switch which app/env is current                            |
| `C`      | Copy the highlighted secret to the clipboard               |
| `R`      | Refresh                                                    |
| `Q` `Esc`| Quit                                                       |

Direct commands (useful in scripts and CI):

```sh
nnop                                    # interactive dashboard
nn-op project init                      # first-time setup
nn-op env import ./.env                 # push .env → vault
nn-op env pull --materialize            # vault → .env
nn-op env template --out .env.template  # write op:// template
nn-op env use web staging               # switch app + env
nn-op env set STRIPE_SECRET_KEY         # add/update a single secret
nn-op run -- npm run dev                # inject secrets into a child process
```
