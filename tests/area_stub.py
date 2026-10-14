"""A stand-in for WD.AreaEditor, for harnesses that run a page's script on its own.

Several tests evaluate capacity.js or prep.js against a hand-made `WD` to
check something that has nothing to do with drawing - the per-floor headcount,
the multiplier line, what Apply sends. Those scripts now ask WD.AreaEditor for
its controls and its query parameter, so the hand-made `WD` needs one that
does nothing and answers "no outline". The real tool is exercised by
tests/test_area_editor.py and tests/test_area_drawing_browser.py.
"""

#: Goes first inside the `WD = { ... }` literal.
JS = ("AreaEditor: { create: () => ({ cancel() {}, mode: () => 'idle', claims: () => false,"
      " overlay() {}, onDown: () => false, onMove() {}, onUp() {} }),"
      " bind() {}, sync() {}, controlsHtml: () => '', param: () => '' },")


def with_area_stub(harness: str) -> str:
    """The harness with the stand-in in every `WD = {` it builds."""
    out = harness
    for head in ("global.WD = {", "globalThis.WD = {"):
        out = out.replace(head, head + " " + JS)
    if out == harness:
        raise AssertionError("this harness builds no WD to put the stand-in in")
    return out
