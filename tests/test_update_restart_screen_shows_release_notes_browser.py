"""After an update installs, the "Restart to finish" screen lists what arrived.

The notes of the releases newer than the install were shown only above the
Update button; the moment the update ran they were replaced by the restart
screen, so the one time the person is about to restart onto new code was the
one time the notes were gone.

The probe mounts the real updater panel with invented releases, stubs the one
request that installs (nothing is installed), presses the real Update button,
and reads the real restart screen. A release newer than the version the update
reports landing on must not be listed, a pull that moved no version must list
nothing, and the heading must not say "since your version".
"""
from __future__ import annotations

import unittest

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.support.ui import WebDriverWait

PREPARE = """
window.wdOpenAbout();
return true;
"""

IDLE = """
var b = document.querySelector('#wdAboutModal .wd-about-checkBtn');
return !!b && !b.disabled;
"""

# `landed` is the version the stubbed install reports. Five releases are
# offered, 9.0.9 down to 9.0.5; an update that lands on 9.0.8 must not list
# 9.0.9.
MOUNT = """
var landed = arguments[0], from = arguments[1];
var changes = [];
for (var v = 9; v >= 5; v--) {
  changes.push({ version: '9.0.' + v, title: 'Invented release ' + v,
                 notes: '## What changed\\n- An invented line for ' + v, url: '' });
}
var realFetch = window.fetch;
window.fetch = function (url, opts) {
  if (String(url).indexOf('/api/update') === 0 && String(url).indexOf('/status') < 0) {
    return Promise.resolve({ ok: true, json: function () {
      return Promise.resolve({ ok: true, changed: true, previousVersion: from,
                               newVersion: landed, commits: 3, steps: ['Invented step'] });
    } });
  }
  return realFetch.apply(window, arguments);
};
var panel = document.querySelector('#wdAboutModal .wd-update-panel');
WD.Updater.mount(panel, { localVersion: from, latestVersion: '9.0.9',
                          latestUrl: '', changes: changes, changesTruncated: false });
return true;
"""

HAS_GO = """
return !!document.querySelector('#wdAboutModal .wd-update-goBtn');
"""

GO = """
document.querySelector('#wdAboutModal .wd-update-goBtn').click();
return true;
"""

RESTART_READY = """
return !!document.querySelector('#wdAboutModal .wd-update-restartBtn');
"""

READ = """
var q = function (s) { return document.querySelector('#wdAboutModal .wd-update-body ' + s); };
var btn = q('.wd-update-restartBtn');
var box = q('.wd-update-changes');
var link = q('a.wd-about-updateLink');
var vers = [].map.call(document.querySelectorAll('#wdAboutModal .wd-update-changes .rc-ver'),
                       function (e) { return e.textContent; });
return {
  restart: !!btn,
  head: box && box.querySelector('.rc-head') ? box.querySelector('.rc-head').textContent : null,
  versions: vers,
  boxHidden: box ? box.hidden : null,
  notesAfterButton: !!(btn && box && (btn.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING)),
  history: link ? link.href : null
};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheRestartScreenListsWhatWasInstalled(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import server
        server.updater.detect_install.return_value = {
            "method": "zip", "isGitInstall": False, "isDevCheckout": False,
            "currentVersion": "9.0.4", "reason": "Invented install."}

    def finish_an_update(self, drv, landed):
        drv.set_window_size(1366, 768)
        drv.get(self.base + "/cloud")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return typeof window.wdOpenAbout === 'function' && !!window.WD && !!WD.Updater;"))
        drv.execute_script(PREPARE)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(IDLE))
        drv.execute_script(MOUNT, landed, "9.0.4")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(HAS_GO))
        drv.execute_script(GO)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(RESTART_READY))
        if landed != "9.0.4":
            WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                "return document.querySelectorAll('#wdAboutModal .wd-update-changes .rc-item').length > 0"))
        return drv.execute_script(READ)

    def test_the_notes_are_listed_under_the_restart_button(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.finish_an_update(drv, "9.0.9")
                self.assertTrue(m["restart"], m)
                self.assertEqual(m["versions"], ["v9.0.9", "v9.0.8", "v9.0.7", "v9.0.6", "v9.0.5"], m)
                self.assertTrue(m["notesAfterButton"], m)
                self.assertIn("in this update", m["head"], m)
                self.assertNotIn("since your version", m["head"], m)
                self.assertTrue(m["history"] and m["history"].endswith("/releases"), m)

    def test_a_release_newer_than_the_one_installed_is_not_listed(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.finish_an_update(drv, "9.0.8")
                self.assertEqual(m["versions"], ["v9.0.8", "v9.0.7", "v9.0.6", "v9.0.5"], m)

    def test_a_pull_that_moved_no_version_lists_nothing(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.finish_an_update(drv, "9.0.4")
                self.assertTrue(m["restart"], m)
                self.assertEqual(m["versions"], [], m)
                self.assertIsNone(m["history"], m)


if __name__ == "__main__":
    unittest.main()
