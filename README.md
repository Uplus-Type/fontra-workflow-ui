# Fontra Workflow UI

A graphical **Workflow view** for [Fontra](https://fontra.xyz), to be built
as a Fontra extension (plug-in): a step stack, schema-generated inspectors
for each action, and a per-step font preview, round-tripping to the YAML
that `fontra-workflow` already runs.

**Status: early.** The Python package has its first piece: the **action
catalog** (a JSON schema for every `fontra-workflow` action, generated from
the installed actions) and **recipe validation**. The view itself is not
written yet; the repo also holds the thinking and the clickable mockup.

## The package

```sh
pip install -e path/to/fontra          # Fontra from source, 2026.10.2 or later
pip install -e ".[dev]"                # this repo
```

```sh
fontra-workflow-ui list-actions               # every installed action, with its arguments
fontra-workflow-ui list-actions --json        # the catalog, with a JSON schema per action
fontra-workflow-ui validate recipe.yaml       # check a recipe without running it
```

Nothing in the catalog is written by hand per action. It is read from
Fontra's action registry, with the actions of every installed package
(`fontra.workflow.actions` entry points, so fontra-compile's when it is
installed), and each action's arguments come from the fields of its
dataclass: type, default, required or not, enumerations. When Fontra adds an
action or renames an argument, the catalog follows. Descriptions come from an
action's docstring, or else from
[`descriptions.yaml`](src/fontra_workflow_ui/descriptions.yaml); a test fails
when an installed action or argument has no description, or when the file
describes one that no longer exists.

From Python:

```python
import yaml
from fontra_workflow_ui.introspect import buildCatalog
from fontra_workflow_ui.validate import RecipePolicy, validateRecipe

check = validateRecipe(yaml.safe_load(text), catalog=buildCatalog())
for error in check.errors:
    print(error)  # steps[2] (filter: scale), argument 'scaleFactor': expected a number, got 'abc'
print(check.variables)  # the {substitutions} the recipe uses
```

A `RecipePolicy` lets a runner refuse actions or arguments that name files
or folders (`"format": "path"` in the schema), for recipes run on a shared
server.

Tests: `pytest` (they need Fontra importable; fontra-compile is optional).

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

The code (the `fontra_workflow_ui` package and its tests) is under the
[GNU General Public License v3](LICENSE), like Fontra. The documents in
`docs/`, this README's background sections and the original mockup
(`mockup.html`) stay under [CC BY 4.0](LICENSE-docs), as in the repo they came
from.
