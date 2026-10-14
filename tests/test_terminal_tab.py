"""The launcher opens in a Windows Terminal tab, and only when it should.

`tools/terminal_tab.py` is what `Start WD Wireless Tools.bat` runs first. It
decides one thing - hand off to `wt.exe -w 0 new-tab`, or stay in this window -
and a wrong answer in either direction is visible: a tab opened from inside a
tab is a loop, and a launcher that never hands off is the thing this exists to
replace.

Windows Terminal cannot be started here, so these drive the decision with its
inputs injected (OS, environment, `which`, `Popen`, settings) and assert the
command that would have run. What none of this proves is how a real
`wt.exe` parses that command line; that is read off a real machine.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import settings as suite_settings  # noqa: E402
from tools import terminal_tab as tt  # noqa: E402

NODE_TIMEOUT_S = 120
BAT = "C:\\wd tools\\Start WD Wireless Tools.bat"
WT = "C:\\Users\\x\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe"


def _which(found=True):
    return lambda name: WT if (found and name == "wt.exe") else None


def _decide(**over):
    args = dict(os_name="nt", env={}, which=_which(), settings={}, argv=())
    args.update(over)
    return tt.can_hand_off(BAT, **args)


class WhenItHandsOffTests(unittest.TestCase):
    def test_a_bare_double_click_on_windows_with_wt_installed_hands_off(self):
        self.assertTrue(_decide())

    def test_already_inside_windows_terminal_it_stays(self):
        """Typed into an open PowerShell tab, or WT is the default terminal:
        the launcher runs in the tab it is in."""
        self.assertFalse(_decide(env={"WT_SESSION": "9f1c"}))

    def test_inside_another_terminal_host_it_stays(self):
        self.assertFalse(_decide(env={"TERM_PROGRAM": "vscode"}))

    def test_the_flag_the_tab_passes_back_stops_a_second_tab(self):
        self.assertFalse(_decide(argv=(BAT, tt.IN_TAB_FLAG)))

    def test_switched_off_in_settings_it_stays(self):
        self.assertFalse(_decide(settings={"global": {"terminal_tab": False}}))

    def test_without_wt_exe_it_stays(self):
        self.assertFalse(_decide(which=_which(found=False)))

    def test_off_windows_it_stays(self):
        self.assertFalse(_decide(os_name="posix"))

    def test_a_semicolon_in_the_path_stays_because_wt_would_split_it(self):
        self.assertFalse(tt.can_hand_off(
            "C:\\a;b\\Start WD Wireless Tools.bat", os_name="nt", env={},
            which=_which(), settings={}, argv=()))


class TheInputsTests(unittest.TestCase):
    def test_find_wt_takes_wt_exe_and_falls_back_to_wt(self):
        self.assertEqual(WT, tt.find_wt(_which()))
        only_bare = lambda name: "C:\\bin\\wt" if name == "wt" else None  # noqa: E731
        self.assertEqual("C:\\bin\\wt", tt.find_wt(only_bare))
        self.assertIsNone(tt.find_wt(_which(found=False)))

    def test_a_terminal_host_is_told_by_the_variables_it_sets(self):
        self.assertTrue(tt.already_in_a_terminal({"WT_SESSION": "1"}))
        self.assertTrue(tt.already_in_a_terminal({"TERM_PROGRAM": "vscode"}))
        self.assertFalse(tt.already_in_a_terminal({"PATH": "x"}))
        self.assertFalse(tt.already_in_a_terminal({"WT_SESSION": ""}))


class TheTabCommandTests(unittest.TestCase):
    def test_it_opens_a_tab_in_the_current_window_and_runs_the_launcher(self):
        cmd = tt.tab_command(WT, BAT)
        self.assertEqual(WT, cmd[0])
        self.assertEqual(["-w", "0", "new-tab"], cmd[1:4])
        # What follows the tab's options is the command line it runs: the
        # launcher, carrying the guard flag.
        self.assertEqual(["cmd.exe", "/c", BAT, tt.IN_TAB_FLAG], cmd[-4:])
        self.assertEqual("WD Wireless Tools", cmd[cmd.index("--title") + 1])
        self.assertEqual("C:\\wd tools", cmd[cmd.index("-d") + 1])


class OpenTabTests(unittest.TestCase):
    def test_it_starts_the_tab_and_says_so(self):
        popen = MagicMock()
        self.assertTrue(tt.open_tab(BAT, popen=popen, which=_which()))
        popen.assert_called_once()
        self.assertEqual(tt.tab_command(WT, BAT), popen.call_args[0][0])

    def test_a_wt_that_will_not_start_means_run_here_not_nothing(self):
        popen = MagicMock(side_effect=OSError("access denied"))
        with patch.object(tt, "_note_failure") as note:
            self.assertFalse(tt.open_tab(BAT, popen=popen, which=_which()))
        note.assert_called_once()

    def test_main_reports_handed_off_only_when_a_tab_started(self):
        with patch.object(tt, "can_hand_off", return_value=True), \
                patch.object(tt, "open_tab", return_value=True):
            self.assertEqual(tt.HANDED_OFF, tt.main([BAT]))
        with patch.object(tt, "can_hand_off", return_value=True), \
                patch.object(tt, "open_tab", return_value=False):
            self.assertEqual(tt.RUN_HERE, tt.main([BAT]))
        with patch.object(tt, "can_hand_off", return_value=False), \
                patch.object(tt, "open_tab") as opened:
            self.assertEqual(tt.RUN_HERE, tt.main([BAT]))
        opened.assert_not_called()

    def test_run_as_the_launcher_runs_it_it_is_silent_and_says_stay(self):
        """`python -m tools.terminal_tab "<bat>"` is the real call, run here as
        a subprocess to prove the entry point imports and exits quietly.

        The environment says it is already inside Windows Terminal. Without
        that, a Windows machine with `wt.exe` answers "handed off" - correctly -
        and this test would open a real tab on whoever ran it. CI's Windows
        runner did exactly that on its first run.
        """
        env = dict(os.environ, WT_SESSION="test")
        r = subprocess.run(
            [sys.executable, "-m", "tools.terminal_tab", BAT],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
            env=env, timeout=60)
        self.assertEqual(tt.RUN_HERE, r.returncode, r.stdout + r.stderr)
        self.assertEqual("", r.stdout.strip() + r.stderr.strip())


class TheSettingTests(unittest.TestCase):
    def test_it_ships_on(self):
        self.assertIs(True, suite_settings.DEFAULTS["global"]["terminal_tab"])
        self.assertTrue(tt.tab_enabled(suite_settings.DEFAULTS))

    def test_a_saved_off_is_read_back_as_off_through_the_real_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"global": {"terminal_tab": False}}),
                            encoding="utf-8")
            loaded = suite_settings.load_settings(_path=path)
        self.assertFalse(tt.tab_enabled(loaded))

    def test_a_settings_file_that_says_nothing_leaves_it_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"global": {"output_dir": ""}}),
                            encoding="utf-8")
            loaded = suite_settings.load_settings(_path=path)
        self.assertTrue(tt.tab_enabled(loaded))

    def test_settings_that_cannot_be_read_do_not_turn_it_off(self):
        class Broken:
            def get(self, *_):
                raise ValueError("unreadable")
        self.assertTrue(tt.tab_enabled(Broken()))


class RestartTests(unittest.TestCase):
    """The server's restart, with the OS and the process exit replaced."""

    @classmethod
    def setUpClass(cls):
        # WD_USER_DIR is read once, at import, so it has to be set before the
        # server is first imported - and the scratch directory removed after.
        cls._scratch = None
        if "WD_USER_DIR" not in os.environ:
            cls._scratch = tempfile.TemporaryDirectory(prefix="wd-tt-")
            os.environ["WD_USER_DIR"] = cls._scratch.name
        import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        if cls._scratch is not None:
            os.environ.pop("WD_USER_DIR", None)
            cls._scratch.cleanup()

    class _Exit(Exception):
        pass

    def _restart(self, tab_opened):
        fake_os = SimpleNamespace(
            name="nt", getppid=lambda: 4321,
            _exit=MagicMock(side_effect=self._Exit))
        popen = MagicMock()
        close = MagicMock()
        restart_in_tab = MagicMock(return_value=tab_opened)
        with patch.object(self.server, "os", fake_os), \
                patch.object(self.server.time, "sleep"), \
                patch.object(self.server.subprocess, "Popen", popen), \
                patch.object(self.server, "_close_old_launcher_window", close), \
                patch.object(self.server.terminal_tab, "restart_in_tab",
                             restart_in_tab):
            with self.assertRaises(self._Exit):
                self.server._restart_in_new_console()
        return fake_os._exit, popen, close, restart_in_tab

    def test_a_restart_opens_the_new_launcher_as_a_tab_and_exits_cleanly(self):
        leave, popen, close, restart_in_tab = self._restart(tab_opened=True)
        launcher = restart_in_tab.call_args[0][0]
        self.assertTrue(launcher.endswith("Start WD Wireless Tools.bat"))
        # The launcher turns this code into a clean exit, which is what lets
        # Windows Terminal close the old tab. Killing the window would not.
        leave.assert_called_once_with(tt.RESTART_EXIT_CODE)
        popen.assert_not_called()
        close.assert_not_called()

    def test_without_a_tab_the_old_console_restart_is_unchanged(self):
        leave, popen, close, _ = self._restart(tab_opened=False)
        self.assertEqual("cmd.exe", popen.call_args[0][0][0])
        close.assert_called_once_with(4321)
        leave.assert_called_once_with(0)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheSettingsPageCarriesItTests(unittest.TestCase):
    """The checkbox is shown from what is saved and sent back on save.

    A control that renders and is dropped from the patch is the shape this
    repository keeps finding. The page's functions are run in a context where
    every name the page does not define is a stub, so a missing stub cannot
    stop the body partway and hide a write that comes after it.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const [mode, savedJson, tick] = process.argv.slice(2);

function slice(header) {
  const a = src.indexOf(header);
  if (a < 0) throw new Error(header + ' has moved or been renamed');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}

const any = () => new Proxy(function () {}, {
  get: (t, k) => k === Symbol.toPrimitive ? () => '' : any(),
  apply: () => any(),
});
const elements = {};
const el = (id) => elements[id] = elements[id] || {
  id, value: '', checked: false, textContent: '', innerHTML: '', style: {},
  options: [], dataset: {}, classList: { add(){}, remove(){}, toggle(){},
    contains(){ return false; } },
  querySelectorAll: () => [], querySelector: () => null,
  addEventListener(){}, appendChild(){} };
const sent = [];
const sandbox = new Proxy({
  document: { getElementById: el, querySelectorAll: () => [],
              querySelector: () => null },
  settings: JSON.parse(savedJson),
  API: (endpoint, payload) => { sent.push({endpoint, payload});
                                return { then(){ return this; } }; },
  splitComma: () => [], collectCustomDests: () => [],
  _subfolders: [], _subfolderNames: {},
  SP: {},
  console,
}, { has: () => true, get: (t, k) => k in t ? t[k] : (k === Symbol.unscopables ? undefined : any()) });
vm.createContext(sandbox);

if (mode === 'populate') {
  vm.runInContext(slice('  function populate() {') + '; populate();', sandbox);
  process.stdout.write(JSON.stringify({ checked: el('sTerminalTab').checked }));
} else {
  el('sTerminalTab').checked = tick === 'on';
  vm.runInContext(slice('  SP.save = function () {') + '; SP.save();', sandbox);
  const call = sent.find(c => /settings\/update/.test(c.endpoint)) || {};
  const patch = (call.payload && call.payload.patch) || null;
  process.stdout.write(JSON.stringify({
    terminal_tab: patch && patch.global ? patch.global.terminal_tab : null }));
}
"""

    def run_probe(self, mode, saved, tick="on"):
        r = subprocess.run(
            ["node", "-e", self.PROGRAM,
             str(ROOT / "web" / "assets" / "js" / "settings-page.js"),
             mode, json.dumps(saved), tick],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_saved_off_shows_unticked(self):
        got = self.run_probe("populate", {"global": {"terminal_tab": False}})
        self.assertIs(False, got["checked"])

    def test_saved_on_and_nothing_saved_both_show_ticked(self):
        for saved in ({"global": {"terminal_tab": True}}, {"global": {}}):
            with self.subTest(saved=saved):
                self.assertIs(True, self.run_probe("populate", saved)["checked"])

    def test_unticking_sends_false_and_ticking_sends_true(self):
        self.assertIs(False, self.run_probe("save", {}, tick="off")["terminal_tab"])
        self.assertIs(True, self.run_probe("save", {}, tick="on")["terminal_tab"])


if __name__ == "__main__":
    unittest.main()
