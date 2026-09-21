"""What the server promises about its own responses, and about what it reads.

Four findings from the 2026-09-20 sweep, each small and each the sort that
survives a read-through because the line looks right:

* **A stored SVG was a document on this origin.** The report cover accepts
  SVG deliberately - a company logo usually is one - and `/api/report/cover`
  served it back with no policy on it. Through the `<img>` the report uses,
  a script inside it never runs; opened at that address directly, it runs
  with the origin that owns the Ekahau session, the project folder and the
  update endpoint.
* **Three `Content-Disposition` headers were built by interpolation** from a
  filename that arrives in a query parameter, so a double quote in it closed
  the field early - the attribute-escaping bug of v2.146.1, one layer down -
  and an accented project name could not travel at all.
* **There was no ceiling on a request body.** Four routes read the whole
  thing into memory before looking at it.
* **`.esx` archives were read without being looked at first.** An `.esx` is
  an untrusted archive by nature, and a few hundred kilobytes of deflate can
  carry gigabytes of zeroes into `json.loads`.

The limits are all set far above his real work rather than near it; a guard
that fires on a Monday morning is the failure this repository keeps writing
rules against.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server
from tools import esx_guard


class ResponseHeaders(unittest.TestCase):

    def setUp(self):
        self.client = server.app.test_client()

    def test_every_response_says_do_not_sniff_the_type(self):
        for path in ("/", "/settings", "/assets/versions.json"):
            with self.subTest(path=path):
                r = self.client.get(path)
                self.assertEqual("nosniff",
                                 r.headers.get("X-Content-Type-Options"))

    def test_the_default_policy_still_blocks_framing(self):
        r = self.client.get("/")
        self.assertIn("frame-ancestors 'none'",
                      r.headers.get("Content-Security-Policy", ""))
        self.assertEqual("DENY", r.headers.get("X-Frame-Options"))

    def test_a_route_may_set_a_stricter_policy_of_its_own(self):
        """`_no_cache` used to overwrite the header rather than set it.

        The cover route's whole defence is a policy of its own, and an
        `after_request` that clobbers it would have removed that silently -
        the route would still read as correct.
        """
        with mock.patch.object(server.report_store, "cover_path",
                               return_value=self._an_svg_on_disk()):
            r = self.client.get("/api/report/cover")
        policy = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    def _an_svg_on_disk(self):
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="wd-cover-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        p = d / "cover.svg"
        p.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>',
            encoding="utf-8")
        return p

    def test_a_stored_svg_cover_cannot_run_script(self):
        """The finding. A logo from somebody else is an ordinary upload."""
        with mock.patch.object(server.report_store, "cover_path",
                               return_value=self._an_svg_on_disk()):
            r = self.client.get("/api/report/cover")
        self.assertEqual(200, r.status_code)
        policy = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'none'", policy,
                      "an SVG cover is served with no policy stopping its "
                      "script from reaching this origin")
        self.assertIn("sandbox", policy)
        self.assertEqual("nosniff", r.headers.get("X-Content-Type-Options"))

    def test_the_cover_is_still_served(self):
        """The regression half: it has to remain a usable image."""
        with mock.patch.object(server.report_store, "cover_path",
                               return_value=self._an_svg_on_disk()):
            r = self.client.get("/api/report/cover")
        self.assertEqual(200, r.status_code)
        self.assertIn(b"<svg", r.data)


class TheAttachmentHeader(unittest.TestCase):
    """Built by a helper now, because it was built by interpolation."""

    def test_an_ordinary_name_survives(self):
        value = server._attachment("Riverside Campus (trimmed).esx")
        self.assertIn('filename="Riverside Campus (trimmed).esx"', value)

    def test_a_quote_cannot_close_the_field(self):
        """The finding: `?name=` reaches this header.

        `a" ; filename="b.exe` used to produce a header with two `filename`
        parameters, the browser taking whichever it read first.
        """
        value = server._attachment('a" ; filename="evil.exe')
        self.assertEqual(
            1, value.count('filename="'),
            "a quote in the name opened a second filename parameter: " + value)
        self.assertNotIn('"evil.exe"', value)

    def test_a_backslash_cannot_escape_out_of_it(self):
        value = server._attachment('a\\" x.esx')
        self.assertEqual(1, value.count('filename="'))

    def test_a_newline_never_reaches_the_header(self):
        """Werkzeug rejects one outright, so this must not produce one."""
        value = server._attachment("a\r\nX-Evil: 1")
        self.assertNotIn("\r", value)
        self.assertNotIn("\n", value)

    def test_an_accented_name_travels_intact(self):
        """Not a security fix - a header the browser could not read.

        `filename=` is Latin-1 only, so a project named with an accent came
        back mangled or dropped. The real name goes in `filename*`.
        """
        value = server._attachment("Café Nord (prepared).esx")
        self.assertIn("filename*=UTF-8''", value)
        self.assertIn("Caf%C3%A9", value)

    def test_an_empty_name_still_produces_a_filename(self):
        for empty in ("", None, "   "):
            with self.subTest(name=repr(empty)):
                self.assertIn('filename="', server._attachment(empty))

    def test_the_routes_go_through_it(self):
        """A fourth site built by hand would reopen this."""
        text = (ROOT / "server.py").read_text(encoding="utf-8")
        body = text.split("def _attachment", 1)[1].split("\n\n\n", 1)[1]
        self.assertNotIn('"Content-Disposition"] = (\n            f\'attachment',
                         body)
        self.assertEqual(
            3, body.count('headers["Content-Disposition"] = _attachment('),
            "a download route is building the header itself again")


class TheRequestCeiling(unittest.TestCase):

    def test_there_is_one(self):
        self.assertEqual(server.MAX_REQUEST_BYTES,
                         server.app.config["MAX_CONTENT_LENGTH"])

    def test_it_is_far_above_a_real_project(self):
        """His projects run to a couple of hundred megabytes.

        This is the assertion that stops somebody 'tightening' the limit to
        a number that refuses his Monday morning.
        """
        self.assertGreaterEqual(server.MAX_REQUEST_BYTES, 512 * 1024 * 1024)

    def test_going_over_it_answers_in_json(self):
        """Werkzeug's own 413 is an HTML page, which every page here renders
        as nothing at all."""
        client = server.app.test_client()
        with mock.patch.dict(server.app.config,
                             {"MAX_CONTENT_LENGTH": 1024}):
            r = client.post("/api/plantrim/analyze", data=b"x" * 4096,
                            headers={server.API_REQUEST_HEADER: "1"})
        self.assertEqual(413, r.status_code)
        body = r.get_json()
        self.assertFalse(body["ok"])
        self.assertIn("larger", body["error"])


def _zip_of(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            z.writestr(name, data)
    return buf.getvalue()


class TheArchiveGuard(unittest.TestCase):
    """`esx_guard.check`, against archives rather than against its source."""

    def setUp(self):
        import tempfile
        self.dir = Path(tempfile.mkdtemp(prefix="wd-guard-"))
        self.addCleanup(
            lambda: __import__("shutil").rmtree(self.dir, ignore_errors=True))

    def write(self, blob):
        p = self.dir / "in.esx"
        p.write_bytes(blob)
        return p

    def test_an_ordinary_project_passes(self):
        blob = _zip_of([
            ("project.json", json.dumps({"project": {"id": "x", "name": "Site"}})),
            ("floorPlans.json", json.dumps({"floorPlans": []})),
            ("image-1", b"\x89PNG\r\n\x1a\n" + b"\x00" * 200_000),
        ])
        esx_guard.check(self.write(blob))     # must not raise

    def test_a_zip_bomb_is_refused(self):
        """A megabyte on the wire, a gigabyte in memory."""
        blob = _zip_of([("project.json", b"\x00" * (2 * 1024 * 1024 * 1024))])
        with self.assertRaises(esx_guard.HostileArchive) as caught:
            esx_guard.check(self.write(blob))
        self.assertIn("single file", str(caught.exception).lower())

    def test_an_absurd_member_count_is_refused(self):
        blob = _zip_of([(f"m{i}", b"") for i in range(esx_guard.MAX_MEMBERS + 2)])
        with self.assertRaises(esx_guard.HostileArchive) as caught:
            esx_guard.check(self.write(blob))
        self.assertIn("entries", str(caught.exception).lower())

    def test_a_high_ratio_across_many_members_is_refused(self):
        """No single member over the ceiling, and still a bomb in total."""
        chunk = b"\x00" * (100 * 1024 * 1024)
        blob = _zip_of([(f"m{i}", chunk) for i in range(12)])
        with self.assertRaises(esx_guard.HostileArchive) as caught:
            esx_guard.check(self.write(blob))
        self.assertIn("expands", str(caught.exception).lower())

    def test_a_small_compressible_file_is_not_refused(self):
        """The ratio only means something once there is data behind it.

        An empty file and a short JSON document of repeated whitespace both
        compress enormously and are entirely ordinary.
        """
        esx_guard.check(self.write(_zip_of([("project.json", b" " * 100_000)])))
        esx_guard.check(self.write(_zip_of([("project.json", b"")])))

    def test_something_that_is_not_a_zip_is_left_to_the_tool(self):
        """Saying "not an Ekahau project" is the tool's job, not this one's.

        Two different explanations for one problem is how a user ends up not
        believing either.
        """
        esx_guard.check(self.write(b"not a zip at all"))
        esx_guard.check(self.write(b""))

    def test_a_missing_file_does_not_raise(self):
        esx_guard.check(self.dir / "nope.esx")


class TheUploadRoutesUseIt(unittest.TestCase):
    """The wiring, driven through the routes the archive really arrives at."""

    def setUp(self):
        self.client = server.app.test_client()
        self.bomb = _zip_of([("project.json", b"\x00" * (2 * 1024 * 1024 * 1024))])

    def post(self, path):
        return self.client.post(path, data=self.bomb,
                                headers={server.API_REQUEST_HEADER: "1"})

    def test_plantrim_refuses_it(self):
        r = self.post("/api/plantrim/analyze?name=x.esx")
        self.assertEqual(400, r.status_code)
        self.assertIn("single file", r.get_json()["error"].lower())

    def test_capacity_refuses_it(self):
        r = self.post("/api/capacity/analyze?name=x.esx")
        self.assertEqual(400, r.status_code)
        self.assertIn("single file", r.get_json()["error"].lower())

    def test_prep_refuses_it(self):
        r = self.post("/api/prep/plan?name=x.esx")
        self.assertEqual(400, r.status_code)
        self.assertIn("single file", r.get_json()["error"].lower())

    def test_the_refusal_is_a_sentence_rather_than_a_fault(self):
        """400 with words, not 500 with "something went wrong"."""
        body = self.post("/api/plantrim/analyze?name=x.esx").get_json()
        self.assertFalse(body["ok"])
        self.assertIn("Nothing was read from it", body["error"])


if __name__ == "__main__":
    unittest.main()
