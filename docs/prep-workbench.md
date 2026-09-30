# Prep as one workbench: the plan

Status: the layout was approved on 2026-09-30 and shipped in suite 2.195.0
(Prep 2.0.0). The layout mockup is a private artifact that the maintainer
holds. This file is the working record; "Still to do" below is what is left.

## The goal

Prep should be where a freshly imported project gets ready in one sitting:
**one file, one plan canvas, three full tools as stages, one save.** The full
tools, not cut-down copies:

| Stage | Comes from | Prep has today | Prep lacks |
|---|---|---|---|
| 1 Trim | PlanTrim | margin preset, reuse of boxes already drawn in PlanTrim, read-only crop preview | drawing and editing a box, Suggest, Apply to all, pan and zoom, saving boxes back |
| 2 Requirement areas | Capacity | apply a template, headcount, per-floor headcount, existing-device choice | capturing a template from a project, managing templates, seeing the area on the plan |
| 3 Wall types | Quick Walls | apply a saved template | editing types, keybinds, save/import/export, the wall audit |
| 4 Wall swap (optional) | Quick Walls → Visual Wall Swap | nothing | all of it; matters only on a re-run, once walls exist |

The standalone PlanTrim, Capacity and Quick Walls pages stay. Each becomes a
thin shell that mounts the same module Prep mounts, so the two cannot drift
apart.

## What is already shared, and what is not

**The back end is already shared.** Prep calls the same `esx_trimmer`,
`capacity_profiles` and `TemplateStore` functions as the tools. The one
duplicate is the wall-template merge: `mergeTemplateTypes` in `walls.js` and
its Python port in `tools/wall_inject.py`. That needs a parity test, or one
copy.

**The front end is the work.** None of the three tools can be mounted
anywhere else yet:

- Every control is `data-fn="someGlobal"`, and the three tools reuse the same
  page ids (`editor`, `fileInput`, `dropzone` and others). Two tools on one
  page would collide.
- PlanTrim is two IIFEs that talk to each other through `window.__pt*`
  globals, and about 20 hard-coded ids.
- Capacity is one small IIFE. It is the easiest to convert, and its apply
  half is already duplicated in `prep.js`.
- Quick Walls is a classic script with top-level state, and it edits the ZIP
  in the browser with JSZip. The other three edit the file on the server.
  That is the hardest part.

The dispatcher already resolves dotted names (`data-fn="WD.Trim.fit"`), so
namespacing the handlers needs nothing new from `wd-shared.js`.

## The shape

- **`WD.PlanView`** is one canvas for the whole suite. It handles pan and
  zoom, fitting to a region, and drawing the plan **on a white page**. Other
  code draws on top of it through overlay callbacks. It is extracted from
  PlanTrim's box editor, which is the most complete canvas in the suite; the
  Report grid preview is the reference for pan and zoom. AP Labeler and Wall
  Swap can move onto it later.
- **`WD.ProjectFile`** loads a project once, whether it was dropped or
  opened from disk. It provides the floor list and the floor images, cached.
  Today Prep, PlanTrim and Capacity each load the file their own way.
- **Tool modules** have the form `mount(root, project, hooks)`, and each
  returns the *decisions* it holds:
  - Trim: boxes and a margin.
  - Areas: a template, headcounts and the existing-device choices.
  - Walls: a template, plus any edits to it.
- **One write.** Prep keeps its current model: decisions are collected, then
  `prep_pipeline.run` applies them in `STEP_ORDER` and writes a new copy once.
  That is what keeps a large project fast, and the order rules stay enforced
  on the server.

## Layout (see the mockup)

- A **left rail** of stages. Each stage has a tick box to include it and a
  one-line status: "3 of 4 floors cropped · Normal, 10 ft".
- **The plan canvas in the middle, shared by every stage.** A floor strip
  runs along its top. The overlay changes with the stage:
  - Trim: the crop box and its handles.
  - Areas: the requirement area polygon.
  - Walls: the wall-type legend.
- A **right panel** holds the controls for the current stage.
- A **footer that is always visible**. It says what will be written and holds
  the **Prepare** button. Every stage opens on the saved defaults, so a
  project that needs no attention is one click.

## Phases

0. **Done in suite 2.191.2:** Prep's plan view draws on white, and Prep writes
   the 2.190.0 repair for plans an earlier trim left dark.
1. **Done in suite 2.192.0:** `WD.PlanView` and `WD.ProjectFile` in
   `web/assets/js/wd-planview.js`. They reproduce PlanTrim's canvas behaviour:
   the white page, a zoom step of 1.15 clamped to 0.02-20, and pan through
   `WD.PanZoom`. Prep's map runs on them and gains zoom, pan and a **Fit**
   button. `tests/test_plan_view.py` holds them, in Node and in all three
   browsers.
   **PlanTrim itself is not on them yet, and that was deliberate.** About
   fifty tests in `test_plantrim_boxes.py` and `test_plantrim_svg_background.py`
   slice PlanTrim's canvas functions out by name and position. Moving the code
   now would rewrite them twice, because phase 2 moves the box editor anyway.
   Until phase 2 lands, the two canvases are separate code with the same
   numbers. A change to one of them needs the same change in the other.
2. **Done in suite 2.195.0, for Prep:** `WD.BoxEditor` in `wd-planview.js`
   is PlanTrim's box editor as a tool that mounts on `WD.PlanView` through
   `onDown`/`onMove`/`onUp`, with boxes in plan units scaled onto the image.
   Prep's Trim stage has drawing, handles, Suggest (`/api/prep/suggest`), Draw
   my own, Apply to all and Back to automatic. Boxes are saved to
   `plantrim_store` under the project id as soon as a drag ends, and the page
   sends its own set as `boxes` (an empty map is "all automatic"); before the
   first preview it asks for the saved ones with `useBoxes=1`.
   `tests/test_plan_view.py::TheBoxEditor` and
   `tests/test_prep_trim_options.py::TheTrimStageDrivesTheBoxes` hold it.
3. **Done in suite 2.195.0:** the layout - rail, shared canvas, right panel,
   footer. The Areas stage draws each floor's area from `outline` (added to
   `capacity_profiles.plan_application`: the kept polygon, or the computed
   rectangle when one is made or redrawn) and captures a template in a modal
   through the existing `/api/capacity/analyze`, `derive` and `save` routes.
4. **Partly done in suite 2.195.0:** the Walls stage picks the template and
   lists every type added or updated. Editing types stays in Quick Walls, and
   Prep reloads the templates when its tab becomes visible again.
5. **Partly done in suite 2.195.0:** Wall swap is on the rail, unavailable
   with its reason on a project with no walls, and pointing to Quick Walls'
   Wall Swap where there are walls (`wallCount` in the plan's `project`).

## Still to do

- **PlanTrim is not on `WD.BoxEditor` yet.** Its own canvas code still exists,
  because about fifty tests slice it by name. Until it moves, the two box
  editors are separate code with the same numbers (handle sizes, the 8-unit
  minimum side, the edge-drag rule); a change to one needs the same change in
  the other. The boxes themselves are already shared, through the store.
- The wall-type editor inside Prep, and the duplicate wall-template merge
  (`mergeTemplateTypes` in `walls.js`, its port in `tools/wall_inject.py`).
- Wall Swap inside Prep. It edits the archive in the browser with JSZip, which
  Prep, being server-side, does not.

Each phase ships on its own and leaves every page working.

## Defaults taken, to be confirmed by the maintainer

- The standalone tools stay, as shells over the shared modules.
- Capturing a Capacity template happens inside Prep, not only through a link
  to Capacity.
- Wall Swap is last, and optional.
- The one-write model stays. Nothing is written until **Prepare** is pressed.
