# WD Wireless Tools tests

These tests use temporary directories and generated fictional ESX archives.
They do not read the user's Ekahau folders, browser cookies, saved settings, or
Cloud account, and they do not make network requests.

Run the complete suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

GitHub Actions runs the same suite automatically on Windows and macOS with
both the minimum supported Python 3.10 and current Python 3.14. A release tag
must pass all four combinations before GitHub publishes its ZIP.

The suite currently checks:

- Squirrel file classification, custom destinations, rename rules, scanning,
  duplicate detection, organize/undo, exclusions, overrides, and collisions.
- Generated ESX summaries, image references, project metadata, and project type.
- Cloud/local matching precedence and discriminator safeguards.
- Filesystem containment checks used by Cloud Manager.
- Encrypted Cloud-session storage, migration, tamper rejection, and removal.
- Quick Walls template save/scan/delete behavior and traversal protection.
- Flask page/API routing, the version manifest, and JavaScript syntax.

Live Ekahau Cloud mutations are intentionally not automated. A safety test
must never rename, transfer, or delete real Cloud data.
