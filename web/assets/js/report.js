/* WD Report — installer-facing reports from .esx files.
   All parsing happens in the browser (JSZip), same as Quick Walls. */
(function () {
  'use strict';

  var showToast = WD.toast;

  // ── State ──
  var esxZip = null;
  var fileName = '';
  var proj = {
    accessPoints: [],   // [{id, name, vendor, model, location:{floorPlanId, coord:{x,y}}}]
    radios: [],         // [{accessPointId, antennaDirection, antennaTilt, antennaHeight, antennaMounting, antennaTypeId, radioTechnology, ...}]
    antennas: {},       // id → antennaType
    floorPlans: [],     // [{id, name, width, height, metersPerUnit, imageId, bitmapImageId, cropMinX/Y/MaxX/MaxY}]
    images: {},         // id → {imageFormat, resolutionWidth, resolutionHeight}
    imageUrls: {},      // imageId → blob URL for <img>
  };
  var apDisabled = new Set();  // AP ids the user unchecked

  // ── Dropzone wiring ──
  var dropzone = document.getElementById('dropzone');
  var fileInput = document.getElementById('fileInput');
  dropzone.addEventListener('click', function () { fileInput.click(); });
  dropzone.addEventListener('dragover', function (e) { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', function () { dropzone.classList.remove('dragover'); });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function (e) {
    if (e.target.files.length) loadFile(e.target.files[0]);
  });

  window.loadNewFile = function () {
    fileInput.value = '';
    fileInput.click();
  };

  async function loadFile(file) {
    if (!file.name.toLowerCase().endsWith('.esx')) {
      showToast('Not an .esx file', 'error');
      return;
    }
    try {
      var data = await file.arrayBuffer();
      esxZip = await JSZip.loadAsync(data);
      fileName = file.name;
      await parseEsx();

      // Swap dropzone → workspace
      dropzone.style.display = 'none';
      document.getElementById('dzTopbar').style.display = 'none';
      document.getElementById('workspace').classList.add('active');
      document.getElementById('fileBadge').textContent = fileName;
      document.getElementById('fileBadge').style.display = 'inline';
      renderApFilter();
      renderReport();
    } catch (err) {
      showToast('Error reading file: ' + err.message, 'error');
      console.error(err);
    }
  }

  async function readJson(name) {
    var f = esxZip.file(name);
    if (!f) return null;
    return JSON.parse(await f.async('string'));
  }

  async function readImageAsUrl(imageId) {
    if (!imageId) return null;
    if (proj.imageUrls[imageId]) return proj.imageUrls[imageId];
    var entry = esxZip.file('image-' + imageId);
    if (!entry) return null;
    var blob = await entry.async('blob');
    var meta = proj.images[imageId] || {};
    // JSZip returns a generic blob — retag with an image mime so <img> renders.
    var mime = meta.imageFormat === 'SVG' ? 'image/svg+xml'
      : meta.imageFormat === 'JPEG' ? 'image/jpeg'
      : meta.imageFormat === 'PNG' ? 'image/png'
      : 'image/*';
    var typed = new Blob([blob], { type: mime });
    var url = URL.createObjectURL(typed);
    proj.imageUrls[imageId] = url;
    return url;
  }

  async function parseEsx() {
    var ap = await readJson('accessPoints.json');
    var rad = await readJson('simulatedRadios.json');
    var ant = await readJson('antennaTypes.json');
    var fp = await readJson('floorPlans.json');
    var img = await readJson('images.json');

    proj.accessPoints = (ap && ap.accessPoints) || [];
    proj.radios = (rad && rad.simulatedRadios) || [];
    proj.antennas = {};
    ((ant && ant.antennaTypes) || []).forEach(function (a) { proj.antennas[a.id] = a; });
    proj.floorPlans = (fp && fp.floorPlans) || [];
    proj.images = {};
    ((img && img.images) || []).forEach(function (i) { proj.images[i.id] = i; });
    proj.imageUrls = {};
    apDisabled = new Set();

    // Preload the bitmap for each floor plan (or fall back to the SVG if no bitmap).
    for (var i = 0; i < proj.floorPlans.length; i++) {
      var f = proj.floorPlans[i];
      var iid = f.bitmapImageId || f.imageId;
      await readImageAsUrl(iid);
    }
  }

  // ── Helpers ──
  function primaryRadio(apId) {
    // Skip Bluetooth radios — they typically use a different antenna and aren't
    // what the installer cares about. Prefer the first IEEE 802.11 radio.
    var rs = proj.radios.filter(function (r) { return r.accessPointId === apId; });
    return rs.find(function (r) { return r.radioTechnology === 'IEEE802_11'; })
      || rs[0] || null;
  }

  function compass(deg) {
    var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    return dirs[Math.floor(((deg % 360) + 11.25) / 22.5) % 16];
  }
  var M_TO_FT = 3.28084;
  function metersToFt(m) { return m * M_TO_FT; }
  function fmt(n, dp) { return Number(n).toFixed(dp).replace(/\.?0+$/, ''); }

  function floorPlanForAp(ap) {
    if (!ap.location) return null;
    var fid = ap.location.floorPlanId;
    return proj.floorPlans.find(function (f) { return f.id === fid; }) || null;
  }

  // ── AP filter sidebar ──
  function renderApFilter() {
    var host = document.getElementById('apFilterList');
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-empty-small">No APs found.</div>';
      return;
    }
    var html = '';
    proj.accessPoints
      .slice()
      .sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
      .forEach(function (ap) {
        var id = WD.escAttr(ap.id);
        html += '<label class="rep-check small">'
          + '<input type="checkbox" data-ap-id="' + id + '" '
          + (apDisabled.has(ap.id) ? '' : 'checked')
          + ' onchange="toggleAp(this)">'
          + '<span>' + WD.esc(ap.name) + '</span></label>';
      });
    host.innerHTML = html;
  }

  window.toggleAp = function (cb) {
    var id = cb.getAttribute('data-ap-id');
    if (cb.checked) apDisabled.delete(id); else apDisabled.add(id);
    renderReport();
  };

  // ── Report rendering ──
  window.renderReport = function () {
    var host = document.getElementById('reportCanvas');
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-empty">No APs in this project.</div>';
      return;
    }
    var opts = {
      overview: document.getElementById('optOverview').checked,
      specs: document.getElementById('optSpecs').checked,
      imperial: document.getElementById('optImperial').checked,
      compass: document.getElementById('optCompass').checked,
    };
    var visibleAps = proj.accessPoints.filter(function (a) { return !apDisabled.has(a.id); });
    host.innerHTML = renderAntennaReport(visibleAps, opts);
  };

  function projectName() {
    // Best-effort — the file name is the most reliable label. Strip .esx.
    return fileName.replace(/\.esx$/i, '');
  }

  function renderAntennaReport(aps, opts) {
    var today = new Date();
    var dateStr = today.toISOString().slice(0, 10);

    var head = '<header class="rep-doc-head">'
      + '<div class="rep-doc-brand"><span class="rep-brand-icon">&#128203;</span> Directional Antenna Installation Report</div>'
      + '<h1 class="rep-doc-title">' + WD.esc(projectName()) + '</h1>'
      + '<div class="rep-doc-meta">'
      + '<span><b>APs:</b> ' + aps.length + '</span>'
      + '<span><b>Floor plans:</b> ' + proj.floorPlans.length + '</span>'
      + '<span><b>Generated:</b> ' + WD.esc(dateStr) + '</span>'
      + '</div>'
      + '</header>';

    // Group APs by floor plan so the overview + table can be per-floor.
    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var sections = '';
    var floorOrder = proj.floorPlans.slice();
    // Include the "no floor plan" bucket at the end if it has APs.
    if (byFloor['_none']) floorOrder.push({ id: '_none', name: '(No floor plan)' });

    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderFloorSection(fp, floorAps, opts);
    });

    var legend = '';
    if (opts.specs) legend = renderAntennaLegend(aps);

    return head + sections + legend + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderFloorSection(fp, aps, opts) {
    var out = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';

    if (opts.overview && fp.id !== '_none') {
      out += renderOverview(fp, aps);
    }

    out += renderApTable(aps, opts);
    out += '</section>';
    return out;
  }

  function renderOverview(fp, aps) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) return '<div class="rep-empty-small">Floor plan image not available.</div>';

    var W = fp.width || 1;
    var H = fp.height || 1;

    // SVG overlay is scaled to the plan's logical coord space; the outer div
    // wraps both the <img> and the <svg> so they stretch together.
    var markers = '';
    aps.forEach(function (ap, idx) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var r = primaryRadio(ap.id);
      var dir = r ? r.antennaDirection : null;
      var mount = r ? r.antennaMounting : '';
      var isDirectional = dir != null && mount !== 'CEILING';
      var label = String(idx + 1);
      var color = isDirectional ? '#0d9488' : '#8b5cf6';
      markers += '<g class="rep-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional) {
        // Cone/arrow: rotate so 0°=up (North), Y-down inverts sin/cos.
        var len = Math.min(W, H) * 0.06;
        markers += '<g transform="rotate(' + dir + ')">'
          + '<path d="M 0 0 L ' + (-len * 0.35) + ' ' + (-len) + ' L ' + (len * 0.35) + ' ' + (-len) + ' Z" '
          + 'fill="' + color + '" fill-opacity="0.35" stroke="' + color + '" stroke-width="1"/>'
          + '</g>';
      }
      markers += '<circle r="' + (Math.min(W, H) * 0.015) + '" fill="' + color + '" stroke="#fff" stroke-width="1.5"/>'
        + '<text y="4" text-anchor="middle" font-size="' + (Math.min(W, H) * 0.02) + '" fill="#fff" font-weight="700">' + label + '</text>'
        + '</g>';
    });

    return '<div class="rep-overview">'
      + '<div class="rep-overview-plan" style="aspect-ratio:' + W + '/' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key"><span class="rep-key-swatch dir"></span> Directional antenna &nbsp;·&nbsp; <span class="rep-key-swatch omni"></span> Omni / ceiling</div>'
      + '</div>';
  }

  function renderApTable(aps, opts) {
    var rows = '';
    aps.slice().sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
      .forEach(function (ap, i) {
        var r = primaryRadio(ap.id);
        var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
        var dir = r ? r.antennaDirection : null;
        var tilt = r ? r.antennaTilt : null;
        var height = r ? r.antennaHeight : null;
        var mount = r ? r.antennaMounting : '—';

        var heightStr = height == null ? '—'
          : (opts.imperial
              ? fmt(height, 2) + ' m &nbsp;<span class="rep-alt">(' + fmt(metersToFt(height), 2) + ' ft)</span>'
              : fmt(height, 2) + ' m');

        var azStr = dir == null ? '—'
          : (opts.compass
              ? fmt(dir, 1) + '° <span class="rep-alt">(' + compass(dir) + ')</span>'
              : fmt(dir, 1) + '°');

        var tiltStr = tilt == null ? '—' : fmt(tilt, 1) + '°';
        var antName = ant ? ant.name : '—';
        var vendor = ap.vendor || '—';
        var model = ap.model || '—';

        rows += '<tr>'
          + '<td class="rep-num">' + (i + 1) + '</td>'
          + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
          + '<td>' + WD.esc(vendor) + '</td>'
          + '<td>' + WD.esc(model) + '</td>'
          + '<td>' + WD.esc(mount) + '</td>'
          + '<td>' + heightStr + '</td>'
          + '<td class="rep-az">' + azStr + '</td>'
          + '<td>' + tiltStr + '</td>'
          + '<td>' + WD.esc(antName) + '</td>'
          + '</tr>';
      });

    return '<table class="rep-ap-table">'
      + '<thead><tr>'
      + '<th class="rep-num">#</th>'
      + '<th>AP name</th>'
      + '<th>Vendor</th>'
      + '<th>Model</th>'
      + '<th>Mount</th>'
      + '<th>Height</th>'
      + '<th>Azimuth</th>'
      + '<th>Tilt</th>'
      + '<th>Antenna</th>'
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  function renderAntennaLegend(aps) {
    // Collect distinct antennas actually referenced by the visible APs.
    var used = {};
    aps.forEach(function (ap) {
      var r = primaryRadio(ap.id);
      if (!r) return;
      proj.radios.filter(function (x) { return x.accessPointId === ap.id; })
        .forEach(function (x) { if (x.antennaTypeId) used[x.antennaTypeId] = true; });
    });
    var ids = Object.keys(used);
    if (!ids.length) return '';

    var rows = '';
    ids.forEach(function (id) {
      var a = proj.antennas[id];
      if (!a) return;
      var bits = [];
      if (a.frequencyBand) bits.push(a.frequencyBand);
      if (a.apCoupling) bits.push(a.apCoupling.replace(/_/g, ' ').toLowerCase());
      if (a.maxGain != null) bits.push(a.maxGain + ' dBi max gain');
      if (a.beamWidthHorizontal != null) bits.push(a.beamWidthHorizontal + '° h-beam');
      if (a.beamWidthVertical != null) bits.push(a.beamWidthVertical + '° v-beam');
      rows += '<tr><td class="rep-name">' + WD.esc(a.name || id) + '</td>'
        + '<td>' + WD.esc(bits.join(' · ')) + '</td></tr>';
    });
    return '<section class="rep-legend">'
      + '<h2 class="rep-floor-title">Antennas in use</h2>'
      + '<table class="rep-ap-table"><thead><tr><th>Antenna</th><th>Specs</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>'
      + '</section>';
  }

  // Expose for the file-badge onclick + inline handlers.
  window.renderReport = window.renderReport || function () {};
})();
