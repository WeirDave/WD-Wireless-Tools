"""Report options are settings, and they leave with the settings.

He was clear about this: "Report options should absolutely be saved. They
should go in with the rest of the settings." They are - `report.report_defaults`
in `settings.json`, registered in `web/assets/settings-registry.json` like
every other preference - and this holds the part nobody would notice was
missing until they needed it: that an export carries them and an import puts
them back.

The reason it is worth a test of its own rather than trusting "settings.json
is exported wholesale": `report_defaults` is a nested map keyed by report, and
`update_settings` merges rather than replaces. A merge rule that treated it as
a scalar would silently drop every report but the last on the way in.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
import json, sys
from tools import settings, settings_backup

# what someone would actually have saved: two reports, different options
settings.update_settings({"report": {"report_defaults": {
    "placement": {"shortLabels": True, "inclOmni": False, "compassRef": "never"},
    "bom": {"externalOnly": True},
}}})

bundle = settings_backup.export_bundle(browser={})
exported = ((bundle.get("settings") or {}).get("report") or {}).get("report_defaults")

# wipe, the way a fresh machine or a reset looks
settings.update_settings({"report": {"report_defaults": {}}})
after_wipe = settings.load_settings()["report"]["report_defaults"]

settings_backup.apply_import(bundle, sections=("settings",))
restored = settings.load_settings()["report"]["report_defaults"]

print(json.dumps({"exported": exported, "afterWipe": after_wipe,
                  "restored": restored}))
"""


class ReportOptionsAreInTheSettings(unittest.TestCase):
    def test_they_export_and_come_back(self):
        with tempfile.TemporaryDirectory(prefix="wd-optexport-") as tmp:
            env = dict(os.environ)
            env["WD_USER_DIR"] = tmp
            env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
            r = subprocess.run([sys.executable, "-c", PROBE], capture_output=True,
                               text=True, cwd=str(ROOT), env=env, timeout=180)
            self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())
            import json
            got = json.loads(r.stdout.strip().splitlines()[-1])

        self.assertEqual(
            got["exported"],
            {"placement": {"shortLabels": True, "inclOmni": False,
                           "compassRef": "never"},
             "bom": {"externalOnly": True}},
            "the export dropped or flattened the per-report options")
        self.assertEqual(got["afterWipe"], {},
                         "the wipe did not actually clear them, so the restore "
                         "below proves nothing")
        self.assertEqual(got["restored"], got["exported"],
                         "an import did not put the report options back")


class TheyAreRegisteredLikeEverythingElse(unittest.TestCase):
    def test_the_registry_knows_about_them(self):
        import json
        reg = json.loads((ROOT / "web" / "assets" / "settings-registry.json")
                         .read_text(encoding="utf-8"))
        flat = json.dumps(reg)
        self.assertIn("report.report_defaults", flat,
                      "a setting that is not in the registry is a setting "
                      "nobody can find - see CLAUDE.md")


if __name__ == "__main__":
    unittest.main()
