# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.100.5**, 2026-09-14 — the second pass that day was a
verification sweep, run in Chrome, Edge and Firefox against a real project
rather than read off the source. What it closed is noted on each item.

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

---

### PlanTrim

#### 7. P3 — Only PNG, JPEG and SVG floor plans can be cropped

`image_kind()` in `tools/esx_trimmer.py` returns `PNG`, `JPEG`, `SVG` or
`UNKNOWN`, and `UNKNOWN` is refused. Ekahau accepts more than that — BMP, WBMP
and GIF among them — so a project can carry a floor plan the trimmer will not
touch.

Pillow already reads all three, and the crop path is format-agnostic once the
image is open; the gate is the magic-byte sniffer and the writer's format
branch. The refusal is at least honest today, which is why this is P3 and not
higher.

---

### Suite-wide

#### 8. P3 — The Firefox scrollbar styling was shipped unverified

`wd-tools.css` carries one `scrollbar-width` / `scrollbar-color` rule. Firefox
is the browser he actually uses, and this has never been looked at in it. It is
cosmetic, so it is P3 — but it is also five minutes with the BiDi path that is
now established, and print work has twice shipped wrong by being checked in the
wrong engine.

#### 9. P3 — BLOCKED: the DWG-to-`.esx` finding is not written down

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


---

## Decisions already made — kept so they are not re-litigated

Not work. Recorded because each was settled once and would otherwise be
rediscovered as an open question.

### A notes-terminated document prints correctly — item 7, closed by evidence

The trailing-blank-sheet fix (v2.96.2) had only ever been confirmed on a
document whose last section was the compass page. A project with a note on all
44 of its access points was printed in Chrome, Edge and Firefox: 13 sheets in
every engine, the last one an **AP Notes** page, and no blank sheet anywhere.

Printing it is also what found the ordering fault fixed in v2.100.6 — the
compass page was coming out **after** the notes on the AP Placement Map, which
is the one report he asked for notes on.

### A template adds; it never changes a wall type Ekahau ships

His words, after applying WD Template was found to recolour three standard wall
types: "I just want to add in the walls that we added, not change anything from
the defaults. So if stuff has changed from the defaults, that's probably wrong."

So the merge leaves a stock type exactly as it is and says in the toast which
ones it left alone. The **Ekahau Defaults** template is the deliberate
exception — putting the stock values back is the whole point of that one — and
the three drifted colours were corrected in the shipped template as well, since
a template carrying a wrong value is wrong whether or not anything applies it.

The trade is recorded because it is a real one: a template can no longer carry
a house value for a standard type. If that is ever wanted it has to be a
deliberate, visible thing, not a side effect of having saved a template out of
a project where somebody had recoloured a door once.

### The wall audit is reachable — item 9 of the 2026-09-14 review, now done

`tools/wall_audit.py` had 15 passing tests and no way into it from the app. It
is now reached over `/api/walls/audit` and reported in the `#wallAudit` panel
beside the wall list, on the open project, with one implementation shared with
the folder sweep.

### Squirrel Rename is reachable, and the audit was wrong about it

Recorded because this was raised as a gap and should not be raised again.

`/rename` was reported as having "no link from any page". That was an audit
looking in the wrong place: it swept the suite-wide navigation menus and found
nothing. Rename is linked from **Squirrel's own page**, which is where a
sub-tool of Squirrel belongs - his words, "rename is located on the main page
of squirrel so not understanding this either."

The lesson is about the audit rather than the app: "no link in any menu" is not
the same as "unreachable", and a grep for menu entries cannot tell the
difference. Check the owning tool's page before calling something orphaned.

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
