/* User Manual page — sidebar behaviour only. The manual itself is rendered
   server-side by tools/manual.py; nothing here parses markdown.

   Three jobs:
     1. Filter box over the contents list, so a 17-section manual is navigable
        by typing rather than by scanning.
     2. Highlight whichever section you are currently reading.
     3. Remember where you were, so following a link out and coming back does
        not put you at the top of a 1200-line document.
*/
(function () {
  'use strict';

  var list = document.getElementById('manualTocList');
  var article = document.getElementById('manualArticle');
  if (!list || !article) return;

  var links = Array.prototype.slice.call(list.querySelectorAll('a'));
  var filter = document.getElementById('manualFilter');
  var empty = document.getElementById('manualTocEmpty');

  // --- filter -------------------------------------------------------------
  function applyFilter() {
    var q = (filter.value || '').trim().toLowerCase();
    var shown = 0;
    links.forEach(function (a) {
      var hit = !q || a.textContent.toLowerCase().indexOf(q) !== -1;
      a.hidden = !hit;
      if (hit) shown++;
    });
    if (empty) empty.hidden = shown > 0;
  }

  if (filter) {
    filter.addEventListener('input', applyFilter);
    // Escape clears rather than blurs: clearing is what you want next, and a
    // filter left set on a hidden sidebar is how a section goes "missing".
    filter.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { filter.value = ''; applyFilter(); }
      if (e.key === 'Enter') {
        var first = links.filter(function (a) { return !a.hidden; })[0];
        if (first) first.click();
      }
    });
  }

  // --- current section ----------------------------------------------------
  var targets = links.map(function (a) {
    return document.getElementById(decodeURIComponent(a.getAttribute('href').slice(1)));
  });

  var current = null;
  function markCurrent() {
    // The heading nearest the top of the viewport that has not scrolled past
    // it. Reading downwards, so the last one at or above the line wins.
    var line = 90;
    var best = -1;
    for (var i = 0; i < targets.length; i++) {
      var el = targets[i];
      if (el && el.getBoundingClientRect().top <= line) best = i;
    }
    if (best === current) return;
    if (current >= 0 && links[current]) links[current].classList.remove('is-current');
    current = best;
    if (best >= 0 && links[best]) {
      links[best].classList.add('is-current');
      var a = links[best];
      var box = list.getBoundingClientRect();
      var r = a.getBoundingClientRect();
      if (r.top < box.top || r.bottom > box.bottom) {
        list.scrollTop += r.top - box.top - box.height / 3;
      }
    }
    try { sessionStorage.setItem('wd-manual-at', best >= 0 ? links[best].getAttribute('href') : ''); } catch (e) {}
  }

  var ticking = false;
  function onScroll() {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(function () { ticking = false; markCurrent(); });
  }
  // `.content` sets `overflow: auto`, so the page scrolls inside that element
  // and not on the window. Listening only on the window is why an earlier
  // version of this highlighted nothing. Both are wired; the measurements are
  // viewport-relative either way, so it does not matter which one fires.
  var scroller = article.closest('.content');
  if (scroller) scroller.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  markCurrent();

  // --- return to where you were ------------------------------------------
  if (!location.hash) {
    var at = null;
    try { at = sessionStorage.getItem('wd-manual-at'); } catch (e) {}
    if (at) {
      var el = document.getElementById(at.slice(1));
      if (el) el.scrollIntoView();
      markCurrent();
    }
  }
})();
