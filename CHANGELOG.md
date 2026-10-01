# Changelog

## 1.3.3

- Fix account registration with the current 1Password CLI: the Add Account screen now hands the terminal to `op account add --signin --raw` for the Secret Key and password prompts instead of passing an unsupported `--secret-key` flag. Accounts already configured in the CLI go straight to sign-in, and other setup errors remain visible before returning to the dashboard.
- Clarify authentication states in the Secrets UI: show configured account details and sign-in as the primary action, while new devices offer a separate Connect Account flow with an internet requirement.

## 1.3.2

- Fix the `op`/`nn-op` login UI hanging when NovaNode's globally installed `op` shortcut appears before the official 1Password CLI in `PATH`. Internal calls now resolve the real 1Password executable instead of launching NovaNode recursively.
- Stop the “Open op CLI session” action from relaunching the NovaNode shortcut.
