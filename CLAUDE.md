# CLAUDE.md — persistent notes for this repo

Read this at the start of every session. It exists so facts don't have to be
re-discovered (or re-explained) each new chat.

## Release process — do this every time you commit to `main`

1. Bump `web/assets/versions.json` — this is the single source of truth for
   every tool's version + the suite version. Every page's displayed version
   (`data-ver` attributes, read by `WD.applyVersions()` in
   `web/assets/js/wd-shared.js`) comes from this file automatically.
2. **Also manually update `README.md`** — it quotes versions in prose and is
   NOT auto-synced from versions.json:
   - the `WIRELESS TOOLS  vX.X.X` example banner, and
   - the version badge of **every tool you touched** in the table near the top
     (not just Cloud Manager — the test checks all seven).

   There used to be a third place, `web/pages/hosted-cloud-stub.html`, which
   quoted the Cloud Manager version. It went with hosted mode. The public
   landing page (`web/pages/landing.html`) deliberately quotes no version at
   all, so there is nothing there to fall out of date.

   A real test enforces this:
   `tests/test_server_and_assets.py::test_public_documentation_uses_current_versions_and_report_status`.
   Skipping step 2 breaks CI on every commit — this has happened before.
3. Run the full test suite locally before pushing:
   `python -m unittest discover -s tests -v`
   If the sandbox's system Python has a broken flask/cryptography install,
   use a clean venv: `python3 -m venv /tmp/venv && /tmp/venv/bin/pip install
   -q -r requirements.txt && /tmp/venv/bin/python -m unittest discover -s
   tests -v`.
4. Commit and push to `main` directly (no PR needed for routine work).
5. Create the GitHub release with hand-written notes, matching the
   WaxFrame Pro style (H1 = one-line summary, `## What changed` with
   bullets, `## Verified`, `## Files changed`):
   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "WD Wireless Tools vX.Y.Z" --notes "..."
   ```
   The release workflow (`.github/workflows/release.yml`) triggers on
   `release: [published]`, runs tests, builds the ZIP via
   `scripts/build_release.py`, and uploads it as a release asset.
   `build_release.py` raises if the tag doesn't match `versions.json`'s
   `"suite"` value — so the version bump commit MUST land before the
   tag is pushed.
   Note: tag pushes work from local sessions but are blocked from
   Claude Code **cloud** sessions (claude.ai web).

6. **A release note for a user-facing feature must say how to use it.**
   "Added X" is not sufficient. Someone read a note, saw the feature listed,
   and still could not find the control — it was sixth in a panel of
   eighteen, and the note never said where it was. Every user-facing entry
   states four things:

   - **the tool** it is in (Report → AP Placement Map)
   - **the panel** it lives in (the options panel in the Configure step)
   - **the exact label** on the control, quoted, so it can be searched for
   - **its default**, and what to do to turn it on

   Where it sits in a long list is worth a sentence too, and if a later
   release moves it, say so — someone on the older build is reading the
   older note.

   This is the same rule the product itself follows: state the consequence
   and the action, not just the fact. A note is documentation for someone
   who was not in the conversation where the feature was designed.

   Version numbers are a live source of confusion and belong in the note.
   **The suite version and each tool's version are different numbers** —
   suite 2.92.0 ships Report 2.60.0, and the Report page shows the Report
   one. A note that says "fixed in 2.92" leaves the reader unable to tell
   whether the number on their screen is newer or older than that.


## Verifying a change — test servers, ports, and browsers

**Sessions have hung here before. The symptom is a session that reports as
running with a frozen turn count** — a dev-server start or a browser-pane call
that never returns. From outside it is indistinguishable from idle, which is
why it costs real waiting time. Four sessions stalled on this in one day.

- **Prefer not starting a server at all.** Most things are verifiable by
  generating the output and inspecting it, or by executing the renderer in Node
  against real data. `tests/test_ap_notes_page.py` is the pattern: it slices the
  render function out of `report.js`, runs it with stubs, and asserts on the
  HTML. No port, nothing to leak, and it runs in CI.
- **Never bind a default or shared port.** Several sessions work in this repo at
  once, and 8675 is the user's own running instance. Pick an explicit, unusual
  high port, and pick a different one per session rather than the number
  everybody reaches for.
- **Always tear it down**, on the failure path too. An abandoned process holds
  the port for the next session. Kill it by PID on the port, not by name — that
  would take down the user's own instance.
- **Never block indefinitely on a bind or a browser call.** Bound the wait, and
  fail loudly if it does not come up. A failed check is visible; a stalled
  session is not, which makes the stall the worse outcome.

### Nobody is at the keyboard

The user works remotely from these sessions and often reads them hours later
on a phone. **Never use AskUserQuestion or any other interactive prompt**, and
never run a command that waits on stdin (`git rebase -i`, `git add -i`, a
`read`, a pager). A session blocked on a prompt nobody can answer looks
exactly like a session doing work, which is how the time gets lost.

Make the reasonable call, do the whole task, and say in the report what you
decided and why. A decision that turns out wrong is cheap to correct; a
session that stopped to ask is not.

### Print verification needs a real browser — use BiDi

Print is the one thing that genuinely needs a browser, and it must be checked in
**Firefox**, which is what the user prints from. Fixes verified only in Chromium
have twice failed to reach him.

Firefox has **no `--print-to-pdf`**, and the silent-print preferences
(`print.always_print_silent` + `print.print_to_filename`) produce no file.
Headless also throws `RenderCompositorSWGL failed mapping default framebuffer`.
Do not spend another session rediscovering those three.

What works is **WebDriver BiDi**: launch with `--remote-debugging-port`, connect
to `ws://127.0.0.1:<port>/session`, then `session.new` →
`browsingContext.getTree` → `browsingContext.print`, which returns the PDF as
base64. There is no websocket library installed; a minimal RFC 6455 client is
about 60 lines. This drives the same path `window.print()` takes, which is what
the Report Print button calls.

Inspect the result rather than trusting it: decompressing the content streams
and reading the `(...)` text operators is enough to tell which page each piece
of content landed on, so "it starts a new sheet" and "the row did not split" are
assertions about the printed output, not about the CSS source.

## Updating (in-app) — how it fits together

- `tools/updater.py` is the whole mechanism. `detect_install()` decides which
  of git / ZIP / convert / manual / dev applies, and the About panel leads with
  that single action instead of asking the user to choose. `/api/update/status`
  (GET) and `/api/update` (POST) in `server.py` are the only entry points; the
  UI lives in `_showUpdatePanel()` and friends in `web/assets/js/wd-shared.js`.
- **User data must never live in the install tree**, or updates break. Wall
  templates moved to `~/.wd_wireless_tools/templates/` for exactly this reason
  — `templates/WD Template_walltemplate.json` is git-tracked *and* was
  user-writable, so a customized copy made `git pull` abort with "local changes
  would be overwritten" and the user could never update again. Shipped
  templates stay in `templates/` as read-only built-ins; user files shadow them
  by filename; deleting a built-in writes a tombstone in `hidden.json`. If you
  add any new user-writable state, put it under `~/.wd_wireless_tools/`.
- **The update check must not depend on `api.github.com`, and the browser must
  not call GitHub at all.** Both were true until v2.98.1 and it cost the feature
  its only user: on his work machine `git pull` worked from a terminal while the
  in-app check timed out, because a corporate network commonly carries git over
  HTTPS to github.com and still blocks or throttles `api.github.com`. The page
  made that call itself, with no timeout on it, so About hung and then reported
  that GitHub was unreachable on an install perfectly able to update.

  The order now is: the page asks `/api/update/status`; that asks
  `remote_release_tag()` (`git ls-remote --tags origin`) for a git install; and
  the API is left with release notes only, on an 8s budget, failing quietly. A
  ZIP install has no remote and still uses the API. Don't put the API back in
  front of that, and don't let the browser reach GitHub directly —
  `tests/test_updater.py::ClientChecksThroughTheServerTests` and
  `BlockedApiTests` hold both.

  Related: every git call runs with `GIT_TERMINAL_PROMPT=0` and non-interactive
  credential helpers. Nothing here has a terminal, so a prompt became a
  two-minute timeout and on Windows could raise a credential dialog on a desktop
  nobody is at. Local git commands have their own `LOCAL_GIT_TIMEOUT`, and the
  timeout message names the command — "timed out talking to GitHub" was being
  reported for `git status`.

- `is_dev_checkout()` blocks auto-update on a maintainer's clone (detected by
  `.github` / `tests` / `scripts` / `BACKLOG.md` / `CLAUDE.md`, none of which
  ship in a release ZIP). Without it, clicking Update in your own working copy
  would check out a release tag over in-progress work and detach HEAD.
- `release.yml` publishes `<asset>.sha256` alongside the ZIP. The ZIP updater
  and both install scripts refuse to install a mismatched download, so don't
  drop that step.
- `install.ps1` / `install.sh` are dual-role: piped through `iex`/`bash` they
  bootstrap a fresh install; run from inside an install folder they update it.
  Both are in `build_release.py`'s payload, so ZIP users get them too. A fresh
  interactive install asks git-vs-ZIP; an existing install keeps whatever it
  already uses and is never asked again.
- Missing git is **not** a dead end on Windows: `winget install Git.Git` runs as
  part of the flow (`install_git()` / `Install-Git`), with `--scope user` tried
  first to dodge the admin prompt. Every failure mode — no winget, no network,
  blocked by policy — falls back to ZIP with the reason shown. macOS is
  supported by this repo but git is only *described* there (`xcode-select`,
  Homebrew), never auto-installed.
- `convert_to_git()` deliberately checks out the tag matching the version
  already installed, not the newest one. Converting and updating are separate
  decisions; doing both at once would silently ship new code to someone who
  only clicked "switch". It backs up first and is gated behind a confirm step
  in the UI.

## Porting the updater to the other apps

`tools/updater.py` and the `WD.Updater` block in `wd-shared.js` are written to
move to LensLedger / Subscription Wizard by copying two files and editing one
config block each — nothing below `CONFIG` names this app.

- Python: edit the `CONFIG = AppConfig(...)` literal (repo, version file path
  and key, asset name template, payload files/dirs, user-data dir,
  `rescuable_globs`). A test asserts `CONFIG.payload_*` stays in step with
  `build_release.py`; write the equivalent for the target repo.
- JS: edit `WD.Updater.config` (repo, bootstrap command, endpoint paths), then
  call `WD.Updater.mount(el, state)` from wherever that app shows version info.
- Server: copy the `/api/update` and `/api/update/status` routes.
- `rescue_dirty_templates()` still imports `tools.template_store` directly —
  that is the one WD-specific seam left. Generalize it if the target app has
  its own user-editable-but-tracked files; delete the call if it has none.
- **WaxFrame is the exception**: it is a `file://` app with no server, so it
  cannot have the in-app button at all. Its path stays the standalone
  `Update-WaxFrame.ps1`, which is where this design came from.

## Where a setting is allowed to live

**Adding a setting means adding it to `web/assets/settings-registry.json` first.**
That file is the rule, not a description of one, and
`tests/test_settings_registry.py` enforces it. The categories and why each
exists are defined *in the registry itself* — read them there, they are the
whole point.

**Two categories, and only two.** **preference** (follows the person,
server-side in `settings.json`, exactly one control anywhere) and **ui-state**
(panel widths, collapsed sections, tips seen — stays in `localStorage`
deliberately, because syncing a collapsed panel between machines is a
regression).

There used to be a third, `hosted-mirror`, for the GitHub Pages build where
Quick Walls / Scale / Report ran with no server to save to. **Hosted mode is
retired** (v2.61.0 replaced it with a static landing page; v2.71.0 moved the
last three settings server-side). There is no server-when-present store any
more, and adding one back would recreate the two-store bug below.

How this drifted in the first place, so it is not repeated: settings went
wherever the tool that needed them already had a habit, and the habit was set
by whether that tool happened to have a server call handy. Cloud Manager
straddled both eras and ended up with `merge_rule` and `live_interval_ms` in
**both** stores — Suite Settings read and wrote `settings.json` while the
runtime only read `localStorage`, so the page displayed a value that was not
in force and saving there did nothing at all. Fixed in v2.57.0; the migration
takes the browser's value as the one in effect and only deletes the local key
once the server write has succeeded.

Two of the registry tests each correspond to a bug that shipped: "no setting
lives in two stores" is that one, and "every `settings/update` sends a `patch`
envelope" is report page orientation, which posted `{report: {...}}` where the
server reads `d["patch"]` and therefore saved nothing while reporting success.

## Uploading to Ekahau Cloud — what is known, and what is not

Cloud Manager can download and it cannot upload over an existing cloud
project. The wording in the Sync confirm says "that direction is not built
yet" **deliberately**: the API is not known to be the obstacle, the code is
simply not written, and the previous wording ("cannot") told the user
something false about his own tool.

**What is established:**

- `GET /projectapi/v1/projects/{id}/batch` returns every document keyed
  exactly as the `.esx` members. `download_project` writes each key as
  `{key}.json` and the result is byte-identical to Ekahau's own download
  (`docs/releases/v1.8.41.md`).
- That batch response therefore **includes `projectHistorys`** — a real `.esx`
  contains `projectHistorys.json`, and it can only have come from there. So
  **the cloud stores the revision chain**, which is the data a server would
  need to detect a conflict. That is what makes in-place update with a
  sync-or-overwrite prompt plausible rather than wishful.
- `rename_project` already writes back in place:
  `PUT /projectapi/v1/projects/{id}/batch/update` with `{"project": {...}}`.
  Read-all and write-one, same shape.
- `upload_project` uses `esxfileapi/v1/projects/upload/initiate` → S3 PUT →
  `commit`. `initiate` takes only `fileName`/`fileExtension`, no project id,
  so that flow creates a **new** project. This is the web UI's upload path.
- `assign_to_site(site_id, dataset_id, type)` exists and works, so
  re-attaching a re-uploaded project to its original site is a call we
  already have.

**What is NOT established:** whether `batch/update` accepts documents other
than `project`. Nothing has been tested against it, and no speculative PUT
should be made against a real account to find out.

**Dead ends — do not spend another session on these:**

- `docs/reverse-engineering/capture_upload.js` **cannot see the sync/overwrite
  prompt.** That dialog is in Ekahau AI Pro, the desktop client; the script
  wraps `fetch`/`XHR` in a browser page and desktop traffic never goes near
  it.
- **There is no public Ekahau Cloud API documentation.** That is why these
  capture scripts exist at all.
- Proxying the desktop client would settle it, but it means installing a
  trusted root certificate on a **work machine**. Not to be suggested.

**The cheap route that is still open.**
`docs/reverse-engineering/capture_project_fields.js` hits the project
*listing*, which is a browser operation and is unaffected by the desktop
problem. Field names alone answer whether a project record carries a
revision, version or etag. The safe one-liner, which prints no values and
copies nothing:

```js
fetch('/projectapi/v1/projects').then(r => r.json()).then(d => {
  const p = (Array.isArray(d) ? d : d.projects || d.items || [])[0] || {};
  console.log(Object.keys(p).sort().join(', '));
});
```

Whether the Ekahau Cloud **web** UI can replace an existing project is the
other open question. Note that if it only offers "upload new", capturing it
will reveal nothing about replacing — our `upload_project` already is that
flow.

**The fallback, if in-place proves unavailable:** delete the cloud project,
upload the local file, re-assign it to its original site. The loss is
narrower than earlier notes claimed — `tags` live inside `project.json` and
travel with the file, and `projectHistorys.json` travels with it too. Shares
are keyed to the project id and would be lost, but `share_projects` exists,
so they can be captured beforehand and re-applied. That is a product
decision, not an engineering one: take it to the user rather than choosing
for him.

## The Ekahau AP colour palette

`WD.EKAHAU_COLORS` in `web/assets/js/wd-shared.js` is the only copy. Anything
that draws or names an AP colour goes through `WD.ekahauColorKey()` (value →
key) and `WD.ekahauColorName()` (key → the word Ekahau uses).

| Ekahau's name | key in code | hex |
|---|---|---|
| Clear | `__none` | *(no colour written at all)* |
| Yellow | `yellow` | `#FFE600` |
| Orange | `orange` | `#FF8500` |
| Red | `red` | `#FF0000` |
| Pink | `magenta` | `#FF00FF` |
| Violet | `purple` | `#C297FF` |
| Blue | `blue` | `#0068FF` |
| Gray | `gray` | `#6D6D6D` (also accepts `#6B6B6B`) |
| Green | `green` | `#00FF00` |
| Brown | `brown` | `#C97700` |
| Mint | `cyan` | `#00FFCE` |

**The names and the keys disagree on purpose.** Ekahau says Pink, Violet and
Mint; this codebase called them magenta, purple and cyan long before anyone
checked. The keys are internal and a saved colour sequence is stored by key,
so renaming them would silently reorder somebody's sequence — the display name
is what changed. `WD.EKAHAU_COLOR_ALIASES` accepts either vocabulary coming in.

**Gray is the cautionary tale.** The table started with `#6D6D6D`, which is
what a real project actually contains. A later pass "corrected" it to
`#6B6B6B` by reading the swatch off the picker on screen, and from then on
every grey AP fell through to `Custom #6D6D6D` in the colour list. Reading a
rendered colour is not the same as knowing what gets written to the file.
`WD.EKAHAU_HEX_ALIASES` exists for this: **add an observed hex, never replace
one**, or the bug just moves to whoever had the other value.

**What is verified and what is not.** Red, Green, Orange and Pink are
confirmed against a real project — they resolved to names in it. Gray is
confirmed the other way round, as above. Yellow, Violet, Blue, Brown and Mint
are still only as good as the picker. The hex values were checked against the
real Ekahau colour picker (2026-09-04). The *stored representation* is not
verified: across 111 local `.esx` files and 913 APs there is not a single
`color` field on an access point, because none of those projects has a marked
AP. Everywhere else the format stores colour as hex (`"color": "#FF0000"` on
wall types, areas, attenuation areas) and no palette name appears anywhere in
any file, so hex is what is trusted. If a value arrives that is neither a known
hex nor a known name it is kept as-is, drawn, and labelled `Custom #XXXXXX` —
never dropped and never guessed at.

To settle it: mark one AP of each colour in a throwaway project, save, and read
`accessPoints.json`. Until then, do not assume the table is complete — Ekahau
may permit a custom colour.

**Two implementations is the failure mode here.** The Report printed `#6B6B6B`
as a section heading while the Labeler said `Gray`, because grouping-by-colour
labelled sections with the raw stored value. The user reported seeing a hex,
the Labeler got fixed, and the Report kept doing it. Every surface that shows
an AP colour to a reader — labeler sequence list, labeler preview swatch,
report grouping headings — goes through the shared pair now, and
`tests/test_ap_color_order.py` holds that.

## Known gotchas

- **Per-page paper orientation depends on a Chromium-only feature, and the
  invariant matters more than the feature.** Mixed orientation in one document
  is done with named `@page` rules (`@page placementLandscape { size: Letter
  landscape }`) in `web/assets/wd-tools.css`. Chromium implements named pages;
  Firefox does not implement them at all. Where they are not honoured every
  sheet takes the print dialog's orientation and the per-page choice is
  discarded silently.

  **Correction (v2.56.1 → withdrawn in 49e30fb): the Firefox half of that claim
  was never measured and must not be repeated.** Chrome and Edge were measured
  and are correct. Firefox was not — headless printing could not be driven, so
  what it does with named pages is simply unknown. Worse, the detection shipped
  to warn about it was wrong on its own terms: `CSS.supports('page','auto')`
  returns true in Firefox as well as Chrome, so the warning could never have
  fired in the browser it existed for. Say "verified in Chrome and Edge", not
  "Firefox is broken" — asserting a defect nobody has observed is worse than
  saying nothing.

  Verified by printing the same document with the `page:` declarations intact
  and stripped: with them, each page gets the sheet it asked for; without them,
  a page sized 7.667in wide for a landscape sheet lands on a portrait one.

  **The invariant: layout and sheet must never disagree.** A document that is
  uniformly landscape is fine. A page laid out for a sheet it will not get is
  not - content sized for one orientation on a sheet of the other overflows and
  is clipped at the margin, which is how APs went missing from an installer's
  drawing. So where named pages are unavailable, pick **one** orientation for
  the whole document - from the majority of pages, or from the widest content -
  and lay every page out for that one. Degrading to a uniform document is
  correct; delivering mixed orientation that the engine will not honour is not.

  Related but separate: the clipping reported alongside this turned out to be
  the label placer walking labels off the plan edge, fixed in v2.52.1 and
  guarded by `tests/test_marker_bounds.py`. Don't assume an orientation report
  and a clipping report are the same defect.

- **A requirement area silently stops the canvas being trimmed, so trimming
  always runs first.** `esx_trimmer._floor_coord_bbox` unions every coordinate
  belonging to a floor into the crop box, so that nothing ends up off the image
  — and `areas[].area[]` is one of the carriers it walks. An area written before
  the trim is therefore part of the crop and holds it open. On a plan with no
  walls or APs yet, `capacity_profiles.area_for_floor` falls back to the canvas
  basis and the area *is* the whole sheet, so it holds the crop open to the full
  sheet and `FILL_SKIP_RATIO` then skips the floor with "content already fills
  100% of the canvas".

  Nothing errors. The file opens, every floor is present, and the plan is simply
  the size it always was — a clean skip reported for a crop that was prevented.
  This is why `tools/prep_pipeline.py` has `STEP_ORDER` **and** `ORDER_RULES`:
  the sequence about to run is checked against the rules before anything is
  written, and again against what actually ran, so reordering the list fails
  loudly. `tests/test_prep_pipeline.py` tests it twice — once against the guard,
  and once by building the project that fails and asserting the floor really was
  cropped, which still fails with every guard deleted.

  The reverse constraint does not exist: injecting wall *types* adds no wall
  *segments*, so it cannot change the area basis and can run either side of the
  area step. Only trim-before-areas is real. An early draft of this had the
  order wrong for a plausible-sounding reason, which is the argument for the
  rules being executable rather than written down.

- **Owner filter (Mine/Others/All)** in Cloud Manager used to persist to
  `localStorage` across page loads/sessions, which meant it could get
  silently stuck on "Mine" or "Others" on one machine while defaulting
  correctly on another — this once looked like a data bug ("only 3 sites
  show up") when it was actually a stale filter. It was then made in-memory
  only, which cost a click on every load for anyone who really does work
  mostly in their own projects.

  Since v2.51.0 it is **two settings, not one**, and the split is what keeps
  the old bug from coming back:

  - **What the list opens on** is `cloud.default_owner_filter` in
    `~/.wd_wireless_tools/settings.json` (Settings → Default view). It ships
    as `"all"`, so nobody else's install changes behaviour. It is *not* in
    `localStorage` — a per-browser copy is exactly how two machines came to
    disagree about how many sites there were.
  - **What is on screen now** is the toolbar Owner toggle, and it lasts until
    the page is reloaded. Nothing in the toolbar writes to the settings file.

  The condition attached to the old note still holds and is now enforced
  rather than remembered: any filter narrower than All renders
  `#ownerFilterNotice` above the list, in words, saying what is hidden and
  whether it is the saved default or just this visit; an empty list names the
  filter that emptied it; and a listing that comes back with no
  `currentUser` turns the filter off and says why, because otherwise a saved
  "Mine" would render an empty page indistinguishable from an empty cloud
  account. `tests/test_cloud_owner_filter.py` drives all of that through the
  real functions in Node — don't relax it.
- The Sites tab tree (`renderSitesTree()` / `renderTreeChildren()` in
  `web/assets/js/cloud.js`) gives every row — top-level sites AND nested
  project files — independent cloud-side/local-side checkboxes
  (`s-c:`/`s-l:` for sites, `ct-c:`/`ct-l:` for nested files). Selecting
  either side of a matched pair resolves back to the single pair record in
  `selectedSyncItems()` for bulk Sync purposes, but is deletable
  independently in `bulkDelete()` (kind stays `'cloud'`/`'local'`, never
  collapses to a combined pair-delete). Any cloud-side delete (single or
  bulk) requires typing `DELETE` in a second confirmation modal
  (`#cloudDeleteConfirmModal`) — cloud deletes aren't recoverable, local
  ones are (re-download from cloud), so the friction is asymmetric on
  purpose.

## Memory across sessions, generally

Claude Code cloud sessions have no memory of past conversations by default
— only what's readable in the repo at session start (this file, code,
`BACKLOG.md`). If something matters for next time, write it here rather
than assuming it'll be remembered.
