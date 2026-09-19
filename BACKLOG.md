# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.100.12**, 2026-09-14 — the second pass that day was a
verification sweep, run in Chrome, Edge and Firefox against a real project
rather than read off the source. What it closed is noted on each item.

The navigation labels were swept separately on 2026-09-18; what that found is
under "Awaiting a decision, not work".

**The rest of this file has not been re-read since v2.100.12 and the suite is
now past v2.141.** One item has been struck as closed by the backups removal;
the others are carried forward unverified, so confirm an item against the code
before starting it rather than trusting its wording. A full pass is itself
outstanding work.

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

**Every P1 item is now closed — six of them in v2.142.0, one commit and one
failing-first test each.** They are kept listed here, and in full in the audit,
because the reasoning is why each guard exists, and a guard whose reason is not
written down is the one a later session removes as redundant.

* ~~**The upload identifies the project it just made as "the first id that was
  not in the listing a moment ago"**~~ (`cloud_manager.py:2611`) — it applied
  `_await_new_project`'s evidence rule on the fallback path only, while the
  primary path did the thing that docstring forbids in those words. Both paths
  use it now, and an upload that cannot identify what it made renames nothing,
  files nothing and writes nothing back over the local file.
* ~~**The push overwrites the local `.esx` with no backup**~~ — **closed by
  v2.141.0, which removed backups suite-wide.** It was a finding about
  *inconsistency*: every other local overwrite in the file backed one up first
  and this one did not. None of them do now, deliberately, and the writes rest
  on atomic replace instead. Read `CLAUDE.md` § "Backups were removed, and that
  is the design" before treating an unprotected write here as a defect. Its
  live half was the item above, and that is what closed it.
* ~~**`replace_cloud_project` never re-checks direction before deleting**~~ —
  it re-reads both dates before anything is uploaded, and refuses with both of
  them named. Same guard the pull direction has always had, and a missing date
  still counts as "Ekahau did not say" rather than "newer".
* ~~**Cancel on a running cloud write does nothing and then reports success as
  "Cancelled"**~~ — Cancel is opt-in now and nothing opts in, so no running
  write offers it; queued work still offers Remove, which always worked. Work
  that returns is Done.
* ~~**Merge's "delete the source folder afterwards" is ticked by default**~~ —
  "empty" is measured over every file rather than the scan's skip list, and the
  local delete dialog names what is tucked away in `archive/` and `output/`.
* ~~**On the Projects tab the cloud and local checkboxes are the same
  control**~~ — each side has its own key, as the Sites tab and nested rows
  always did, and a mixed selection no longer claims local copies are safe.

**The twelve P2 items are closed as well, in v2.143.0** — seven commits, each
carrying a test that fails against the code before it. In short: Auto-assign
files away only the projects it listed; the External chip can be reached on the
Sites tab; the search reaches the projects inside a site and says what it is
hiding; the head counts what the letter left and an empty list names what
emptied it; sharing reports what Ekahau did, including when it will not say;
the bulk planners refuse the push the row refuses; a stored comparison retires
when the pair moves; a rename brings the name inside the file with it; and a
typed destination is where the file goes. The audit has the detail per item,
including the one deliberate non-change: the chips count the account rather
than the search, and say so above the list.

**And the twelve P3 items are closed, in v2.144.0** — two commits, the
matching engine and the client. The matcher reads a three-digit building
number as the number rather than as the letter "g", stops reading years as
street numbers, will not pair two projects on a shared site code alone, gives
the same answer whatever order Ekahau lists projects in, treats a name that
differs only in capitals as exact, lets Ekahau's own project id outrank a
stale not-a-match, and notices a file rewritten inside one second. On the
client, a failed background poll no longer takes the list away, the Duplicates
tab deletes through the real dialog instead of `window.confirm()`, and the
row-busy clock starts when the work does.

**Two of those were mis-filed as P3 and were not harmless** — the failed poll
wiping the list, and every Duplicates-tab delete gated only by a truncatable
native dialog. Severity was judged by how small the code was rather than by
what it costs. Worth remembering when the next list is triaged.

One systemic item from the audit is still open:

* **The untested surface is the destructive one** — cloud and local delete
  from the main list, transfer ownership and folder merge still have no test
  that could fail if they broke. Sharing, the merge's emptiness check and the
  Duplicates delete dialog have tests now; the rest of that list does not.

*(CI installing Node — the other systemic item — was closed separately in
`claude/ci-installs-node`.)*

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

**All four were answered on 2026-09-19 and are closed.** Shipped in v2.144.0 —
see "Decisions already made" below for the one that was answered by leaving it
alone. They are kept here, struck through, only until the next full pass of this
file.

- ~~**Rename the AP Label Reference page.**~~ **AP Labels**, so the printed page
  reads like its sibling **AP Notes** rather than like a different product.

- ~~**"Report a Bug" has the same gap "View Issues" had.**~~ **Report a Bug on
  GitHub**, on every page, matching the *View Issues* correction from v2.119.1.
  `LABELS_HE_HAS_NOT_RULED_ON` in `tests/test_every_tool_is_in_every_menu.py` is
  now **empty**, so the outbound-link rule covers everything with nothing
  excused from it.

- ~~**"User Guide" and "User Manual" sit next to each other and do not say which
  is which.**~~ Answered by removing one of them rather than by renaming either:
  *"There should be one universal User guide for the entire suite with chapters
  for each of the tools."* The five per-tool pages are merged into their chapters
  and deleted, the document is the **User Guide**, and every menu carries one
  item. The old `/guide…` addresses redirect to their chapter.

  **Three factual corrections came out of the merge**, and they are the reason
  this was worth doing rather than a tidy-up: the guide promised a
  `.previous-<timestamp>.esx` backup that nothing had written since v2.141.0,
  claimed a wall template never restyles a type Ekahau ships when
  `mergeTemplateTypes` has deliberately done exactly that since v2.100.19, and
  the Report page claimed the cover image lives in `localStorage` when it has
  been in `~/.wd_wireless_tools/report/` throughout. Two documents answering one
  question is how all three survived.

- ~~**"Suite Settings" goes to five different places.**~~ **Left as it is,
  deliberately.** The deep link lands where you would want and the jump has never
  surprised anyone. Closed rather than carried.

  *All four found by a sweep of every `menu-item` / `help-menu-item` in
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
