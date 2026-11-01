"""Build the public GitHub Pages site from its tracked sources."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "web" / "pages"
ASSETS = ROOT / "web" / "assets"
LEGACY_DIRECTORIES = ("walls", "scale", "report", "cloud", "organizer")
LEGACY_FILES = ("guide", "guide-cloud", "guide-organizer", "guide-report")


def _landing_html(asset_prefix: str = "") -> str:
    html = (PAGES / "landing.html").read_text(encoding="utf-8")
    if asset_prefix:
        html = html.replace('href="assets/', f'href="{asset_prefix}assets/')
        html = html.replace('src="assets/', f'src="{asset_prefix}assets/')
    return html


def build_site(destination: Path) -> None:
    """Write a complete Pages artifact into an empty destination."""
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError(f"Pages destination is not empty: {destination}")

    shutil.copytree(ASSETS, destination / "assets")
    (destination / "index.html").write_text(
        _landing_html(), encoding="utf-8", newline="\n")

    # Old hosted-tool URLs were posted publicly. They stay useful landing
    # pages, while the canonical tag consolidates them under the site root.
    for name in LEGACY_DIRECTORIES:
        target = destination / name
        target.mkdir()
        (target / "index.html").write_text(
            _landing_html("../"), encoding="utf-8", newline="\n")

    for name in LEGACY_FILES:
        (destination / f"{name}.html").write_text(
            _landing_html(), encoding="utf-8", newline="\n")

    shutil.copy2(PAGES / "sitemap.xml", destination / "sitemap.xml")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build_site(args.destination.resolve())
    for path in sorted(args.destination.rglob("*.html")):
        print(path.relative_to(args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
