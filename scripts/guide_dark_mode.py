"""Rewrite the [data-theme="dark"] block in each guide with a comprehensive
set of overrides. The v1 block was too thin — headings, kbd pills, and
tip/warning boxes all used hardcoded light-mode colors that vanish on the
dark background.

Also updates the "David Paine" attribution to "R David Paine III" if it
wasn't already changed.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    'web/guide.html',
    'web/guide-cloud.html',
    'web/guide-organizer.html',
]

THEME_SCRIPT = '''<script>
  (function () { try { document.documentElement.setAttribute('data-theme', localStorage.getItem('wd-theme') || 'dark'); } catch (e) { document.documentElement.setAttribute('data-theme', 'dark'); } })();
</script>
'''

# Comprehensive dark-mode override block — covers every element in the
# guide's inline CSS that has hardcoded light-mode colors.
DARK_BLOCK = '''
  [data-theme="dark"] {
    --text: #e7ebf0;
    --text-muted: #9aa5b1;
    --bg: #0f1620;
    --surface: #18212c;
    --border: #273240;
  }
  [data-theme="dark"] body { background: var(--bg); color: var(--text); }
  [data-theme="dark"] .content { color: var(--text); }
  [data-theme="dark"] .subtitle { color: var(--text-muted); }
  [data-theme="dark"] .topbar .back-link { color: rgba(255,255,255,0.6); }
  [data-theme="dark"] .topbar .back-link:hover { color: #fff; }

  /* Headings — the original uses --navy (near-black), invisible on dark. */
  [data-theme="dark"] h2 { color: var(--text); border-bottom-color: var(--green); }
  [data-theme="dark"] h3 { color: var(--text); }

  /* Inline code and preformatted blocks. */
  [data-theme="dark"] code {
    background: rgba(255,255,255,0.06); color: #a7d3ef;
    border-color: rgba(255,255,255,0.10);
  }
  [data-theme="dark"] pre { background: #0b1620; color: #d6e0ea; border-color: rgba(255,255,255,0.10); }

  /* <kbd> — was blank-on-blank in dark mode because both bg and text were
     hardcoded light-mode values. */
  [data-theme="dark"] kbd {
    background: var(--surface-raised, #252830);
    border-color: rgba(255,255,255,0.18);
    color: var(--text);
  }

  /* Step cards. */
  [data-theme="dark"] .step-card {
    background: var(--surface); border-color: var(--border);
  }
  [data-theme="dark"] .step-card .step-desc { color: var(--text-muted); }
  [data-theme="dark"] .step-card .step-title { color: var(--text); }

  /* Tip / warning callouts — hardcoded pastel backgrounds in light mode.
     Swap for tinted dark-surface variants that still read as "green/amber". */
  [data-theme="dark"] .tip-box {
    background: rgba(95,171,79,0.08); border-color: rgba(95,171,79,0.30);
    color: var(--text);
  }
  [data-theme="dark"] .tip-box strong { color: #7ec06f; }
  [data-theme="dark"] .warning-box, [data-theme="dark"] .note {
    background: rgba(217,119,6,0.08); border-color: rgba(217,119,6,0.30);
    color: var(--text);
  }
  [data-theme="dark"] .warning-box strong, [data-theme="dark"] .note strong { color: #e0a63a; }

  /* Tables. */
  [data-theme="dark"] table { border-color: var(--border); }
  [data-theme="dark"] th { background: #0b1620; color: #fff; }
  [data-theme="dark"] td { border-color: var(--border); color: var(--text); }
  [data-theme="dark"] tr:nth-child(even) td { background: rgba(255,255,255,0.03); }

  /* Footer + link colors. */
  [data-theme="dark"] .footer { color: var(--text-muted); border-color: var(--border); }
  [data-theme="dark"] .footer a, [data-theme="dark"] a { color: #6bb3e0; }
'''

# The v1 block signature — used to remove the old block before inserting
# the new one. Matches from the opening [data-theme="dark"] { line through
# the last rule of the previous block.
V1_BLOCK_PATTERN = re.compile(
    r'\n  \[data-theme="dark"\]\s*\{[^}]*\}[\s\S]*?\[data-theme="dark"\]\s+a\s*\{[^}]*\}\n?',
    re.MULTILINE,
)

for rel in FILES:
    p = ROOT / rel
    s = p.read_text(encoding='utf-8')
    original = s

    # 1. Ensure the pre-body theme script is present.
    if 'wd-theme' not in s:
        s = s.replace('</head>', THEME_SCRIPT + '</head>', 1)

    # 2. Remove any existing [data-theme="dark"] block(s) so we start clean.
    s = V1_BLOCK_PATTERN.sub('\n', s)
    # Also remove any leftover isolated dark rules — safety net.
    s = re.sub(r'\n  \[data-theme="dark"\][^\n]*\{[^}]*\}\n', '\n', s)

    # 3. Insert the comprehensive DARK_BLOCK right after the :root close.
    m = re.search(r'(:root\s*\{[^}]*\})', s)
    if m:
        s = s[:m.end()] + DARK_BLOCK + s[m.end():]

    # 4. Author attribution.
    s = s.replace('>David Paine</a>', '>R David Paine III</a>')

    if s != original:
        p.write_text(s, encoding='utf-8', newline='')
        print(f'CHANGED: {rel}')
    else:
        print(f'no change: {rel}')
