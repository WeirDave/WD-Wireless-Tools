(function () {
  'use strict';

  /* ── state ─────────────────────────────────────────────────────── */
  var S = {
    file: null,
    zip: null,
    rawAPs: null,
    aps: [],
    floors: [],
    imageFormats: {},
    floorImageUrls: {},
    currentFloor: null,
    sorted: [],
    preview: [],
    byId: {},          // ap id -> its preview row, so one number serves every surface
    templates: [],
    manualOrder: [],   // ap ids, in the order they were clicked
    manualUndo: [],    // snapshots of manualOrder, newest last
    _showAllPreview: false
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(s); }
  function toast(m, k) { WD.toast(m, k); }

  /* ── Ekahau color palette (10 selectable colors + CLEAR) ───────────
     Defined in wd-shared.js, because the Report has to read the same .esx and
     was drawing palette names as CSS keywords for want of this map. */
  var EKAHAU_COLORS = WD.EKAHAU_COLORS;
  var COLOR_ORDER = WD.EKAHAU_COLOR_ORDER;

  function resolveColor(c) { return WD.resolveApColor(c); }

  /* One group key per colour, whichever way the project spells it.

     An .esx may carry a palette name ("BLUE") or the hex Ekahau paints it with
     ("#0068FF"). Grouped on the raw string those are two different colours, so
     a sequence chosen by name would skip every hex-coloured AP and drop it into
     the leftovers. Normalise to the palette name where one matches. */
  function colorKey(c) {
    if (!c) return '__none';
    var lc = String(c).toLowerCase().trim();
    if (EKAHAU_COLORS[lc]) return lc;
    var up = lc.toUpperCase();
    for (var i = 0; i < COLOR_ORDER.length; i++) {
      if (EKAHAU_COLORS[COLOR_ORDER[i]] === up) return COLOR_ORDER[i];
    }
    return lc;
  }

  function colorSortKey(c) {
    if (!c) return COLOR_ORDER.length;
    var lc = c.toLowerCase().trim();
    var idx = COLOR_ORDER.indexOf(lc);
    if (idx >= 0) return idx;
    for (var i = 0; i < COLOR_ORDER.length; i++) {
      if (EKAHAU_COLORS[COLOR_ORDER[i]] === c.toUpperCase()) return i;
    }
    return COLOR_ORDER.length;
  }

  /* Contrast is decided in wd-shared.js, not here. Every tool that paints on
     a colour somebody chose in Ekahau has this problem, and three private
     copies of the answer is how they came to disagree about green. Call
     WD.readableOn() for ink and WD.outlineOn() for the ring. */

  /* ── naming mode ────────────────────────────────────────────────── */
  var _mode = 'structured';
  var _scope = 'all';
  /* 'floor' finishes a floor before moving up; 'color' carries one colour
     through the whole building. Only consulted when ordering is by-color. */
  var _nesting = 'floor';
  // What was read out of the loaded project, for the note. Null when nothing.
  var _inferred = null;
  // The colour sequence for the By Colour ordering, newest choice last.
  var _colorOrder = [];

  /* ── segment builder model ──────────────────────────────────────── */
  var _segments = [
    { type: 'text', value: '' },
    { type: 'text', value: '' },
    { type: 'floor' },
    { type: 'text', value: '' },
    { type: 'counter', tag: 'AP', start: 1, digits: 3 }
  ];

  window.arSetMode = function (m) {
    _mode = m;
    $('arStructuredFields').hidden = (m !== 'structured');
    $('arSimpleFields').hidden     = (m !== 'simple');
    $('arMacFields').hidden        = (m !== 'mac');
    document.querySelectorAll('.ar-mode-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-mode') === m);
    });
    updateAll();
  };

  window.arSetScope = function (s) {
    _scope = s;
    /* Scoped to its own group. The nesting tabs below reuse .ar-scope-tab for
       its styling, and a bare class query here toggled `active` off them by
       asking for a data-scope they do not have - leaving both nesting tabs
       looking unselected. */
    document.querySelectorAll('#arScopeTabs .ar-scope-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-scope') === s);
    });
    var desc = $('arScopeDesc');
    if (desc) {
      desc.textContent = s === 'perFloor'
        ? 'Each floor restarts numbering independently.'
        : 'One continuous sequence across the entire project.';
    }
    updateAll();
  };

  /* Colour-major and "restart numbering each floor" cannot both be true.

     Numbering every blue on floors 1-3 and then coming back to floor 1 for the
     greens means a per-floor counter has already been spent: the greens either
     collide with the blues or restart in the middle of a floor. Neither is a
     thing anybody wants, so choosing colour-major moves Scope to continuous
     and says so, rather than letting the combination be discovered in a set of
     duplicate AP names. Floor-major composes with either. */
  window.arSetNesting = function (n) {
    _nesting = n;
    document.querySelectorAll('#arNestTabs .ar-scope-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-nest') === n);
    });
    var forced = false;
    if (n === 'color' && _scope === 'perFloor') {
      arSetScope('all');            // this calls updateAll() itself
      forced = true;
    }
    var desc = $('arNestDesc');
    if (desc) {
      desc.textContent = n === 'color'
        ? 'Every blue in the building, then every green, then every grey. One continuous sequence — a per-floor counter cannot survive leaving a floor and coming back.'
        : 'Floor 1’s colours in your order, then floor 2’s, and so on. Each floor is finished before the next.';
    }
    var tabs = document.querySelectorAll('#arScopeTabs .ar-scope-tab');
    tabs.forEach(function (t) {
      var lock = (n === 'color' && t.getAttribute('data-scope') === 'perFloor');
      t.disabled = lock;
      t.title = lock
        ? 'Not available while numbering a colour through the whole building — the sequence leaves each floor and comes back.'
        : '';
    });
    if (forced) toast('Scope set to All APs — colour-through-building is one continuous sequence', 'info');
    if (!forced) updateAll();
  };

  function syncNestPanel() {
    var panel = $('arNestPanel');
    if (!panel) return;
    // Nothing to nest on a single-floor project.
    var multiFloor = (S.floors || []).length > 1;
    panel.hidden = !($('arOrder').value === 'by-color' && multiFloor);
    // The description explains what the active choice does, so it has to say
    // something before anyone has clicked anything.
    var desc = $('arNestDesc');
    if (!panel.hidden && desc && !desc.textContent) {
      desc.textContent = _nesting === 'color'
        ? 'Every blue in the building, then every green, then every grey. One continuous sequence — a per-floor counter cannot survive leaving a floor and coming back.'
        : 'Floor 1’s colours in your order, then floor 2’s, and so on. Each floor is finished before the next.';
    }
  }

  function getFloorNumber(floor) {
    if (!floor) return '01';
    var n = floor.order != null ? floor.order : 0;
    var s = String(n);
    while (s.length < 2) s = '0' + s;
    return s;
  }

  function buildStructuredName(floor, num) {
    var sep = $('arSepStructured').value;
    var parts = [];
    for (var i = 0; i < _segments.length; i++) {
      var seg = _segments[i];
      if (seg.type === 'text') {
        if (seg.value) parts.push(seg.value);
      } else if (seg.type === 'floor') {
        parts.push(seg.value ? seg.value : getFloorNumber(floor));
      } else if (seg.type === 'counter') {
        var tag = seg.tag || '';
        var digits = seg.digits || 3;
        parts.push(tag + padNum(num, digits));
      }
    }
    return parts.join(sep);
  }

  /* ── reading the scheme a project already uses ──────────────────

     If the APs in a project are already named to a scheme, retyping that
     scheme by hand just to add one AP and renumber is work the file can do
     for you. So the names are read and the segment list is inferred.

     This infers *segments*, not a fixed CLLI/Building/Suite/Floor shape.
     The Labeler stopped having named fields when the segment builder landed
     - a name is whatever ordered list of text / floor / counter parts you
     drag together - so inferring by position keeps working for schemes that
     look nothing like anyone else's, and avoids having to decide whether the
     third segment is a suite or a floor when the tool no longer cares.

     Only what the names actually show is filled in. Where the evidence is
     ambiguous the segment stays plain text, which reproduces the existing
     names exactly; a wrong guess that goes unnoticed renames a building. */

  var SEPARATOR_CANDIDATES = ['-', '_', '.', ' '];

  function _modal(values) {
    var count = {}, best = null, bestN = 0;
    values.forEach(function (v) {
      count[v] = (count[v] || 0) + 1;
      if (count[v] > bestN) { bestN = count[v]; best = v; }
    });
    return { value: best, n: bestN };
  }

  /* The separator is whichever carves the most names into the same number of
     parts. A scheme that uses none, or mixes them, yields nothing. */
  function _detectSeparator(names) {
    var best = null;
    SEPARATOR_CANDIDATES.forEach(function (sep) {
      var counts = names
        .map(function (n) { return n.split(sep).length; })
        .filter(function (c) { return c >= 2; });
      if (!counts.length) return;
      var m = _modal(counts);
      if (!best || m.n > best.agree || (m.n === best.agree && m.value > best.parts)) {
        best = { sep: sep, parts: m.value, agree: m.n };
      }
    });
    return best;
  }

  /* "AP01" -> tag AP, 2 digits. Applied to one segment, never to a whole
     name: a regex anchored at the end of a full name misses anything with a
     suffix after the number, which is how a duplicate marker broke this
     once. */
  var COUNTER_RE = /^(.*?)(\d+)$/;

  function _asCounter(values) {
    var tags = [], widths = [];
    for (var i = 0; i < values.length; i++) {
      var m = COUNTER_RE.exec(values[i]);
      if (!m) return null;
      tags.push(m[1]);
      widths.push(m[2].length);
    }
    var tag = _modal(tags), width = _modal(widths);
    if (tag.n !== tags.length) return null;      // the tag has to be constant
    return { tag: tag.value, digits: width.value };
  }

  /* entries: [{ name, floorId }]. Returns null when nothing can be read. */
  function inferSegments(entries) {
    entries = (entries || []).filter(function (e) { return e && e.name; });
    if (entries.length < 2) return null;

    var det = _detectSeparator(entries.map(function (e) { return e.name; }));
    if (!det || det.parts < 2) return null;

    /* Only the names sharing the majority shape take part. The rest are
       counted and reported rather than forced to fit - a project with a
       handful of oddly named APs should still hand over its scheme, and say
       how many it read it from. */
    var matched = entries.filter(function (e) {
      return e.name.split(det.sep).length === det.parts;
    });
    if (matched.length < 2) return null;

    var floors = {};
    matched.forEach(function (e) {
      (floors[e.floorId || ''] = floors[e.floorId || ''] || []).push(e);
    });
    var floorIds = Object.keys(floors);

    var partAt = function (e, i) { return e.name.split(det.sep)[i]; };
    var segments = [], counterAt = -1;

    for (var i = 0; i < det.parts; i++) {
      var all = matched.map(function (e) { return partAt(e, i); });
      var everywhere = _modal(all);

      if (everywhere.n === all.length) {
        segments.push({ type: 'text', value: everywhere.value });
        continue;
      }

      /* Constant within each floor but different between them: that is the
         floor, and it is the one thing a single-floor project cannot show
         us - so there it stays text, and the names still come out right. */
      var constantPerFloor = floorIds.every(function (fid) {
        var vals = floors[fid].map(function (e) { return partAt(e, i); });
        return _modal(vals).n === vals.length;
      });
      if (constantPerFloor && floorIds.length > 1) {
        segments.push({ type: 'floor' });
        continue;
      }

      var counter = _asCounter(all);
      if (counter) {
        segments.push({ type: 'counter', tag: counter.tag, start: 1,
                        digits: counter.digits });
        counterAt = i;
        continue;
      }
      return null;            // a segment nobody can explain; infer nothing
    }

    if (counterAt < 0) return null;             // no number means no scheme

    // Exactly one counter. If a scheme somehow produced two, the later one is
    // the AP number and the earlier is treated as the text it looks like.
    for (var j = 0; j < segments.length; j++) {
      if (segments[j].type === 'counter' && j !== counterAt) {
        var col = matched.map(function (e) { return partAt(e, j); });
        segments[j] = { type: 'text', value: _modal(col).value };
      }
    }

    /* A scheme has to look deliberate before it is allowed to replace what he
       already had. Ekahau's own default names are "AP-1", "AP-2" - which do
       infer a scheme, technically, and reproducing it would be useless: a
       fresh survey would arrive and quietly throw away his saved default in
       favour of Ekahau's placeholder.

       What separates a scheme somebody chose from a placeholder is that the
       number carries a tag ("AP01") or is padded ("001"). Ekahau's are bare
       and unpadded - "AP-1", "Ekahau AP 1" - so those are left alone and the
       saved default stands. */
    var tag = segments[counterAt].tag;
    if (!tag && segments[counterAt].digits < 2) return null;

    return {
      segments: segments,
      sep: det.sep,
      matched: matched.length,
      total: entries.length,
      floors: floorIds.length,
      sample: matched[0].name
    };
  }


  /* Read the project's own scheme and use it.

     The project wins over saved defaults when it has a scheme of its own,
     because that is the point: adding one AP to a building that is already
     named should not mean retyping the pattern. Saved defaults are what to
     do when the file has nothing to say.

     What was read, and from how many APs, is stated on screen. An inferred
     pattern that silently disagreed with the file would rename every AP in
     the building on the next Apply, so it says where it came from and shows
     a name it matched. */
  function adoptProjectScheme() {
    var box = $('arInferred');
    if (box) { box.hidden = true; box.innerHTML = ''; }
    _inferred = null;

    var read = inferSegments(S.aps.map(function (ap) {
      return { name: ap.name, floorId: ap.floorPlanId };
    }));
    if (!read) return;

    _segments = read.segments.map(function (seg) {
      if (seg.type === 'text')    return { type: 'text', value: seg.value };
      if (seg.type === 'floor')   return { type: 'floor', value: '' };
      return { type: 'counter', tag: seg.tag, start: seg.start, digits: seg.digits };
    });
    var sepSel = $('arSepStructured');
    if (sepSel) {
      var has = Array.prototype.some.call(sepSel.options, function (o) {
        return o.value === read.sep;
      });
      if (has) sepSel.value = read.sep;
    }
    _inferred = read;
    renderSegments();
    renderInferredNote(read);
    updateAll();
  }

  function renderInferredNote(read) {
    var box = $('arInferred');
    if (!box) return;
    var all = read.matched === read.total;
    var from = all
      ? 'all ' + read.matched + ' AP' + (read.matched === 1 ? '' : 's')
      : read.matched + ' of ' + read.total + ' APs';
    var floorNote = read.floors > 1
      ? ' The segment that changes between floors is set to Floor.'
      : ' Only one floor here, so nothing could show which segment is the '
        + 'floor — every fixed part was left as text.';
    var odd = all ? ''
      : ' The other ' + (read.total - read.matched)
        + ' do not follow it and were ignored.';
    box.innerHTML =
      '<div class="ar-inf-head">Read from this project</div>' +
      '<div class="ar-inf-body">Filled in from the names ' + esc(from) +
      ' already use, like <code>' + esc(read.sample) + '</code>.' +
      esc(odd) + esc(floorNote) + '</div>' +
      '<div class="ar-inf-body ar-inf-sub">Edit anything below — nothing is ' +
      'renamed until you apply.</div>';
    box.hidden = false;
  }

  /* ── segment builder UI ─────────────────────────────────────────── */
  function renderSegments() {
    var container = $('arSegments');
    if (!container) return;
    container.innerHTML = '';
    _segments.forEach(function (seg, i) {
      var row = document.createElement('div');
      row.className = 'ar-seg-row';
      row.setAttribute('draggable', 'true');
      row.setAttribute('data-seg-idx', i);

      var handle = document.createElement('span');
      handle.className = 'ar-seg-handle';
      handle.textContent = '≡';
      row.appendChild(handle);

      var badge = document.createElement('span');
      badge.className = 'ar-seg-type';
      if (seg.type === 'text')    { badge.classList.add('t-text'); badge.textContent = 'Text'; }
      else if (seg.type === 'floor') { badge.classList.add('t-floor'); badge.textContent = 'Floor'; }
      else                        { badge.classList.add('t-counter'); badge.textContent = 'AP #'; }
      row.appendChild(badge);

      if (seg.type === 'counter') {
        var tagLbl = document.createElement('span');
        tagLbl.className = 'ar-seg-lbl';
        tagLbl.textContent = 'tag';
        row.appendChild(tagLbl);
        var tagIn = document.createElement('input');
        tagIn.className = 'ar-seg-input ar-seg-input-bordered';
        tagIn.style.flex = '0 0 36px';
        tagIn.value = seg.tag || '';
        tagIn.placeholder = 'AP';
        tagIn.addEventListener('input', function () { seg.tag = this.value; updateAll(); });
        row.appendChild(tagIn);
        var startLbl = document.createElement('span');
        startLbl.className = 'ar-seg-lbl';
        startLbl.textContent = 'start';
        row.appendChild(startLbl);
        var startIn = document.createElement('input');
        startIn.type = 'number';
        startIn.className = 'ar-seg-input ar-seg-input-bordered';
        startIn.style.flex = '0 0 40px';
        startIn.style.textAlign = 'center';
        startIn.value = seg.start || 1;
        startIn.min = '0';
        startIn.addEventListener('input', function () { seg.start = parseInt(this.value, 10) || 1; updateAll(); renderSegments(); });
        row.appendChild(startIn);
        var digLbl = document.createElement('span');
        digLbl.className = 'ar-seg-lbl';
        digLbl.textContent = 'zeros';
        row.appendChild(digLbl);
        var digIn = document.createElement('select');
        digIn.className = 'ar-seg-input ar-seg-input-bordered';
        digIn.style.flex = '0 0 40px';
        var curZeros = (seg.digits || 3) - 1;
        for (var d = 0; d <= 5; d++) {
          var opt = document.createElement('option');
          opt.value = d; opt.textContent = d;
          if (d === curZeros) opt.selected = true;
          digIn.appendChild(opt);
        }
        digIn.addEventListener('change', function () { seg.digits = (parseInt(this.value, 10) || 0) + 1; updateAll(); renderSegments(); });
        row.appendChild(digIn);
        var meta = document.createElement('span');
        meta.className = 'ar-seg-meta';
        meta.textContent = '→ ' + padNum(seg.start || 1, seg.digits || 3);
        row.appendChild(meta);
      } else if (seg.type === 'floor') {
        var floorIn = document.createElement('input');
        floorIn.className = 'ar-seg-input ar-seg-input-bordered';
        floorIn.value = seg.value || '';
        var curFloor = S.currentFloor ? S.floors.find(function (f) { return f.id === S.currentFloor; }) : S.floors[0];
        var autoVal = getFloorNumber(curFloor || null);
        floorIn.placeholder = autoVal;
        floorIn.title = 'Auto-detected: ' + autoVal + '. Type a value to override.';
        floorIn.addEventListener('input', function () { seg.value = this.value; updateAll(); });
        row.appendChild(floorIn);
        var floorHint = document.createElement('span');
        floorHint.className = 'ar-seg-lbl';
        floorHint.textContent = 'auto from .esx — type to override';
        floorHint.style.flex = '1';
        row.appendChild(floorHint);
      } else {
        var inp = document.createElement('input');
        inp.className = 'ar-seg-input ar-seg-input-bordered';
        inp.value = seg.value || '';
        inp.placeholder = 'Label';
        inp.addEventListener('input', function () { seg.value = this.value; updateAll(); });
        row.appendChild(inp);
      }

      var rm = document.createElement('button');
      rm.className = 'ar-seg-rm';
      rm.type = 'button';
      rm.innerHTML = '&times;';
      rm.addEventListener('click', function () { _segments.splice(i, 1); renderSegments(); updateAll(); });
      row.appendChild(rm);

      // Drag reorder
      row.addEventListener('dragstart', function (e) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(i));
        row.style.opacity = '.4';
      });
      row.addEventListener('dragend', function () { row.style.opacity = ''; });
      row.addEventListener('dragover', function (e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; });
      row.addEventListener('drop', function (e) {
        e.preventDefault();
        var from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        var to = i;
        if (from === to) return;
        var item = _segments.splice(from, 1)[0];
        _segments.splice(to, 0, item);
        renderSegments();
        updateAll();
      });

      container.appendChild(row);
    });
  }

  // Add-segment menu
  (function () {
    var btn = $('arAddBtn');
    var menu = $('arAddMenu');
    if (!btn || !menu) return;
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener('click', function () { menu.hidden = true; });
    menu.querySelectorAll('.ar-add-item').forEach(function (item) {
      item.addEventListener('click', function (e) {
        e.stopPropagation();
        var t = item.getAttribute('data-type');
        if (t === 'text')        _segments.push({ type: 'text', value: '' });
        else if (t === 'floor')  _segments.push({ type: 'floor' });
        else                     _segments.push({ type: 'counter', tag: 'AP', start: 1, digits: 3 });
        menu.hidden = true;
        renderSegments();
        updateAll();
      });
    });
  })();

  // Scope tab clicks
  (function () {
    var tabs = $('arScopeTabs');
    if (!tabs) return;
    var nestTabs = $('arNestTabs');
    if (nestTabs) {
      nestTabs.querySelectorAll('.ar-scope-tab').forEach(function (tab) {
        tab.addEventListener('click', function () {
          if (tab.disabled) return;
          arSetNesting(tab.getAttribute('data-nest'));
        });
      });
    }
    tabs.querySelectorAll('.ar-scope-tab').forEach(function (tab) {
      tab.addEventListener('click', function () {
        arSetScope(tab.getAttribute('data-scope'));
      });
    });
  })();

  function parseMacHex(mac) {
    return mac.replace(/[^0-9a-fA-F]/g, '').toUpperCase();
  }

  function formatMac(hex, format, octets, macCase) {
    if (hex.length < 2) return hex;
    var full = hex;
    while (full.length < 12) full = '0' + full;
    if (octets < 6) full = full.slice(-octets * 2);

    var pairs = [];
    for (var i = 0; i < full.length; i += 2) pairs.push(full.substr(i, 2));

    var result;
    if (format === 'colon') result = pairs.join(':');
    else if (format === 'dash') result = pairs.join('-');
    else if (format === 'dot') {
      var quads = [];
      for (var j = 0; j < pairs.length; j += 2) {
        quads.push(pairs[j] + (pairs[j + 1] || ''));
      }
      result = quads.join('.');
    } else result = pairs.join('');

    return macCase === 'lower' ? result.toLowerCase() : result.toUpperCase();
  }

  function buildMacName(num) {
    var raw     = $('arMacAddr').value;
    var format  = $('arMacFormat').value;
    var octets  = parseInt($('arMacOctets').value, 10) || 3;
    var macCase = $('arMacCase').value;
    var prefix  = $('arMacPrefix').value;
    var hex     = parseMacHex(raw);

    if (!hex) return prefix + '000000'.slice(0, octets * 2);

    var baseNum = parseInt(hex, 16) + (num - 1);
    var incHex  = baseNum.toString(16).toUpperCase();
    while (incHex.length < hex.length) incHex = '0' + incHex;

    return prefix + formatMac(incHex, format, octets, macCase);
  }

  /* ── templates (server-side) & defaults ───────────────────────── */
  function apiSettings(action, body) {
    return fetch('/api/settings/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify(body || {})
    }).then(function (r) { return r.json(); });
  }

  function loadDefaults() {
    return apiSettings('get').then(function (res) {
      var d = res && res.ok && res.settings && res.settings.aprename;
      if (d && d.defaults) applySettings(d.defaults);
      if (d && d.templates) { S.templates = d.templates; renderTemplateSelect(); }
      updateAll();
    }).catch(function () { /* offline or older server: keep the built-ins */ });
  }

  window.arSaveDefaults = function () {
    var s = getSettings();
    delete s.macAddr;
    apiSettings('update', { patch: { aprename: { defaults: s } } }).then(function (res) {
      if (res && res.ok) toast('Saved as defaults', 'success');
      else toast('Could not save defaults', 'error');
    }).catch(function () { toast('Could not save defaults', 'error'); });
  };

  function renderTemplateSelect() {
    var sel = $('arTemplateSelect');
    if (!sel) return;
    var html = '<option value="">— Load template —</option>';
    S.templates.forEach(function (t, i) {
      html += '<option value="' + i + '">' + esc(t.name) + '</option>';
    });
    sel.innerHTML = html;
  }

  function getSettings() {
    return {
      mode:      _mode,
      scope:     _scope,
      nesting:   _nesting,
      order:     $('arOrder').value,
      colorOrder: _colorOrder.slice(),
      segments:  _segments.map(function (s) {
        var o = { type: s.type };
        if (s.type === 'text')    o.value = s.value || '';
        if (s.type === 'floor' && s.value)  o.value = s.value;
        if (s.type === 'counter') { o.tag = s.tag || ''; o.start = s.start || 1; o.digits = s.digits || 3; }
        return o;
      }),
      sepS:      $('arSepStructured').value,
      prefix:    $('arPrefix').value,
      sep:       $('arSep').value,
      startNum:  parseInt($('arStart').value, 10) || 1,
      digits:    (parseInt($('arDigits').value, 10) || 0) + 1,
      macAddr:   $('arMacAddr').value,
      macFormat: $('arMacFormat').value,
      macOctets: parseInt($('arMacOctets').value, 10) || 3,
      macCase:   $('arMacCase').value,
      macPrefix: $('arMacPrefix').value,
      spacing:   parseInt($('arSpacing').value, 10) || 0
    };
  }

  function applySettings(s) {
    if (s.mode) arSetMode(s.mode);
    if (s.nesting) arSetNesting(s.nesting);
    // After nesting, so colour-major's continuous rule is not undone by a
    // stale saved scope from before the two were ever combined.
    if (s.scope) arSetScope(s.scope);
    if (s.nesting === 'color') arSetScope('all');
    if (s.order)     $('arOrder').value = s.order;
    if (Array.isArray(s.colorOrder)) _colorOrder = s.colorOrder.slice();
    if (s.segments && Array.isArray(s.segments)) {
      _segments = s.segments.map(function (o) {
        if (o.type === 'text')    return { type: 'text', value: o.value || '' };
        if (o.type === 'floor')   return { type: 'floor', value: o.value || '' };
        if (o.type === 'counter') return { type: 'counter', tag: o.tag || '', start: o.start || 1, digits: o.digits || 3 };
        return { type: 'text', value: '' };
      });
      renderSegments();
    }
    // Migrate old structured fields into segments
    if (!s.segments && (s.clli != null || s.building != null || s.apTag != null)) {
      _segments = [];
      if (s.clli)     _segments.push({ type: 'text', value: s.clli });
      if (s.building) _segments.push({ type: 'text', value: s.building });
      if (s.floorAuto !== false) _segments.push({ type: 'floor' });
      else if (s.floor) _segments.push({ type: 'text', value: s.floor });
      if (s.suite)    _segments.push({ type: 'text', value: s.suite });
      _segments.push({ type: 'counter', tag: s.apTag || 'AP', start: s.startNumS || 1, digits: s.digitsS || 3 });
      renderSegments();
    }
    if (s.sepS != null)     $('arSepStructured').value = s.sepS;
    if (s.prefix != null)   $('arPrefix').value = s.prefix;
    if (s.sep != null)      $('arSep').value = s.sep;
    if (s.startNum != null) $('arStart').value = s.startNum;
    if (s.digits != null)   $('arDigits').value = s.digits - 1;
    if (s.macAddr != null)   $('arMacAddr').value = s.macAddr;
    if (s.macFormat != null) $('arMacFormat').value = s.macFormat;
    if (s.macOctets != null) $('arMacOctets').value = s.macOctets;
    if (s.macCase != null)   $('arMacCase').value = s.macCase;
    if (s.macPrefix != null) $('arMacPrefix').value = s.macPrefix;
    if (s.spacing)           $('arSpacing').value = s.spacing;
    else                     $('arSpacing').value = '';
    updateAll();
  }

  function saveTemplatesServer() {
    return apiSettings('update', { patch: { aprename: { templates: S.templates } } });
  }

  window.arSaveTemplate = function () {
    var name = prompt('Template name:');
    if (!name || !name.trim()) return;
    name = name.trim();
    var existing = -1;
    for (var i = 0; i < S.templates.length; i++) {
      if (S.templates[i].name === name) { existing = i; break; }
    }
    var entry = Object.assign({ name: name }, getSettings());
    if (existing >= 0) S.templates[existing] = entry;
    else S.templates.push(entry);
    saveTemplatesServer().then(function (res) {
      if (res && res.ok) toast('Template “' + name + '” saved', 'success');
      else toast('Could not save template', 'error');
    }).catch(function () { toast('Could not save template', 'error'); });
    renderTemplateSelect();
  };

  window.arDeleteTemplate = function () {
    var idx = parseInt($('arTemplateSelect').value, 10);
    if (isNaN(idx) || !S.templates[idx]) return;
    var name = S.templates[idx].name;
    S.templates.splice(idx, 1);
    saveTemplatesServer().then(function (res) {
      if (res && res.ok) toast('Template “' + name + '” deleted', 'success');
      else toast('Could not delete template', 'error');
    }).catch(function () { toast('Could not delete template', 'error'); });
    renderTemplateSelect();
  };

  /* ── dropzone ──────────────────────────────────────────────────── */
  var dropzone = $('dropzone');
  var fileInput = $('fileInput');

  dropzone.addEventListener('click', function () { fileInput.click(); });
  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', function () {
    dropzone.classList.remove('dragover');
  });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function (e) {
    if (e.target.files.length) loadFile(e.target.files[0]);
  });

  window.arLoadNew = function () {
    Object.keys(S.floorImageUrls).forEach(function (k) {
      URL.revokeObjectURL(S.floorImageUrls[k]);
    });
    S.floorImageUrls = {};
    fileInput.value = '';
    fileInput.click();
  };

  /* ── load & parse ESX ──────────────────────────────────────────── */
  function loadFile(file) {
    if (!/\.esx$/i.test(file.name)) {
      toast('Not an .esx file', 'error');
      return;
    }
    S.file = file;
    dropzone.style.display = 'none';
    $('dzTopbar').style.display = 'none';
    $('editor').classList.add('active');
    $('fileBadge').textContent = file.name;
    $('fileBadge').style.display = 'inline-block';
    // The badge truncates on a long project name, so the whole one lives here.
    $('fileBadge').title = file.name + '  —  click to open another .esx';
    $('arNoPlan').textContent = 'Reading project…';
    $('arNoPlan').style.display = '';
    $('arPlanBox').hidden = true;
    $('arDownloadBtn').disabled = true;
    $('arFloorTabs').innerHTML = '';

    file.arrayBuffer().then(function (buf) {
      return JSZip.loadAsync(buf);
    }).then(function (zip) {
      S.zip = zip;
      S.manualOrder = [];
      S.manualUndo = [];
      return parseEsx(zip);
    }).then(function () {
      if (!S.floors.length) {
        $('arNoPlan').textContent = 'This project has no floor plans.';
        return;
      }
      if (!S.aps.length) {
        $('arNoPlan').textContent = 'This project has no access points.';
        return;
      }
      adoptProjectScheme();
      renderFloorTabs();
      showFloor(S.floors[0].id);
      $('arDownloadBtn').disabled = false;
    }).catch(function (e) {
      $('arNoPlan').textContent = 'Error reading project: ' + String(e);
      toast('Could not read that file', 'error');
    });
  }

  function readJson(zip, name) {
    var f = zip.file(name);
    if (!f) return Promise.resolve(null);
    return f.async('string').then(function (txt) {
      return JSON.parse(txt);
    }).catch(function () { return null; });
  }

  function parseEsx(zip) {
    return Promise.all([
      readJson(zip, 'accessPoints.json'),
      readJson(zip, 'floorPlans.json'),
      readJson(zip, 'images.json'),
      readJson(zip, 'buildingFloors.json')
    ]).then(function (results) {
      var apData  = results[0];
      var fpData  = results[1];
      var imgData = results[2];
      var bfData  = results[3];

      S.rawAPs = (apData && apData.accessPoints) || [];
      S.aps = S.rawAPs.map(function (ap, i) {
        var loc = ap.location || {};
        var coord = loc.coord || {};
        return {
          id: ap.id,
          name: ap.name || '',
          x: coord.x || 0,
          y: coord.y || 0,
          floorPlanId: loc.floorPlanId || null,
          color: ap.color || null,
          _idx: i
        };
      });

      S.floors = ((fpData && fpData.floorPlans) || []).map(function (fp) {
        return {
          id: fp.id,
          name: fp.name || 'Unnamed',
          width: fp.width || 1,
          height: fp.height || 1,
          imageId: fp.imageId || null,
          order: 0
        };
      });

      S.imageFormats = {};
      ((imgData && imgData.images) || []).forEach(function (img) {
        S.imageFormats[img.id] = (img.imageFormat || 'PNG').toUpperCase();
      });

      ((bfData && bfData.buildingFloors) || []).forEach(function (bf) {
        var fp = S.floors.find(function (f) { return f.id === bf.floorPlanId; });
        if (fp) fp.order = bf.floorNumber != null ? bf.floorNumber : 0;
      });

      S.floors.sort(function (a, b) { return a.order - b.order; });
    });
  }

  /* ── floor tabs & image ────────────────────────────────────────── */
  function renderFloorTabs() {
    var html = '';
    S.floors.forEach(function (f) {
      var n = floorAPCount(f.id);
      html += '<button class="ar-floor-tab" data-fp="' + esc(f.id) + '">' +
              esc(f.name) + ' <span style="opacity:.5;font-size:11px">(' + n + ')</span></button>';
    });
    var unplaced = S.aps.filter(function (a) { return !a.floorPlanId; }).length;
    if (unplaced) {
      html += '<button class="ar-floor-tab" data-fp="__unplaced" style="opacity:.6">Unplaced (' + unplaced + ')</button>';
    }
    $('arFloorTabs').innerHTML = html;

    $('arFloorTabs').querySelectorAll('.ar-floor-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        showFloor(this.getAttribute('data-fp'));
      });
    });
  }

  function floorAPCount(fpId) {
    return S.aps.filter(function (a) { return a.floorPlanId === fpId; }).length;
  }

  function showFloor(fpId) {
    S.currentFloor = fpId;
    resetZoom();
    $('arFloorTabs').querySelectorAll('.ar-floor-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-fp') === fpId);
    });

    if (fpId === '__unplaced') {
      $('arPlanBox').hidden = true;
      $('arNoPlan').textContent = 'Unplaced APs have no floor-plan position.';
      $('arNoPlan').style.display = '';
      updateAll();
      return;
    }

    var floor = S.floors.find(function (f) { return f.id === fpId; });
    if (!floor) return;

    loadFloorImage(floor).then(function (url) {
      var img = $('arPlanImg');
      img.onload = function () {
        $('arNoPlan').style.display = 'none';
        $('arPlanBox').hidden = false;
        updateAll();
      };
      img.onerror = function () {
        $('arNoPlan').textContent = 'Could not decode floor-plan image.';
        $('arNoPlan').style.display = '';
        $('arPlanBox').hidden = true;
        updateAll();
      };
      img.src = url;
    }).catch(function () {
      $('arNoPlan').textContent = 'No floor-plan image found.';
      $('arNoPlan').style.display = '';
      $('arPlanBox').hidden = true;
      updateAll();
    });
  }

  function loadFloorImage(floor) {
    if (S.floorImageUrls[floor.id]) {
      return Promise.resolve(S.floorImageUrls[floor.id]);
    }
    if (!floor.imageId) return Promise.reject('no imageId');
    var entry = S.zip.file('image-' + floor.imageId);
    if (!entry) return Promise.reject('missing image blob');
    return entry.async('uint8array').then(function (data) {
      var fmt = S.imageFormats[floor.imageId] || 'PNG';
      var mime = fmt === 'JPEG' ? 'image/jpeg' : fmt === 'SVG' ? 'image/svg+xml' : 'image/png';
      var blob = new Blob([data], { type: mime });
      var url = URL.createObjectURL(blob);
      S.floorImageUrls[floor.id] = url;
      return url;
    });
  }

  /* ── sorting algorithms ────────────────────────────────────────── */
  function getFloorAPs(fpId) {
    if (fpId === '__unplaced') {
      return S.aps.filter(function (a) { return !a.floorPlanId; });
    }
    return S.aps.filter(function (a) { return a.floorPlanId === fpId; });
  }

  function getSpacingUnits(axis) {
    var px = parseInt($('arSpacing').value, 10);
    if (!px || px <= 0) return 0;
    var floor = S.currentFloor ? S.floors.find(function (f) { return f.id === S.currentFloor; }) : null;
    if (!floor) return 0;
    var img = $('arPlanImg');
    if (!img || !img.naturalWidth) return 0;
    var dim = axis === 'y' ? floor.height : floor.width;
    var imgPx = axis === 'y' ? img.naturalHeight : img.naturalWidth;
    return (px / imgPx) * dim;
  }

  function sortAPs(aps, method) {
    if (!aps.length) return [];
    var sorted = aps.slice();
    switch (method) {
      case 'row-ltr':   return sortByRow(sorted, false);
      case 'row-rtl':   return sortByRow(sorted, true);
      case 'proximity':  return sortProximity(sorted);
      case 'row-snake':  return sortSnake(sorted);
      case 'col-ttb':    return sortByColumn(sorted, false);
      case 'col-btt':    return sortByColumn(sorted, true);
      case 'clockwise':  return sortRadial(sorted, true);
      case 'counter-clockwise': return sortRadial(sorted, false);
      case 'by-color':   return sortByColorGroup(sorted, _colorOrder);
      case 'manual':     return sortManual(sorted);
    }
    return sorted;
  }

  /* ── manual click numbering ──────────────────────────────────────
     The number an AP gets is its position in S.manualOrder, which is
     append-on-click. Unnumbered APs are deliberately left out of the sorted
     list: everything downstream numbers whatever it is handed, so excluding
     them is what keeps an unclicked AP at its original name. */
  function sortManual(aps) {
    var rank = {};
    S.manualOrder.forEach(function (id, i) { rank[id] = i; });
    return aps.filter(function (ap) { return rank[ap.id] !== undefined; })
              .sort(function (a, b) { return rank[a.id] - rank[b.id]; });
  }

  function isManual() {
    var el = $('arOrder');
    return !!el && el.value === 'manual';
  }

  function manualIndex(apId) {
    return S.manualOrder.indexOf(apId);
  }

  // Snapshots rather than inverse operations: the state being undone is a
  // short array of ids, so copying it is simpler and safer than replaying.
  function manualSnapshot() {
    S.manualUndo.push(S.manualOrder.slice());
    if (S.manualUndo.length > 200) S.manualUndo.shift();
  }

  window.arManualClick = function (apId) {
    if (!isManual()) return;
    // The click that ends a pan lands on whatever was under the cursor. If the
    // pan started on a marker, that is this one — ignore it. The flag has to
    // outlive mouseup, because click fires after it.
    if (_zoom.suppressClick) { _zoom.suppressClick = false; return; }
    var at = manualIndex(apId);
    manualSnapshot();
    if (at === -1) {
      S.manualOrder.push(apId);
    } else {
      // Re-clicking a numbered AP takes it out and shifts the rest down. One
      // rule covers both "I clicked the wrong one" and "drop this from the
      // middle of the run", and the renumber is visible immediately.
      S.manualOrder.splice(at, 1);
    }
    updateAll();
  };

  window.arManualUndo = function () {
    if (!S.manualUndo.length) { toast('Nothing to undo'); return; }
    var before = S.manualOrder.length;
    S.manualOrder = S.manualUndo.pop();
    updateAll();
    // Name the number that came free, so a run of undos is followable without
    // reading the panel between each one.
    var settings = getSettings();
    var freed = getStartNum(settings) + S.manualOrder.length;
    if (S.manualOrder.length < before) {
      toast('Released ' + freed + ' — next up again');
    } else {
      toast('Undo — next is ' + freed);
    }
  };

  window.arManualClear = function () {
    if (!S.manualOrder.length) return;
    if (!confirm('Clear all ' + S.manualOrder.length + ' manual numbers?')) return;
    manualSnapshot();
    S.manualOrder = [];
    updateAll();
  };


  function updateManualPanel() {
    var panel = $('arManualPanel');
    if (!panel) return;
    var on = isManual();
    panel.hidden = !on;
    if (!on) return;
    var placed = 0;
    S.floors.forEach(function (f) { placed += getFloorAPs(f.id).length; });
    var settings = getSettings();
    $('arManualNext').textContent = String(getStartNum(settings) + S.manualOrder.length);
    $('arManualCount').textContent = S.manualOrder.length + ' of ' + placed + ' numbered';
    $('arManualUndo').disabled = !S.manualUndo.length;
    $('arManualClear').disabled = !S.manualOrder.length;
  }

  /* Number colour group by colour group, in the order the engineer chose.

     The sequence is theirs because it mirrors how the work is actually done -
     hang all the blues, come back for the oranges - and no fixed palette order
     can know which colour means what on this job.

     Colours present in the project but not placed in the sequence follow it, in
     palette order, so nothing is silently dropped. APs with no colour are
     numbered last: they are the ones nobody marked, and putting them first
     would push the deliberate groups down the sequence.

     Within a group the existing spatial ordering does the work - this changes
     which APs are handed to the numbering pass and in what order, nothing else. */
  /* ── colour sequence panel ──────────────────────────────────────
     Only the colours actually in the project are offered. Showing all ten
     Ekahau colours would mostly be a list of things this job does not use. */
  function projectColors() {
    var seen = {};
    (S.aps || []).forEach(function (ap) {
      if (!ap.color) return;
      var k = colorKey(ap.color);
      seen[k] = (seen[k] || 0) + 1;
    });
    /* Alphabetical by name, because that is a place to start looking rather
       than an order anyone wants: Ekahau's palette order is arbitrary to
       someone reading a list, and the whole point is that he drags it into
       the order the work is actually done in. Only ever the first-run
       default - once he has dragged, his order is what persists. */
    return Object.keys(seen).sort(function (a, b) {
      return colorLabel(a).localeCompare(colorLabel(b), undefined,
                                         { sensitivity: 'base' });
    }).map(function (k) { return { key: k, count: seen[k] }; });
  }

  /* Ekahau's own name for the colour where the project gives one. A custom
     hex has no name, so it is labelled as what it is rather than shown as a
     bare code - "#c0ffee" in a list you are meant to be putting in order
     tells you nothing about which one it is. */
  function colorLabel(key) {
    if (!key) return 'No colour';
    if (EKAHAU_COLORS[key]) return key.charAt(0).toUpperCase() + key.slice(1);
    if (/^#?[0-9a-f]{6}$/i.test(key)) {
      return 'Custom ' + (key.charAt(0) === '#' ? key.toUpperCase()
                                                : '#' + key.toUpperCase());
    }
    return key.charAt(0).toUpperCase() + key.slice(1);
  }

  /* The colour sequence.

     This was a picker: click a colour to append it, click x to take it out,
     and anything not picked trailed along afterwards in Ekahau's palette
     order. So the only way to get blue, yellow, green, grey was to remove
     everything and re-add it in that order, and there was no way to move one
     colour past another at all.

     It is one list now, holding every colour the project actually uses, in
     the order they will be numbered. Drag a row, or use the arrows. Nothing
     to add because nothing is missing, nothing to remove because every AP has
     to be numbered - the only question is what comes first. */

  /* Reconcile the saved sequence with the colours this project really has.
     Returns the keys that had to be appended so the panel can say so: a
     colour quietly landing at the end would still be numbered, just not where
     he expected, which is the sort of thing nobody notices until the labels
     are printed. */
  function syncColorOrder() {
    var present = projectColors();
    var byKey = {};
    present.forEach(function (c) { byKey[c.key] = c.count; });

    // A sequence carried over from another job may name colours this project
    // does not use. Those are dropped rather than shown as phantom rows.
    _colorOrder = _colorOrder.filter(function (k) { return byKey[k] != null; });

    /* "Added" only means something against an order he actually had. On a
       first run the sequence is empty, so every colour is new and badging all
       of them says nothing - the alphabetical starting order is the story
       there, not a list of surprises. */
    var hadOrder = _colorOrder.length > 0;
    var added = [];
    present.forEach(function (c) {
      if (_colorOrder.indexOf(c.key) < 0) {
        _colorOrder.push(c.key);
        if (hadOrder) added.push(c.key);
      }
    });
    return { present: present, byKey: byKey, added: added, hadOrder: hadOrder };
  }

  function moveColor(from, to) {
    if (to < 0 || to >= _colorOrder.length || from === to) return;
    var item = _colorOrder.splice(from, 1)[0];
    _colorOrder.splice(to, 0, item);
    updateAll();
  }

  function renderColorPanel() {
    var panel = $('arColorPanel');
    if (!panel) return;
    var on = $('arOrder').value === 'by-color';
    panel.hidden = !on;
    syncNestPanel();
    if (!on) return;

    var state = syncColorOrder();
    if (!state.present.length) {
      panel.innerHTML = '<div class="ar-col-note">No AP in this project has a ' +
        'colour set, so every AP is numbered by the spatial order alone.</div>';
      return;
    }

    var justAdded = {};
    state.added.forEach(function (k) { justAdded[k] = 1; });
    var last = _colorOrder.length - 1;

    var rows = _colorOrder.map(function (k, i) {
      var hex = resolveColor(k) || '#888';
      /* The position sits inside the swatch, in the AP's own colour, the same
         way it does on the plan - so this list reads like the map. Which
         means real ink: a number on Ekahau green in white cannot be read. */
      var ink = WD.readableOn(hex);
      var ring = WD.outlineOn(hex);
      /* Focusable, because dragging a row inside a narrow sidebar is fiddly
         and he works in a constrained window. Arrow keys move the focused
         colour; the buttons do the same thing for a mouse. */
      return '<div class="ar-cseq-row" draggable="true" data-i="' + i + '"' +
        ' tabindex="0" role="listitem"' +
        ' aria-label="' + esc(colorLabel(k)) + ', position ' + (i + 1) +
        ' of ' + (last + 1) + '. Use the arrow keys to move it.">' +
        '<span class="ar-cseq-grip" title="Drag to reorder">&#8801;</span>' +
        '<span class="ar-cseq-dot" style="background:' + esc(hex) +
          ';color:' + esc(ink) + ';border-color:' + esc(ring) + '">' + (i + 1) + '</span>' +
        '<span class="ar-cseq-name">' + esc(colorLabel(k)) + '</span>' +
        '<span class="ar-cseq-ct">' + state.byKey[k] +
          ' AP' + (state.byKey[k] === 1 ? '' : 's') + '</span>' +
        (justAdded[k] ? '<span class="ar-cseq-new" title="This project uses a ' +
          'colour your saved order did not cover, so it was added at the end.">' +
          'added</span>' : '') +
        '<span class="ar-cseq-btns">' +
          '<button type="button" class="ar-cseq-up" data-i="' + i + '"' +
            (i === 0 ? ' disabled' : '') + ' title="Move earlier">&#9650;</button>' +
          '<button type="button" class="ar-cseq-dn" data-i="' + i + '"' +
            (i === last ? ' disabled' : '') + ' title="Move later">&#9660;</button>' +
        '</span>' +
      '</div>';
    }).join('');

    var none = (S.aps || []).filter(function (a) { return !a.color; }).length;
    var note = '';
    if (state.added.length) {
      note += state.added.length + ' colour' + (state.added.length === 1 ? '' : 's') +
        ' in this project ' + (state.added.length === 1 ? 'was' : 'were') +
        ' not in your saved order, so ' +
        (state.added.length === 1 ? 'it was' : 'they were') +
        ' added at the end. ';
    }
    note += none
      ? String(none) + ' AP' + (none === 1 ? '' : 's') + ' with no colour set ' +
        (none === 1 ? 'is' : 'are') + ' numbered last, after every colour. '
      : 'Every AP in this project has a colour. ';
    note += 'Within a colour, the ordering above decides the sequence.';

    panel.innerHTML =
      '<div class="ar-cseq-lab">Number the colours in this order' +
        (state.hadOrder ? '' : ' <span class="ar-cseq-hint">' +
          '— alphabetical to start; drag to reorder</span>') + '</div>' +
      '<div class="ar-cseq">' + rows + '</div>' +
      '<div class="ar-col-note">' + esc(note) + '</div>';

    panel.querySelectorAll('.ar-cseq-up').forEach(function (b) {
      b.onclick = function () {
        var i = parseInt(b.getAttribute('data-i'), 10);
        moveColor(i, i - 1);
      };
    });
    panel.querySelectorAll('.ar-cseq-dn').forEach(function (b) {
      b.onclick = function () {
        var i = parseInt(b.getAttribute('data-i'), 10);
        moveColor(i, i + 1);
      };
    });
    // Drag, the same way the segment builder does it.
    panel.querySelectorAll('.ar-cseq-row').forEach(function (row) {
      var i = parseInt(row.getAttribute('data-i'), 10);
      row.addEventListener('keydown', function (e) {
        var to = e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? i - 1
               : e.key === 'ArrowDown' || e.key === 'ArrowRight' ? i + 1 : null;
        if (to == null) return;
        e.preventDefault();
        moveColor(i, to);
        // Re-rendered underneath us; keep the colour he is moving in hand.
        var moved = panel.querySelectorAll('.ar-cseq-row')[Math.max(0,
          Math.min(_colorOrder.length - 1, to))];
        if (moved) moved.focus();
      });
      row.addEventListener('dragstart', function (e) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(i));
        row.style.opacity = '.4';
      });
      row.addEventListener('dragend', function () { row.style.opacity = ''; });
      row.addEventListener('dragover', function (e) {
        e.preventDefault(); e.dataTransfer.dropEffect = 'move';
      });
      row.addEventListener('drop', function (e) {
        e.preventDefault();
        var from = parseInt(e.dataTransfer.getData('text/plain'), 10);
        if (!isNaN(from)) moveColor(from, i);
      });
    });
  }
  window.arRenderColorPanel = renderColorPanel;

  var _colorPanelSyncing = false;
  function syncColorPanelVisibility() {
    if (_colorPanelSyncing) return;
    _colorPanelSyncing = true;
    try { renderColorPanel(); } finally { _colorPanelSyncing = false; }
  }

  /* Group APs by colour and put the groups in the engineer's chosen order.

     Split out from sortByColorGroup because the two nestings need the same
     answer to "which colour comes first" while walking the project in
     different orders: floor-major asks once per floor, colour-major asks once
     for the whole building. One implementation of the ordering, two traversals
     over it. */
  function groupByColor(aps, colorOrder) {
    var order = (colorOrder || []).map(function (c) { return String(c).toLowerCase().trim(); });
    var groups = {};
    aps.forEach(function (ap) {
      var key = colorKey(ap.color);
      if (!groups[key]) groups[key] = [];
      groups[key].push(ap);
    });
    function rank(k) {
      if (k === '__none') return 2e6;                 // unmarked APs go last
      var i = order.indexOf(k);
      if (i >= 0) return i;                           // chosen sequence first
      return 1e6 + colorSortKey(k);                   // then the rest, palette order
    }
    var keys = Object.keys(groups).sort(function (a, b) {
      var d = rank(a) - rank(b);
      return d !== 0 ? d : (a < b ? -1 : 1);
    });
    return { keys: keys, groups: groups };
  }

  function sortByColorGroup(aps, colorOrder) {
    var g = groupByColor(aps, colorOrder);
    var result = [];
    g.keys.forEach(function (k) {
      var one = sortNearestNeighbor(g.groups[k]);
      for (var i = 0; i < one.length; i++) result.push(one[i]);
    });
    return result;
  }

  /* Proximity: walk to whichever AP is nearest, the way the snake game eats.

     Two things make it usable rather than merely short. It always starts from
     the AP closest to the top-left of the group, so the same project numbers
     the same way every time instead of beginning wherever the topmost AP
     happened to land. And the greedy walk is cleaned up afterwards, because
     greedy strands outliers: it consumes a dense cluster, skips the AP just
     outside it, and has to cross the whole building to collect it at the end.
     On a real 29-AP floor that last hop was nearly three times the average.

     The cleanup is 2-opt plus or-opt, which is heavy-handed for a travelling
     salesman and completely free here - a floor has tens of APs, not
     thousands, so a few full passes cost nothing and remove exactly the long
     recrossing hops that make a sequence unfollowable. */
  function sortProximity(aps) {
    if (aps.length < 3) return sortNearestNeighbor(aps);
    var tour = greedyWalk(aps, startCorner(aps));
    tour = twoOpt(tour);
    tour = orOpt(tour);
    return tour;
  }

  function dist2(a, b) {
    var dx = a.x - b.x, dy = a.y - b.y;
    return dx * dx + dy * dy;
  }
  function dist(a, b) { return Math.sqrt(dist2(a, b)); }

  // The AP nearest the top-left of the group's own bounding box, so the answer
  // does not move when the plan has empty canvas around it.
  function startCorner(aps) {
    var minX = Infinity, minY = Infinity;
    aps.forEach(function (a) {
      if (a.x < minX) minX = a.x;
      if (a.y < minY) minY = a.y;
    });
    var corner = { x: minX, y: minY };
    var best = 0, bestD = Infinity;
    for (var i = 0; i < aps.length; i++) {
      var d = dist2(aps[i], corner);
      // ties resolve the same way every time
      if (d < bestD - 1e-9 ||
          (Math.abs(d - bestD) <= 1e-9 && aps[i].y < aps[best].y)) {
        bestD = d; best = i;
      }
    }
    return best;
  }

  function greedyWalk(aps, startIdx) {
    var remaining = aps.slice();
    var result = [remaining.splice(startIdx, 1)[0]];
    while (remaining.length) {
      var last = result[result.length - 1];
      var bestIdx = 0, bestDist = Infinity;
      for (var i = 0; i < remaining.length; i++) {
        var d = dist2(remaining[i], last);
        if (d < bestDist) { bestDist = d; bestIdx = i; }
      }
      result.push(remaining.splice(bestIdx, 1)[0]);
    }
    return result;
  }

  /* Reverse any run whose two end links cross. The first AP stays first - the
     starting corner is a promise, not something to optimise away. */
  function twoOpt(t) {
    var n = t.length, improved = true, guard = 0;
    while (improved && guard++ < 60) {
      improved = false;
      for (var i = 1; i < n - 2; i++) {
        for (var k = i + 1; k < n - 1; k++) {
          var before = dist(t[i - 1], t[i]) + dist(t[k], t[k + 1]);
          var after = dist(t[i - 1], t[k]) + dist(t[i], t[k + 1]);
          if (after < before - 1e-9) {
            var seg = t.slice(i, k + 1).reverse();
            t = t.slice(0, i).concat(seg, t.slice(k + 1));
            improved = true;
          }
        }
      }
    }
    return t;
  }

  /* Lift a run of one to three APs out and drop it where it costs least. This
     is what actually rescues the stranded outlier: 2-opt can only reverse, so
     an AP sitting on its own needs moving rather than flipping. */
  function orOpt(t) {
    var improved = true, guard = 0;
    while (improved && guard++ < 60) {
      improved = false;
      for (var len = 1; len <= 3 && !improved; len++) {
        // i starts at 1: the first AP is the chosen corner and stays put.
        for (var i = 1; i + len <= t.length && !improved; i++) {
          var seg = t.slice(i, i + len);
          var rest = t.slice(0, i).concat(t.slice(i + len));
          if (!rest.length) continue;
          // Taking the run out closes the gap it leaves behind. Links inside
          // the run survive the move, so they cancel and are left out.
          var saved = 0;
          if (i > 0) saved += dist(t[i - 1], seg[0]);
          if (i + len < t.length) saved += dist(seg[len - 1], t[i + len]);
          if (i > 0 && i + len < t.length) saved -= dist(t[i - 1], t[i + len]);

          var bestGain = 1e-9, bestAt = -1, bestRev = false;
          for (var j = 1; j <= rest.length; j++) {
            for (var rev = 0; rev < 2; rev++) {
              var piece = rev ? seg.slice().reverse() : seg;
              var gain = saved - spliceCost(rest, j, piece);
              if (gain > bestGain) { bestGain = gain; bestAt = j; bestRev = !!rev; }
            }
          }
          if (bestAt >= 0) {
            var moved = bestRev ? seg.slice().reverse() : seg;
            t = rest.slice(0, bestAt).concat(moved, rest.slice(bestAt));
            improved = true;
          }
        }
      }
    }
    return t;
  }

  // What it costs to open `rest` at j and drop `piece` in.
  function spliceCost(rest, j, piece) {
    var prev = rest[j - 1], next = rest[j], add = 0;
    if (prev) add += dist(prev, piece[0]);
    if (next) add += dist(piece[piece.length - 1], next);
    if (prev && next) add -= dist(prev, next);
    return add;
  }

  /* A real snake: rows top to bottom, every other row reversed, so the walk
     turns at the end of a row instead of flying back to the near edge. */
  function sortSnake(aps) {
    if (aps.length < 2) return aps.slice();
    var sp = getSpacingUnits('y');
    var rows = sp > 0 ? clusterByFixedSpacing(aps, 'y', sp) : clusterByAxis(aps, 'y');
    rows.sort(function (a, b) { return avg(a, 'y') - avg(b, 'y'); });
    var result = [];
    rows.forEach(function (row, i) {
      row.sort(function (a, b) { return i % 2 ? b.x - a.x : a.x - b.x; });
      for (var j = 0; j < row.length; j++) result.push(row[j]);
    });
    return result;
  }

  function _dist(a, b) {
    var dx = a.x - b.x, dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  /* 2-opt on an open path: uncross the route.

     Reversing the run p[i..j] swaps the edges (i-1,i) and (j,j+1) for
     (i-1,j) and (i,j+1). Where j is the last stop there is no following
     edge, so the move is simply "turn the tail around", which is still
     worth testing - a greedy walk very often ends by doubling back. */
  function _twoOpt(p) {
    var n = p.length, changed = false;
    for (var i = 1; i < n - 1; i++) {
      for (var j = i + 1; j < n; j++) {
        var a = p[i - 1], b = p[i], c = p[j];
        var before, after;
        if (j + 1 < n) {
          var d = p[j + 1];
          before = _dist(a, b) + _dist(c, d);
          after  = _dist(a, c) + _dist(b, d);
        } else {
          before = _dist(a, b);
          after  = _dist(a, c);
        }
        if (after < before - 1e-9) {
          for (var lo = i, hi = j; lo < hi; lo++, hi--) {
            var t = p[lo]; p[lo] = p[hi]; p[hi] = t;
          }
          changed = true;
        }
      }
    }
    return changed;
  }

  /* Or-opt: lift a run of 1-3 stops out and re-insert it where it belongs.

     This is the one that rescues a stranded AP. 2-opt can only reverse a
     run, so it cannot rescue a single unit the greedy walk visited at the
     wrong moment; or-opt picks it up and drops it next to its neighbours.
     Both orientations of the lifted run are tried. */
  function _orOpt(p) {
    var n = p.length, changed = false;
    for (var L = 1; L <= 3; L++) {
      for (var i = 1; i + L <= n; i++) {
        var prev = p[i - 1], segFirst = p[i], segLast = p[i + L - 1];
        var after = i + L;
        var removed = _dist(prev, segFirst)
                    + (after < n ? _dist(segLast, p[after]) : 0)
                    - (after < n ? _dist(prev, p[after]) : 0);
        if (removed <= 1e-9) continue;          // lifting it saves nothing
        var seg = p.slice(i, i + L);
        var rest = p.slice(0, i).concat(p.slice(i + L));
        var bestGain = 1e-9, bestPos = -1, bestRev = false;
        for (var k = 1; k <= rest.length; k++) {
          var A = rest[k - 1], B = (k < rest.length ? rest[k] : null);
          for (var r = 0; r < 2; r++) {
            var head = r ? seg[L - 1] : seg[0];
            var tail = r ? seg[0] : seg[L - 1];
            var added = _dist(A, head) + (B ? _dist(tail, B) : 0)
                      - (B ? _dist(A, B) : 0);
            if (removed - added > bestGain) {
              bestGain = removed - added; bestPos = k; bestRev = !!r;
            }
          }
        }
        if (bestPos >= 0) {
          var put = bestRev ? seg.slice().reverse() : seg;
          rest.splice.apply(rest, [bestPos, 0].concat(put));
          for (var q = 0; q < n; q++) p[q] = rest[q];
          changed = true;
        }
      }
    }
    return changed;
  }

  /* Greedy nearest-neighbour is fast and it strands outliers: it takes the
     closest unvisited AP every time, so the one on the far side of the floor
     is left until the walk has no choice, and the sequence ends with a long
     trek back. That gets *more* likely inside a colour group, which is often
     a handful of APs scattered over a floor rather than a cluster.

     So the greedy walk is a first draft, and these passes clean it up. They
     run on every proximity ordering, at every size - a five-AP group with one
     outlier is exactly where the fix matters, and it is far too small for the
     cost to matter. Only strictly-improving moves are taken, scanned in a
     fixed order, so the result is reproducible.

     The one guard is at the top end: a floor with hundreds of APs re-sorts on
     every keystroke, so the number of rounds tightens as the set grows. */
  function _improvePath(p) {
    var n = p.length;
    if (n < 4) return p;
    var limit = n <= 60 ? 12 : (n <= 200 ? 6 : 3);
    var rounds = 0, moved = true;
    while (moved && rounds++ < limit) {
      var a = _twoOpt(p);
      var b = _orOpt(p);
      moved = a || b;
    }
    return p;
  }

  function sortNearestNeighbor(aps) {
    if (aps.length < 2) return aps.slice();
    var remaining = aps.slice();
    // Deterministic start: the top-left-most AP, so the same project always
    // numbers the same way.
    remaining.sort(function (a, b) { return a.y - b.y || a.x - b.x; });
    var result = [remaining.shift()];
    while (remaining.length) {
      var last = result[result.length - 1];
      var bestIdx = 0;
      var bestDist = Infinity;
      for (var i = 0; i < remaining.length; i++) {
        var dx = remaining[i].x - last.x;
        var dy = remaining[i].y - last.y;
        var d = dx * dx + dy * dy;
        if (d < bestDist) { bestDist = d; bestIdx = i; }
      }
      result.push(remaining.splice(bestIdx, 1)[0]);
    }
    return _improvePath(result);
  }

  function sortByRow(aps, reverse) {
    if (aps.length < 2) return aps.slice();
    var sp = getSpacingUnits('y');
    var rows = sp > 0 ? clusterByFixedSpacing(aps, 'y', sp) : clusterByAxis(aps, 'y');
    rows.sort(function (a, b) { return avg(a, 'y') - avg(b, 'y'); });
    var result = [];
    rows.forEach(function (row) {
      row.sort(function (a, b) {
        return reverse ? b.x - a.x : a.x - b.x;
      });
      for (var j = 0; j < row.length; j++) result.push(row[j]);
    });
    return result;
  }

  function sortByColumn(aps, reverse) {
    if (aps.length < 2) return aps.slice();
    var sp = getSpacingUnits('x');
    var cols = sp > 0 ? clusterByFixedSpacing(aps, 'x', sp) : clusterByAxis(aps, 'x');
    cols.sort(function (a, b) { return avg(a, 'x') - avg(b, 'x'); });
    var result = [];
    cols.forEach(function (col) {
      col.sort(function (a, b) {
        return reverse ? b.y - a.y : a.y - b.y;
      });
      for (var j = 0; j < col.length; j++) result.push(col[j]);
    });
    return result;
  }

  function sortRadial(aps, clockwise) {
    if (aps.length < 2) return aps.slice();
    var cx = avg(aps, 'x');
    var cy = avg(aps, 'y');
    var withAngle = aps.map(function (a) {
      var dx = a.x - cx;
      var dy = a.y - cy;
      var angle = Math.atan2(dx, -dy);
      if (angle < 0) angle += 2 * Math.PI;
      return { ap: a, angle: angle };
    });
    withAngle.sort(function (a, b) {
      return clockwise ? a.angle - b.angle : b.angle - a.angle;
    });
    return withAngle.map(function (w) { return w.ap; });
  }

  function clusterByAxis(aps, axis) {
    if (aps.length <= 1) return [aps.slice()];
    var sorted = aps.slice().sort(function (a, b) { return a[axis] - b[axis]; });
    var gaps = [];
    for (var i = 1; i < sorted.length; i++) {
      gaps.push(sorted[i][axis] - sorted[i - 1][axis]);
    }
    var sortedGaps = gaps.slice().sort(function (a, b) { return a - b; });
    var median = sortedGaps[Math.floor(sortedGaps.length / 2)];
    var threshold = Math.max(median * 2.5, 0.001);
    var clusters = [];
    var current = [sorted[0]];
    for (var j = 1; j < sorted.length; j++) {
      if (sorted[j][axis] - sorted[j - 1][axis] > threshold) {
        clusters.push(current);
        current = [];
      }
      current.push(sorted[j]);
    }
    clusters.push(current);
    return clusters;
  }

  function clusterByFixedSpacing(aps, axis, spacing) {
    var buckets = {};
    aps.forEach(function (ap) {
      var idx = Math.floor(ap[axis] / spacing);
      if (!buckets[idx]) buckets[idx] = [];
      buckets[idx].push(ap);
    });
    var keys = Object.keys(buckets).sort(function (a, b) { return a - b; });
    return keys.map(function (k) { return buckets[k]; });
  }

  function avg(arr, key) {
    if (!arr.length) return 0;
    var sum = 0;
    for (var i = 0; i < arr.length; i++) sum += arr[i][key] || 0;
    return sum / arr.length;
  }

  /* ── naming ────────────────────────────────────────────────────── */
  function padNum(n, digits) {
    var s = String(n);
    while (s.length < digits) s = '0' + s;
    return s;
  }

  function generateName(settings, floor, num) {
    if (settings.mode === 'structured') return buildStructuredName(floor, num);
    if (settings.mode === 'mac')        return buildMacName(num);
    return settings.prefix + settings.sep + padNum(num, settings.digits);
  }

  function getStartNum(settings) {
    if (settings.mode === 'structured') {
      for (var i = 0; i < _segments.length; i++) {
        if (_segments[i].type === 'counter') return _segments[i].start || 1;
      }
      return 1;
    }
    if (settings.mode === 'mac') return 1;
    return settings.startNum;
  }

  /* The order APs are handed to the numbering pass, as a flat list of
     {floor, ap}. Two nestings, because "do all the blues" means two different
     jobs depending on how the work is actually done:

       floor-major  floor 1's blues, greens, greys; then floor 2's, and so on.
                    You finish a floor before going up a ladder to the next.
       colour-major all the blues on every floor, then every green, then every
                    grey. You carry one box of hardware through the building.

     Only the sequence changes. generatePreview() below remains the single
     place a number is decided - this returns who is next, never what they are
     called. */
  function buildSequence(settings) {
    var seq = [];
    if (settings.order === 'by-color' && _nesting === 'color') {
      var everyone = [];
      S.floors.forEach(function (floor) {
        getFloorAPs(floor.id).forEach(function (ap) {
          everyone.push({ floor: floor, ap: ap });
        });
      });
      var g = groupByColor(everyone.map(function (x) { return x.ap; }), _colorOrder);
      var floorOf = {};
      everyone.forEach(function (x) { floorOf[x.ap.id] = x.floor; });
      g.keys.forEach(function (key) {
        // Within one colour, walk the floors in their own order, and within a
        // floor fall back to the spatial ordering rather than inventing one.
        var byFloor = {};
        g.groups[key].forEach(function (ap) {
          var fid = floorOf[ap.id].id;
          (byFloor[fid] = byFloor[fid] || []).push(ap);
        });
        S.floors.forEach(function (floor) {
          var here = byFloor[floor.id];
          if (!here) return;
          sortNearestNeighbor(here).forEach(function (ap) {
            seq.push({ floor: floor, ap: ap });
          });
        });
      });
      return seq;
    }
    S.floors.forEach(function (floor) {
      sortAPs(getFloorAPs(floor.id), settings.order).forEach(function (ap) {
        seq.push({ floor: floor, ap: ap });
      });
    });
    return seq;
  }

  function generatePreview() {
    var settings = getSettings();
    var allItems = [];
    var start = getStartNum(settings);
    var num = start;

    // One pass, one counter, whatever the traversal was.
    var seq = buildSequence(settings);
    var colorMajor = settings.order === 'by-color' && _nesting === 'color';
    var numbered = {};
    var byFloorItems = {};
    var lastFloorId = null;
    seq.forEach(function (step) {
      /* Restarting per floor only means anything while the walk stays on a
         floor until it is done. Colour-major leaves and comes back, so the
         two are mutually exclusive and the UI forces continuous there - this
         guard is the same rule stated where the counter actually lives. */
      if (_scope === 'perFloor' && !(settings.order === 'by-color' && _nesting === 'color')
          && step.floor.id !== lastFloorId) {
        num = start;
      }
      lastFloorId = step.floor.id;
      numbered[step.ap.id] = 1;
      var item = { ap: step.ap, oldName: step.ap.name,
                   newName: generateName(settings, step.floor, num),
                   floorId: step.floor.id, num: num };
      num++;
      /* Colour-major is listed in the order it will number, because that
         sequence is the thing being chosen and it is invisible anywhere else.
         Floor-major keeps the floor-by-floor table it has always had - which
         is also the only readable shape when the counter restarts per floor. */
      if (colorMajor) allItems.push(item);
      else (byFloorItems[step.floor.id] = byFloorItems[step.floor.id] || []).push(item);
    });

    // In manual mode sortAPs only returns the clicked APs, so the rest are
    // listed unchanged rather than silently vanishing from the preview.
    S.floors.forEach(function (floor) {
      if (!colorMajor) {
        (byFloorItems[floor.id] || []).forEach(function (it) { allItems.push(it); });
      }
      getFloorAPs(floor.id).forEach(function (ap) {
        if (!numbered[ap.id]) {
          allItems.push({ ap: ap, oldName: ap.name, newName: ap.name,
                          floorId: floor.id, unnumbered: true, num: null });
        }
      });
    });

    var unplaced = getFloorAPs('__unplaced');
    unplaced.forEach(function (ap) {
      allItems.push({ ap: ap, oldName: ap.name, newName: ap.name,
                      floorId: null, num: null });
    });

    S.preview = allItems;
    S.byId = {};
    allItems.forEach(function (it) { S.byId[it.ap.id] = it; });
    return allItems;
  }

  function updateSpacingVisibility() {
    updateManualPanel();
    var order = $('arOrder').value;
    var show = order === 'row-ltr' || order === 'row-rtl' ||
               order === 'col-ttb' || order === 'col-btt' ||
               order === 'row-snake';
    $('arSpacingRow').hidden = !show;
  }

  /* ── render ────────────────────────────────────────────────────── */
  function updateAll() {
    updateSpacingVisibility();
    syncColorPanelVisibility();
    var items = generatePreview();
    renderMarkers();
    renderPreviewTable(items);
    updateDownloadBtn();
  }


  function renderGuideLines(box, floor, order) {
    var old = box.querySelectorAll('.ar-guide');
    for (var i = 0; i < old.length; i++) old[i].remove();

    var isRow = order === 'row-ltr' || order === 'row-rtl';
    var isCol = order === 'col-ttb' || order === 'col-btt';
    if (!isRow && !isCol) return;

    var px = parseInt($('arSpacing').value, 10);
    if (!px || px <= 0) return;

    var img = $('arPlanImg');
    if (!img || !img.naturalWidth) return;
    var imgDim = isRow ? img.naturalHeight : img.naturalWidth;
    var count = Math.floor(imgDim / px);

    for (var n = 1; n <= count; n++) {
      var pct = (n * px / imgDim * 100).toFixed(3) + '%';
      var line = document.createElement('div');
      line.className = 'ar-guide ' + (isRow ? 'ar-guide-h' : 'ar-guide-v');
      if (isRow) line.style.top = pct;
      else       line.style.left = pct;
      box.appendChild(line);
    }
  }

  function renderMarkers() {
    var box = $('arPlanBox');
    var old = box.querySelectorAll('.ar-marker');
    for (var k = 0; k < old.length; k++) old[k].remove();

    if (!S.currentFloor || S.currentFloor === '__unplaced') return;
    var floor = S.floors.find(function (f) { return f.id === S.currentFloor; });
    if (!floor || !floor.width || !floor.height) return;

    var settings = getSettings();
    var manual = settings.order === 'manual';
    renderGuideLines(box, floor, settings.order);
    var floorAPs = getFloorAPs(S.currentFloor);
    var sorted = sortAPs(floorAPs, settings.order);
    S.sorted = sorted;

    // Manual mode still draws the APs nobody has clicked yet — you cannot pick
    // the next one if it is not on the plan.
    if (manual) {
      var clicked = {};
      sorted.forEach(function (ap) { clicked[ap.id] = 1; });
      floorAPs.forEach(function (ap) {
        if (clicked[ap.id]) return;
        var m = document.createElement('div');
        m.className = 'ar-marker is-unnumbered is-clickable';
        m.style.left = (ap.x / floor.width * 100) + '%';
        m.style.top  = (ap.y / floor.height * 100) + '%';
        // Ring the marker in its own AP colour. Without this every un-clicked
        // AP is the same white-with-a-dashed-ring, which makes "start with the
        // blue ones" impossible to do by eye - the one view where you are
        // picking APs by colour was the one view that did not show them.
        var uc = resolveColor(ap.color);
        if (uc) { m.style.borderColor = uc; m.style.color = uc; }
        m.textContent = '+';
        m.setAttribute('data-ap-id', ap.id);
        m.onclick = function (e) { e.stopPropagation(); arManualClick(ap.id); };
        var t = document.createElement('span');
        t.className = 'ar-tip';
        t.textContent = ap.name + ' \u2014 click to number';
        m.appendChild(t);
        box.appendChild(m);
      });
    }

    sorted.forEach(function (ap, idx) {
      var item = S.byId[ap.id] || {};
      var num = item.num;
      var fracX = ap.x / floor.width;
      var fracY = ap.y / floor.height;
      var newName = item.newName || ap.name;

      var marker = document.createElement('div');
      marker.className = 'ar-marker' + (manual ? ' is-clickable' : '') +
        (manual && idx === sorted.length - 1 ? ' is-last' : '');
      if (manual) {
        marker.onclick = function (e) { e.stopPropagation(); arManualClick(ap.id); };
      }
      marker.style.left = (fracX * 100) + '%';
      marker.style.top  = (fracY * 100) + '%';
      var numStr = num == null ? '\u2013' : String(num);
      marker.textContent = numStr;
      if (numStr.length >= 3) marker.classList.add('is-wide');
      marker.setAttribute('data-ap-id', ap.id);

      var resolved = resolveColor(ap.color);
      if (resolved) {
        marker.style.background = resolved;
        marker.style.color = WD.readableOn(resolved);
        // The default ring is white, which is fine on screen and disappears on
        // a white CAD plan the moment the fill is pale - yellow or cyan with a
        // white ring on white paper is the marker not being there at all. The
        // ring is darkened in proportion to how close the fill is to the paper.
        marker.style.borderColor = WD.outlineOn(resolved);
      } else {
        marker.classList.add('is-clear');
      }

      var tip = document.createElement('span');
      tip.className = 'ar-tip';
      tip.textContent = ap.name + ' → ' + newName +
        (manual ? '  (click to remove)' : '');
      marker.appendChild(tip);

      box.appendChild(marker);
    });
  }

  /* The structured pattern gives every AP on a floor the same leading
     segments - FTCL3-01-00-01- - so the only thing that differs row to row is
     the tail. Hoisting that stem out of the rows is what makes the diff
     readable in a narrow panel instead of wrapping onto two lines.

     The stem is only taken at a separator boundary, so a name is never cut
     mid-segment, and only when it leaves something behind on every row. */

  function tailOf(full, stem) {
    if (!full || !stem || full.indexOf(stem) !== 0) return '';
    return full.slice(stem.length);
  }

  function commonStem(names) {
    if (names.length < 2) return '';
    var first = names[0];
    var i = 0;
    while (i < first.length) {
      var ch = first[i];
      var all = true;
      for (var k = 1; k < names.length; k++) {
        if (names[k][i] !== ch) { all = false; break; }
      }
      if (!all) break;
      i++;
    }
    var prefix = first.slice(0, i);
    var cut = Math.max(prefix.lastIndexOf('-'), prefix.lastIndexOf('_'),
                       prefix.lastIndexOf('.'), prefix.lastIndexOf(' '));
    if (cut < 0) return '';
    var stem = prefix.slice(0, cut + 1);
    if (stem.length < 4) return '';
    for (var j = 0; j < names.length; j++) {
      if (names[j].length <= stem.length) return '';
    }
    return stem;
  }

  function renderPreviewTable(allItems) {
    var items;
    if (S.currentFloor === '__unplaced') {
      items = allItems.filter(function (it) { return !it.floorId; });
    } else if (S.currentFloor) {
      items = allItems.filter(function (it) { return it.floorId === S.currentFloor; });
    } else {
      items = allItems;
    }
    if ($('arOrder').value === 'manual') {
      items = items.slice().sort(function (a, b) {
        var ra = manualIndex(a.ap.id), rb = manualIndex(b.ap.id);
        if (ra === -1 && rb === -1) return 0;
        if (ra === -1) return 1;
        if (rb === -1) return -1;
        return ra - rb;
      });
    }
    var changed = items.filter(function (it) { return it.oldName !== it.newName; }).length;
    $('arPreviewHead').textContent = 'Preview (' + items.length + ' APs, ' + changed + ' labeled)';

    var stemOld = commonStem(items.map(function (it) { return it.oldName || ''; }));
    var stemNew = commonStem(items.map(function (it) { return it.newName || ''; }));
    var stemEl = $('arStem');
    if (stemEl) {
      if (stemOld || stemNew) {
        var sample = items[0] || {};
        var stemChanged = stemOld !== stemNew;
        function side(key, stem, full, cls) {
          var body = stem
            ? '<span class="ar-stem-body"><span class="ar-stem-val">' + esc(stem) + '</span>'
              + '<span class="ar-stem-tail">' + esc(tailOf(full, stem)) + '</span></span>'
            : '<span class="ar-stem-none">nothing in common</span>';
          return '<div class="ar-stem-line ' + cls + '">'
            + '<span class="ar-stem-key">' + key + '</span>' + body + '</div>';
        }
        stemEl.hidden = false;
        stemEl.innerHTML =
          '<div class="ar-stem-cap">Every name on this floor'
          + (stemChanged ? '<span class="ar-stem-chg">changing</span>' : '') + '</div>'
          + side('Current', stemOld, sample.oldName || '', '')
          + side('New', stemNew, sample.newName || '', 'is-new');
      } else {
        stemEl.hidden = true;
        stemEl.innerHTML = '';
      }
    }

    var body = $('arPreviewBody');
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:16px;color:var(--text-2,#666)">No access points on this floor</td></tr>';
      return;
    }
    var html = '';
    var manual = $('arOrder').value === 'manual';
    var PREVIEW_CAP = 5;
    var showAll = S._showAllPreview;
    var visCount = (showAll || items.length <= PREVIEW_CAP + 1) ? items.length : PREVIEW_CAP;
    items.forEach(function (it, i) {
      if (i >= visCount) return;
      var isDiff = it.oldName !== it.newName;
      // In manual mode the left column is the assigned position, so an
      // unclicked AP reads as "-" rather than borrowing a row number.
      var seq = it.num == null ? '\u2013' : String(it.num);
      var swatch = '';
      var rc = resolveColor(it.ap.color);
      if (rc) {
        // Not WD.outlineOn(): that returns a black ring sized for white paper,
        // which is what the plan is. This swatch sits on the panel, which is
        // dark by default and light only under [data-theme=light] - so ring
        // the pale ones, which are the only ones the light theme can lose.
        var border = WD.needsDarkText(rc) ? '1px solid rgba(0,0,0,.2)' : 'none';
        swatch = '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + rc + ';border:' + border + ';vertical-align:middle;margin-right:4px"></span>';
      } else {
        swatch = '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#fff;border:2px solid #222;vertical-align:middle;margin-right:4px;box-sizing:border-box"></span>';
      }
      var curTxt = it.oldName || '—';
      var newTxt = it.newName || '';
      var curShown = (stemOld && curTxt.indexOf(stemOld) === 0) ? curTxt.slice(stemOld.length) : curTxt;
      var newShown = (stemNew && newTxt.indexOf(stemNew) === 0) ? newTxt.slice(stemNew.length) : newTxt;
      html += '<tr class="' + (isDiff ? 'changed' : '') +
        (it.unnumbered ? ' unnumbered' : '') + '">' +
        '<td class="ar-num">' + seq + '</td>' +
        '<td class="ar-cur" title="' + esc(curTxt) + '">' + swatch + esc(curShown) + '</td>' +
        '<td class="ar-arrow">→</td>' +
        '<td class="ar-new" title="' + esc(newTxt) + '">' + esc(newShown) + '</td>' +
        '</tr>';
    });

    if (visCount < items.length) {
      html += '<tr><td colspan="4" style="text-align:center;padding:6px">'
        + '<button type="button" class="ar-show-all-btn" onclick="window._arShowAll()">'
        + 'Show all ' + items.length + ' (' + (items.length - visCount) + ' more)</button></td></tr>';
    } else if (showAll && items.length > PREVIEW_CAP + 1) {
      html += '<tr><td colspan="4" style="text-align:center;padding:6px">'
        + '<button type="button" class="ar-show-all-btn" onclick="window._arShowAll()">Collapse</button></td></tr>';
    }
    body.innerHTML = html;
  }

  function updateDownloadBtn() {
    var hasChanges = S.preview.some(function (it) { return it.oldName !== it.newName; });
    $('arDownloadBtn').disabled = !hasChanges;
  }

  window._arShowAll = function () {
    S._showAllPreview = !S._showAllPreview;
    // renderPreviewTable needs the items; called bare it threw on the first
    // line and the button did nothing at all, silently, every time.
    renderPreviewTable(S.preview || []);
  };

  /* ── download ──────────────────────────────────────────────────── */
  window.arDownload = function () {
    if (!S.zip || !S.preview.length) return;

    var renameMap = {};
    S.preview.forEach(function (it) {
      if (it.oldName !== it.newName) {
        renameMap[it.ap.id] = it.newName;
      }
    });
    if (!Object.keys(renameMap).length) {
      toast('Nothing to label', 'error');
      return;
    }

    var modifiedAPs = JSON.parse(JSON.stringify(S.rawAPs));
    modifiedAPs.forEach(function (ap) {
      if (renameMap[ap.id] != null) ap.name = renameMap[ap.id];
    });

    var json = JSON.stringify({ accessPoints: modifiedAPs }, null, 1);
    S.zip.file('accessPoints.json', json);

    $('arDownloadBtn').disabled = true;
    $('arDownloadBtn').textContent = 'Building…';

    S.zip.generateAsync({ type: 'blob' }).then(function (blob) {
      var name = S.file.name.replace(/\.esx$/i, '') + ' (labeled).esx';
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(url); }, 4000);

      $('arDownloadBtn').disabled = false;
      $('arDownloadBtn').textContent = 'Download labeled .esx';
      toast('Downloaded ' + name, 'success');
    }).catch(function (e) {
      $('arDownloadBtn').disabled = false;
      $('arDownloadBtn').textContent = 'Download labeled .esx';
      toast('Download failed: ' + e, 'error');
    });
  };

  /* ── control listeners ─────────────────────────────────────────── */
  ['arOrder', 'arPrefix', 'arSep', 'arStart', 'arDigits',
   'arSepStructured',
   'arMacAddr', 'arMacFormat', 'arMacOctets', 'arMacCase', 'arMacPrefix',
   'arSpacing'].forEach(function (id) {
    var el = $(id);
    if (!el) return;
    el.addEventListener('change', updateAll);
    if (el.tagName === 'INPUT') el.addEventListener('input', updateAll);
  });

  $('arTemplateSelect').addEventListener('change', function () {
    var idx = parseInt(this.value, 10);
    if (isNaN(idx) || !S.templates[idx]) return;
    applySettings(S.templates[idx]);
    toast('Loaded template “' + S.templates[idx].name + '”', 'success');
  });

  /* ── zoom & pan ─────────────────────────────────────────────────── */
  var _zoom = { scale: 1, tx: 0, ty: 0, dragging: false, sx: 0, sy: 0, stx: 0, sty: 0,
               btn: -1, moved: false, suppressClick: false };
  var MIN_ZOOM = 0.5, MAX_ZOOM = 8;

  // Ctrl+Z steps back one click. Numbering a floor is a long run of clicks and
  // a misclick part-way through is certain, so this is bound globally rather
  // than only while the plan has focus.
  document.addEventListener('keydown', function (e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    var k = String(e.key || '').toLowerCase();
    if (k !== 'z' && k !== 'y') return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (!isManual()) return;
    e.preventDefault();
    if (k === 'z') arManualUndo();
  });

  function applyTransform() {
    var box = $('arPlanBox');
    box.style.transform = 'translate(' + _zoom.tx + 'px,' + _zoom.ty + 'px) scale(' + _zoom.scale + ')';
    box.style.transformOrigin = '0 0';
  }

  function resetZoom() {
    _zoom.scale = 1; _zoom.tx = 0; _zoom.ty = 0;
    applyTransform();
    $('arZoomLbl').textContent = '100%';
  }

  var planWrap = $('arPlanWrap');

  planWrap.addEventListener('wheel', function (e) {
    e.preventDefault();
    var rect = planWrap.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;

    var oldScale = _zoom.scale;
    var delta = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    _zoom.scale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, _zoom.scale * delta));

    var ratio = _zoom.scale / oldScale;
    _zoom.tx = mx - ratio * (mx - _zoom.tx);
    _zoom.ty = my - ratio * (my - _zoom.ty);
    applyTransform();
    $('arZoomLbl').textContent = Math.round(_zoom.scale * 100) + '%';
  }, { passive: false });

  // A press becomes a drag only once it travels this far. Below it the gesture
  // is a click. 6px clears ordinary hand tremor and the shake of pressing a
  // stiff mouse button, while a deliberate pan moves tens of pixels — so a
  // spurious undo mid-run, which would silently drop a number, cannot happen,
  // and a real click never feels dead.
  var DRAG_SLOP = 6;

  // The plan owns the right button, so the browser menu must not appear over
  // it — the same suppression Quick Walls does for its right-drag pan.
  planWrap.addEventListener('contextmenu', function (e) { e.preventDefault(); });

  planWrap.addEventListener('mousedown', function (e) {
    // Left drags the plan, right drags it too (matching Quick Walls and
    // Report). Which button it was decides what a *non*-drag means on release.
    if (e.button !== 0 && e.button !== 2) return;
    _zoom.dragging = true;
    _zoom.btn = e.button;
    _zoom.moved = false;
    _zoom.suppressClick = false;
    _zoom.sx = e.clientX; _zoom.sy = e.clientY;
    _zoom.stx = _zoom.tx; _zoom.sty = _zoom.ty;
    planWrap.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', function (e) {
    if (!_zoom.dragging) return;
    var dx = e.clientX - _zoom.sx, dy = e.clientY - _zoom.sy;
    if (!_zoom.moved && Math.abs(dx) + Math.abs(dy) > DRAG_SLOP) _zoom.moved = true;
    if (!_zoom.moved) return;   // hold still until it is clearly a drag
    _zoom.tx = _zoom.stx + dx;
    _zoom.ty = _zoom.sty + dy;
    applyTransform();
  });

  window.addEventListener('mouseup', function (e) {
    if (!_zoom.dragging) return;
    var wasDrag = _zoom.moved;
    var btn = _zoom.btn;
    _zoom.dragging = false;
    _zoom.moved = false;
    // click fires after mouseup, so the decision has to be parked here.
    _zoom.suppressClick = wasDrag;
    planWrap.style.cursor = '';
    // Right-click with no travel is undo — it keeps the hand on the mouse
    // through a long numbering run instead of reaching for the keyboard.
    if (!wasDrag && btn === 2 && isManual()) arManualUndo();
  });

  window.arResetZoom = resetZoom;

  // Same splitter Visual Wall Swap uses — one implementation, lifted into
  // wd-shared.js rather than copied.
  if (WD.mountSplitter) {
    WD.mountSplitter({
      splitter: 'arSplitter',
      panel: 'arSidebar',
      container: '.ar-split',
      key: 'wd.aprename.sidebarWidth',
      min: 300,
      def: 340,
      maxRatio: 0.6
    });
  }

  /* Same folding as the Quick Walls panel, from the same implementation.
     Once the naming pattern is set it is just taking up column, and the
     colour sequence grows with the project - so being able to put Name
     Pattern away is what keeps this usable in a small window. */
  if (WD.mountFolds) {
    WD.mountFolds({ selector: '.ar-foldable', key: 'wd.aprename.folded' });
  }

  // Diagnostics hook, same shape as Quick Walls' __wallsSwap.
  window.__apLabeler = {
    state: function () {
      return {
        order: S.manualOrder.slice(),
        undoDepth: S.manualUndo.length,
        undoLengths: S.manualUndo.map(function (a) { return a.length; }),
        drag: { btn: _zoom.btn, moved: _zoom.moved, suppressClick: _zoom.suppressClick }
      };
    }
  };

  /* ── init ───────────────────────────────────────────────────────── */
  renderSegments();
  loadDefaults();

  window.__aprename = {
    loadFile: loadFile,
    getState: function () { return S; }
  };
})();
