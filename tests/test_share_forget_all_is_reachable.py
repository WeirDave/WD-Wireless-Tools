"""The share panel's "Forget all" reaches the server, and only after a yes.

`forget_all_recipients` was routed on the server and offered by nothing: the
remembered-address list could be cleared one address at a time and never as a
whole. The control is the one this test renders with the real
`_shareRecentRender`, pulls the handler back out of the markup and runs - the
real `_shareForgetAll` against a recorder for `pyApi`, `confirm` and `toast`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delegated import DELEGATED_JS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  if (a < 0) throw new Error('could not find ' + from);
  const b = source.indexOf(to, a);
  if (b < 0) throw new Error('could not find ' + to);
  return source.slice(a, b);
}
const block = slice('function _shareRecentRender()', '\nasync function _shareForget(email)');

const WD = {
  esc: s => String(s == null ? '' : s),
  escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;')
    .replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;'),
};
const host = { hidden: true, innerHTML: '' };
const document = { getElementById: id => (id === 'shareRecent' ? host : null) };
const calls = [], toasts = [], confirms = [];
let answer = true, reply = { ok: true, recipients: [] }, hid = 0;
const pyApi = async (...a) => { calls.push(a); return reply; };
const toast = (m, k) => toasts.push(String(m));
const confirm = (m) => { confirms.push(String(m)); return answer; };

const api = new Function('WD', 'document', '_shareChips', 'pyApi', 'toast', 'confirm',
  '_shareSuggestHide',
  'let _shareKnown = [];\n' + block +
  '\nreturn { render: _shareRecentRender, forgetAll: _shareForgetAll,' +
  ' known: () => _shareKnown, setKnown: v => { _shareKnown = v; } };')(
  WD, document, [], pyApi, toast, confirm, () => { hid++; });

(async () => {
  const out = {};
  api.setKnown([{ email: 'a@example.test' }, { email: 'b@example.test' }]);
  api.render();
  const hit = delegated(host.innerHTML, '_shareForgetAll');
  out.offered = !!hit;
  out.offeredAfterEachAddress =
    host.innerHTML.indexOf('_shareForgetAll') > host.innerHTML.lastIndexOf('_shareForget"');

  // declined
  answer = false;
  await api.forgetAll.apply(null, hit.args);
  out.declinedCalls = calls.length;
  out.declinedKept = api.known().length;

  // accepted
  answer = true;
  await api.forgetAll.apply(null, hit.args);
  out.acceptedCalls = calls.map(c => c[0]);
  out.acceptedKnown = api.known().length;
  out.hiddenAfter = host.hidden;
  out.askedAboutShares = /stay shared/.test(confirms[confirms.length - 1]);

  // refused by the server
  calls.length = 0; toasts.length = 0;
  api.setKnown([{ email: 'a@example.test' }]);
  reply = { ok: false, error: 'Could not clear the list.' };
  await api.forgetAll();
  out.failedKept = api.known().length;
  out.failedToast = toasts.slice();
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ForgetAllTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        script = DELEGATED_JS + NODE_SCRIPT
        proc = subprocess.run(["node", "-e", script, str(CLOUD_JS)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=120)
        if proc.returncode != 0:
            raise AssertionError((proc.stdout + proc.stderr).strip())
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])

    def test_the_panel_offers_it(self):
        self.assertTrue(self.out["offered"])

    def test_declining_the_question_changes_nothing(self):
        self.assertEqual(0, self.out["declinedCalls"])
        self.assertEqual(2, self.out["declinedKept"])

    def test_a_yes_clears_the_list_through_the_server(self):
        self.assertEqual(["forget_all_recipients"], self.out["acceptedCalls"])
        self.assertEqual(0, self.out["acceptedKnown"])
        self.assertTrue(self.out["hiddenAfter"])

    def test_the_question_says_projects_already_shared_stay_shared(self):
        self.assertTrue(self.out["askedAboutShares"])

    def test_a_failure_keeps_the_list_and_says_why(self):
        self.assertEqual(1, self.out["failedKept"])
        self.assertEqual(["Could not clear the list."], self.out["failedToast"])


if __name__ == "__main__":
    unittest.main()
