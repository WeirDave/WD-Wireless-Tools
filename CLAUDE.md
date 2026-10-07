# CLAUDE.md — persistent notes for this repo

Read this at the start of every session. It exists so facts don't have to be
re-discovered (or re-explained) each new chat.

## Rule zero — never commit real personal or company information

**Never use real personal or company information in this project, in any form,
without asking him first.** Not as an example, not as a test fixture, not in a
comment, not in a commit message, not "just to reproduce the bug". Ask, and
wait for an answer.

**What counts.** His employer's name. Site and building codes. Street
addresses and the cities his sites are in. Client, consultant and vendor names
off his drawings. Colleague names. Internal hostnames, gateways or other
infrastructure names. Internal chat channels. His work email. Real project and
`.esx` filenames, and real CAD sheet names. **And any measurement, count or
figure attributed to an identifiable real site** - "52 segments in <site>" is
disclosure; "52 segments in one real project" is not.

**Where it applies: everything that persists.** Source, comments, test
fixtures, sample data, `docs/`, the user manual, `BACKLOG.md`, this file,
commit messages, release notes, the landing page, and screenshots.

**When he shares a real project to settle a technical question**, read it for
structure and metadata only. Do not copy its content, do not turn it into a
fixture, and do not let a name or a figure out of it reach a commit. Build the
fixture synthetically, with invented names.

**Assume this repository is public, because it is.** Anything committed is
published: ZIP assets, forks, clones and commit history cannot be taken back.

**If you are unsure whether something is traceable to his employer or to a
real person, leave it out and ask.** Unsure is a hit.

**`~/.wd_wireless_tools/share_recipients.json` holds real colleagues' email
addresses.** `tools/share_recipients.py` manages it; it is gitignored, absent
from the release payload, and has no network imports, and
`tests/test_share_recipients.py` asserts all three. Never open his copy, never
paste from it, never build a fixture from it. Every address in this repo is
invented at an RFC 2606 documentation domain.

**How it is enforced.** `tests/test_no_real_world_data.py`:

* every site-code-shaped token in tracked files must be on an allowlist of
  invented ones, emails must use documentation domains, and no credential
  shapes or infrastructure addresses are allowed. **A new placeholder fails
  that test - that is the check working.** Confirm it is invented, then add it
  to the allowlist. Never add a real one to make the suite green.
* `TheHistoryIsCheckedToo` checks commit messages and every blob ever
  committed, as a **ratchet**: what is already published is listed in
  `tests/no_real_world_data_baseline.json` and skipped; anything new fails.
  Regenerate it with `python scripts/refresh_history_baseline.py` only after a
  deliberate history rewrite; it should only ever get shorter.
* **Nothing prints the value.** A failure names the commit or blob id and the
  path, because a CI transcript is as public as the thing it complains about.

It is rule zero because it had already gone wrong: a real site code was the
worked example in Cloud Manager's own UI and in every release ZIP, and his
employer's name reached a release note in a quoted CAD sheet title. Each one
arrived as real data used to reproduce a real problem and then left behind.
**Audit by enumerating every token of the shape, not by searching a list of
known names** - the list missed every real identifier that was found.

## Releases are automatic: a version bump on `main` publishes

**Bump `web/assets/versions.json` and the release publishes itself.** Do not
tag, do not run `gh release create`, and do not hold a release back.
`.github/workflows/auto-release.yml` watches that file: when `suite` on `main`
has no matching tag, it runs the full suite, tags **the commit that bumped
it** (`github.sha`, never a moving HEAD), re-reads `versions.json` **at the
tag**, publishes, and calls `release-assets.yml` to attach the ZIP and its
`.sha256`. A red suite publishes nothing.
`tests/test_release_is_automatic.py` holds all of that.

**Why:** he installs what is published. An unreleased commit is invisible to
him - three versions of finished work once sat untagged while he fought bugs
at work that were already fixed.

* **A release created with `GITHUB_TOKEN` does not fire `release: published`**,
  so the automatic path calls `release-assets.yml` itself rather than relying
  on `release.yml`. An asset-less release is worse than none: the updater and
  both install scripts refuse a download without a matching checksum.
* **It skips a suite that already passed on the same tree.**
  `scripts/tested_head.py` recognises a merge that added nothing to a PR head
  with a green `tests.yml` run; the release then takes about a minute instead
  of about 27. So **merge main into a PR before merging it.**
  `tests/test_release_skips_a_suite_it_already_ran.py` holds it.
* **Safari does not gate a release.** `auto-release.yml` calls `tests.yml`
  with `safari: 'off'`; the job still runs, and shows red, on every pull
  request and push. It failed a different test on each run, `main` included,
  and one red job anywhere in the called workflow leaves a finished release
  unpublished. The condition is `inputs.safari != 'off'` on purpose: a missing
  input and `false` coerce to 0 and compare equal in a GitHub expression, so
  `!= false` would skip Safari on every pull request.
  `SafariInformsAPullRequestAndDoesNotGateARelease` in
  `tests/test_release_is_automatic.py`. A PR run with Safari red is not a
  "successful" run to `tested_head.py`, so such a release runs the suite again
  (about 14 minutes) instead of skipping it.
* `release.yml` remains for a release published by hand in the GitHub UI and
  for backfilling assets onto a tag whose build failed.

### Release notes

The automatic note is a stub (version, install link, commit). **The real note
is committed as `docs/releases/vX.Y.Z.md`**; `release-notes.yml` applies it on
push or when the release build finishes, so it can land before or after the
release. Style: H1 = one-line summary, `## What changed` with bullets,
`## Verified`, `## Files changed`.

| | commit message | release note |
|---|---|---|
| read by | whoever maintains this | whoever downloads it |
| covers | why, what was tried, what was got wrong | what changed, and its effect |
| quotes the user | yes, that is the point | never |
| first/second person | fine | never |

Third person, no "I"/"we"/"you", describe the change not the discovery, never
mention screenshots, reports or conversations, group by tool, lead with the
user-visible effect. **It is a privacy boundary too**: a note narrating who
reported something or what network they were on publishes that under his name,
and the rule-zero scanners never read release bodies.

**A user-facing feature's note says how to use it**: the **tool**, the
**panel**, the **exact label** in quotes, and its **default** and how to turn
it on. Someone once read a note and still could not find a control sixth in a
panel of eighteen. **Suite and tool versions are different numbers** - suite
2.92.0 shipped Report 2.60.0, and the Report page shows the Report number - so
name both.

## A finished PR is merged and released without asking

*"next time just merge and release without asking."* **A cloud session merges
its own PR when every check is green.** A green PR waiting on him is
unreleased work he cannot install. A local session pushes straight to `main`.

All of these, on the PR's **current head**:

1. **Every check has passed**: the four suite jobs, the firefox, chrome and
   edge jobs, and CodeQL. Red, cancelled or running means no merge. **Safari
   is not on that list** - it informs, it does not gate (see above).
2. **The branch contains the latest `main`.** Merge `origin/main` in first and
   let CI run on the result - which is also what lets the release skip its
   own test run.
3. **The version number is still yours.** Check
   `git show origin/main:web/assets/versions.json` right before merging. If
   another session took it, bump to the next, push, back to 1.

Then mark it ready if it is a draft and merge with a **merge commit** (not
squash or rebase - `tested_head.py` only recognises a merge) pinned to the
tested head SHA (`expectedHeadSha`). Stop watching the PR, confirm the release
published with its ZIP and `.sha256`, and tell him the version.

**Not covered:** a PR somebody else opened, one he said to hold, anything he
asked to review first. GitHub's auto-merge is ticked on and does nothing, by
design - it would need a branch protection rule that would also reject local
sessions' direct pushes.

## Release checklist — the parts that are still yours

1. **Bump `web/assets/versions.json`** - the single source of truth for every
   tool's version and the suite version. Pages read it via `data-ver` and
   `WD.applyVersions()`. **Take the number from `origin/main`**, not from your
   checkout: two sessions have independently written the same number, git saw
   identical bytes, and nothing flagged it.
2. **Update `README.md` by hand**: the `WIRELESS TOOLS  vX.X.X` banner, and the
   version badge of **every tool you touched**.
   `tests/test_server_and_assets.py::test_public_documentation_uses_current_versions_and_report_status`
   enforces it. The landing page deliberately quotes no version.
3. **`git add` new files, then run the suite.** Several tests ask
   `git ls-files` what exists - including the rule-zero scan - so an unstaged
   file is invisible locally and read by CI. v2.136.0 went out red that way;
   v2.102.0 went out dead the opposite way, with a module left untracked.
   `python scripts/run_tests.py` is the suite CI runs, about 3x faster than
   `python -m unittest discover -s tests -v`. If system Python's flask or
   cryptography is broken, use a venv from `requirements.txt`.
4. **Push, and treat red CI as stop**, whatever it says. CI runs a clean
   checkout; it is the only thing that sees a file you forgot.
5. **Commit the release note** as `docs/releases/vX.Y.Z.md`.

**Never run a bare `git commit`** where the index might be shared - name the
paths: `git commit -F msg.txt -- path/one path/two`. A pathless commit once
published another session's staged work under a message saying the opposite.
Staging a file another session is also editing needs content-based staging
(`git hash-object -w --stdin --path <path>` on `HEAD:path` plus your edits,
then `git update-index --cacheinfo`) - **and the `--path` is what applies the
LF filter**; see Known gotchas.

**If you ever tag by hand, name the SHA, never HEAD**, and check
`git show vX.Y.Z:web/assets/versions.json` before pushing. v2.103.14 landed on
another session's commit that way. Tag pushes are blocked from cloud sessions.

**How the suite is run.** `scripts/run_tests.py` runs each module in its own
process with its own `WD_USER_DIR`. A test that passes under `discover` and
fails here usually depends on an earlier module's side effects - fix the test,
not the order. **Browser tests have their own CI jobs**: the four suite jobs
set `WD_BROWSER_TESTS=off`; the `browsers` job runs on Windows, one matrix
entry each for Firefox, Chrome and Edge, via `run_tests.py --browsers-only`.
`tests/test_ci_splits_and_parallelises_the_suite.py` holds that split. Leave
both variables unset locally.

**A test that reads the live repository goes red for reasons unrelated to your
change.** If CI fails somewhere you did not touch, check whether the test asks
git a question before assuming you broke it.

## Unrecoverable earns friction, not refusal

**When an action cannot be undone, make it ask - do not make it impossible.** A
guard that refuses the ordinary state of his work is a wall across the main
road, and he stops believing the guards that matter.

The case that named it: `Local → Cloud` was offered only on pairs sharing
Ekahau's id. A project built locally and uploaded carries that id in the cloud
copy only, so "local is newer and there is no shared id" is the normal state
of work in progress - the one thing the guard refused. He asked for the
feature about six times and could never reach it. It now asks once, naming the
cloud project it will delete. A *guessed* pairing is still refused. **Confirm
what he can check, refuse only what he cannot.**

## Verifying a change — servers, ports, browsers

**Sessions have hung here: a server start or browser call that never returns
looks exactly like a session working.** Four stalled in one day.

- **Prefer not starting a server at all.** Generate the output and inspect it,
  or run the renderer in Node against real data -
  `tests/test_ap_notes_page.py` is the pattern.
- **WD_USER_DIR is enforced, not just available.** Set it to a scratch
  directory before starting any server, so his real configuration cannot be
  reached. It is read once at import. `tests/test_user_dir_is_the_only_door.py`
  holds that every module owning user data moves with it.
- **Never bind a default or shared port.** 8675 is his own running instance;
  pick an unusual high port, different per session.
- **Always tear it down**, on the failure path too. Kill by PID on the port,
  never by name.
- **Never run `server.py` directly for a check.** `main()` opens a real browser
  window nobody closes - once 307 Firefox processes holding 22.5 GB. Import the
  module and neutralise `_open_browser` first.
- **Never kill `firefox.exe` by name, and never by command line alone.** An
  `-osint -url http://localhost:<port>/` process whose port is dead can be the
  **root** of his own browser, because on Windows the first requester becomes
  the instance everything else attaches to. **Check for children first**; a
  process other `firefox.exe` processes name as parent is his browser. Leave
  it and report it.
- **A test process that dies takes its browsers with it** because
  `tests/browsers.py` puts it in a kill-on-close job object
  (`ADeadTestProcessTakesItsBrowsersWithIt`). A leftover has `--marionette`
  and a `rust_mozprofile` profile on its command line.
- **Bound every wait**, and fail loudly. A failed check is visible; a stall is
  not.

### Nobody is at the keyboard

He often reads sessions hours later on a phone. **Never use AskUserQuestion or
any interactive prompt**, and never run a command that waits on stdin
(`git rebase -i`, `git add -i`, `read`, a pager). Make the reasonable call, do
the whole task, and say in the report what you decided and why.

### A control is verified by running its handler, not by finding its name

Render the row with the **real** render function, pull the handler back out of
that HTML, and execute it against recording stubs. `tests/delegated.py` reads a
control's handler and arguments out of rendered markup, and
`tests/test_cloud_push_is_reachable.py` is the pattern. It catches a handler
that is missing, misnamed, takes different arguments, or bails early, and it
pins argument order - which matters when one argument names what gets deleted.

**Text that tells him to use a control requires that control to exist**:
`TheAppOnlyPointsAtControlsThatExistTests` fails on a bolded control name that
nothing renders.

### A control that exists is a control that works

*"I don't want the user to be the bug catcher."* Wherever the tool **can know
in advance** that an operation will fail, it must not offer it. The control
stays visible and named, marked unavailable, carrying the reason - vanishing
is its own problem.

**A filter is a view, not a permission.** Auto-assign once proposed
assignments Ekahau answered `403` to, because candidates were gated on the
owner *filter* rather than on ownership. Gate an action on the fact.
`ownershipBlock()` / `iOwn()` in `cloud.js` are the ownership half: assign,
move, rename, delete, share and replace-cloud need ownership; **reads do not**.
`tests/test_cloud_offers_only_what_can_work.py` holds both halves.

**Where the tool cannot know in advance**, the failure explains itself in
plain language and shows the server's message in full - never a raw status or
a message clipped at `{"s…`.

### Browser verification — Chrome, Edge, Firefox and Safari, every time

**Anything user-facing is checked in all four.** Safari is checked in CI only
(see the end of this section); on his machine, the other three:

    Chrome   C:\Program Files\Google\Chrome\Application\chrome.exe
    Edge     C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
    Firefox  C:\Program Files\Mozilla Firefox\firefox.exe

`selenium` drives all three; Selenium Manager fetches drivers. Set
`options.binary_location`. If a browser will not start, check the path exists
before believing the error - a bad path surfaces as
`NoSuchDriverException`. **Firefox decides print questions**: he prints from
it, and it has twice carried a print fault Chromium does not.

**Safari is the `safari / macOS` CI job, and nowhere else.** It exists only
on macOS, has no headless mode and allows one session per machine, so it
cannot be run on his Windows machine or in a cloud container - **push and read
the job's log.** `WD_BROWSERS=safari` makes `browsers.triple()` list it as a
fourth browser, so every module built on `triple()` / `BROWSERS` drives it
through its `_driver`; `scripts/run_tests.py` then runs the browser modules one
at a time. Three things hold it honest, each from a way it could have lied:

* **A run that cannot start Safari fails**, and **a module in which no test
  passed fails** (`drove_nothing`, read off `unittest -v`) - green with Safari
  never started is the failure this suite already had once for the other
  three. It counts passes, not skips against runs: a module builds one class
  per browser, so three class-level skips sit beside however many Safari tests
  ran.
* **`browsers.SAFARI_NOT_APPLICABLE` is the only list of modules it does not
  run**, each with a one-sentence reason that the job prints. It is for a test
  that is about another browser (Firefox's print pipeline), never for one that
  fails.
* **A new browser test is written once and given a class per browser**: build
  its driver with `browsers.make_driver(kind, binary)`, serve a page it writes
  to a temp directory with `browsers.serve_directory` (Safari refuses `file:`
  URLs), and make the classes from `browsers.triple()`. `run_tests.py` finds a
  browser module by its `import selenium` *or* its call to `make_driver` /
  `safari_driver`; a module that did neither would run in no job at all.
* **A Safari-only difference is a finding, not noise.** The first full run
  found `img.naturalHeight` is the on-screen size there, so AP Labeler's
  spacing lines disagreed with its numbering; Safari's WebDriver also refuses
  to click an `<option>`, which `browsers._patch_select_for_safari` answers
  for every `Select` in a Safari run. Fix the page when the page is wrong.

**Printing to PDF.** `webdriver.Firefox(headless)` →
`driver.print_page(PrintOptions())` returns the PDF through Firefox's real
print pipeline. `PrintOptions` is in
`selenium.webdriver.common.print_page_options`. **Leave
`page_width`/`page_height` unset** when the question is what `@page` does, or
every sheet comes back the size you pinned. WebDriver BiDi
(`browsingContext.print`) is the other route. Firefox has no
`--print-to-pdf`, and the silent-print preferences produce no file - do not
rediscover those. Read the PDF with PyMuPDF; `tests/pdf_sheets.py` reads sheet
sizes without it, for CI.

**Do not install Playwright.** Its bundled Firefox left zombie processes that
locked its own binary and made every later launch fail with `spawn UNKNOWN`.

**Firefox in a cloud container:** `apt` has only the snap stub and mozilla.org
is blocked. Fetch `firefox-*.conda`, `geckodriver-*.conda`, `nss-*.conda` and
`nspr-*.conda` from `conda.anaconda.org/conda-forge/linux-64/` (each is a zip
holding a `pkg-*.tar.zst`) and run Firefox with `LD_LIBRARY_PATH` at the
extracted `lib/`. **Unset that variable for Chromium**, or the conda NSS
crashes it and it reads as `InvalidSessionIdException`.

## Updating (in-app) — how it fits together

- `tools/updater.py` is the whole mechanism. `detect_install()` picks git / ZIP
  / convert / manual / dev, and About leads with that one action.
  `/api/update/status` and `/api/update` in `server.py` are the only entry
  points; the UI is `_showUpdatePanel()` in `wd-shared.js`.
- **User data never lives in the install tree**, or updates break. Put new
  user-writable state under `~/.wd_wireless_tools/`. Shipped wall templates
  stay in `templates/` as read-only built-ins; user files in
  `~/.wd_wireless_tools/templates/` shadow them by filename, and deleting a
  built-in writes a tombstone in `hidden.json`.
- **The update check must not depend on `api.github.com`, and the browser must
  not call GitHub at all.** A corporate network can allow git over HTTPS and
  still block the API. A git install checks with `git ls-remote --tags origin`;
  the API is only for release notes, on an 8s budget, failing quietly. A ZIP
  install still uses the API. `ClientChecksThroughTheServerTests` and
  `BlockedApiTests` in `tests/test_updater.py` hold it.
- Every git call runs with `GIT_TERMINAL_PROMPT=0` and non-interactive
  credential helpers; local commands have `LOCAL_GIT_TIMEOUT`, and a timeout
  names the command.
- `is_dev_checkout()` blocks auto-update on a maintainer's clone (detected by
  `.github` / `tests` / `scripts` / `BACKLOG.md` / `CLAUDE.md`).
- **A missing `.sha256` is a hard stop, the same as a wrong one**, in the ZIP
  updater and both install scripts.
  `tests/test_zip_update_installs_only_what_it_verified.py` drives it,
  including that a release with a valid checksum still installs.
- `install.ps1` / `install.sh` bootstrap when piped, update when run inside an
  install. Missing git on Windows installs via `winget` (`--scope user` first),
  falling back to ZIP with the reason. macOS git is described, never
  auto-installed.
- `convert_to_git()` checks out the tag matching the installed version, not
  the newest - converting and updating are separate decisions. It backs up
  first and sits behind a confirm step.

Porting this to his other apps: `docs/dev-notes/porting.md`.

## Logging — `tools/applog.py`, and there is only one of it

**Anything that goes wrong goes through `applog`, not `print`.**

- One file: `~/.wd_wireless_tools/logs/wd-wireless-tools.log`. **Do not add a
  second log location.**
- It appends, is never truncated on startup, keeps 7 days, and is capped at
  10 MB. Opening in `w` would destroy the evidence at the moment someone
  restarts to see if the fault recurs.
- A healthy install grows 90 bytes per launch. Root logger at WARNING, `wd` at
  INFO. Put any per-request logging behind a level.
- `applog.install()` hooks both `sys.excepthook` and `threading.excepthook`.
  `applog.note_failure(...)` for anything the app carries on from;
  `applog.console(...)` for the one terminal line.
- **A traceback never reaches his terminal**: `server.py`'s catch-all
  `@app.errorhandler(Exception)` logs the stack and returns short JSON.
- The path is shown in **About → Diagnostics** and the startup banner.
- **It holds real paths and hostnames, so it is rule-zero material**:
  gitignored, not in the release, never a fixture. `tests/test_applog.py`.

## Where a setting is allowed to live

**Add a setting to `web/assets/settings-registry.json` first.** That file is
the rule; `tests/test_settings_registry.py` enforces it. Two categories only:
**preference** (server-side in `settings.json`, exactly one control anywhere)
and **ui-state** (`localStorage`, deliberately - syncing a collapsed panel
between machines is a regression). Hosted mode is retired, so there is no
third store; adding one back recreates the bug where Suite Settings wrote one
store while the runtime read another.

Two registry tests each match a bug that shipped: "no setting lives in two
stores", and "every `settings/update` sends a `patch` envelope" (a page posted
`{report: {...}}`, saved nothing, and reported success).

## Uploading to Ekahau Cloud — what is known, and what is not

**Cloud Manager replaces a cloud project by composition:**
`replace_cloud_project` in `tools/cloud_manager.py`, offered on the row as
*"Local newer · replace cloud"*. **Upload, verify, then delete the old one** -
never delete first, because a failed upload would leave nothing in the cloud.
It re-checks which side is newer server-side, carries `siteId` over, and
**names everyone who loses access**, since shares are keyed to the project id.
Re-sharing on his behalf was deliberately rejected.

**In-place replacement is ruled out and should not be reopened**: floor plans
are binary images, and `batch/update` is JSON.

**Dead ends:** no public Ekahau Cloud API documentation exists; the browser
capture scripts cannot see Ekahau AI Pro's desktop traffic; proxying it would
need a trusted root certificate on a **work machine** - not to be suggested.

The full API notes - endpoints, what is established, the one cheap route still
open - are in `docs/dev-notes/ekahau-cloud-api.md`.

## Every tool has its own brand colour

*"all tools should have their own unique color branding"* - said as the
suite-wide visual refresh began. **A refresh unifies the look, never the
colours.** Type, spacing, panels and components are shared; a tool is told
apart by one colour.

* **One block sets it**: the brand block in `web/assets/wd-tools.css`
  (`--tool-accent`, and `--tool-title` where the accent is not legible as a
  title). Header tint, title, drop box and the current item on a workbench
  rail all read it. Never write a per-tool header rule again.
* **The Home tile is the reference** for which colour a tool is: Cloud blue,
  Capacity azure, AP Labeler purple, PlanTrim teal, Prep lime, Quick Walls
  green, Report rose, Scale red, Squirrel amber (organizer and rename are one
  tool, one colour). Home, Settings, Setup and the User Guide stay neutral.
* **Status colours are not brands**: `--ok`, `--attn`, `--danger` mean the
  same thing in every tool.
* **Ownership in Cloud Manager is one pair of tokens**: `--owner-mine` (the
  accent) and `--owner-other` / `--owner-other-fill` (violet). Anything that
  says "somebody else's" - dot, name, address, Others toggle, External card,
  and every control on the row - reads them; an External row remaps
  `--accent` to them. It was violet on the name and orange on the dot, and he
  asked for one colour "throughout including the buttons".
  `tests/test_cloud_other_owner_is_one_colour.py`.
* `tests/test_every_tool_has_its_own_brand.py` resolves the colours and fails
  on a tool without one, two tools sharing one, or a title under 3:1 on its
  own bar in either theme. A new tool page needs a line in the block.

### The shared look is on scales, and the debt only goes down

Corners use `--r-xs/sm/md/lg` (4/6/8/12) or `--radius-pill`; type uses
`--fs-meta/small/body/emph/section/title`; spacing `--sp-*` on a 4px grid.
`tests/test_the_stylesheet_stays_on_its_scale.py` fails on an off-scale
corner and on any growth in colour literals or distinct font sizes in
`wd-tools.css` - **lower its constants when you remove debt, never raise
them.** Swap a literal for a token only where the token is not redefined per
theme, or the light theme changes under you; compare before/after pixels.

## The Ekahau AP colour palette

`WD.EKAHAU_COLORS` in `web/assets/js/wd-shared.js` is the only copy. Anything
that draws or names an AP colour goes through `WD.ekahauColorKey()` (value →
key) and `WD.ekahauColorName()` (key → Ekahau's word).

| Ekahau's name | key in code | hex |
|---|---|---|
| Clear | `__none` | *(no colour written)* |
| Yellow | `yellow` | `#FFE600` |
| Orange | `orange` | `#FF8500` |
| Red | `red` | `#FF0000` |
| Pink | `magenta` | `#FF00FF` |
| Violet | `purple` | `#C297FF` |
| Blue | `blue` | `#0068FF` |
| Gray | `gray` | `#6D6D6D` (also `#6B6B6B`) |
| Green | `green` | `#00FF00` |
| Brown | `brown` | `#C97700` |
| Mint | `cyan` | `#00FFCE` |

- **Keys and names disagree on purpose.** Saved colour sequences are stored by
  key, so renaming keys would silently reorder them. `WD.EKAHAU_COLOR_ALIASES`
  accepts either vocabulary.
- **Add an observed hex to `WD.EKAHAU_HEX_ALIASES`, never replace one.** Gray
  was "corrected" from a real file's `#6D6D6D` to a picker reading of
  `#6B6B6B`, and every grey AP became `Custom #6D6D6D`.
- Red, Green, Orange, Pink and Gray are confirmed against real files; the rest
  only against the picker. An unknown value is kept, drawn and labelled
  `Custom #XXXXXX` - never dropped or guessed.
- **Every surface goes through the shared pair.** The Report once printed a hex
  heading while the Labeler said `Gray`. `tests/test_ap_color_order.py`.

## Changing a report means printing it and reading it

**A report that renders is not a report that works.** Three defects from one
live job were green throughout because tests asserted properties (the label
was rotated) rather than results (it printed at 24pt over the markers).

For any report change: **generate, print, and measure the PDF.** Can the
person the sheet is for finish their task from it?

- **Installation and placement sheets** - every AP identifier legible, every
  marker findable, model/mount/height/orientation present, sections joined by
  match lines and the key plan.
- **BOM and summary** - every distinct part and quantity, no hand counting.
- **Everything** - nothing overlapping, off the sheet, or clipped at a break;
  headers repeated; no text under about 6pt.

### Six output paths, not one

| Output path | Produces a document | Renders correctly | File name populated |
|---|---|---|---|
| Firefox → Save to PDF | yes | yes | **yes** |
| Chrome → Save as PDF | yes | yes | **yes** |
| Edge → Save as PDF | yes | yes | **yes** |
| Firefox → Microsoft Print to PDF | yes | yes | **no** |
| Firefox → Adobe PDF (Distiller) | yes, since v2.164.1 | not measured | not measured |
| macOS → Print to PDF | not measured | not measured | not measured |

The first three are measured. **A printer names its output file from the
Windows print job, not the page title, and a page cannot change that** - the
Print step says so (`renderPrintHint` in `report.js`). Adobe failed outright
until v2.164.1 because Distiller resolves fonts by PostScript name. **Fill a
row in by printing**; a row that cannot be measured says so. **Do not drive a
Windows printer from Selenium**: silent printing hangs the driver and orphans
Firefox. Never print to a real printer on his machine.

### Fonts

**A font stack uses its first face that exists, not its last.** `'Cascadia
Code'` came with developer tools, so it resolved on dev machines and killed
the job in Distiller. The preferred face has to ship with the OS:

    --mono: Consolas, Menlo, 'DejaVu Sans Mono', monospace;

`tests/test_fonts_survive_printing.py` checks every named face against an
allowlist of OS-shipped ones, custom properties included.

### How to measure

- **Text on text**: pairs of span bboxes overlapping by more than half the
  shorter height and a couple of points of width.
- **Off the sheet**: anything within about 18pt of the edge (Chromium's own
  footer sits there and is not ours).
- **Point sizes**: anything under 6pt is a defect.
- **Cross-references**: every match-line label names a sheet that exists.

**The fixture is synthetic and deliberately imperfect**: two floors, one dense
enough to split into sections, around seventy APs, two omni and two
directional models, long antenna part numbers (real ones reach fifty
characters) - and an AP with a generic name, one with no model, one with no
mount or height, one on no floor plan. A clean project passes everything and
proves nothing.

**A size that is a fraction of the drawing is not a size on paper.** Anything
read off a sheet gets an absolute floor or a size in points - the placement
map's idiom floors at about 1.35% of the long edge, near 7pt - and labels go in
the margin, not on the drawing.

**Before writing a rule for a shared class, check who else uses it**, and
prefer wrapping to `nowrap`. `.rep-ap-table td.rep-name` serves three tables,
and a `nowrap` meant for one broke the other two. Column widths are the
mechanism; `overflow: hidden` on a cell is not a backstop.

## A test that would pass with the feature deleted is not a test

Five shipped defects were green the whole time, all the same shape: the test
asserted the *source contained* something rather than that the *code did*
something. A 2026-09-17 survey found 358 source-text assertions across 61 of
107 test files.

**Instead:** render the real thing, pull the handler out of the rendered
markup, run it, and assert the call that arrives - name, arguments, order, and
the path that should refuse. `tests/test_cloud_sync_direction.py` is the worked
example, using the **real** `WD.escJsStr`. For anything visual, measure the
rendered result. Where a property matters, assert the property, not the
phrasing - a test pinning a sentence pins the bug with it.

**Check your test can fail**: mutate the code and watch it go red. And make
sure the mutation check itself can fail:

* **Clear `__pycache__` either side of every mutation**
  (`find . -name __pycache__ -type d -exec rm -rf {} +`) - a stale `.pyc` can
  keep running the mutated code after restore.
* **Grep the anchor and count it before `str.replace(anchor, new, 1)`** - it
  may hit a different function. If it is not unique, mutate by line number.
* **An async Node probe must `await` its exit**, or `node -e` exits 0 before
  the failures are read. `run_drop` in `tests/test_report_filename.py` has the
  fix.
* **A stub server standing in for `server.py` must answer
  `/api/settings/get`**, or the page decides it has no server and skips every
  server-backed path.

**Slicing a function out of a source file: count the braces.** Slicing to the
next function's start swallows anything inserted between, and searching for a
two-space `}` finds a nested one. This works on CRLF and LF alike:

```js
const a = src.indexOf('  function openHashSection() {');
if (a < 0) throw new Error('openHashSection moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
eval(src.slice(a, b));
```

**A probe's own failure has to be loud**: throw on a missing slice marker, and
raise `AssertionError((r.stdout + r.stderr).strip())` on a non-zero exit. A
probe that returns `{}` passes every assertion of absence. **Stub everything
the code under test calls**, or it throws partway and hides a later write;
read the list off the function with
`sed -n '/function setOpt/,/^  };/p' report.js | grep -oE "\b[a-zA-Z_][a-zA-Z0-9_.]*\(" | sort -u`.

### The ratchet

`tests/test_a_test_must_be_able_to_fail.py`: every handler named in an event
attribute is defined somewhere, and **no test file gains assertions against
its own source** - existing debt is in
`tests/source_string_assertion_baseline.json`. Lower a number, never raise one,
and lower it when you convert a file. Scripts:
`scripts/audit_source_string_tests.py`,
`scripts/audit_tests_that_never_run_anything.py`,
`scripts/audit_handlers_exist.py`,
`scripts/audit_functions_never_named_by_a_test.py`.

### A store with no writer is invisible

**For anything that persists, test that the operation writes it, not only that
the store can hold it**, and assert the value. `sync_state`, the comparison
memory and the merge same-folder guard were each thoroughly tested as stores or
rules while nothing checked the call site that fills or enforces them;
disabling it left the suite green. **A guard or store that exists in two places
needs exercising in both** - mutate one at a time. Only mutation finds these.

## Backups were removed, and that is the design

v2.141.0 deleted `tools/backups.py`, the Backup Folder tab and its endpoints.
**Do not put it back.** His argument: a backup taken out of *doubt* is doubt
made permanent - fix the code or refuse the operation instead. The *undo* case
was already covered: every tool that derives a project writes under a new name,
and Cloud Manager's local copy is a copy of what Ekahau still holds.

**Writes rest on atomicity instead**: build in a temp file and rename over the
top. `_rewrite_project_json` writes nothing when nothing changes, so callers can
re-run safely.

**No text may promise a copy that is not kept.** Every place in `cloud.js` now
names the cloud as the other copy. `NothingPromisesACopyThatIsNoLongerKeptTests`
in `tests/test_cloud_ops_queue.py` fails on the old phrasings and requires the
true one.

**What survived:**

* **`tools/longpath.py`** - `MAX_PATH` handling (`tests/test_long_paths.py`).
* **`tools/settings_backup.py`** - the one exception: a settings import must
  land on `settings.json` itself, so it keeps three dated copies.
* **`backups` stays in `_SKIP_DIRS`** - old installs have that folder full of
  real projects, and a scan that descended into it would flag them all.

**Lessons that outlive the feature:**

* **When a feature moves where it writes, every reader of that location is
  part of the change** - a pruner looking in the old folder found nothing and
  reported success.
* **A root that is "the parent of X" is the whole drive when X is near the
  top.** One scan walked all of `C:\`.
* **`Path.is_dir()` does not swallow WinError 1920** (`ERROR_CANT_ACCESS_FILE`),
  raised by unavailable cloud-storage placeholders and inside `$Recycle.Bin`.
  Anything that walks his tree must survive it.

## Escaping: four sinks, four escapers

Which escaper is right depends on **where the value lands**:

| Where it lands | Escaper |
|---|---|
| Element text - `<span>HERE</span>` | `WD.esc` |
| An attribute - `title="HERE"` | `WD.escAttr` |
| A JS string in an attribute | `WD.escJsStr` |
| A URL | `encodeURIComponent` per component |

This class has been found three times, each time in a shape the previous guard
could not see - including `JSON.stringify(x).replace(/"/g, '&quot;')`, which
never escapes `&`. **Use the function that exists for the job; never assemble
an escaping pipeline at the call site.** The guard is
`tests/test_an_attribute_is_escaped_as_an_attribute.py`.

**A guard must not fire on its own explanation**: strip comments and
docstrings before matching (`_comment_lines` there, `_code_only` in
`tests/test_user_dir_is_the_only_door.py`).

## Comments

His rule: *"leave the code comments in that make the difference."*

* **Don't restate the line below.**
* **Do record a finding** - why it is this way, what breaks if "corrected",
  what failed.
* **Prefer a finding that enforces itself**: a test docstring beside the test,
  a named constant, a runtime rule (`ORDER_RULES` in `tools/prep_pipeline.py`
  is the model).
* **Grep the tests for a comment's text before deleting it** - `// AP dots` in
  `report.js` was a slice delimiter and removing it broke seven tests. Run the
  whole suite.
* `# noqa:` and `# pragma:` are directives; never strip them.

## Every control is declared, not written — `WD.actions`

All pages carry `script-src 'self'` with no `'unsafe-inline'`, so **no inline
`onclick`**. A control names its handler and the dispatcher in `wd-shared.js`
calls it:

```html
<button data-action="call" data-fn="setFilter" data-arg="all">All</button>
```

`data-action` is for a click, `data-action-<event>` for another event in
`EVENTS`. `data-fn` is resolved by walking a dotted path over `window` - a
lookup, not `eval`. Actions: `call`, `call-chain`, `backdrop-call`, `menu`,
`click-target`, `focus-target`, `scroll-target`, `toggle-class`, `noop`,
`prevent`, `enter-call`. Argument order is fixed: `data-arg`/`data-arg-json`,
`data-arg2`, event, element, value, checked. `data-prevent`/`data-stop` call
the matching method. `tests/test_pages_with_a_strict_policy.py` and
`tests/test_strict_pages_work_in_a_browser.py` hold it.

Traps:

* **`data-args-json` carries a whole argument list** - use it rather than
  inventing a separator format.
* **`data-fn-<event>` names a handler per event.** Multiple `data-fn`
  attributes silently keep the first.
* **`data-arg-checked` passes a checkbox's state**; `data-arg-value` gives the
  string `"on"` either way.
* **`prevent` is not `noop`**: `noop` stops propagation.
* **`e.currentTarget` is the document under delegation.** Take the element
  argument.
* **An escaper wrapper can carry behaviour.** `cloud.js`'s old `pj()` also
  normalised backslashes; `np()` does that now.
* A harness that stubs `escAttr` as identity produces unparseable markup.

## Known gotchas

- **Every tracked text file is stored with LF.** `core.autocrlf` only filters
  `git add`; `git hash-object -w --stdin` **without `--path`** applies no filter
  and once committed a 32-line change as a 20,434-line diff.
  `tests/test_every_tracked_file_is_stored_with_lf.py` reads the index. To
  repair, rewrite the blob and re-stage; use `\r+\n` because a mixed edit can
  leave `\r\r\n`. `*.bat text eol=crlf` in `.gitattributes` is a checkout rule
  only.

- **Write the character, not an escape for it.** Patch scripts have produced
  `\\u2019` on screen and heredocs have eaten `\25BE`.
  `EscapeSequencesDoNotReachTheScreenTests` in
  `tests/test_cloud_list_design.py` catches double escapes. If a heredoc keeps
  mangling backslashes, use the editing tools.

- **Pass `encoding="utf-8"` to every `subprocess.run` that reads Node's
  output.** `text=True` uses the locale - cp1252 on Windows - so a probe passes
  in CI and fails on his machine.

- **CI runs Python 3.10 and 3.14; he runs 3.12.** A check on *how* the
  interpreter reports something is a check on its version - e.g.
  `SyntaxWarning` vs `DeprecationWarning`. Assert that it happened, not its
  class or wording. Matrix: `[windows-latest, macos-latest]` x
  `['3.10', '3.14']`.

- **`zip_update` replaces a user's install and is now tested end to end** by
  `TheRealUpdateRunsTests` in
  `tests/test_release_archive_paths_are_contained.py`, after a shadowed
  variable once pointed it at a temp directory that was then deleted.

- **A wall template updates every type it carries, including Ekahau's stock
  ones - and three are recoloured on purpose:** `Elevator Shaft` green,
  `Door, Steel Fire/Exit` orange, `Window, Thick` `#0093EA`, because Ekahau's
  greys for those are hard to tell apart. Do not "restore" Ekahau's defaults
  or add a skip-stock-types guard - both were done once and he asked for them
  reversed. The `kept` / `keptPhrase` reporting is still in `walls.js`.

- **AP notes pages print last.** Every renderer in `report.js` concatenates
  `apNotesPages(...)` **in its return expression**
  (`tests/test_ap_notes_last.py`), because the section is unbounded.

- **Per-page orientation works in Firefox, Chrome and Edge**, via named
  `@page` rules in `web/assets/wd-tools.css` (measured). **The invariant: layout
  and sheet must never disagree** - where named pages are unavailable, pick one
  orientation for the whole document. **A whitespace text node beside a
  `display:none` sibling gets its own print box in Firefox** and can give
  page one the default paper; `dropPrintWhitespace` in `report.js` strips them
  (`tests/test_report_first_sheet_orientation_browser.py`). Label-placer
  clipping is a separate defect (`tests/test_marker_bounds.py`).

- **A requirement area stops the canvas being trimmed, so trimming always runs
  first.** `esx_trimmer._floor_coord_bbox` includes area coordinates in the
  crop, and on an empty plan the area is the whole sheet, so the floor is
  skipped as "already fills 100%". `STEP_ORDER` and `ORDER_RULES` in
  `tools/prep_pipeline.py` enforce it; `tests/test_prep_pipeline.py` tests it
  twice. Wall-type injection can run either side.

- **AP notes live in `notes.json`, not `pictureNotes.json`.** Entries are
  `{id, text, imageIds[], history?}`; a picture note is a note with
  `imageIds` and often empty text. An AP's `noteIds` is an array - resolve
  every id. `notesForAp()` skips a note only when text **and** images are both
  empty. `pictureNotes.json` is a different feature (pins with
  `location.coord`).

- **The owner filter is saved.** What the list opens on is
  `cloud.default_owner_filter` in `settings.json` (Settings → Default view),
  **shipping as `"mine"`**; `loadDefaultOwnerFilter` falls back to `"all"`
  only when settings cannot be read. Pressing All / Mine / Others in the
  toolbar writes that same setting (`setOwnerFilterUI`), at his request - it
  used to reset on reload and he re-picked Mine after every update. That is
  safe only because `renderOwnerFilterNotice` names any filter narrower than
  All above the list. Never put it in `localStorage`.
  `tests/test_cloud_owner_filter.py`.

- **Every matched row gives each side its own checkbox** (`s-c:`/`s-l:`,
  `ct-c:`/`ct-l:`). Selecting either resolves to the pair for bulk Sync, but
  deletes stay `'cloud'` or `'local'` - a cloud delete cannot be undone.
  `tests/test_cloud_each_side_has_its_own_checkbox.py`.

- **There is no typed-`DELETE` gate, deliberately.** The delete dialog names
  every item - project, site, last change, who loses access - never "and 12
  more". `tests/test_cloud_delete_identity.py` asserts the old modal's absence.

- **A note here can go stale just like UI text can.** Nothing checks this
  file's claims against the code. When something here contradicts the code,
  trust the code, fix the note, and say so in the commit.

## The dev toolbar

**The toolbar is permanent.** *"I always like to keep a dev toolbar on all of
my projects."* It is **WaxFrame Professional's method, not an
interpretation of it** - the first build reshaped it and he rejected that:
*"I asked for the method that we used in WaxFrame Pro."* Where something in
WaxFrame cannot carry over, say "WaxFrame does X, it cannot work here because
Y, so I propose Z" - do not silently improve on it.

    web/assets/js/wd-dev.js          gate, dispatcher, drag, mount (portable)
    web/assets/js/wd-dev-actions.js  every button's markup and handler (this app's)
    wd-tools.css                     `.dev-*` rules, at the end

**The method:**

* **Gate**: `localStorage['wd_dev'] === '1'`, set by a SHA-256 password modal.
  A wrong password closes the modal silently. `?dev=1` is the other route in;
  **no key chord**, ever.
* **Entry**: a Dev Tools item under **Advanced** in every menu, visible while
  dev mode is **off** (it is the way in); an exit item appears when on.
  Injected by **class** - `.main-menu, .help-menu, .wd-menu` - because pages
  name their menus differently and drop-zone tools have two.
  `tests/test_dev_nav_on_every_page.py` walks every page that loads
  `wd-dev.js`. `setup.html` has no menu, by design.
* **Layout**: one horizontal strip, `⚙ DEV` label as drag handle, position in
  `localStorage['wd_dev_toolbar_pos']`. Buttons carry **readable names**, and
  **nothing in the strip writes** - each opens a panel that states what it
  looks at, changes and will not do.
* **Dispatch**: `data-action="call" data-fn="WD.Dev.x"`, scoped to
  `#wdDevRoot`.
* **Adding an action**: one button in `Dev.toolbarInnerHtml`, one handler in
  `wd-dev-actions.js`.

**The password is the same hash WaxFrame Professional uses**, at his request.
The plaintext is in neither repository; `tests/test_dev_password_hash.py`
checks the hashes match and scans for anything password-shaped. The flag is
obfuscation, not security. **The two housekeeping actions that write are gated
by the server**: every run starts locked and `/api/dev/unlock` checks the
password with `hmac.compare_digest`. The survey is a read and is deliberately
not gated. This is not a claim that the rest of the API is authenticated -
what protects `/api/cloud/*` is that every destructive action re-derives its
target server-side. `tests/test_the_dev_actions_that_write_need_the_server.py`.

**Panel behaviour, each from something he hit:**

* **Controls live in the modal footer, outside the scroll.** A report six
  screens tall put the armed button off-screen.
* **Closing and reopening keeps the last result and stays armed**, stamped
  with when it was taken. That is safe because **the client is not the
  guard** - the server re-derives everything at write time. A spent delete
  list is cleared.
* **Preview is lime and says it changes nothing; the live control is pink,
  `disabled` until its own preview succeeds, and names the count.**
* A future action that runs for minutes needs visible progress and a
  finished state that says "Finished" in words. The removed realign action
  did this by sending an `opId` and polling `/api/cloud/progress` every
  250 ms; its code is in git history before v2.193.0.

**Testing it**: `tests/test_dev_toolbar_browser.py` drives it in all three
browsers over plain `http.server` on `web/`, with `WD.api` stubbed.
`WD.Dev._hash` / `_expectedHash` let a test drive the real gate with an
invented password. Selenium Manager drops `geckodriver/` and
`se-metadata.json` into the working directory; both are gitignored.

**The realign action was a one-off and was removed in v2.193.0**, after it had
been run. `tools/cloud_realign.py` stays: Cloud Manager's reconcile action on
selected rows (`reconcile_pairs`) uses it. Its trap still applies there:
`get_local_esx_files` reports `internalMtime or fs_mtime`, so **`os.utime`
alone does not move the date the row compares** - both are set.

### Housekeeping

`tools/housekeeping.py` inventories session debris and says what is safe to
remove. Read its module docstring before changing it.

* **It flags on what is inside an `.esx`** (name and author in
  `project.json`), not the extension - the extension-based version flagged
  2,226 test fixtures.
* **Bound every quantifier in a scanning regex.** An unbounded email pattern
  took 163 seconds on one log file.
* **`git worktree list` must be run with the repository as `cwd`**; outside a
  repo it returns nothing and every worktree looks abandoned - the failure is
  toward deleting more.
* **It deletes only inside roots we own, and re-derives the list at delete
  time.** `stop_processes` checks every PID against a fresh
  `list_processes()` because Windows reuses PIDs; `stop_process` is only
  called through it. `refused_roots()` uses `user_dir()`, not the default.

## Worktrees and session artifacts

**Local sessions work in their own worktree, never the shared checkout.**
Several sessions run against his local repository at once, and a shared tree,
index and HEAD caused a string of incidents: commits swallowing another
session's staged work, a tag on the wrong commit, a release with an untracked
module. A cloud session is already its own clone and needs none of this.

The rules, for a local session:

* **Worktrees live at `C:\wd-worktrees\<session-name>\`**, outside Dropbox,
  branched from `origin/main`:
  `git worktree add -b claude/<name> C:\wd-worktrees\<name> origin/main`.
* **Fetch and rebase at the start and before any large change**, not only at
  push time, and re-read this file - it is what most often changes underneath
  you.
* **Merge back**: suite green, `git fetch`, `git rebase origin/main`, suite
  green again, `git push origin HEAD:main`. **Never force-push `main`.**
* **The stash stack is shared** across worktrees; stash with a unique message
  and apply by id.
* **Remove it when finished** (`git worktree remove`, `git branch -d`,
  `git worktree prune -v`). **Prune does not find an abandoned worktree** -
  only one whose directory is gone. Reconcile the directory listing against
  `git worktree list`. A teardown that fails with `Permission denied` on an
  empty directory is usually a process of your own still running inside it.
* **`C:\wd-worktrees` holds worktrees and nothing else.**
* **Permanent "slot" worktrees were tried and rejected** on 2026-09-29; do not
  propose them again.

The full commands, the reconcile script and the incident record are in
`docs/dev-notes/local-worktrees.md`.

**Session artifacts go in one place: your scratchpad**, or inside your own
worktree. Screenshots, scratch scripts, probe output, downloads, draft commit
messages - **never his Desktop**, not `~/Downloads`, not the repo root, not a
hand-made `%TEMP%` folder. A 2026-09-17 sweep recovered 12.73 GB of session
debris and found 27 files of real workplace data in `%TEMP%`.

**The suite cleans up after itself.** `TheSuiteCleansUpAfterItself` in
`tests/test_housekeeping.py` fails if a function calls `mkdtemp` without
cleanup. `WD_KEEP_TEST_USER_DIR=1` keeps the test user directory when you want
the evidence. **Report what you found and removed rather than cleaning
quietly.**

## Memory across sessions

Sessions have no memory of past conversations - only what is in the repo
(this file, the code, `BACKLOG.md`, `docs/dev-notes/`). If something matters
for next time, write it here, and keep it to the rule and the reason. The
history belongs in the commit message.
