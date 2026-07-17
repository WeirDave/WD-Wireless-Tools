/* WD Report — installer-facing reports from .esx files.
   All parsing happens in the browser (JSZip), same as Quick Walls.

   Architecture: a REPORTS registry. Each report is a plain object with
   {id, label, description, docName, sidebar, render}. Adding a new report
   type is one entry — no HTML changes required. */
(function () {
  'use strict';

  var showToast = WD.toast;
  var M_TO_FT = 3.28084;
  var DEFAULT_REPORT_ID = 'antenna';

  // ── State ──
  var esxZip = null;
  var fileName = '';
  var proj = {
    accessPoints: [],
    radios: [],
    antennas: {},
    floorPlans: [],
    images: {},
    imageUrls: {},
  };
  var apDisabled = new Set();
  var currentReportId = DEFAULT_REPORT_ID;
  var currentOpts = {};  // last-known per-report checkbox state, keyed by option id

  var savedLogo = null;
  try { savedLogo = localStorage.getItem('wd-report-logo') || null; } catch (e) {}

  // ── Dropzone ──
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
  window.loadNewFile = function () { fileInput.value = ''; fileInput.click(); };

  async function loadFile(file) {
    if (!file.name.toLowerCase().endsWith('.esx')) {
      showToast('Not an .esx file', 'error'); return;
    }
    try {
      var data = await file.arrayBuffer();
      esxZip = await JSZip.loadAsync(data);
      fileName = file.name;
      await parseEsx();

      dropzone.style.display = 'none';
      document.getElementById('dzTopbar').style.display = 'none';
      document.getElementById('workspace').classList.add('active');
      document.getElementById('fileBadge').textContent = fileName;
      document.getElementById('fileBadge').style.display = 'inline';
      renderReportPicker();
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

    for (var i = 0; i < proj.floorPlans.length; i++) {
      var f = proj.floorPlans[i];
      await readImageAsUrl(f.bitmapImageId || f.imageId);
    }
  }

  // ── Shared helpers ──
  function primaryRadio(apId) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === apId; });
    return rs.find(function (r) { return r.radioTechnology === 'IEEE802_11'; }) || rs[0] || null;
  }
  function compass(deg) {
    var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    return dirs[Math.floor(((deg % 360) + 11.25) / 22.5) % 16];
  }
  function metersToFt(m) { return m * M_TO_FT; }
  function fmt(n, dp) { return Number(n).toFixed(dp).replace(/\.?0+$/, ''); }
  function floorPlanForAp(ap) {
    if (!ap.location) return null;
    return proj.floorPlans.find(function (f) { return f.id === ap.location.floorPlanId; }) || null;
  }

  // Extract SITE name from the .esx filename. Strips ".esx" and a trailing
  // " - {short project suffix}" (EXT PD, Baseline Survey, etc.), preserving
  // address parts like "WA 98014" that contain commas or are longer.
  function siteName() {
    var stem = fileName.replace(/\.esx$/i, '');
    var i = stem.lastIndexOf(' - ');
    if (i > 0) {
      var suffix = stem.slice(i + 3);
      if (suffix.length <= 30 && suffix.indexOf(',') === -1) return stem.slice(0, i);
    }
    return stem;
  }
  function reportDocTitle() {
    return 'Report - ' + currentReport().docName + ' - ' + siteName();
  }

  // ── AP filter sidebar ──
  function renderApFilter() {
    var host = document.getElementById('apFilterList');
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-empty-small">No APs found.</div>';
      return;
    }
    var html = '';
    proj.accessPoints.slice()
      .sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
      .forEach(function (ap) {
        html += '<label class="rep-check small">'
          + '<input type="checkbox" data-ap-id="' + WD.escAttr(ap.id) + '" '
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

  // ── Logo ──
  function updateLogoPreview() {
    var host = document.getElementById('logoPreview');
    var clr = document.getElementById('logoClearBtn');
    if (savedLogo) {
      host.innerHTML = '<img src="' + savedLogo + '" alt="Logo">';
      clr.style.display = '';
    } else {
      host.innerHTML = ''; clr.style.display = 'none';
    }
  }
  window.pickLogo = function () {
    var picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = 'image/png,image/jpeg,image/svg+xml,image/webp,image/gif';
    picker.onchange = function () {
      var f = picker.files && picker.files[0]; if (!f) return;
      var reader = new FileReader();
      reader.onload = function () {
        savedLogo = String(reader.result || '');
        try { localStorage.setItem('wd-report-logo', savedLogo); }
        catch (e) { showToast('Logo saved for this session only (storage full)', 'warn'); }
        updateLogoPreview(); renderReport();
      };
      reader.readAsDataURL(f);
    };
    picker.click();
  };
  window.clearLogo = function () {
    savedLogo = null;
    try { localStorage.removeItem('wd-report-logo'); } catch (e) {}
    updateLogoPreview(); renderReport();
  };
  updateLogoPreview();

  // ── Report picker (dropdown) + dynamic per-report options ──
  function renderReportPicker() {
    var host = document.getElementById('reportPickerList');
    if (!host) return;
    var opts = Object.keys(REPORTS).map(function (id) {
      var r = REPORTS[id];
      return '<option value="' + WD.escAttr(id) + '"'
        + (id === currentReportId ? ' selected' : '') + '>'
        + WD.esc(r.label) + '</option>';
    }).join('');
    var r = currentReport();
    var desc = r.description
      ? '<div class="rep-picker-desc">' + WD.esc(r.description) + '</div>'
      : '';
    host.innerHTML = '<select class="rep-select" id="reportSelect" '
      + 'onchange="selectReport(this.value)" aria-label="Report type">'
      + opts + '</select>' + desc;
  }

  window.selectReport = function (id) {
    if (!REPORTS[id]) return;
    currentReportId = id;
    currentOpts = {};   // reset — each report has its own set of option ids
    renderReportPicker();  // refresh the description under the select
    renderReport();
  };

  function renderReportOpts() {
    var host = document.getElementById('reportOptsSlot');
    if (!host) return;
    var r = currentReport();
    if (!r.sidebar || !r.sidebar.length) { host.innerHTML = ''; return; }
    var html = '<div class="rep-section-head">' + WD.esc(r.docName + ' options') + '</div>';
    r.sidebar.forEach(function (opt) {
      var checked = (opt.id in currentOpts) ? currentOpts[opt.id] : !!opt.default;
      html += '<label class="rep-check">'
        + '<input type="checkbox" data-opt-id="' + WD.escAttr(opt.id) + '" '
        + (checked ? 'checked' : '') + ' onchange="setOpt(this)">'
        + '<span>' + WD.esc(opt.label) + '</span></label>';
    });
    host.innerHTML = html;
  }
  window.setOpt = function (cb) {
    currentOpts[cb.getAttribute('data-opt-id')] = cb.checked;
    renderReport();
  };

  function currentReport() { return REPORTS[currentReportId] || REPORTS[DEFAULT_REPORT_ID]; }

  // Collect all options: common (cover) + per-report defaults filled in.
  function collectOpts() {
    var opts = {};
    var coverEl = document.getElementById('optCover');
    opts.cover = coverEl ? coverEl.checked : true;
    var r = currentReport();
    (r.sidebar || []).forEach(function (o) {
      opts[o.id] = (o.id in currentOpts) ? currentOpts[o.id] : !!o.default;
    });
    return opts;
  }

  // ── Common cover + inline header (parameterized by docName / brand) ──
  function renderCover(aps, dateStr, r) {
    var logo = savedLogo
      ? '<div class="rep-cover-logo-wrap"><img class="rep-cover-logo" src="' + savedLogo + '" alt="Logo"></div>'
      : '';
    var floorLabel = proj.floorPlans.length === 1 ? 'Floor plan' : 'Floor plans';
    return '<section class="rep-cover">'
      + logo
      + '<div class="rep-cover-brand"><span class="rep-brand-icon">&#128203;</span> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-cover-title">' + WD.esc(siteName()) + '</h1>'
      + '<div class="rep-cover-stats">'
      +   '<div class="rep-cover-stat"><b>' + aps.length + '</b><span>Access points</span></div>'
      +   '<div class="rep-cover-stat"><b>' + proj.floorPlans.length + '</b><span>' + floorLabel + '</span></div>'
      + '</div>'
      + '<div class="rep-cover-date">Generated ' + WD.esc(dateStr) + '</div>'
      + '</section>';
  }
  function renderInlineHeader(aps, dateStr, r) {
    return '<header class="rep-doc-head">'
      + '<div class="rep-doc-brand"><span class="rep-brand-icon">&#128203;</span> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-doc-title">' + WD.esc(siteName()) + '</h1>'
      + '<div class="rep-doc-meta">'
      + '<span><b>APs:</b> ' + aps.length + '</span>'
      + '<span><b>Floor plans:</b> ' + proj.floorPlans.length + '</span>'
      + '<span><b>Generated:</b> ' + WD.esc(dateStr) + '</span>'
      + '</div></header>';
  }

  // ── Renderer: entry point ──
  window.renderReport = function () {
    var host = document.getElementById('reportCanvas');
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-empty">Drop an .esx to render a report.</div>';
      return;
    }
    renderReportOpts();  // dynamic sidebar section for the current report

    var opts = collectOpts();
    var aps = proj.accessPoints.filter(function (a) { return !apDisabled.has(a.id); });
    var r = currentReport();
    var today = new Date();
    var dateStr = today.toISOString().slice(0, 10);
    var ctx = {
      report: r,
      dateStr: dateStr,
      proj: proj,
      savedLogo: savedLogo,
      cover: function (aps2, ds) { return renderCover(aps2, ds, r); },
      inlineHeader: function (aps2, ds) { return renderInlineHeader(aps2, ds, r); },
      // exposed helpers so per-report renderers can share the same style
      primaryRadio: primaryRadio,
      compass: compass, metersToFt: metersToFt, fmt: fmt,
      floorPlanForAp: floorPlanForAp,
    };
    host.innerHTML = r.render(aps, opts, ctx);
    document.title = reportDocTitle();
  };

  // ═══════════════════════════════════════════════════════════════════
  //  REPORT 1: Directional Antenna Installation (aka AP Placement)
  // ═══════════════════════════════════════════════════════════════════
  function renderAntennaReport(aps, opts, ctx) {
    var head = opts.cover ? ctx.cover(aps, ctx.dateStr) : ctx.inlineHeader(aps, ctx.dateStr);

    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var sections = '';
    var floorOrder = proj.floorPlans.slice();
    if (byFloor['_none']) floorOrder.push({ id: '_none', name: '(No floor plan)' });

    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderAntennaFloorSection(fp, floorAps, opts, ctx);
    });

    var legend = opts.specs ? renderAntennaLegend(aps, ctx) : '';
    return head + sections + legend + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderAntennaFloorSection(fp, aps, opts, ctx) {
    var out = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
    if (opts.overview && fp.id !== '_none') out += renderAntennaOverview(fp, aps, ctx);
    out += renderAntennaApTable(aps, opts, ctx);
    return out + '</section>';
  }

  function renderAntennaOverview(fp, aps, ctx) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) return '<div class="rep-empty-small">Floor plan image not available.</div>';
    var W = fp.width || 1, H = fp.height || 1;

    var markers = '';
    aps.forEach(function (ap, idx) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var r = ctx.primaryRadio(ap.id);
      var dir = r ? r.antennaDirection : null;
      var mount = r ? r.antennaMounting : '';
      var isDirectional = dir != null && mount !== 'CEILING';
      var color = isDirectional ? '#0d9488' : '#8b5cf6';
      markers += '<g class="rep-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional) {
        var len = Math.min(W, H) * 0.06;
        markers += '<g transform="rotate(' + dir + ')">'
          + '<path d="M 0 0 L ' + (-len * 0.35) + ' ' + (-len) + ' L ' + (len * 0.35) + ' ' + (-len) + ' Z" '
          + 'fill="' + color + '" fill-opacity="0.35" stroke="' + color + '" stroke-width="1"/></g>';
      }
      markers += '<circle r="' + (Math.min(W, H) * 0.015) + '" fill="' + color + '" stroke="#fff" stroke-width="1.5"/>'
        + '<text y="4" text-anchor="middle" font-size="' + (Math.min(W, H) * 0.02) + '" fill="#fff" font-weight="700">' + (idx + 1) + '</text></g>';
    });

    return '<div class="rep-overview">'
      + '<div class="rep-overview-plan" style="aspect-ratio:' + W + '/' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key"><span class="rep-key-swatch dir"></span> Directional antenna &nbsp;·&nbsp; <span class="rep-key-swatch omni"></span> Omni / ceiling</div>'
      + '</div>';
  }

  function renderAntennaApTable(aps, opts, ctx) {
    var rows = '';
    aps.slice().sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
      .forEach(function (ap, i) {
        var r = ctx.primaryRadio(ap.id);
        var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
        var dir = r ? r.antennaDirection : null;
        var tilt = r ? r.antennaTilt : null;
        var height = r ? r.antennaHeight : null;
        var mount = r ? r.antennaMounting : '—';

        var heightStr = height == null ? '—'
          : (opts.imperial
              ? ctx.fmt(height, 2) + ' m &nbsp;<span class="rep-alt">(' + ctx.fmt(ctx.metersToFt(height), 2) + ' ft)</span>'
              : ctx.fmt(height, 2) + ' m');
        var azStr = dir == null ? '—'
          : (opts.compass
              ? ctx.fmt(dir, 1) + '° <span class="rep-alt">(' + ctx.compass(dir) + ')</span>'
              : ctx.fmt(dir, 1) + '°');
        var tiltStr = tilt == null ? '—' : ctx.fmt(tilt, 1) + '°';

        rows += '<tr><td class="rep-num">' + (i + 1) + '</td>'
          + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
          + '<td>' + WD.esc(ap.vendor || '—') + '</td>'
          + '<td>' + WD.esc(ap.model || '—') + '</td>'
          + '<td>' + WD.esc(mount) + '</td>'
          + '<td>' + heightStr + '</td>'
          + '<td class="rep-az">' + azStr + '</td>'
          + '<td>' + tiltStr + '</td>'
          + '<td>' + WD.esc(ant ? ant.name : '—') + '</td></tr>';
      });

    return '<table class="rep-ap-table">'
      + '<thead><tr><th class="rep-num">#</th><th>AP name</th><th>Vendor</th><th>Model</th>'
      + '<th>Mount</th><th>Height</th><th>Azimuth</th><th>Tilt</th><th>Antenna</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  function renderAntennaLegend(aps, ctx) {
    var used = {};
    aps.forEach(function (ap) {
      if (!ctx.primaryRadio(ap.id)) return;
      proj.radios.filter(function (x) { return x.accessPointId === ap.id; })
        .forEach(function (x) { if (x.antennaTypeId) used[x.antennaTypeId] = true; });
    });
    var ids = Object.keys(used); if (!ids.length) return '';
    var rows = '';
    ids.forEach(function (id) {
      var a = proj.antennas[id]; if (!a) return;
      var bits = [];
      if (a.frequencyBand) bits.push(a.frequencyBand);
      if (a.apCoupling) bits.push(a.apCoupling.replace(/_/g, ' ').toLowerCase());
      if (a.maxGain != null) bits.push(a.maxGain + ' dBi max gain');
      if (a.beamWidthHorizontal != null) bits.push(a.beamWidthHorizontal + '° h-beam');
      if (a.beamWidthVertical != null) bits.push(a.beamWidthVertical + '° v-beam');
      rows += '<tr><td class="rep-name">' + WD.esc(a.name || id) + '</td><td>' + WD.esc(bits.join(' · ')) + '</td></tr>';
    });
    return '<section class="rep-legend"><h2 class="rep-floor-title">Antennas in use</h2>'
      + '<table class="rep-ap-table"><thead><tr><th>Antenna</th><th>Specs</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table></section>';
  }

  // ═══════════════════════════════════════════════════════════════════
  //  REPORT 2: Bill of Materials (BOM)
  //  Internal/integrated antennas ship with the AP and are never
  //  purchased separately — they are excluded from the antennas list.
  // ═══════════════════════════════════════════════════════════════════
  function isExternalAntenna(a) {
    // External if apCoupling explicitly says so (EXTERNAL_ANTENNA,
    // DIRECT_ATTACH, etc.). Missing/INTEGRATED/INTERNAL → internal.
    if (!a || !a.apCoupling) return false;
    return /EXTERNAL|DIRECT_ATTACH/i.test(a.apCoupling);
  }

  function renderBomReport(aps, opts, ctx) {
    var head = opts.cover ? ctx.cover(aps, ctx.dateStr) : ctx.inlineHeader(aps, ctx.dateStr);

    // AP counts by vendor+model. One line per SKU.
    var apCounts = {};
    aps.forEach(function (ap) {
      var key = (ap.vendor || 'Unknown') + '||' + (ap.model || 'Unknown');
      apCounts[key] = (apCounts[key] || 0) + 1;
    });

    // External antenna counts: one antenna per AP (union of distinct
    // antennaTypeIds across the AP's radios — a dual-band AP with two
    // different external antennas counts once per antenna, not per radio).
    var antCounts = {};
    aps.forEach(function (ap) {
      var seen = {};
      proj.radios.filter(function (r) { return r.accessPointId === ap.id; })
        .forEach(function (r) { if (r.antennaTypeId) seen[r.antennaTypeId] = true; });
      Object.keys(seen).forEach(function (id) {
        var a = proj.antennas[id];
        if (!isExternalAntenna(a)) return;
        var name = a ? a.name : 'Unknown antenna';
        antCounts[name] = (antCounts[name] || 0) + 1;
      });
    });

    var apKeys = Object.keys(apCounts).sort(function (a, b) {
      return apCounts[b] - apCounts[a] || a.localeCompare(b);
    });
    var apRows = apKeys.map(function (k) {
      var parts = k.split('||');
      return '<tr><td class="rep-num"><b>' + apCounts[k] + '</b></td>'
        + '<td>' + WD.esc(parts[0]) + '</td>'
        + '<td class="rep-name">' + WD.esc(parts[1]) + '</td></tr>';
    }).join('');
    var apTotal = apKeys.reduce(function (s, k) { return s + apCounts[k]; }, 0);

    var antKeys = Object.keys(antCounts).sort(function (a, b) {
      return antCounts[b] - antCounts[a] || a.localeCompare(b);
    });
    var antRows = antKeys.map(function (n) {
      return '<tr><td class="rep-num"><b>' + antCounts[n] + '</b></td>'
        + '<td class="rep-name">' + WD.esc(n) + '</td></tr>';
    }).join('');
    var antTotal = antKeys.reduce(function (s, k) { return s + antCounts[k]; }, 0);

    var apSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Access Points</h2>'
      + '<table class="rep-ap-table"><thead><tr>'
      +   '<th class="rep-num">Qty</th><th>Vendor</th><th>Model</th></tr></thead>'
      + '<tbody>' + (apRows || '<tr><td colspan="3" class="rep-empty-small">No APs.</td></tr>') + '</tbody>'
      + '<tfoot><tr class="rep-bom-total"><td class="rep-num"><b>' + apTotal + '</b></td>'
      +   '<td colspan="2"><b>Total access points</b></td></tr></tfoot></table>'
      + '</section>';

    var antEmpty = '<tr><td colspan="2" class="rep-empty-small">'
      + 'No external antennas — all APs use integrated antennas that ship with the unit.'
      + '</td></tr>';
    var antSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">External Antennas</h2>'
      + '<div class="rep-section-note">Integrated antennas are omitted — they are not procured separately.</div>'
      + '<table class="rep-ap-table"><thead><tr>'
      +   '<th class="rep-num">Qty</th><th>Antenna</th></tr></thead>'
      + '<tbody>' + (antRows || antEmpty) + '</tbody>'
      + (antRows
          ? '<tfoot><tr class="rep-bom-total"><td class="rep-num"><b>' + antTotal + '</b></td>'
            + '<td><b>Total external antennas</b></td></tr></tfoot>'
          : '')
      + '</table>'
      + '</section>';

    return head + apSection + antSection
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  // ═══════════════════════════════════════════════════════════════════
  //  REGISTRY
  // ═══════════════════════════════════════════════════════════════════
  var REPORTS = {
    antenna: {
      id: 'antenna',
      label: 'Directional Antenna Installation',
      description: 'Per-AP mount, azimuth, tilt, height with floor-plan overlays.',
      docName: 'AP Placement',
      coverBrand: 'Report · AP Placement',
      sidebar: [
        { id: 'overview', label: 'Floor plan overview (all APs)', default: true },
        { id: 'specs',    label: 'Antenna specs (gain, beam width)', default: true },
        { id: 'imperial', label: 'Show feet alongside meters', default: true },
        { id: 'compass',  label: 'Compass abbreviations (N, ENE, …)', default: true },
      ],
      render: renderAntennaReport,
    },
    bom: {
      id: 'bom',
      label: 'Bill of Materials',
      description: 'AP counts + external antennas for procurement handoff.',
      docName: 'Bill of Materials',
      coverBrand: 'Report · Bill of Materials',
      sidebar: [],
      render: renderBomReport,
    },
  };

  // Render the picker on load so the sidebar isn't blank before a file drop.
  renderReportPicker();
})();
