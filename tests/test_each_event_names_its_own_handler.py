"""A control that listens for several events names a handler for each one.

`WD.actions` resolves the handler for an event from `data-fn-<event>` and
falls back to `data-fn`. Two shapes defeat that silently:

* **One `data-fn` shared across events that need different handlers.** Quick
  Walls' shortcut slots declared dragstart, dragend, dragover, dragleave and
  drop with a single `data-fn="onSlotDragStart"`, so every one of them ran
  dragstart. A drop on an empty slot assigned nothing, a dragend left the card
  greyed, and Firefox threw on every dragover.
* **Several `data-fn` attributes on one element.** HTML keeps the first and
  drops the rest, so Cloud Manager's share box sent input, paste, blur and
  keydown all to the input handler: Enter, leaving the box and the arrow keys
  did nothing.

Only pairs that genuinely share one handler may use the fallback for more
than one event; each handler in `SHARED_OK` reads `event.type` to tell them
apart.
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Events that one handler serves on purpose, telling them apart by
#: `event.type` - a hover handler for enter and leave, a field handler for
#: change and input.
SHARED_OK = [{"mouseenter", "mouseleave"}, {"change", "input"}]

TAG = re.compile(r"<[a-zA-Z][^<>]*?data-action-[a-z]+=[^<>]*?>", re.S)


def _tracked():
    out = subprocess.run(["git", "ls-files", "web"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.split() if p.endswith((".js", ".html"))]


def problems(files=None):
    """`files` is (name, text) pairs; the tracked pages and scripts when
    omitted."""
    if files is None:
        files = [(p.relative_to(ROOT).as_posix(), p.read_text(encoding="utf-8"))
                 for p in _tracked()]
    found = []
    for name, text in files:
        for m in TAG.finditer(text):
            tag = m.group(0)
            line = text.count("\n", 0, m.start()) + 1
            where = "%s:%d" % (name, line)
            if len(re.findall(r"\sdata-fn=", tag)) > 1:
                found.append(where + " has more than one data-fn")
                continue
            calls = set(re.findall(r'data-action-([a-z]+)="call"', tag))
            if re.search(r'\sdata-action="call"', tag):
                calls.add("click")
            named = set(re.findall(r"data-fn-([a-z]+)=", tag))
            fallback = calls - named
            if len(fallback) > 1 and not any(fallback <= ok for ok in SHARED_OK):
                found.append("%s sends %s to one data-fn"
                             % (where, ", ".join(sorted(fallback))))
    return found


class EachEventNamesItsOwnHandlerTests(unittest.TestCase):

    def test_no_control_sends_different_events_to_one_handler(self):
        self.assertEqual(problems(), [])

    def test_the_check_finds_the_shape_that_broke_the_shortcuts(self):
        """The scan has to be able to fail: run it over the markup the
        shortcut slots had before the fix."""
        broken = ('<div data-action-dragstart="call" data-fn="onSlotDragStart"'
                  ' data-action-drop="call" data-arg-event="1">')
        dup = ('<input data-action-input="call" data-fn="a"'
               ' data-action-blur="call" data-fn="b">')
        found = problems([("probe.html", broken + "\n" + dup)])
        self.assertEqual(len(found), 2, found)


if __name__ == "__main__":
    unittest.main()
