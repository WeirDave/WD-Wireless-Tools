"""The saved report file name ends with the project.

    Report - AP Installation - v2.0 - Silicone Plus - Building 4 - 1200 Fake Rd

The project is the name of the **folder** the .esx was opened from, when that
can be known. That is where a project name actually lives in practice: the job
is kept in a folder called after the client, the building and the address, and
the file inside it is called after the site or the discipline. Naming the report
after the folder is what someone does by hand, and doing it by hand on every
save is what this replaces.

The folder is only knowable through the native picker. A browser file input -
which is what drag-and-drop and the hosted build both use - hands over a bare
file name with no path at all, so there the .esx stem answers instead:

    Report - AP Installation - v2.0 - 4653 Denrose Ct, Fort Collins, CO 80524 - PD

The project segment has gone missing once already (fixed in v2.33.0) and been
reported missing a second time, which is what this file exists to stop. There
was no test on it: v2.33.0 was verified by looking at the title bar, and looking
at something once does not keep it there.

The name is assembled in exactly one place - buildDocTitle - and every save path
reaches it through reportDocTitle -> document.title, which is what the browser
offers in the Save-as-PDF dialog. If a second assembler ever appears, the
segment can go missing on one path while every test here still passes, so
test_only_one_place_assembles_the_name guards that too.

These run the real functions rather than reading the source, and they use the
project names actually in use - long, comma-heavy, with an address and a
trailing discipline code - because those are what a naive sanitiser breaks.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block =
    slice('function fileSafe(part)', '\n  function currentRevisionValue')
  + slice('function currentRevisionValue()', '\n  /* The saved file name');

// What the sliced-out functions reach for from the rest of the page.
globalThis.fileName = '';
globalThis.projectFolder = '';
globalThis.proj = { projectName: '' };
globalThis.currentOpts = {};
globalThis.reportSettings = {};
globalThis.settingDefault = (id) => globalThis.reportSettings[id] || '';
globalThis.currentReport = () => ({ docName: globalThis.docName || 'AP Installation' });
globalThis.includeRevisionInName = true;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  if (got !== want) failures.push(what + '\n     got:  ' + got + '\n     want: ' + want);
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_block(checks: str, source: Path = REPORT_JS) -> subprocess.CompletedProcess:
    program = PRELUDE + "eval(block + " + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(source)],
                              capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ReportFileName(unittest.TestCase):
    def check(self, checks: str):
        result = run_block(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_the_project_is_the_last_segment(self):
        """The whole of the reported bug, in one assertion."""
        self.check("""
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = 'v2.0';
          eq('the saved name lost the project', reportDocTitle(),
             'Report - AP Installation - v2.0 - '
             + '4653 Denrose Ct, Fort Collins, CO 80524 - PD');
          done();
        """)

    def test_the_folder_wins_over_the_file_name(self):
        """The whole point of the change.

        His folder says what the job is; the file inside says which site or
        which discipline. They are different strings and he wants the first.
        """
        self.check("""
          projectFolder = 'Silicone Plus - Building 4 - 1200 Fake Rd';
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = 'v2.0';
          eq('the file name was used instead of the folder', reportDocTitle(),
             'Report - AP Installation - v2.0 - Silicone Plus - Building 4 - 1200 Fake Rd');
          eq('the preview would name the wrong source',
             projectNameSource().from, 'the folder it was opened from');
          done();
        """)

    def test_no_folder_falls_back_to_the_file_name(self):
        """Drag-and-drop and the hosted build, where there is no path to read.

        This is not a rare corner - it is every load that does not go through
        the native picker, and it must keep behaving exactly as it did before
        the folder existed as a source.
        """
        self.check("""
          projectFolder = '';
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = 'v2.0';
          eq('a drop lost the project', reportDocTitle(),
             'Report - AP Installation - v2.0 - '
             + '4653 Denrose Ct, Fort Collins, CO 80524 - PD');
          eq('the preview would name the wrong source',
             projectNameSource().from, 'the .esx file name');
          done();
        """)

    def test_a_folder_that_says_nothing_is_not_used(self):
        """Downloads is where a file sits, not what the job is called.

        Matched whole, so a real folder that merely starts with one of these
        words still counts - "Downtown Campus" is a project, "Downloads" is
        not.
        """
        self.check("""
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = '';
          ['Downloads', 'Desktop', 'Documents', 'OneDrive', 'Dropbox',
           'New Folder (2)', 'temp', 'ESX', 'Ekahau Projects', ''].forEach(function (f) {
            projectFolder = f;
            const t = reportDocTitle();
            check('"' + f + '" was treated as a project name: ' + t,
                  t === 'Report - AP Installation - '
                      + '4653 Denrose Ct, Fort Collins, CO 80524 - PD');
          });
          ['Downtown Campus', 'Project Falcon', 'Documents Warehouse'].forEach(function (f) {
            projectFolder = f;
            check('"' + f + '" was rejected as generic',
                  reportDocTitle().indexOf(f) > -1);
          });
          done();
        """)

    def test_a_folder_name_keeps_its_punctuation(self):
        """His folders are "client - building - address". Every one of those
        separators and commas is meaning, not noise."""
        self.check("""
          projectFolder = 'Silicone Plus, Bldg 4 - 1200 Fake Rd, Suite 200';
          fileName = 'whatever.esx';
          currentOpts.revision = 'v1.0';
          const t = reportDocTitle();
          check('punctuation was stripped from the folder: ' + t,
                t.indexOf('Silicone Plus, Bldg 4 - 1200 Fake Rd, Suite 200') > -1);
          done();
        """)

    def test_commas_and_addresses_survive(self):
        """A file name is not a slug. Commas, digits and a trailing discipline
        code are all legal on both platforms and all carry meaning here."""
        self.check("""
          fileName = 'LNBH1 - LGB-03 - 3435 E Conant St, Long Beach, CA 90806 - B20 - PD.esx';
          currentOpts.revision = 'v1.3';
          const t = reportDocTitle();
          check('the address was mangled: ' + t,
                t.indexOf('3435 E Conant St, Long Beach, CA 90806') > -1);
          check('the trailing code was dropped: ' + t, /- B20 - PD$/.test(t));
          done();
        """)

    def test_turning_the_version_off_keeps_the_project(self):
        """The two options are independent, and the segment order is the point
        of the report: the project stays last either way."""
        self.check("""
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = 'v2.0';

          includeRevisionInName = true;
          eq('with the version', reportDocTitle(),
             'Report - AP Installation - v2.0 - 4653 Denrose Ct, Fort Collins, CO 80524 - PD');

          includeRevisionInName = false;
          eq('without the version', reportDocTitle(),
             'Report - AP Installation - 4653 Denrose Ct, Fort Collins, CO 80524 - PD');
          done();
        """)

    def test_a_blank_version_leaves_no_dangling_separator(self):
        self.check("""
          fileName = 'Denrose.esx';
          currentOpts.revision = '';
          eq('an empty piece left its separator behind', reportDocTitle(),
             'Report - AP Installation - Denrose');
          done();
        """)

    def test_every_report_type_keeps_the_project(self):
        """The name is built from the report's docName, and there are a dozen
        reports. One of them getting a different assembler is exactly how this
        would break a third time."""
        self.check("""
          fileName = '4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx';
          currentOpts.revision = 'v2.0';
          ['AP Installation', 'Antenna Aim Sheet', 'AP Placement Map',
           'Site Survey Summary'].forEach(function (name) {
            docName = name;
            const t = reportDocTitle();
            check('"' + name + '" lost the project: ' + t,
                  /4653 Denrose Ct, Fort Collins, CO 80524 - PD$/.test(t));
            check('"' + name + '" lost the version: ' + t, t.indexOf(' - v2.0 - ') > -1);
          });
          done();
        """)

    def test_a_name_that_says_nothing_defers_to_the_project_file(self):
        """"final.esx" is not a project name; "Final Report Denrose.esx" is.
        The fallback is matched whole for that reason."""
        self.check("""
          proj.projectName = 'Denrose Court';
          currentOpts.revision = 'v1.0';

          fileName = 'final.esx';
          eq('a placeholder name was used as the project', reportDocTitle(),
             'Report - AP Installation - v1.0 - Denrose Court');

          fileName = 'Final Denrose Ct - PD.esx';
          eq('a real name starting with a placeholder word was thrown away',
             reportDocTitle(),
             'Report - AP Installation - v1.0 - Final Denrose Ct - PD');
          done();
        """)

    def test_illegal_characters_are_replaced_not_truncated_at(self):
        """A colon is legal in an Ekahau project name and illegal in a Windows
        file name. Replacing it keeps the rest of the name; stopping at it would
        silently amputate everything after."""
        self.check("""
          fileName = 'Site: Denrose / Phase 2.esx';
          currentOpts.revision = '';
          const t = reportDocTitle();
          check('the name was cut at the illegal character: ' + t,
                t.indexOf('Denrose') > -1 && t.indexOf('Phase 2') > -1);
          check('an illegal character reached the file name: ' + t,
                !/[<>:"/\\\\|?*]/.test(t));
          done();
        """)


class FileNameAssembly(unittest.TestCase):
    """Structural guards - one builder, reached from every save path."""

    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def test_only_one_place_assembles_the_name(self):
        """Parallel derivations of one value is this repository's recurring
        fault - three ordinal computations in the AP labeller, two staleness
        computations in Cloud Manager. A second name assembler would let the
        segment go missing on one path with every test above still green."""
        self.assertEqual(self.js.count("function buildDocTitle("), 1)
        self.assertEqual(self.js.count("['Report', docName"), 1,
                         "the segment list belongs to buildDocTitle alone")
        callers = self.js.count("buildDocTitle(")
        self.assertLessEqual(callers, 4,
                             "buildDocTitle should be reached from the doc "
                             "title and the settings preview, nothing else")

    def test_the_title_is_written_from_that_one_builder(self):
        """document.title is what the browser offers in the save dialog, so it
        is the file name in all but name."""
        for line in self.js.splitlines():
            if "document.title =" in line:
                with self.subTest(line=line.strip()):
                    self.assertIn("reportDocTitle()", line,
                                  "a title set from anything else bypasses "
                                  "the one builder")

    def test_the_title_is_refreshed_before_printing(self):
        """It was set once, after a successful render, which left it stale on
        every path that returned early."""
        start = self.js.index("window.printReport = async function ()")
        body = self.js[start:self.js.index("window.print()", start)]
        self.assertIn("syncDocTitle()", body)


class OpenEsxRoute(unittest.TestCase):
    """The endpoint that makes the folder knowable at all.

    Report parses the archive in the browser, so it needs the bytes; the native
    picker only returns a path. This route is the join, and the folder name
    rides back on a header because a Blob cannot carry one.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(ROOT))
        from server import app, API_REQUEST_HEADER
        app.config.update(TESTING=True)
        cls.client = app.test_client()
        cls.header = {API_REQUEST_HEADER: "1"}

    def setUp(self):
        import tempfile, zipfile
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-fname-"))
        folder = self.tmp / "Silicone Plus - Building 4 - 1200 Fake Rd"
        folder.mkdir()
        self.esx = folder / "4653 Denrose Ct, Fort Collins, CO 80524 - PD.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", "{}")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_it_returns_the_bytes_and_names_the_folder(self):
        r = self.client.post("/api/report/open_esx",
                             json={"path": str(self.esx)}, headers=self.header)
        try:
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.data[:2], b"PK", "that is not a zip")
            self.assertEqual(unquote(r.headers["X-WD-Project-Folder"]),
                             "Silicone Plus - Building 4 - 1200 Fake Rd")
            self.assertEqual(unquote(r.headers["X-WD-File-Name"]), self.esx.name)
        finally:
            r.close()

    def test_the_header_survives_commas_and_spaces(self):
        """HTTP headers are latin-1 and these are real folder names. They are
        percent-encoded rather than sent raw, and the page decodes them."""
        r = self.client.post("/api/report/open_esx",
                             json={"path": str(self.esx)}, headers=self.header)
        try:
            raw = r.headers["X-WD-Project-Folder"]
            self.assertNotIn(" ", raw, "an un-encoded space would break the header")
            self.assertIn("%20", raw)
        finally:
            r.close()

    def test_it_refuses_what_is_not_a_project(self):
        """The path comes from the client, so it is checked rather than
        trusted - and a stale path should read as a sentence, not a
        traceback."""
        other = self.tmp / "notes.txt"
        other.write_text("hello", encoding="utf-8")
        for label, payload, code in (
            ("not an .esx", {"path": str(other)}, 400),
            ("missing", {"path": str(self.tmp / "gone.esx")}, 404),
            ("nothing", {}, 400),
        ):
            with self.subTest(label=label):
                r = self.client.post("/api/report/open_esx", json=payload,
                                     headers=self.header)
                try:
                    self.assertEqual(r.status_code, code)
                    self.assertIn("error", r.get_json())
                finally:
                    r.close()


if __name__ == "__main__":
    unittest.main()
