"""The size of every sheet in a PDF, in order, with nothing but the stdlib.

A print test asks what paper each page came out on, and PyMuPDF is not
installed in CI - so a test written against it skips there, which is the
silent kind of pass `requirements-dev.txt` describes. This reads just enough
of the file to answer that one question: the page tree for the order, and
each page's MediaBox for the size.

Firefox keeps its page objects inside compressed object streams, so a regex
over the raw bytes finds nothing; those streams are unpacked first. Chromium
writes them in the clear. Both are handled the same way once every object is
in one table.
"""
from __future__ import annotations

import re
import zlib

_OBJ = re.compile(rb"(\d+)\s+0\s+obj\b(.*?)endobj", re.S)
_STREAM = re.compile(rb"stream\r?\n(.*)\r?\nendstream", re.S)
_REF = re.compile(rb"(\d+)\s+0\s+R")
_BOX = re.compile(rb"/MediaBox\s*\[\s*([-\d.\s]+)\]")


def _objects(pdf: bytes) -> dict[int, bytes]:
    table: dict[int, bytes] = {}
    for m in _OBJ.finditer(pdf):
        num, body = int(m.group(1)), m.group(2)
        table[num] = body
        if b"/ObjStm" not in body:
            continue
        s = _STREAM.search(body)
        if not s:
            continue
        data = zlib.decompress(s.group(1))
        n = int(re.search(rb"/N\s+(\d+)", body).group(1))
        first = int(re.search(rb"/First\s+(\d+)", body).group(1))
        head = data[:first].split()
        pairs = [(int(head[i]), int(head[i + 1])) for i in range(0, 2 * n, 2)]
        for k, (onum, off) in enumerate(pairs):
            end = pairs[k + 1][1] if k + 1 < len(pairs) else len(data) - first
            table[onum] = data[first + off:first + end]
    return table


def _dict_part(body: bytes) -> bytes:
    s = body.find(b"stream")
    return body if s < 0 else body[:s]


def sheet_sizes(pdf: bytes) -> list[tuple[float, float]]:
    """(width, height) in points for every page, in reading order."""
    table = _objects(pdf)
    root = None
    for body in table.values():
        d = _dict_part(body)
        if re.search(rb"/Type\s*/Pages\b", d) and b"/Parent" not in d:
            root = d
            break
    if root is None:
        raise AssertionError("no page tree in the PDF")

    out: list[tuple[float, float]] = []

    def walk(node: bytes, inherited):
        box = _BOX.search(node)
        box = box.group(1) if box else inherited
        if re.search(rb"/Type\s*/Pages\b", node):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", node).group(1)
            for ref in _REF.findall(kids):
                walk(_dict_part(table[int(ref)]), box)
            return
        if box is None:
            raise AssertionError("a page with no MediaBox")
        x0, y0, x1, y1 = (float(v) for v in box.split()[:4])
        out.append((x1 - x0, y1 - y0))

    walk(root, None)
    return out


def orientations(pdf: bytes) -> str:
    """One letter per sheet - L or P - so a sequence reads at a glance."""
    return "".join("L" if w > h else "P" for (w, h) in sheet_sizes(pdf))
