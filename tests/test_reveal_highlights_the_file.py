"""Show in Explorer, on the paths he actually has.

**Every "Show" button in the suite was opening the wrong folder**, on every
path with a space in it - which is all of his, because his projects live under
`Documents\\Ekahau AI Pro Projects`. Reported as "the Show button just takes
you to the parent directory of Documents", against one tab - and it was never
that tab's bug: `tools/reveal.py` is one function with five callers, and every
one of them had it.

The mechanism, because it is not obvious and the code looked right:

    subprocess.Popen(["explorer", "/select," + str(p)])

Windows has no argv, so Python joins that list with `list2cmdline`, which sees
a space inside the single token and quotes *the whole token*:

    explorer "/select,C:\\Users\\...\\Ekahau AI Pro Projects\\x.esx"

Explorer will not read a switch that starts inside a quote, so it drops it and
opens its default folder. **On a path with no spaces the same code is
correct**, which is why it survived every check ever made here - including the
note in CLAUDE.md that fixed the argument-splitting half of this and left the
quoting half in place.

So the assertion is on the command line, not on the call: `windows_select_command`
returns the string, and these tests read it. Driving `Popen` would have passed
throughout, since the call itself always succeeded.
"""
from __future__ import annotations

import re
import subprocess
import unittest

from tools.reveal import windows_select_command

#: The shape of his real paths, invented names throughout.
WITH_SPACES = r"C:\Users\wduser\Documents\Ekahau AI Pro Projects\NORTHWIND\Northwind Survey - Power Level Adjustment.esx"
NO_SPACES = r"C:\Projects\Survey.esx"


class TheSwitchIsOutsideTheQuotesTests(unittest.TestCase):

    def test_the_path_is_quoted_and_the_switch_is_not(self):
        cmd = windows_select_command(WITH_SPACES)
        self.assertTrue(cmd.startswith('explorer /select,"'), cmd)
        self.assertTrue(cmd.endswith('"'), cmd)
        #: The thing that was wrong: a quote before `/select`.
        self.assertNotIn('"/select', cmd)

    def test_the_whole_path_survives_including_its_spaces(self):
        cmd = windows_select_command(WITH_SPACES)
        quoted = re.search(r'"(.*)"', cmd)
        self.assertIsNotNone(quoted, cmd)
        self.assertEqual(quoted.group(1), WITH_SPACES)

    def test_a_path_without_spaces_is_built_the_same_way(self):
        """The old code happened to be right here, which is the whole reason
        nobody caught it. One form for both, so there is no lucky case."""
        cmd = windows_select_command(NO_SPACES)
        self.assertEqual(cmd, 'explorer /select,"%s"' % NO_SPACES)

    def test_the_list_form_really_does_mangle_it(self):
        """The bug, reproduced against the standard library rather than
        asserted from memory. If Python ever stopped quoting that token this
        test says so, and the fix could be reconsidered."""
        mangled = subprocess.list2cmdline(["explorer", "/select," + WITH_SPACES])
        self.assertIn('"/select', mangled)
        self.assertNotEqual(mangled, windows_select_command(WITH_SPACES))


class EveryCallerGetsTheFixTests(unittest.TestCase):
    """One implementation, five callers - the reason this lives in one file.

    Quick Walls, Prep, the log path, Cloud Manager's row menu and the Backup
    Folder tab all reveal through `tools.reveal`. A second copy of the command
    line anywhere else is a second copy of this bug waiting to happen.
    """

    def test_nothing_else_builds_an_explorer_select_command(self):
        """Walked as source, not grepped as text.

        The first draft of this matched the substring and failed on
        `cloud_manager.py`, which only *mentions* `/select,` in a comment
        explaining why it delegates here - the opposite of an offender. Same
        lesson as the housekeeping checker: match what the code does, and a
        checker that has to exempt its own true cases has a hole in it.
        """
        import ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in sorted(root.glob("tools/*.py")) + [root / "server.py"]:
            if path.name == "reveal.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and "/select," in node.value):
                    offenders.append("%s:%s" % (path.name, node.lineno))
        self.assertEqual(offenders, [], "these build their own: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
