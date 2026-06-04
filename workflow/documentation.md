# Fontra Workflow — Comprehensive Documentation (Draft)

*Draft user documentation, written against fontra commit `e86dc88` and fontra-compile `main` (June 2026). Intended as a starting point for the official docs — feedback welcome. Everything described here was verified against the source; behavior notes marked ⚠ are caveats worth confirming with the core team.*

---

## 1. Overview

**Fontra Workflow** is a command-line tool for processing font sources in repeatable, declarative pipelines. You describe *what* should happen to a font in a YAML file — read, filter, merge, write — and Workflow executes it:

```yaml
# minimal.yaml
steps:
  - input: fontra-read
    source: MyFont.designspace
  - filter: decompose-composites
  - output: fontra-write
    destination: MyFont-decomposed.fontra
```

```console
$ fontra-workflow minimal.yaml --output-dir build
```

Use it for: format conversion, subsetting, designspace surgery (dropping/trimming/renaming axes), instance extraction, merging fonts, generating feature code from kerning or anchors, production QA gates, and — via the fontra-compile plugin — compiling binaries with fontmake, fontc, or Fontra's own VARC compiler.

Workflow operates on the same font object model as the Fontra editor. Anything Fontra can open (.designspace, .ufo, .ttf, .otf, .woff, .woff2, .ttx, .fontra, .glyphs/.glyphspackage) is a valid pipeline input. (Note: .glyphs support is built into Fontra Pak; in a bare `pip install fontra` CLI environment it comes from the `fontra-glyphs` package.)

---

## 2. Installation and the command line

Workflow ships with fontra itself; installing fontra gives you the `fontra-workflow` command (alongside `fontra` and `fontra-copy`).

```console
$ pip install fontra            # or: install from source
$ fontra-workflow --help
```

### CLI reference

```
fontra-workflow [options] CONFIG [CONFIG ...]
```

| Option | Default | Description |
|---|---|---|
| `CONFIG` (positional, 1+) | — | One or more YAML or JSON config files. Multiple configs are **chained**: the end point of each feeds the next as input. |
| `--output-dir PATH` | current dir | Folder for all outputs. Must exist. |
| `--substitute key:value` | — | Add a key/value pair to the substitution table (repeatable). Values are parsed as YAML, so `count:3` arrives as an int. |
| `--continue-on-error` | off | If reading/processing a glyph fails, log the error and skip the glyph instead of aborting. |
| `--logging-level LEVEL` | `WARNING` | Verbosity for stdout (`DEBUG` … `CRITICAL`). |
| `--log-file PATH` | — | Capture action log activity to a file. |
| `--log-file-logging-level LEVEL` | `WARNING` | Verbosity for the log file. |

Relative paths inside a config (e.g. `source:`, `glyphNamesFile:`) are resolved **relative to the config file's location**, not the working directory. Output `destination:` paths are resolved against `--output-dir`.

---

## 3. Concepts

### 3.1 The font stream

A pipeline carries a *font stream*: a complete font seen through Fontra's backend protocol — glyphs, axes, sources, kerning, features, font info, cmap, custom data. Every step consumes a stream and presents a stream.

### 3.2 Five step types

| Keyword | Role |
|---|---|
| `input:` *action* | Open a font and **merge** it into the current stream |
| `filter:` *action* | Transform the current stream |
| `output:` *action* | Write the current stream; the stream continues **unchanged** after the output |
| `fork:` | Branch: nested steps see a copy of the stream; the main stream is unaffected |
| `fork-merge:` | Branch, then merge the branch's result back into the main stream |

`fork:` and `fork-merge:` take no action name and no arguments — only nested `steps:`. (Writing `fork: something` is an error.)

### 3.3 Lazy, pull-based execution

Workflow does not process fonts eagerly. Internally, every filter *is* a font backend wrapping its input; setting up a pipeline just stacks these backends. When an output runs, it **pulls** data through the whole chain, glyph by glyph, asynchronously.

Practical consequences:

- Only data an output actually requests gets processed. If an output writes 100 glyphs, only those 100 (plus dependencies) flow through the filters.
- A glyph may be pulled **more than once** (e.g. by two outputs, or by a filter that needs to inspect many glyphs, like `decompose-composites` resolving nested components). If your pipeline is expensive, insert a cache: `memory-cache` (RAM) or `disk-cache` (temp files, for very large fonts).
- Step order matters in the obvious way: each filter sees the stream as transformed by everything above it.

### 3.4 Nesting: `steps:` inside a step

Any step can carry nested `steps:`. The meaning depends on the parent:

- **Under `input:`** — the nested steps process the *incoming* font **before** it is merged into the main stream. Use this to clean up or subset a font as it enters.
- **Under `filter:`** — the nested steps continue the sub-pipeline after that filter (rarely needed; equivalent to listing them at the same level).
- **Under `output:`** — the nested steps apply **only to that output**. This is the idiomatic way to make per-output variations without forking:

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace

  - output: fontra-write          # full font
    destination: Full.fontra

  - output: fontra-write          # subset, only for this output
    destination: Basic.fontra
    steps:
      - filter: subset-glyphs
        glyphNamesFile: basic-set.txt
```

### 3.5 Merging semantics

When an `input` (or `fork-merge`) merges font B into current stream A, the merger applies these rules (warnings are logged where it matters):

- **Glyphs**: B wins; a warning is logged for glyphs present in both (suppressed for `fork-merge`).
- **cmap**: union; on code point conflict B's mapping wins; conflicts within one font are warned about.
- **Font info**: field-by-field union, B wins.
- **Axes**: same-name axes are merged — ranges are unioned (min of mins, max of maxes), discrete values are unioned; default values and mappings *must* match (logged as errors otherwise). Axes only in A are appended. If both fonts define cross-axis (avar-2) mappings, B's are taken.
- **Font sources**: matched by designspace location; line metrics and custom data merged with B winning per key.
- **Kerning**: A's kerning is first subsetted to the glyphs A still owns; group names are disambiguated; tables are merged across the union of sources.
- **Features**: merged with ufomerge (FEA only; other feature languages produce a warning and B is used).
- **Units per em**: B's; a warning if they differ.

### 3.6 Substitutions (templating)

Configs may contain `{key}` placeholders in any string value, filled from `--substitute key:value`:

```yaml
steps:
  - input: fontra-read
    source: "{family}.designspace"
  - output: fontra-write
    destination: "{family}-{flavor}.fontra"
```

```console
$ fontra-workflow template.yaml --substitute family:Spectral --substitute flavor:subset
```

If a string consists of *exactly* one placeholder (`"{count}"`), the substituted value keeps its YAML type (number, bool, list…) — so substitutions can feed non-string arguments.

### 3.7 Chaining configs

`fontra-workflow a.yaml b.yaml` runs `a.yaml`, then feeds its resulting stream into `b.yaml` as the initial input. This lets you keep, say, a shared "cleanup" pipeline separate from per-product pipelines.

### 3.8 YAML niceties

Plain YAML features work as expected: comments, multi-line strings, and **YAML anchors** for reusing argument blocks across steps.

---

## 4. Action reference

Arguments map 1:1 to the action's parameters; unknown arguments are errors. "—" means no arguments.

### 4.1 Inputs

| Action | Arguments | Description |
|---|---|---|
| `fontra-read` | `source` (path, required) | Open any font Fontra has a backend for. Format chosen by file extension. |

### 4.2 Outputs

| Action | Arguments | Description |
|---|---|---|
| `fontra-write` | `destination` (path, required) | Write the stream to any writable backend (.fontra, .ufo, .designspace, …). Format chosen by extension. |

### 4.3 Filters — axes & designspace

| Action | Arguments | Description |
|---|---|---|
| `rename-axes` | `axes` (dict) | Rename axes and/or change tag/label: `axes: { Weight: { name: wght } }`. Updates all source locations. |
| `adjust-axes` | `axes` (dict), `remapSources` (bool, `true`) | Change min/default/max of axes; optionally remap source locations to the new ranges (piecewise-linear). |
| `trim-axes` | `axes` (dict of `minValue`/`maxValue`) | Restrict axis ranges; sources outside the range are re-instantiated at the boundary; kerning is re-interpolated; conditional-substitution rules are rewritten. |
| `subset-axes` | `axisNames` (list), `dropAxisNames` (list) | Keep (or drop) axes; sources off the default location of dropped axes are removed. |
| `instantiate` | `location` (dict) | Pin axes to fixed values and remove them — extract a partial or full static instance. Kerning re-interpolated. |
| `move-default-location` | `newDefaultUserLocation` (dict) | Move the designspace default to a new location, synthesizing sources where needed. |
| `drop-axis-mappings` | `axes` (list, optional = all) | Remove avar-style axis mappings, converting locations to source space. |
| `drop-cross-axis-mappings` | — | Remove avar-2 cross-axis mappings. |
| `set-location-base` / `clear-location-base` | — | Convert glyph source locations to/from references to font sources (`locationBase`). |
| `drop-unused-sources-and-layers` | — | Remove inactive sources and orphaned layers per glyph. |

### 4.4 Filters — glyphs & outlines

| Action | Arguments | Description |
|---|---|---|
| `decompose-composites` | `onlyVariableComposites` (bool, `false`) | Fully decompose components into outlines, synthesizing the extra sources needed so variation is preserved across the whole designspace. |
| `shallow-decompose-composites` | `glyphNames` (list), `componentGlyphNames` (list) | Decompose one level, optionally only specific composites/components. |
| `trim-variable-glyphs` | `moveDefaultBehavior` (`none`/`empty`/`any`, default `any`) | Trim glyph-level axes to the ranges actually used by referencing composites. |
| `remove-overlaps` | — | Boolean union on every layer's path. |
| `convert-to-quadratics` | `maximumError` (float), `reverseDirection` (bool, `false`) | Cubic → quadratic (cu2qu), interpolation-compatible across sources. |
| `round-coordinates` | six bools, all `true`: `roundPathCoordinates`, `roundComponentOrigins`, `roundGlyphMetrics`, `roundAnchors`, `roundLineMetrics`, `roundKerning` | Round everything (or selectively). |
| `scale` | `scaleFactor` (float, required), `scaleFontMetrics` (bool, `true`), `scaleKerning` (bool, `true`) | Scale outlines, metrics, kerning — including units-per-em when `scaleFontMetrics` is on (i.e. UPM conversion). |
| `drop-shapes` | `dropPath`, `dropComponents`, `dropAnchors`, `dropGuidelines` (bools, all `true`) | Empty out glyph content selectively (e.g. produce a metrics-only skeleton). |
| `propagate-anchors` | — | Copy anchors from components up into composites, with glyphsLib-compatible ligature-anchor heuristics. |
| `drop-background-images` | — | Remove background images from all layers. |
| `set-vertical-glyph-metrics` | `verticalOrigin` (int), `yAdvance` (int) | Fill in *missing* vertical metrics. |
| `set-vertical-glyph-metrics-from-anchors` | `tsbAnchorName` (`"TSB_DEFAULT"`), `bsbAnchorName` (`"BSB_DEFAULT"`) | Derive vertical metrics from anchors. |

### 4.5 Filters — subsetting

All three subsetters share `layoutHandling`: `"subset"` (subset the feature code), `"closure"` (let layout rules *extend* the glyph set), or `"ignore"`. All perform component closure (a kept composite keeps its base glyphs), kerning/group subsetting, and conditional-substitution handling.

| Action | Arguments | Description |
|---|---|---|
| `subset-glyphs` | `glyphNames` (list), `glyphNamesFile` (path), `dropGlyphNames` (list), `dropGlyphNamesFile` (path), `layoutHandling` (default `subset`) | Keep or drop an explicit glyph set (lists and files are combined). |
| `drop-unreachable-glyphs` | `keepNotdef` (bool, `true`), `layoutHandling` (default `closure`) | Keep only encoded glyphs plus everything reachable through layout rules and components. |
| `subset-by-development-status` | `statuses` (list of ints, required), `sourceSelectBehavior` (`default`/`any`/`all`), `layoutHandling` | Keep glyphs whose status (e.g. "finished") matches — status lives in `fontra.development.status` custom data. |

### 4.6 Filters — features & kerning

| Action | Arguments | Description |
|---|---|---|
| `add-features` | `featureFile` (path, required) | Merge a FEA file into the font's features (ufomerge). |
| `drop-features` | — | Remove all feature code. |
| `generate-kern-feature` | `dropKern` (bool, `true`) | Compile the font's kerning data into a FEA `kern` feature with **variable scalars**; optionally drop the source kerning afterwards. |
| `generate-vkrn-feature` | `dropVkrn` (bool, `true`) | Same for vertical kerning (`vkrn`). |
| `generate-palt-vpal-feature` | `languageSystems` (list of [script, language]) | Generate `palt`/`vpal` proportional-spacing adjustments from LSB/RSB/TSB/BSB anchors — variable, across the designspace. |

### 4.7 Filters — font data & QA

| Action | Arguments | Description |
|---|---|---|
| `set-font-info` | `fontInfo` (dict, required) | Override font info fields (unknown names are reported). |
| `amend-cmap` | `cmap` (dict, `"U+0041": A` style or int keys), `cmapFile` (path) | Add/override/remove (map to nothing) code point assignments. |
| `check-interpolation` | `fixWithFallback` (bool, `false`) | Verify every glyph interpolates; either fail or replace broken glyphs with their default-source-only version. |
| `drop-font-sources-and-kerning` | — | Remove font-level sources and kerning. |
| `memory-cache` / `disk-cache` | — | Cache the stream at this point (RAM / temp dir). |

### 4.8 Plugin actions: fontra-compile

Installing **fontra-compile** (`pip install fontra-compile`) registers three binary-compiling outputs via the `fontra.workflow.actions` entry point:

| Action | Arguments | Description |
|---|---|---|
| `compile-fontmake` | `destination` (required), `options` (dict of fontmake CLI flags), `setOverlapSimpleFlag` (bool), `addMinimalGaspTable` (bool), `ufoTempDir` (path) | Round-trips through a temporary UFO/designspace and runs **fontmake**. `.ttf` destination → TrueType (variable if the font has axes); otherwise CFF/CFF2. Synthesizes instances from axis value labels when none are defined. |
| `compile-fontc` | same as `compile-fontmake` | Same staging, compiled with Google's Rust **fontc**. |
| `compile-varc` | `destination` (required), `subroutinize` (bool, `true`), `useExtendedGvar` (bool, `false`) | Fontra's own experimental compiler producing **VARC** (variable composites) fonts; CFF2 when destination is `.otf`. |

---

## 5. Recipes

**Convert anything to anything**

```yaml
steps:
  - input: fontra-read
    source: MyFont.glyphs        # built into Fontra Pak; bare CLI: pip install fontra-glyphs
  - output: fontra-write
    destination: MyFont.designspace
```

**Webfont subset from a variable font**

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace
  - filter: subset-glyphs
    glyphNamesFile: latin-basic.txt
    layoutHandling: subset
  - filter: drop-unreachable-glyphs
  - output: compile-fontmake
    destination: MyFont-Subset.ttf
```

**Extract two static instances and the full VF in one run**

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace

  - output: compile-fontmake
    destination: MyFont-VF.ttf

  - output: compile-fontmake
    destination: MyFont-Regular.ttf
    steps:
      - filter: instantiate
        location: { Weight: 400 }

  - output: compile-fontmake
    destination: MyFont-Bold.ttf
    steps:
      - filter: instantiate
        location: { Weight: 700 }
```

**Narrow a family (drop an axis, trim another)**

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace
  - filter: subset-axes
    dropAxisNames: [Optical]
  - filter: trim-axes
    axes: { Weight: { minValue: 300, maxValue: 700 } }
  - output: fontra-write
    destination: MyFont-Slim.designspace
```

**Merge a symbols font into a text family (cleaning it on the way in)**

```yaml
steps:
  - input: fontra-read
    source: Text.designspace
  - input: fontra-read
    source: Symbols.ufo
    steps:                        # applied to Symbols before merging
      - filter: scale
        scaleFactor: 0.5
        scaleFontMetrics: false
      - filter: drop-features
  - output: fontra-write
    destination: Merged.fontra
```

**Ship only finished glyphs, with an interpolation gate**

```yaml
steps:
  - input: fontra-read
    source: Project.fontra
  - filter: subset-by-development-status
    statuses: [4]                 # "finished"
  - filter: check-interpolation
  - filter: decompose-composites
  - filter: remove-overlaps
  - filter: round-coordinates
  - output: compile-fontmake
    destination: Project.ttf
```

**Variable kerning as feature code, then binaries via two compilers**

```yaml
steps:
  - input: fontra-read
    source: MyFont.designspace
  - filter: memory-cache
  - filter: generate-kern-feature
  - fork:
    steps:
      - output: compile-fontmake
        destination: MyFont-fontmake.ttf
  - output: compile-fontc
    destination: MyFont-fontc.ttf
```

**UPM conversion**

```yaml
steps:
  - input: fontra-read
    source: MyFont-1000upm.ufo
  - filter: scale
    scaleFactor: 2.048            # 1000 → 2048
  - filter: round-coordinates
  - output: fontra-write
    destination: MyFont-2048upm.ufo
```

**Templated batch (one config, many families)**

```console
$ for f in Sans Serif Mono; do
    fontra-workflow build.yaml --substitute family:$f --output-dir build
  done
```

---

## 6. Live previews: workflows in the editor

fontra registers a `yaml` filesystem backend that wraps Workflow. Opening a workflow config in Fontra (e.g. `fontra --launch filesystem myworkflow.yaml`, or via Fontra Pak) shows the **result of the pipeline as a font, live, in the editor** — read-only. Edit the YAML, reopen, inspect. This makes the editor a debugger for pipelines.

⚠ Outputs in the config are not triggered by the editor; only the stream's end point is browsed.

---

## 7. Writing your own actions

Actions are plain Python classes registered by name. Filters usually subclass `BaseFilter` and override one or more `process*` hooks — **return modified copies, never mutate**:

```python
# my_actions.py
from dataclasses import dataclass
from fontra.workflow.actions import registerFilterAction
from fontra.workflow.actions.base import BaseFilter

@registerFilterAction("prefix-glyph-names")   # name used in YAML
@dataclass(kw_only=True)
class PrefixGlyphNames(BaseFilter):
    prefix: str = "x."                        # ← YAML argument, with default

    async def processGlyphMap(self, glyphMap):
        return {self.prefix + name: cp for name, cp in glyphMap.items()}
```

Available hooks: `processGlyph`, `processGlyphMap`, `processAxes`, `processSources`, `processKerning`, `processFeatures`, `processFontInfo`, `processUnitsPerEm`, `processCustomData`, `processConditionalSubstitutions`, `processBackgroundImage`, `processGlyphInfos` — or override the `get*` methods directly for full control (as the subsetters do). Useful helpers on `BaseFilter`: `self.validatedInput` (the upstream backend), `self.fontInstancer` (interpolation machinery), cached `self.inputAxes` / `self.inputGlyphMap` / `self.inputSources` / `self.inputKerning`.

Inputs implement `prepare()` (an async context manager yielding a readable backend); outputs implement `connect(input)` yielding a processor with `async process(outputDir, *, continueOnError)`. Register with `registerInputAction` / `registerOutputAction`.

Ship actions in a package via the entry-point group:

```toml
[project.entry-points."fontra.workflow.actions"]
my_actions = "my_package.my_actions"
```

The module is imported when any workflow starts; the decorators do the registration. (This is exactly how fontra-compile adds its three outputs.)

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `no action type keyword found in step` | A step dict lacks `input`/`filter`/`output`/`fork`/`fork-merge` — check indentation. |
| `fork 'value' needs to be empty` | You wrote `fork: name`; use bare `fork:` with nested `steps:`. |
| `No action found named '…'` | Typo, or the plugin providing the action isn't installed in this environment. |
| Unexpected keyword argument | Argument name doesn't match the action's parameters (arguments are strict). |
| `Merger: Glyph 'x' exists in both fonts` | Expected on overlapping merges — the later input wins. Subset one side if not intended. |
| `Merger: Axis default values should be the same` | Merging fonts whose shared axes disagree on default/mapping; align them first (`adjust-axes`). |
| Slow pipeline | Filters re-pull glyphs; add `memory-cache` (or `disk-cache` for huge fonts) after expensive steps. |
| One bad glyph kills the run | Use `--continue-on-error` and read the log; pair with `check-interpolation` to control *where* it fails. |

Logging: `--logging-level INFO` shows per-action activity; `--log-file` plus `--log-file-logging-level DEBUG` captures a full trace for CI artifacts.
