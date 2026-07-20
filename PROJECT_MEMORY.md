# WD Wireless Tools — Project Memory / Handoff

_Read this first when picking up the project in a new chat. See also **`BACKLOG.md`** (prioritized to-do list) in this same folder._

## What this is
**WD Wireless Tools** — a local, browser-based suite of Ekahau WiFi-survey workflow tools that David (dpaine@anduril.com) built. It runs as a small Flask server on his Windows machine and opens in his browser. Distributed via the Ekahau Slack community. Two tools + a launcher home page.

- **Location:** `C:\WD Wireless Tools\`
- **Run:** `python server.py` (or `run.bat`) → serves on `http://127.0.0.1:8675/` and opens the browser.

## Architecture
- `server.py` — Flask server, port 8675. Routes: `/` (home.html), `/cloud` (cloud.html), `/walls` (walls.html), `/organizer` (organizer.html), `/assets/<fn>`, `POST /api/cloud/<action>` → `CloudManager`, `POST /api/organizer/<action>` → `FolderOrganizer`. Serves files fresh from disk each request. **Has an `@app.after_request` no-cache header** so the browser always gets the current file.
- `tools/cloud_manager.py` — Cloud Manager backend. `EkahauAPI` (undocumented cloud API via `browser_cookie3` session cookies), matching helpers, `CloudManager` class, folder scanning, merge logic, folder inventory.
- `tools/folder_organizer.py` — Folder Organizer backend. `FolderOrganizer` class: scan (dry-run preview), execute (apply moves), get/set/reset config for editable type mapping. Config stored in `~/.wd_wireless_tools/organizer_config.json`.
- `web/home.html` — launcher (three tool cards: Cloud Manager, Quick Walls, Folder Organizer). 3-column responsive grid.
- `web/cloud.html` — **WD Cloud Manager** (single-file HTML/CSS/JS, ~1600+ lines).
- `web/walls.html` — **WD Quick Walls** (single-file, large, has embedded user-guide HTML string near the end).
- `web/organizer.html` — **WD Folder Organizer** (single-file HTML/CSS/JS). Flow: pick folder → dry-run scan → review with per-file checkboxes → apply. Settings modal for editable type mapping.
- `web/assets/` — logos (`cloud_manager.png`, `quick_walls.png`, `wireless_tools.png`, `folder_organizer.svg`).
- `run.bat` (Windows) / `run.command` (macOS) — double-click launchers.
- Config in `~/.wd_wireless_tools/`. Auth = Ekahau browser session cookies (Chrome/Firefox/Edge; NOT Safari on Mac).

## Versions (I own the numbering — David delegated it)
- **WD Cloud Manager: v2.8** (stamped in header `<span class="ver">` and the About modal).
- **WD Quick Walls: v7.9** (stamped in header h1).
- **WD Folder Organizer: v1.1** (stamped in header `<span class="ver">` and the About modal).
- Bump **minor** for features, **patch** for fixes, ALWAYS stamp it. The version number doubles as a cache-check for David.

## WD brand palette (use these everywhere)
- Blue `#1e77ac`, Green `#5fab4f`, Slate `#5d5b60`. Cloud Manager also uses amber `#d97706` and red `#dc2626`.
- Cloud = blue, Local/synced = green, mismatch = orange/amber, **orphan = RED**, duplicate hint = amber.

## Cloud Manager (cloud.html) — current state
- Two tabs: **Sites** (folder-level) and **Project Files** (.esx-level). Tabs are file-folder-shaped, active tab filled with its brand color (blue Sites / green Project Files).
- **WinDiff-style aligned ledger** (`renderLedger`): LEFT = every cloud item, RIGHT = every local item, one aligned row per reconciliation unit; matched pairs side-by-side, orphans leave a blank gap on the other side with a ghost "+ create" button. Big center-gutter markers: `=` synced, `➡`/`⬅` for mismatch (clickable sync) and orphan (points at empty side).
- **Status "tabs"** = colored left-edge bars on each filled cell (green synced / orange mismatch / RED orphan), mirrored both columns. Amber bar on the RIGHT edge = code exists on other side ("possible duplicate").
- Dashboard filter cards: **All / Mismatches / Orphans / Synced** (mismatches lead, ordering mismatch→orphan→synced). Cards sit on a `--surface` panel (unified "single console" look). Filter persists across tabs.
- Actions per row (hover overlay, absolute-positioned so the `esx · size` meta stays right-aligned): eye 👁 (preview folder contents), flag ⚐ (adds `!` prefix, Sites folders), merge ⇉ (Sites), rename ✎, delete 🗑. Cloud side = rename+delete only.
- **Preview eye + peek modal** — lists a folder's contents grouped (Ekahau .esx / floor plans / images / other) with size + modified date/time. Amber eye = folder holds non-.esx "source files" (floor plans, installer images) that are NOT on Ekahau Cloud — never delete those blind (delete dialog warns).
- **Merge folder → folder** (`merge_preview`/`merge_execute`): pick destination (★ = same site code), bigger preview modal lists EVERY file with a checkbox to include/exclude (unticked = stays in source, shown struck-through), new/conflict badges + timestamps. Conflict rule: Keep newer / Keep both (date-stamps the OLDER file) / Skip. Default set in Settings (gear); "don't ask again" saves it. Never auto-deletes source; offers to delete emptied source after.
- **Compare** — select 2+ local folders → side-by-side columns of their contents; files appearing in >1 folder highlighted amber.
- **Shift-click** range selection on checkboxes (delegated handler `onRowChkClick`). Matched rows show a checkbox on BOTH sides (same key, kept in sync).
- **Live** toggle — auto-refresh from Ekahau Cloud every 30s (pauses while selecting/modal open/searching). Source of truth: cloud column = Ekahau Cloud (pull on refresh), local column = disk.
- **Hamburger menu** (top-left, matches Quick Walls): About / Settings / Change Local Folder / Refresh / links to Tools + Quick Walls (new tab). About modal.
- Cross-tool nav links open in **new tabs** (`target="_blank"`) so both tools can be open at once.
- Row/name text WRAPS (no ellipsis) — `.cell-name`, `.mfile-name`, `.pk-name`, `.cmp-title`, `.cmp-n` all use `overflow-wrap: anywhere` or nowrap+scroll. **Zero `text-overflow: ellipsis` remains in cloud.html.**
- Instant styled tooltips (JS) replace slow native `title` tooltips on row buttons.
- Styled instant tooltips, no-cache meta tags in `<head>`.
- **Live auto-refresh interval** configurable in Settings: 15s / 30s (default) / 60s. Stored in `localStorage('wd-live-ms')`.
- Merge modal titles and peek-row names use `overflow-wrap: anywhere` to wrap properly instead of clipping.
- WaxFrame-style hamburger menu with section headers and `·` prefixed sub-items, user guide link → `/guide-cloud`.
- **Toast messages**: centered on screen, theme background, blue border, theme text, 6s duration.
- **New Site modal**: dual-creation with Cloud + Local checkboxes (both checked by default). Creates on both sides in one action.
- **Known gap — no selection action bar**: checkboxes exist on rows, and `confirmDelete()` handles `deleteTarget.bulk`, but there's NO UI bar that appears when items are selected. David expects a bulk-action toolbar. Backlogged as P1.
- **Project Files upload** (v2.4): Red arrow on Project Files tab now active — uploads local .esx to Ekahau Cloud via 3-step presigned S3 flow (`/esxfileapi/v1/projects/upload/initiate` → S3 PUT → `/esxfileapi/v1/projects/upload/commit`). `EkahauAPI.upload_project()` handles the full flow.

## Quick Walls (walls.html) — current state
- Loads an `.esx`, remap wall types, assign keyboard shortcuts [1]-[9], save back.
- Wall types **sorted alphabetically** (in `renderList`).
- Wall-type color = **wide (14px) full-height left tab** on the card (not an inner swatch). Shortcut slots use the same left-tab style (`.hotkey-swatch`).
- Wall names show in **full (no ellipsis)**.
- Header buttons: **Apply Template**, **Save Template**, **Save .esx**. Save Template now saves to localStorage AND **downloads a `_walltemplate.json` file** (so the user knows where it went).
- Brand colors: `--accent` = WD blue `#1e77ac`, `--success` = WD green `#5fab4f`.
- Dropzone logo → `/assets/quick_walls.png`; removed the redundant text title (logo has the text). fileInput moved OUTSIDE the dropzone (fixed a click re-entrancy bug that broke "browse").
- WaxFrame-style hamburger menu with section headers (`▸ Navigation`, `▸ Tools`, `▸ Help & Support`), `·` prefixed sub-items, active page highlighted in accent color.
- **Toast messages**: centered on screen, theme background (`var(--surface)`), blue border (`var(--accent)`), theme text color, 6s duration.
- **Dark mode background**: `--bg: #0c0e11` (darkened for card contrast), `--border: #33363f`.
- **Wall card and hotkey slot gaps**: 6px, with `#hotkeySlots` having its own `display:flex; flex-direction:column; gap:6px`.
- **WallType ID preservation**: `_originalIdMap` (key→id from loaded .esx) + `preserveId(wt)` helper ensures template application reuses original IDs, preventing wallSegment orphaning.
- **Auto-load Ekahau Defaults**: when .esx has no wallTypes.json, loads 21 default wall types from `ekahau_defaults.json`.
- Apply Template has **no confirmation dialog** — nothing is permanent until Save .esx.
- Template system: server-backed JSON files in project-local `templates/` folder via `/api/templates/` endpoints.

## Folder Organizer (organizer.html + tools/folder_organizer.py) — SHIPPED v1.0
- Ported from PowerShell script `Organize-EkahauFolders.ps1`.
- For every site folder under a root, creates `images/`, `floorplans/`, `reports/`; keeps `.esx` in root; sorts loose files by type. PDFs→floorplans unless name has report/audit/etc.→reports; `.pcp`→floorplans; WaxFrame/checkpoint/assessment `.json`→reports; unknown types left in place.
- UI flow: pick folder → scan (dry-run preview) → review with per-file checkboxes → apply. Grouped by site folder, collapsible.
- Editable type mapping in Settings modal (image/plan/report extensions, PDF keywords, JSON keywords, skip dirs). Saved to `~/.wd_wireless_tools/organizer_config.json`.
- Collision-safe (`(1)` suffix). Never destructive without confirm.
- Brand color: amber `#d97706`.

## CRITICAL gotchas / lessons
- **The Linux sandbox `bash` mount is FLAKY — it truncates/staleness reads AND writes.** NEVER use `bash`/`sed`/redirects to write these files. A `sed` write once **truncated `walls.html`** mid-JS-string and broke Quick Walls entirely (restored). **Only use the Edit/Write tools (canonical).** `bash` reads are also often stale — verify via the canonical Read tool, not `ls`/`grep` in bash (dates/line-counts lie).
- Memory store dir was unreachable this session (`Write` said "outside connected folders") — hence this file lives in the project folder.
- Cloud data is pull-on-refresh (not live unless Live toggle on).

## Open items / things to verify
1. ~~Merge modal ellipsis~~ — **Fixed in v2.2.** Root cause: `overflow: hidden` on `.modal.peek` clipping h3 titles, and `pk-name` using `white-space: nowrap`. Now uses `overflow-wrap: anywhere` throughout.
2. ~~Port the Folder Organizer~~ — **Shipped as v1.0.**
3. **"External/shared .esx" tagging** — David has teammate-shared `.esx` that can't attach to his cloud sites, so they show as red orphans forever. He's ruminating on how to tag them (file-level vs a catch-all folder) so they stop counting as orphans. Not yet built.
4. ~~Mac support~~ — **Done.** `run.command` added. Auth needs Chrome/Firefox/Edge (not Safari); folder picker needs Python w/ Tk.

## David's working style (feedback)
- Rapid, iterative UI feedback; values momentum and a cohesive "single console" feel. Likes things **obvious** (bold colors, clear active states, WinDiff metaphor — he loved the tabs and big arrows).
- Gets (understandably) frustrated when a fix "still isn't there" — usually it was browser caching; the no-cache header + version stamp now mitigate that. When he says it's still broken after showing a current version, believe him and dig deeper rather than re-asserting caching.
- When David reports a visual bug (like "there's no gap"), **trust him and investigate the CSS/DOM** — don't blame contrast or dark mode. He was right about the `#hotkeySlots` flex gap issue; I wasted time deflecting before finding the real structural CSS problem.
- Values **cross-tool consistency** ("synergy") — same toast style, same menu style, same interactions across all tools. References WaxFrame.com as a design North Star for navigation patterns.
- Delegated version numbering to me. Wants versions kept current and cache-busting built in.
- Casual, direct tone; swears a bit when frustrated; also warm/appreciative ("thanks pal", "nice job pal").
- Uses voice-to-text heavily — messages may have spelling artifacts (e.g., "Echo House" = Ekahau, "Jason" = JSON). Interpret phonetically.
