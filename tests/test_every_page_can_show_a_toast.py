"""A page that can raise a toast has to have somewhere to put it.

`WD.toast` writes into `#toasts` if it is there, falls back to `#toast`, and if
neither exists **does nothing at all** - no console warning, no throw. Eight
pages loaded `wd-shared.js` and had neither.

The worst of them was Suite Settings. It makes four toast calls, and one of
them is `WD.toast(r.error || 'Save failed', 'error')`. So a save that failed
looked exactly like a save that worked: click Save, nothing happens, either
way. The other three - "Settings saved", "Login forgotten", "Organizer reset to
defaults" - were silent too, which is why nobody noticed the fourth.

The rest were quieter but the same shape. Every page's menu carries
"- Copy Diagnostics", which lives in `wd-shared.js` and toasts either
"Diagnostics copied to clipboard" or "Copy failed - open dev tools console and
try again". On Home, Setup and all four guide pages, both outcomes said
nothing.

Found by clicking Save in Firefox and looking for the confirmation, which is
the only way this shows up: the save itself worked, the server had the new
values, the file on disk had them, and the page said nothing.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "assets" / "js"

TOAST_CALL = re.compile(r"\bWD\.toast\s*\(")


def pages():
    for f in sorted(WEB.glob("*.html")):
        yield f, f.read_text(encoding="utf-8")


def scripts_of(text: str) -> str:
    out = ""
    for src in re.findall(r'<script src="([^"]+)"', text):
        p = ROOT / "web" / src.lstrip("/")
        if p.exists():
            out += p.read_text(encoding="utf-8")
    return out


class SomewhereToPutIt(unittest.TestCase):

    def test_every_page_that_can_toast_has_a_host_element(self):
        for f, text in pages():
            js = scripts_of(text)
            can_toast = TOAST_CALL.search(js) or TOAST_CALL.search(text)
            if not can_toast:
                continue
            with self.subTest(page=f.name):
                self.assertTrue(
                    'id="toasts"' in text or 'id="toast"' in text,
                    f"{f.name} calls WD.toast and has no #toasts or #toast, "
                    f"so every message it raises - including failures - is "
                    f"silently dropped")

    def test_wd_shared_is_what_makes_this_apply_to_nearly_every_page(self):
        """Copy Diagnostics is in every menu and lives in the shared file, so
        loading `wd-shared.js` is on its own enough to need a host."""
        shared = (JS / "wd-shared.js").read_text(encoding="utf-8")
        self.assertRegex(shared, r"WD\.toast\('Diagnostics copied")
        self.assertRegex(shared, r"WD\.toast\('Copy failed")

    def test_the_settings_page_reports_a_failed_save(self):
        """The one that mattered: an unreported failure is indistinguishable
        from success."""
        page = (WEB / "settings.html").read_text(encoding="utf-8")
        sp = (JS / "settings-page.js").read_text(encoding="utf-8")
        self.assertIn("'Save failed'", sp)
        self.assertIn('id="toasts"', page)

    def test_the_host_is_styled_as_a_stack(self):
        """`.toast-container` positions its children and lets them pile up.
        A bare div would leave each message drawn on top of the last."""
        css = (WEB / "assets" / "wd-tools.css").read_text(encoding="utf-8")
        self.assertIn(".toast-container {", css)
        self.assertIn(".toast-container .toast {", css)
        for f, text in pages():
            if 'id="toasts"' not in text:
                continue
            with self.subTest(page=f.name):
                tag = re.search(r'<div[^>]*id="toasts"[^>]*>', text).group(0)
                self.assertIn("toast", tag)


class TheTemplateHintNamesRealTokens(unittest.TestCase):
    """Suite Settings' "Create-folder naming template" field suggested
    `e.g. {site} - {date}`. `{site}` is not a token - `_extractTokens` in
    organizer.js matches against CREATE_TOKENS plus two aliases, and `site` is
    in neither - so a template copied from the placeholder would put the
    literal text `{site}` in the folder name.

    The field also never said what the tokens were, which is why the wrong one
    in the placeholder was the only guidance there was. Squirrel's own copy of
    this control shows worked examples; the suite-level one now at least lists
    the vocabulary."""

    def setUp(self):
        self.page = (WEB / "settings.html").read_text(encoding="utf-8")
        org = (JS / "organizer.js").read_text(encoding="utf-8")
        line = re.search(r"const CREATE_TOKENS = \[([^\]]*)\]", org).group(1)
        self.tokens = re.findall(r"'([a-z_]+)'", line)

    def test_the_placeholder_uses_tokens_that_exist(self):
        ph = re.search(r'id="sCreateTpl"[^>]*placeholder="([^"]*)"',
                       self.page).group(1)
        for tok in re.findall(r"\{([a-z_]+)\}", ph):
            with self.subTest(token=tok):
                self.assertIn(tok, self.tokens)

    def test_the_hint_lists_every_token(self):
        hint = self.page[self.page.index('id="sCreateTpl"'):]
        hint = hint[:hint.index("</div>")]
        for tok in self.tokens:
            with self.subTest(token=tok):
                self.assertIn("{" + tok + "}", hint)


if __name__ == "__main__":
    unittest.main()
