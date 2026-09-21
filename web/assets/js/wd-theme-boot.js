/* Set the theme before the first paint.

   This used to be an inline <script> repeated in fourteen pages, and it was
   inline for a real reason: the attribute has to be on <html> before anything
   is painted, or the page shows a flash of the wrong theme. A file in <head>
   with no `defer` and no `async` blocks rendering in exactly the same way, so
   the behaviour is unchanged - and it is a few hundred bytes served from the
   same origin, cached after the first page.

   Moving it out is what lets a page carry `script-src 'self'`: a policy
   without 'unsafe-inline' blocks an inline block like this one, so every page
   had to keep a permissive policy while it was there. Backlog item 10.

   The two copies differed. Thirteen pages set 'dark' in the catch; home.html
   did nothing there, so a browser with localStorage blocked got no attribute
   at all and fell through to whatever the stylesheet defaults to. The
   defensive version is kept - it is the one that behaves the same in a
   private window as in an ordinary one. */
(function () {
  try {
    document.documentElement.setAttribute(
      'data-theme', localStorage.getItem('wd-theme') || 'dark');
  } catch (e) {
    /* Private windows and blocked site data both throw on access rather than
       returning null, so the fallback has to be here rather than in the `||`
       above. */
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
