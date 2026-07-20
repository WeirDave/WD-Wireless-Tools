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
    buildings: {},        // buildingId -> building object
    buildingFloors: {},   // floorPlanId -> buildingFloor object (has buildingId)
    images: {},
    imageUrls: {},
  };
  var apDisabled = new Set();
  var currentReportId = DEFAULT_REPORT_ID;
  var currentOpts = {};  // last-known per-report checkbox state, keyed by option id

  // ── AP filter UI state ──
  var apGroupBy = 'none';           // 'none' | 'color' | 'floor' | 'building' | 'model'
  var apSearch = '';                // free-text name filter
  var collapsedGroups = new Set();  // group keys the user has collapsed

  // ── Wizard stage state ──
  // 'template' → gallery of report cards
  // 'configure' → cover/options/APs form
  // 'review'    → rendered canvas + print
  var currentStage = 'template';
  var templateConfirmed = false;   // user clicked "Use this template"
  var configureDirty = true;       // review canvas needs re-render

  var savedLogo = null;
  try { savedLogo = localStorage.getItem('wd-report-logo') || null; } catch (e) {}

  // ── Stage manager ──
  var STAGE_ORDER = ['template', 'configure', 'review'];
  var STAGE_ELS = {}; // filled on first showStage

  window.goStage = function (name) {
    if (STAGE_ORDER.indexOf(name) === -1) return;
    // Gate forward navigation on prerequisites.
    if (name === 'configure' && !templateConfirmed) return;
    if (name === 'review' && !templateConfirmed) return;
    showStage(name);
  };

  function showStage(name) {
    currentStage = name;
    STAGE_ORDER.forEach(function (s) {
      var el = STAGE_ELS[s] || (STAGE_ELS[s] = document.getElementById('stage' + s.charAt(0).toUpperCase() + s.slice(1)));
      if (!el) return;
      if (s === name) el.removeAttribute('hidden');
      else el.setAttribute('hidden', '');
    });
    updateStepper();
    if (name === 'review') {
      if (configureDirty) renderReport();
      configureDirty = false;
      window.scrollTo({ top: 0, behavior: 'auto' });
    }
  }

  function updateStepper() {
    var stepper = document.getElementById('stepper');
    if (!stepper) return;
    var currentIdx = STAGE_ORDER.indexOf(currentStage);
    STAGE_ORDER.forEach(function (s, i) {
      var pill = stepper.querySelector('[data-stage="' + s + '"]');
      if (!pill) return;
      pill.classList.remove('active', 'done');
      if (i < currentIdx) pill.classList.add('done');
      else if (i === currentIdx) pill.classList.add('active');
      // Only enable stages the user has already reached (or the current one).
      var reachable = (s === 'template')
        || (s === 'configure' && templateConfirmed)
        || (s === 'review' && templateConfirmed);
      if (reachable) pill.removeAttribute('disabled');
      else pill.setAttribute('disabled', '');
    });
  }

  window.markConfigDirty = function () { configureDirty = true; };
  window.toggleAllAps = function (checked) {
    proj.accessPoints.forEach(function (ap) {
      if (checked) apDisabled.delete(ap.id); else apDisabled.add(ap.id);
    });
    renderApFilter();
    configureDirty = true;
  };

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

      // Reset wizard state — new file starts fresh at the template picker.
      templateConfirmed = false;
      configureDirty = true;
      currentStage = 'template';

      dropzone.style.display = 'none';
      document.getElementById('dzTopbar').style.display = 'none';
      document.getElementById('workspace').classList.add('active');
      document.getElementById('fileBadge').textContent = fileName;
      document.getElementById('fileBadge').style.display = 'inline';

      // Populate the "parsed X APs across Y floor plans" subtitles.
      var sub = proj.accessPoints.length + ' APs across '
        + proj.floorPlans.length + ' floor plan'
        + (proj.floorPlans.length === 1 ? '' : 's');
      var tSub = document.getElementById('templateStageSub');
      if (tSub) tSub.textContent = siteName() + ' — ' + sub;
      var cSub = document.getElementById('configStageSub');
      if (cSub) cSub.textContent = siteName() + ' — ' + sub;

      renderTemplateGallery();
      renderApFilter();
      // Pre-render the currently-selected report's options into the config
      // card so the configure stage is ready the moment the user gets there.
      renderReportOpts();
      showStage('template');
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
    var bld = await readJson('buildings.json');
    var bf = await readJson('buildingFloors.json');

    proj.accessPoints = (ap && ap.accessPoints) || [];
    proj.radios = (rad && rad.simulatedRadios) || [];
    proj.antennas = {};
    ((ant && ant.antennaTypes) || []).forEach(function (a) { proj.antennas[a.id] = a; });
    proj.floorPlans = (fp && fp.floorPlans) || [];
    proj.images = {};
    ((img && img.images) || []).forEach(function (i) { proj.images[i.id] = i; });
    proj.buildings = {};
    ((bld && bld.buildings) || []).forEach(function (b) { proj.buildings[b.id] = b; });
    proj.buildingFloors = {};
    ((bf && bf.buildingFloors) || []).forEach(function (x) { proj.buildingFloors[x.floorPlanId] = x; });
    proj.imageUrls = {};
    apDisabled = new Set();

    for (var i = 0; i < proj.floorPlans.length; i++) {
      var f = proj.floorPlans[i];
      await readImageAsUrl(f.bitmapImageId || f.imageId);
    }
  }

  // ── Antenna classification helpers ──
  // An AP is "omni-only" if EVERY radio uses an antenna named "omni". We
  // deliberately DON'T fall back to null beam widths — integrated antennas
  // (like Mist AP47D) leave those null even though the AP is directional.
  function apIsOmniOnly(ap) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === ap.id; });
    if (!rs.length) return false;
    return rs.every(function (r) {
      if (!r.antennaTypeId) return true;   // no antenna assigned = treat as omni
      var a = proj.antennas[r.antennaTypeId];
      if (!a) return true;
      return /omni/i.test(a.name || '');
    });
  }
  function apHasExternal(ap) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === ap.id; });
    return rs.some(function (r) {
      if (!r.antennaTypeId) return false;
      var a = proj.antennas[r.antennaTypeId];
      return a && a.apCoupling && a.apCoupling !== 'INTERNAL_ANTENNA';
    });
  }
  function hasAnyBeamWidth(p) {
    var ids = Object.keys(p.antennas || {});
    return ids.some(function (id) {
      var a = p.antennas[id];
      return a && (a.beamWidthHorizontal != null || a.beamWidthVertical != null);
    });
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

  // ── AP filter grid (stage 3) — grouping, search, collapsible groups ──

  function apModelDesignator(ap) {
    var v = ap.vendor || '';
    var m = ap.model || '';
    if (v && m) return v + ' · ' + m;
    return v || m || 'Unknown model';
  }

  // Group-by key extractors + label formatters
  function apGroupKey(ap, dim) {
    if (dim === 'color') return ap.color || '__nocolor';
    if (dim === 'model') return (ap.vendor || 'Unknown') + '|' + (ap.model || 'Unknown');
    if (dim === 'floor') return (ap.location && ap.location.floorPlanId) || '__nofloor';
    if (dim === 'building') {
      var floorId = ap.location && ap.location.floorPlanId;
      var bf = proj.buildingFloors && proj.buildingFloors[floorId];
      return (bf && bf.buildingId) || '__nobuilding';
    }
    return '__none';
  }
  function apGroupLabel(key, dim) {
    if (dim === 'color') {
      if (key === '__nocolor') return 'No color';
      return key;   // hex value; swatch shown separately
    }
    if (dim === 'model') {
      if (key === 'Unknown|Unknown') return 'Unknown model';
      return key.replace('|', ' · ');
    }
    if (dim === 'floor') {
      if (key === '__nofloor') return 'No floor';
      var fp = proj.floorPlans.find(function (f) { return f.id === key; });
      return (fp && fp.name) || 'Unnamed floor';
    }
    if (dim === 'building') {
      if (key === '__nobuilding') return 'No building';
      var b = proj.buildings && proj.buildings[key];
      return (b && b.name) || 'Unnamed building';
    }
    return key;
  }

  function renderApFilter() {
    var host = document.getElementById('apFilterList');
    var countHost = document.getElementById('apCount');
    if (!host) return;
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-ap-empty">No APs found in this .esx.</div>';
      if (countHost) countHost.textContent = '0 APs';
      return;
    }

    // Filter by antenna-type toggles (report options), then by search.
    var inclDirectional = ('inclDirectional' in currentOpts) ? currentOpts.inclDirectional : true;
    var inclOmni        = ('inclOmni'        in currentOpts) ? currentOpts.inclOmni        : false;
    var eligible = proj.accessPoints.filter(function (ap) {
      var omni = apIsOmniOnly(ap);
      if (omni && !inclOmni) return false;
      if (!omni && !inclDirectional) return false;
      return true;
    });

    var q = apSearch.trim().toLowerCase();
    var filtered = q
      ? eligible.filter(function (ap) { return (ap.name || '').toLowerCase().indexOf(q) !== -1; })
      : eligible.slice();

    // Update count badge — of ALL APs that are ELIGIBLE (respects omni/directional toggle),
    // not raw AP count, so the badge doesn't confuse ("5 of 500 checked" when 495 are omni-hidden).
    if (countHost) {
      var eligibleChecked = eligible.filter(function (a) { return !apDisabled.has(a.id); }).length;
      var suffix = (eligible.length !== proj.accessPoints.length)
        ? ' (' + (proj.accessPoints.length - eligible.length) + ' hidden by filter)'
        : '';
      countHost.textContent = eligibleChecked + ' of ' + eligible.length + ' checked' + suffix;
    }

    if (!filtered.length) {
      host.innerHTML = '<div class="rep-ap-empty">No APs match "' + WD.esc(apSearch) + '"</div>';
      return;
    }

    // Sort by name inside every group and inside the flat list
    filtered.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });

    if (apGroupBy === 'none') {
      // Flat grid
      host.innerHTML = '<div class="rep-ap-grid">' + filtered.map(apRowHtml).join('') + '</div>';
      return;
    }

    // Grouped — bucket into groups, then render each with a collapsible header.
    var groups = {};
    var groupOrder = [];
    filtered.forEach(function (ap) {
      var k = apGroupKey(ap, apGroupBy);
      if (!groups[k]) { groups[k] = []; groupOrder.push(k); }
      groups[k].push(ap);
    });
    // Sort group order: hex colors sort by count desc; other dims by label asc.
    groupOrder.sort(function (a, b) {
      var la = apGroupLabel(a, apGroupBy), lb = apGroupLabel(b, apGroupBy);
      return la.localeCompare(lb);
    });

    // Auto-collapse behavior: default collapsed when total APs > 30.
    // (User's per-group toggle overrides this via collapsedGroups.)
    var autoCollapse = proj.accessPoints.length > 30;

    var html = '<div class="rep-ap-groups">';
    groupOrder.forEach(function (k) {
      var aps = groups[k];
      var label = apGroupLabel(k, apGroupBy);
      var checkedInGroup = aps.filter(function (a) { return !apDisabled.has(a.id); }).length;
      var collapsed = collapsedGroups.has(k) || (autoCollapse && !collapsedGroups.has('__expanded:' + k));
      var swatch = (apGroupBy === 'color' && k !== '__nocolor')
        ? '<span class="rep-ap-group-swatch" style="background:' + WD.escAttr(k) + '"></span>'
        : (apGroupBy === 'color'
          ? '<span class="rep-ap-group-swatch" style="background:transparent;"></span>'
          : '');
      html += '<div class="rep-ap-group' + (collapsed ? ' is-collapsed' : '') + '" data-group-key="' + WD.escAttr(k) + '">'
        +   '<div class="rep-ap-group-head" onclick="toggleGroupCollapse(\'' + WD.escAttr(k) + '\')">'
        +     '<span class="rep-ap-group-chevron">▾</span>'
        +     swatch
        +     '<span class="rep-ap-group-label">' + WD.esc(label) + '</span>'
        +     '<span class="rep-ap-group-count">' + checkedInGroup + ' of ' + aps.length + '</span>'
        +     '<button type="button" class="rep-ap-group-toggle" '
        +       'onclick="event.stopPropagation();toggleGroupAll(\'' + WD.escAttr(k) + '\')">Toggle all</button>'
        +   '</div>'
        +   '<div class="rep-ap-group-body">' + aps.map(apRowHtml).join('') + '</div>'
        + '</div>';
    });
    html += '</div>';
    host.innerHTML = html;
  }

  function apRowHtml(ap) {
    return '<label class="rep-ap-row">'
      + '<input type="checkbox" data-ap-id="' + WD.escAttr(ap.id) + '" '
      + (apDisabled.has(ap.id) ? '' : 'checked')
      + ' onchange="toggleAp(this)">'
      + '<span class="rep-ap-row-body">'
      +   '<span class="rep-ap-row-name">' + WD.esc(ap.name) + '</span>'
      +   '<span class="rep-ap-row-model">' + WD.esc(apModelDesignator(ap)) + '</span>'
      + '</span></label>';
  }

  window.toggleAp = function (cb) {
    var id = cb.getAttribute('data-ap-id');
    if (cb.checked) apDisabled.delete(id); else apDisabled.add(id);
    // Update the count badge + group counts without full re-render
    var countHost = document.getElementById('apCount');
    if (countHost) {
      var count = proj.accessPoints.length - apDisabled.size;
      countHost.textContent = count + ' of ' + proj.accessPoints.length + ' checked';
    }
    // Update owning group's count if we're grouped
    if (apGroupBy !== 'none') {
      var ap = proj.accessPoints.find(function (a) { return a.id === id; });
      if (ap) {
        var k = apGroupKey(ap, apGroupBy);
        var group = document.querySelector('.rep-ap-group[data-group-key="' + CSS.escape(k) + '"]');
        if (group) {
          var apsInGroup = proj.accessPoints.filter(function (a) { return apGroupKey(a, apGroupBy) === k; });
          var checkedInGroup = apsInGroup.filter(function (a) { return !apDisabled.has(a.id); }).length;
          var badge = group.querySelector('.rep-ap-group-count');
          if (badge) badge.textContent = checkedInGroup + ' of ' + apsInGroup.length;
        }
      }
    }
    configureDirty = true;
  };

  window.setGroupBy = function (dim) {
    apGroupBy = dim;
    // Reset per-group collapse state whenever grouping changes.
    collapsedGroups = new Set();
    document.querySelectorAll('.rep-groupby-pill').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-group') === dim);
    });
    renderApFilter();
  };

  window.setApSearch = function (v) {
    apSearch = v || '';
    renderApFilter();
  };

  window.toggleGroupCollapse = function (key) {
    // Manual toggle overrides the auto-collapse default. We remember BOTH
    // states so auto-collapse doesn't re-collapse a user-expanded group.
    if (collapsedGroups.has(key)) {
      collapsedGroups.delete(key);
      collapsedGroups.add('__expanded:' + key);
    } else if (collapsedGroups.has('__expanded:' + key)) {
      collapsedGroups.delete('__expanded:' + key);
      collapsedGroups.add(key);
    } else {
      // Currently in auto state — toggle to the opposite of what's auto.
      var autoCollapsed = proj.accessPoints.length > 30;
      if (autoCollapsed) collapsedGroups.add('__expanded:' + key);
      else collapsedGroups.add(key);
    }
    renderApFilter();
  };

  window.toggleGroupAll = function (key) {
    var apsInGroup = proj.accessPoints.filter(function (ap) { return apGroupKey(ap, apGroupBy) === key; });
    var anyChecked = apsInGroup.some(function (a) { return !apDisabled.has(a.id); });
    apsInGroup.forEach(function (a) {
      if (anyChecked) apDisabled.add(a.id); else apDisabled.delete(a.id);
    });
    configureDirty = true;
    renderApFilter();
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
        updateLogoPreview();
        configureDirty = true;
      };
      reader.readAsDataURL(f);
    };
    picker.click();
  };
  window.clearLogo = function () {
    savedLogo = null;
    try { localStorage.removeItem('wd-report-logo'); } catch (e) {}
    updateLogoPreview();
    configureDirty = true;
  };
  updateLogoPreview();

  // ── Template gallery (stage 2) — one card per REPORTS entry ──
  function renderTemplateGallery() {
    var host = document.getElementById('templateGallery');
    if (!host) return;
    var html = '';
    Object.keys(REPORTS).forEach(function (id) {
      var r = REPORTS[id];
      var isSoon = r.status === 'coming-soon';
      var isSelected = templateConfirmed && id === currentReportId;
      var pill = isSoon
        ? '<span class="rep-template-pill soon">Coming soon</span>'
        : (isSelected
          ? '<span class="rep-template-pill selected">✓ Selected</span>'
          : '<span class="rep-template-pill available">Available</span>');

      var sections = (r.sections || []).map(function (s) {
        return '<li class="rep-template-section">'
          + '<span class="rep-template-section-icon">' + WD.esc(s.icon || '·') + '</span>'
          + '<span class="rep-template-section-body">'
          +   '<b>' + WD.esc(s.title) + '</b>'
          +   '<span>' + WD.esc(s.description || '') + '</span>'
          + '</span></li>';
      }).join('');

      var bestFor = r.bestFor
        ? '<div class="rep-template-best-for"><b>Best for:</b> ' + WD.esc(r.bestFor) + '</div>'
        : '';

      var cta = isSoon
        ? '<div class="rep-template-soon-note">In progress — check back soon</div>'
        : '<div class="rep-template-cta"><button type="button" class="btn btn-blue" '
          + 'onclick="selectReport(\'' + WD.escAttr(id) + '\')">'
          + (isSelected ? 'Continue with this template →' : 'Use this template →')
          + '</button></div>';

      html += '<div class="rep-template-card '
        + (isSoon ? 'is-coming-soon' : '')
        + (isSelected ? ' is-selected' : '')
        + '"' + (isSoon ? '' : ' onclick="if(event.target.tagName!==\'BUTTON\')selectReport(\'' + WD.escAttr(id) + '\')"')
        + '>'
        +   '<div class="rep-template-card-top">'
        +     '<div class="rep-template-preview">' + (r.preview || '') + '</div>'
        +     '<div class="rep-template-titles">'
        +       pill
        +       '<h3 class="rep-template-title">' + WD.esc(r.label) + '</h3>'
        +       '<p class="rep-template-subtitle">' + WD.esc(r.description || '') + '</p>'
        +     '</div>'
        +   '</div>'
        +   (sections ? '<div class="rep-template-sections-head">What\'s inside</div>'
          + '<ul class="rep-template-sections">' + sections + '</ul>' : '')
        +   bestFor
        +   cta
        + '</div>';
    });
    host.innerHTML = html;
  }

  window.selectReport = function (id) {
    if (!REPORTS[id]) return;
    if (REPORTS[id].status === 'coming-soon') return;
    if (id !== currentReportId) {
      currentReportId = id;
      currentOpts = {};  // reset per-report option state
    }
    templateConfirmed = true;
    configureDirty = true;
    renderTemplateGallery();  // refresh "selected" state
    renderReportOpts();       // render the options card for this report
    goStage('configure');
  };

  function renderReportOpts() {
    var host = document.getElementById('reportOptsSlot');
    if (!host) return;
    var r = currentReport();
    if (!r.sidebar || !r.sidebar.length) {
      host.innerHTML = '<div class="rep-config-card-head">'
        + '<span class="rep-config-icon">📋</span>'
        + '<span>' + WD.esc(r.docName) + ' options</span></div>'
        + '<div class="rep-empty-small">No extra options for this report.</div>';
      return;
    }
    var html = '<div class="rep-config-card-head">'
      + '<span class="rep-config-icon">📋</span>'
      + '<span>' + WD.esc(r.docName) + ' options</span></div>';
    r.sidebar.forEach(function (opt) {
      var disabled = typeof opt.disabledWhen === 'function' ? !!opt.disabledWhen(proj) : false;
      var checked = (opt.id in currentOpts) ? currentOpts[opt.id] : !!opt.default;
      // Disabled option can still show its checked-state, but user can't toggle.
      var desc = opt.description || '';
      // If a disabled option has a "disabledReason" (or we can derive one),
      // append it to the description in italics.
      var reason = disabled && opt.disabledReason ? opt.disabledReason(proj) : '';
      if (reason) desc = (desc ? desc + ' ' : '') + '— ' + reason;
      html += '<label class="rep-check with-desc' + (disabled ? ' is-disabled' : '') + '"'
        + (disabled ? ' title="' + WD.escAttr(reason || 'Not available for this project') + '"' : '') + '>'
        + '<input type="checkbox" data-opt-id="' + WD.escAttr(opt.id) + '" '
        + (checked ? 'checked' : '') + (disabled ? ' disabled' : '')
        + ' onchange="setOpt(this)">'
        + '<span class="rep-check-body">'
        +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        + '</span></label>';
    });
    host.innerHTML = html;
  }
  window.setOpt = function (cb) {
    var id = cb.getAttribute('data-opt-id');
    currentOpts[id] = cb.checked;
    configureDirty = true;
    // Toggles that affect which APs are eligible → re-render the picker so
    // the user sees the effect immediately.
    if (id === 'inclOmni' || id === 'inclDirectional') renderApFilter();
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
      + '<div class="rep-cover-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
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
      + '<div class="rep-doc-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
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

    var opts = collectOpts();
    // Report gets APs that are (1) eligible per omni/directional toggle AND
    // (2) not explicitly unchecked in the picker.
    var inclDirectional = ('inclDirectional' in currentOpts) ? currentOpts.inclDirectional : true;
    var inclOmni        = ('inclOmni'        in currentOpts) ? currentOpts.inclOmni        : false;
    var aps = proj.accessPoints.filter(function (a) {
      if (apDisabled.has(a.id)) return false;
      var omni = apIsOmniOnly(a);
      if (omni && !inclOmni) return false;
      if (!omni && !inclDirectional) return false;
      return true;
    });
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
  // Inline SVG "page mockup" thumbnails for the template gallery cards.
  var PREVIEW_ANTENNA = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0668D9" stroke-width="0.8"/>'
    // cover title bar
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0668D9"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="24" width="55" height="2" rx="1" fill="#c8d4e0"/>'
    // floor plan section with AP dots + direction arrows
    +   '<rect x="10" y="34" width="72" height="34" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<g fill="#0668D9">'
    +     '<circle cx="20" cy="46" r="1.5"/><circle cx="34" cy="42" r="1.5"/>'
    +     '<circle cx="46" cy="50" r="1.5"/><circle cx="60" cy="46" r="1.5"/>'
    +     '<circle cx="72" cy="52" r="1.5"/><circle cx="28" cy="60" r="1.5"/>'
    +     '<circle cx="52" cy="62" r="1.5"/>'
    +   '</g>'
    // little direction arrow on one AP
    +   '<path d="M46 50 L48 46 L50 50 Z" fill="#d97706"/>'
    // per-AP table hint
    +   '<rect x="10" y="74" width="72" height="3" rx="0.5" fill="#0668D9" opacity="0.55"/>'
    +   '<rect x="10" y="80" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="80" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="84" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="84" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="88" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="88" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="98" width="72" height="6" rx="1" fill="#eef2f7"/>'
    + '</svg>';

  var PREVIEW_BOM = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#d97706" stroke-width="0.8" stroke-dasharray="2 1"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#d97706"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#e5d5c0"/>'
    +   '<rect x="10" y="32" width="72" height="20" rx="1" fill="#faf3ea"/>'
    +   '<rect x="10" y="58" width="72" height="20" rx="1" fill="#faf3ea"/>'
    +   '<rect x="10" y="84" width="72" height="8" rx="1" fill="#eaddc7"/>'
    + '</svg>';

  var REPORTS = {
    antenna: {
      id: 'antenna',
      label: 'Directional Antenna Installation',
      description: 'Per-AP mount, azimuth, tilt, height with floor-plan overlays.',
      docName: 'AP Placement',
      coverBrand: 'Report · AP Placement',
      status: 'ready',
      preview: PREVIEW_ANTENNA,
      bestFor: 'Installer handoff, permit submissions, as-built documentation.',
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, AP + floor-plan counts, your logo, date.' },
        { icon: '🗺️', title: 'Floor plan overview',
          description: 'Every AP plotted on the plan with SVG direction arrows.' },
        { icon: '📡', title: 'Per-AP detail pages',
          description: 'Mount type, azimuth (with compass), tilt, mount height, antenna model.' },
        { icon: '📊', title: 'Antenna specs table',
          description: 'Gain and beam width for each antenna model used.' },
      ],
      sidebar: [
        { id: 'overview', label: 'Floor plan overview page', default: true,
          description: 'Every AP plotted on the plan with SVG direction arrows.' },
        { id: 'specs',    label: 'Antenna specs reference', default: true,
          description: 'Final table listing every antenna model with gain and beam width.',
          disabledWhen: function (p) { return !hasAnyBeamWidth(p); },
          disabledReason: function () { return 'No beam-width data in this project (all-integrated antennas).'; } },
        { id: 'imperial', label: 'Show mount heights in both units', default: true,
          description: 'Meters primary, feet in parentheses — e.g. "2.5 m (8\'2\")".' },
        { id: 'compass',  label: 'Show compass headings alongside azimuth', default: true,
          description: 'Azimuth shown as "137° (SE)" instead of just "137°".' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Standard case — APs whose antennas have a specific azimuth.' },
        { id: 'inclOmni',        label: 'Include omni APs', default: false,
          description: 'APs with only omni antennas — rendered as "Omni — no direction". Off by default because this report focuses on directional mounting.' },
        { id: 'flagExternal',    label: 'Flag APs with external antennas', default: true,
          description: 'Highlight APs that use external (not integrated) antennas so installers know they need separate mounting.' },
      ],
      render: renderAntennaReport,
    },
    bom: {
      id: 'bom',
      label: 'Bill of Materials',
      description: 'AP counts + external antennas for procurement handoff.',
      docName: 'Bill of Materials',
      coverBrand: 'Report · Bill of Materials',
      status: 'coming-soon',
      preview: PREVIEW_BOM,
      bestFor: 'Procurement teams sizing purchase orders.',
      sections: [
        { icon: '📦', title: 'AP quantities',
          description: 'Grouped by vendor and model, with totals.' },
        { icon: '📡', title: 'Antenna quantities',
          description: 'Grouped by antenna type — filter to external-only for procurement.' },
      ],
      sidebar: [],
      render: renderBomReport,
    },
  };

  // Initial render — populates the template gallery so the wizard is
  // ready the instant a file lands.
  renderTemplateGallery();
})();
