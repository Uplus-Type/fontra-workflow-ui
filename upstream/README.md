# Patches for fontra/fontra

Changes proposed to Fontra itself, kept here as `git format-patch` files
until they are opened as pull requests. Nothing in this package depends on
them: when one is merged upstream, the matching code here can go.

| Patch | What | Base |
|---|---|---|
| [fontra-workflow-list-actions.patch](fontra-workflow-list-actions.patch) | `fontra-workflow list-actions [--json]`: every registered action with its arguments (one file, `src/fontra/workflow/command.py`, plus its test) | `fontra/fontra@81fd957`; applies as is on `6e04a57` |

To try one in a Fontra checkout: `git am path/to/file.patch`.
