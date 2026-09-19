# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.100.12**, 2026-09-14 — the second pass that day was a
verification sweep, run in Chrome, Edge and Firefox against a real project
rather than read off the source. What it closed is noted on each item.

The navigation labels were swept separately on 2026-09-18; what that found is
under "Awaiting a decision, not work".

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

#### 4a. P1 — Findings from the full Cloud Manager audit, 2026-09-18

A whole-tool audit against v2.139.0 — every filter, every list, every action
across `cloud.html`, `cloud.js`, `cloud_manager.py` and the 46 `CLOUD_ACTIONS`.
**Full detail, with the evidence for each item, is in
`docs/audits/cloud-manager-2026-09-18.md`.** Findings there are marked
`[measured]` (the real function was executed), `[traced]` (read through the
call chain) or `[reported]` (not independently re-executed — confirm first).

One defect was fixed on the spot and shipped in **v2.139.1**: `settlePair`
sent its two arguments the wrong way round, so every action's "did it land"
confirmation had failed since v2.120.0 — and the test covering it was pinning
the swap by asserting a positional argument.

The P1 items, all still open:

* **The upload identifies the project it just made as "the first id that was
  not in the listing a moment ago"** (`cloud_manager.py:2611`), then renames
  it, files it, downloads it over the local `.esx`, and — in
  `replace_cloud_project` — deletes the old cloud project. `_await_new_project`
  exists precisely to forbid this and is only used on the fallback path.
* **The push overwrites the local `.esx` with no backup** (`:2691`), the only
  local overwrite in the file that does not back up first.
* **`replace_cloud_project` never re-checks direction before deleting** — no
  `modifiedAt` comparison anywhere in it, so a cloud copy saved after the
  ledger was drawn is deleted in favour of an older local file.
* **Cancel on a running cloud write does nothing and then reports success as
  "Cancelled"** — nothing reads `cancelFlag`.
* **Merge's "delete the source folder afterwards" is ticked by default** and
  judges the folder empty with a walk that skips `archive/` and `output/`.
* **On the Projects tab the cloud and local checkboxes are the same control**,
  so a cloud-side tick deletes the local file too — while the dialog says
  local copies are not touched.

Two systemic items worth doing before the rest, because they are cheap and
everything else depends on them:

* **CI never installs Node**, so roughly 30 cloud test files skip silently.
  They pass today only because the runner image happens to ship Node.
* **The untested surface is the destructive one** — cloud/local delete, the
  whole Duplicates tab, all of sharing, transfer ownership and folder merge
  have no test that could fail if they broke.

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

#### 8. P3 — BLOCKED: the DWG-to-`.esx` finding is not written down

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

- **"Report a Bug" has the same gap "View Issues" had.** He asked for
  **View Issues** → **View Issues on GitHub**, which shipped in v2.119.1. Its
  neighbour in the same Help & Support section is the *only* other menu item
  in the whole suite that leaves the app, it goes to the same GitHub
  repository, and it says so no more than the one he corrected did. It is on
  eighteen pages, so it is a find-and-replace rather than a decision about
  effort. Options: leave it, `Report a Bug on GitHub`, or `Report a Bug
  (GitHub)`. Until he says, it is exempted by name in
  `tests/test_every_tool_is_in_every_menu.py` so that the rule still catches
  any *new* outbound link.

- **"User Guide" and "User Manual" sit next to each other and do not say which
  is which.** Both are in Help & Support on the same pages, both are
  in-app documents, and the names are near-synonyms. The Guide is the
  per-tool walkthrough (`/guide-cloud`, `/guide-report`, …) and opens in a new
  tab; the Manual is the one long suite-wide document and jumps to that tool's
  anchor (`/manual#cloud-manager`). Nothing on screen carries that
  distinction. Options: leave it, or make the Guide name its tool
  (`Cloud Manager Guide`), or rename the pair to something like
  `Walkthrough` / `Full Manual`.

- **"Suite Settings" goes to five different places.** Most pages link
  `/settings`, but Cloud Manager, Squirrel, Report and Quick Walls link
  `/settings#cloud`, `#organizer`, `#report` and `#walls` — a jump to that
  tool's own section, which the label does not mention. It is arguably right
  as it is (it lands where you would want), and it is only worth changing if
  the jump has ever surprised him. Options: leave it, or
  `Suite Settings — Cloud` on the pages that deep-link.

  *All three found by a sweep of every `menu-item` / `help-menu-item` in
  `web/**.html` on 2026-09-18, done alongside the View Issues rename. Nothing
  else in any menu is ambiguous about where it goes: everything else is either
  a tool page, an in-app dialog, or an action with no destination.*


---

## Decisions already made — kept so they are not re-litigated

### The manual is organised around the job, not the tool list — done in v2.116.0

Item 9 in Open work, now closed. He opened the manual, said it was horrible,
agreed it needed a revamp and asked for it on the back burner while he was
blocked at work. It was done overnight on 2026-09-18.

**The organising decision, so it is not quietly undone:** the manual opens with
"A site from start to finish", which walks one job through every tool in the
order he uses them — Squirrel, Ekahau import, Scale, Prep, Quick Walls and hand-
drawn walls over a background image, APs, upload, pull the cloud copy back down,
Report. The per-tool sections are reference *underneath* that. Anyone tempted to
restore an alphabetical tool list at the top should read this first: the tool
list is what it was, and it was the thing he objected to.

PlanTrim (50 words) and Scale (67) were written properly. Every tool section
says what the tool is for before how to use it. Stale content was corrected —
notably the claim that every tool leaves its backup beside the file it replaced,
which stopped being true for Cloud Manager in v2.104.5.

Six screenshots live in `web/assets/manual/`, all taken from a synthetic project
generated for the purpose ("Example Project", "Level 1"/"Level 2", APs from
"AP-101"). The generator is not committed; regenerate rather than photographing
anything real.


### The roll-up door colour is Ekahau's, and nothing was lost

`#646D7E` on every roll-up door type. **This was briefly written down as "his
custom colour was never written anywhere, he must supply the hex from
OneNote". That was wrong**, and the correction matters more than the fact,
because the reasoning failed in a way that is easy to repeat.

The first pass saw `#646D7E` on all 57 projects, reasoned that a value present
everywhere must be the default, and concluded his own value had been lost. He
pushed back - "I've got roll up doors in like a million freaking projects... and
actually this afternoon Quick Walls had the roll up door colour correct -
basically a blue-grey tint instead of just grey." He was right on both counts,
and `#646D7E` **is** that blue-grey. Ubiquity was taken as evidence of being
stock without anyone checking what Ekahau actually ships.

What settles it, four ways:

* **The discriminator is the steel fire door.** A project his template has been
  applied to carries `#E85D04` there; one it has not carries Ekahau's
  `#999999`. Across 109 projects, **56 had never had his template applied** -
  and all 56 carry `#646D7E` on the roll-up. A colour present in projects his
  template has never touched is not a colour his template put there.
* **Widening the net changed nothing.** Five naming variants, 146 instances -
  `Door, Steel Rollup`, `Steel rollup door`, the `(11dB)` forms and a `(Copy)` -
  every one `#646D7E`, no exceptions.
* **v2.100.5 is the control.** That commit deliberately reverted his
  customisations to Ekahau stock. It changed exactly three colours - steel fire
  door, elevator shaft, thick window - and did not touch the roll-up, because
  the roll-up was already stock. The orphaned pre-restore backup agrees.
* **Every commit since the repository was initialised** has `#646D7E` there.

So the colour he calls correct is the colour that is already in both templates,
and there is nothing to recover. `tests/test_template_store.py` pins it with
this reasoning attached, so the question does not get reopened from the same
wrong end.


Not work. Recorded because each was settled once and would otherwise be
rediscovered as an open question.

### Every native file picker says when it could not open — v2.100.12

A picker that failed to open was reported as a cancel, everywhere, and a cancel
is silent by design. So **Open from disk...** in Prep and Quick Walls could do
nothing at all, measured in three engines: the page did not change by one
character.

Fixed at the source, so it holds for all six pickers - Prep, Quick Walls, both
of Squirrel's, the Report's, and Cloud Manager's folder picker. Prep, Quick
Walls and the Report fall through to the browser's own file dialog; Squirrel
cannot (it needs a path, not bytes) and says what went wrong instead.

The distinction is load-bearing and is tested: the cancel wording must stay
exactly as it is, because every page keys its silence on that string.

### A notes-terminated document prints correctly — item 7, closed by evidence

The trailing-blank-sheet fix (v2.96.2) had only ever been confirmed on a
document whose last section was the compass page. A project with a note on all
44 of its access points was printed in Chrome, Edge and Firefox: 13 sheets in
every engine, the last one an **AP Notes** page, and no blank sheet anywhere.

Printing it is also what found the ordering fault fixed in v2.100.6 — the
compass page was coming out **after** the notes on the AP Placement Map, which
is the one report he asked for notes on.

### The scrollbar styling is verified, and it was not what the item said

Item 8 described "one `scrollbar-width` / `scrollbar-color` rule". There were
two different mechanisms, and the one on the Cloud Manager list was
`::-webkit-scrollbar`, which **Firefox does not implement at all**. Measured
with the list scrolling: Chrome and Edge reserved a 6px gutter, Firefox reserved
0 and drew its own overlay bar in the platform colour.

Fixed in v2.100.7 by adding the standard properties behind
`@supports not selector(::-webkit-scrollbar)`. The guard is not decoration:
Chromium 121+ reads `scrollbar-width` too, and setting it there overrode the
WebKit rule and took Chrome and Edge from 6px to 10px. Firefox still overlays
rather than reserving — that is the platform, not a bug — so its bar is now
thin and muted where it was default, and nothing about the layout moved.

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
