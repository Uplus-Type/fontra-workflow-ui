# Fontra Workflow

*A reading of `src/fontra/workflow` (commit `e86dc88`). June 2026.*

---

## 1. What it is

Fontra Workflow is a **declarative, composable font-processing pipeline engine**, driven by YAML (or JSON) configuration and run from the command line:

```
fontra-workflow myworkflow.yaml --output-dir build
```

Conceptually: what fontTools/fontmake scripts do imperatively, Workflow does declaratively — a "Makefile for designspaces". It is the production counterpart to the editor, built on the exact same font object model (`ReadableFontBackend`, `VariableGlyph`, `Axes`, `Kerning`, …).

## 2. The execution model (the elegant bit)

A workflow is a list of **steps**. Five step types exist:

| Step type | Role |
|---|---|
| `input` | Opens a font source; **merges** into the current stream (`FontBackendMerger`) |
| `filter` | Transforms the current stream |
| `output` | Writes the current stream somewhere |
| `fork:` | Branches off — nested steps see the current stream, main stream unaffected |
| `fork-merge:` | Branches, then merges the branch result back into the main stream |

The key design decision: **every filter is itself a `ReadableFontBackend`** wrapping its input. Nothing is processed eagerly. Outputs *pull* data through the chain — lazily, glyph by glyph, fully async. A pipeline is a stack of font-shaped objects, each answering `getGlyph()`, `getAxes()`, `getKerning()`… by transforming its input's answer.

Practical consequences:

- Only glyphs that are actually written get processed.
- Pipelines compose arbitrarily: any filter's output is a valid input for any other.
- Writing a new filter is trivial: subclass `BaseFilter`, override one or more no-op hooks (`processGlyph`, `processAxes`, `processKerning`, `processFeatures`, `processGlyphMap`, …). Often ten lines.
- `memory-cache` / `disk-cache` filters exist because laziness means repeated pulls — caching is itself just another filter in the chain.

## 3. Config anatomy

Each step is a dict whose key is the step type and whose value is the action name; remaining keys are the action's arguments (matching the action dataclass fields). `steps:` nests.

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace

  - filter: decompose-composites
    onlyVariableComposites: true

  - filter: subset-glyphs
    glyphNamesFile: glyphset.txt

  - filter: convert-to-quadratics

  - fork:
    steps:
      - filter: instantiate
        location: { Weight: 700 }
      - output: fontra-write
        destination: MyFont-Bold.ufo

  - output: fontra-write
    destination: MyFont-subset.fontra
```

CLI affordances (from `command.py`):

- `--output-dir` for all outputs
- `--substitute key:value` — configs support `{key}` string substitution (templated workflows)
- multiple config files on one command line are **chained** (output of one feeds the next)
- `--continue-on-error` — log failing glyphs, keep going (CJK-scale pragmatism)
- proper logging controls (`--logging-level`, `--log-file`)

A detail worth knowing: `pyproject.toml` registers a `yaml` filesystem backend (`WorkflowBackend`) — a workflow config can be opened *in the Fontra editor itself* as a virtual font, i.e. a live preview of a pipeline's result.

## 4. Action catalog (complete, at this commit)

**Input** — `fontra-read`. **Output** — `fontra-write`. (Format chosen by file extension; any registered backend works, so "fontra-write" writes .ufo, .fontra, .designspace…)

**Filters**, grouped by module:

| Module | Actions |
|---|---|
| `base.py` | `memory-cache`, `disk-cache` |
| `axes.py` | `rename-axes`, `drop-unused-sources-and-layers`, `drop-axis-mappings`, `adjust-axes`, `subset-axes`, `move-default-location`, `instantiate`, `trim-axes`, `clear-location-base`, `set-location-base`, `drop-cross-axis-mappings` |
| `glyph.py` | `scale`, `decompose-composites`, `shallow-decompose-composites`, `trim-variable-glyphs`, `drop-shapes`, `round-coordinates`, `set-vertical-glyph-metrics`, `set-vertical-glyph-metrics-from-anchors`, `drop-background-images`, `convert-to-quadratics`, `remove-overlaps`, `propagate-anchors` |
| `subset.py` | `subset-glyphs`, `drop-unreachable-glyphs`, `subset-by-development-status` |
| `misc.py` | `set-font-info`, `amend-cmap`, `check-interpolation`, `drop-font-sources-and-kerning` |
| `features.py` | `add-features`, `drop-features`, `generate-kern-feature`, `generate-vkrn-feature`, `generate-palt-vpal-feature` |

What makes these more than toys: each action handles the **hard secondary consequences**, not just glyph outlines. Examples:

- Subsetting performs component closure, feature closure (via real FEA subsetting), kerning/group subsetting, and conditional-substitution closure.
- `instantiate` / `trim-axes` / `subset-axes` re-interpolate kerning at the new source locations using a `DiscreteVariationModel`, and correctly rewrite conditional substitution rules.
- `subset-by-development-status` filters on `fontra.development.status` customData — workflow-aware production (ship only "finished" glyphs).
- `generate-kern-feature` emits FEA with **variable scalars** — variable kerning as feature code.
- `propagate-anchors` replicates glyphsLib's ligature-anchor heuristics for .glyphs compatibility.

The CJK heritage is visible throughout: `palt`/`vpal` generation from LSB/RSB/TSB/BSB anchors, vertical metrics handling, vkrn, development-status subsetting, disk caching for very large fonts.

## 5. Extensibility

Third-party actions register through the `fontra.workflow.actions` entry-point group — the same plugin mechanism as storage backends. Plugins (e.g. fontra-compile for binary compilation) can add their own inputs/filters/outputs, and the registration API is three decorators: `registerInputAction`, `registerFilterAction`, `registerOutputAction`.

## 6. Assessment

Strengths: a genuinely clean architecture (pull-based backend chaining), a complete-enough action vocabulary for real production, templating + chaining for reuse, and the editor/pipeline sharing one data model.

Weakness: **it is publicly invisible.** No page on docs.fontra.xyz mentions it; the only documentation is the source code. For a tool whose audience (font engineers, production people) is exactly the audience that evaluates software by reading docs, this is the largest gap between capability and discoverability in the whole project. (See the [documentation strategy](../strategy/documentation-strategy.md).)

---

*Open questions for feedback: (a) is Workflow considered stable/public API, or internal tooling that happens to ship? (b) is the intended audience foundry production staff, or also advanced designers? (c) how does it relate to fontra-compile and fontc plans — is Workflow meant to grow into the full build system?*
