"""Write a file so that it is either the old one or the new one.

`open(path, "w")` truncates the file before the first byte of the new content
is written. A crash, a full disk, or a value `json.dump` cannot serialise
halfway through leaves a truncated file and the previous good copy is already
gone. For a wall template, the capacity templates, the rename profiles and the
undo logs, that is the user's own work.

The content is built first, written to a temp file in the same folder, and
renamed over the target. The rename is one operation, so a reader sees one
version or the other and never half of one. The temp file is removed if
anything fails, and the target is untouched.

Several stores here already did exactly this by hand (`report_store`,
`plantrim_store`, `area_presets`, `sync_state`, `settings`); this is that,
written once for the ones that had not.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_text(path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".wd-tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path, data, indent: int = 2, encoding: str = "utf-8") -> None:
    """`json.dumps` first - so a value that cannot be serialised raises before
    anything on disk has been touched - then `write_text`."""
    write_text(path, json.dumps(data, indent=indent), encoding)
