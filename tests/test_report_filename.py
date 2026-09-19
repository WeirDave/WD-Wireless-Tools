"""The saved report file name is the report, then the site.

    AP Placement Map - Northwind Traders - Building 4 - 1200 Fake Rd

The site is the name of the **folder** the .esx was opened from. That is where
a project name actually lives in practice: the job is kept in a folder called
after the client, the building and the address, and the file inside it is
called after the site or the discipline. Naming the report after the folder is
what someone does by hand, and doing it by hand on every save is what this
replaces.

That name was asked for three times and delivered none of them, and each miss
is a rule below. It led with the literal word "Report", which says nothing the
report name does not already say and files every report in the folder under R.
It put the revision third, between the report name and the site. And it
appended the .esx stem after the folder, on the reading that the stem carried a
discipline worth keeping - so the name ran on past the site into a repeat of
most of it.

When the folder cannot be known the .esx stem answers instead:

    AP Placement Map - 400 Example St, Fairview, CA 90003 - PD

That used to be every drag-and-drop, because a browser file input hands over a
bare file name with no path at all - and the drop zone is the front page of the
tool, so most reports were named without their site. The bytes are on the
machine either way, so the folder is now looked up server-side; see
ADroppedFileFindsItsFolder below and report_store.locate_project_folder.

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

    def test_the_name_is_the_report_then_the_site(self):
        """The whole of the reported bug, in one assertion.

        Asked for three times: "AP Placement - {Site Name}.pdf". The site
        follows the report name directly, with nothing in between.
        """
        self.check("""
          docName = 'AP Placement Map';
          projectFolder = 'Northwind Traders - Building 4 - 1200 Fake Rd';
          fileName = 'B04 - PD.esx';
          currentOpts.revision = '';
          eq('the name is not <report> - <site>', reportDocTitle(),
             'AP Placement Map - Northwind Traders - Building 4 - 1200 Fake Rd');
          done();
        """)

    def test_nothing_is_put_in_front_of_the_report_name(self):
        """It used to lead with the literal word "Report", which says nothing
        the report name does not and files every report in the folder under R."""
        self.check("""
          projectFolder = 'Northwind Traders - Building 4';
          fileName = 'B04 - PD.esx';
          currentOpts.revision = 'v2.0';
          ['AP Installation', 'Antenna Aim Sheet', 'AP Placement Map',
           'Bill of Materials'].forEach(function (name) {
            docName = name;
            const t = reportDocTitle();
            check('"' + name + '" does not lead the name: ' + t,
                  t.indexOf(name) === 0);
          });
          done();
        """)

    def test_the_project_is_the_last_segment(self):
        """No revision typed, which is the ordinary case - so the site really is
        last, and a folder of reports sorts by report and then by site."""
        self.check("""
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = '';
          eq('the saved name lost the project', reportDocTitle(),
             'AP Installation - 400 Example St, Fairview, CA 90003 - PD');
          done();
        """)

    def test_the_folder_is_the_whole_site_and_the_stem_is_dropped(self):
        """The folder is the site, and when it is known it is the whole answer.

        This used to join the folder and the .esx stem with a dash, on the
        reading that the stem carried a discipline worth keeping. The name
        asked for is "<report name> - <site>" and nothing else, so the stem
        goes: it repeats most of the folder, and the part it does not repeat
        belongs to the file rather than to the sheet someone is handed.
        """
        self.check("""
          projectFolder = 'Northwind Traders - Building 4 - 1200 Fake Rd';
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = '';
          eq('the .esx stem is still in the name', reportDocTitle(),
             'AP Installation - Northwind Traders - Building 4 - 1200 Fake Rd');
          eq('the preview would name the wrong source',
             projectNameSource().from, 'the folder it was opened from');
          done();
        """)

    def test_the_folder_wins_however_the_two_names_relate(self):
        """One folder per job, with the .esx inside named after the site, the
        discipline, or the same thing again. Every shape gives one answer now,
        and that answer is the folder."""
        self.check("""
          currentOpts.revision = '';
          projectFolder = 'SITE1 - BLD-03';
          ['SITE1 - BLD-03.esx', 'SITE1 - BLD-03 - PD.esx', 'PD.esx',
           'Survey final.esx'].forEach(function (f) {
            fileName = f;
            eq('"' + f + '" changed the site', reportDocTitle(),
               'AP Installation - SITE1 - BLD-03');
          });
          done();
        """)

    def test_a_skipped_folder_is_named_so_it_can_be_asked_about(self):
        """Twenty of his projects sit directly in a folder called after the
        software rather than the job, so the folder is dropped and the name
        looks as though the feature is not working. The rule is invisible;
        this is what makes it sayable on screen."""
        self.check("""
          projectFolder = 'Ekahau Projects';
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          const src = projectNameSource();
          eq('the generic folder leaked into the name', src.name,
             '400 Example St, Fairview, CA 90003 - PD');
          eq('the page cannot say which folder it ignored',
             src.skippedFolder, 'Ekahau Projects');
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
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = 'v2.0';
          eq('a drop lost the project', reportDocTitle(),
             'AP Installation - 400 Example St, Fairview, CA 90003 - PD - v2.0');
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
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = '';
          ['Downloads', 'Desktop', 'Documents', 'OneDrive', 'Dropbox',
           'New Folder (2)', 'temp', 'ESX', 'Ekahau Projects', ''].forEach(function (f) {
            projectFolder = f;
            const t = reportDocTitle();
            check('"' + f + '" was treated as a project name: ' + t,
                  t === 'AP Installation - '
                      + '400 Example St, Fairview, CA 90003 - PD');
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
          projectFolder = 'Northwind Traders, Bldg 4 - 1200 Fake Rd, Suite 200';
          fileName = 'whatever.esx';
          currentOpts.revision = 'v1.0';
          const t = reportDocTitle();
          check('punctuation was stripped from the folder: ' + t,
                t.indexOf('Northwind Traders, Bldg 4 - 1200 Fake Rd, Suite 200') > -1);
          done();
        """)

    def test_commas_and_addresses_survive(self):
        """A file name is not a slug. Commas, digits and a trailing discipline
        code are all legal on both platforms and all carry meaning here."""
        self.check("""
          fileName = 'SITE1 - BLD-03 - 100 Example Ave, Springfield, WA 90000 - B10 - PD.esx';
          currentOpts.revision = 'v1.3';
          const t = reportDocTitle();
          check('the address was mangled: ' + t,
                t.indexOf('100 Example Ave, Springfield, WA 90000') > -1);
          check('the trailing code was dropped: ' + t,
                /- B10 - PD - v1[.]3$/.test(t));
          done();
        """)

    def test_turning_the_version_off_keeps_the_project(self):
        """The two options are independent, and the segment order is the point
        of the report: the project stays last either way."""
        self.check("""
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = 'v2.0';

          includeRevisionInName = true;
          eq('with the version', reportDocTitle(),
             'AP Installation - 400 Example St, Fairview, CA 90003 - PD - v2.0');

          includeRevisionInName = false;
          eq('without the version', reportDocTitle(),
             'AP Installation - 400 Example St, Fairview, CA 90003 - PD');
          done();
        """)

    def test_a_blank_version_leaves_no_dangling_separator(self):
        self.check("""
          fileName = 'Example.esx';
          currentOpts.revision = '';
          eq('an empty piece left its separator behind', reportDocTitle(),
             'AP Installation - Example');
          done();
        """)

    def test_every_report_type_keeps_the_project(self):
        """The name is built from the report's docName, and there are a dozen
        reports. One of them getting a different assembler is exactly how this
        would break a third time.

        The project sits between the report name and the version here, because
        a version is typed: the version is a suffix on a finished name rather
        than a segment in the middle of one."""
        self.check("""
          fileName = '400 Example St, Fairview, CA 90003 - PD.esx';
          currentOpts.revision = 'v2.0';
          ['AP Installation', 'Antenna Aim Sheet', 'AP Placement Map',
           'Site Survey Summary'].forEach(function (name) {
            docName = name;
            const t = reportDocTitle();
            check('"' + name + '" lost the project: ' + t,
                  t.indexOf('400 Example St, Fairview, CA 90003 - PD') > -1);
            check('"' + name + '" lost the version: ' + t, /- v2[.]0$/.test(t));
          });
          done();
        """)

    def test_a_name_that_says_nothing_defers_to_the_project_file(self):
        """"final.esx" is not a project name; "Final Report Example.esx" is.
        The fallback is matched whole for that reason."""
        self.check("""
          proj.projectName = 'Example Court';
          currentOpts.revision = 'v1.0';

          fileName = 'final.esx';
          eq('a placeholder name was used as the project', reportDocTitle(),
             'AP Installation - Example Court - v1.0');

          fileName = 'Final Example St - PD.esx';
          eq('a real name starting with a placeholder word was thrown away',
             reportDocTitle(),
             'AP Installation - Final Example St - PD - v1.0');
          done();
        """)

    def test_illegal_characters_are_replaced_not_truncated_at(self):
        """A colon is legal in an Ekahau project name and illegal in a Windows
        file name. Replacing it keeps the rest of the name; stopping at it would
        silently amputate everything after."""
        self.check("""
          fileName = 'Site: Example / Phase 2.esx';
          currentOpts.revision = '';
          const t = reportDocTitle();
          check('the name was cut at the illegal character: ' + t,
                t.indexOf('Example') > -1 && t.indexOf('Phase 2') > -1);
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
        self.assertEqual(self.js.count("[docName, siteLabel"), 1,
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

    def test_picking_a_report_renames_the_tab_straight_away(self):
        """Measured in Firefox before this was true: choosing a report left the
        tab - and therefore Ctrl+P - naming the report you had picked *last*,
        all the way through the configure stage, until a render replaced it.
        Picking the aim sheet showed "AP Placement Map" until you generated.

        The app's own Print button was never wrong; it syncs first. This is the
        tab and the keyboard shortcut, which is why it is a rename rather than
        a wrong file.
        """
        start = self.js.index("window.selectReport = function (id)")
        body = self.js[start:self.js.index("\n  function ", start)]
        self.assertIn("syncDocTitle()", body,
                      "selectReport must refresh the title it just invalidated")
        self.assertLess(body.index("syncDocTitle()"), body.index("goStage("),
                        "refresh before leaving for the next stage")


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
        self.addCleanup(shutil.rmtree, self.tmp, True)
        folder = self.tmp / "Northwind Traders - Building 4 - 1200 Fake Rd"
        folder.mkdir()
        self.esx = folder / "400 Example St, Fairview, CA 90003 - PD.esx"
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
                             "Northwind Traders - Building 4 - 1200 Fake Rd")
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


DROP_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block =
    slice('function folderMissingReason()', '\n  // Shows both spellings')
  + slice('async function recoverProjectFolder(file)', '\n  async function loadFile');

globalThis.projectFolder = '';
globalThis.folderLookup = '';
globalThis.settingsAvailable = true;
globalThis.calls = [];
globalThis.WD = { api: async function (action, body) {
  calls.push([action, body]);
  return globalThis.answer;
} };

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


def run_drop(checks: str) -> subprocess.CompletedProcess:
    """The checks are awaited, so the exit has to be awaited with them.

    Written without the trailing done() and the rejection handler, every test
    in this class exited 0 whatever it had recorded: node reached the end of
    the script while the IIFE was still pending, and the failures list was
    never read. Mutating the code under test is what found it - four
    deliberate breakages stayed green. Both lines below are load-bearing.
    """
    program = (DROP_PRELUDE + "eval(block);\n(async function () {\n"
               + checks + "\ndone();\n})().catch(function (e) {\n"
               + "  console.error((e && e.stack) || e); process.exit(1);\n});")
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ADroppedFileFindsItsFolder(unittest.TestCase):
    """The drop zone is the front page, and a drop has no path in it.

    Every report opened by dropping a file was therefore named without its
    site, which is most of them. These run the real recoverProjectFolder
    against a recording stub rather than checking that the source mentions it -
    a handler that is never reached, or reached with the wrong fields, looks
    identical from the source and produces the same wrong file name.
    """

    def check(self, checks: str):
        result = run_drop(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_the_folder_comes_back_and_lands_in_the_name(self):
        self.check("""
          answer = { ok: true, folder: 'Northwind Traders - Building 4' };
          await recoverProjectFolder({ name: 'B04 - PD.esx', size: 40960 });
          eq('the folder was not taken', projectFolder,
             'Northwind Traders - Building 4');
          eq('a reason was left behind on success', folderLookup, '');
        """)

    def test_it_asks_the_right_endpoint_with_the_name_and_the_size(self):
        """The size is what makes the answer safe to use: two buildings
        surveyed from one template share a file name, and a wrong site on an
        installer's drawing is worse than no site."""
        self.check("""
          answer = { ok: true, folder: 'X' };
          await recoverProjectFolder({ name: 'B04 - PD.esx', size: 40960 });
          eq('the wrong endpoint was called', calls[0][0], 'report/find_folder');
          eq('the file name was not sent', calls[0][1].name, 'B04 - PD.esx');
          eq('the byte size was not sent', calls[0][1].size, 40960);
        """)

    def test_a_refusal_leaves_the_name_exactly_as_it_was(self):
        """Every way this can come back empty costs nothing: the .esx stem
        still answers, which is what happened before the lookup existed."""
        self.check("""
          [['not_found', 'not_found'], ['ambiguous', 'ambiguous'],
           ['no_root', 'no_root'], ['too_big', 'too_big']].forEach(function (p) {
            projectFolder = 'stale';
          });
          const reasons = ['not_found', 'ambiguous', 'no_root', 'too_big'];
          for (const reason of reasons) {
            projectFolder = '';
            answer = { ok: false, reason: reason };
            await recoverProjectFolder({ name: 'B04 - PD.esx', size: 1 });
            eq('"' + reason + '" invented a folder', projectFolder, '');
            eq('"' + reason + '" was not recorded', folderLookup, reason);
          }
        """)

    def test_no_server_and_a_thrown_call_are_both_survivable(self):
        """The hosted build has no server at all, and a server that errors must
        not stop the file being opened."""
        self.check("""
          settingsAvailable = false;
          projectFolder = '';
          await recoverProjectFolder({ name: 'B04 - PD.esx', size: 1 });
          eq('a call was made with no server', calls.length, 0);
          eq('no reason was recorded', folderLookup, 'no_server');

          settingsAvailable = true;
          WD.api = async function () { throw new Error('offline'); };
          await recoverProjectFolder({ name: 'B04 - PD.esx', size: 1 });
          eq('a thrown call was not survived', folderLookup, 'failed');
          eq('a thrown call invented a folder', projectFolder, '');
        """)

    def test_every_reason_says_what_to_do_about_it(self):
        """"The site is missing and I do not know why" is the state being
        fixed. Each reason names a way forward rather than stating a fact."""
        self.check("""
          const reasons = ['not_found', 'ambiguous', 'no_root', 'too_big',
                           'failed', 'no_server', ''];
          for (const reason of reasons) {
            folderLookup = reason;
            const why = folderMissingReason();
            check('"' + reason + '" says nothing: ' + why, why.length > 40);
            check('"' + reason + '" offers no way forward: ' + why,
                  why.indexOf('Open another') > -1 || why.indexOf('Settings') > -1);
          }
          folderLookup = 'no_root';
          check('a missing setting does not say where to set it',
                folderMissingReason().indexOf('Local project folder') > -1);
        """)

    def test_the_lookup_runs_only_when_the_folder_is_unknown(self):
        """The native picker already knows. Asking again would be a disk walk
        per file open, for an answer already in hand."""
        js = REPORT_JS.read_text(encoding="utf-8")
        start = js.index("async function loadFile(file, folderName)")
        body = js[start:js.index("await parseEsx();", start)]
        self.assertIn("if (!projectFolder) await recoverProjectFolder(file)", body)
        self.assertLess(body.index("projectFolder = folderName"),
                        body.index("recoverProjectFolder(file)"),
                        "the picker's answer must be taken first")


class LocateProjectFolder(unittest.TestCase):
    """The server half: which folder on disk a dropped .esx came from.

    It answers only when it is certain. Name *and* byte size must match, and a
    name found in two folders is refused rather than guessed at.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(ROOT))

    def setUp(self):
        import tempfile, zipfile
        from tools import report_store
        self.store = report_store
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-locate-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.site = self.tmp / "ACME2 - SITE-03 - 100 Example St, Springfield, IL 62701"
        self.site.mkdir()
        self.esx = self.site / "SITE-03 - B01 - PD.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", "{}")
        self.size = self.esx.stat().st_size
        real_root = report_store._lookup_root
        report_store._lookup_root = lambda: str(self.tmp)
        self.addCleanup(setattr, report_store, "_lookup_root", real_root)

    def test_a_single_match_names_its_folder(self):
        self.assertEqual(
            self.store.locate_project_folder(self.esx.name, self.size),
            {"ok": True, "folder": self.site.name})

    def test_only_the_folder_name_travels_back(self):
        """The page needs the folder name and nothing else, and a path is not
        something to hand out because it was asked for."""
        got = self.store.locate_project_folder(self.esx.name, self.size)
        self.assertNotIn("path", got)
        self.assertNotIn(str(self.tmp), repr(got))

    def test_a_different_file_of_the_same_name_is_not_a_match(self):
        """Same name, different bytes - a copy that has moved on. Matching on
        the name alone would put the wrong site on the sheet."""
        got = self.store.locate_project_folder(self.esx.name, self.size + 1)
        self.assertEqual(got, {"ok": False, "reason": "not_found"})

    def test_two_folders_with_the_same_project_are_refused(self):
        """One template surveyed into two buildings is a real shape here."""
        import shutil as _sh
        other = self.tmp / "ACME2 - SITE-04 - 200 Example St"
        other.mkdir()
        _sh.copy2(self.esx, other / self.esx.name)
        got = self.store.locate_project_folder(self.esx.name, self.size)
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "ambiguous")

    def test_the_same_project_found_twice_in_one_folder_is_still_one_answer(self):
        """A .esx and a copy of it side by side still came from one folder, so
        there is nothing ambiguous about the answer."""
        import shutil as _sh
        _sh.copy2(self.esx, self.site / ("Copy of " + self.esx.name))
        got = self.store.locate_project_folder("Copy of " + self.esx.name, self.size)
        self.assertEqual(got, {"ok": True, "folder": self.site.name})

    def test_an_unset_local_project_folder_says_so(self):
        self.store._lookup_root = lambda: ""
        self.assertEqual(self.store.locate_project_folder("x.esx", 1),
                         {"ok": False, "reason": "no_root"})

    def test_it_will_not_be_pointed_at_something_that_is_not_a_project(self):
        self.assertEqual(self.store.locate_project_folder("notes.pdf", 1),
                         {"ok": False, "reason": "not_a_project"})
        self.assertEqual(self.store.locate_project_folder("", 1),
                         {"ok": False, "reason": "not_a_project"})

    def test_the_walk_is_bounded_so_a_mis_set_root_cannot_hold_the_request(self):
        """A Local project folder pointing at the drive root has to come back
        with an answer, not sit there. The depth cap is what makes that true."""
        deep = self.tmp
        for part in ("a", "b", "c", "d", "e", "f"):
            deep = deep / part
        deep.mkdir(parents=True)
        import zipfile
        buried = deep / "Buried.esx"
        with zipfile.ZipFile(buried, "w") as z:
            z.writestr("project.json", "{}")
        got = self.store.locate_project_folder("Buried.esx", buried.stat().st_size)
        self.assertEqual(got, {"ok": False, "reason": "not_found"})

    def test_a_backups_folder_is_not_searched(self):
        """The suite files a copy aside under backups/ before it overwrites
        anything. Finding the backup would name the backup folder as the site."""
        import zipfile
        backups = self.tmp / "backups" / "Some Site"
        backups.mkdir(parents=True)
        name = "Only In Backups.esx"
        with zipfile.ZipFile(backups / name, "w") as z:
            z.writestr("project.json", "{}")
        size = (backups / name).stat().st_size
        self.assertEqual(self.store.locate_project_folder(name, size),
                         {"ok": False, "reason": "not_found"})


class FindFolderRoute(unittest.TestCase):
    """The endpoint the page reaches, with the real Flask app."""

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
        from tools import report_store
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-findroute-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        site = self.tmp / "Northwind Traders - Building 4 - 1200 Fake Rd"
        site.mkdir()
        self.esx = site / "B04 - PD.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", "{}")
        real_root = report_store._lookup_root
        report_store._lookup_root = lambda: str(self.tmp)
        self.addCleanup(setattr, report_store, "_lookup_root", real_root)

    def test_the_page_gets_the_folder_back(self):
        r = self.client.post("/api/report/find_folder",
                             json={"name": self.esx.name,
                                   "size": self.esx.stat().st_size},
                             headers=self.header)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(),
                         {"ok": True,
                          "folder": "Northwind Traders - Building 4 - 1200 Fake Rd"})

    def test_a_request_with_nothing_in_it_is_a_sentence_not_a_traceback(self):
        r = self.client.post("/api/report/find_folder", json={},
                             headers=self.header)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": False, "reason": "not_a_project"})
