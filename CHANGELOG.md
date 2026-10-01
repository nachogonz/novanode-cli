# Changelog

## 1.3.2

- Fix the `op`/`nn-op` login UI hanging when NovaNode's globally installed `op` shortcut appears before the official 1Password CLI in `PATH`. Internal calls now resolve the real 1Password executable instead of launching NovaNode recursively.
- Stop the “Open op CLI session” action from relaunching the NovaNode shortcut.
