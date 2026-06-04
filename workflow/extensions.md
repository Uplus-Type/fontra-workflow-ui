# Fontra Workflow — Proposed Extensions

*Companion to the [Workflow documentation](documentation.md). Each proposal states the gap, the idea, and a usage sketch. Grouped: new actions, engine features, ecosystem integrations. Prioritization at the end.*

---

## A. New actions

### A1. `rename-glyphs` — the most notable absence

There is no way to rename glyphs in a pipeline today, yet it's a universal production need (working names → production names, `uniXXXX` normalization, foundry conventions). Hard to do correctly by hand because renames must cascade through component references, kerning pairs and groups, feature code, and the glyph map — exactly the cross-cutting bookkeeping Workflow actions already excel at (cf. `rename-axes`).

```yaml
- filter: rename-glyphs
  nameMap: { a.alt01: a.ss01 }
  nameMapFile: production-names.txt    # two-column file
  # or: scheme: production            # AGL/uniXXXX-based automatic renaming
```

### A2. `generate-mark-feature` / `generate-mkmk-feature`

`generate-kern-feature` proves the pattern: data → FEA with variable scalars. Anchors are already first-class in the model and `propagate-anchors` exists, but mark positioning still requires external tooling. Generating variable `mark`/`mkmk` (and `curs` from entry/exit anchors) would make Workflow + fontra-compile a complete shaping pipeline for many scripts — and dovetails with the 2026 HarfBuzz shaping work.

```yaml
- filter: generate-mark-feature
- filter: generate-mkmk-feature
```

### A3. `subset-by-code-points` / `subset-by-glyphset`

`subset-glyphs` keys on glyph *names*; web and localization workflows think in *code points* and named glyph sets (Google Fonts glyphsets, `.nam` files, unicode ranges). A thin sibling would remove a recurring friction:

```yaml
- filter: subset-by-code-points
  ranges: ["U+0000-U+00FF", "U+20AC"]
  codePointsFile: latin-1.nam
```

### A4. `generate-instances` (batch instantiation)

`instantiate` produces one static instance per pipeline. Families ship dozens. A single action that fans out over the font's named instances (or axis value labels, as `compile-fontmake` already synthesizes) would collapse N configs into one step:

```yaml
- output: generate-instances
  destinationTemplate: "{familyName}-{styleName}.ufo"
  # instances: [...]               # optional explicit list; default: from font data
```

(Alternatively an engine-level `foreach` — see B4 — which is more general.)

### A5. `validate` + `report` — QA as a pipeline stage

`check-interpolation` is the seed of something bigger. A `validate` filter (configurable checks: open contours, path direction, duplicate unicodes, missing anchors against a per-script requirement list, zero-advance non-marks, component depth) plus a `report` *output* writing JSON/HTML would make Workflow a CI quality gate, not just a transformer:

```yaml
- filter: validate
  checks: [contours, unicodes, anchors]
  failFast: false
- output: report
  destination: qa-report.html
```

A `diff` input variant — compare the stream against a previous release and report changed glyphs/metrics/kerning — would serve regression review before releases.

### A6. `set-development-status`

The status data is consumed (`subset-by-development-status`) but cannot be *written* in a pipeline. Stamping statuses (e.g. mark everything in a glyph list as "finished" after review) closes the loop:

```yaml
- filter: set-development-status
  status: 4
  glyphNamesFile: reviewed.txt
```

### A7. `set-glyph-order`

`compile-fontmake` quietly invents a glyph order; making it explicit and reusable (a list or file, with a sensible default sort) benefits every output and gives diff-stable binaries.

### A8. Convenience: `scale-to-upm`

`scale` requires computing the factor by hand and rounding errors invite mistakes. `scale-to-upm: { unitsPerEm: 2048 }` says what you mean. Ten lines of code, disproportionate quality-of-life.

### A9. Plugin candidates (separate packages, like fontra-compile)

- `autohint` output wrapper (ttfautohint for TTF) after compile actions.
- `shape-test` filter: run HarfBuzz shaping regression tests (input text + expected glyph sequence) — natural once the editor's shaping lands; would make Fontra the first environment where shaping tests live next to the sources.
- `fontbakery` output: run Font Bakery profiles on freshly compiled binaries, one config from sources to QA'd fonts.

---

## B. Engine features

### B1. Introspection: `fontra-workflow list-actions`

Today the action vocabulary is discoverable only by reading source. A subcommand listing all registered actions (including plugin-provided ones) with their arguments, types, and defaults — generated from the dataclass fields — is cheap and doubles as always-current reference documentation:

```console
$ fontra-workflow list-actions --json   # machine-readable, feeds docs generation
```

### B2. Config validation and better errors

Arguments already fail on mismatch, but late (at step setup) and sometimes deep in a traceback. Generating a JSON Schema from the action dataclasses enables: upfront validation of the whole config with line numbers, editor autocomplete (YAML language servers consume JSON Schema), and `--dry-run` that prints the resolved pipeline tree without executing. The schema is derivable automatically — no maintenance burden.

### B3. `--watch` mode

`watchfiles` is already a fontra dependency (it powers the editor's auto-reload). `fontra-workflow --watch` re-running on source change turns Workflow into a live build server — pair it with the editor open on the output (or the `yaml` backend) and you get incremental production feedback while designing. Strong synergy with Fontra's "works alongside other editors" philosophy.

### B4. Parametrized steps: `foreach`

The substitution system is one-shot per run. A `foreach` step type would express matrix builds (instances, subsets, scripts) in one config:

```yaml
- foreach:
    values: { weight: [400, 700], width: [75, 100] }
    steps:
      - fork:
        steps:
          - filter: instantiate
            location: { Weight: "{weight}", Width: "{width}" }
          - output: compile-fontmake
            destination: "MyFont-{weight}-{width}.ttf"
```

This reuses the existing substitution machinery; semantically it's sugar for generated forks.

### B5. Concurrency

The model is async but pulls are effectively sequential per output. Two cheap wins: process outputs concurrently (`asyncio.gather` over `output.process()`), and batch glyph pulls within `copyFont`. The functional, copy-not-mutate filter design means parallelism is largely safe by construction.

### B6. Persistent, content-addressed cache

`disk-cache` lives and dies with the run. Keying the cache on (input content hash + pipeline-prefix hash) in a user cache dir gives **incremental builds**: re-running a 40k-glyph CJK pipeline after touching three glyphs reprocesses three glyphs. This is the feature that makes Workflow viable as the inner loop for very large projects, and aligns with the roadmap's "incremental compilation" ambition.

### B7. CI ergonomics

Deterministic exit codes (validation failed vs. glyph errors vs. config error), a `--strict` flag promoting warnings to failures, and an optional JSON log stream. Small, but the difference between "usable in CI" and "trusted in CI".

### B8. A documented, stable Python API

`Workflow(config=...)` + `endPoints()` is already a clean embedding API — `WorkflowBackend` proves it. Documenting it (and committing to its stability) lets foundries script pipelines from Python, mix Workflow into existing build systems, and write tests against pipelines. Cost: a docs page and discipline; the design work is done.

---

## C. Ecosystem integrations

### C1. Editor integration

The `yaml` backend already previews pipelines read-only. Next steps, in increasing ambition: a "Run workflow…" command in Fontra Pak (pick config, pick output dir, progress bar); pipeline visualization (the step tree rendered as a graph — the structure is pure data); and per-step preview (click a step, see the stream at that point — the lazy backend-stack makes this nearly free, since every step boundary *is* a browsable font).

### C2. An official GitHub Action

`fontra/setup-fontra-workflow` + a worked example repo: push to main → build VF + statics + webfont subsets → run report → attach artifacts to a release. Google Fonts onboarding and indie foundries both increasingly live in CI; being present there is adoption strategy, not just tooling. (Pairs with B7.)

### C3. Recipe registry

A `fontra/workflow-recipes` repo of curated, tested configs (the cookbook from the [Workflow documentation](documentation.md), grown by PRs). Each recipe is runnable against a small test font in CI, so recipes can't rot. Low-cost community on-ramp: contributing a YAML file is the easiest first contribution imaginable.

---

## D. Prioritization

| Proposal | Impact | Effort | Note |
|---|---|---|---|
| B1 list-actions / introspection | High | Low | Unlocks docs generation; do first |
| A8 scale-to-upm | Medium | Trivial | Quality of life |
| A1 rename-glyphs | High | Medium | Most-requested-shaped gap |
| A3 subset-by-code-points | High | Low | Webfont workflows |
| B2 schema validation + dry-run | High | Low-Med | Derived from dataclasses |
| C3 recipe registry | High | Low | Community + docs in one |
| B3 --watch | Medium | Low | Dependency already present |
| A5 validate + report | High | Medium-High | Positions Workflow as QA gate |
| A2 mark/mkmk generation | High | Medium-High | Completes the FEA-generation story |
| B4 foreach | Medium | Medium | Wait for real demand; A4 covers the common case |
| B6 persistent cache | High (CJK) | High | The big architectural investment |
| C1 editor integration | High | Medium-High | Strategic; per-step preview is the gem |
| C2 GitHub Action | Medium | Low | Marketing + utility |
| B5 concurrency | Medium | Medium | Profile first |
| B8 Python API docs | Medium | Low | Mostly a commitment decision |

---

*Open questions: (a) which of these collide with existing plans (fontc integration, incremental compilation) where the team already has a design in mind? (b) is there appetite for Workflow to grow into the QA/CI role (A5, B7, C2), or should it stay a transformer and leave QA to Font Bakery? (c) rename-glyphs: should production-name logic live in core or as a plugin shared with the editor?*
