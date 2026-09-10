# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against v2.69.0.

## P2 — Cloud Manager: bulk merge many folders into one

The current merge workflow accepts one local source folder and one destination. Add a bulk action that accepts multiple selected local source folders, previews the combined file operations, preserves per-file exclusions, and executes each source safely against one destination.

Cloud-to-cloud merging should remain unsupported unless Ekahau provides a safe server-side operation. This feature needs dry-run coverage and file-count verification because source-folder cleanup can be destructive.

## P2 — Cloud Manager: manual External override

Automatic External detection uses project ownership metadata. Add a persistent per-project override so a user can mark a project as External or Mine when ownership metadata is missing or does not reflect operational responsibility.

The dashboard counts, filters, and row styling must all honor the same override. The final UI—row action, inline control, or settings list—still needs a design decision.

## P3 — Report: Change / Audit report

The gallery card exists but is intentionally marked **Coming soon**. Completing it requires:

- A second `.esx` file picker for before-and-after projects.
- AP matching and change classification for added, removed, moved, re-aimed, and re-mounted APs.
- Before/after summaries, change tables, and per-floor overlay rendering.
- Tests for dual-file state, matching thresholds, and generated output.

This is the largest remaining Report feature and should be developed separately from routine maintenance.

## P2 — Report: column grid references on section pages

A warehouse section page shows an AP floating in empty slab with no feature to
locate it against. Construction crews locate everything off the column grid —
lettered one axis, numbered the other, bubbled on the drawing — so a grid
reference is the coordinate system they already use. This is the third of the
three AEC conventions; the Key Plan (v2.60.0) and match lines (v2.62.0) shipped.

**Automatic extraction from the raster is not tractable here.** It needs circle
detection, OCR of the bubble letters and numbers, and line tracing. There is no
OCR in this stack, and adding one would fail silently on exactly the drawings
that matter — a mis-read bubble produces a confidently wrong reference, which is
worse than none. Do not attempt it.

**Two clicks per floor, not a drawn grid.** Column grids are regular by
construction — that is what a structural bay is — so the user clicks two known
intersections and types their labels (say `A-1` and `G-7`). Spacing and origin
follow from those two points and the grid extends across the plan. This is far
less work than drawing every axis, and it is most accurate precisely where it
matters most, because a warehouse is the most regular building there is. He has
already accepted a manual step over automatic detection once, for PlanTrim's
bounding box, for the same reason.

**What it cannot handle**, and should say so rather than guess:

- Irregular or interrupted bays — an expansion joint, an added wing, a grid that
  restarts. Two points describe one regular grid and nothing else.
- Skewed or rotated grids. Solvable later from the two points' angle, but not in
  a first version.
- Split grids with their own sequences per building section.

In all three the tool should let the reference be turned off for that floor
rather than print something plausible and wrong.

**Delivery, cheapest first.** A `Grid` column on the Antenna Aim Sheet and AP
Installation tables — that is where an installer reads a location, and it needs
no drawing changes. Under the marker label on the plan is a second step, and
should be optional: on a dense plan it is one more thing competing for space.

**Where it lives.** `~/.wd_wireless_tools`, keyed by project and floor — user
data never goes in the install tree, and it must not go into the `.esx` either,
since Ekahau has no member for it and a round trip would drop it.

**Reuse.** The grid-config canvas already has picking, pan and zoom on a real
floor plan, and is the model for WD canvases generally. Build the two-point
picker on that rather than a fourth canvas implementation.
