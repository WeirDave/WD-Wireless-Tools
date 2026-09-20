# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.145.0**, 2026-09-19. Every item below was opened in
the code and checked; what each check found is recorded on the item, including
where the check found the item itself was wrong.

**Item numbers are reassigned at each pass.** A reference to one from outside
this file has to name the pass date as well as the number, or in a month it
will point at something else.

> **What the 2026-09-19 pass found.** The previous pass was against v2.100.12
> and the file said so, in bold, at the top. The problem was the mirror image
> of 2026-09-14's: that pass found *under-recording*, real work carried in
> conversation instead of here. This one found **over-recording** — three
> entries describing the tool as it was forty-five minor versions ago, two of
> them in the section whose whole job is to be trusted without re-checking.
>
> **One open item had simply shipped.** *Upload direction* said Cloud Manager
> "cannot upload over an existing cloud project" and quoted a Sync confirm
> reading "that direction is not built yet". `replace_cloud_project` has done
> it since v2.104.6, and that sentence is in no file in the repository. Anyone
> picking the item up would have started by building something that exists.
>
> **One had shrunk without being re-measured.** *Sync cannot tell a divergence*
> said a divergence is "silently resolved as a one-way copy ... without anyone
> being told a choice was made". The Sync dialog now says it in bold, and a
> content comparison answers it per row. What is left is real and is about a
> third of what the item claimed.
>
> **And one settled decision had been reversed two releases after it was
> written down.** *A template adds; it never changes a wall type Ekahau ships*
> was recorded at v2.100.12 and undone at v2.100.19, when he asked for his
> three wall colours back. It sat in "Decisions already made — kept so they are
> not re-litigated" from v2.100.19 to v2.145.0, stating the opposite of both
> the shipped template and the code. That is the worst place in the file for a
> wrong entry, because the section exists to be acted on without checking.
> It is rewritten below with the reversal in it.
>
> **The lesson is about the staleness warning itself.** It was added in
> c11b051, it was accurate, and it stopped nothing: an item you have been told
> to distrust reads exactly like an item you have not, once you are three
> paragraphs into it. A warning at the top is not a substitute for a pass.

---

## Open work

### Cloud Manager

#### 1. P2 — Sync has no record of what was last synced

`syncEverythingPlan()` (`web/assets/js/cloud.js:7246`) sorts each pair by
`staleness` into `cloud_newer`, `local_newer` or in-sync, and nothing else.
Two timestamps cannot separate "they changed it" from "we both changed it",
because that needs a third number — the state at the last sync — and nothing
records one.

**Two thirds of this item has been answered since it was written, and not by
storing that number.** Both halves matter before starting:

- **It is no longer silent.** The Sync confirm carries the warning in bold —
  *"Two dates cannot tell you whether both sides changed"* — names the
  consequence, and says to compare first (`cloud.js:6999`).
- **A content comparison answers it per pair, on demand.** `compare_esx`
  (`tools/esx_compare.py:143`) returns `identical`, `renamedOnly`,
  `designDiffers`, a `nameState` and a per-member summary, and
  `_syncVerdictCell` (`cloud.js:7319`) puts that verdict in the plan row —
  "name only" against a row that is safe to tick, the summary against one that
  is not.

So he is told, and he can find out. What is missing is that the **tool** still
cannot tell, so it cannot stop on its own: comparing is something he has to
choose to do, and the plan runs whatever the verdict said.

**Done** is: a stored record of the last synced state, a third classification
that stops rather than copies, and both sides named with their timestamps. It
must never auto-resolve. The record is most of the work, and it is the part
that did not get easier.

#### 2. P2 — Bulk merge many folders into one

`merge_preview(src_path, dst_path)` and `merge_execute(src_path, dst_path,
ops)` (`tools/cloud_manager.py:3743`, `:3785`) each take exactly one source and
one destination, and `CLOUD_ACTIONS` exposes them that way
(`server.py:1122-1123`). Verified unchanged.

Add a bulk action that accepts multiple selected local source folders, previews
the combined file operations, preserves per-file exclusions, and executes each
source safely against one destination.

Cloud-to-cloud merging should remain unsupported unless Ekahau provides a safe
server-side operation. This needs dry-run coverage and file-count verification
because source-folder cleanup can be destructive — and note that
`merge_preview` is one of the twenty server actions no test names at all (item
4), so there is no coverage to build on.

#### 3. P2 — Manual External override

`_isExternal(cloudObj, localObj)` (`cloud.js:1339`) compares the owner email on
either side against `data.currentUser` and does nothing else. There is no
override anywhere in the repo: `external_override`, `externalOverride`,
`markExternal` and `mark_external` appear in no file.

Add a persistent per-project override so a project can be marked External or
Mine when ownership metadata is missing or does not reflect operational
responsibility. The dashboard counts, filters and row styling must all honor
the same override.

**One case worth designing for, found while checking this.** `_isExternal`
returns `false` for everything when `currentUser` is empty, so an account that
comes back without one shows no External projects rather than an unknown
number. That is the right default, and it is the case an override most
obviously serves. Note the shape the owner filter settled on for the same
problem (CLAUDE.md § "Known gotchas"): when a filter cannot answer, say so on
screen rather than render a confident empty list.

The final UI — row action, inline control, or settings list — still needs a
design decision.

#### 4. P1 — One systemic finding from the Cloud Manager audit is still open

The whole-tool audit of 2026-09-18 is in
`docs/audits/cloud-manager-2026-09-18.md`, with the evidence per item, each
marked `[measured]`, `[traced]` or `[reported]`. **Thirty-one of its findings
are closed** — A0 in v2.139.1, the six P1s in v2.142.0, the twelve P2s in
v2.143.0, the twelve P3s in v2.145.0, A31 (CI never installs Node) in
`claude/ci-installs-node` — verified here: `.github/workflows/tests.yml` now
runs `setup-node@v4` on Node 22 — and A32, the notes describing a delete gate
that no longer exists, on 2026-09-19.

What remains open is **A33: the untested surface is the destructive one**.
Re-measured at v2.145.0 rather than carried forward, because three of the five
behaviours the audit listed have gained real coverage since:

| Behaviour | At the audit | Now |
| --- | --- | --- |
| Transfer ownership | no coverage | `test_cloud_sharing_says_what_happened.py` executes it through five outcomes |
| Folder merge (`merge_execute`) | no coverage | `test_cloud_merge_empty_means_empty.py` moves a real file on disk |
| Duplicates tab delete | no coverage | `test_cloud_duplicates_delete_says_what_goes.py` drives the real dialog |
| `merge_preview` | no coverage | **still none** |
| `delete_cloud` / `delete_local` executing | no coverage | **still none** — `delete_cloud` appears in one test *docstring* and nowhere else |

Counted the same way across the whole tool: **20 of 49** `CLOUD_ACTIONS`, 149
of 302 top-level functions in `cloud.js`, and 42 of 58 inline handlers are not
named in any test file. The twenty actions are `add_group_member`,
`create_local_folder`, `forget_all_recipients`, `get_duplicates`,
`get_my_group`, `housekeeping_stop`, `list_manual_matches`, `list_not_matches`,
`list_shares`, `mark_manual_match`, `mark_not_match`, `merge_preview`,
`open_login`, `refresh_group_shares`, `remove_group_member`, `remove_share`,
`reveal_in_explorer`, `toggle_group_share`, `unmark_manual_match` and
`unmark_not_match`.

**Do not read those three numbers against the audit's** (25 of 46, 214 of 380,
44 of 78). The audit's counting method was never committed as a script, so the
two are not the same measurement and the difference is not a trend. The one
reproducible number is `scripts/audit_source_string_tests.py`: 350 assertions
in 61 files at the audit, **346 in 58** now.

**Highest value first**, and the first two are the destructive ones:
`delete_cloud` and `delete_local` actually executing, then `merge_preview`,
then the sharing group's six actions.

Related, and already ratcheted rather than listed as work: 114 assertions in 19
test files that execute nothing at all
(`scripts/audit_tests_that_never_run_anything.py`). That debt is held per file
in `tests/source_string_assertion_baseline.json` and can only go down — see
CLAUDE.md § "A test that would pass with the feature deleted is not a test".

---

### Report

#### 5. P2 — Column grid references on section pages

A warehouse section page shows an AP floating in empty slab with no feature to
locate it against. Construction crews locate everything off the column grid —
lettered one axis, numbered the other, bubbled on the drawing — so a grid
reference is the coordinate system they already use. This is the third of the
three AEC conventions; the Key Plan (v2.60.0) and match lines (v2.62.0)
shipped. Nothing has been built: `gridRef`, `grid_ref`, `columnGrid` and
`column_grid` appear nowhere in the repo.

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

**Reuse.** The grid-config canvas (`openGridConfig()`, `report.js:1757`) already
has picking, pan and zoom on a real floor plan. Build the two-point picker on
that rather than a fourth canvas.

**Anything drawn or printed gets an absolute size floor, in points, not a
fraction of the drawing** — CLAUDE.md § "The rule that keeps coming back". This
feature's entire output is small text on a drawing, so it is the rule's next
likely victim: a grid reference an installer cannot read on paper is the same
defect as no grid reference.

#### 6. P3 — Change / Audit report

The gallery card exists and is intentionally marked **Coming soon** — verified
as the only report still in that state (`report.js:6298`). Completing it
requires:

- A second `.esx` file picker for before-and-after projects.
- AP matching and change classification for added, removed, moved, re-aimed,
  and re-mounted APs.
- Before/after summaries, change tables, and per-floor overlay rendering.
- Tests for dual-file state, matching thresholds, and generated output.

This is the largest remaining Report feature and should be developed separately
from routine maintenance.

**The matching half may largely exist already.** `tools/esx_compare.py` answers
"how do these two `.esx` files differ", per member, without touching disk; and
v2.145.0 fixed seven faults in Cloud Manager's name matcher, several of which
(three-digit building numbers, years read as street numbers, listing-order
dependence) any second comparison engine would reproduce from scratch. Read
both before writing a third one.

---

### PlanTrim

#### 7. P3 — Only PNG, JPEG and SVG floor plans can be cropped

`image_kind()` (`tools/esx_trimmer.py:288`) sniffs three magic-byte signatures
and returns `UNKNOWN` for everything else, which is refused. Verified
unchanged. Ekahau accepts more than that — BMP, WBMP and GIF among them — so a
project can carry a floor plan the trimmer will not touch.

Pillow already reads all three, and the crop path is format-agnostic once the
image is open; the gate is the magic-byte sniffer and the writer's format
branch. The refusal is at least honest today, which is why this is P3 and not
higher.

---

### Suite-wide

#### 8. P3 — BLOCKED: the DWG-to-`.esx` finding may now be written down

A finding about going from DWG to `.esx` was established in an earlier session
and never recorded. The item has stood on the grounds that nothing in the repo
said what it was.

**That is no longer quite true, and the item is narrower than it was.** Two
places now record a DWG finding, neither of which existed when the item was
written:

- `tools/esx_trimmer.py`, module docstring, lines 27-32: a DWG import lands as
  a vector plan; Ekahau writes a companion raster of the same drawing beside
  it; and the two axes have to be scaled independently, because the rasteriser
  rounds — 792x612 renders to 5000x3863 where one shared ratio would give
  3863.6, so a single ratio would refuse every real file over the artefact.
- `docs/USER_MANUAL.md` § "Vector plans — DWG and PDF imports", added in
  v2.144.0, which states the same thing for a reader.

**Whether that is *the* finding, only he can say.** It is a good candidate and
it is specific, so the question to put to him is now "is this it?" rather than
"what was it?" — which is a question he can answer in one word. Do not close
the item on the strength of the candidate, and do not invent the remainder: a
plausible invented finding is worse than the gap, which is why this item exists
at all.

---

## Awaiting a decision, not work

Blocked on a call rather than on effort, so they can be answered together.

**The four menu-label questions that filled this section were all answered on
2026-09-19** and are recorded under "Decisions already made" below. One
question replaces them, and it came out of this pass:

- **Is the DWG note in `esx_trimmer` the finding item 8 is missing?** It says a
  DWG import lands as a vector plan with a companion raster beside it, and that
  the two axes have to scale independently because the rasteriser rounds. If
  that is what was established in the earlier session, item 8 closes and the
  note is already written. If there was more to it, item 8 stays open and needs
  the rest. **A yes or no is enough** — nothing else about item 8 can move
  until this is answered, which is why it is here rather than only there.

---

## Decisions already made — kept so they are not re-litigated

**Read the date on an entry here.** One of them was reversed two releases after
it was written and sat here wrong for forty-five minor versions, so this
section is not exempt from the next pass.

### A wall template updates every type it carries, including Ekahau's — and the opposite was recorded here until 2026-09-19

**The entry this replaces said the opposite, and it was wrong from v2.100.19
onward.** It read: *"A template adds; it never changes a wall type Ekahau
ships"*, quoting him — *"I just want to add in the walls that we added, not
change anything from the defaults."* That reading produced v2.100.5, which
stripped three of his colours out of the shipped template and added a guard to
`mergeTemplateTypes` skipping stock types.

Both halves were wrong, and he said so: *"get them back to where they were for
my template."* The three colours — `Door, Steel Fire/Exit` orange, `Elevator
Shaft` green, `Window, Thick` `#0093EA` — are **his**, chosen so similar types
can be told apart on a plan, and the Quick Walls guide had documented them as a
feature for as long as they had existed. v2.100.19 put them back and removed
the guard with them, because every Ekahau project already contains those three
types: a skip-stock-types rule means his colours never land on anything, which
is a restoration that changes a file and nothing anyone can see.

Verified in this pass, both ends: `templates/WD Template_walltemplate.json`
carries `#E85D04`, `#5FAB4F` and `#0093EA` on those three, and
`mergeTemplateTypes` (`web/assets/js/walls.js:258`) has no stock branch —
`kept` is never pushed to, so `keptPhrase` is dead code, left in place
deliberately so that re-adding the skip is one line and the message that
explains it is already written.

**What is still true from the old entry**, and is the part worth keeping: a
type the template says nothing about is left exactly as it is, and nothing is
ever removed here. **Ekahau Defaults** is the button that deliberately starts
over, and it asks first.

The full reasoning, including how the colours were recovered from a real
project, is in CLAUDE.md § "Known gotchas". That section has been right
throughout; this file was the one that drifted.

### Upload direction is built, and in-place replacement is ruled out — closed 2026-09-19

Carried as open work from v2.69.0 to v2.145.0 on wording that stopped being
true at v2.104.6. `replace_cloud_project` (`tools/cloud_manager.py:2322`) puts a
local `.esx` up over an existing cloud project, and the Sync confirm sentence
the item quoted — "that direction is not built yet" — is in no file in the
repository.

**It is a composition, and it always will be.** That settles the question the
item left open, which was whether `batch/update` accepts documents other than
`project`. It does write in place — it is how renaming works — but it is JSON,
and a project's floor plans are binary images fetched from S3 by id during
download. **A JSON document write cannot carry a re-cropped plan**, which is
exactly what his edits change. So in-place replacement is ruled out by what the
data is, not by an untested endpoint, and the capture script the old item
pointed at would not have changed that.

Four properties of the built version, each worth not undoing:

* **The order is inverted from the way he asked for it, on purpose.** Upload,
  verify, *then* delete. Deleting first means a failed upload leaves nothing in
  the cloud — his local copy survives, but the shared copy other people work
  from is gone and he may not find out until somebody asks. Uploading first
  means a failure leaves a duplicate: visible, annoying, removable in one click.
* **Direction is re-read on the server before anything is uploaded**
  (v2.142.0), because the ledger's `staleness` is a snapshot from when the list
  was drawn and it is the push that deletes. A missing cloud date is Ekahau not
  saying, which is not Ekahau saying newer.
* **The site is carried over** — the dataset listing is read for the old
  project's `siteId` and the upload goes into it.
* **Shares are lost, and it says so by name.** A share is keyed to the project
  id and this deliberately creates a new project. Nothing re-applies them:
  sharing other people's projects on their behalf is not a side effect an
  upload should have. The result names everyone who loses access, at the moment
  it happens rather than when somebody asks why they cannot open it.

CLAUDE.md § "Uploading to Ekahau Cloud" was corrected in the same pass; its
opening sentence still said the direction did not exist.

### The four menu-label decisions — answered 2026-09-19, shipped in v2.144.0

Verified against the files in this pass rather than taken from the commit
message.

- **AP Label Reference → AP Labels**, so the printed page reads like its
  sibling **AP Notes**. No occurrence of the old name remains in `web/` or
  `docs/`.
- **Report a Bug → Report a Bug on GitHub**, on every page carrying it,
  matching the *View Issues* correction from v2.119.1.
  `LABELS_HE_HAS_NOT_RULED_ON` in `tests/test_every_tool_is_in_every_menu.py`
  is now an empty set, so the outbound-link rule covers everything with nothing
  excused from it by name.
- **User Guide / User Manual** — answered by removing one rather than renaming
  either: *"There should be one universal User guide for the entire suite with
  chapters for each of the tools."* No `guide-*.html` page remains, and
  `server.py:273-278` redirects all six old addresses to their chapter anchor.

  **Three factual corrections came out of the merge**, and they are why it was
  worth doing rather than a tidy-up: the guide promised a
  `.previous-<timestamp>.esx` backup that nothing had written since v2.141.0;
  it claimed a wall template never restyles a type Ekahau ships, when
  `mergeTemplateTypes` has deliberately done exactly that since v2.100.19 (the
  same error this file was carrying — see the first entry in this section); and
  the Report page claimed the cover image lives in `localStorage` when it has
  been in `~/.wd_wireless_tools/report/` throughout. **Two documents answering
  one question is how all three survived**, which is the argument against
  splitting them again.
- **"Suite Settings" deep-linking to five different anchors — left alone,
  deliberately.** The jump lands where you would want and has never surprised
  anyone. Closed rather than carried.

### The user documentation is organised around the job, not the tool list — v2.116.0, merged in v2.144.0

He opened it, said it was horrible, and asked for the revamp on the back burner
while he was blocked at work.

**The organising decision, so it is not quietly undone:** it opens with "A site
from start to finish", which walks one job through every tool in the order he
uses them — Squirrel, Ekahau import, Scale, Prep, Quick Walls and hand-drawn
walls over a background image, APs, upload, pull the cloud copy back down,
Report. The per-tool sections are reference *underneath* that. Anyone tempted to
restore an alphabetical tool list at the top should read this first: the tool
list is what it was, and it was the thing he objected to.

Since v2.144.0 this is the suite's **only** user document — the five per-tool
guides are chapters in it. It is reached as **User Guide**, served at
`/manual`, and lives at `docs/USER_MANUAL.md`; the file name is the last place
the old word survives.

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

### A notes-terminated document prints correctly — closed by evidence

The trailing-blank-sheet fix (v2.96.2) had only ever been confirmed on a
document whose last section was the compass page. A project with a note on all
44 of its access points was printed in Chrome, Edge and Firefox: 13 sheets in
every engine, the last one an **AP Notes** page, and no blank sheet anywhere.

Printing it is also what found the ordering fault fixed in v2.100.6 — the
compass page was coming out **after** the notes on the AP Placement Map, which
is the one report he asked for notes on.

### The scrollbar styling is verified, and it was not what the item said

The item described "one `scrollbar-width` / `scrollbar-color` rule". There were
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

### The wall audit is reachable

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
