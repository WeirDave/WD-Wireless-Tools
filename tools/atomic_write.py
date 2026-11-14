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

import functools
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


def serialised(lock):
    """Run the decorated function holding `lock`.

    An atomic write makes each file whole; it does not stop two requests each
    reading the file, changing their copy and writing it back, which loses the
    first one's change. The server handles requests on several threads, so a
    store that reads, changes and writes takes this around the whole of it. The
    lock is re-entrant: a function that calls another that is also serialised
    on the same lock does not wait for itself.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def run(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)
        return run
    return decorate
