"""Swap escAttr calls inside JS-string-in-HTML-attribute contexts for
escJsStr equivalents. The vulnerable pattern is `'${a(` and `'${p(` —
inside a single-quoted JS string that lives inside a double-quoted HTML
attribute value. Also fix kAttr = a(...) and iidAttr = a(...) since
they're always used inside JS strings too."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    ROOT / 'web/assets/js/cloud.js',
]

REPLACEMENTS = [
    # JS-string-inside-onclick contexts
    (r"'\$\{a\(", "'${j("),   # 'PREFIX${a(x)}...' → 'PREFIX${j(x)}...'
    (r"'\$\{p\(", "'${pj("),
    # kAttr and iidAttr are pre-escaped once at the top of the loop and
    # then used inside JS strings — they must also come from j()/pj().
    (r'const kAttr = a\(', 'const kAttr = j('),
    (r'const iidAttr = it\.side === \'local\' \? p\(iid\) : a\(iid\);',
     "const iidAttr = it.side === 'local' ? pj(iid) : j(iid);"),
]

for f in TARGETS:
    s = f.read_text(encoding='utf-8')
    original = s
    counts = []
    for pattern, replacement in REPLACEMENTS:
        new_s, n = re.subn(pattern, replacement, s)
        counts.append((pattern, n))
        s = new_s
    if s != original:
        f.write_text(s, encoding='utf-8', newline='')
        print(f'CHANGED: {f.relative_to(ROOT)}')
        for pat, n in counts:
            print(f'  {n:>3}  {pat}')
    else:
        print(f'no change: {f.relative_to(ROOT)}')
