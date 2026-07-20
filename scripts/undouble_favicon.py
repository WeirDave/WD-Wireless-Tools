"""Undo v1.8.31's HTML media-query doubling.

For each page: keep the "light" (color) variant, drop the "dark" (white)
variant, strip the media="(prefers-color-scheme: light)" attribute so the
tag is unconditional. JS will handle the color→white swap at runtime based
on window.matchMedia so Firefox (which ignores media on link[rel=icon])
also gets the right behavior.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML_FILES = [
    'web/home.html', 'web/cloud.html', 'web/walls.html', 'web/organizer.html',
    'web/scale.html', 'web/report.html', 'web/guide.html',
    'web/guide-cloud.html', 'web/guide-organizer.html',
    'web/pages/hosted-index.html', 'web/pages/hosted-cloud-stub.html',
    'web/pages/hosted-organizer-stub.html',
]

DARK_LINK_RE = re.compile(
    r'\s*<link[^>]*rel="icon"[^>]*media="\(prefers-color-scheme:\s*dark\)"[^>]*>\s*\n?',
    re.IGNORECASE,
)
LIGHT_MEDIA_RE = re.compile(
    r'\s+media="\(prefers-color-scheme:\s*light\)"',
    re.IGNORECASE,
)

for rel in HTML_FILES:
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    orig = s
    s = DARK_LINK_RE.sub('\n', s)
    s = LIGHT_MEDIA_RE.sub('', s)
    if s != orig:
        p.write_text(s, encoding='utf-8', newline='')
        print(f'  {rel}: cleaned')
    else:
        print(f'  {rel}: nothing to clean (maybe already single-set)')
print('DONE')
