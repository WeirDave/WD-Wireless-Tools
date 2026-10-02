"""The live log is filed under the day it was written, not the day the app started.

The handler began every run believing the live file was today's. An app
started once a month - or daily and never left running past midnight - kept
appending to the same live file for good: it was never rolled, so never
pruned, and the seven-day window did not apply to the one file that holds
real paths. The day now comes from the file's own modification time.
"""
from __future__ import annotations

import logging
import os
import time
import unittest
from datetime import date, timedelta

from tools import applog
from tests.test_applog import _Isolated


class AnOldLiveFileIsRolledTests(_Isolated):

    def leave_live_file(self, days_ago: int, text: str):
        path = applog.log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        when = time.time() - days_ago * 86400
        os.utime(path, (when, when))
        return path

    def first_line_of_this_run(self):
        applog.install(app_version="0.0.0-test")
        applog.get_logger().warning("this run")
        for handler in logging.getLogger().handlers:
            handler.flush()

    def files(self):
        return sorted(p.name for p in applog.log_dir().iterdir())

    def test_a_month_old_live_file_is_pruned(self):
        self.leave_live_file(30, "an old failure naming D:\\Invented\\Path\n")

        self.first_line_of_this_run()

        self.assertFalse("an old failure" in self.text())
        self.assertTrue("this run" in self.text())
        self.assertEqual(self.files(), [applog.LOG_FILE_NAME])

    def test_a_recent_live_file_is_filed_under_its_own_day_and_kept(self):
        self.leave_live_file(3, "three days ago\n")

        self.first_line_of_this_run()

        day = (date.today() - timedelta(days=3)).isoformat()
        archived = applog.log_dir() / f"wd-wireless-tools.{day}.log"
        self.assertTrue(archived.exists(), self.files())
        self.assertEqual(archived.read_text(encoding="utf-8"), "three days ago\n")
        self.assertFalse("three days ago" in self.text())

    def test_a_live_file_from_today_is_continued(self):
        self.leave_live_file(0, "earlier today\n")

        self.first_line_of_this_run()

        self.assertTrue(self.text().startswith("earlier today\n"))
        self.assertEqual(self.files(), [applog.LOG_FILE_NAME])


if __name__ == "__main__":
    unittest.main()
