"""A dialog that asks him for something has a control that accepts it.

"The dialog box appears but there is no Apply. I add both the recent names
and the only option is Add or Close."

The bulk share dialog collected recipients and offered **Add** and **Close**.
`_shareAdd()` was in fact the commit, so the feature worked - but in a dialog
whose whole interaction is putting names on a list, and where clicking a
remembered name already does exactly that, "Add" reads as the step he had
just done twice. No control was named after the operation, so there was no
way to tell the dialog could do anything.

**This is the third of the same shape in a week**: the Sync dialog naming a
control that was greyed out for every row he had, dev mode with no visible
way out, and now a dialog with nothing that commits. The common part is a
surface that looks finished and stops short of the action, and the common
cost is that he finds it while working.

So it is checked rather than remembered. For every modal that collects input,
there must be at least one button that is not a way out - and its handler has
to exist, because a button calling a function nobody defined is the previous
variety of this bug.

**What counts as collecting input**: a modal containing an `input`, `select`
or `textarea` that is not purely a search or filter box. **What counts as a
way out**: `closeModal`, `hideModal`, a cancel, a dismiss. Anything else is
taken to be an action, and the test says which one it found so a wrong guess
is visible rather than silent.

Read from the shipped pages, and every handler resolved against the shipped
scripts.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

#: Handlers that take him out of the dialog rather than doing its work.
WAYS_OUT = re.compile(
    r"^(closeModal|hideModal|_?close|_?cancel|dismiss)\b|"
    r"(Cancel|Close|Dismiss)\s*\(", re.I)

#: A modal whose inputs only narrow a list is not collecting anything - it
#: has nothing to commit, and closing it is the whole interaction. Each entry
#: is here because it was looked at, not to make a number go green.
NOT_COLLECTING = {
    # Pickers and searches: typing filters the list, clicking an item is the
    # action, and the item is not a submit button.
    "jumpModal",
    "helpModal",
    "shortcutsModal",
    "aboutModal",
    "diagnosticsModal",
    "devResultModal",
}


def _modals(html: str):
    """Each `modal-overlay` block, by id, with its inner markup."""
    out = {}
    for m in re.finditer(r'<div[^>]*class="[^"]*modal-overlay[^"]*"[^>]*'
                         r'id="([^"]+)"', html):
        start = m.start()
        depth, i = 0, start
        while i < len(html):
            nxt = re.compile(r"<div\b|</div>").search(html, i)
            if not nxt:
                break
            depth += 1 if nxt.group(0) == "<div" else -1
            i = nxt.end()
            if depth == 0:
                break
        out[m.group(1)] = html[start:i]
    return out


#: A box that narrows a list is not something he is being asked to submit -
#: the dialog's action is clicking an item. Recognised by what it is for
#: rather than by listing the dialogs, so a new picker is handled without
#: anybody remembering to add it.
_FILTER_BOX = re.compile(r'type="search"|(id|placeholder|class)="[^"]*'
                         r'(search|filter|find|query)', re.I)


def _collects_input(body: str) -> bool:
    fields = re.findall(r"<(?:input|select|textarea)\b[^>]*>", body, re.I)
    real = [f for f in fields
            if not _FILTER_BOX.search(f)
            and not re.search(r'type="(checkbox|radio|hidden)"', f, re.I)]
    return bool(real)


def _buttons(body: str):
    """(handler, label) for every button in the block.

    This suite wires a button three ways and the guard has to know all
    three, because a button it cannot see the wiring of looks exactly like a
    dialog with no action:

    * `onclick="doTheThing()"` - most of Cloud Manager;
    * `data-action="call" data-fn="saveConfig"` - the declarative dispatcher
      ported from WaxFrame, used by Organizer and Rename;
    * an `id` the page binds with `addEventListener`.

    Reading only `onclick` reported five dialogs as having no action when
    each had a Save or a Create, which would have made this fire on exactly
    the dialogs that are fine - and a guard that cries wolf is one he stops
    reading, which is the failure mode it exists to prevent.
    """
    out = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", body,
                         re.I | re.S):
        attrs, label = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
        onclick = re.search(r'onclick="([^"]*)"', attrs)
        datafn = re.search(r'data-fn="([^"]*)"', attrs)
        ident = re.search(r'id="([^"]*)"', attrs)
        if onclick:
            handler = onclick.group(1)
        elif datafn:
            handler = datafn.group(1) + "()"
        elif ident:
            handler = "#" + ident.group(1)
        else:
            handler = ""
        out.append((handler.strip(), label.strip()))
    return out


#: A label that means "leave", in any of the spellings this suite uses.
_WAY_OUT_LABEL = re.compile(r"^\s*(cancel|close|dismiss|not now|back)\s*$", re.I)


def _is_way_out(handler: str, label: str) -> bool:
    return bool(WAYS_OUT.search(handler) or _WAY_OUT_LABEL.match(label))


def _defined_names() -> set:
    names = set()
    for js in sorted((WEB / "assets" / "js").rglob("*.js")):
        src = js.read_text(encoding="utf-8", errors="replace")
        names |= set(re.findall(r"function\s+([A-Za-z_$][\w$]*)", src))
        names |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()", src))
        names |= set(re.findall(r"([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?function", src))
        names |= set(re.findall(r"(?:WD|Dev)\.([A-Za-z_$][\w$]*)\s*=", src))
    return names


class EveryInputDialogHasAWayToCommitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pages = {p.name: p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(WEB.rglob("*.html"))}
        cls.defined = _defined_names()

    def test_there_are_dialogs_to_check(self):
        """A parser that silently matches nothing would pass forever."""
        total = sum(len(_modals(h)) for h in self.pages.values())
        self.assertGreater(total, 10, "the modal parser found almost nothing")

    def test_every_dialog_that_collects_input_can_commit_it(self):
        missing = []
        for page, html in self.pages.items():
            for mid, body in _modals(html).items():
                if mid in NOT_COLLECTING or not _collects_input(body):
                    continue
                actions = [(h, l) for (h, l) in _buttons(body)
                           if h and not _is_way_out(h, l)]
                if not actions:
                    missing.append(f"{page}#{mid}")
        self.assertEqual(
            missing, [],
            "these dialogs ask him for something and have no control that "
            "accepts it - only ways out: %s" % sorted(missing))

    def test_the_share_dialog_names_its_action(self):
        """The one that was reported. A commit control called "Add", in a
        dialog where adding to the list is a different button, is not one he
        can find - so this asks for a label that says what it does."""
        body = _modals(self.pages["cloud.html"])["shareModal"]
        actions = [(h, l) for (h, l) in _buttons(body)
                   if h and not _is_way_out(h, l)]
        labels = [l.lower() for (_, l) in actions]
        self.assertTrue(any("share" in l for l in labels),
                        "no control in the share dialog is named for sharing: "
                        f"{labels}")

    def test_the_commit_controls_all_resolve_to_something(self):
        """A button naming a function nobody defined is the same defect
        wearing the previous week's clothes."""
        unknown = []
        for page, html in self.pages.items():
            for mid, body in _modals(html).items():
                if mid in NOT_COLLECTING or not _collects_input(body):
                    continue
                for handler, _label in _buttons(body):
                    if not handler or _is_way_out(handler, _label):
                        continue
                    if handler.startswith("#"):
                        continue   # wired by id; the handler check below
                                   # only covers inline calls
                    for name in re.findall(r"([A-Za-z_$][\w$]*)\s*\(", handler):
                        if name in ("if", "for", "while", "return",
                                    "function", "event", "switch"):
                            continue
                        if name not in self.defined:
                            unknown.append(f"{page}#{mid}: {name}()")
        self.assertEqual(unknown, [],
                         "these dialog buttons call something that is not "
                         "defined anywhere: %s" % sorted(set(unknown)))


if __name__ == "__main__":
    unittest.main()
