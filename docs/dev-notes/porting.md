# Porting the updater and the dev toolbar to his other apps

Moved out of `CLAUDE.md` on 2026-09-30. It is only needed when copying these
into LensLedger, Subscription Wizard or WaxFrame Professional.

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


## The dev toolbar

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
