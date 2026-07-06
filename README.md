# NovaNode

AI token usage status CLI for **Claude**, **Codex**, and **Cursor**.

Ships as a single Bash executable exposed as `nn-usage`.

## Install

### Homebrew (macOS, recommended)

```sh
brew tap nachogonz/tap
brew install novanode
```

Or in one line:

```sh
brew install nachogonz/tap/novanode
```

### npm (global)

```sh
npm install -g novanode
```

Both channels install the same `nn-usage` command onto your `PATH`.

## Usage

```sh
nn-usage
```

## Requirements

- `bash`
- `python3` (used for the inline progress bar rendering)
- macOS or Linux

## Release flow

Releases are driven by git tags. To cut a new version:

```sh
npm version patch   # or minor / major — updates package.json + creates git tag
git push
git push --tags
```

The `release.yml` workflow publishes to npm on tag push. After the tag lands
on GitHub, update the Homebrew formula in
[`nachogonz/homebrew-tap`](https://github.com/nachogonz/homebrew-tap) with the
new `url` and `sha256`:

```sh
curl -L https://github.com/nachogonz/novanode/archive/refs/tags/vX.Y.Z.tar.gz \
  | shasum -a 256
```

## License

MIT — see [LICENSE](./LICENSE).
