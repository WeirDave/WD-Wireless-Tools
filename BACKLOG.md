# WD Wireless Tools — Backlog

_Living, prioritized list. Update as we go: move items between sections, add new ones, note the **why**. Pair with `PROJECT_MEMORY.md` (architecture/context) and `CHANGELOG.md` (version history)._

Priorities: **P1** = do next / blocking · **P2** = wanted · **P3** = nice-to-have / idea.

---

## 🐞 Bugs / To verify
- **[P1] Add selection-based bulk action bar.** When checkboxes are ticked, David expects a bar/toolbar to appear at the top with bulk actions (at minimum: Delete). Currently checkboxes exist but there's no action bar — the only delete is the per-row hover trash icon. Add a floating/sticky bar that appears when `selected.size > 0` with a "Delete N selected" button (and potentially Rename/Merge for Sites). The bulk delete already has backend support in `confirmDelete()` (line ~1655 handles `deleteTarget.bulk`).
- ~~**[P1] Red arrow on Project Files tab is non-clickable.** Fixed in v2.4 — upload support added.~~

## 🚧 In progress / Next up
- ~~**[P2] Check if Ekahau API supports project file uploads.** Confirmed and implemented in v2.4. 3-step presigned flow: initiate → S3 PUT → commit. Endpoint: `/esxfileapi/v1/projects/upload/initiate`.~~
- **[P2] "External/shared .esx" tagging.** Teammate-shared `.esx` can't attach to David's cloud sites, so they show as red orphans forever. Needs a way to tag them (decision pending: per-file vs a catch-all folder vs auto-suggest "these look external") so they stop counting as orphans. David was ruminating — get his call first.

## 💡 Features / Ideas (backlog)
- **[P3] Always-visible "source files" indicator.** The preview eye now lives in the hover overlay; if David misses the at-a-glance amber signal for folders holding non-cloud source files, add a small persistent amber dot separate from the clickable eye.
- **[P3] Bulk "merge several → one destination."** Single-folder merge only today (deliberately, for safety). If merging many gets tedious, add a multi-select "merge selected into…" that still picks the target explicitly.
- **[P3] Folder Organizer: undo support.** After applying moves, offer an "Undo last organize" that moves files back. Would need to log the moves to a temp file.
- **[P3] Folder Organizer: custom subfolder names.** Currently images/floorplans/reports. Let users rename or add their own subfolder targets via Settings.
- **[P3] Folder Organizer: "suggest grouping" mode.** For flat folders with mixed-site files (e.g. a Downloads dump), detect common filename prefixes (like "CLMB1", "Arsenal") and suggest grouping into site subfolders before sorting. Preview only — no moves without user confirmation. Pattern matching is fragile so keep it advisory, not automatic.

## ✅ Recently shipped (for context, newest first)
- **Cloud Manager v2.5**: .esx upload to Ekahau Cloud — 3-step presigned S3 flow (`initiate` → S3 PUT → `commit`). Red arrow on Project Files tab now active (uploads local .esx). Ghost `+ Upload` button on orphan rows. Split-view `↑ Upload` button for local-only .esx files. **Assign to site**: `POST /site-management-api/v1/sites/{id}/datasets` — upload + auto-assign when site_id known, standalone "→ Site" button on cloud-only projects with site picker modal. `upload_project`, `assign_to_site` added to `EkahauAPI`, `CloudManager`, Flask routes, and `API_MAP`.
- **Quick Walls v7.9**: Centered toast messages (theme bg, blue border, theme text, 6s duration), hotkey panel CSS gap fix (`#hotkeySlots` flex container), dark mode background darkened (`#0c0e11`), wall card/hotkey slot gap 6px, **wallType ID preservation** (`_originalIdMap` + `preserveId()`) — fixes "Unknown" walls after template apply, auto-load Ekahau Defaults when .esx has no wallTypes.json, removed Apply confirmation dialog, WaxFrame-style hamburger menu with section headers and `·` sub-items.
- **Cloud Manager v2.3**: Centered toast messages (same style), WaxFrame-style hamburger menu, user guide link (`/guide-cloud`), **New Site** dual-creation with Cloud/Local checkboxes (both checked by default), user guide created (`guide-cloud.html`).
- **Folder Organizer v1.1**: Centered toast messages (same style), WaxFrame-style hamburger menu, user guide link (`/guide-organizer`), user guide created (`guide-organizer.html`).
- **Quick Walls v6.2**: Compact navy topbar (matches Cloud Manager), native OS file dialogs for all saves (showSaveFilePicker + fallback), permanent template dropdown selector with Default button and auto-apply checkbox, version stamp on dropzone, responsive layout (3-col/2-col/1-col breakpoints at 1600/1200/720px), hamburger menu cleanup, cross-tool nav links.
- **Cloud Manager v2.2**: Fixed merge modal text truncation (overflow-wrap: anywhere), live auto-refresh interval setting (15/30/60s), Folder Organizer link in hamburger menu, responsive layout (720px mobile breakpoint), removed inline nav links (nav in hamburger only).
- **Folder Organizer v1.0** _(new tool)_: Sort loose Ekahau site files into images/floorplans/reports/!Quick Walls Templates subfolders. Dry-run preview → review → apply. Editable type mapping in Settings. Collision-safe. Responsive layout (720px mobile breakpoint). Home page card (amber).
- **Suite**: `run.command` macOS launcher. Home page responsive 3-column grid (3/2/1 col at 900/640px). CHANGELOG.md.
- Cloud Manager **v2.1**: hamburger menu (About/Settings/Change Folder/Refresh/links), cross-tool links open new tabs, removed all ellipsis, merge preview shows every file with include/exclude checkboxes, no-cache headers + version-as-cache-check.
- Cloud Manager **v2.0**: WinDiff aligned ledger, status left-tabs (green/orange/red), All filter, big gutter markers, folder→folder merge w/ date-stamp + exclude, Compare, shift-click select, Live auto-refresh, source-file safety net, folder-tab UI.
- Quick Walls **v6.1**: alphabetical sort, wide color left-tabs (cards + slots), full names, Save/Apply Template buttons, template saves a real file, WD brand colors, fixed the browse re-entrancy bug, restored a truncated file.

## ⚠️ Process reminders (don't repeat mistakes)
- **NEVER write these files via bash/sed/redirects** — the sandbox mou