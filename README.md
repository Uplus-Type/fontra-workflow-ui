# Fontra Workflow UI

A graphical **Workflow view** for [Fontra](https://fontra.xyz), to be built
as a Fontra extension (plug-in): a step stack, schema-generated inspectors
for each action, and a per-step font preview, round-tripping to the YAML
that `fontra-workflow` already runs.

**Status: concept.** Nothing runs yet. This repo holds the thinking, the
clickable mockup, and will hold the extension's code.

## Start here

- [`mockup.html`](mockup.html): the **clickable mockup**. Select steps, drag the
  Weight slider, move the preview pin, toggle the YAML drawer, hit Run.
  Static, no engine behind it. Published at
  `https://fontra.github.io/fontra-workflow-ui/mockup.html` once GitHub Pages
  is enabled on this repo (*Settings → Pages → Deploy from branch, `main`, `/`*).
- [`docs/ux.md`](docs/ux.md): **why it looks that way**: a layered answer to
  "does Workflow need a UI?", from invisible fixes to the Workflow view.

## Background documents

| Document | Contents |
|---|---|
| [docs/workflow-analysis.md](docs/workflow-analysis.md) | A close reading of `src/fontra/workflow`: the pull-based pipeline engine, its action vocabulary, and why it's the project's best-kept secret |
| [docs/workflow-documentation.md](docs/workflow-documentation.md) | Draft user documentation for `fontra-workflow`: CLI reference, concepts, complete action reference, recipes, writing your own actions, troubleshooting |
| [docs/extensions.md](docs/extensions.md) | Proposed extensions to the engine: new actions, engine features (introspection, `--watch`, persistent cache…), ecosystem plays, with an impact/effort prioritization |

These were written in June 2026 against `fontra/fontra@e86dc88` and
`fontra-compile@main`; **⚠** marks a claim to verify against the current
source. They came out of the [fontra-docs-redesign](https://github.com/fontra/fontra-docs-redesign)
working session and were moved here, with their history, when the Workflow
view became a project of its own. The user-facing Workflow documentation
(recipes, action reference, writing actions) lives in the docs site.

## How the extension will plug in

Fontra loads editor plug-ins from a folder of static files with a
`plugin.json` manifest (see *Writing your own plug-ins* in the Fontra docs);
server-side actions are Python packages declaring `fontra.workflow.actions`
entry points. The Workflow view will be an editor plug-in talking to the
`fontra-workflow` engine through the server.

## License

CC BY 4.0 for the documents and the mockup, as in the repo they came from.
