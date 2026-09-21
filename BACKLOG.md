# WD Wireless Tools Backlog

Only unfinished product work belongs here. Completed work is tracked by Git
history and GitHub Releases.

Priorities: **P1** = blocking · **P2** = wanted · **P3** = future enhancement.

Last reviewed against **v2.145.0**, 2026-09-19, and item 8 closed against
v2.146.0 the same day. Every item below was opened in the code and checked;
what each check found is recorded on the item, including where the check
found the item itself was wrong.

**Items 2, 3, 5, 6, 7 and 9 were closed on 2026-09-20 in v2.153.0**, and item 4
dropped from P1 to P3, because the destructive and sharing surfaces it was
about now have tests that execute them and what is left of its list is reads
and bookkeeping.

**Item 8 closed in v2.154.0, and how it got here is worth keeping.** It came
from a branch that was finished and never pushed - two commits sitting in a
worktree whose session had gone. That is the same fault as an unreleased
version wearing different clothes: finished work that is invisible to everyone,
including to the pass a few hours later that recorded this file as having no
open items at all. The branch was landed rather than discarded. **A worktree
that looks abandoned is not evidence that what is in it is finished with** -
`git log origin/main..<branch>` is, and it is worth running before removing
one.

**Item 4 closed in v2.155.0.** Every one of Cloud Manager's 51 server actions
is named by a test, and the count is held at zero by
`tests/test_every_cloud_action_is_tested.py`.

> **What the 2026-09-21 pass found.** The previous paragraph here said
> "Nothing is open", and said so while explaining why *this* time it could be
> trusted. It was wrong within hours, and it was wrong in the way this file
> keeps being wrong: not about the entries it contains, but about the ones it
> does not.
>
> **Item 4 said the Cloud Manager audit was finished. The audit has an A34,
> and it is open.** Every one of the nine entries below was verified against
> the code and every claim in them holds - the code was opened, not the entry
> re-read. What none of them could show is a finding that was never written
> down here at all. Item 4 listed A0 through A33 and stopped, because that is
> what the *item* listed the last time somebody copied it forward.
>
> **The audit document says so too, and contradicts itself doing it.** Its
> Status section reads "Every numbered finding is closed" and then, two
> paragraphs later, "One thing is not finished: A33" - A33 having closed in
> v2.148.0. Both halves stale, in opposite directions, in the section whose
> whole job is to be read instead of the document.
>
> **The lesson is not "check the entries".** That was done, and the entries
> were right. It is that a backlog is a list of what somebody remembered to
> write down, so a pass has to go looking somewhere else - the audit documents,
> the release payload, the things marked unfinished in code - for the work that
> never made it onto the list.

**The next pass should still open the code**, and should also read anything
this file *summarises* rather than contains. An entry that has been right for a
month is not evidence; it is an entry nobody has checked for a month.

**Item 9 was filed under "Decisions already made", which is the wrong section
for open work**, and it was moved up here in the same pass. That section exists
to be acted on without re-checking; an unfinished task sitting in it is the
mirror of the entry that sat there for forty-five minor versions stating the
opposite of the code.

Two things are recorded rather than finished, and both are on their items.
**Item 7 could only be delivered for two of the three formats it named**:
Pillow ships no WBMP codec, so a format Ekahau accepts stays out of reach until
it does — asserted against the installed Pillow rather than assumed, so the day
that changes, the test says so. And **item 6 compares access points only** —
wall, area and note changes are not in the Change / Audit report, which is what
the item asked for and worth knowing before somebody expects otherwise.

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

#### 1. ~~P2 — Sync has no record of what was last synced~~ — shipped in v2.148.0

`tools/sync_state.py` records what a pair looked like the last time this
machine made the two sides identical, in
`~/.wd_wireless_tools/sync_state.json`, written by a pull or a replace. Four
states then fall out of two comparisons, and the fourth is the one two
timestamps could never produce:

| cloud moved? | local moved? | verdict |
| --- | --- | --- |
| no | no | in sync |
| yes | no | cloud changed - safe to pull |
| no | yes | local changed - safe to push |
| yes | yes | **diverged - left out of the run** |

A diverged pair leaves `Sync everything` entirely and the confirm names it,
says copying either way would discard work, and points at **Check what
differs**. **Nothing resolves a divergence**, deliberately: merging two `.esx`
files is not something this tool can do, and two tests fail if a later change
adds a control that picks a side.

The record is **per installation** rather than a shared truth - the shape that
keeps working when a second person appears, and the reason `both_changed` can
be represented at all. Keyed on Ekahau's project id, which survives a rename
on either side; a local file renamed since the record was written reads
`unknown` rather than matching the wrong pair.

**What this does not do**, and was never the item: it does not compare
contents. It answers "did both sides move", not "did both sides move in ways
that conflict". A pair where both dates moved but only one side's design
changed still lands in the diverged group, and `Check what differs` is how
that gets settled. Narrowing it with a content comparison is a possible
follow-up and would need the comparison's cost thought about first - it
downloads the cloud copy per pair.

#### 2. ~~P2 — Bulk merge many folders into one~~ — shipped in v2.153.0

**How it is used.** Tick the local folders, then **Merge folders into one…**
under **Move, share, mark, overwrite** in the selection bar. Pick the
destination, check the file list, confirm. Nothing moves until you confirm, and
the existing single-folder **Merge** on a row is unchanged.

**The reason it is not a loop over the old call**, which is the whole substance
of the item: two of the folders can each carry a `Report.pdf`. Previewed one at
a time they both read "no conflict", because at that moment neither is in the
destination — and that is true, right up until the first one moves. Run one
after the other, the second lands on the first and nothing ever said so.
`merge_preview_many` walks the sources in the order they will run and carries
what each will place forward into the next, so a collision between two selected
folders is on the file list before anything moves, named — *"also in **SITE9
East**, which moves first"*.

**Under "Keep newer" a cross-source clash keeps both**, deliberately. There is
no file to compare against yet, so "newer" cannot be answered; dropping a copy
on a comparison that could not be made is the one outcome a merge must never
produce.

**A folder that cannot be merged is named and left out** rather than failing the
run — refusing eight because one is wrong is the guard firing on his normal
case. And one source failing mid-run does not stop the rest: the ones that have
already gone moved real files, so the result names the folders that failed
instead of reporting a bare error count.

Cloud-to-cloud merging is still unsupported, as the item asked.

**`merge_preview` is no longer uncovered** — it gained real tests in v2.148.0,
and `tests/test_cloud_merge_many.py` moves real files on a real disk for the
bulk path, including the case that proves the single preview cannot see a
cross-source clash.

#### 3. ~~P2 — Manual External override~~ — shipped in v2.153.0

**How it is used.** Tick the projects, then **Mark as External…** or **Mark as
mine…** under **Move, share, mark, overwrite** in the selection bar — the bar
that appears once something is ticked. A marked row carries a **Marked
External** or **Marked mine** badge in the middle column, and clicking that
badge takes the mark off. There is no default to change; a project with no mark
behaves exactly as it always did.

**Nothing is written to Ekahau Cloud or to any file.** It is an annotation on
this installation's view, filed beside the manual matches in
`~/.wd_wireless_tools/external_overrides.json`, and the confirm says so. That
is also why it needs no ownership check: refusing to let him annotate his own
view of somebody else's project would be a guard firing on the case the feature
exists for.

Keyed on Ekahau's cloud id where there is one, because that survives a rename on
either side, and on the normalised local path otherwise — the same key on both
sides of the wire, since a mark filed under a key the page never builds applies
to nothing and says nothing about having failed. The counts, the filters and the
row striping all read `_isExternal`, so honouring the override there covers all
three at once.

**The case the item singled out is the one it turned out to answer best.**
`_isExternal` returned `false` for everything when `currentUser` was empty, so
an account that comes back without one showed no External projects rather than
an unknown number. That is still the fall-back — but a mark now answers where
the owner comparison cannot, and there is a test for exactly that state.

**What it does not do**, and was not asked for: there is no "everything in this
site is external" rule, and no way to mark by owner address. Both are a
selection away from what the bulk action already does.

#### 4. ~~P3 — The Cloud Manager audit's coverage finding~~ — closed in v2.155.0

> **This item called A33 "the last finding" and it was not.** The audit has an
> **A34**, which no revision of this entry ever mentioned - see item 10, opened
> on 2026-09-21. The heading said "last" because the previous revision did, and
> each pass then checked the findings the *item* listed rather than the ones
> the audit has.

The whole-tool audit of 2026-09-18 is in
`docs/audits/cloud-manager-2026-09-18.md`, with the evidence per item, each
marked `[measured]`, `[traced]` or `[reported]`. **Thirty-one of its findings
are closed** — A0 in v2.139.1, the six P1s in v2.142.0, the twelve P2s in
v2.143.0, the twelve P3s in v2.145.0, A31 (CI never installs Node) in
`claude/ci-installs-node` — verified here: `.github/workflows/tests.yml` now
runs `setup-node@v4` on Node 22 — and A32, the notes describing a delete gate
that no longer exists, on 2026-09-19.

**A33 - the untested surface is the destructive one - is closed as of
v2.148.0**, and the table is kept because the shape of the gap is worth
remembering. All five behaviours the audit listed now have coverage that
executes them:

| Behaviour | At the audit | Now |
| --- | --- | --- |
| Transfer ownership | no coverage | `test_cloud_sharing_says_what_happened.py` executes it through five outcomes |
| Folder merge (`merge_execute`) | no coverage | `test_cloud_merge_empty_means_empty.py` moves a real file on disk |
| Duplicates tab delete | no coverage | `test_cloud_duplicates_delete_says_what_goes.py` drives the real dialog |
| `merge_preview` | no coverage | `test_cloud_the_destructive_actions_are_executed.py` runs it, including every refusal |
| `delete_cloud` / `delete_local` executing | no coverage | same file executes both, and checks every refusal left the file on disk |

**What is left is breadth rather than risk.** `merge_preview` has come off
the list below; the remainder are reads and bookkeeping, and the sharing
group is the most valuable of them. Counted at v2.145.0: **20 of 49**
`CLOUD_ACTIONS`, 149 of 302 top-level functions in `cloud.js`, and 42 of 58
inline handlers are not named in any test file. The actions are
`add_group_member`,
`create_local_folder`, `forget_all_recipients`, `get_duplicates`,
`get_my_group`, `housekeeping_stop`, `list_manual_matches`, `list_not_matches`,
`list_shares`, `mark_manual_match`, `mark_not_match`,
`open_login`, `refresh_group_shares`, `remove_group_member`, `remove_share`,
`reveal_in_explorer`, `toggle_group_share`, `unmark_manual_match` and
`unmark_not_match`.

**Do not read those three numbers against the audit's** (25 of 46, 214 of 380,
44 of 78). The audit's counting method was never committed as a script, so the
two are not the same measurement and the difference is not a trend. The one
reproducible number is `scripts/audit_source_string_tests.py`: 350 assertions
in 61 files at the audit, **346 in 58** now.

**The sharing group's six actions were the last of it, and they closed in
v2.153.0.** `tests/test_cloud_sharing_group_actions.py` executes
`get_my_group`, `add_group_member`, `remove_group_member`,
`toggle_group_share`, `list_shares` and `remove_share` against a fake shaped
the way `cloud_manager` really reads Ekahau, and pins the two that can take
somebody's access away: the whole current member list has to be echoed back on
a removal, and `enable: false` has to arrive as false rather than as something
truthy. `merge_preview` and `merge_execute` are covered by
`tests/test_cloud_merge_many.py` with real files on disk, and
`set_external_override` arrived with its own tests.

Each of those files also pins the **route table**, separately from the method,
because `CLOUD_ACTIONS` is a dictionary literal nobody executed: a method can
be perfect and unreachable, and a lambda reading the wrong key is invisible to
a test of the function it calls.

**The last eleven closed in v2.155.0, and every one of the 51 actions is now
named by a test.** The pairing decisions - `mark_manual_match`,
`unmark_manual_match`, `list_manual_matches`, `mark_not_match`,
`unmark_not_match`, `list_not_matches` - are in
`tests/test_cloud_pairing_decisions_persist.py`; the other five in
`tests/test_cloud_small_actions.py`.

They could not lose a project, which is why this sat at P3. What they *can* do
is make the ledger pair the wrong two things, quietly and permanently, and the
failure then looks like the matcher being wrong rather than like a stored
decision being wrong. So the key gets the attention: a pair is filed under
cloud id and normalised local path, and the same file named with the other
slash has to be the same decision.

Two of the five are more than bookkeeping and are tested as such.
`create_local_folder` writes to disk from a name typed by hand - it sanitises,
refuses a traversal, and refuses to land on a folder that is already there.
`reveal_in_explorer` hands a path from the page to the shell, so the
containment check is tested from outside the folder as well as inside it.

**The number is reproducible now, which it was not.** This item carried a
figure for five releases that nobody could re-derive, because the audit's
counting was never committed - the entry had to say so itself.
`scripts/audit_cloud_action_coverage.py` is that script, and
`tests/test_every_cloud_action_is_tested.py` holds the result at zero. It is an
absolute rather than a baseline because the number *is* zero: a new action now
arrives with a test or the suite says so.

**What the guard counts is deliberately generous** - the action's name
appearing anywhere under `tests/`. That over-reports, and `delete_cloud`
spending the whole audit period in one docstring and nowhere else is exactly
how the gap stayed invisible. Over-reporting is the right direction for a guard
against forgetting and the wrong direction for judging whether a test is any
good, which is what the ratchet in
`tests/test_a_test_must_be_able_to_fail.py` is for. The two work together; one
does not stand in for the other.

Related, and already ratcheted rather than listed as work: 114 assertions in 19
test files that execute nothing at all
(`scripts/audit_tests_that_never_run_anything.py`). That debt is held per file
in `tests/source_string_assertion_baseline.json` and can only go down — see
CLAUDE.md § "A test that would pass with the feature deleted is not a test".

#### 9. ~~P2 — The "only name controls that exist" guard reads one file~~ — shipped in v2.153.0

`tests/test_named_controls_exist.py` now asks the question of every page and
every script in `web/`, not just `cloud.js`. Nothing to turn on: it runs in the
suite, and `scripts/audit_named_controls.py` prints the inventory — five
instructional control names across four files today, all of them real.

**The two failed attempts recorded on this item were both right about the idea
and wrong about one detail, and the detail was in the same place twice.**

* *Searching the source matched a comment in `report.js`* explaining why the
  button had been renamed. The fix is to strip comments — but the reason the
  comment survived is the part worth keeping: `report.js` contains a character
  class of the characters a file name may not hold, and a double quote is one
  of them. A scanner that knows only about quotes sees that quote inside the
  regular expression, decides a string has started, and never finds its end.
  Every comment after it in the file then survives as though it were code. So
  the stripper recognises regular expressions, and a test builds that exact
  shape and fails without it. **The guard was not too naive; its stripper was
  broken, and the two look identical from outside.**
* *Searching for `>Name<` across `web/` matched the instruction itself* — a page
  saying "use <b>Cover image</b>" contains that string, so every instruction
  satisfied itself. Bolded markup is removed from the haystack before the
  needles are looked for.

The third problem the item named is handled as it asked: a label built by
concatenation — `'Cover image' + '…'` — never appears whole anywhere, so
adjacent string literals joined by `+` are folded together before the corpus is
built. **A rendering harness turned out not to be needed**, which is worth
saying because the item proposed one: most labels in this suite are built at
run time from data the page does not have until a file is loaded, so rendering
each page would have missed them too.

`TheCheckCanFailTests` is the load-bearing class. A guard for a defect that has
already been fixed proves nothing unless it is shown to fail on that defect, so
it reconstructs all three failures and requires each to be caught — and the
whole thing was verified by putting the real v2.150.0 defect back into
`settings.html` and watching the suite go red.

The Cloud Manager guard stays. Two checks of one property, with different
corpora, is a state worth noticing rather than an argument for deleting one.

#### 10. P3 — A34, the last audit finding, was never on this list

`docs/audits/cloud-manager-2026-09-18.md` has an **A34: tests that pin wording
rather than property**. Item 4 tracked A0 to A33 and closed on A33; A34 has
never appeared in this file.

**It is smaller than the audit says, and half of what it says is no longer
true.** Measured on 2026-09-21 with `scripts/audit_source_string_tests.py`:

| file the audit names | then | now |
| --- | --- | --- |
| `test_cloud_modals_are_self_sufficient` | the whole file | 15 source-string assertions - the real remainder |
| `test_cloud_replace_project` | two assert on `__doc__` | still two |
| `test_cloud_ops_queue` | named | 2, and the class the audit named was rewritten in v2.141.0 |
| `test_cloud_sync_everything` | named | 0 |
| `test_cloud_sync_plan` | named | 0 |

The audit's sharp sentence is *"editing a docstring breaks the suite while
deleting the safety ordering does not"*. **The first half is still true and was
demonstrated**: changing one word of `replace_cloud_project`'s docstring -
`inverted` to `reversed`, no behaviour change at all - fails the suite. **The
second half is not true any more.** `test_the_old_project_is_deleted_only_after
_the_upload`, `test_a_failed_upload_deletes_nothing` and
`test_an_unverifiable_upload_deletes_nothing` sit in that same file and cover
the ordering properly. So what is left is a documentation edit that can turn CI
red, not a safety property with nothing behind it.

**Done** is: those two `__doc__` assertions replaced by something that fails
when the *ordering* changes rather than when the prose does, and
`modals_are_self_sufficient` converted the way `test_cloud_sync_direction.py`
was - render, pull the handler out of the markup, run it. The
per-file numbers in `tests/source_string_assertion_baseline.json` come down as
that happens; they are the measurement.

#### 11. P3 — The release ZIP carries the internal engineering documents

`scripts/build_release.py` ships all of `docs/` except `docs/releases`, so
every install folder gets `docs/audits/cloud-manager-2026-09-18.md` (718 lines
of internal audit) and `docs/reverse-engineering/` (three browser capture
scripts and their README). `docs/USER_MANUAL.md` and `docs/wall-types.md` are
the two that belong there.

**The decision has already been made in principle** - `docs/releases` is
excluded with the reasoning written beside it: *"not worth 168 files of
internal changelog in a user's install folder"*. These two directories are the
same category and were not considered when that exclusion was added.

**This is tidiness, not exposure, and the difference is worth stating** so
nobody escalates it. The audit is technical throughout - it was checked for
reported speech and quotes none, and `tests/test_no_real_world_data.py` already
reads every tracked file, so there is nothing about his sites or colleagues in
either. The repository is public, so none of it is secret either. It is simply
not for the person who downloaded a wireless tool.

Adding `"audits"` and `"reverse-engineering"` to `EXCLUDED_DIRECTORY_PARTS`
does it, alongside the test that pins the payload.

---

### Report

#### 5. ~~P2 — Column grid references on section pages~~ — shipped in v2.146.0

A **Grid** column on the Antenna Aim Sheet and AP Installation tables, giving
each AP its nearest column-grid intersection. Two clicks and two labels per
floor; nothing is read off the drawing. **Column grid reference** in the options
panel of the Configure step, off by default, with **Set up column grid…**
beneath it. Calibration in `~/.wd_wireless_tools/report/grids.json`, keyed by
project id and floor id, never in the `.esx`.

The three cases two points cannot describe — an interrupted bay, a rotated or
skewed grid, a building carrying two grids — are handled the way this item asked
for: the derived grid is drawn over the plan so a bad fit is visible, and
**Turn off for this floor** is the answer. Nothing is guessed at.

**The second half shipped in v2.153.0.** The reference now prints **under the
marker label on the plan**, on the AP Placement Map: **Add the column grid
reference to each label** in the options panel of the Configure step, off by
default, with **Set up column grid…** beside it. It reads the same calibration
the tables do, so the plan and the table cannot disagree about where C-4 is —
a test compares the two and fails if they ever do.

It is the first of the extras on a marker's second line, ahead of model,
channel and height: the others describe the access point, and this one says
where to stand to find it. An AP with no coordinates, on an uncalibrated floor,
or outside the lettered area contributes nothing rather than a dash, because a
dash printed on a drawing reads as a reference somebody failed to fill in.
Measured off the printed sheet at 6.7pt, above the report's 6pt floor.

**One decision worth revisiting if it reads wrong on site.** The reference is
the **nearest intersection** — `C-4` — because that is how a grid reference is
spoken and it sends somebody to a column they can stand under. On a 40-50 ft bay
the worst case is half a bay of walking. The alternative is naming the bay
(`C-D / 4-5`), which is precise and twice as wide in a table column. Changing it
is a one-line change in `gridRefForPoint`.

#### 6. ~~P3 — Change / Audit report~~ — shipped in v2.153.0

It was the last card marked **Coming soon**, and the gallery refuses to open a
card in that state, so the card had been visible and unusable throughout.

**How it is used.** Open the newer project the way you always do; that one is
the *after*. Pick **Change / Audit Report** in the template gallery, then in
the options panel of the Configure step use **Choose the earlier .esx…**, under
**Earlier project to compare against**. Neither file is written to and the
earlier one is only read. The document is built at the Review step.

The options beneath it: **Count as moved when it moved** (default *0.5 m
(1.6 ft) or more*), **Per-floor overlay drawings** (on), **Measurement units**
(feet), **Cover page** (on) and **AP notes pages** — which defaults to *Never*
here rather than *Auto*, because this is usually the document that gets handed
over and site notes are often private working annotations.

**Matching is by Ekahau's id first and by name second, and never by position.**
An id survives every edit, so where the after-file is a descendant of the
before-file everything pairs exactly and a rename is free. Name is the fallback
for an AP deleted and re-added, it has to be unambiguous on both sides, and the
report says how many pairs were found that way because that is a judgement
rather than a fact. Position is deliberately not a key: two APs that swapped
places are two moves, and matching on position would report that as nothing
having happened.

**The trap worth knowing about is a re-cropped floor plan**, and it is the part
that took the thinking. Coordinates in an `.esx` are measured from the corner of
the floor plan image, so running PlanTrim between the two saves shifts every
coordinate on that floor by the crop offset — seventy access points all
"moved", burying the two that really did. Where a floor's image has *changed
size* the two coordinate spaces are known not to be comparable: the shift is
measured as the median displacement, taken out, and reported in its own section
on the page. Where the image is the same size nothing is compensated, because
there a displacement is real and explaining it away would hide every move on
the floor — the more dangerous of the two failures, and it has its own test.

**`tools/esx_compare.py` was not reused, and the reason is worth recording** so
it is not proposed again. That module answers "do these two archives differ",
per zip member, in Python on disk. This question is "what did somebody do to
this design", per access point, in the browser against two already-parsed
projects. They share no inputs and no output; one is a file comparison and the
other is a design comparison.

**What it does not do.** Wall, area and note changes are not compared — the
item asked for access points and that is what it does. Nothing is written to
either file.

---

### PlanTrim

#### 7. ~~P3 — Only PNG, JPEG and SVG floor plans can be cropped~~ — shipped in v2.153.0

PlanTrim now crops **PNG, JPEG, BMP, GIF, TIFF and WebP**, plus SVG as before,
and each one is written back as the format it already was — an `.esx` carries a
GIF only because Ekahau accepted a GIF, and handing back a PNG under the same
image id is not a decision this tool should make. Nothing has to be turned on.

**The item said "Pillow already reads all three" of BMP, WBMP and GIF. Two of
the three.** Pillow ships no WBMP codec in either direction, and that is now
asserted against the installed Pillow rather than assumed, so a future version
that gains one fails the test and reopens this deliberately. WBMP is out of
reach from the other end too: it has no magic number — its first bytes are
`00 00` — so only `images.json`'s `imageFormat` can name one. It is named from
that declaration and refused **by name** now, rather than as "unrecognised
image format", which is the difference between a reader knowing what to do next
and not.

Two things came out of the work that the item did not ask for:

* **The magic numbers had two homes** and they disagreed about four formats.
  `folder_organizer` sniffed a plan to name an extract, `esx_trimmer` sniffed
  the same bytes with a shorter list to decide whether it could be cropped.
  Both call `tools/image_format.py` now. Two answers to "what is this file" is
  the shape of the fault that once named an SVG `.png`.
* **An image holding more than one frame is refused** — an animated GIF, a
  multipage TIFF. A crop would keep the first and drop the rest without
  erroring, and a loss that leaves a file which opens and looks right is the
  worst shape a loss can take.

### Suite-wide

#### 8. ~~P2 — 831 lines of CSS still live in eight pages rather than the stylesheet~~ — shipped in v2.154.0

All eight `<style>` blocks are in `wd-tools.css` now — 841 lines out of
`ap-rename`, `capacity`, `plantrim`, `prep`, `settings`, `setup`, `walls` and
the landing page. Nothing about any page changed on screen: **every element on
all fifteen pages computes to exactly what it did before, at 1920 and 1366, in
Chrome, Edge and Firefox** — 90 captures, zero differences.

**Moved verbatim, and appending is the safety property.** No rule was
reformatted, reordered or merged. An embedded block sits after the `<link>` in
document order, so a page rule already beat a stylesheet rule of equal
specificity; appended to the end of `wd-tools.css` it still does. Anything
tidier — sorting, deduplicating, scoping by body class — changes specificity or
order and puts a tie in play, and a flipped tie is the two-pixel break that
started this.

**The six drifted selectors are scoped to `.setup-wrap`.** Both pages carry
`body.tool-home`, so the body class could not separate them; the wrapper Setup
already had could. Three of the six match elements that JavaScript builds into
`.sf-list` and are never in the initial DOM, which is why the verification has a
rule-level half at all.

`tests/test_settings_and_setup_stay_different.py` is the guard, and it is the
part worth keeping: it renders the real list markup into each page's real
container, measures both, and fails if Settings and Setup ever agree — in
either direction. Removing the scope makes it fail in all three browsers,
naming all nineteen properties that collapsed.

**The four selectors that collide with `wd-tools.css` were fewer than the entry
thought, and the inline `style` attributes are untouched.** `body.wd-resizing`,
`body.wd-resizing *` and `body.tool-plantrim` collide; appending keeps the page
copy winning, as it did. The five inline attributes stay exactly where they
were.

**One thing the entry did not predict, and it would have made the check
meaningless.** `pages/landing.html` links `assets/wd-tools.css` *relative to
itself*, and the Pages build copies it to the site root with `assets/` beside
it — so served from `web/pages/` that link 404s. Captured that way the page has
no stylesheet at all, every element falls back to browser defaults, and two
such captures agree perfectly whatever was done to the CSS. The harness stages
the page the way it is really deployed.

**Seventeen tests failed on the move and not one of them was testing
behaviour.** They read a page's HTML looking for a CSS rule, because that is
where the rule was when they were written. `tests/css_source.py` answers "what
styles this page" instead, so the next move breaks nothing. Two of the
seventeen were provenance rules — *"scoped to walls.html so the shared sheet
stays out of this change"* — which recorded that some earlier change had not
touched `wd-tools.css`. Reasonable of that change; not a rule about where CSS
belongs, and this item is the decision that overrides them.

Converting those tests took the source-string assertion count from **342 to
327**.

**The method, kept because it is the reusable part:**
`scripts/capture_computed_styles.py` and `scripts/compare_computed_styles.py`
run a server on each side and compare `getComputedStyle` for every element on
every page, index aligned, plus every selector's declarations in cascade order.
The second half is what covers elements that only exist once a file is loaded.
Two mistakes in building it are worth not repeating: the page list must not be
derived from the thing being changed — deriving it from "has a `<style>` block"
emptied it the moment the move landed — and `<style>` is itself an element, so
counting it makes every changed page differ by one and the comparison refuses
before it looks at a property.
---

## Awaiting a decision, not work

Blocked on a call rather than on effort, so they can be answered together.

**Nothing is waiting on him right now.** The four menu-label questions were
answered on 2026-09-19, and the DWG question that replaced them was answered
the same day — both are under "Decisions already made" below.

The heading stays with the section empty, deliberately. It is where an item
blocked on his say-so goes, and
`tests/test_server_and_assets::test_backlog_separates_work_from_decisions`
requires all three sections to exist. That guard is why: a settled decision
sitting in the work queue, or a question filed as though it were effort, is how
the queue stops being trusted. The 2026-09-19 pass deleted this heading on the
grounds that it was momentarily empty, and the test caught it.

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

### What a DWG becomes inside an `.esx` — the lost finding, recovered 2026-09-19

**This closes an item that was an IOU rather than a task.** It read: *"A
finding about going from DWG to `.esx` was established in an earlier session
and never recorded, so the next session will redo the work."* That is all it
said. Nobody since knew what the finding was, so it stood BLOCKED — it could
not be worked on and it could not be closed.

The 2026-09-19 pass found that the substance had since been written down
independently, in `tools/esx_trimmer.py` and the User Guide, and put the
description to him. His answer: *"All of what you said was true and I can't
think of anything else that goes with that."* So it is recorded here in full,
in one place, because the failure mode this item existed to flag was the
knowledge living nowhere.

**What happens to a DWG:**

* **A DWG or PDF imported into Ekahau lands as a vector (SVG) floor plan**, not
  a raster one.
* **Ekahau usually writes a companion raster of the same drawing beside it**,
  for rendering. So one floor can carry two images of the same building.
* **The two are different pixel sizes, and the ratio is not shared between
  axes.** Ekahau renders a 792x612 plan to 5000x3863 — but 612 x (5000/792) is
  3863.6, so the rasteriser rounded. Scaling both axes by one ratio therefore
  disagrees with the file by a fraction of a pixel, and a tool that insists on
  one ratio refuses every real drawing over its own rounding artefact. PlanTrim
  scales the axes independently for exactly this reason.
* **A vector plan is cropped by moving its window, not by cutting pixels** —
  the `viewBox` is edited, so it stays sharp at any zoom. The companion raster
  takes the same region in its own resolution.
* **An SVG whose `<svg>` root cannot be read is refused**, because there is no
  window to move.

**Where it lives now**, so a future session finds it without reading this file:
`tools/esx_trimmer.py`'s module docstring carries the mechanism and the
rounding reasoning; `docs/USER_MANUAL.md` § "Vector plans — DWG and PDF
imports" says the same thing for a reader.

**The lesson is the item, not the finding.** A conclusion reached in
conversation and not committed is gone the moment the session ends, and what
survived here was a note saying something had been lost — which is better than
nothing and much worse than the finding. Write the conclusion down where the
code is, at the time, not a reminder to write it down later.

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
