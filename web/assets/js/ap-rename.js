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
    presets: [],
    manualOrder: [],   // ap ids, in the order they were clicked
    manualUndo: []     // snapshots of manualOrder, newest last
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(s); }
  function toast(m, k) { WD.toast(m, k); }

  /* ── Ekahau color palette ────────────────────────────────────────── */
  var EKAHAU_COLORS = {
    red:       '#FF0000', green:     '#00C853', white:     '#FFFFFF',
    lightgray: '#BDBDBD', gray:      '#6D6D6D', darkgray:  '#424242',
    black:     '#000000', pink:      '#FF80AB', orange:    '#FF8500',
    yellow:    '#FFE600', magenta:   '#FF00FF', cyan:      '#00BCD4',
    blue:      '#0068FF', lightbrown:'#D7A86E', darkbrown: '#795548'
  };
  var COLOR_ORDER = [
    'red','orange','yellow','green','cyan','blue','magenta','pink',
    'white','lightgray','gray','darkgray','black','lightbrown','darkbrown'
  ];

  function resolveColor(c) {
    if (!c) return null;
    var lc = c.toLowerCase().trim();
    if (EKAHAU_COLORS[lc]) return EKAHAU_COLORS[lc];
    if (/^#[0-9a-f]{6}$/i.test(c)) return c.toUpperCase();
    return c;
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

  function needsDarkText(hex) {
    if (!hex) return false;
    var h = hex.replace('#', '');
    var r = parseInt(h.substr(0, 2), 16);
    var g = parseInt(h.substr(2, 2), 16);
    var b = parseInt(h.substr(4, 2), 16);
    return (r * 299 + g * 587 + b * 114) / 1000 > 180;
  }

  /* ── naming mode ────────────────────────────────────────────────── */
  var _mode = 'structured';

  window.arSetMode = function (m) {
    _mode = m;
    $('arStructuredFields').hidden = (m !== 'structured');
    $('arSimpleFields').hidden     = (m !== 'simple');
    $('arFreeformFields').hidden   = (m !== 'freeform');
    $('arMacFields').hidden        = (m !== 'mac');
    document.querySelectorAll('.ar-mode-tab').forEach(function (t) {
      t.classList.toggle('active', t.getAttribute('data-mode') === m);
    });
    updateAll();
  };

  function getFloorNumber(floor) {
    if (!floor) return '01';
    var n = floor.order != null ? floor.order : 0;
    var s = String(n);
    while (s.length < 2) s = '0' + s;
    return s;
  }

  function buildStructuredName(floor, num) {
    var sep    = $('arSepStructured').value;
    var clli   = $('arClli').value;
    var bldg   = $('arBuilding').value;
    var floorV = $('arFloorAuto').checked ? getFloorNumber(floor) : $('arFloor').value;
    var suite  = $('arSuite').value;
    var tag    = $('arApTag').value;
    var digits = parseInt($('arDigitsStructured').value, 10) || 3;

    var parts = [];
    if (clli)   parts.push(clli);
    if (bldg)   parts.push(bldg);
    if (floorV) parts.push(floorV);
    if (suite)  parts.push(suite);
    if (tag)    parts.push(tag + padNum(num, digits));
    else        parts.push(padNum(num, digits));

    return parts.join(sep);
  }

  function buildFreeformName(num) {
    var text   = $('arFreeText').value;
    var pos    = $('arNumPos').value;
    var sep    = $('arSepFree').value;
    var digits = parseInt($('arDigitsFree').value, 10) || 3;
    var numStr = padNum(num, digits);

    if (!text) return numStr;
    return pos === 'prefix' ? numStr + sep + text : text + sep + numStr;
  }

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

  /* ── presets (localStorage) ────────────────────────────────────── */
  var PRESET_KEY = 'wd-ar-presets';

  // Naming defaults live with the other suite settings under
  // ~/.wd_wireless_tools rather than in localStorage, so they follow the
  // install rather than the browser profile. Presets stay local - they are a
  // per-person scratchpad, not a machine default.
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
      updateAll();
    }).catch(function () { /* offline or older server: keep the built-ins */ });
  }

  window.arSaveDefaults = function () {
    var s = getSettings();
    delete s.macAddr;   // a specific radio's MAC is not a default
    apiSettings('update', { patch: { aprename: { defaults: s } } }).then(function (res) {
      if (res && res.ok) toast('Saved as defaults', 'success');
      else toast('Could not save defaults', 'error');
    }).catch(function () { toast('Could not save defaults', 'error'); });
  };

  function loadPresets() {
    try { S.presets = JSON.parse(localStorage.getItem(PRESET_KEY)) || []; }
    catch (e) { S.presets = []; }
    renderPresetSelect();
  }

  function renderPresetSelect() {
    var sel = $('arPresetSelect');
    var html = '<option value="">— Load preset —</option>';
    S.presets.forEach(function (p, i) {
      html += '<option value="' + i + '">' + esc(p.name) + '</option>';
    });
    sel.innerHTML = html;
  }

  function getSettings() {
    return {
      mode:     _mode,
      order:    $('arOrder').value,
      prefix:   $('arPrefix').value,
      sep:      $('arSep').value,
      startNum: parseInt($('arStart').value, 10) || 1,
      digits:   parseInt($('arDigits').value, 10) || 3,
      perFloor: $('arPerFloor').checked,
      clli:     $('arClli').value,
      building: $('arBuilding').value,
      floor:    $('arFloor').value,
      floorAuto:$('arFloorAuto').checked,
      suite:    $('arSuite').value,
      apTag:    $('arApTag').value,
      sepS:     $('arSepStructured').value,
      startNumS:parseInt($('arStartStructured').value, 10) || 1,
      digitsS:  parseInt($('arDigitsStructured').value, 10) || 3,
      freeText: $('arFreeText').value,
      numPos:   $('arNumPos').value,
      sepFree:  $('arSepFree').value,
      startNumF:parseInt($('arStartFree').value, 10) || 1,
      digitsF:  parseInt($('arDigitsFree').value, 10) || 3,
      macAddr:  $('arMacAddr').value,
      macFormat:$('arMacFormat').value,
      macOctets:parseInt($('arMacOctets').value, 10) || 3,
      macCase:  $('arMacCase').value,
      macPrefix:$('arMacPrefix').value,
      spacing:  parseInt($('arSpacing').value, 10) || 0
    };
  }

  function applySettings(s) {
    if (s.mode) arSetMode(s.mode);
    if (s.order)    $('arOrder').value   = s.order;
    if (s.prefix != null) $('arPrefix').value = s.prefix;
    if (s.sep != null)    $('arSep').value    = s.sep;
    if (s.startNum != null) $('arStart').value = s.startNum;
    if (s.digits != null)   $('arDigits').value = s.digits;
    $('arPerFloor').checked = s.perFloor !== false;
    if (s.clli != null)     $('arClli').value = s.clli;
    if (s.building != null) $('arBuilding').value = s.building;
    if (s.floor != null)    $('arFloor').value = s.floor;
    if (s.floorAuto != null) $('arFloorAuto').checked = s.floorAuto;
    if (s.suite != null)    $('arSuite').value = s.suite;
    if (s.apTag != null)    $('arApTag').value = s.apTag;
    if (s.sepS != null)     $('arSepStructured').value = s.sepS;
    if (s.startNumS != null) $('arStartStructured').value = s.startNumS;
    if (s.digitsS != null)   $('arDigitsStructured').value = s.digitsS;
    if (s.freeText != null)  $('arFreeText').value = s.freeText;
    if (s.numPos != null)    $('arNumPos').value = s.numPos;
    if (s.sepFree != null)   $('arSepFree').value = s.sepFree;
    if (s.startNumF != null) $('arStartFree').value = s.startNumF;
    if (s.digitsF != null)   $('arDigitsFree').value = s.digitsF;
    if (s.macAddr != null)   $('arMacAddr').value = s.macAddr;
    if (s.macFormat != null) $('arMacFormat').value = s.macFormat;
    if (s.macOctets != null) $('arMacOctets').value = s.macOctets;
    if (s.macCase != null)   $('arMacCase').value = s.macCase;
    if (s.macPrefix != null) $('arMacPrefix').value = s.macPrefix;
    if (s.spacing)          $('arSpacing').value = s.spacing;
    else                    $('arSpacing').value = '';
    updateAll();
  }

  window.arSavePreset = function () {
    var name = prompt('Preset name:');
    if (!name || !name.trim()) return;
    name = name.trim();
    var existing = -1;
    for (var i = 0; i < S.presets.length; i++) {
      if (S.presets[i].name === name) { existing = i; break; }
    }
    var entry = Object.assign({ name: name }, getSettings());
    if (existing >= 0) S.presets[existing] = entry;
    else S.presets.push(entry);
    try { localStorage.setItem(PRESET_KEY, JSON.stringify(S.presets)); } catch (e) {}
    renderPresetSelect();
    toast('Preset “' + name + '” saved', 'success');
  };

  window.arDeletePreset = function () {
    var idx = parseInt($('arPresetSelect').value, 10);
    if (isNaN(idx) || !S.presets[idx]) return;
    var name = S.presets[idx].name;
    S.presets.splice(idx, 1);
    try { localStorage.setItem(PRESET_KEY, JSON.stringify(S.presets)); } catch (e) {}
    renderPresetSelect();
    toast('Preset “' + name + '” deleted', 'success');
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
      case 'row-snake':  return sortNearestNeighbor(sorted);
      case 'col-ttb':    return sortByColumn(sorted, false);
      case 'col-btt':    return sortByColumn(sorted, true);
      case 'clockwise':  return sortRadial(sorted, true);
      case 'counter-clockwise': return sortRadial(sorted, false);
      case 'by-color':   return sortByColorGroup(sorted);
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

  // How many manually numbered APs sit on a floor — used for the running
  // offset when numbering continues across floors.
  function manualCountForFloor(fpId) {
    var ids = {};
    getFloorAPs(fpId).forEach(function (ap) { ids[ap.id] = 1; });
    return S.manualOrder.filter(function (id) { return ids[id]; }).length;
  }

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

  function sortByColorGroup(aps) {
    var groups = {};
    aps.forEach(function (ap) {
      var key = ap.color ? ap.color.toLowerCase().trim() : '__none';
      if (!groups[key]) groups[key] = [];
      groups[key].push(ap);
    });
    var keys = Object.keys(groups).sort(function (a, b) {
      return colorSortKey(a === '__none' ? null : a) - colorSortKey(b === '__none' ? null : b);
    });
    var result = [];
    keys.forEach(function (k) {
      var g = sortNearestNeighbor(groups[k]);
      for (var i = 0; i < g.length; i++) result.push(g[i]);
    });
    return result;
  }

  function sortNearestNeighbor(aps) {
    if (aps.length < 2) return aps.slice();
    var remaining = aps.slice();
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
    return result;
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
    if (settings.mode === 'freeform')   return buildFreeformName(num);
    if (settings.mode === 'mac')        return buildMacName(num);
    return settings.prefix + settings.sep + padNum(num, settings.digits);
  }

  function getStartNum(settings) {
    if (settings.mode === 'structured') return settings.startNumS;
    if (settings.mode === 'freeform')   return settings.startNumF;
    if (settings.mode === 'mac')        return 1;
    return settings.startNum;
  }

  function generatePreview() {
    var settings = getSettings();
    var allItems = [];
    var start = getStartNum(settings);
    var num = start;

    S.floors.forEach(function (floor) {
      if (settings.perFloor) num = start;
      var floorAPs = getFloorAPs(floor.id);
      var sorted = sortAPs(floorAPs, settings.order);
      var numbered = {};
      sorted.forEach(function (ap) {
        var newName = generateName(settings, floor, num);
        numbered[ap.id] = 1;
        allItems.push({ ap: ap, oldName: ap.name, newName: newName, floorId: floor.id });
        num++;
      });
      // In manual mode sortAPs only returns the clicked APs, so the rest are
      // listed unchanged rather than silently vanishing from the preview.
      floorAPs.forEach(function (ap) {
        if (!numbered[ap.id]) {
          allItems.push({ ap: ap, oldName: ap.name, newName: ap.name,
                          floorId: floor.id, unnumbered: true });
        }
      });
    });

    var unplaced = getFloorAPs('__unplaced');
    unplaced.forEach(function (ap) {
      allItems.push({ ap: ap, oldName: ap.name, newName: ap.name, floorId: null });
    });

    S.preview = allItems;
    return allItems;
  }

  function updateSpacingVisibility() {
    updateManualPanel();
    var order = $('arOrder').value;
    var show = order === 'row-ltr' || order === 'row-rtl' ||
               order === 'col-ttb' || order === 'col-btt';
    $('arSpacingRow').hidden = !show;
  }

  /* ── render ────────────────────────────────────────────────────── */
  function updateAll() {
    updateSpacingVisibility();
    updateExample();
    var items = generatePreview();
    renderMarkers();
    renderPreviewTable(items);
    updateDownloadBtn();
  }

  function updateExample() {
    var s = getSettings();
    var ex = [];
    if (s.mode === 'structured') {
      var floor = S.currentFloor ? S.floors.find(function (f) { return f.id === S.currentFloor; }) : S.floors[0];
      for (var i = 0; i < 3; i++) ex.push(buildStructuredName(floor || null, s.startNumS + i));
      $('arExampleStructured').textContent = 'Example: ' + ex.join(', ');
    } else if (s.mode === 'freeform') {
      for (var j = 0; j < 3; j++) ex.push(buildFreeformName(s.startNumF + j));
      $('arExampleFree').textContent = 'Example: ' + ex.join(', ');
    } else if (s.mode === 'mac') {
      for (var k = 0; k < 3; k++) ex.push(buildMacName(k + 1));
      $('arExampleMac').textContent = 'Example: ' + ex.join(', ');
    } else {
      for (var m = 0; m < 3; m++) ex.push(s.prefix + s.sep + padNum(s.startNum + m, s.digits));
      $('arExample').textContent = 'Example: ' + ex.join(', ');
    }
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

    var start = getStartNum(settings);
    var offset = start;
    if (!settings.perFloor) {
      for (var fi = 0; fi < S.floors.length; fi++) {
        if (S.floors[fi].id === S.currentFloor) break;
        offset += manual ? manualCountForFloor(S.floors[fi].id)
                         : floorAPCount(S.floors[fi].id);
      }
    }

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
        m.textContent = '\u2013';
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
      var num = offset + idx;
      var fracX = ap.x / floor.width;
      var fracY = ap.y / floor.height;
      var newName = generateName(settings, floor, num);

      var marker = document.createElement('div');
      marker.className = 'ar-marker' + (manual ? ' is-clickable' : '') +
        (manual && idx === sorted.length - 1 ? ' is-last' : '');
      if (manual) {
        marker.onclick = function (e) { e.stopPropagation(); arManualClick(ap.id); };
      }
      marker.style.left = (fracX * 100) + '%';
      marker.style.top  = (fracY * 100) + '%';
      marker.textContent = String(idx + 1);
      marker.setAttribute('data-ap-id', ap.id);

      var resolved = resolveColor(ap.color);
      if (resolved) {
        marker.style.background = resolved;
        if (needsDarkText(resolved)) {
          marker.style.color = '#111';
          marker.style.borderColor = 'rgba(0,0,0,.3)';
        }
      }

      var tip = document.createElement('span');
      tip.className = 'ar-tip';
      tip.textContent = ap.name + ' → ' + newName +
        (manual ? '  (click to remove)' : '');
      marker.appendChild(tip);

      box.appendChild(marker);
    });
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

    var body = $('arPreviewBody');
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="4" style="text-align:center;padding:16px;color:var(--text-2,#666)">No access points on this floor</td></tr>';
      return;
    }
    var html = '';
    var manual = $('arOrder').value === 'manual';
    items.forEach(function (it, i) {
      var isDiff = it.oldName !== it.newName;
      // In manual mode the left column is the assigned position, so an
      // unclicked AP reads as "-" rather than borrowing a row number.
      var seq = manual ? (it.unnumbered ? '\u2013' : String(manualIndex(it.ap.id) + 1))
                       : String(i + 1);
      var swatch = '';
      var rc = resolveColor(it.ap.color);
      if (rc) {
        var border = needsDarkText(rc) ? '1px solid rgba(0,0,0,.2)' : 'none';
        swatch = '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + rc + ';border:' + border + ';vertical-align:middle;margin-right:4px"></span>';
      }
      html += '<tr class="' + (isDiff ? 'changed' : '') +
        (it.unnumbered ? ' unnumbered' : '') + '">' +
        '<td class="ar-num">' + seq + '</td>' +
        '<td>' + swatch + esc(it.oldName || '—') + '</td>' +
        '<td class="ar-arrow">→</td>' +
        '<td class="ar-new">' + esc(it.newName) + '</td>' +
        '</tr>';
    });
    body.innerHTML = html;
  }

  function updateDownloadBtn() {
    var hasChanges = S.preview.some(function (it) { return it.oldName !== it.newName; });
    $('arDownloadBtn').disabled = !hasChanges;
  }

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
  ['arOrder', 'arPrefix', 'arSep', 'arStart', 'arDigits', 'arPerFloor',
   'arClli', 'arBuilding', 'arFloor', 'arFloorAuto', 'arSuite', 'arApTag',
   'arSepStructured', 'arStartStructured', 'arDigitsStructured',
   'arFreeText', 'arNumPos', 'arSepFree', 'arStartFree', 'arDigitsFree',
   'arMacAddr', 'arMacFormat', 'arMacOctets', 'arMacCase', 'arMacPrefix',
   'arSpacing'].forEach(function (id) {
    var el = $(id);
    if (!el) return;
    el.addEventListener('change', updateAll);
    if (el.tagName === 'INPUT') el.addEventListener('input', updateAll);
  });

  $('arFloorAuto').addEventListener('change', function () {
    $('arFloor').disabled = this.checked;
  });
  $('arFloor').disabled = $('arFloorAuto').checked;

  $('arPresetSelect').addEventListener('change', function () {
    var idx = parseInt(this.value, 10);
    if (isNaN(idx) || !S.presets[idx]) return;
    applySettings(S.presets[idx]);
    toast('Loaded preset “' + S.presets[idx].name + '”', 'success');
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
  loadPresets();
  loadDefaults();

  window.__aprename = {
    loadFile: loadFile,
    getState: function () { return S; }
  };
})();
