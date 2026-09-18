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
commit messages, published GitHub release notes, the landing page, and
screenshots.

**When he shares a real project to settle a technical question** - and he does,
sparingly, because he keeps work data out of development - read it for
structure and metadata only. Do not copy its content, do not turn it into a
fixture, and do not let a name or a figure out of it reach a commit. Build the
fixture synthetically, with invented names.

**Assume this repository is public, because it is.** Anything committed is
published, and a public repository is not a place anything can be quietly
un-published: release notes can be edited, but ZIP assets, forks, clones and
commit history cannot be taken back the same way.

**If you are unsure whether something is traceable to his employer or to a
real person, leave it out and ask.** Unsure is a hit.

**One file in the user data directory is worse than the rest and should be
treated that way.** `~/.wd_wireless_tools/share_recipients.json` holds the
email addresses of real colleagues - not a path or a filename, other people's
contact details. `tools/share_recipients.py` manages it; it is gitignored,
absent from the release payload, and has no network imports at all, and
`tests/test_share_recipients.py` asserts each of those. Never open his copy to
"see the real shape", never paste a line of it into an issue or a commit, and
never build a fixture from it. Every address in this repo is invented at an
RFC 2606 documentation domain.

**The guard covers the history now, not just the working tree.** For a long
time `tests/test_no_real_world_data.py` read `git ls-files` - the files checked
out right now - and nothing else. The repository is public, so every commit
message and every blob ever committed is published too, and none of that was
being checked. A survey on 2026-09-17 found site-code-shaped tokens still in
both, on `main`, long after the tree had been cleaned - including in the
message of the commit that did the cleaning, which is the scrub-without-quoting
trap.

`TheHistoryIsCheckedToo` closes it, and it is **a ratchet rather than a gate**.
What is already published is listed by object id in
`tests/no_real_world_data_baseline.json` and skipped; anything new fails. That
split is deliberate: failing on the existing history would pin CI red until
somebody rewrote published history, and that is a decision to take on purpose,
not one a test should force. Cleaning the working tree afterwards does not
unpublish a blob, so the check is on the commit.

**Nothing prints the value.** A failure names the commit or blob id and the
path and stops there - a CI transcript is as public as the thing it is
complaining about. Regenerate the baseline with
`python scripts/refresh_history_baseline.py` after a deliberate rewrite; it
should only ever get shorter.

### Why this is rule zero rather than a guideline

It was escalated as an emergency, in those words, because it had already gone
wrong. A real site code was the worked example for Cloud Manager's site-code
match - in `cloud.html` and `guide-cloud.html`, so it was **on screen in the
shipped product**, and inside every release ZIP. A real building and city, a
real Ekahau Cloud project name and a second site code were sitting in release
notes. His employer's name reached a published release note in a quoted CAD
sheet title. None of it was malicious; each one arrived the same way, as real
data used to reproduce a real problem and then left behind.

`tests/test_no_real_world_data.py` enforces what can be enforced: every
site-code-shaped token in tracked files must be on an allowlist of invented
ones, emails must use documentation domains, and no credential shapes or
infrastructure addresses are allowed. **A new placeholder will fail that test.
That is the check working** - confirm the value is invented, then add it to the
allowlist. Never add a real one to make the suite green.

The audit lesson is in the method: searching a *list of known names* missed
every real identifier that was found. Enumerating every token of the shape and
reading all of them is what worked.

## A version bump on `main` is a release — that part is automatic now

**Bump `web/assets/versions.json` and the release publishes itself.** You do not
tag, you do not run `gh release create`, and you must not hold a release back
waiting for a better moment. `.github/workflows/auto-release.yml` watches that
one file: when the `suite` value on `main` has no matching tag, it runs the full
suite, tags **the commit that bumped it**, verifies `versions.json` *at the tag*,
publishes, and calls `release-assets.yml` to attach the ZIP and its checksum.

**Why this stopped being a manual step.** "Why were commits created with no
releases?? That should never happen." He is right, and it was a process gap
rather than a slip. Main went red on a test, three sessions correctly held their
tags, two were cut afterwards and one was not; later sessions then bumped the
version and deliberately did not tag, reasoning that pushing a tag is ceremony
to perform only when asked. Every one of those decisions was defensible on its
own. The result was three versions of finished work he could not install, while
he sat at work fighting the old build and reporting bugs that were already
fixed.

**He installs what is published.** An unreleased commit is not "nearly
shipped", it is invisible - the same problem as uncommitted work wearing a
different hat. So the remembering is gone: green suite and a new version means
a release exists, and a red suite means no release at all, which is the
behaviour that saved three bad tags and is preserved deliberately.

Four properties, each one a failure that has already happened here, and
`tests/test_release_is_automatic.py` holds all of them:

* it fires **only on a version change**, not on every commit
* **a red suite publishes nothing**
* it tags `github.sha` - **the commit the run was for** - never a moving HEAD,
  which is how `v2.103.14` landed on another session's commit
* it re-reads `versions.json` **at the tag** before publishing, because that is
  what `build_release.py` reads

**The one thing that is not obvious and would silently break it:** a release
created with `GITHUB_TOKEN` does **not** fire `release: published`. GitHub
suppresses that to stop workflows looping. So the automatic path cannot rely on
`release.yml` noticing - it calls `release-assets.yml` itself, and both paths
share that one workflow rather than each having their own copy of the build.
An asset-less release is worse than no release: the updater and both install
scripts refuse a download whose checksum does not match, so the user is stuck
rather than merely out of date.

The notes are the commit message, which in this repo is usually the better
document anyway. Replace them with a hand-written note afterwards
(`gh release edit`) when the release deserves the full treatment described
below - and for a user-facing feature it does.

`release.yml` remains for a release published by hand through the GitHub UI,
and for backfilling assets onto a tag whose build failed.

## Release process — the parts that are still yours

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
   **Then wait for the push's CI run to go green before pushing the tag**
   (`gh run watch`). A local suite and CI do not ask the same question: CI
   runs against a clean checkout, so it is the only thing that sees a file you
   forgot to `git add`. v2.102.0 went out with `tools/user_dir.py` untracked -
   the local suite passed because the file was sitting there untracked, CI
   failed with 30 errors, and the tag and release were pushed over the top of
   that failure. The result was a release whose server could not start and
   which had no ZIP asset, because the release build correctly refused to
   package a failing tree. `tests/test_shipped_modules_are_tracked.py` now
   catches that particular shape locally, but red CI means stop, whatever it
   says.
5. **The release publishes itself** once the bump lands and CI is green - see
   the section above. What is still worth doing by hand is the *note*: edit it
   afterwards with `gh release edit vX.Y.Z --notes-file notes.md`, in the
   WaxFrame Pro style (H1 = one-line summary, `## What changed` with bullets,
   `## Verified`, `## Files changed`).

   The commands below are the manual ceremony. You should not need them, and
   they are kept because the reasoning in them still applies to anything that
   tags by hand:
   ```powershell
   git tag -a vX.Y.Z -m "vX.Y.Z" <the sha of your own version-bump commit>
   git show vX.Y.Z:web/assets/versions.json   # must say X.Y.Z before pushing
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "WD Wireless Tools vX.Y.Z" --notes "..."
   ```
   **Name the SHA. Never tag HEAD.** Several sessions share this one working
   tree, so `main` can move between your push and your tag — and a bare
   `git tag` then puts your version number on somebody else's commit. That
   happened to v2.103.14: another session committed v2.103.15 in the seconds
   between, the tag landed on their commit, the release build correctly refused
   it (`Requested release 2.103.14 does not match suite version '2.103.15'`),
   and the release had notes and no ZIP. The tag and release were deleted and
   the change shipped inside v2.103.15, whose ZIP already contained it. The
   `git show` line above is the cheap check: it reads `versions.json` **at the
   tag**, which is exactly what the workflow will read.

   **And never run a bare `git commit`.** The index is shared too. A
   documentation-only commit run with no paths swallowed another session's
   fully staged margin work - fifteen files, a version bump and all - and
   published it under a message that ended "Documentation only ... so no
   version bump", which by then was false. Nothing was lost, but the history
   now says something that is not true. Name the paths every time:
   `git commit -F msg.txt -- path/one path/two`, which commits those paths
   from the working tree and ignores whatever else is staged.

   **Staging a file another session is also editing needs content-based
   staging, not `git add`.** `git add` takes the whole file including their
   half-finished work - and if their half references a module they have not
   tracked yet, that is v2.102.0 again. The way that works: take `git show
   HEAD:path`, apply your own edits to *that*, `git hash-object -w --stdin
   --path <path>`, then `git update-index --cacheinfo 100644,<sha>,<path>`.
   Their working tree is untouched and only your change is staged. Verify it
   before committing by exporting the index somewhere else and running the
   suite there: `git checkout-index -a -f --prefix=/some/dir/`. That is the
   tree CI will see, which is the only tree whose test result means anything.

   **A test that reads the live repository will go red for reasons that have
   nothing to do with your change.** `tests/test_updater.py::BlockedApiTests`
   patched three calls and left `remote_branch_state`, which asks how far
   behind `origin/main` this checkout is - so it passed only while the commit
   under test was the branch tip, and failed on a re-run after anything else
   landed. Fixed in v2.103.17. If CI fails somewhere you did not touch, check
   whether the test is asking the repository a question before assuming you
   broke it.

   The release workflow (`.github/workflows/release.yml`) triggers on
   `release: [published]`, checks out the tag, runs tests, builds the ZIP via
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


## Unrecoverable earns friction, not refusal

**A guard that refuses the ordinary state of his work is a wall across the main
road.** When an action cannot be undone, make it ask - do not make it
impossible.

The case that named this: `Local → Cloud` shipped with
`PUSHABLE_MATCH_TYPES = {id, manual}`, so replacing a cloud project was offered
only on a pair sharing Ekahau's id or one he had linked by hand. The reasoning
was sound - a cloud delete cannot be undone, so the pair should be proven - and
the effect was that the feature never worked for him. A project built locally
and uploaded carries Ekahau's id in the **cloud** copy only; the local file does
not have it until the project is downloaded back. "Local is newer and there is
no shared id" is therefore the normal state of work in progress, and it was the
one thing the guard refused. He asked for that feature about six times and every
ask produced code he could not reach.

It is allowed now and asks once, naming the cloud project it will delete. A
*guessed* pairing - a shared site code, similar wording - is still refused,
because there the two names are not even the same and there is nothing for him
to confirm against. That is the line: **confirm what he can check, refuse only
what he cannot.**

The same mistake in other clothes, already paid for here: the Prep pass that
threw away completed work because one step refused, and the delete that made him
type `DELETE` for something a backup already covered. He has said it plainly
more than once - a guard that fires on his normal case is worse than no guard,
because he stops believing the ones that matter.

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
- **`WD_USER_DIR` is enforced, not just available.** Set it to a scratch
  directory before starting any server you are going to drive, and his real
  configuration cannot be reached.
  `tests/test_user_dir_is_the_only_door.py` imports every module that owns
  user data with the variable set and asserts that every path it will write to
  moved - and that nothing rebuilds `Path.home() / ".wd_wireless_tools"` for
  itself. It is read once at import, so exporting it after a process starts
  does nothing.

- **Never bind a default or shared port.** Several sessions work in this repo at
  once, and 8675 is the user's own running instance. Pick an explicit, unusual
  high port, and pick a different one per session rather than the number
  everybody reaches for.
- **Always tear it down**, on the failure path too. An abandoned process holds
  the port for the next session. Kill it by PID on the port, not by name — that
  would take down the user's own instance.
- **Starting the server opens a browser window on his desktop, and nobody
  closes it.** `main()` spawns `_open_browser()` unconditionally, so every test
  server a session starts puts a real Firefox window on the machine pointing at
  its port. They are never cleaned up, and Firefox keeps about ten content
  processes per window. Measured on 2026-09-16 after a day of sessions doing
  this: **307 Firefox processes holding 22.5 GB, with 1 GB of 32 GB free** -
  which is most of a day's unexplained slowness. Do not run `server.py`
  directly for a check. Extract the tree you want to a scratch directory and
  neutralise `_open_browser` there, or import the module and replace it before
  calling `main()`. If you find leftovers, the safe way to identify them is the
  command line: they read `-osint -url http://localhost:<port>/`, and one whose
  port is no longer listening cannot be anything the user is looking at. Never
  kill `firefox.exe` by name - his own browser is in that list.

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

### A control is verified by running its handler, not by finding its name

**Asserting that the source contains `doTheThing(` proves the string exists. It
does not prove anything happens when he clicks it.** Four defects have now
shipped green this way, the last being a `Local → Cloud` button that rendered
perfectly and was inert for every pair he owned.

So for any control, the test renders the row with the **real** render function,
pulls the `onclick` back **out of that HTML**, and executes it against recording
stubs. `tests/test_cloud_push_is_reachable.py` is the pattern. It catches a
handler that is missing, misnamed, takes different arguments, or bails before
reaching the server - none of which a substring assertion can see. It also
pins the argument order, which matters when one of them names the thing that
gets deleted.

And if any text in the app tells him to use a control, that control has to
exist: `TheAppOnlyPointsAtControlsThatExistTests` fails on a bolded control name
that nothing renders. The Sync dialog spent a release telling him to use a
button that was greyed out for every row he had, which reads as the tool lying
to him. Either wire it or stop naming it.

### Browser verification — Chrome, Edge and Firefox, every time

**Standing rule from the user: anything user-facing is checked in all three.**
Not Firefox alone, and not Chromium alone. This was written down only after a
sweep was run in Firefox by itself and he had to say so again, so it is the rule
rather than a suggestion.

All three are installed:

    Chrome   C:\Program Files\Google\Chrome\Application\chrome.exe
    Edge     C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
    Firefox  C:\Program Files\Mozilla Firefox\firefox.exe

That Firefox line carried a literal form-feed for a while, so it read
`Mozilla Firefoxirefox.exe` - the `\f` had been interpreted rather than
written. If a browser will not start, check the path exists before you
believe the error: the same mistake against Edge surfaces as
`NoSuchDriverException: Unable to obtain driver for MicrosoftEdge`, which
reads like a missing driver while the driver sits in `~/.cache/selenium`
the whole time.

`selenium` drives all three; Selenium Manager fetches each driver itself, so
there is nothing to install by hand. Point `options.binary_location` at the
executable above and use the matching `Options` class.

**Firefox still decides a print question**, because it is what he prints from
and it is the engine that has twice carried a fault Chromium does not have - the
trailing blank sheet in v2.96.2 among them. So: check all three, and when they
disagree about print, Firefox is the one that matters.

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

**Do not install Playwright.** It was tried on 2026-09-15 and removed the same
night. Its bundled Firefox spawned processes that never exited, those locked its
own binary, and every launch after the first failed with `spawn UNKNOWN` against
files its own zombies were holding - which reads exactly like a policy block and
is not one. It left eight orphaned processes running and 683 MB in
`%LOCALAPPDATA%\ms-playwright`. `selenium` + the installed Firefox does the same
job, cleans up after itself, and drives the browser he actually prints from.

**A second path that works, and needs no hand-rolled websocket: geckodriver.**
`pip install selenium`, then `webdriver.Firefox(headless)` →
`driver.print_page(PrintOptions())`, which returns the same base64 PDF through
the same Firefox print pipeline. Selenium Manager fetches geckodriver itself, so
there is nothing to install by hand. Two things to know. `PrintOptions` is in
`selenium.webdriver.common.print_page_options`, not the firefox package. And
setting `page_width`/`page_height` on it **overrides what the CSS asked for** -
leave them unset when the question is what `@page` does, or every sheet comes
back the size you pinned and you will conclude the engine ignored the rule.

This is what found the trailing blank sheet in v2.96.2 - a fault Chromium does
not have and that therefore survived every check made here until one was run in
Firefox. Page count is the assertion: seven sheets before, six after. A page
carrying nothing but the body's white background reads as `chars=0 imgs=0
draws=1` through PyMuPDF, which is how "blank" was made checkable rather than a
matter of opinion.

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

## Logging — `tools/applog.py`, and why there is only one of it

**Anything that goes wrong goes through `applog`, not `print`.** A fault
appeared in his terminal on a machine three hours away, printed a wall of
traceback, and was gone the moment the window was closed. One chance to see
it, missed - that is what this exists for.

- The file is `~/.wd_wireless_tools/logs/wd-wireless-tools.log` - on Windows,
  `%USERPROFILE%\.wd_wireless_tools\logs\`. **Do not add a second log
  location.** The user directory is where state lives; a second home for it is
  the same bug as the two-store settings drift above.
- **It appends and is never truncated on startup**, and the last **7 days** are
  kept, yesterday's filed under its own date. That mode is not an incidental
  default: a handler opening in `w` destroys the evidence at the exact moment
  someone restarts to see whether the fault recurs, which is the sequence that
  lost one. Ceiling is `MAX_TOTAL_BYTES + MAX_FILE_BYTES` = **10 MB**,
  enforced by pruning oldest-first, not estimated.
- **Measured growth on a healthy install: 90 bytes per launch, and nothing
  else** - browsing every tool and calling every endpoint added zero. Root
  logger sits at WARNING and `wd` at INFO deliberately, so library chatter
  cannot rotate the useful part out. If you add per-request logging, put it
  behind a level that can be dialled down.
- `applog.install()` is called once from `main()`. It installs **both**
  `sys.excepthook` and `threading.excepthook` - a raising background thread is
  never seen by the first, prints to stderr, and the process carries on
  serving, which is exactly the failure that leaves no trace.
- `applog.note_failure("update check", exc)` for anything the app chooses to
  carry on from. `applog.console(...)` for the one line the terminal gets.
- **A traceback must never reach his terminal.** `server.py` has a catch-all
  `@app.errorhandler(Exception)` that logs the stack to the file and returns
  short JSON; Flask's default writes the whole stack to stderr, which is how
  one failing request filled the console with seventeen lines.
- The path is on screen in **About → Diagnostics** with a copy button, and in
  the startup banner. Every run writes a `started - version ...` line, so the
  file always exists (About must not point at nothing) and the first question
  - which version was running - is already answered.
- **It holds real paths and hostnames, so it is rule zero material**:
  gitignored, absent from the release payload, never a fixture, never
  uploaded. `tests/test_applog.py` holds all three.

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

## Changing a report means printing it and reading it

**A report that renders is not a report that works, and only one of those had
ever been checked.** Three defects were reported from a live job in one
evening - match line text painted across the AP markers at 24pt, AP names
printed on top of the floor column, a compass page set at 3.9pt - and every one
of them was green in the suite the whole time. The tests asserted properties:
that the match line label was rotated, that the table had `table-layout: fixed`.
Both were true throughout the period the sheets were unusable.

So, for any change to report generation: **generate the affected reports,
print them, and measure the PDF.** The question is not "did it render" but
"can the person this sheet is for finish their task from it".

- **AP installation and placement sheets** - an installer standing in the
  building. Every AP identifier legible at printed size, every marker findable,
  model, mount, height and orientation present, sections joining up through the
  match lines and key plan.
- **Bill of Materials and the summary** - someone raising a purchase order.
  Every distinct part and its quantity, without counting anything by hand.
- **Everything** - nothing overlapping, nothing off the sheet, nothing clipped
  at a page break, table headers repeated on every page they continue onto, and
  no text under about 6pt.

### What to measure, and how

`tests/test_ap_notes_page.py` is still the pattern for anything checkable in
Node. What that cannot do is measure ink on paper, and that is where these
faults live. Print through the real pipeline (`driver.print_page(PrintOptions())`
- see the browser section above) and read the PDF with PyMuPDF:

- **Text on top of text.** Take every span's bbox and look for pairs that
  overlap by more than half the shorter one's height and a couple of points of
  width. That single check finds the whole class: 24 hits on the aim sheet, 4
  on the BOM, none after. Glyph boxes run slightly above and below their ink,
  so a large numeral over its own caption is a false positive - hence the
  thresholds.
- **Anything outside the printable area.** Any span or image whose box passes
  within about 18pt of the sheet edge. Chromium's own page footer sits there
  and is not ours.
- **Point sizes.** Collect every span's size. Anything under 6pt is a defect,
  not a style choice.
- **Cross-sheet references.** Collect the section headings and the match line
  labels and confirm every reference names a sheet that exists.

### The fixture, and why it is deliberately imperfect

Build it synthetically, invented throughout, and structurally realistic: two
floors, one dense enough to trigger section splitting, on the order of seventy
APs, **two omni models and two directional models** so per-model counts are
exercised, external antennas with azimuth, tilt, mount and height, and
deliberately long antenna part numbers - a real one is fifty characters and
that is what overflows a table.

And leave faults in it: an AP with a generic name, one with no model, one with
no mount or height, one on no floor plan. Every one of those found something.
A clean project passes everything and proves nothing.

### The rule that keeps coming back

**A size that is a fraction of the drawing is not a size on paper.** The match
line label was `min(cellW, cellH) * 0.045` and printed at 24pt. The aim
mini-map and coverage markers were `min(W, H) * 0.022` and printed at 5.4pt.
The placement map has had the right idiom since v2.52 with the reasoning
written beside it - floor the value at about 1.35% of the long edge, which
lands near 7pt at the width these print - and the fix each time was to use it.
Anything a person reads off a sheet gets an absolute floor, or a size in
points, and the label goes in the margin rather than on the drawing.

### And the one that caused two of them

`.rep-ap-table td.rep-name` is used by three tables. Its print rule said "the
AP name is transcribed onto a physical label, so it is never cut" and
implemented that as `white-space: nowrap; overflow: visible` - which is not
"never cut", it is "never wrapped, and allowed to leave the cell". Only one of
the three tables holds a short AP name. **Before writing a rule for a shared
class, check who else uses it**, and prefer wrapping to nowrap: wrapping loses
no characters, which is what "never cut" actually asks for. `overflow: hidden`
on a table cell is not a reliable backstop on its own - the BOM had it and
overflowed anyway. Column widths are the mechanism.

## A test that would pass with the feature deleted is not a test

**Five shipped defects were green the entire time they were broken**, and all
five were the same shape: the test asserted that the *source contained*
something rather than that the *code did* something.

- **Apply-to-all** reported "Applied to 1 floor" while discarding the work.
- **The match line label** test asserted the label was *rotated*. It passed for
  the whole period the installer sheets were unusable.
- **`↑ Local newer · replace cloud`** - the tests asserted the markup contained
  `pushLocalOverCloud(`, and it did. He could not use it for days.
- **Prep's wall step** was verified 1 → 26 on fixtures while doing nothing
  visible on his machine.
- **The backups wording** was pinned by a test requiring a particular sentence,
  so five dialogs told him the wrong place to find a file he had just
  overwritten. A test that pins the phrasing pins the bug with it.

A survey on 2026-09-17 found **358 assertions against the text of a source
file, across 61 of 107 test files** - 120 of them in 22 files that never
execute anything at all.

### What to write instead

**Render the real thing, pull the handler back out of the rendered markup, run
it, and assert the call that arrives** - its name, its arguments, their order,
and what happens on the path that is supposed to refuse.
`tests/test_cloud_sync_direction.py` is the worked example: it evaluates the
`onclick` it finds in the output, with `pushLocalOverCloud` and friends
stubbed, and checks the five arguments. It uses the **real** `WD.escJsStr`,
because a project named with an apostrophe or a path with a backslash is
exactly what turns a present button into a dead one.

For anything visual, **measure the rendered result** rather than asserting the
rule exists - see the report section above, which prints the PDF and reads back
point sizes and bounding boxes.

**Where a property genuinely matters, assert the property rather than the
phrasing.** The backups case is the rule: require that the dialog names the
location `_backup_target` actually uses, not that it contains a given
sentence. Wording changes; being wrong about where his file went does not
become acceptable because the sentence was updated.

**Check your test can fail.** Mutate the thing it covers and watch it go red.
Swapping the first two arguments of `pushLocalOverCloud` fails the new test and
passed every one of the assertions it replaced.

### The ratchet

`tests/test_a_test_must_be_able_to_fail.py` holds two properties:

- **every handler named in an event attribute is defined somewhere** - 299
  checked, and a name in an `onclick` is a string until something calls it;
- **no test file gains assertions against its own source.** Existing debt is
  recorded per file in `tests/source_string_assertion_baseline.json` and
  tolerated; growth fails, and so does leaving a stale number in place after
  converting a file. Lower a number, never raise one.

`scripts/audit_source_string_tests.py` prints the inventory,
`scripts/audit_tests_that_never_run_anything.py` splits it into files that
execute and files that do not, and `scripts/audit_handlers_exist.py` is the
handler check.

## Known gotchas

- **Write the character, not an escape for it - and never let a patch script
  decide how many backslashes that takes.** This file is UTF-8 and the source
  is full of arrows, ticks, stars and em dashes written literally; a tooltip
  already says "Cloud → Local: apply the cloud name". An escape buys
  nothing, hides what the string says from anyone reading it, and has now gone
  wrong three ways in one session:

  - a patch written in a Python raw string put `\\u2019` into `cloud.js`, so a
    tooltip would have read "the two files\u2019 contents" - valid JavaScript,
    green tests, visible only to him
  - a bash heredoc read `\25BE` as an octal escape and a chevron rendered as
    "BE"
  - a test looking for the arrow could not find it, because the test wrote the
    character and the source wrote the escape

  None of those breaks a build. `tests/test_cloud_list_design.py::
  EscapeSequencesDoNotReachTheScreenTests` fails on a double-escaped sequence
  in any file that renders text. And **if a patch script keeps mangling
  backslashes, stop using the shell heredoc** and write the file with the
  editing tools instead - that is what finally worked both times.

- **A Node probe must be told its encoding, or it passes in CI and fails on his
  machine.** `subprocess.run(..., text=True)` decodes the child's stdout with
  the *locale* encoding, which is cp1252 on Windows and UTF-8 in GitHub
  Actions. A probe that renders a label containing an arrow therefore comes
  back mangled locally and intact in CI - the exact inversion of the usual
  failure, and the one that wastes the most time, because the machine reporting
  the fault is the one nobody trusts. Pass `encoding="utf-8"` to every
  `subprocess.run` that reads node's output.


- **A wall template updates every type it carries, including the ones Ekahau
  ships - and three of those are recoloured on purpose.** `Elevator Shaft`
  green, `Door, Steel Fire/Exit` orange, `Window, Thick` `#0093EA`, because
  Ekahau's greys for those three are hard to tell apart on a plan.

  **This was got wrong once, expensively, so do not re-derive it.** v2.100.5
  read "I just want to add in the walls that we added, not change anything from
  the defaults" as meaning the template must never deviate from Ekahau, removed
  those three colours and added a guard to `mergeTemplateTypes` that skipped
  stock types. Both were wrong: the Quick Walls guide had documented the
  recolour as a feature for as long as it existed, and he asked for them back -
  "get them back to where they were for my template."

  The colours were recovered from `wallTypes.json` inside his own most recent
  project, which is the backup for this: Quick Walls writes his types into
  every project he applies them to. Only the newest of three September projects
  carried them; the two older ones had Ekahau's greys, so **take the most
  recent rather than assuming agreement**.

  The guard had to go with them. Every Ekahau project already contains those
  three types, so a skip-stock-types rule means his colours never land on
  anything - a restoration that changes a file and nothing anyone can see. The
  `kept` / `keptPhrase` reporting is still in `walls.js` if the guard is ever
  wanted back.

- **The AP notes pages print last, and it is a decision.** The section is
  unbounded - a survey that photographs every AP would be a page per access
  point - so nothing anyone looks up by position may sit behind it. Every
  renderer in `report.js` concatenates `apNotesPages(...)` **in its return
  expression**, never into an earlier block. That form is enforced by
  `tests/test_ap_notes_last.py`, and the reason it is enforced rather than
  written down: the AP Placement Map did `sections += apNotesPages(...)` two
  dozen lines before its return and then appended the compass page after the
  lot, so the return expression did not mention the notes at all and there was
  nothing for a reader to notice. Found by printing it, not by reading it.

- **Per-page paper orientation works in Firefox too. It is measured now, and
  the invariant still matters more than the feature.** Mixed orientation in one
  document is done with named `@page` rules (`@page placementLandscape { size:
  Letter landscape }`) in `web/assets/wd-tools.css`.

  **Settled 2026-09-12: Firefox 155 honours named `@page` sizes at print time.**
  A two-page probe - one div on a named portrait page, one on a named landscape
  page - came out 612x792 then 792x612 from a single document, printed through
  geckodriver's WebDriver Print Page command. Chromium and Edge were already
  measured and are correct. So mixed orientation is supported in all three, and
  "make everything portrait" is a workaround nobody needs any more.

  **The history, because this claim has been wrong in both directions.** It was
  first asserted that Firefox does not implement named pages at all; that was
  never measured and was withdrawn in 49e30fb. The detection shipped alongside
  it was wrong on its own terms too - `CSS.supports('page','auto')` returns true
  in Firefox as well as Chromium, so the warning could never have fired in the
  browser it existed for. The lesson held through both rounds: print behaviour
  is a measurement, not a recollection, and the engine has to be named.

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

- **A note's photo does not live in `pictureNotes.json`, and AP notes are one
  object type rather than two.** This was written down wrongly once and the
  wrong version cost a round of design work, so: observed in a real project
  Ekahau itself wrote (its own `Office-Onsite-Example` with a text note and a
  picture note added through the Ekahau UI), `pictureNotes.json` was **absent
  from the archive entirely**.

  What is actually there is `notes.json`, whose entries are
  `{id, text, imageIds[], history?}`. A picture note is one of those with
  `imageIds` populated - and usually `text: ""`, because a note taken for its
  photo often has nothing typed on it. So there is no separate picture-note
  object to look for: there is a note, and it may have images.

  Access points reference notes by `noteIds`, which is an array, and **one AP
  can carry several** - in that sample `Cisco: Entrance` holds a text note and
  a picture note. Resolve every id, not the first.

  Two consequences for anything that reads them. A note with no text but an
  image is still a note; dropping it because `text` is empty loses exactly the
  one an installer took a photo for, which is why `notesForAp()` in
  `web/assets/js/report.js` skips an entry only when text *and* images are both
  empty. And `pictureNotes.json` is some other feature - it carries
  `location.coord`, so most likely standalone pins on the plan - and is not the
  place to look for what is attached to an AP.

  The Report's AP notes page renders the text and marks the attachment rather
  than printing the image. That is deliberate and there is no image layout path
  to fall back on: see the option's own description in `report.js`.

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

## The dev toolbar — WaxFrame Professional's method, ported

**The toolbar is permanent. Do not remove it.** *"I always like to keep a dev
toolbar on all of my projects, hence me making you copy it to this one from
WaxFrame Professional."* It is standing furniture in his products, not
scaffolding put up for one job, and it was asked for on its own terms.

That matters because of how it arrived here: the first thing it hosted was a
one-off repair, and he has said the repair itself is disposable - *"once it's
done then we're going to pull all this code out because it's only a one shot
deal"*. **That applies to the realign action, not to the toolbar.** A future
session reading the history could easily reach the opposite conclusion, which
is the whole reason this paragraph is at the top of the section.

What is disposable, and what is not:

* **`tools/cloud_realign.py`, its endpoint, its button and its tests** - the
  one-off. The ninety-project event came from a single bulk cloud rename. Once
  he has run it, it can come out in one commit. See "The first action" below
  for what is safe to delete with it.
* **The toolbar itself** - permanent.
* **`tools/housekeeping.py`** - also not a one-off. Session debris accumulates
  continuously; that action is what recovered 12.73 GB and found twenty-seven
  files of his workplace data sitting in `%TEMP%`.

**The underlying condition the realign action fixes is not a one-off either**,
even though the bulk event was. Renaming any cloud project without pulling
leaves that pair reading "cloud newer", because Ekahau stamps `modifiedAt` on a
rename and the local copy does not move. One or two at a time is already
handled by `fixInternalName` in `cloud.js`, which has named the difference and
offered to correct it since v2.112.0. The bulk tool exists because ninety at
once is not a per-row job.

**This is WaxFrame's dev toolbar, not an interpretation of it.** The first
build reshaped it into a vertical panel of named actions and dropped the
password gate. Both were reasoned and both were wrong to decide here, and he
said so plainly: *"That is NOT what I asked for. I asked for the method that we
used in WaxFrame Pro to be used in this project."* He has two products and
wants them to work the same way; consistency across them beats either
individual layout choice.

**It is written to be copied again**, since he keeps one in every project, and
the split is the same shape the updater uses - see "Porting the updater to the
other apps".

* **`wd-dev.js` is the portable half.** The only app-specific things in it are
  `LS_DEV` / `LS_POS` (`wd_dev`, `wd_dev_toolbar_pos`) and `DEV_PW_HASH` -
  and the hash is the one thing that should *not* change, since he wants one
  dev password across products.
* **`wd-dev-actions.js` is entirely this app's**, 37 references to its
  endpoints. That is the file a new project replaces wholesale.
* **What it needs from the host**, checked rather than assumed: `WD.toast` and
  `WD.toggleMenu`. It also renders into the suite's `.modal` / `.btn` /
  `.progress-track` classes, so a new project supplies those or the
  `.dev-*` block in `wd-tools.css` comes across with it.

**The rule that follows from that:** where something in WaxFrame genuinely
cannot carry over, raise it rather than substituting an answer. "WaxFrame does
X, it cannot work here because Y, so I propose Z" is the shape. Silently
improving on an established pattern of his is the failure.

    web/assets/js/wd-dev.js          gate, dispatcher, drag, mount
    web/assets/js/wd-dev-actions.js  every button's markup and handler
    wd-tools.css                     `.dev-toolbar`, `.dev-flyout`, at the end

### The method, part by part

* **Gate** — `localStorage['wd_dev'] === '1'`, set by a SHA-256 password
  modal. WaxFrame: `waxframe_dev`, `DEV_PW_HASH`, `submitDevPassword`. A wrong
  password **closes the modal and says nothing** - telling a guesser they were
  close is worse than silence.
* **Entry point** — a nav item under an **Advanced** heading opens the modal,
  and a second item, hidden until dev mode is on, leaves it. WaxFrame:
  `#navDevSection`, `.active` to reveal.
* **Layout** — one horizontal strip: a `⚙ DEV` label that is also the drag
  handle, buttons carrying an emoji, a short label and a `title`, `|`
  separators grouping them, and a hover flyout for a cluster. WaxFrame does the
  flyout with its five Scenes buttons; the Cloud pair uses it here.
* **Registration** — declarative, in markup:
  `data-action="call" data-fn="WD.Dev.housekeepLook"`, run by one delegated
  click listener that walks up to the nearest `[data-action]`. The name is
  resolved by walking a dotted path over `window` and binding the result -
  **a lookup, not `eval`**, so it stays safe under a strict CSP. WaxFrame:
  `callAction` / `resolveDotted` in `helper-handlers.js`. `data-arg`,
  `data-arg-this`, `data-arg-event`, `data-stop`, `data-prevent` and
  `call-chain` all carry over.
* **Drag** — by the label, position in `localStorage['wd_dev_toolbar_pos']`,
  restored on load and cleared on exit. WaxFrame: `attachDevToolbarDrag`.
* **Detail goes in a modal**, not in the strip. WaxFrame shows a
  Troubleshooting Card; this shows `#devResultModal`. Either way the strip
  stays a strip.

### Injecting into nineteen pages means finding nineteen menus

**The entry went into `#mainMenu`, and only three pages call it that.** Cloud
Manager, Squirrel and Rename use that id; Home is `homeMenu`, Scale is
`scaleMenu`, each guide has its own, and the drop-zone tools carry **two**
menus apiece - `dzMenu` before a file is loaded and `helpMenu` after. So on
sixteen of nineteen pages the Dev Tools entry silently never appeared, and he
reported it the only way it looks from outside: *"I see no link in nav
hamburger menu."*

The fix is to target the **classes**, which is what `WD.toggleMenu` already
does: `.main-menu, .help-menu, .wd-menu`. Every menu on the page gets an
entry, the row class matches the menu it lands in (`help-menu-item` in a
`help-menu`, `menu-item` elsewhere), and the exit wrapper is a **class** not
an id, because a page with two menus would otherwise have two elements sharing
`#navDevSection` and only the first would ever be found.

**The testing lesson is the bigger one.** `test_dev_toolbar_browser.py` drives
`cloud.html` and nothing else, and `cloud.html` is one of the three pages that
happened to work. One page tested, nineteen shipped.
`tests/test_dev_nav_on_every_page.py` now walks every page that loads
`wd-dev.js`, reading that list off disk rather than from a hand-written array,
and checks the entry is present, in every menu, visible with dev mode off, and
that clicking it opens the modal. Reverting the injection to the single id
fails it on sixteen pages by name.

Two things that page needs to know, both found by driving it:

* **Some pages hide their whole app screen until the tool is in use.** Cloud
  Manager's `#appScreen` is `display: none` until it has a session, so on the
  login screen the topbar and its hamburger are not on the page at all. A
  visibility check has to reveal that first, or it is asserting about a menu he
  cannot see yet either.
* **The entry must be visible while dev mode is OFF**, because it is the way
  *in*. Only the exit item is hidden until dev mode is on. Getting those two
  backwards leaves `?dev=1` as the only route, which looks exactly like the bug
  above.

**`setup.html` has no hamburger at all** and that is fine - it is the first-run
screen. `?dev=1` works there, and the test records the absence as intended
rather than leaving it to look like a gap.

### The one thing that could not carry over

**WaxFrame is one page; this suite is nineteen.** WaxFrame writes the toolbar,
the modal and the nav entries straight into `index.html`. Copying that here
would mean the same block in nineteen files, drifting the moment one is edited,
and there is no server-side include to share it. So the *identical markup* is
injected once from `wd-dev.js` - same elements, same classes, same data
attributes, same dispatcher. Only where the string lives differs.

The dispatcher is also **scoped to `#wdDevRoot`**. The rest of this suite wires
its controls with inline `onclick`, and a document-wide `[data-action]` walk
would eventually pick up a click meant for a tool. Converting the whole app to
the WaxFrame dispatcher is a separate job with its own risk.

### What is his rather than WaxFrame's, and is kept

* `--pink` and `--lime` instead of WaxFrame's amber. No tool in this suite uses
  pink for its chrome, so the strip cannot be mistaken for part of one, and
  lime marks the half of each pair that writes nothing.
* **`?dev=1`, and deliberately no key chord.** He was explicit about never
  landing in dev mode by accident. Both routes in are deliberate; the password
  modal is WaxFrame's and the query parameter is his.
* **The two-stage dry run**, expressed in WaxFrame's idiom: the live button is
  rendered `disabled` and only its own preview turns it on. A failed preview
  leaves it dead and a completed run disarms it. That is what stands between a
  mis-click and ninety rewritten project files.

**The dev password is the same one WaxFrame Professional uses**, and only
the hash lives here: *"The password should use the same hash I currently use
on WaxFrame Pro."* An earlier build generated its own, reasoning that a
password should not be shared between two products. He overruled that - it is
his password and his two products, and he would rather remember one.

**The plaintext is in neither repository**, and `tests/test_dev_password_hash.py`
holds that: it checks the constant here matches WaxFrame's `DEV_PW_HASH` by
reading both files (skipped where WaxFrame is not installed), and scans the
gate, its tests and this file for anything shaped like a password being written
down - naming the file and line, never the value.

Both repositories are public, so the hash now appears in two public places.
That is no more exposed than it already was, but one recovered password opens
both products rather than one. The gate is obfuscation, not security: it keeps
a curious user out of a maintenance surface on a localhost-bound server, and
anyone with a console can set the flag directly.

**Testing the gate without the secret.** `WD.Dev._hash` and
`WD.Dev._expectedHash` are exposed so a test can hash a string it invented,
point the gate at that digest, and drive the real submit path - the input is
read, hashed with the real SHA-256, compared, and on a match the flag is
written and the toolbar mounts. Neither seam weakens anything: the constant is
readable in the file and the flag is settable from any console.

### The labels have to say what the button does

He opened the first WaxFrame-method build and said: *"there are items in here
and I don't know what they do."* The buttons were emoji plus a short phrase
with the explanation in a `title`, which is hover-to-reveal - and his standing
rules are that every control carries a text label and that nothing a decision
rests on hides behind a hover.

So the strip carries readable names, **nothing in the strip writes to
anything**, and each button opens a panel - WaxFrame's modal, where WaxFrame
already puts detail. The panel states in plain words what the action looks at,
what it changes, what it backs up, what it will not do, and that the preview
changes nothing; the controls sit underneath that. The hover flyout went with
it, being the thing the rule rules out.

Read-only versus writing stays visible in colour as well as words: the preview
control is lime and says it changes nothing, the live one is pink and stays
`disabled` until its own preview comes back clean. The live button **names the
count** once it arms - "Align 87 projects for real" rather than "Align them for
real", because that is the moment the number matters.

**The preview report is the screen he decides on**, at around ninety pairs, so
it gets the room: a wider modal, full names never truncated, and the skipped
ones grouped by reason with a count per group rather than ninety flat rows.

### The client is not the guard, so stop making him pay for it

He ran the clean-up, got a result, and reported: *"there was no way to make it
run for real and then when I went back it needed for me to do it again to do a
preview and run for real was grayed out. This is counterproductive."* Two
separate faults, and both were self-inflicted friction rather than safety.

**The control was armed; it was just off screen.** The panel's buttons sat
inside the scrolling body, above the output. A housekeeping report on his
machine is **six screens tall**, so the moment he scrolled down to read it the
armed "Delete 4,084 items" button was above the fold with nothing to indicate
it existed. The controls live in the modal's own footer now, outside the
scroll. **A control he has to scroll back up to find is a control he does not
have.**

**Closing the panel threw the result away.** Reopening reset the pending list
and disarmed the live button, so he had to re-run the whole thing. That
mattered most for realign, which downloads ninety cloud projects to prove them
identical before it will offer to write.

Keeping the result is safe, and this is the load-bearing part: **the button
state is not the safety mechanism.** `housekeeping.sweep` looks every path up
in a fresh survey and skips anything no longer deletable;
`cloud_realign.realign` re-downloads and re-compares each pair before touching
it. Both re-derive their work at write time. The armed button is a
convenience; the server is the guard. Disarming on close bought nothing and
cost him the run.

A remembered result says so - when it was taken, and that the server re-checks
anyway - because showing a stale answer as though it were fresh would be worse
than clearing it. A *spent* delete list is still cleared after a sweep: keeping
a preview is the fix, keeping a list that has already been acted on is not.

`test_the_controls_stay_on_screen_however_long_the_report_is` and
`test_reopening_the_panel_keeps_the_result_and_stays_armed` hold both, and both
go red on the old behaviour.

### Knowing it is running, and knowing it is done

*"How will I know after the alignment is complete?"* Fair question, and the
answer was "you won't, until it finishes".

**The server was already reporting progress and nothing was listening.**
`cloud_realign.realign` calls its `progress_cb` once per pair - "Checking 34 of
90" - and `server.py` exposes that at `/api/cloud/progress`, keyed by an
`opId`. The toolbar sent no `opId`, so ninety cloud downloads happened behind a
button reading "Aligning..." and nothing else. On a fleet that size that is
minutes of a screen indistinguishable from a hung one.

It sends one now and polls every 250 ms, same shape Cloud Manager's ops deck
uses, into the suite's existing `.progress-track` / `.progress-fill`. The
poller stops when the call returns, or it would keep overwriting the report he
is trying to read.

**The finished state says so in words.** A report appearing where a progress
bar was is a weak signal, so a live run leads with a lime banner - "Finished.
71 projects are now in step with the cloud - those rows will stop reporting the
cloud as newer. Nothing was uploaded, and nothing was deleted from the cloud."
- and the panel retitles itself to "Realign - finished". A preview never says
"Finished"; the two states must not read alike.

One wording trap worth keeping in mind: `plural(n, 'one', 'some')` produced
**"3 some failed"**, which read fine in the source and not on screen. It was
caught by photographing the finished state rather than by any assertion, and
`test_a_finished_run_reads_as_a_sentence` exists because that class of mistake
survives a read-through.

**Adding an action:** one button in `Dev.toolbarInnerHtml` and one handler
below it in `wd-dev-actions.js`. WaxFrame's convention is that every
dev-toolbar button's handler lives in one file - `wf-debug.js` - so nothing in
that file is dead and no button calls something that is gone.

**Testing it.** `tests/test_dev_toolbar_browser.py` drives the real toolbar in
Firefox, Chrome and Edge over a plain `http.server` on `web/` - never
`server.py`, which opens a browser window nobody closes. It works the password
gate, the dispatcher, the flyout, the drag and both actions, and stubs `WD.api`
because that is the seam the handlers use. **Selenium Manager drops
`geckodriver/` and `se-metadata.json` into the working directory** on first
use; both are gitignored, and a 4 MB binary is one `git add -A` from the
repository if those entries ever go.

### The first action, and the trap in it

**This one is disposable - see the top of this section.** When he has run it
against his fleet and is satisfied, it comes out: `tools/cloud_realign.py`,
`CLOUD_ACTIONS["realign_renamed"]` in `server.py`, the `wdRealignOpenBtn`
button and the `Dev.openRealign` / `realignPreview` / `realignRun` /
`realignReport` block in `wd-dev-actions.js`, `tests/test_cloud_realign.py`,
`tests/test_dev_toolbar_report.py`, and the realign tests inside
`tests/test_dev_toolbar_browser.py`. Nothing else depends on it.

Two things to keep on the way out. `_rewrite_project_json` in
`cloud_manager.py` was extracted for this, but `set_internal_project_name` is
its other caller - **it stays**. And the progress polling in
`wd-dev-actions.js` is generic; any future action that runs for minutes wants
it.

Three more files mention it and none of them depend on it - the references are
prose in comments: `tools/housekeeping.py` twice ("same rule as the realign
action", about re-deriving before writing) and one slice-marker comment in
`tests/test_housekeeping_report.py`. Reword them; nothing breaks either way.
The slice markers themselves (`function mb(bytes)` to `Dev.housekeepLook`)
survive the removal untouched.

`tools/cloud_realign.py` settles the pairs that read "cloud newer" only
because the cloud project was renamed. Roughly ninety of them, from a rename
we did. It proves each pair identical with `esx_compare.compare_esx` -
**not** with `build_matches`'s rename heuristic, whose own docstring says it
does not prove content - then corrects the name inside the .esx and the date,
backing up each file it rewrites.

**The trap: `os.utime` is not enough and looks like it is.**
`get_local_esx_files` reports a local file's `mtime` as
`internalMtime or fs_mtime` - the `history.modifiedAt` written inside
`project.json` - because a filesystem date resets on copy or sync and the
internal one does not. So setting only the disk timestamp leaves every row
still saying "cloud newer" while every filesystem assertion passes. Both are
set. `test_the_date_the_tool_compares_is_the_one_that_moves` asserts on what
`get_local_esx_files` returns, which is the number the row is built from, and
that test fails on the `os.utime`-only version.

`_rewrite_project_json` in `cloud_manager.py` is the shared back-up, rebuild,
replace-atomically, prune path, extracted from `set_internal_project_name`
when this became its second caller. It writes nothing when the mutation
changes nothing, which is what makes both callers safe to re-run.
### The second action

`tools/housekeeping.py` answers "is there junk everywhere", and the rule it is
built on is in the section below: artifacts go in one place. Three things about
it are worth knowing before changing it.

**It flags on what is inside an `.esx`, not on the extension.** The first
version counted every `.esx` in a temp folder as his data and lit up 2,226
entries - all of them fixtures the suite had written. The second counted every
archive it could not open and lit up 683 - stub files the suite writes to
exercise error paths. It now reads `project.json` and runs the detector over
the name and author, with a size floor so a genuinely truncated project still
gets listed. **A flag that fires on everything is one he learns to scroll
past**, and this is the category he actually cares about.

**Bound every quantifier in a scanning regex.** The obvious email pattern
backtracks quadratically on long runs of its own character class with no `@` -
which is what a log file is. One 393 KB file took **163 seconds**, and the
first real survey never finished. The bounded form is 0.005 s on the same
input. `tests/test_no_real_world_data.py` carries the same unbounded pattern
and has not been bitten because it only reads small tracked files; if it ever
starts reading logs, bound it there too.

**The registration lookup must name its repository.** `git worktree list` run
outside a repository exits non-zero and returns nothing, so every worktree
looked abandoned - including live ones. The server is started from wherever the
launcher is, so the default `cwd` was wrong. **The failure direction is toward
deleting more**, which is why it has its own test. Found by driving the real
action against the real machine, not by any unit test, which is the argument
for doing that once per feature.


## Every session gets its own worktree

**Do not work directly in the shared checkout.** Several sessions run against
this repository at once, and until 2026-09-17 they all shared one working tree,
one index and one HEAD. Every incident of that day traces back to that single
fact:

- a session went to stage its own CSS and found `HEAD` already contained it,
  because another session had committed the file out from under it
- a documentation-only commit run with no pathspec swallowed another session's
  fully staged work - fifteen files and a version bump - and published it under
  a message saying no version bump was needed
- `v2.103.14` landed on somebody else's commit, because `main` moved between
  the push and a bare `git tag`
- `v2.102.0` shipped dead, because a module was present in the shared tree and
  untracked, so the local suite passed and CI did not
- uncommitted routing edits sitting in the shared tree failed CI for a session
  that had not touched them
- a session left a landmine where a plain `git add` would have reverted three
  version numbers
- and the clean-slate operation itself opened with `tools/cloud_manager.py`
  holding another session's stale work-in-progress, six lines of committed code
  behind the tree it was sitting in

Each of those has a rule written against it elsewhere in this file - name the
SHA, name the paths, content-based staging. Those rules exist because the tree
is shared. Stop sharing the tree and most of them stop being load-bearing.

### Where they live

    C:\wd-worktrees\<session-name>\

**Outside Dropbox, deliberately.** This repository lives inside a Dropbox
folder and a worktree is a full second copy of the tree, so a worktree kept
under the repo gets uploaded and re-downloaded in its entirety, and Dropbox
takes file locks on files git is in the middle of writing.

An earlier draft of this note kept them at `.claude/worktrees/` and suppressed
the sync with an NTFS alternate data stream (`com.dropbox.ignored`). That
works, and it is the wrong shape: it defends against a problem rather than not
having it, and it stays correct only while one invisible attribute survives
every fresh clone, restore and copy. `C:\wd-worktrees` is not Dropbox's
business in the first place. If you find a worktree under `.claude/worktrees/`,
it predates this note - move it.

The directory is created on demand; nothing needs to exist first.

### How to create one

```powershell
git fetch origin
git worktree add -b claude/<session-name> C:\wd-worktrees\<session-name> origin/main
```

Branch off `origin/main`, not off the shared checkout's `HEAD` - the shared
checkout may be mid-edit, and that is the whole problem being avoided. Then
work in there: it has its own index, its own HEAD and its own working files, so
`git add`, `git commit` and `git stash` all become ordinary again.

Two things are still shared and are worth knowing. The **object store** is
shared, which is why this is cheap rather than a second clone. And the **stash
stack** is shared, so a bare `git stash pop` in a worktree can still take
somebody else's entry - prefer a throwaway WIP commit, or `git stash push -m
"<unique tag>"` and `git stash apply <sha>` by id.

### How work merges back

`main` is still the only branch anybody publishes, and routine work still goes
straight to it - no PR. From inside the worktree:

```powershell
python -m unittest discover -s tests          # green first
git fetch origin
git rebase origin/main                        # not interactive, no editor
python -m unittest discover -s tests          # green again, after the rebase
git push origin HEAD:main
```

The second run is not ceremony. A rebase replays your commits onto code you
have not tested against, and that is exactly how a green branch turns into a
red `main`.

If the push is rejected because `main` moved, fetch and rebase again. Never
force-push `main`. It was force-pushed once, on 2026-09-17, for the history
rewrite, with the repository owner's explicit say-so for that one operation.

Then wait for CI, and tag from the shared checkout as the release process
describes - naming the SHA, as always.

### The one thing a worktree does not protect you from

**Two sessions can pick the same version number, and git will not notice.**

On 2026-09-17 two worktrees bumped `versions.json` from 2.107.0 to 2.108.0
within minutes of each other, for different features. The second rebase applied
cleanly and reported nothing, because both sides had written the *same* bytes -
a conflict needs the two versions to differ. `main` ended up with two unrelated
commits both titled v2.108.0, and the suite version no longer distinguished
them. Nothing was lost and CI stayed green, which is what makes it easy to miss.

A worktree isolates your files. It does not reserve a version number. So before
you bump:

```powershell
git fetch origin
git show origin/main:web/assets/versions.json
```

and bump from *that*, not from what your worktree had when you created it. If
somebody has taken the number you were going to use, take the next one - and if
you only notice after pushing, bump again in a follow-up commit rather than
leaving two changes wearing one number, because the release workflow matches a
tag to exactly one `versions.json`.

### Remove it when you are finished

A worktree left behind is a stale branch, a second copy of the tree, and a
place rule zero material sits unnoticed. From the shared checkout:

```powershell
git worktree remove C:\wd-worktrees\<session-name>
git branch -d claude/<session-name>
git worktree prune -v
```

`git worktree remove` refuses if the tree has uncommitted changes, which is the
correct behaviour - look at what is in there before reaching for `--force`.

**If a teardown ever fails on a perfectly clean worktree**, with:

    error: failed to delete '...': Permission denied

that is not a lock on the contents. Git deletes every file successfully and
then cannot remove the now-empty directory, because something outside git is
holding a handle on it. The registration *is* cleared - `git worktree list`
stops showing it - so the state is half-done while looking finished. Finish it:

```powershell
Remove-Item C:\wd-worktrees\<session-name> -Recurse -Force
git worktree prune -v
```

**Measured on 2026-09-17, and it is the argument for the location.** A worktree
under the repo inside Dropbox failed teardown exactly this way. Three
create-and-remove cycles at `C:\wd-worktrees` - 380 files each - all exited 0
with the directory gone. So the handle was Dropbox's, and moving out of Dropbox
did not merely avoid the sync traffic, it removed the failure. Keep the
`Remove-Item` line anyway: a virus scanner or an open editor can hold a handle
just as well.

**And most often it is your own session holding it.** On 2026-09-18 a teardown
failed this way outside Dropbox entirely, with `Remove-Item -Force` *also*
failing on a directory that was already empty. The holder was a `python.exe`
this session had started itself, hours earlier, as a long-running background
command that never returned - its working directory was inside the worktree,
so an empty folder could not be removed while it lived.

Nothing about that is visible from git, from the error, or from listing the
folder. What finds it is asking which processes are running out of the path:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -like "*<worktree-name>*" } |
  Select-Object ProcessId, Name, CommandLine
```

Stop the ones that are yours - check the command line rather than the name,
for the same reason as `firefox.exe` - and the removal then succeeds. **A
backgrounded command that has not returned is still a live process**, so kill
it before teardown rather than discovering it as a permission error. The dev
toolbar's housekeeping action lists exactly these, which is the other half of
why it exists.

### Prune does not clean up after an abandoned session

**`git worktree prune` cannot see the failure mode that actually happens.**
An earlier version of this note said to prune at the start of every session and
left it there. That instruction is not wrong, it is inert: prune only clears
registrations whose *directory has gone missing*. A session that dies mid-task
leaves the directory sitting there intact, so prune looks straight past it,
exits 0 and prints nothing.

Measured on 2026-09-18, on a worktree created and then abandoned without
teardown:

    git worktree prune -v     # exit 0, no output
    git worktree list         # still lists it
    Test-Path <dir>           # still True

So a green prune at session start is not evidence that `C:\wd-worktrees` is
clean. On 2026-09-18 that folder held six entries: three live, and three that
several sessions had each reported removing on completion. Nothing had errored.
The teardown step simply never ran, and prune could not tell anyone.

**Reconcile the directory against git instead.** At the start of a session, and
again when you finish:

```powershell
git fetch origin
git worktree prune -v
foreach ($d in Get-ChildItem C:\wd-worktrees -Directory) {
    $reg  = (git worktree list) -match [regex]::Escape($d.Name)
    $age  = (New-TimeSpan -Start $d.LastWriteTime).TotalHours
    "{0,-22} registered={1,-5} idleHours={2:N1}" -f $d.Name, [bool]$reg, $age
}
```

Anything idle for hours is a candidate. Anything **not registered** is not a
worktree at all and no git command will ever clean it - see below. Do not
delete another session's work on a timer: confirm it is finished before
removing it, then tear it down properly. `git branch -d` (not `-D`) is the
check that matters - it refuses unless the branch is merged, so a clean
`-d` is your evidence the work shipped.

### `C:\wd-worktrees` holds worktrees and nothing else

Two of the six entries found on 2026-09-18 - `manual-review` and
`ux-sweep-work` - were **not worktrees**. They were ordinary folders a session
had created next to the real ones to hold screenshots, audit scripts, browser
profiles and a draft commit message. `git worktree list` never showed them,
`git worktree remove` did not apply, and prune had nothing to prune. They were
invisible to every step of this convention while sitting in the middle of it.

Session scratch goes in your scratchpad or inside your own worktree, where it
leaves with the worktree. If you put a loose folder or a stray `.txt` in
`C:\wd-worktrees`, nothing in this file will ever clean it up and it becomes
David's problem on his own C: drive - and see the rule below, which covers
every other place this has gone wrong.

**Report what you found and removed rather than cleaning quietly** - rule zero
material has sat in exactly these forgotten corners before.

## Session artifacts go in one place, and nowhere else

**One root per session, and that root is your scratchpad.** Screenshots,
scratch scripts, probe output, downloaded ZIPs, audit results, draft commit
messages - all of it, under the scratchpad directory the session is given, or
inside your own worktree where it leaves with the worktree. Nothing else is a
legal destination.

**Not his Desktop.** That is the example to name, because it is the one he can
see: `cloud-flat-1920.png`, `cloud-flat-before.png`, `cloud-heldback-1366x900.png`
and six more sat on his Desktop on 2026-09-18, written there by sessions taking
UI screenshots. Nobody was going to clean those up, he did not put them there,
and they are the first thing he looks at every morning.

Not `~/Downloads`. Not the repository root. Not a sibling folder next to your
worktree. Not a hand-rolled directory in `%TEMP%` - use the scratchpad, which is
already per-session and already isolated.

### Why this is a rule and not a preference

A disk sweep on 2026-09-17 recovered **12.73 GB** of session debris: roughly
7,900 leaked temp directories and 7,000 abandoned repository clones. **Twenty
seven files carrying real workplace data** were sitting in `%TEMP%` - rule zero
material, in a forgotten corner, exactly where it has been found before. Four
worktrees outlived the sessions that reported removing them, and 21 orphaned
Firefox processes were found in one sweep.

He asked the question that produced this rule: *"how do I know, once we've done
all the work, when to be able to clean stuff up? Because now I feel like we've
got files fucking everywhere across the board, and I don't know if you clean up
your own work or not."* The honest answer was that we did not.

Scattering is what made that unanswerable. Debris in one known root can be
listed, counted and cleared; debris across `%TEMP%`, the Desktop, Downloads and
the repo cannot be, and nothing can ever tell him whether the machine is clean.

### The suite cleans up after itself, and a test holds it

**The biggest single leaker was this test suite**, which is worth knowing
because it was not carelessness - it was two defensible decisions:

* `tests/test_cloud_pull.py` had a `setUp` with `mkdtemp` and no `tearDown`.
  One directory per test method: **1,314** of them.
* `tests/__init__.py` created one per run and left it deliberately, so the
  evidence survived a failure, reasoning that "the OS clears the temp tree
  anyway". **It does not on Windows.** 143 of them.

Both are fixed, and `WD_KEEP_TEST_USER_DIR=1` keeps the evidence when you
actually want it. Measured either side of the fix: **116 directories leaked per
suite run before, 1 after** - and that one is Chrome's, not ours.

`TheSuiteCleansUpAfterItself` in `tests/test_housekeeping.py` is the ratchet. It
walks the AST for `mkdtemp` **calls** and fails if the enclosing function has no
cleanup in it. Calls, not the substring - matching text made the checker fail on
its own source, and a checker that has to exempt itself has a hole in it.

### And there is now a button for the rest

`tools/housekeeping.py`, reachable from the dev toolbar, inventories what our
tooling leaves behind and says what is safe to remove. It is what turns "I
wonder if there is junk everywhere" into a five-second answer. Read its module
docstring before changing it - particularly the part about why it flags on what
is *inside* an `.esx` rather than on the extension, which is the difference
between a useful list and 2,226 false alarms.

It only ever deletes inside roots we own, never from the Desktop, and it
re-derives the list at delete time instead of trusting what the page sends.


## Memory across sessions, generally

Claude Code cloud sessions have no memory of past conversations by default
— only what's readable in the repo at session start (this file, code,
`BACKLOG.md`). If something matters for next time, write it here rather
than assuming it'll be remembered.

**Reconcile `C:\wd-worktrees` at the start of every session too**, for the same
reason — see "Every session gets its own worktree" above. Note that `git
worktree prune` on its own will not tell you the folder is dirty: it only
clears registrations whose directory is already gone, so an abandoned worktree
and a loose scratch folder both survive it silently. Compare the directory
listing against `git worktree list`, not prune's exit code.
