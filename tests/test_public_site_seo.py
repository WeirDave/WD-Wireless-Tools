"""The deployed landing site identifies one canonical, shareable product."""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from scripts.build_pages_site import build_site


CANONICAL = "https://weirdave.github.io/WD-Wireless-Tools/"
SOCIAL_IMAGE = CANONICAL + "assets/wd-wireless-tools-social-preview-v2.png"


class PageMetadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonical = None
        self.meta = {}
        self.structured = []
        self.text = []
        self.references = []
        self._json_ld = False
        self._json_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ("href", "src"):
            if attrs.get(name):
                self.references.append(attrs[name])
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs.get("href")
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key:
                self.meta[key] = attrs.get("content")
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag):
        if tag == "script" and self._json_ld:
            self.structured.append(json.loads("".join(self._json_parts)))
            self._json_ld = False

    def handle_data(self, data):
        if self._json_ld:
            self._json_parts.append(data)
        else:
            self.text.append(data)


def parse_page(path: Path) -> PageMetadata:
    page = PageMetadata()
    page.feed(path.read_text(encoding="utf-8"))
    return page


class PublicSiteSeoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.site = Path(self.temp.name) / "site"
        build_site(self.site)

    def tearDown(self):
        self.temp.cleanup()

    def test_every_legacy_page_consolidates_on_the_site_root(self):
        pages = sorted(self.site.rglob("*.html"))
        self.assertEqual(10, len(pages))
        for path in pages:
            with self.subTest(path=path.relative_to(self.site)):
                self.assertEqual(CANONICAL, parse_page(path).canonical)

    def test_root_page_has_complete_share_metadata_and_software_schema(self):
        page = parse_page(self.site / "index.html")
        self.assertEqual("website", page.meta["og:type"])
        self.assertEqual(CANONICAL, page.meta["og:url"])
        self.assertEqual(SOCIAL_IMAGE, page.meta["og:image"])
        self.assertEqual("1280", page.meta["og:image:width"])
        self.assertEqual("640", page.meta["og:image:height"])
        self.assertEqual("summary_large_image", page.meta["twitter:card"])
        self.assertEqual(SOCIAL_IMAGE, page.meta["twitter:image"])

        self.assertEqual(1, len(page.structured))
        software = page.structured[0]
        self.assertEqual("https://schema.org", software["@context"])
        self.assertEqual("SoftwareApplication", software["@type"])
        self.assertEqual("WD Wireless Tools", software["name"])
        self.assertEqual("0", software["offers"]["price"])
        self.assertEqual(["Windows", "macOS"], software["operatingSystem"])

    def test_landing_page_names_the_complete_nine_tool_suite(self):
        text = " ".join(parse_page(self.site / "index.html").text)
        self.assertIn("all nine", text)
        for tool in ("Cloud Manager", "Quick Walls", "Squirrel", "Scale",
                     "Report", "PlanTrim", "AP Labeler", "Capacity", "Prep"):
            with self.subTest(tool=tool):
                self.assertIn(tool, text)

    def test_sitemap_lists_only_the_canonical_page(self):
        root = ET.parse(self.site / "sitemap.xml").getroot()
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locations = [node.text for node in root.findall("s:url/s:loc", namespace)]
        self.assertEqual([CANONICAL], locations)

    def test_social_preview_is_the_required_png_under_one_megabyte(self):
        image = self.site / "assets" / "wd-wireless-tools-social-preview-v2.png"
        data = image.read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        self.assertEqual((1280, 640), struct.unpack(">II", data[16:24]))
        self.assertLess(len(data), 1_000_000)

    def test_nested_legacy_pages_keep_working_asset_paths(self):
        page = parse_page(self.site / "walls" / "index.html")
        self.assertIn("../assets/wd-tools.css", page.references)
        self.assertIn("../assets/wd-wireless-tools-v8.0-720x720.png",
                      page.references)


if __name__ == "__main__":
    unittest.main()
