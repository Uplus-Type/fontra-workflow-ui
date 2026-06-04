# A Friendlier UX for Fontra Workflow

*Companion to the [Workflow documentation](documentation.md) and [proposed extensions](extensions.md). Question: would Workflow need a UI? Short answer: yes — but layered, and Fontra is unusually well positioned to build it cheaply. A clickable mockup accompanies this document ([`ui-mockup.html`](ui-mockup.html) — open in a browser).*

---

## 1. Diagnosis: what is unfriendly today?

Workflow's *engine* is friendly (composable, safe, lazy). The *experience* around it is not:

1. **Blank-page problem** — you start from an empty YAML file and a vocabulary you can't discover without reading source code.
2. **Blind authoring** — arguments are typed against invisible schemas; you learn the argument names by being wrong.
3. **Blind execution** — you see the result only at the end, in an output file; intermediate states are invisible (unless you know the [`yaml`-backend trick](documentation.md)).
4. **Errors arrive late and deep** — at step setup or mid-pull, as tracebacks.
5. **Audience mismatch** — the people who would benefit most (designers doing production) are exactly the people YAML excludes.

Note that 1–4 hurt *engineers too*. So the answer to "does it need UI?" is layered: the first layer of friendliness is invisible.

## 2. Layer 0 — friendlier with no UI at all

These come first because they also become the *foundation* of any GUI ([extensions](extensions.md) B1, B2):

- `fontra-workflow list-actions` — discoverability at the CLI.
- JSON Schema generated from the action dataclasses → upfront config validation with line numbers, *and* free autocomplete + inline docs in VS Code/Zed via YAML language servers. For the engineer audience, schema-powered YAML editing **is** the UI.
- `--dry-run` printing the resolved pipeline tree.
- Error messages that name the step, the action, and the argument — not the stack frame.

If only one thing gets built, build the schema: every later layer consumes it.

## 3. Does it need a *graphical* UI? Yes — three reasons

1. **Audience.** Fontra's growth channels (designers, educators, students) overlap barely at all with "comfortable writing YAML pipelines". A GUI doesn't make Workflow nicer for its current users; it makes it *exist* for everyone else.
2. **The architecture begs for it.** Every step boundary in a pipeline *is* a `ReadableFontBackend` — a browsable font. Fontra already knows how to render fonts, glyph grids, axis sliders, text previews, in the browser, over a WebSocket. The hard parts of a pipeline GUI (live preview of intermediate state) are nearly free here, which is not true for any other build tool in the type world.
3. **Precedent.** Shortcuts succeeded where AppleScript stayed niche — same engine, different surface. Non-destructive step-stack UIs (Shortcuts, Automator, Photoshop adjustment layers, Blender modifiers) are a proven way to make pipeline thinking accessible.

## 4. What UI: a **Workflow view** inside Fontra

Not a separate app — a fourth view alongside editor / font overview / font info, registered exactly like them (`fontra.views` entry point). Working layout, three panes plus a run bar (see mockup):

### 4.1 Left: action palette

Searchable, grouped by category (the taxonomy from the [Workflow documentation](documentation.md)), each action with a one-line description and its arguments — all generated from the introspection layer. Drag onto the pipeline, or click ＋ between steps. Plugin actions (fontra-compile etc.) appear automatically because registration is already dynamic.

### 4.2 Center: the pipeline as a vertical step stack

**Not a node graph.** Workflow configs are trees (linear chains + occasional fork/nesting), not arbitrary DAGs — a Blender-style node canvas over-serves and intimidates. A vertical stack maps 1:1 to the YAML:

- one card per step: icon by type (input/filter/output), action name, argument summary;
- nesting (`steps:` under input/output, `fork:`) rendered as indented branch lanes;
- drag to reorder, toggle to disable a step (round-trips as a commented step or an `enabled: false` key);
- status badges per step after validation/run: ✓ ok, ⚠ warnings (e.g. merger conflicts, with the actual glyph names listed on click), ✕ invalid arguments — *before* running.

**The YAML stays the artifact.** A toggle shows the live-synced YAML; edits flow both ways. This is non-negotiable: it keeps configs git-diffable, keeps CI parity (the GUI runs the same file CI runs), and keeps the engineers who already adopted Workflow.

### 4.3 Right: inspector + preview

**Inspector (top):** select a step → a form generated from its schema. The crucial upgrade over raw YAML: fields are populated from the *live stream at that point in the pipeline*, not blank:

- `instantiate` → real axis sliders with the font's actual axes and ranges (the editor component exists);
- `subset-axes` → checkboxes of the actual axes;
- `subset-glyphs` → a glyph-set field backed by the font overview's cell picker;
- file arguments → file pickers; enums (`layoutHandling`) → dropdowns with explanations.

**Preview (bottom), the gem:** a preview pin ◉ that sits *between* steps. The pane shows the font as it exists at the pinned point — mini glyph grid, sample text line, glyph/axis/source counts. Move the pin down the stack and watch the font transform step by step. Add a before/after diff toggle (changed glyphs highlighted, count deltas). Because each boundary is already a backend, this is the cheapest impressive feature in the whole design — it's the `yaml`-backend trick (Workflow [documentation](documentation.md) §6) given a handle.

### 4.4 Bottom: run bar

Output folder, Run button, per-output progress (glyph counts — the engine knows them), and a log console where errors are *clickable*: jump to the offending step, or open the offending glyph in the editor view. Substitution variables surface here too: placeholders in the config become named fields in a run dialog (`family: ____`), which turns templated configs into shareable mini-tools for non-technical colleagues.

### 4.5 Onboarding: recipe gallery

"New workflow" opens a gallery, not a blank canvas: *Webfont subset*, *Extract instances*, *Merge fonts*, *Ship finished glyphs*, *Convert format* — the [documentation](documentation.md) cookbook as starting templates (and the extensions' C3 recipe registry as its upstream). The blank-page problem dies here.

## 5. How, technically (and cheaply)

| Piece | Cost driver | Why it's cheap here |
|---|---|---|
| Action palette, inspector forms | schema | Generated from dataclasses (extensions B1/B2) — no hand-built forms |
| Step stack ↔ YAML sync | round-trip fidelity | The step tree *is* the YAML structure; a comment-preserving YAML lib is the only subtlety |
| Per-step preview | serving intermediate fonts | `WorkflowBackend` already wraps a pipeline as a font; generalize to "backend at step *k*", serve like any project |
| Live preview components | UI | Reuse: font overview grid, axis sliders, text preview with shaping (2026 HarfBuzz work) |
| Run + progress | process management | Server already owns the engine; progress = glyph counts it already iterates |
| View registration | integration | `fontra.views` entry point — same as existing views |

The deliberately *missing* piece is a new runtime: the GUI authors and runs the same YAML through the same engine. Headless/CI parity is guaranteed by construction.

## 6. Phasing

1. **Phase 0** — schema, list-actions, dry-run, error rewrite (no UI; serves everyone, feeds everything).
2. **Phase 1 — read-only Workflow viewer.** Open a `.yaml`, see the step stack, move the preview pin. No editing, no running. Already a debugger people would love; minimal sync complexity.
3. **Phase 2 — inspector editing + validation + Run.** Forms, badges, run bar. Fontra Pak grows a "Run workflow…" menu item.
4. **Phase 3 — authoring comfort.** Palette drag-and-drop, recipe gallery, substitution run-dialogs, diff preview.
5. **Phase 4 — ambient ideas.** Watch mode wired to the preview (`--watch`, extensions B3); "export this font-overview selection as a subset-glyphs step"; collaborative editing of pipelines (the server is already multi-client).

## 7. Non-goals

- **No node-graph programming environment.** If a config needs arbitrary DAGs, it needs Python (B8), not more boxes and wires.
- **No hiding the YAML.** The GUI is a *view* of the file, never a proprietary replacement.
- **No separate product.** It ships as a Fontra view, or it loses the reuse that makes it feasible.

---

*Open questions: (a) is "view inside Fontra" right, or should Fontra Pak get a simpler standalone "droplet" mode first (drop a font on a recipe → output), which is even less UI? (b) comment/format-preserving YAML round-trip — acceptable to relax (normalize formatting) in v1? (c) does the team see the Workflow view as core or as the first big test case for the 2026 plugin API?*
