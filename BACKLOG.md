# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.98.5**, 2026-09-14.

> **What the 2026-09-14 review found.** The previous review was against
> v2.69.0 — twenty-nine releases stale — and the problem was the opposite of
> the one expected. Nothing in here had already shipped. What it did was
> *under-record*: ten open items were being carried in conversation rather
> than in the file, which is how the same questions got asked twice in a day.
> Everything below was checked against the code, not recalled.

---

## Open work

### Cloud Manager

#### 1. P2 — Sync cannot tell a divergence from a one-sided change

`syncEverythingPlan()` classifies each file as `cloud_newer` or `local_newer`
and nothing else. There is no concept of *both sides changed since the last
sync*, so a genuine divergence is silently resolved as a one-way copy and the
older edit is lost without anyone being told a choice was made.

This is the last unbuilt capability in Sync — per-file direction (v2.86.0) and
one-click pull of cloud-newer plus cloud-only files both work.

**Done** is: a third state that stops rather than copies, names both sides with
their timestamps, and makes the user pick. It must never auto-resolve. Needs a
record of what was last synced, which does not exist yet — that is most of the
work.

#### 2. P2 — Bulk merge many folders into one

The current merge workflow accepts one local source folder and one destination.
Add a bulk action that accepts multiple selected local source folders, previews
the combined file operations, preserves per-file exclusions, and executes each
source safely against one destination.

Cloud-to-cloud merging should remain unsupported unless Ekahau provides a safe
server-side operation. This feature needs dry-run coverage and file-count
verification because source-folder cleanup can be destructive.

#### 3. P2 — Manual External override

Automatic External detection uses project ownership metadata. Add a persistent
per-project override so a user can mark a project as External or Mine when
ownership metadata is missing or does not reflect operational responsibility.

The dashboard counts, filters, and row styling must all honor the same
override. The final UI — row action, inline control, or settings list — still
needs a design decision.

#### 4. P3 — Upload direction: replacing an existing cloud project

Cloud Manager can download and cannot upload over an existing cloud project.
The Sync confirm says "that direction is not built yet" deliberately: the API
is not known to be the obstacle, the code is simply not written.

**Read `CLAUDE.md` § "Uploading to Ekahau Cloud" before touching this.** It
records what is established (the batch endpoint returns every document,
including `projectHistorys`, so the cloud does hold the revision chain), what
is not (whether `batch/update` accepts documents other than `project`), and
three dead ends not to spend another session on — including that the desktop
client's sync prompt cannot be captured from a browser.

The cheap open route is `docs/reverse-engineering/capture_project_fields.js`,
which reads the project *listing* and would settle whether a project record
carries a revision or etag.

---

### Report

#### 5. P2 — Column grid references on section pages

A warehouse section page shows an AP floating in empty slab with no feature to
locate it against. Construction crews locate everything off the column grid —
lettered one axis, numbered the other, bubbled on the drawing — so a grid
reference is the coordinate system they already use. This is the third of the
three AEC conventions; the Key Plan (v2.60.0) and match lines (v2.62.0)
shipped.

**Automatic extraction from the raster is not tractable here.** It needs circle
detection, OCR of the bubble letters and numbers, and line tracing. There is no
OCR in this stack, and adding one would fail silently on exactly the drawings
that matter — a mis-read bubble produces a confidently wrong reference, which
is worse than none. Do not attempt it.

**Two clicks per floor, not a drawn grid.** Column grids are regular by
construction — that is what a structural bay is — so the user clicks two known
intersections and types their labels (say `A-1` and `G-7`). Spacing and origin
follow from those two points and the grid extends across the plan. He has
already accepted a manual step over automatic detection once, for PlanTrim's
bounding box, for the same reason.

**What it cannot handle**, and should say so rather than guess: irregular or
interrupted bays; skewed or rotated grids; split grids with their own sequences
per building section. In all three the reference should be turned off for that
floor rather than printing something plausible and wrong.

**Delivery, cheapest first.** A `Grid` column on the Antenna Aim Sheet and AP
Installation tables — that is where an installer reads a location, and it needs
no drawing changes. Under the marker label on the plan is a second step, and
should be optional.

**Where it lives.** `~/.wd_wireless_tools`, keyed by project and floor — user
data never goes in the install tree, and it must not go into the `.esx` either,
since Ekahau has no member for it and a round trip would drop it.

**Reuse.** The grid-config canvas already has picking, pan and zoom on a real
floor plan. Build the two-point picker on that rather than a fourth canvas.

#### 6. P3 — Change / Audit report

The gallery card exists but is intentionally marked **Coming soon**. Completing
it requires:

- A second `.esx` file picker for before-and-after projects.
- AP matching and change classification for added, removed, moved, re-aimed,
  and re-mounted APs.
- Before/after summaries, change tables, and per-floor overlay rendering.
- Tests for dual-file state, matching thresholds, and generated output.

This is the largest remaining Report feature and should be developed separately
from routine maintenance.

#### 7. P3 — A notes-terminated document has not been print-verified

The trailing blank sheet was fixed in v2.96.2 and confirmed on a real
deliverable — but that document had notes **off**, so its last section was the
compass page. The fix is independent of which section is last, and the
mechanism is length-independent, so this is a gap in evidence rather than a
suspected fault.

**Done** is: one document ending in AP Notes pages, printed through the Firefox
BiDi path, page count asserted.

---

### PlanTrim

#### 8. P2 — The floor strip says "Automatic" for a floor that has a drawn box

`floorState()` in `web/assets/js/plantrim.js` is given the trim report and
nothing else. It never consults `box.boxes`, so a floor where the user drew a
box that the trim did not end up using reads as **Automatic** — with no hint
that a box exists at all.

That is the one case where the strip is actively misleading rather than merely
terse: it reports the outcome and hides the input. The user drew something and
the page says the machine decided.

**Done** is: a floor with a saved box says so, whichever way the crop went, and
a box that was drawn but not used says that it was not used and why.

#### 9. P3 — Only PNG, JPEG and SVG floor plans can be cropped

`image_kind()` in `tools/esx_trimmer.py` returns `PNG`, `JPEG`, `SVG` or
`UNKNOWN`, and `UNKNOWN` is refused. Ekahau accepts more than that — BMP, WBMP
and GIF among them — so a project can carry a floor plan the trimmer will not
touch.

Pillow already reads all three, and the crop path is format-agnostic once the
image is open; the gate is the magic-byte sniffer and the writer's format
branch. The refusal is at least honest today, which is why this is P3 and not
higher.

---

### Quick Walls

#### 10. P2 — The wall audit is built, tested, and unreachable

`tools/wall_audit.py` exists with 15 passing tests, and `scripts/audit_walls.py`
drives it from a terminal. There is **no server route and no UI** — grep finds
zero references in `server.py` and zero in any page's JavaScript.

It reports, per project, which wall types are on Auto height with a segment
count and a severity. That is the backstop the whole
"a height ships only where the name states one" decision rests on
(see `docs/wall-types.md`), and nobody using the app can run it.

**Done** is: reachable from Quick Walls on an open project, reporting in the
page rather than the terminal. The logic and its tests already exist, so this
is a route plus a panel.

---

### Suite-wide

#### 11. P3 — The Firefox scrollbar styling was shipped unverified

`wd-tools.css` carries one `scrollbar-width` / `scrollbar-color` rule. Firefox
is the browser he actually uses, and this has never been looked at in it. It is
cosmetic, so it is P3 — but it is also five minutes with the BiDi path that is
now established, and print work has twice shipped wrong by being checked in the
wrong engine.

#### 12. P3 — BLOCKED: the DWG-to-`.esx` finding is not written down

A finding about going from DWG to `.esx` was established in an earlier session
and never recorded, so the next session will redo the work.

**This cannot be written up from the repo.** `DWG` appears only as a file
extension in the organizer, settings and Cloud Manager, and nothing in the git
history, `CLAUDE.md`, the docs or the release notes records a conversion
finding. Someone has to supply what the finding actually was before it can be
written down; inventing a plausible one would be worse than the gap.

---

## Awaiting a decision, not work

These are all small, and all blocked on a call rather than on effort. Grouped
so they can be answered together.

- **Rename the AP Label Reference page.** The notes page is now plain
  **AP Notes** at his request. The label page beside it still says **AP Label
  Reference**, so two sibling pages are named two different ways. Options:
  leave it, `AP Labels`, or `AP Label Key`.
- **AP Notes pages on report types beyond the AP Placement Map.** `compassRef`
  already appears on **Antenna Aim** and **Location**, which makes those the
  natural candidates. Notes exist only on Placement today.
- **Auto / Always / Never for the notes pages.** Today it is a checkbox, off by
  default. The compass page uses a three-way select. Consistency argues for a
  select; the privacy reasoning behind notes being opt-in argues for keeping a
  plain off switch.
- **Squirrel Rename has no link anywhere.** `/rename` is routed in `server.py`
  and reachable only by typing the URL. Either it gets a menu entry or it is
  deliberately internal — it has never been decided which.

---

## Decisions already made — kept so they are not re-litigated

Not work. Recorded because each was settled once and would otherwise be
rediscovered as an open question.

### Where the AP Notes section sits: last, deliberately

Notes pages are **unbounded in length**. Today they are short text tables, so
the position looks arbitrary; it is not.

If picture notes become common the section could run to dozens of image-heavy
pages. That is existing industry practice rather than a hypothetical — Mist's
installer app requires a photo of every AP — so a project could arrive with one
note and one image per access point.

An open-ended section at the end cannot push fixed reference material around.
Anything placed after it would move unpredictably depending on how many photos
a survey happened to carry. So: last is right while the length is unknown, and
if the order is ever changed this reasoning has to be answered rather than
rediscovered.

It also supports the decision not to build an image layout path speculatively.
The day that matters it will be a real requirement with real files and a real
page budget, not a guess at what an image note should look like.

Revisit only when a project actually turns up with photo notes on most of
its APs.
