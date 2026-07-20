"""Add prefers-color-scheme media variants to every favicon link tag.

For each <link rel="icon" href="...v8.0-{stem}.png|ico"> we replace with two
tags:
  1) the original — but with media="(prefers-color-scheme: light)"
  2) a new one   — media="(prefers-color-scheme: dark)" pointing at the
     matching v8.0-white-{stem} file.

apple-touch-icon is left alone — Apple ignores media queries there.
Idempotent: skips files that already contain "prefers-color-scheme".
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

# Matches a full <link rel="icon" ...> tag (not apple-touch-icon).
LINK_RE = re.compile(
    r'<link\s+([^>]*?\brel\s*=\s*"icon"[^>]*?)\s*/?>',
    re.IGNORECASE,
)

# Matches the icon file basename inside an href, e.g.
# href="/assets/wd-wireless-tools-v8.0-multi-size.ico"
HREF_RE = re.compile(
    r'href\s*=\s*"([^"]*?/wd-wireless-tools-v8\.0-)(multi-size\.ico|32x32\.png|192x192\.png)"',
    re.IGNORECASE,
)

def transform(html: str) -> tuple[str, int]:
    if 'prefers-color-scheme' in html:
        return html, 0  # already done

    n = 0
    def repl(m):
        nonlocal n
        attrs = m.group(1)
        href_m = HREF_RE.search(attrs)
        if not href_m:
            return m.group(0)  # not one we know how to swap; leave alone
        prefix, stem = href_m.group(1), href_m.group(2)
        white_href = f'{prefix}white-{stem}'
        # Original tag, plus media="(prefers-color-scheme: light)"
        light_attrs = f'{attrs} media="(prefers-color-scheme: light)"'
        light_tag = f'<link {light_attrs}>'
        # Duplicate tag with white href + dark media
        dark_attrs = HREF_RE.sub(f'href="{white_href}"', attrs)
        dark_attrs = f'{dark_attrs} media="(prefers-color-scheme: dark)"'
        dark_tag = f'<link {dark_attrs}>'
        n += 1
        return f'{light_tag}\n{dark_tag}'

    new = LINK_RE.sub(repl, html)
    return new, n


if __name__ == '__main__':
    total_changed = 0
    for rel in HTML_FILES:
        p = ROOT / rel
        s = p.read_text(encoding='utf-8')
        new, n = transform(s)
        if n:
            p.write_text(new, encoding='utf-8', newline='')
            print(f'  {rel}: swapped {n} icon link(s)')
            total_changed += 1
        else:
            print(f'  {rel}: skipped (already has prefers-color-scheme or no matching links)')
    print(f'\nDONE: {total_changed} file(s) updated')
