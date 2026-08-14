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
5. **Tag pushes are blocked from Claude Code cloud sessions** — confirmed
   this is NOT a GitHub permissions problem (the installed GitHub App
   already has full read/write on code/contents; no branch or tag
   protection rules exist on this repo). It's a boundary on Claude's side:
   cloud sessions can push branches/commits but not create tags. So:
   give the user this exact snippet to run from their own machine — it's
   the one step that can't be automated from here:

   ```powershell
   cd "<repo folder>"
   git pull origin main
   git tag -a vX.Y.Z origin/main -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

   The release workflow (`.github/workflows/release.yml`) validates that
   the tag exactly matches `versions.json`'s `"suite"` value
   (`scripts/build_release.py` raises if they don't match) — so the
   version bump commit MUST land before the tag is pushed.
6. No hand-written release notes file needed — `release.yml` uses
   `generate_release_notes: true` (GitHub auto-generates from commits).
   The old `docs/releases/vX.Y.Z.md`-per-tag convention was removed when
   this repo did a clean history reset at v2.0.0.

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
