# Cloud Manager — full audit, 2026-09-18

Against **v2.139.0** (Cloud Manager 4.57.0), the whole tool: `web/cloud.html`,
`web/assets/js/cloud.js` (9,044 lines, ~380 top-level functions),
`tools/cloud_manager.py` (3,757 lines), `tools/cloud_realign.py`, the 46
`CLOUD_ACTIONS` entries in `server.py`, and the 37 `tests/test_cloud_*.py`
files. Every filter, every list, every action.

Every project, site, address and email in this document is invented.

## How to read this

Findings are marked by how they were established, because that is the
difference between a fact and a reading:

* **[measured]** — the real shipped function was executed and the result is
  quoted. These are facts.
* **[traced]** — read end to end through the call chain, with the deciding
  lines named. Reliable, but nothing was run.
* **[reported]** — surfaced by a reading pass and not independently
  re-executed here. **Confirm before acting.**

Priorities follow `BACKLOG.md`: **P1** blocking · **P2** wanted · **P3**
future.

## How the `[measured]` findings were run, because it is reusable

The repo's Node probes slice functions out of `cloud.js` with a `cut(from, to)`
helper and stitch the pieces together. That works, but the slices have to avoid
each other — one test carries a comment explaining that reaching from the first
function to the last pulls `const ICONS` in twice — and anything the slice
misses has to be re-stubbed by hand, which is how a stub comes to invent a
contract the real function does not have.

**The whole file evaluates.** Given a DOM stub of about 120 lines built by
parsing `web/cloud.html` for its tags and ids, plus stubs for `localStorage`,
`navigator`, `fetch`, `matchMedia` and `WD`, `cloud.js` evaluates end to end in
Node with every one of its ~380 functions callable and wired to each other:

```js
const src = fs.readFileSync('web/assets/js/cloud.js', 'utf8');
(0, eval)(src + tail);        // `tail` closes over the module-scope `let`s
```

Two things make it work. `cloud.js` is a classic script, not a module, so its
top-level `function` declarations become globals — which is also why its inline
`onclick` handlers resolve. And its module state (`data`, `currentTab`,
`activeFilter`, `activeLetter`) is declared with `let`, so it is *not* reachable
through `globalThis`; appending a small setter block to the source before
evaluating puts those setters in the same scope:

```js
;globalThis.__set = (k, v) => { switch (k) { case 'data': data = v; break; /* … */ } };
```

With that, `updateDashboard()` writes real counts into the real chips parsed
out of the real page, and `renderLedger()` builds the real `pass`/`projPass`
predicates — so a count and its list can be compared without the test
supplying a predicate of its own. That last point is the gap in
`test_cloud_a_count_matches_its_list.py`, which hand-writes the `pass` it
passes to `renderSitesTree` and therefore cannot see a divergence between what
a chip counts and what the list actually filters on. A7, A8 and A9 were all
found this way.

Worth knowing: `node script.js a b` puts the script path in `argv[1]`, so a
probe that reads `process.argv[1]` as its first argument reads *itself*. The
repo's tests use `node -e PROGRAM`, where `argv[1]` is the first real argument
— match that, and pass `encoding="utf-8"` to `subprocess.run`, or a rendered
arrow comes back mangled on Windows and intact in CI.

---

## Already fixed

### A0. `settlePair` sent its two arguments the wrong way round — fixed in v2.139.1 [measured]

`web/assets/js/cloud.js:3643`. `pyApi` maps positionally onto
`['path', 'cloudId', 'opId']`; `settlePair` passed `(cloudId, localPath)`, so
the cloud id arrived as `path`:

```
settlePair          sends: {"path":"3f2a9c14-…","cloudId":"D:/…/Survey.esx"}
checkRealDifference sends: {"path":"D:/…/Survey.esx","cloudId":"3f2a9c14-…"}
```

`compare_with_cloud(local_path, cloud_project_id)` hands the first to
`_assert_inside`, which correctly refuses a UUID. Run against the real guard:

```
ACCEPTED : C:\Projects\ACME\Survey.esx
REFUSED  : 3f2a9c14-7b6d-4e51-9a02-8c55d1e7b430
```

So the call **could not succeed for anybody, on any row**, in all three of its
uses — after the internal-name fix (`:3795`), after a push (`:3875`), after a
pull (`:5929`). Each ended with a red toast reading *"Could not confirm the
result: Local path is outside the configured folder"*. Introduced in
**v2.120.0**, the release whose entire point was that an action leaves the row
saying what is now true. Dead for 19 releases.

That sentence is quoted in `_assert_inside`'s own docstring as the symptom
that led the guard to be loosened to a textual comparison. The reparse-point
reasoning there stands on its own, but no containment guard can accept a bare
UUID — so the symptom survived the fix aimed at it.

**The test pinned it.** `test_cloud_row_detail_band` asserted `calls[1][2]` is
the local path — true only while the arguments are swapped. One position out
of a pair is not a contract. Both arguments are asserted now, and
`tests/test_cloud_settle_names_its_arguments.py` asserts the request body by
the keys `server.py` reads rather than by position. It fails on the old code.

---

## P1 — can destroy work that cannot be recovered

> **All six are closed, in v2.142.0.** Each is a separate commit carrying a
> test that fails against the code before it. They are left here in full
> rather than deleted, because the reasoning is why each guard exists — and a
> guard whose reason is not written down is the one a later session removes as
> redundant.
>
> A2 needed no code of its own; its live half was A1. See the note under it.

### A1. The uploaded project is identified as "the first id that was not in the listing a moment ago" [traced] — **fixed in v2.142.0**

`tools/cloud_manager.py:2611-2617`:

```python
new_ones = [p for p in after if p["id"] not in before_ids]
new_project = new_ones[0]
```

No name check, no "exactly one" rule, no use of the local file's internal id.
Four irreversible things then happen to whatever that id names: it is renamed
to his filename (`:2625`), assigned to his site (`:2649`), **downloaded back
over his local `.esx`** (`:2681-2694`), and in `replace_cloud_project` his
original cloud project is **deleted** (`:2413`).

`_await_new_project`'s own docstring (`:2454-2476`) forbids exactly this:

> "a project that was not there a minute ago" is not good enough on an account
> other people also write to … taking the first new row would eventually
> delete his old project on the strength of somebody else's new one.

That careful rule — positive identification by the `.esx`'s internal project
id, else *exactly one* new project with an expected name — is applied **only
on the fallback path**. The primary path does the thing the docstring says
must never be done.

Failure scenario: a colleague uploads to the shared account during his upload.
Their project is renamed to his filename, filed into his site, downloaded over
his local file, and his cloud project is deleted.

**Compounding:** `_verify_uploaded` (`:2518-2556`) is circular. Its docstring
states its scope honestly — it confirms *that id is present in the listing* —
but the id came from that same listing. The delete is therefore conditional on
nothing having raised, not on a positive verification.

### A2. The push path overwrites the local `.esx` with no backup [traced]

`tools/cloud_manager.py:2691-2694` — the sync-back writes `.wd-syncback.tmp`
and `os.replace`s over the source. The write is atomic; there is **no
`_backup_target` call and `keep_local_backups` is never consulted**. Every
other local overwrite in the file backs up first and refuses if the backup
cannot be written (`verify_replace_local:2874-2891`,
`_rewrite_project_json:1862-1870`).

Combined with A1, a mis-identified project is written over his local file with
nothing in `backups/`.

> **Superseded in part, v2.141.0.** Backups were removed from the whole suite,
> so "every other local overwrite backs up first" is no longer true of any of
> them - `verify_replace_local` and `_rewrite_project_json` both write
> atomically and keep nothing. The *comparison* in this finding is therefore
> void; **the finding itself is not.** What made A2 serious is A1: a push
> writes over a local file on a project identified by "the first id that was
> not in the listing a moment ago". That is still true, and the local file is
> now the only copy. See "Backups were removed, and that is the design" in
> CLAUDE.md before reading this as an argument for putting them back.

> **Closed in v2.142.0, by A1 rather than by a backup.** The remaining half —
> "a push writes over a local file on a project identified by the first new
> row" — is exactly what A1's fix removes: the sync-back is reached only for a
> project positively identified as the one just uploaded, and when nothing can
> be identified the upload renames nothing, files nothing and writes nothing
> back. The write itself was already atomic (temp file, then `os.replace`), so
> it cannot truncate. Nothing was added that copies a file aside.

### A3. `replace_cloud_project` never re-checks direction before deleting [measured] — **fixed in v2.142.0**

`tools/cloud_manager.py:2275-2445` contains **zero** references to
`modifiedAt`, `_NEWER_TOLERANCE_S` or `local_newer` (grepped: 0 matches). The
pull direction has exactly that guard server-side
(`verify_replace_local:2852-2864`) — "the server wins, it just re-read both."

Failure scenario: the ledger is drawn at 08:55 saying `local_newer`; the cloud
copy is saved at 08:58; Local → Cloud runs at 09:00. The newer cloud project is
deleted and replaced with the older local file. The only thing standing in
front of that delete is a client-side snapshot.

### A4. Cancel on a running cloud write does nothing, then reports it as cancelled [measured] — **fixed in v2.142.0**

`cloud.js:488-494`. `opCancel` sets `op.cancelFlag.aborted = true`. Every
occurrence of `cancelFlag`/`aborted` in the whole file:

```
421:    cancelFlag: { aborted: false },
449:      const result = await spec.run(id, op.cancelFlag);
459:      op.status = op.cancelFlag.aborted ? 'cancelled' : 'done';
461:      op.stage = op.cancelFlag.aborted ? 'Cancelled' : 'Done';
491:  op.cancelFlag.aborted = true;
```

**No `run` implementation reads it**, and `pyApi` has no `AbortController`.
The status is assigned *after* `await spec.run(...)` has returned — i.e. after
the work finished. No op sets `cancelable: false`, so Cancel renders on all of
them.

Failure scenario: Cancel "Replacing cloud X with your local copy". The upload,
the verify and **the cloud delete** all complete. The card reads *Cancelled*,
and the run body still toasts *"the old one was removed"*. A cancel button on
an irreversible delete that does nothing and then claims it worked.

### A5. Merge's "delete the source folder afterwards" is ticked by default and judges "empty" with a walk that skips `archive/` and `output/` [reported] — **confirmed, and fixed in v2.142.0**

`web/cloud.html:372` — `<input type="checkbox" id="mergeDeleteSrc" checked>`.
`cloud.js:6337-6350` goes straight to `pyApi('delete_local', …)` with no
dialog. `cloud_manager.py:3688-3694` decides emptiness with `_walk_files`,
which skips `backups, backup, output, outputs, archive, archives, .git`
(`:977`), and `delete_local` is `shutil.rmtree` (`:2256-2272`) — no recycle
bin, no backup.

So a source folder holding exported reports in `Output/` and last year's
surveys in `Archive/` is reported empty, and permanently deleted, having never
been named on screen. The "⚠ this folder holds N source files" warning reads
the *same* skip list, so it says zero.

**Not independently verified — confirm before acting.** It is the single most
destructive path found.

### A6. On the Projects tab the cloud and local checkboxes are the same control [measured] — **fixed in v2.142.0**

`cloud.js:2610` builds matched Projects-tab rows with `key: 'p:' + p.cloud.id`
and **no** `cloudCheckKey` / `localCheckKey`. Both the Sites tab (`:2691`) and
nested project rows (`:3198-3199`) set both:

```
sites   : cloudCheckKey: 's-c:' + id,  localCheckKey: 's-l:' + path
nested  : cloudCheckKey: 'ct-c:' + id, localCheckKey: 'ct-l:' + path
projects: (neither — both cells fall back to r.key)
```

`bulkDelete` then expands `kind: 'pair'` into a cloud item **and** a local
item. So ticking the cloud box of a matched project on the Projects tab
deletes the local `.esx` too. CLAUDE.md documents per-side independence; this
is the one tab where it does not hold.

**Compounding [reported]:** the dialog says, in adjacent sentences, *"Permanently
delete 1 matched pair (both cloud and local sides). … Local copies (if any)
are not touched."*

---

## P2 — the tool states something untrue

> **All twelve are closed, in v2.143.0**, across seven commits, each carrying
> a test that fails against the code before it. Four of the `[reported]` ones
> were confirmed by measurement on the way in; none turned out to be wrong.
>
> One decision worth keeping rather than rediscovering: the chips still count
> the account rather than the search (A10). Making them follow it would put a
> second spelling of the search predicate into the counting code, which is the
> shape of defect this file has already paid for twice — so the narrowing is
> stated above the list instead, the way the owner filter has always stated
> its own.

### A7. The Auto-assign banner counts the filtered list; the button acts on everything [measured] — **fixed in v2.143.0**

`cloud.js:2778` builds the banner from the rows that survived the filter and
search. `cloud.js:3125` runs the action from `_visibleSiteRowsForBatch()`
(`:3139`), which **rebuilds every row from `data` with no filter, no search,
no letter**. Measured, three unassigned projects across two sites, search box
containing `alpha`:

```
banner offers  : 1 [ 'alpha one' ]
button assigns : 3 [ 'alpha one', 'bravo one', 'bravo two' ]
```

This writes to Ekahau. Two projects he never saw, in a site he had filtered
away, are assigned — and the ops deck shows three operations for a button that
said one.

### A8. The External chip can never be reached on the Sites tab [measured] — **fixed in v2.143.0**

`cloud.js:1570-1571`:

```js
_setCount('dExternal', isSitesTab ? kidExternal : externalCount);
_showFilter('external', cloudy && externalCount > 0);
```

`externalCount` is incremented only through
`rowIsExternal = (c, l) => !isSitesTab && _isExternal(c, l)` (`:1490`), so on
the Sites tab it is always 0. The count is written from `kidExternal`; the
*visibility* is decided by `externalCount`. Measured, owner filter All, one
project owned by a colleague:

```
SITES tab    : dExternal = 1   chip hidden = true
PROJECTS tab : dExternal = 1   chip hidden = false
```

The Sites tab is the default view (`lastFilesKind()`), and the chip's own
tooltip in `web/cloud.html:133` describes Sites-tab behaviour he cannot
invoke.

### A9. The search box filters sites but not the projects inside them [measured] — **fixed in v2.143.0**

`renderTreeChildren` (`cloud.js:3169`) takes `hit` as its second parameter and
**never references it**. A site survives via `childHit`, `_searching` forces it
open, and then every project in it is drawn. Measured, searching one project's
exact name in a site holding two:

```
site rows drawn    : 1
project rows drawn : 2   (expected 1)
```

On a real site of a dozen surveys, searching for one gives him all twelve.

### A10. No chip count accounts for the search box, and the ledger head ignores the A-Z letter [reported] — **fixed in v2.143.0**

`updateDashboard` never reads `#searchBox`; `renderLedger` filters on it.
Nothing on screen says the search is narrowing the list (the owner filter has
`#ownerFilterNotice`; the search has nothing). Separately, `nCloud`/`nLocal`
are computed before the letter filter is applied — and on the tree, orphans
*are* letter-filtered while `visible` is not, so one number is built from two
filter states. Selecting a letter with no rows under it reportedly yields zero
rows, no group headings and **no message at all**.

### A11. `_share_message_is_failure` decides success by looking for nine English words [measured] — **fixed in v2.143.0**

`tools/cloud_manager.py:2097-2105`. Run against realistic messages:

```
  success <- 'Access is forbidden'
  success <- 'No such user'
  success <- '403 Forbidden'
  success <- 'Share limit reached'
  success <- 'User is not a member of your organization'
  success <- 'Utilisateur introuvable'
  success <- {'code': 'USER_NOT_FOUND'}
  success <- False
  FAILURE <- 'User not found - invitation sent'
  FAILURE <- 'Added (external users cannot edit)'
```

Wrong in both directions. A failed share is toasted as *"Shared with …"*, and
the address is persisted into Recent Recipients — the one thing that store
exists to avoid.

### A12. A successful ownership transfer is reported as a failure [traced] — **fixed in v2.143.0**

`EkahauAPI.transfer_ownership` (`:500-512`) returns
`{"status": r.status_code, "result": data}` with `data = {}` on an empty body.
`cloud_manager.py:3291` does `result.get("result", {}).get(project_id)`, gets
`None`, and returns `{"error": "Transfer failed: …"}`. Every other write
helper in the file has an explicit empty-body fallback (`:486`, `:496`,
`:585`) precisely because Ekahau returns empty bodies; this one does not.

The transfer has happened and is irreversible from this tool. The UI says it
failed, leaves the armed button in place, and a second click reports *"Only
the owner (…) can transfer this project"* — because it now is not his.

### A13. A cached comparison is never invalidated, and a settled row hides a newer cloud copy [reported] — **fixed in v2.143.0**

`_compareResults` is written at `cloud.js:3645` and `:3672` and deleted only by
`fixInternalName`. Nothing clears it after the local file is rewritten and
nothing validates it against the mtimes a refresh just returned.
`comparisonIsSettled` then drives `isOutOfSync`, and at `:4210` a settled row
renders **no action at all** — so a genuinely newer cloud copy becomes
invisible until the page is reloaded.

### A14. The bulk planners offer a push the row itself refuses [reported] — **fixed in v2.143.0**

`canPushToCloud` requires `iOwn(r.cloud)`; the row renders a disabled control
for a colleague's project. `syncPlan`'s `mayPush` and `syncEverythingPlan`'s
`takePair` test only `PUSHABLE_MATCH_TYPES`. The result is a new duplicate in
the shared account followed by a 403 on the delete — unattended, inside a Sync
all run.

### A15. Bulk share reports success when the share entirely failed [traced] — **fixed in v2.143.0**

`cloud_manager.py:3227-3260` catches every exception into
`results["emailError"]` / `results["groupError"]` and then sets
`results["ok"] = True` unconditionally — there is no `error` key on any
failure path. The client tests only `r.error` (`cloud.js:5736`), falls
through, and toasts:

```js
const who = _shareNameList(r.emailsAdded || emails);
toast(`Shared with ${who} on ${n} project${n === 1 ? '' : 's'}`, 'success');
```

`emailsAdded` is set only on success, so on failure it falls back to the full
typed list — the toast names every recipient and claims the share landed on
every project.

The group path is OFF-then-ON across all selected ids. If the OFF succeeds and
the ON raises, the group is **removed** from every selected project and the
toast still says it was shared.

### A16. `change_share_role` is remove-then-add and never checks the add [reported] — **fixed in v2.143.0**

`cloud_manager.py:3532-3551` checks the remove step and returns `ok: True`
whatever the add said. A rejected re-add leaves the colleague with **no
access**, reported as the new role.

### A17. Paired rename leaves the name inside the file stale [reported] — **fixed in v2.143.0**

`confirmRename` calls only `rename_cloud` / `rename_local`; nothing touches
`project.json`. Ekahau stamps `modifiedAt` on a rename while the local
`internalMtime` does not move, so every pair he renames immediately reports
*"Cloud newer · renamed"* — which is the condition `tools/cloud_realign.py`
exists to clean up afterwards. `set_internal_project_name` already does this
correctly elsewhere.

### A18. Move-to-site: a typed destination that was never clicked is discarded [reported] — **fixed in v2.143.0**

`_resolveDest` reads only `t.destValue`, written only by `_taPick` /
`_taPickNew`. Typing a site name in full and clicking Move uses the previous
auto-guess instead, while the field still shows what he typed. Related: the
previewed path is the raw site name, but every server writer sanitises it
first, so the preview and the destination disagree.

---

## P3 — wrong, but visible or harmless

> **All twelve are closed, in v2.144.0**, in two commits — the matching engine
> and the client — each with a test that fails against the code before it.
> Six of the eight `[reported]` ones were re-measured on the way in and all
> six held.
>
> Two of them were filed here and were not harmless. A26's stream of false
> "taking longer than expected" toasts was cosmetic, but **A27** — a failed
> background poll replacing the list and leaving `data` as an error object, so
> every later re-render silently drew nothing — and **A30** — every
> Duplicates-tab delete, including irreversible cloud deletes, gated only by a
> truncatable `window.confirm()` — both belong higher than P3. Severity was
> judged by the size of the code involved rather than by what it costs, which
> is worth remembering the next time a list like this is triaged.
>
> **A28** is the one item closed without being removed. The undo path is
> genuinely unreachable — nothing supplies an undo function — but it is the
> deck's own machinery, so the latent expiry race was fixed and the code left
> in place rather than deleted out from under whoever wires it up.

* **A19. `_building_token` breaks on 3-digit building numbers [measured].** — **fixed in v2.144.0**
  The regex backtracks to the `bld` alternative and captures the `g`:
  ```
  'Bldg 3'   -> '3'      'Bldg 100'  -> 'G'
  'Bldg B'   -> 'B'      'BLDG 123'  -> 'G'
  'Bldg 99'  -> '99'     'bldg. 250' -> 'G'
  ```
  Two different 3-digit buildings therefore produce the same token, and the
  guard sees no conflict:
  ```
  discriminators_reason('SITE1 1200 Main St Bldg 100',
                        'SITE1 1200 Main St Bldg 200') -> None
  ```
  That is precisely the case the guard was written for. `'Bldg 3'` vs
  `'Bldg 5'` is still caught, which is why it has looked fine.

* **A20. A year is read as a street number [measured].** — **fixed in v2.144.0**
  `discriminators_reason('SITE1 Survey 2025', 'SITE1 Survey 2026')` →
  *"Street numbers don't match (2025 vs 2026)"*. A false hold-back.

* **A21. The site-code pass has no similarity floor [measured].** — **fixed in v2.144.0** The fuzzy
  pass requires `sim > 0.5`; the code pass requires only equal site codes:
  ```
  'SITE2 Rooftop Antenna Replacement' <-> 'SITE2 Basement Parking Garage'
  codes SITE2 / SITE2, similarity 0.143  -> paired
  ```
  The badge tooltip says *"The site codes match and the names are close."* The
  second half is never checked, and these land in `mismatches`, so Sync offers
  to rename one to the other.

* **A22. Pairing is greedy in Ekahau's listing order [reported].** — **fixed in v2.144.0** No global
  assignment, and `get_projects()` is returned unsorted, so a weaker candidate
  considered first can take a file a later one matches far better — and the
  answer can change when an unrelated project is saved.

* **A23. `exact` is case-sensitive [reported]** — **fixed in v2.144.0** despite the docstring
  promising "case + whitespace normalized", demoting case-only differences to
  `fuzzy`, which is excluded from `PUSHABLE_MATCH_TYPES` — so Local → Cloud is
  greyed out for pairs whose names are the same word for word.

* **A24. Stale not-match entries are never pruned [reported].** — **fixed in v2.144.0** Nothing removes
  an entry whose path has gone, and `_blocked` is consulted in *every* pass
  including the id pass. A freshly downloaded file landing on an old path is
  silently refused a pair it can prove.

* **A25. `_ESX_META_CACHE` keys on `(path, int(mtime))` [reported]** — **fixed in v2.144.0** — one-second
  granularity, no size component, never evicted, unbounded.

* **A26. The row-busy 30 s ceiling is measured from enqueue, not from start
  [reported].** — **fixed in v2.144.0** With `OP_MAX_CONCURRENT = 1`, a bulk run emits a stream of
  *"That is taking longer than expected"* toasts about work that is merely
  queued.

* **A27. A failed background poll wipes the list [reported].** — **fixed in v2.144.0** `onData` checks
  `data.error` *before* the background guard, so an unrequested poll replaces
  the list with error text and leaves `data` pointing at the error object —
  after which every later re-render silently draws an empty list while the
  selection bar still says "12 selected".

* **A28. The undo path is dead code [reported].** — **fixed in v2.144.0** No `opEnqueue` call site
  anywhere supplies `undoFn`; every one passes `undoable: false`.

* **A29. `wd-match-help-seen` is written and never read [measured].** — **fixed in v2.144.0**
  `openMatchHelp` hides `#matchHelpHint`, which does not exist in
  `web/cloud.html`. Dead, not harmful.

* **A30. Duplicates-tab deletes — including irreversible cloud deletes across
  every cluster — are gated only by `window.confirm()` [reported]** — **fixed in v2.144.0**, which
  browsers truncate, and which shows no site, no date and no "shared with".

---

## Systemic

### A31. CI never installs Node, so roughly 30 cloud test files skip silently [measured]

`.github/workflows/tests.yml` has `setup-python` and no `setup-node` step, and
nothing asserts Node exists. Most cloud tests are Node probes that
`@unittest.skipIf(shutil.which("node") is None)`. They pass today because the
GitHub runner images happen to ship Node. A runner image change turns the
majority of Cloud Manager's real coverage into green no-ops with nothing
reporting it.

**This is the cheapest high-value fix in the document:** add `setup-node`, and
make the skip an error in CI.

### A32. The documentation describes a control that no longer exists [measured]

`CLAUDE.md` still states that any cloud-side delete "requires typing `DELETE`
in a second confirmation modal (`#cloudDeleteConfirmModal`)". That gate was
removed deliberately and well — the reasoning is in
`tests/test_cloud_delete_identity.py`, and naming what is being destroyed is
the better answer. But `#cloudDeleteConfirmModal` is gone from `web/cloud.html`
and a test now asserts its *absence*, so CLAUDE.md is describing a control that
does not exist — the `TheAppOnlyPointsAtControlsThatExist` rule pointed at the
repo's own notes.

### A33. Where the tests cannot fail

`scripts/audit_source_string_tests.py` reports 350 source-text assertions
across 61 files. Three cloud files execute nothing at all:
`test_cloud_header_never_clips`, `test_cloud_header_structure`,
`test_cloud_modals_are_self_sufficient`.

Behaviours with **no test that could fail if they broke** — the gap list is the
most actionable part of this audit:

1. **Cloud and local deletion actually executing.** `delete_cloud` and
   `delete_local` appear in no test. The dialog is proven; the handler is not.
2. **The entire Duplicates tab** — a destructive surface with zero executed
   coverage.
3. **Sharing and the sharing group** — 12 server actions and ~30 client
   functions, untested.
4. **Transfer ownership** — untested. Hands a project to someone else.
5. **Folder merge** — `merge_preview` / `merge_execute` move and delete files
   on disk. No coverage at all. See A5.
6. Manual-match / not-match round trips; auto-assign running; move-to-site
   execution; plain upload and download; bulk row tools; held-back handling;
   search, A-Z jump, expand/collapse; live-refresh timing; `opRetry` / `opUndo`.

Counted: **214 of 380** top-level functions in `cloud.js`, **44 of 78** inline
handlers, and **25 of 46** `CLOUD_ACTIONS` are not named in any test file.

### A34. Tests that pin wording rather than property

Worst first: `test_cloud_modals_are_self_sufficient` (the whole file, including
literal code strings like `input.value = name;`);
`test_cloud_ops_queue::TheBackupLocationIsDescribedCorrectly` (rewritten in
v2.141.0 as `NothingPromisesACopyThatIsNoLongerKeptTests`, which holds the
property in both directions rather than one sentence);
`test_cloud_sync_everything`; `test_cloud_sync_plan::TheConfirmNamesWhatItWillDestroy`;
`test_cloud_replace_project` (two tests assert on `__doc__` text, so editing a
docstring breaks the suite while deleting the safety ordering does not).

A0 is the proof that this class is not theoretical: the assertion that pinned
the argument order was the reason a dead feature stayed green for 19 releases.

---

## Checked and found correct

Recording these so the next pass does not re-derive them.

* **Escaping is clean.** Every value interpolated into a JS string literal or
  an event attribute across all 9,044 lines is wrapped in `j()`/`pj()`/`a()`/
  `e()`, or is an internal token (tab kind, boolean, loop index, generated op
  id). The typeahead deliberately passes an index (`'i:' + i`) rather than a
  site name. No duplicate function definitions; 105 of 107 `getElementById`
  targets exist, and both exceptions are guarded or inside a comment.
* **The client/server action table agrees.** All 44 `API_MAP` entries resolve
  to a `CLOUD_ACTIONS` entry with matching argument keys; all 60+ `pyApi` call
  sites use a known method. A0 was the only genuine mismatch.
* **`verify_replace_local` — the one destructive local write — is right.** It
  writes to a temp file and `os.replace`s, cleans up on failure, re-reads both
  sides server-side and refuses `local_newer` regardless of what the client
  believed. *(As audited it also copied the file aside first; v2.141.0 removed
  that across the suite — the cloud project it is replacing the file with is
  the other copy. Everything else in this line still holds.)*
* **`_rewrite_project_json`** is atomic and no-ops when the mutation changes
  nothing — so `fixInternalName` is safe to re-run. *(It backed up first as
  audited; see v2.141.0.)*
* **Credentials at rest.** No path writes a plaintext credential; encrypt-then-
  verify-by-decrypting before trusting the file; the legacy readable file is
  deleted only after a verified encrypted write; corrupt, truncated and
  tampered ciphertexts all fail closed. **Every HTTP call has a timeout.** No
  credential reaches a log line. `tests/test_cloud_credentials.py` proves it.
* **The owner filter composes correctly with every chip**, including the
  empty-site case, and the saved-default/this-visit split works as designed.
* **`comparisonIsSettled` / `isOutOfSync` are one predicate** shared by the
  chip, the list and the site digest — no second spelling.
* **Sites-tab chip↔row agreement holds** for `orphans-cloud`, `orphans-local`,
  `mismatches`, `name-matches`, `unshared`, `stale`, `unmatched-sites` and
  `unassigned` under all three owner settings, with no search and no letter.
* **`_opActive` cannot leak** — incremented once under a guard, decremented in
  exactly one `finally`; a dismissed queued op returns before the `try`.
* **Server-side progress is pruned**, not leaked, including on exception paths.
* **`replace_cloud_project`'s ordering is right** — upload, verify, then
  delete. There is no window where the cloud project is gone without a
  replacement having been created. The weakness is what "verified" means (A1),
  not the order.
* **`backups.remove` re-derives** every path from a fresh scan rather than
  trusting the page. `prune_for` retention is live, and protects the
  just-written generation. *(`tools/backups.py` was deleted in v2.141.0; this
  line records what was true on the audited tree. The re-derive-before-writing
  rule it demonstrates is still the house rule - `housekeeping.sweep` and
  `cloud_realign.realign` both follow it.)*
* **`fuzzy_similarity`** cannot throw, divide by zero or return NaN, and is
  symmetric and bounded for every input tried including empty and 5,000-char
  names.
* **One-to-one matching integrity holds** — a local file cannot be claimed
  twice and a cloud project cannot claim twice. Only the *choice* is
  order-dependent (A22).
* **No modal can be dismissed by Escape or backdrop click**, so no confirm can
  leak a pending promise.
* **Bulk delete captures ids at dialog-open time**, so a refresh between
  confirm and execution cannot redirect it.
