# CLAUDE.md — persistent notes for this repo

Read this at the start of every session. It exists so facts don't have to be
re-discovered (or re-explained) each new chat.

## Release process — do this every time you commit to `main`

1. Bump `web/assets/versions.json` — this is the single source of truth for
   every tool's version + the suite version. Every page's displayed version
   (`data-ver` attributes, read by `WD.applyVersions()` in
   `web/assets/js/wd-shared.js`) comes from this file automatically.
2. **Also manually update these two places** — they quote versions in prose
   and are NOT auto-synced from versions.json:
   - `README.md` — the `WIRELESS TOOLS  vX.X.X` example banner, and the
     Cloud Manager version badge in the tool table near the top.
   - `web/pages/hosted-cloud-stub.html` — the `<div class="stub-ver">`
     line.
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

## Known gotchas

- **Owner filter (Mine/Others/All)** in Cloud Manager used to persist to
  `localStorage` across page loads/sessions, which meant it could get
  silently stuck on "Mine" or "Others" on one machine while defaulting
  correctly on another — this once looked like a data bug ("only 3 sites
  show up") when it was actually a stale filter. Fixed: `ownerFilter()` in
  `web/assets/js/cloud.js` is now in-memory only (`_ownerFilterState`),
  always starts at `'all'` on a fresh load. Don't reintroduce persistence
  here without a very visible indicator of the active filter.
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
