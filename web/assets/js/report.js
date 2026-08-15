(function () {
  'use strict';

  var showToast = WD.toast;
  var M_TO_FT = 3.28084;
  var DEFAULT_REPORT_ID = 'antenna';

  var esxZip = null;
  var fileName = '';
  var proj = {
    accessPoints: [],
    radios: [],
    antennas: {},
    floorPlans: [],
    buildings: {},
    buildingFloors: {},
    images: {},
    imageUrls: {},
    measurements: [],
    measuredRadios: [],
    surveys: [],
  };
  var apDisabled = new Set();
  var currentReportId = DEFAULT_REPORT_ID;
  var currentOpts = {};

  var apGroupBy = 'none';
  var apSearch = '';
  var collapsedGroups = new Set();

  var currentStage = 'template';
  var templateConfirmed = false;
  var configureDirty = true;

  var savedLogo = null;
  try { savedLogo = localStorage.getItem('wd-report-logo') || null; } catch (e) {}

  var STAGE_ORDER = ['template', 'configure', 'review'];
  var STAGE_ELS = {};

  window.goStage = function (name) {
    if (STAGE_ORDER.indexOf(name) === -1) return;
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

      templateConfirmed = false;
      configureDirty = true;
      currentStage = 'template';

      dropzone.hidden = true;
      document.getElementById('dzTopbar').hidden = true;
      document.getElementById('workspace').classList.add('active');
      var badge = document.getElementById('fileBadge');
      badge.textContent = fileName;
      badge.style.display = 'inline-block';

      var sub = proj.accessPoints.length + ' APs across '
        + proj.floorPlans.length + ' floor plan'
        + (proj.floorPlans.length === 1 ? '' : 's');
      var tSub = document.getElementById('templateStageSub');
      if (tSub) tSub.textContent = siteName() + ' — ' + sub;
      var cSub = document.getElementById('configStageSub');
      if (cSub) cSub.textContent = siteName() + ' — ' + sub;

      renderTemplateGallery();
      renderApFilter();
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
    var apm = await readJson('accessPointMeasurements.json');
    var mr = await readJson('measuredRadios.json');
    var sv = await readJson('surveys.json');
    var perSurveyFiles = esxZip.file(/^survey-[a-f0-9\-]+\.json$/);
    var perSurveyArrays = [];
    for (var psi = 0; psi < perSurveyFiles.length; psi++) {
      try {
        var body = JSON.parse(await perSurveyFiles[psi].async('string'));
        if (body && Array.isArray(body.surveys)) perSurveyArrays.push(body.surveys);
      } catch (e) {}
    }

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
    proj.measurements = (apm && apm.accessPointMeasurements) || [];
    proj.measuredRadios = (mr && mr.measuredRadios) || [];
    proj.surveys = (sv && sv.surveys) ? sv.surveys.slice() : [];
    for (var psj = 0; psj < perSurveyArrays.length; psj++) {
      for (var psk = 0; psk < perSurveyArrays[psj].length; psk++) {
        proj.surveys.push(perSurveyArrays[psj][psk]);
      }
    }
    proj.imageUrls = {};
    apDisabled = new Set();

    for (var i = 0; i < proj.floorPlans.length; i++) {
      var f = proj.floorPlans[i];
      await readImageAsUrl(f.bitmapImageId || f.imageId);
    }
  }

  function apLabel(ap, mode) {
    var n = (ap && ap.name) || '';
    if (mode === 'full') return n;
    var m = n.match(/AP[\-_\s]?(\d+[A-Za-z]?)\s*$/i);
    return m ? m[1] : n;
  }
  function antennaIsDirectional(ant) {
    if (!ant) return false;
    if (ant.directional === true) return true;
    if (ant.directional === false) return false;
    return !/omni/i.test(ant.name || '');
  }
  function radioIsDirectional(r) {
    if (!r || r.antennaDirection == null) return false;
    return antennaIsDirectional(proj.antennas[r.antennaTypeId]);
  }
  function apIsOmniOnly(ap) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === ap.id; });
    if (!rs.length) return false;
    return rs.every(function (r) {
      if (!r.antennaTypeId) return true;
      var a = proj.antennas[r.antennaTypeId];
      if (!a) return true;
      return !antennaIsDirectional(a);
    });
  }
  function hasAnyBeamWidth(p) {
    var ids = Object.keys(p.antennas || {});
    return ids.some(function (id) {
      var a = p.antennas[id];
      return a && (a.beamWidthHorizontal != null || a.beamWidthVertical != null);
    });
  }

  function primaryRadio(apId) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === apId; });
    return rs.find(function (r) { return r.radioTechnology === 'IEEE802_11'; }) || rs[0] || null;
  }
  function compass(deg) {
    var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    var norm = ((deg % 360) + 360) % 360;
    return dirs[Math.floor((norm + 11.25) / 22.5) % 16];
  }
  function metersToFt(m) { return m * M_TO_FT; }
  function fmt(n, dp) { return Number(n).toFixed(dp).replace(/\.?0+$/, ''); }
  function floorPlanForAp(ap) {
    if (!ap.location) return null;
    return proj.floorPlans.find(function (f) { return f.id === ap.location.floorPlanId; }) || null;
  }

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

  function apModelDesignator(ap) {
    var v = ap.vendor || '';
    var m = ap.model || '';
    if (v && m) return v + ' · ' + m;
    return v || m || 'Unknown model';
  }

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
      return key;
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

    filtered.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });

    if (apGroupBy === 'none') {
      host.innerHTML = '<div class="rep-ap-grid">' + filtered.map(apRowHtml).join('') + '</div>';
      return;
    }

    var groups = {};
    var groupOrder = [];
    filtered.forEach(function (ap) {
      var k = apGroupKey(ap, apGroupBy);
      if (!groups[k]) { groups[k] = []; groupOrder.push(k); }
      groups[k].push(ap);
    });
    groupOrder.sort(function (a, b) {
      var la = apGroupLabel(a, apGroupBy), lb = apGroupLabel(b, apGroupBy);
      return la.localeCompare(lb);
    });

    var autoCollapse = proj.accessPoints.length > 30;

    var html = '<div class="rep-ap-groups">';
    groupOrder.forEach(function (k) {
      var aps = groups[k];
      var label = apGroupLabel(k, apGroupBy);
      var checkedInGroup = aps.filter(function (a) { return !apDisabled.has(a.id); }).length;
      var collapsed = collapsedGroups.has(k) || (autoCollapse && !collapsedGroups.has('__expanded:' + k));
      var swatch = '';
      if (apGroupBy === 'color') {
        swatch = (k !== '__nocolor')
          ? '<span class="rep-ap-group-swatch" style="--swatch:' + WD.escAttr(k) + '"></span>'
          : '<span class="rep-ap-group-swatch rep-ap-group-swatch--empty"></span>';
      }
      html += '<div class="rep-ap-group' + (collapsed ? ' is-collapsed' : '') + '" data-group-key="' + WD.escAttr(k) + '">'
        +   '<div class="rep-ap-group-head" onclick="toggleGroupCollapse(\'' + WD.escJsStr(k) + '\')">'
        +     '<span class="rep-ap-group-chevron">▾</span>'
        +     swatch
        +     '<span class="rep-ap-group-label">' + WD.esc(label) + '</span>'
        +     '<span class="rep-ap-group-count">' + checkedInGroup + ' of ' + aps.length + '</span>'
        +     '<button type="button" class="rep-ap-group-toggle" '
        +       'onclick="event.stopPropagation();toggleGroupAll(\'' + WD.escJsStr(k) + '\')">Toggle all</button>'
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
    var countHost = document.getElementById('apCount');
    if (countHost) {
      var count = proj.accessPoints.length - apDisabled.size;
      countHost.textContent = count + ' of ' + proj.accessPoints.length + ' checked';
    }
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
    if (collapsedGroups.has(key)) {
      collapsedGroups.delete(key);
      collapsedGroups.add('__expanded:' + key);
    } else if (collapsedGroups.has('__expanded:' + key)) {
      collapsedGroups.delete('__expanded:' + key);
      collapsedGroups.add(key);
    } else {
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

  function updateLogoPreview() {
    var host = document.getElementById('logoPreview');
    var clr = document.getElementById('logoClearBtn');
    if (savedLogo) {
      host.innerHTML = '<img src="' + savedLogo + '" alt="Logo">';
      clr.hidden = false;
    } else {
      host.innerHTML = ''; clr.hidden = true;
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

  var REPORT_CATEGORIES = [
    { key: 'install', label: 'Installation & Placement',
      ids: ['antenna', 'predictive', 'aim', 'location'] },
    { key: 'analysis', label: 'Site Analysis',
      ids: ['summary', 'coverage', 'interference', 'bom'] },
    { key: 'audit', label: 'Audit & Change',
      ids: ['audit'] },
  ];

  var expandedTemplateId = null;

  function renderTemplateGallery() {
    var host = document.getElementById('templateGallery');
    if (!host) return;
    var html = '';
    REPORT_CATEGORIES.forEach(function (cat) {
      var catReports = cat.ids.filter(function (id) { return REPORTS[id]; });
      if (!catReports.length) return;
      html += '<div class="rep-cat-group">'
        + '<h3 class="rep-cat-heading">' + WD.esc(cat.label) + '</h3>'
        + '<div class="rep-cat-list">';
      catReports.forEach(function (id) {
        var r = REPORTS[id];
        var isSoon = r.status === 'coming-soon';
        var isSelected = templateConfirmed && id === currentReportId;
        var isExpanded = expandedTemplateId === id;
        var pill = isSoon
          ? '<span class="rep-template-pill soon">Coming soon</span>'
          : (isSelected
            ? '<span class="rep-template-pill selected">Selected</span>'
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
            + 'onclick="event.stopPropagation();selectReport(\'' + WD.escJsStr(id) + '\')">'
            + (isSelected ? 'Continue with this template' : 'Use this template')
            + '</button></div>';

        var detailToggle = '<button type="button" class="rep-template-expand" onclick="event.stopPropagation();toggleTemplateDetail(\'' + WD.escJsStr(id) + '\')">'
          + (isExpanded ? '▾ Less' : '▸ Details') + '</button>';

        html += '<div class="rep-template-card tpl-' + WD.escAttr(id)
          + (isSoon ? ' is-coming-soon' : '')
          + (isSelected ? ' is-selected' : '')
          + (isExpanded ? ' is-expanded' : '')
          + '"' + (isSoon ? '' : ' onclick="selectReport(\'' + WD.escJsStr(id) + '\')"')
          + '>'
          +   '<div class="rep-template-card-top">'
          +     '<div class="rep-template-preview">' + (r.preview || '') + '</div>'
          +     '<div class="rep-template-titles">'
          +       pill
          +       '<h3 class="rep-template-title">' + WD.esc(r.label) + '</h3>'
          +       '<p class="rep-template-subtitle">' + WD.esc(r.description || '') + '</p>'
          +     '</div>'
          +     '<div class="rep-template-actions">'
          +       detailToggle
          +     '</div>'
          +   '</div>'
          +   '<div class="rep-template-detail"' + (isExpanded ? '' : ' hidden') + '>'
          +     (sections ? '<div class="rep-template-sections-head">What\'s inside</div>'
            + '<ul class="rep-template-sections">' + sections + '</ul>' : '')
          +     bestFor
          +     cta
          +   '</div>'
          + '</div>';
      });
      html += '</div></div>';
    });

    var uncategorized = Object.keys(REPORTS).filter(function (id) {
      return !REPORT_CATEGORIES.some(function (cat) { return cat.ids.indexOf(id) !== -1; });
    });
    if (uncategorized.length) {
      html += '<div class="rep-cat-group"><h3 class="rep-cat-heading">Other</h3><div class="rep-cat-list">';
      uncategorized.forEach(function (id) {
        var r = REPORTS[id];
        html += '<div class="rep-template-card tpl-' + WD.escAttr(id) + '" onclick="selectReport(\'' + WD.escJsStr(id) + '\')">'
          + '<div class="rep-template-card-top"><div class="rep-template-preview">' + (r.preview || '') + '</div>'
          + '<div class="rep-template-titles"><span class="rep-template-pill available">Available</span>'
          + '<h3 class="rep-template-title">' + WD.esc(r.label) + '</h3>'
          + '<p class="rep-template-subtitle">' + WD.esc(r.description || '') + '</p>'
          + '</div></div></div>';
      });
      html += '</div></div>';
    }

    host.innerHTML = html;
  }

  window.toggleTemplateDetail = function (id) {
    expandedTemplateId = expandedTemplateId === id ? null : id;
    renderTemplateGallery();
  };

  window.selectReport = function (id) {
    if (!REPORTS[id]) return;
    if (REPORTS[id].status === 'coming-soon') return;
    if (id !== currentReportId) {
      currentReportId = id;
      currentOpts = {};
    }
    templateConfirmed = true;
    configureDirty = true;
    renderTemplateGallery();
    renderReportOpts();
    goStage('configure');
  };

  function renderReportOpts() {
    var host = document.getElementById('reportOptsSlot');
    if (!host) return;
    var r = currentReport();
    var apCard = document.getElementById('apFilterCard');
    if (apCard) apCard.hidden = !!r.noApFilter;
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
      var desc = opt.description || '';
      var reason = disabled && opt.disabledReason ? opt.disabledReason(proj) : '';
      if (reason) desc = (desc ? desc + ' ' : '') + '— ' + reason;
      if (opt.type === 'grid-button') {
        var gc = (currentOpts.segCols || '') + '';
        var gr = (currentOpts.segRows || '') + '';
        var gridLabel = (gc && gr) ? gc + ' × ' + gr : 'Auto';
        if (currentOpts.cropBox) gridLabel += ' (cropped)';
        html += '<div class="rep-check with-desc">'
          + '<span class="rep-check-body">'
          +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
          +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
          + '</span>'
          + '<button type="button" class="btn btn-secondary btn-sm" style="margin-left:auto;white-space:nowrap" '
          + 'onclick="openGridConfig()">' + gridLabel + '</button>'
          + '</div>';
      } else if (opt.type === 'number') {
        var numVal = (opt.id in currentOpts) ? currentOpts[opt.id] : (opt.default || '');
        html += '<div class="rep-check with-desc' + (disabled ? ' is-disabled' : '') + '">'
          + '<span class="rep-check-body">'
          +   '<label class="rep-check-label" for="opt-' + WD.escAttr(opt.id) + '">' + WD.esc(opt.label) + '</label>'
          +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
          + '</span>'
          + '<input type="number" id="opt-' + WD.escAttr(opt.id) + '" data-opt-id="' + WD.escAttr(opt.id) + '" data-opt-type="number" '
          + 'value="' + WD.escAttr(String(numVal)) + '" min="' + (opt.min || 1) + '" max="' + (opt.max || 20) + '" '
          + 'style="width:60px;margin-left:auto" '
          + (disabled ? 'disabled' : '')
          + ' onchange="setOpt(this)" oninput="setOpt(this)">'
          + '</div>';
      } else {
        var checked = (opt.id in currentOpts) ? currentOpts[opt.id] : !!opt.default;
        html += '<label class="rep-check with-desc' + (disabled ? ' is-disabled' : '') + '"'
          + (disabled ? ' title="' + WD.escAttr(reason || 'Not available for this project') + '"' : '') + '>'
          + '<input type="checkbox" data-opt-id="' + WD.escAttr(opt.id) + '" '
          + (checked ? 'checked' : '') + (disabled ? ' disabled' : '')
          + ' onchange="setOpt(this)">'
          + '<span class="rep-check-body">'
          +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
          +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
          + '</span></label>';
      }
    });
    host.innerHTML = html;
  }
  window.setOpt = function (cb) {
    var id = cb.getAttribute('data-opt-id');
    if (cb.getAttribute('data-opt-type') === 'number') {
      currentOpts[id] = cb.value === '' ? '' : parseInt(cb.value, 10);
    } else {
      currentOpts[id] = cb.checked;
    }
    configureDirty = true;
    if (id === 'inclOmni' || id === 'inclDirectional') renderApFilter();
  };

  // ── Grid configuration modal ──

  var _gridCols = 0, _gridRows = 0, _gridFloorIdx = 0;
  var _cropBox = { x: 0, y: 0, w: 1, h: 1 };
  var _dragState = null;

  window.openGridConfig = function () {
    var modal = document.getElementById('gridConfigModal');
    if (!modal) return;
    var fps = proj.floorPlans || [];
    if (!fps.length) { alert('No floor plans in this project.'); return; }
    _gridFloorIdx = 0;
    var fp = fps[0];
    var aps = filterApsForFloor(fp);
    var auto = computeAntennaGrid(fp.width, fp.height, aps, {});
    _gridCols = (currentOpts.segCols > 0) ? currentOpts.segCols : auto.cols;
    _gridRows = (currentOpts.segRows > 0) ? currentOpts.segRows : auto.rows;
    _cropBox = currentOpts.cropBox
      ? { x: currentOpts.cropBox.x, y: currentOpts.cropBox.y, w: currentOpts.cropBox.w, h: currentOpts.cropBox.h }
      : { x: 0, y: 0, w: 1, h: 1 };

    var sel = document.getElementById('gridFloorSelect');
    sel.innerHTML = '';
    fps.forEach(function (f, i) {
      var opt = document.createElement('option');
      opt.value = i;
      opt.textContent = f.name || ('Floor ' + (i + 1));
      sel.appendChild(opt);
    });
    sel.value = '0';

    updateGridPreview();
    modal.hidden = false;
  };

  function filterApsForFloor(fp) {
    return (proj.accessPoints || []).filter(function (ap) {
      return ap.location && ap.location.floorPlanId === fp.id;
    });
  }

  window.gridFloorChanged = function (sel) {
    _gridFloorIdx = parseInt(sel.value, 10) || 0;
    var fp = proj.floorPlans[_gridFloorIdx];
    if (!fp) return;
    var aps = filterApsForFloor(fp);
    var auto = computeAntennaGrid(fp.width, fp.height, aps, {});
    _gridCols = auto.cols;
    _gridRows = auto.rows;
    _cropBox = { x: 0, y: 0, w: 1, h: 1 };
    updateGridPreview();
  };

  window.adjustGridCols = function (delta) {
    _gridCols = Math.max(1, Math.min(20, _gridCols + delta));
    updateGridPreview();
  };

  window.adjustGridRows = function (delta) {
    _gridRows = Math.max(1, Math.min(20, _gridRows + delta));
    updateGridPreview();
  };

  window.resetCropBox = function () {
    _cropBox = { x: 0, y: 0, w: 1, h: 1 };
    updateGridPreview();
  };

  function updateGridPreview() {
    var fp = proj.floorPlans[_gridFloorIdx];
    if (!fp) return;
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId] || '';
    var W = fp.width, H = fp.height;
    var aps = filterApsForFloor(fp);

    document.getElementById('gridColsVal').textContent = _gridCols;
    document.getElementById('gridRowsVal').textContent = _gridRows;
    document.getElementById('gridCellCount').textContent =
      _gridCols * _gridRows + ' cells, ' + aps.length + ' APs on this floor';

    var vw = 1000, vh = 1000 * (H / W);

    var bx = _cropBox.x * vw, by = _cropBox.y * vh;
    var bw = _cropBox.w * vw, bh = _cropBox.h * vh;

    var letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + vw + ' ' + vh + '" '
      + 'style="width:100%;height:100%;object-fit:contain" '
      + 'id="gridSvg" data-dw="' + vw + '" data-dh="' + vh + '">';
    svg += '<image href="' + WD.escAttr(url) + '" width="' + vw + '" height="' + vh + '" />';

    // dim area outside crop box
    svg += '<path d="M0,0 H' + vw + ' V' + vh + ' H0 Z '
      + 'M' + bx + ',' + by + ' V' + (by + bh) + ' H' + (bx + bw) + ' V' + by + ' Z" '
      + 'fill="rgba(0,0,0,0.45)" fill-rule="evenodd" pointer-events="none"/>';

    // grid lines inside crop box
    var cw = bw / _gridCols, ch = bh / _gridRows;
    for (var ci = 1; ci < _gridCols; ci++) {
      var lx = bx + ci * cw;
      svg += '<line x1="' + lx + '" y1="' + by + '" x2="' + lx + '" y2="' + (by + bh) + '" stroke="rgba(59,130,246,0.7)" stroke-width="1.5" stroke-dasharray="6,3" pointer-events="none"/>';
    }
    for (var ri = 1; ri < _gridRows; ri++) {
      var ly = by + ri * ch;
      svg += '<line x1="' + bx + '" y1="' + ly + '" x2="' + (bx + bw) + '" y2="' + ly + '" stroke="rgba(59,130,246,0.7)" stroke-width="1.5" stroke-dasharray="6,3" pointer-events="none"/>';
    }

    // cell labels inside crop box
    for (var ri2 = 0; ri2 < _gridRows; ri2++) {
      for (var ci2 = 0; ci2 < _gridCols; ci2++) {
        var lbl = (ci2 < 26 ? letters[ci2] : 'C' + (ci2 + 1)) + (ri2 + 1);
        var cx = bx + ci2 * cw + cw / 2, cy = by + ri2 * ch + ch / 2;
        svg += '<text x="' + cx + '" y="' + cy + '" text-anchor="middle" dominant-baseline="central" '
          + 'fill="rgba(59,130,246,0.5)" font-size="' + Math.max(10, Math.min(24, cw * 0.3)) + '" font-weight="700" pointer-events="none">' + lbl + '</text>';
      }
    }

    // AP dots
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var px = c.x / W * vw, py = c.y / H * vh;
      svg += '<circle cx="' + px + '" cy="' + py + '" r="3" fill="rgba(239,68,68,0.8)" stroke="#fff" stroke-width="0.5" pointer-events="none"/>';
    });

    // crop box border
    svg += '<rect x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh
      + '" fill="none" stroke="#3b82f6" stroke-width="2" pointer-events="none"/>';

    // move area rendered FIRST so edges and corners sit on top in SVG z-order
    svg += '<rect data-edge="move" x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh
      + '" fill="transparent" cursor="move"/>';

    // drag handles — edges (wide hit areas for easy grabbing)
    var ht = 20;
    var cs = 18;
    svg += '<rect class="crop-handle" data-edge="left" x="' + (bx - ht / 2) + '" y="' + (by + cs) + '" width="' + ht + '" height="' + (bh - cs * 2) + '" fill="transparent" cursor="ew-resize"/>';
    svg += '<rect class="crop-handle" data-edge="right" x="' + (bx + bw - ht / 2) + '" y="' + (by + cs) + '" width="' + ht + '" height="' + (bh - cs * 2) + '" fill="transparent" cursor="ew-resize"/>';
    svg += '<rect class="crop-handle" data-edge="top" x="' + (bx + cs) + '" y="' + (by - ht / 2) + '" width="' + (bw - cs * 2) + '" height="' + ht + '" fill="transparent" cursor="ns-resize"/>';
    svg += '<rect class="crop-handle" data-edge="bottom" x="' + (bx + cs) + '" y="' + (by + bh - ht / 2) + '" width="' + (bw - cs * 2) + '" height="' + ht + '" fill="transparent" cursor="ns-resize"/>';

    // drag handles — corners (visible blue squares, on top of everything)
    svg += '<rect class="crop-handle" data-edge="tl" x="' + (bx - cs / 2) + '" y="' + (by - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nwse-resize"/>';
    svg += '<rect class="crop-handle" data-edge="tr" x="' + (bx + bw - cs / 2) + '" y="' + (by - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nesw-resize"/>';
    svg += '<rect class="crop-handle" data-edge="bl" x="' + (bx - cs / 2) + '" y="' + (by + bh - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nesw-resize"/>';
    svg += '<rect class="crop-handle" data-edge="br" x="' + (bx + bw - cs / 2) + '" y="' + (by + bh - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nwse-resize"/>';

    svg += '</svg>';
    document.getElementById('gridPreviewImage').innerHTML = svg;
    bindCropHandles();
  }

  function bindCropHandles() {
    var svgEl = document.getElementById('gridSvg');
    if (!svgEl) return;
    var handles = svgEl.querySelectorAll('[data-edge]');
    for (var i = 0; i < handles.length; i++) {
      handles[i].addEventListener('mousedown', startCropDrag);
    }
  }

  function getSvgScale(svgEl) {
    var dw = parseFloat(svgEl.getAttribute('data-dw'));
    var dh = parseFloat(svgEl.getAttribute('data-dh'));
    var rect = svgEl.getBoundingClientRect();
    var imgAspect = dw / dh;
    var boxAspect = rect.width / rect.height;
    var renderedW, renderedH;
    if (imgAspect > boxAspect) {
      renderedW = rect.width;
      renderedH = rect.width / imgAspect;
    } else {
      renderedH = rect.height;
      renderedW = rect.height * imgAspect;
    }
    return { dw: dw, dh: dh, scaleX: dw / renderedW, scaleY: dh / renderedH };
  }

  function startCropDrag(e) {
    e.preventDefault();
    e.stopPropagation();
    var edge = e.target.getAttribute('data-edge');
    var svgEl = document.getElementById('gridSvg');
    var s = getSvgScale(svgEl);

    _dragState = {
      edge: edge,
      startX: e.clientX, startY: e.clientY,
      origBox: { x: _cropBox.x, y: _cropBox.y, w: _cropBox.w, h: _cropBox.h },
      scaleX: s.scaleX, scaleY: s.scaleY, dw: s.dw, dh: s.dh
    };

    document.addEventListener('mousemove', onCropDrag);
    document.addEventListener('mouseup', endCropDrag);
  }

  function onCropDrag(e) {
    if (!_dragState) return;
    var ds = _dragState;
    var dx = (e.clientX - ds.startX) * ds.scaleX / ds.dw;
    var dy = (e.clientY - ds.startY) * ds.scaleY / ds.dh;
    var ob = ds.origBox;
    var minSize = 0.05;

    var nx = ob.x, ny = ob.y, nw = ob.w, nh = ob.h;

    switch (ds.edge) {
      case 'left':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        break;
      case 'right':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        break;
      case 'top':
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'bottom':
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'tl':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'tr':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'bl':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'br':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'move':
        nx = Math.max(0, Math.min(1 - ob.w, ob.x + dx));
        ny = Math.max(0, Math.min(1 - ob.h, ob.y + dy));
        break;
    }

    _cropBox = { x: nx, y: ny, w: nw, h: nh };
    updateGridPreview();
  }

  function endCropDrag() {
    _dragState = null;
    document.removeEventListener('mousemove', onCropDrag);
    document.removeEventListener('mouseup', endCropDrag);
  }

  window.applyGridConfig = function () {
    currentOpts.segCols = _gridCols;
    currentOpts.segRows = _gridRows;
    var isFullImage = _cropBox.x < 0.001 && _cropBox.y < 0.001 && _cropBox.w > 0.999 && _cropBox.h > 0.999;
    currentOpts.cropBox = isFullImage ? null : { x: _cropBox.x, y: _cropBox.y, w: _cropBox.w, h: _cropBox.h };
    configureDirty = true;
    document.getElementById('gridConfigModal').hidden = true;
    renderReportOpts();
  };

  window.resetGridToAuto = function () {
    var fp = proj.floorPlans[_gridFloorIdx];
    var aps = filterApsForFloor(fp);
    var auto = computeAntennaGrid(fp.width, fp.height, aps, {});
    _gridCols = auto.cols;
    _gridRows = auto.rows;
    _cropBox = { x: 0, y: 0, w: 1, h: 1 };
    updateGridPreview();
  };

  window.closeGridConfig = function () {
    _dragState = null;
    document.removeEventListener('mousemove', onCropDrag);
    document.removeEventListener('mouseup', endCropDrag);
    document.getElementById('gridConfigModal').hidden = true;
  };

  function currentReport() { return REPORTS[currentReportId] || REPORTS[DEFAULT_REPORT_ID]; }

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

  function renderCover(count, dateStr, r, countLabel) {
    var logo = savedLogo
      ? '<div class="rep-cover-logo-wrap"><img class="rep-cover-logo" src="' + savedLogo + '" alt="Logo"></div>'
      : '';
    var floorLabel = proj.floorPlans.length === 1 ? 'Floor plan' : 'Floor plans';
    return '<section class="rep-cover">'
      + logo
      + '<div class="rep-cover-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-cover-title">' + WD.esc(siteName()) + '</h1>'
      + '<div class="rep-cover-stats">'
      +   '<div class="rep-cover-stat"><b>' + count + '</b><span>' + WD.esc(countLabel || 'Access points') + '</span></div>'
      +   '<div class="rep-cover-stat"><b>' + proj.floorPlans.length + '</b><span>' + floorLabel + '</span></div>'
      + '</div>'
      + '<div class="rep-cover-date">Generated ' + WD.esc(dateStr) + '</div>'
      + '</section>';
  }
  function renderInlineHeader(count, dateStr, r, countLabel) {
    return '<header class="rep-doc-head">'
      + '<div class="rep-doc-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-doc-title">' + WD.esc(siteName()) + '</h1>'
      + '<div class="rep-doc-meta">'
      + '<span><b>' + WD.esc(countLabel || 'APs') + ':</b> ' + count + '</span>'
      + '<span><b>Floor plans:</b> ' + proj.floorPlans.length + '</span>'
      + '<span><b>Generated:</b> ' + WD.esc(dateStr) + '</span>'
      + '</div></header>';
  }

  window.renderReport = function () {
    var host = document.getElementById('reportCanvas');
    var r = currentReport();
    if (!proj.accessPoints.length && !r.noApFilter) {
      host.innerHTML = '<div class="rep-empty">Drop an .esx to render a report.</div>';
      return;
    }

    var opts = collectOpts();
    var inclDirectional = ('inclDirectional' in currentOpts) ? currentOpts.inclDirectional : true;
    var inclOmni        = ('inclOmni'        in currentOpts) ? currentOpts.inclOmni        : false;
    var aps = proj.accessPoints.filter(function (a) {
      if (apDisabled.has(a.id)) return false;
      var omni = apIsOmniOnly(a);
      if (omni && !inclOmni) return false;
      if (!omni && !inclDirectional) return false;
      return true;
    });
    var today = new Date();
    var dateStr = today.toISOString().slice(0, 10);
    var ctx = {
      report: r,
      dateStr: dateStr,
      proj: proj,
      savedLogo: savedLogo,
      cover: function (count, ds, label) { return renderCover(count, ds, r, label); },
      inlineHeader: function (count, ds, label) { return renderInlineHeader(count, ds, r, label); },
      primaryRadio: primaryRadio,
      compass: compass, metersToFt: metersToFt, fmt: fmt,
      floorPlanForAp: floorPlanForAp,
    };
    host.innerHTML = r.render(aps, opts, ctx);
    document.title = reportDocTitle();
    if (typeof r.postRender === 'function') {
      try { r.postRender(host, opts, ctx); } catch (e) { console.error('postRender', e); }
    }
  };

  function renderAntennaReport(aps, opts, ctx) {
    var head = opts.cover ? ctx.cover(aps.length, ctx.dateStr) : ctx.inlineHeader(aps.length, ctx.dateStr);

    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var sections = '';
    var floorOrder = proj.floorPlans.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
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
    var sorted = aps.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var out = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
    if (opts.overview && fp.id !== '_none') out += renderAntennaOverview(fp, sorted, opts, ctx);
    out += renderAntennaApTable(sorted, opts, ctx);
    return out + '</section>';
  }

  function buildAntennaMarkers(aps, scaleW, scaleH, opts, ctx) {
    var markers = '';
    var minDim = Math.min(scaleW, scaleH);
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var r = ctx.primaryRadio(ap.id);
      var dir = r ? r.antennaDirection : null;
      var isDirectional = radioIsDirectional(r);
      var cls = isDirectional ? 'rep-mark rep-mark--dir' : 'rep-mark rep-mark--omni';
      markers += '<g class="' + cls + '" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional) {
        var len = minDim * 0.06;
        markers += '<g transform="rotate(' + dir + ')">'
          + '<path class="rep-mark-cone" d="M 0 0 L ' + (-len * 0.35) + ' ' + (-len) + ' L ' + (len * 0.35) + ' ' + (-len) + ' Z"/></g>';
      }
      var label = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      var labelFont = minDim * 0.02 * Math.min(1, 3 / Math.max(3, label.length));
      var padX = minDim * 0.006;
      var boxW = Math.max(minDim * 0.03, label.length * labelFont * 0.65) + padX * 2;
      var boxH = minDim * 0.028;
      var cornerR = minDim * 0.005;
      markers += '<rect class="rep-mark-dot" x="' + (-boxW / 2) + '" y="' + (-boxH / 2) + '" width="' + boxW + '" height="' + boxH + '" rx="' + cornerR + '" ry="' + cornerR + '"/>'
        + '<text class="rep-mark-label" y="' + (labelFont * 0.35) + '" text-anchor="middle" font-size="' + labelFont + '">' + WD.esc(label) + '</text></g>';
    });
    return markers;
  }

  function antennaLabelHint(opts) {
    return opts.shortLabels === false
      ? 'Labels: full AP name.'
      : 'Labels: trailing "APnn" from each AP name (e.g. "42" for "…AP42"). Names without that suffix show the full name.';
  }

  function renderAntennaOverview(fp, aps, opts, ctx) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) return '<div class="rep-empty-small">Floor plan image not available.</div>';
    var W = fp.width || 1, H = fp.height || 1;

    if (opts.segmented) {
      var grid = computeAntennaGrid(W, H, aps, opts);
      if (grid.cols * grid.rows > 1) return renderAntennaSegmentedOverview(url, W, H, aps, opts, ctx, grid);
    }

    var markers = buildAntennaMarkers(aps, W, H, opts, ctx);
    return '<div class="rep-overview">'
      + '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key"><span class="rep-key-swatch dir"></span> Directional antenna &nbsp;·&nbsp; <span class="rep-key-swatch omni"></span> Omni / ceiling &nbsp;·&nbsp; ' + WD.esc(antennaLabelHint(opts)) + '</div>'
      + '</div>';
  }






  function computeAntennaGrid(W, H, aps, opts) {
    var userCols = parseInt(opts && opts.segCols, 10);
    var userRows = parseInt(opts && opts.segRows, 10);
    if (userCols > 0 && userRows > 0) return { cols: userCols, rows: userRows };
    var areaSqFt = W * H * 10.7639;
    var byDensity = Math.ceil(aps.length / 14) || 1;
    var bySize = Math.ceil(areaSqFt / 120000) || 1;
    var target = Math.min(24, Math.max(byDensity, bySize, 1));
    if (target <= 1) return { cols: 1, rows: 1 };
    var cols = Math.max(1, Math.round(Math.sqrt(target * (W / H))));
    var rows = Math.max(1, Math.ceil(target / cols));
    return { cols: cols, rows: rows };
  }

  function segCellLabel(col, row) {
    var letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var letter = col < 26 ? letters[col] : ('C' + (col + 1));
    return letter + (row + 1);
  }

  function renderAntennaSegmentedOverview(url, W, H, aps, opts, ctx, grid) {
    var cols = grid.cols, rows = grid.rows;
    var cb = opts.cropBox || { x: 0, y: 0, w: 1, h: 1 };
    var ox = cb.x * W, oy = cb.y * H;
    var rw = cb.w * W, rh = cb.h * H;
    var cw = rw / cols, ch = rh / rows;

    var cells = [];
    for (var ri = 0; ri < rows; ri++) {
      for (var ci = 0; ci < cols; ci++) {
        cells.push({ col: ci, row: ri, x0: ox + ci * cw, y0: oy + ri * ch, x1: ox + (ci + 1) * cw, y1: oy + (ri + 1) * ch, aps: [] });
      }
    }
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      if (c.x < ox || c.x > ox + rw || c.y < oy || c.y > oy + rh) return;
      var ci = Math.min(cols - 1, Math.max(0, Math.floor((c.x - ox) / cw)));
      var ri = Math.min(rows - 1, Math.max(0, Math.floor((c.y - oy) / ch)));
      cells[ri * cols + ci].aps.push(ap);
    });

    var nonEmpty = cells.filter(function (cell) { return cell.aps.length; });
    var emptyLabels = cells.filter(function (cell) { return !cell.aps.length; })
      .map(function (cell) { return segCellLabel(cell.col, cell.row); });

    var out = '<div class="rep-seg-note">Floor plan split into ' + nonEmpty.length + ' section' + (nonEmpty.length === 1 ? '' : 's')
      + ' (' + cols + '&times;' + rows + ' grid) so AP markers stay legible on this large floor plan.'
      + (emptyLabels.length ? ' No APs in section' + (emptyLabels.length === 1 ? '' : 's') + ' ' + emptyLabels.join(', ') + ' — skipped.' : '')
      + '</div>';
    out += renderAntennaGridIndex(url, W, H, nonEmpty);
    nonEmpty.forEach(function (cell) {
      out += renderAntennaSegmentCell(url, W, H, cell, opts, ctx);
    });
    return out;
  }

  function renderAntennaGridIndex(url, W, H, nonEmptyCells) {
    var lw = Math.min(W, H) * 0.003;
    var lines = '';
    nonEmptyCells.forEach(function (cell) {
      lines += '<rect x="' + cell.x0 + '" y="' + cell.y0 + '" width="' + (cell.x1 - cell.x0) + '" height="' + (cell.y1 - cell.y0)
        + '" class="rep-grid-cell" stroke-width="' + lw + '"/>';
    });
    var labels = '';
    var fontSize = Math.min(W, H) * 0.028;
    nonEmptyCells.forEach(function (cell) {
      var cx = (cell.x0 + cell.x1) / 2, cy = (cell.y0 + cell.y1) / 2;
      labels += '<text x="' + cx + '" y="' + cy + '" text-anchor="middle" dominant-baseline="middle" class="rep-grid-label" font-size="' + fontSize + '">'
        + segCellLabel(cell.col, cell.row) + '</text>';
    });
    return '<div class="rep-overview rep-seg-index">'
      + '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan section index">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + lines + labels + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key">Section index — each labeled cell is detailed on its own page below.</div>'
      + '</div>';
  }

  function renderAntennaLocatorThumb(url, W, H, cell) {
    var lw = Math.min(W, H) * 0.006;
    return '<div class="rep-seg-locator" style="--w:' + W + ';--h:' + H + '">'
      + '<img src="' + url + '" alt="Locator">'
      + '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">'
      +   '<rect x="' + cell.x0 + '" y="' + cell.y0 + '" width="' + (cell.x1 - cell.x0) + '" height="' + (cell.y1 - cell.y0)
      +   '" class="rep-seg-locator-rect" stroke-width="' + lw + '"/>'
      + '</svg>'
      + '</div>';
  }

  function renderAntennaSegmentCell(url, W, H, cell, opts, ctx) {
    var cW = cell.x1 - cell.x0, cH = cell.y1 - cell.y0;
    var label = segCellLabel(cell.col, cell.row);
    var markers = buildAntennaMarkers(cell.aps, W, H, opts, ctx);
    return '<div class="rep-overview rep-seg-cell">'
      + '<div class="rep-seg-cell-head">' + renderAntennaLocatorThumb(url, W, H, cell)
      +   '<h3 class="rep-seg-cell-title">Section ' + WD.esc(label)
      +     ' <span class="rep-seg-cell-count">— ' + cell.aps.length + ' AP' + (cell.aps.length === 1 ? '' : 's') + '</span></h3>'
      + '</div>'
      + '<div class="rep-overview-plan" data-seg="1" data-orig-w="' + W + '" data-orig-h="' + H
      +   '" data-seg-x0="' + cell.x0 + '" data-seg-y0="' + cell.y0 + '" data-seg-x1="' + cell.x1 + '" data-seg-y1="' + cell.y1
      +   '" style="--w:' + cW + ';--h:' + cH + '">'
      +   '<img src="' + url + '" alt="Floor plan section ' + WD.escAttr(label) + '">'
      +   '<svg viewBox="' + cell.x0 + ' ' + cell.y0 + ' ' + cW + ' ' + cH + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key"><span class="rep-key-swatch dir"></span> Directional antenna &nbsp;·&nbsp; <span class="rep-key-swatch omni"></span> Omni / ceiling &nbsp;·&nbsp; ' + WD.esc(antennaLabelHint(opts)) + '</div>'
      + '</div>';
  }

  function cropAntennaSegment(overlayEl) {
    var img = overlayEl.querySelector('img');
    if (!img) return Promise.resolve();
    var W = parseFloat(overlayEl.getAttribute('data-orig-w'));
    var H = parseFloat(overlayEl.getAttribute('data-orig-h'));
    var x0 = parseFloat(overlayEl.getAttribute('data-seg-x0'));
    var y0 = parseFloat(overlayEl.getAttribute('data-seg-y0'));
    var x1 = parseFloat(overlayEl.getAttribute('data-seg-x1'));
    var y1 = parseFloat(overlayEl.getAttribute('data-seg-y1'));
    if (!W || !H) return Promise.resolve();

    return new Promise(function (resolve) {
      function ready() {
        try { doCrop(); } catch (e) { console.error('segment crop', e); }
        resolve();
      }
      if (img.complete && img.naturalWidth) ready();
      else { img.addEventListener('load', ready, {once: true});
             img.addEventListener('error', function () { resolve(); }, {once: true}); }
    });

    function doCrop() {
      var natW = img.naturalWidth, natH = img.naturalHeight;
      if (!natW || !natH) return;
      var srcX = Math.max(0, Math.round(natW * x0 / W));
      var srcY = Math.max(0, Math.round(natH * y0 / H));
      var srcW = Math.min(natW - srcX, Math.max(1, Math.round(natW * (x1 - x0) / W)));
      var srcH = Math.min(natH - srcY, Math.max(1, Math.round(natH * (y1 - y0) / H)));
      var outScale = Math.min(2, 1800 / Math.max(srcW, srcH));
      var c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(srcW * outScale));
      c.height = Math.max(1, Math.round(srcH * outScale));
      c.getContext('2d').drawImage(img, srcX, srcY, srcW, srcH, 0, 0, c.width, c.height);
      c.toBlob(function (blob) {
        if (!blob) return;
        img.src = URL.createObjectURL(blob);
      }, 'image/jpeg', 0.9);
    }
  }

  function applyAntennaSegmentCrop(host, opts) {
    if (!opts.segmented) return;
    var overlays = host.querySelectorAll('.rep-overview-plan[data-seg="1"]');
    for (var i = 0; i < overlays.length; i++) cropAntennaSegment(overlays[i]);
  }





  function renderPredictiveReport(aps, opts, ctx) {
    var head = opts.cover ? ctx.cover(aps.length, ctx.dateStr, 'APs to place')
                          : ctx.inlineHeader(aps.length, ctx.dateStr, 'APs to place');
    var summary = opts.summary ? renderPredictiveSummary(aps, ctx) : '';

    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var sections = '';
    var floorOrder = proj.floorPlans.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    if (byFloor['_none']) floorOrder.push({ id: '_none', name: '(No floor plan)' });

    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderPredictiveFloorSection(fp, floorAps, opts, ctx);
    });

    return head + summary + sections + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderPredictiveSummary(aps, ctx) {
    var floorIds = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      floorIds[fp ? fp.id : '_none'] = true;
    });
    var floorCount = Object.keys(floorIds).length;
    var directional = aps.filter(function (ap) { return !apIsOmniOnly(ap); }).length;
    var omni = aps.length - directional;
    var bits = [aps.length + ' AP' + (aps.length === 1 ? '' : 's') + ' planned across ' + floorCount + ' floor plan' + (floorCount === 1 ? '' : 's')];
    if (directional) bits.push(directional + ' directional');
    if (omni) bits.push(omni + ' omni');
    return '<div class="rep-seg-note">' + WD.esc(bits.join(' · ')) + '.</div>';
  }

  function renderPredictiveFloorSection(fp, aps, opts, ctx) {
    var sorted = aps.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var out = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
    out += fp.id !== '_none'
      ? renderAntennaOverview(fp, sorted, opts, ctx)
      : '<div class="rep-empty-small">No floor plan assigned to these APs.</div>';
    return out + '</section>';
  }

  function renderAntennaApTable(aps, opts, ctx) {
    var rows = '';
    aps.forEach(function (ap) {
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

        var lbl = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
        rows += '<tr><td class="rep-num">' + WD.esc(lbl) + '</td>'
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

  function renderSummaryReport(_apsUnused, opts, ctx) {


    var head = opts.cover ? ctx.cover(proj.accessPoints.length, ctx.dateStr, 'Access points')
                          : ctx.inlineHeader(proj.accessPoints.length, ctx.dateStr, 'Access points');


    var buildingCount = Object.keys(proj.buildings || {}).length;
    var radiosCount = (proj.radios || []).length;
    var antennaTypesUsed = new Set();
    proj.radios.forEach(function (r) { if (r.antennaTypeId) antennaTypesUsed.add(r.antennaTypeId); });
    var measuredCount = (proj.measuredRadios || []).length;
    var surveyCount = (proj.surveys || []).length;

    var stats = [];
    stats.push({ label: 'Access points', value: proj.accessPoints.length, cls: 'total' });
    stats.push({ label: 'Radios', value: radiosCount, cls: 'iphone' });
    stats.push({ label: 'Floor plans', value: proj.floorPlans.length, cls: 'android' });
    if (buildingCount) stats.push({ label: 'Buildings', value: buildingCount, cls: 'carrier' });
    stats.push({ label: 'Antenna types', value: antennaTypesUsed.size, cls: 'total' });
    if (surveyCount) stats.push({ label: 'Surveys', value: surveyCount, cls: 'iphone' });
    if (measuredCount) stats.push({ label: 'Measured radios', value: measuredCount, cls: 'android' });

    var statHtml = '<div class="rep-hotspot-stats">'
      + stats.map(function (s) {
          return '<div class="rep-hotspot-stat rep-hotspot-stat--' + s.cls + '"><b>'
            + WD.esc(String(s.value)) + '</b><span>' + WD.esc(s.label) + '</span></div>';
        }).join('')
      + '</div>';

    var strip = '<section class="rep-floor-section rep-summary-hero">'
      + '<h2 class="rep-floor-title">Project at a glance</h2>'
      + statHtml
      + '</section>';


    var perFloorSection = '';
    if (opts.perFloor !== false && proj.floorPlans.length) {
      var apByFloor = {};
      proj.accessPoints.forEach(function (a) {
        var fp = ctx.floorPlanForAp(a);
        var key = fp ? fp.id : '_unplaced';
        (apByFloor[key] = apByFloor[key] || []).push(a);
      });
      var rows = '';
      proj.floorPlans.forEach(function (f) {
        var apList = apByFloor[f.id] || [];
        var bf = proj.buildingFloors[f.id];
        var buildingName = bf && proj.buildings[bf.buildingId]
          ? proj.buildings[bf.buildingId].name || '' : '';
        var wm = f.width || 0, hm = f.height || 0;
        var sizeStr = (wm && hm)
          ? Math.round(wm) + ' × ' + Math.round(hm) + ' px'
          : '—';
        rows += '<tr>'
          + '<td class="rep-name">' + WD.esc(f.name || 'Untitled') + '</td>'
          + '<td>' + WD.esc(buildingName) + '</td>'
          + '<td class="rep-az">' + apList.length + '</td>'
          + '<td class="rep-az">' + WD.esc(sizeStr) + '</td>'
          + '</tr>';
      });
      var unplaced = (apByFloor['_unplaced'] || []).length;
      if (unplaced) {
        rows += '<tr><td class="rep-name"><em>Unplaced</em></td><td></td>'
          + '<td class="rep-az">' + unplaced + '</td>'
          + '<td class="rep-az">—</td></tr>';
      }
      perFloorSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Per-floor breakdown</h2>'
        + '<table class="rep-ap-table"><thead><tr>'
        + '<th>Floor</th><th>Building</th><th class="rep-num">APs</th><th class="rep-num">Canvas</th>'
        + '</tr></thead><tbody>' + rows + '</tbody></table>'
        + '</section>';
    }


    var bandSection = '';
    if (opts.bandBreakdown !== false && radiosCount) {
      var bandCounts = {};
      var total = 0;
      proj.radios.forEach(function (r) {
        var ant = r.antennaTypeId && proj.antennas[r.antennaTypeId];
        var band = (ant && ant.frequencyBand) || 'Unspecified';
        bandCounts[band] = (bandCounts[band] || 0) + 1;
        total += 1;
      });
      var order = ['TWO', 'FIVE', 'SIX', 'Unspecified'];
      var pretty = { TWO: '2.4 GHz', FIVE: '5 GHz', SIX: '6 GHz' };
      var sortedBands = Object.keys(bandCounts).sort(function (a, b) {
        var ia = order.indexOf(a), ib = order.indexOf(b);
        if (ia === -1) ia = 99; if (ib === -1) ib = 99;
        return ia - ib || a.localeCompare(b);
      });
      var barRows = sortedBands.map(function (b) {
        var count = bandCounts[b];
        var pct = total ? Math.round(count / total * 100) : 0;
        var label = pretty[b] || b.replace(/_/g, ' ');
        return '<tr>'
          + '<td class="rep-name">' + WD.esc(label) + '</td>'
          + '<td><div class="rep-summary-bar-outer"><div class="rep-summary-bar-inner" style="width:' + pct + '%"></div></div></td>'
          + '<td class="rep-az">' + count + '</td>'
          + '<td class="rep-az">' + pct + '%</td>'
          + '</tr>';
      }).join('');
      bandSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Radio band breakdown</h2>'
        + '<p class="rep-summary-hint">One row per radio. Each AP typically has one 2.4 and one 5 GHz radio; 6 GHz appears on Wi-Fi 6E hardware only.</p>'
        + '<table class="rep-ap-table"><thead><tr>'
        + '<th>Band</th><th></th><th class="rep-num">Radios</th><th class="rep-num">Share</th>'
        + '</tr></thead><tbody>' + barRows + '</tbody></table>'
        + '</section>';
    }


    var modelsSection = '';
    if (opts.topModels !== false && proj.accessPoints.length) {
      var modelCounts = {};
      proj.accessPoints.forEach(function (a) {
        var m = (a.model || a.vendor || '').trim() || 'Unknown';
        modelCounts[m] = (modelCounts[m] || 0) + 1;
      });
      var entries = Object.keys(modelCounts).map(function (k) { return { model: k, count: modelCounts[k] }; })
        .sort(function (a, b) { return b.count - a.count || a.model.localeCompare(b.model); })
        .slice(0, 10);
      var modelRows = entries.map(function (e) {
        return '<tr><td class="rep-name">' + WD.esc(e.model) + '</td>'
          + '<td class="rep-az">' + e.count + '</td></tr>';
      }).join('');
      modelsSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Top AP models</h2>'
        + '<table class="rep-ap-table"><thead><tr><th>Model</th><th class="rep-num">Quantity</th></tr></thead>'
        + '<tbody>' + modelRows + '</tbody></table>'
        + '</section>';
    }


    var antennasSection = opts.antennas !== false ? summaryAntennas() : '';


    return head + strip + perFloorSection + bandSection + modelsSection + antennasSection
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function summaryAntennas() {
    var used = {};
    proj.radios.forEach(function (r) { if (r.antennaTypeId) used[r.antennaTypeId] = true; });
    var ids = Object.keys(used); if (!ids.length) return '';
    var rows = ids.map(function (id) {
      var a = proj.antennas[id]; if (!a) return '';
      var bits = [];
      if (a.frequencyBand) bits.push(a.frequencyBand);
      if (a.apCoupling) bits.push(a.apCoupling.replace(/_/g, ' ').toLowerCase());
      if (a.maxGain != null) bits.push(a.maxGain + ' dBi');
      if (a.beamWidthHorizontal != null) bits.push(a.beamWidthHorizontal + '° h-beam');
      return '<tr><td class="rep-name">' + WD.esc(a.name || id)
        + '</td><td>' + WD.esc(bits.join(' · ')) + '</td></tr>';
    }).filter(Boolean).join('');
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Antennas in use</h2>'
      + '<table class="rep-ap-table"><thead><tr><th>Antenna</th><th>Specs</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table></section>';
  }

  function renderBomReport(_apsUnused, opts, ctx) {

    var head = opts.cover ? ctx.cover(proj.accessPoints.length, ctx.dateStr, 'Access points')
                          : ctx.inlineHeader(proj.accessPoints.length, ctx.dateStr, 'Access points');

    var externalOnly = !!opts.externalOnly;


    var apGroups = {};
    proj.accessPoints.forEach(function (a) {
      var vendor = (a.vendor || '').trim() || '—';
      var model = (a.model || '').trim() || 'Unknown';
      var key = vendor + '\u0000' + model;
      if (!apGroups[key]) apGroups[key] = { vendor: vendor, model: model, count: 0 };
      apGroups[key].count += 1;
    });
    var apRows = Object.values(apGroups)
      .sort(function (a, b) {
        return a.vendor.localeCompare(b.vendor) || b.count - a.count || a.model.localeCompare(b.model);
      });
    var apRowsHtml = apRows.map(function (g) {
      return '<tr>'
        + '<td>' + WD.esc(g.vendor) + '</td>'
        + '<td class="rep-name">' + WD.esc(g.model) + '</td>'
        + '<td class="rep-az">' + g.count + '</td>'
        + '</tr>';
    }).join('');
    var apTotal = proj.accessPoints.length;
    var apTotalRow = '<tr class="rep-bom-total"><td></td><td class="rep-name">Total access points</td><td class="rep-az">' + apTotal + '</td></tr>';
    var apSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Access point quantities</h2>'
      + '<table class="rep-ap-table"><thead><tr>'
      + '<th>Vendor</th><th>Model</th><th class="rep-num">Qty</th>'
      + '</tr></thead><tbody>' + apRowsHtml + apTotalRow + '</tbody></table>'
      + '</section>';


    var antGroups = {};
    var totalAntennas = 0;
    proj.radios.forEach(function (r) {
      if (!r.antennaTypeId) return;
      var a = proj.antennas[r.antennaTypeId];
      if (!a) return;
      if (externalOnly && a.apCoupling !== 'EXTERNAL_ANTENNA') return;
      var key = a.id;
      if (!antGroups[key]) antGroups[key] = { antenna: a, count: 0 };
      antGroups[key].count += 1;
      totalAntennas += 1;
    });
    var antRows = Object.values(antGroups)
      .sort(function (a, b) {
        return b.count - a.count || (a.antenna.name || '').localeCompare(b.antenna.name || '');
      });
    var antRowsHtml = antRows.map(function (g) {
      var a = g.antenna;
      var coupling = (a.apCoupling || '').replace(/_/g, ' ').toLowerCase() || '—';
      var band = a.frequencyBand ? ({TWO:'2.4', FIVE:'5', SIX:'6'})[a.frequencyBand] + ' GHz' : '—';
      var gain = (a.maxGain != null) ? a.maxGain + ' dBi' : '—';
      return '<tr>'
        + '<td class="rep-name">' + WD.esc(a.name || a.id) + '</td>'
        + '<td>' + WD.esc(coupling) + '</td>'
        + '<td>' + WD.esc(band) + '</td>'
        + '<td>' + WD.esc(gain) + '</td>'
        + '<td class="rep-az">' + g.count + '</td>'
        + '</tr>';
    }).join('');
    var antTotalLabel = externalOnly ? 'Total external antennas' : 'Total antennas (all)';
    var antTotalRow = '<tr class="rep-bom-total"><td class="rep-name">' + antTotalLabel
      + '</td><td></td><td></td><td></td><td class="rep-az">' + totalAntennas + '</td></tr>';
    var antIntro = externalOnly
      ? '<p class="rep-summary-hint">Showing external (procurement-relevant) antennas only. Toggle in the sidebar to see the full antenna list.</p>'
      : '<p class="rep-summary-hint">All antennas including integrated (built-in) ones. Toggle "External only" in the sidebar for a procurement-ready view.</p>';
    var antSection = antRows.length
      ? '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Antenna quantities</h2>'
        + antIntro
        + '<table class="rep-ap-table"><thead><tr>'
        + '<th>Antenna</th><th>Coupling</th><th>Band</th><th>Gain</th><th class="rep-num">Qty</th>'
        + '</tr></thead><tbody>' + antRowsHtml + antTotalRow + '</tbody></table>'
        + '</section>'
      : '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Antenna quantities</h2>'
        + '<p class="rep-empty-small">No antennas match the current filter. Try turning off "External only" in the sidebar.</p>'
        + '</section>';


    var notes = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Notes for procurement</h2>'
      + '<ul class="rep-summary-notes">'
      + '<li>Antenna quantities count each radio-to-antenna assignment. An AP with a dual-band external antenna kit is counted per radio (2×), not per physical part — cross-check against your antenna kit\'s inclusions.</li>'
      + '<li>Mount hardware, cable runs, cable ties, PoE injectors, and switch ports are <b>not</b> derived from Ekahau data. Add those manually per your rack/ceiling standard.</li>'
      + '<li>External-antenna APs typically ship without their antennas; verify the AP part number matches your procurement SKU (e.g. Cisco C9166I-B vs. C9166I-E for internal vs. external).</li>'
      + '<li>This BOM reflects the design shown in the .esx as of ' + WD.esc(ctx.dateStr) + '. Cross-reference with the final walked design before ordering.</li>'
      + '</ul>'
      + '</section>';

    return head + apSection + antSection + notes
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function classifyHotspot(ssid) {
    if (!ssid) return null;
    var s = String(ssid).trim();
    var low = s.toLowerCase();
    if (/['’]s\s+i(phone|pad|pod)\b/.test(low)) return 'iPhone';
    if (/\bi(phone|pad|pod)\b/.test(low)) return 'iPhone';
    if (/^androidap[_\-]/.test(low)) return 'Android';
    if (/^androidshare[_\-]/.test(low)) return 'Android';
    if (/direct-.{1,3}-androidap/.test(low)) return 'Android';
    if (/^galaxy\s/.test(low)) return 'Android';
    if (/^samsung\s+galaxy/.test(low)) return 'Android';
    if (/^hotspot[a-z0-9]{3,8}$/.test(low)) return 'Carrier hotspot';
    if (/^wi-?fi\s+hotspot\s+\d+/.test(low)) return 'Carrier hotspot';
    if (/mifi|jetpack/.test(low)) return 'Carrier hotspot';
    if (/[_\-]hotspot\b/.test(low)) return 'Carrier hotspot';
    if (/^att[a-z0-9]{6,10}$/.test(s)) return 'ATT (phone or gateway)';
    return null;
  }

  function hotspotBand(chans) {
    if (!chans || !chans.length) return '—';
    var bands = {};
    chans.forEach(function (c) {
      if (c < 3000) bands['2.4'] = 1;
      else if (c >= 5955) bands['6'] = 1;
      else bands['5'] = 1;
    });
    return Object.keys(bands).sort().join(' / ') + ' GHz';
  }

  function hotspotChannel(chans) {
    if (!chans || !chans.length) return '';
    return chans.map(function (c) {
      if (c >= 2412 && c <= 2484) return 'ch' + (c === 2484 ? 14 : (c - 2407) / 5);
      if (c >= 5000 && c <= 5900) return 'ch' + ((c - 5000) / 5);
      if (c >= 5955) return 'ch' + ((c - 5950) / 5) + '(6E)';
      return String(c);
    }).join(', ');
  }




  function channelWidthMHz(chans) {
    return (chans && chans.length) ? chans.length * 20 : null;
  }






  function interferenceSeverity(chans) {
    var widthMHz = channelWidthMHz(chans);
    if (!widthMHz) return 'Low';
    var has24 = chans.some(function (c) { return c < 3000; });
    if (widthMHz >= 80) return 'High';
    if (widthMHz === 40) return has24 ? 'High' : 'Medium';
    return 'Low';
  }

  var SEV_RANK = { High: 2, Medium: 1, Low: 0 };
  var SEV_CLASS = { High: 'rep-sev-chip--high', Medium: 'rep-sev-chip--medium', Low: 'rep-sev-chip--low' };
  function sevChip(sev) {
    return '<span class="rep-sev-chip ' + SEV_CLASS[sev] + '">' + sev + '</span>';
  }

  function buildMeasurementToFloors() {
    var out = {};
    proj.surveys.forEach(function (sv) {
      var fpid = sv.floorPlanId;
      if (!fpid) return;
      (sv.wifiTracks || []).forEach(function (wt) {
        (wt.accessPointMeasurementIds || []).forEach(function (mid) {
          if (!out[mid]) out[mid] = {};
          out[mid][fpid] = 1;
        });
      });
    });
    return out;
  }

  function surveyPolylinesForFloor(fpId, extraClass) {
    var out = '';
    proj.surveys.forEach(function (sv) {
      if (sv.floorPlanId !== fpId) return;
      (sv.routePoints || []).forEach(function (seg) {
        var pts = (seg || []).filter(function (rp) { return rp && rp.location; })
          .map(function (rp) { return rp.location.x.toFixed(1) + ',' + rp.location.y.toFixed(1); });
        if (pts.length >= 2) {
          out += '<polyline class="rep-hotspot-walk' + (extraClass || '') + '" points="' + pts.join(' ') + '"/>';
        }
      });
    });
    return out;
  }

  var HOTSPOT_CHIP_CLASS = {
    'iPhone':                 'rep-hotspot-chip--iphone',
    'Android':                'rep-hotspot-chip--android',
    'Carrier hotspot':        'rep-hotspot-chip--carrier',
    'ATT (phone or gateway)': 'rep-hotspot-chip--att',
    'Wide-channel Wi-Fi':     'rep-hotspot-chip--wide',
  };

  function renderInterferenceReport(aps, opts, ctx) {
    if (!proj.measurements.length) {
      return (opts.cover ? ctx.cover(0, ctx.dateStr, 'Interferers detected') : ctx.inlineHeader(0, ctx.dateStr, 'Interferers detected'))
        + '<section class="rep-floor-section">'
        +   '<h2 class="rep-floor-title">No survey data</h2>'
        +   '<div class="rep-empty-small">This .esx contains only design/planning data — no measured APs to report on. '
        +     'Open a project file that includes an Ekahau Survey walk.</div>'
        + '</section>'
        + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
    }

    var accept = {
      'iPhone': !!opts.catIphone,
      'Android': !!opts.catAndroid,
      'Carrier hotspot': !!opts.catCarrier,
      'ATT (phone or gateway)': !!opts.catAtt,
    };
    var acceptWide = !!opts.catWide;

    var floorMap = buildMeasurementToFloors();
    var hotspots = [];
    proj.measurements.forEach(function (m) {
      var chans = m.channelByCenterFrequencyDefinedNarrowChannels;
      var widthMHz = channelWidthMHz(chans);
      var isWide = widthMHz != null && widthMHz >= 40;
      var cat = classifyHotspot(m.ssid);
      if (cat) {
        if (!accept[cat]) return;
      } else if (isWide && acceptWide) {
        cat = 'Wide-channel Wi-Fi';
      } else {
        return;
      }
      var floors = Object.keys(floorMap[m.id] || {});
      var floorNames = floors.map(function (fid) {
        var f = proj.floorPlans.find(function (x) { return x.id === fid; });
        return f ? f.name : '';
      }).filter(Boolean);
      hotspots.push({
        ssid: m.ssid || '(hidden)',
        mac: m.mac || '—',
        category: cat,
        security: m.security || '—',
        band: hotspotBand(chans),
        channel: hotspotChannel(chans),
        widthMHz: widthMHz,
        severity: interferenceSeverity(chans),
        floorIds: floors,
        floorNames: floorNames,
      });
    });

    var catRank = { 'iPhone': 0, 'Android': 1, 'Carrier hotspot': 2, 'ATT (phone or gateway)': 3, 'Wide-channel Wi-Fi': 4 };
    hotspots.sort(function (a, b) {
      return (SEV_RANK[b.severity] - SEV_RANK[a.severity])
        || (catRank[a.category] - catRank[b.category])
        || (a.ssid || '').toLowerCase().localeCompare((b.ssid || '').toLowerCase());
    });

    function chip(cat) {
      return '<span class="rep-hotspot-chip ' + HOTSPOT_CHIP_CLASS[cat] + '">' + WD.esc(cat) + '</span>';
    }

    var head = opts.cover
      ? ctx.cover(hotspots.length, ctx.dateStr, 'Interferers detected')
      : ctx.inlineHeader(hotspots.length, ctx.dateStr, 'Interferers detected');

    var counts = { 'iPhone': 0, 'Android': 0, 'Carrier hotspot': 0, 'ATT (phone or gateway)': 0, 'Wide-channel Wi-Fi': 0 };
    var highCount = 0;
    hotspots.forEach(function (h) { counts[h.category]++; if (h.severity === 'High') highCount++; });
    var summary = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Summary</h2>'
      + '<div class="rep-hotspot-stats">'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--total">'
      +     '<b>' + hotspots.length + '</b><span>Total interferers</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--severity">'
      +     '<b>' + highCount + '</b><span>High severity</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--iphone">'
      +     '<b>' + counts['iPhone'] + '</b><span>iPhone / iPad</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--android">'
      +     '<b>' + counts['Android'] + '</b><span>Android</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--carrier">'
      +     '<b>' + (counts['Carrier hotspot'] + counts['ATT (phone or gateway)']) + '</b>'
      +     '<span>Carrier / MiFi</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--wide">'
      +     '<b>' + counts['Wide-channel Wi-Fi'] + '</b><span>Wide-channel Wi-Fi</span></div>'
      + '</div></section>';

    var overlays = '';
    if (opts.overview) {
      var floorSevRank = {};
      hotspots.forEach(function (h) {
        h.floorIds.forEach(function (fid) {
          var r = SEV_RANK[h.severity];
          if (r > (floorSevRank[fid] || 0)) floorSevRank[fid] = r;
        });
      });
      proj.floorPlans.forEach(function (fp) {
        var url = proj.imageUrls[fp.bitmapImageId || fp.imageId];
        if (!url) return;
        var floorHotspots = hotspots.filter(function (h) {
          return h.floorIds.indexOf(fp.id) !== -1;
        });
        var flagged = floorHotspots.filter(function (h) { return h.severity !== 'Low'; })
          .sort(function (a, b) { return SEV_RANK[b.severity] - SEV_RANK[a.severity]; });
        var flaggedChips = flagged.slice(0, 6).map(function (h) {
          return sevChip(h.severity) + ' <span class="rep-hotspot-floor-flag-ssid">' + WD.esc(h.ssid) + '</span>';
        }).join(' &nbsp; ');
        if (flagged.length > 6) flaggedChips += ' &nbsp; <span class="rep-hotspot-floor-flag-ssid">+' + (flagged.length - 6) + ' more</span>';
        var rank = floorSevRank[fp.id] || 0;
        var walkClass = rank === 2 ? ' rep-hotspot-walk--high' : rank === 1 ? ' rep-hotspot-walk--medium' : '';
        var polylines = surveyPolylinesForFloor(fp.id, walkClass);
        overlays += '<section class="rep-floor-section">'
          + '<h2 class="rep-floor-title">Floor ' + WD.esc(fp.name || 'plan')
          +   ' <span class="rep-hotspot-floor-count">- '
          +   floorHotspots.length + ' interferer' + (floorHotspots.length === 1 ? '' : 's') + ' detected</span>'
          + '</h2>'
          + (flaggedChips ? '<div class="rep-hotspot-floor-flags">' + flaggedChips + '</div>' : '')
          + '<div class="rep-overview"><div class="rep-overview-plan rep-hotspot-fp" '
          +   'data-crop-src="' + WD.escAttr(url) + '" '
          +   'style="--w:' + fp.width + ';--h:' + fp.height + '">'
          +   '<img src="' + url + '" alt="Floor plan">'
          +   '<svg viewBox="0 0 ' + fp.width + ' ' + fp.height + '" preserveAspectRatio="none">'
          +     polylines
          +   '</svg>'
          + '</div>'
          + '<div class="rep-overview-key">Walk path = where scans were captured on this floor '
          +   '(blue = normal, amber = a medium-severity interferer was seen here, red = a high-severity one). '
          +   'This traces the walk, not the interferer&#39;s exact position - see &quot;How we classified these&quot; below.</div>'
          + '</div></section>';
      });
    }

    var showChannel = !!opts.channel;
    var rows = hotspots.map(function (h) {
      return '<tr><td>' + chip(h.category) + '</td>'
        + '<td class="rep-name">' + WD.esc(h.ssid) + '</td>'
        + '<td class="rep-az">' + WD.esc(h.mac) + '</td>'
        + '<td>' + WD.esc(h.band) + '</td>'
        + (showChannel ? '<td>' + WD.esc(h.channel) + '</td>' : '')
        + '<td>' + (h.widthMHz ? h.widthMHz + ' MHz' : '—') + '</td>'
        + '<td>' + sevChip(h.severity) + '</td>'
        + '<td>' + WD.esc(h.security) + '</td>'
        + '<td>' + (h.floorNames.length ? h.floorNames.map(function (n) { return 'Fl ' + WD.esc(n); }).join(', ') : '—') + '</td>'
        + '</tr>';
    }).join('');

    var colCount = showChannel ? 9 : 8;
    var tableSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">All detected interferers</h2>'
      + '<table class="rep-ap-table">'
      +   '<thead><tr>'
      +     '<th>Category</th><th>SSID</th><th>BSSID</th><th>Band</th>'
      +     (showChannel ? '<th>Channel(s)</th>' : '')
      +     '<th>Width</th><th>Severity</th><th>Security</th><th>Seen on</th>'
      +   '</tr></thead>'
      +   '<tbody>' + (rows || '<tr><td colspan="' + colCount + '" class="rep-empty-small">No interferers matched the selected categories.</td></tr>') + '</tbody>'
      + '</table></section>';

    var method = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">How we classified these</h2>'
      + '<div class="rep-hotspot-method">'
      +   'Each row is a unique BSSID picked up during the passive survey walk. '
      +   'An SSID was flagged as a phone/carrier hotspot when it matched one of the default naming patterns, '
      +   'or as <b>Wide-channel Wi-Fi</b> when it did not match a naming pattern but was still transmitting on '
      +   'a 40MHz+ channel - wide enough to be a plausible interference source on its own:'
      +   '<ul>'
      +     '<li><b>iPhone / iPad</b> — SSID contains iPhone, iPad, or "’s iPhone" (default iOS Personal Hotspot naming).</li>'
      +     '<li><b>Android</b> — AndroidAP_XXXX, AndroidShare_XXXX, DIRECT-xx-AndroidAP, or a Samsung Galaxy device name.</li>'
      +     '<li><b>Carrier hotspot / MiFi</b> — HotspotXXXX, WiFi Hotspot NNNN, or SSIDs containing MiFi / Jetpack (Verizon and T-Mobile default names for standalone hotspot devices).</li>'
      +     '<li><b>ATT (phone or gateway)</b> — SSIDs matching ATT[6-10 chars]. This pattern is used by both AT&amp;T phone hotspots and AT&amp;T home gateways, so treat as suggestive rather than definitive.</li>'
      +     '<li><b>Wide-channel Wi-Fi</b> - any other BSSID using a 40MHz or wider channel. Catches rogue APs and hotspots that do not match a phone-naming pattern.</li>'
      +   '</ul>'
      +   '<p><b>Severity</b> is channel width plus band, not a comparison against your own APs&#39; assigned channels (this tool does not have a reliable read on those from the .esx design data): '
      +   '<b>High</b> = 80MHz+ anywhere, or 40MHz in the crowded 2.4GHz band. <b>Medium</b> = 40MHz in 5/6GHz. <b>Low</b> = 20MHz or unknown.</p>'
      +   '<p><b>Excluded intentionally:</b> car head units (Uconnect, MBUX, CarPlay, CarLink), dashcams (ROVE, VANTRUE, 70mai), printers/scanners, T-Mobile CellSpot femtocells, and other non-phone personal Wi-Fi devices.</p>'
      +   '<p><b>The floor plan overlay is a detection map, not a signal-strength heat map.</b> It shows the surveyor&#39;s walk path colored by the worst severity detected while walking that floor - it does not pinpoint the interferer&#39;s physical location, because the .esx does not expose per-point signal readings tied to coordinates.</p>'
      + '</div>'
      + '</section>';

    return head + summary + overlays + tableSection + method
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }





  function renderAimReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points to aim')
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points to aim');

    if (!aps.length) {
      return head
        + '<section class="rep-floor-section">'
        +   '<h2 class="rep-floor-title">No directional APs</h2>'
        +   '<div class="rep-empty-small">This report only lists APs that need aiming. Enable "Include omni APs" in the sidebar if you want the omni units on the sheet too.</div>'
        + '</section>'
        + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
    }

    var floorOrder = proj.floorPlans.slice();
    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });
    if (byFloor['_none']) floorOrder.push({ id: '_none', name: '(No floor plan)' });

    var sorted = [];
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      floorAps.slice()
        .sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
        .forEach(function (ap) { sorted.push({ ap: ap, floor: fp }); });
    });

    var showSignOff = opts.signOff !== false;
    var rows = '';
    sorted.forEach(function (item, i) {
      var ap = item.ap;
      var r = ctx.primaryRadio(ap.id);
      var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
      var dir = r ? r.antennaDirection : null;
      var tilt = r ? r.antennaTilt : null;
      var height = r ? r.antennaHeight : null;

      var heightStr = height == null ? '—'
        : (opts.imperial !== false
            ? ctx.fmt(height, 2) + ' m &nbsp;<span class="rep-alt">(' + ctx.fmt(ctx.metersToFt(height), 2) + ' ft)</span>'
            : ctx.fmt(height, 2) + ' m');
      var azStr = dir == null ? '<span class="rep-alt">omni</span>'
        : (opts.compass !== false
            ? ctx.fmt(dir, 1) + '° <span class="rep-alt">(' + ctx.compass(dir) + ')</span>'
            : ctx.fmt(dir, 1) + '°');
      var tiltStr = tilt == null ? '—' : ctx.fmt(tilt, 1) + '°';

      var lbl = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      rows += '<tr>'
        + '<td class="rep-num">' + WD.esc(lbl) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
        + '<td>' + WD.esc(item.floor.name || '—') + '</td>'
        + '<td class="rep-az">' + azStr + '</td>'
        + '<td>' + tiltStr + '</td>'
        + '<td>' + heightStr + '</td>'
        + '<td>' + WD.esc(ant ? ant.name : '—') + '</td>'
        + (showSignOff ? '<td class="rep-aim-signoff"></td><td class="rep-aim-signoff"></td>' : '')
        + '</tr>';
    });

    var table = '<section class="rep-aim-table-section">'
      + '<table class="rep-ap-table rep-aim-table">'
      +   '<thead><tr>'
      +     '<th class="rep-num">#</th>'
      +     '<th>AP name</th>'
      +     '<th>Floor</th>'
      +     '<th>Azimuth</th>'
      +     '<th>Tilt</th>'
      +     '<th>Height</th>'
      +     '<th>Antenna</th>'
      +     (showSignOff ? '<th class="rep-aim-signoff-head">Installer initials</th><th class="rep-aim-signoff-head">Date</th>' : '')
      +   '</tr></thead>'
      +   '<tbody>' + rows + '</tbody>'
      + '</table>'
      + '</section>';

    var maps = '';
    if (opts.overview !== false) {
      floorOrder.forEach(function (fp) {
        var floorAps = byFloor[fp.id];
        if (!floorAps || !floorAps.length || fp.id === '_none') return;
        maps += renderAimMiniMap(fp, floorAps, opts, ctx);
      });
    }

    return head + table + maps
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderAimMiniMap(fp, floorAps, opts, ctx) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) return '';
    var W = fp.width || 1, H = fp.height || 1;
    var tickLen = Math.min(W, H) * 0.05;
    var dotR = Math.min(W, H) * 0.014;

    var minDim = Math.min(W, H);
    var markers = '';
    floorAps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var r = ctx.primaryRadio(ap.id);
      var dir = r ? r.antennaDirection : null;
      var isDirectional = radioIsDirectional(r);
      markers += '<g class="rep-aim-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional) {
        markers += '<g transform="rotate(' + dir + ')">'
          + '<line class="rep-aim-tick" x1="0" y1="0" x2="0" y2="' + (-tickLen) + '"/>'
          + '</g>';
      }
      var label = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      var labelFont = minDim * 0.022 * Math.min(1, 3 / Math.max(3, label.length));
      var padX = minDim * 0.006;
      var boxW = Math.max(minDim * 0.03, label.length * labelFont * 0.65) + padX * 2;
      var boxH = minDim * 0.028;
      var cornerR = minDim * 0.005;
      markers += '<rect class="rep-aim-dot" x="' + (-boxW / 2) + '" y="' + (-boxH / 2) + '" width="' + boxW + '" height="' + boxH + '" rx="' + cornerR + '" ry="' + cornerR + '"/>'
        + '<text class="rep-aim-num" y="' + (labelFont * 0.35) + '" text-anchor="middle" font-size="' + labelFont + '">'
        + WD.esc(label) + '</text></g>';
    });

    var labelHint = opts.shortLabels === false
      ? 'Labels: full AP name.'
      : 'Labels: trailing "APnn" from each AP name (e.g. "42" for "…AP42"). Names without that suffix show the full name.';
    return '<section class="rep-floor-section rep-aim-map-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
      + '<div class="rep-overview">'
      +   '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +     '<img src="' + url + '" alt="Floor plan">'
      +     '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      +   '</div>'
      +   '<div class="rep-overview-key">' + WD.esc(labelHint) + '</div>'
      + '</div>'
      + '</section>';
  }






  var COV_THRESH_STRONG = -55;
  var COV_THRESH_GOOD   = -67;
  var COV_THRESH_FAIR   = -75;
  var COV_THRESH_WEAK   = -80;

  function _covBandFromChannel(channels) {
    if (!channels || !channels.length) return 'FIVE';
    var f = channels[0];
    if (f < 3000) return 'TWO';
    if (f < 5950) return 'FIVE';
    return 'SIX';
  }

  function _covBandLabel(band) {
    if (band === 'TWO') return '2.4 GHz';
    if (band === 'SIX') return '6 GHz';
    return '5 GHz';
  }

  function _covBandColor(band) {
    if (band === 'TWO') return '#1e77ac';
    if (band === 'SIX') return '#8b5cf6';
    return '#5fab4f';
  }



  function _covPlBase(band) {
    if (band === 'TWO') return 40.0;
    if (band === 'SIX') return 48.0;
    return 46.5;
  }

  function _covRadiusMeters(eirp, rssiTarget, band) {
    var pl = eirp - rssiTarget;
    var expo = (pl - _covPlBase(band)) / 30.0;
    var r = Math.pow(10, expo);
    if (!isFinite(r) || r < 0.1) return 0.1;
    if (r > 500) return 500;
    return r;
  }

  function _covApRadio(ap) {


    var r = primaryRadio(ap.id);
    if (r) return r;
    var rs = proj.radios.filter(function (x) { return x.accessPointId === ap.id; });
    return rs[0] || null;
  }

  function renderCoverageReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points')
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points');

    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var sections = '';
    var indexById = {};


    var seq = 0;
    (proj.floorPlans || []).forEach(function (fp) {
      (byFloor[fp.id] || []).forEach(function (ap) { indexById[ap.id] = ++seq; });
    });
    (byFloor['_none'] || []).forEach(function (ap) { indexById[ap.id] = ++seq; });

    (proj.floorPlans || []).forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderCoverageFloorSection(fp, floorAps, opts, ctx, indexById);
    });

    var legend = opts.legend !== false ? renderCoverageLegend(aps, opts, ctx, indexById) : '';
    var method = renderCoverageMethodology(opts);

    return head + sections + legend + method
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderCoverageFloorSection(fp, aps, opts, ctx, indexById) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) {
      return '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
        + '<div class="rep-empty-small">Floor plan image not available.</div>'
        + '</section>';
    }
    var W = fp.width || 1, H = fp.height || 1;
    var mPerU = fp.metersPerUnit || 0.05;
    var showCells = opts.primaryCells !== false;
    var showRings = opts.signalRings === true;
    var showLabels = opts.showApLabels !== false;
    var bandTint = opts.bandColors !== false;
    var minDim = Math.min(W, H);

    var cellsSvg = '', ringsSvg = '', pinsSvg = '';
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var r = _covApRadio(ap);
      if (!r) return;
      var ant = r.antennaTypeId ? proj.antennas[r.antennaTypeId] : null;
      var gain = ant && ant.maxGain != null ? ant.maxGain : 3;
      var txp = r.transmitPower != null ? r.transmitPower : 15;
      var eirp = txp + gain;
      var band = _covBandFromChannel(r.channelByCenterFrequencyDefinedNarrowChannels);
      var color = bandTint ? _covBandColor(band) : '#0668D9';

      var rGood   = _covRadiusMeters(eirp, COV_THRESH_GOOD,   band) / mPerU;
      if (showCells) {
        cellsSvg += '<circle class="rep-cov-cell" cx="' + c.x + '" cy="' + c.y + '" r="' + rGood + '" fill="' + color + '" fill-opacity="0.13" stroke="' + color + '" stroke-opacity="0.55" stroke-width="' + (minDim * 0.0015) + '"/>';
      }
      if (showRings) {
        var rStrong = _covRadiusMeters(eirp, COV_THRESH_STRONG, band) / mPerU;
        var rFair   = _covRadiusMeters(eirp, COV_THRESH_FAIR,   band) / mPerU;
        var rWeak   = _covRadiusMeters(eirp, COV_THRESH_WEAK,   band) / mPerU;
        var sw = minDim * 0.0015;
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rStrong + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.9"/>';
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rFair   + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.55" stroke-dasharray="' + (minDim * 0.008) + ' ' + (minDim * 0.005) + '"/>';
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rWeak   + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.35" stroke-dasharray="' + (minDim * 0.003) + ' ' + (minDim * 0.006) + '"/>';
      }
      var covLabel = String(indexById[ap.id] || '');
      var covFont = minDim * 0.022;
      var covPadX = minDim * 0.006;
      var covBoxW = Math.max(minDim * 0.03, covLabel.length * covFont * 0.65) + covPadX * 2;
      var covBoxH = minDim * 0.028;
      var covCornerR = minDim * 0.005;
      pinsSvg += '<g class="rep-cov-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      pinsSvg += '<rect class="rep-cov-dot" x="' + (-covBoxW / 2) + '" y="' + (-covBoxH / 2) + '" width="' + covBoxW + '" height="' + covBoxH + '" rx="' + covCornerR + '" ry="' + covCornerR + '" fill="' + color + '" stroke="#fff" stroke-width="' + (minDim * 0.003) + '"/>';
      if (showLabels) {
        pinsSvg += '<text class="rep-cov-num" y="' + (covFont * 0.35) + '" text-anchor="middle" font-size="' + covFont + '" fill="#fff" font-weight="700">' + covLabel + '</text>';
      }
      pinsSvg += '</g>';
    });

    return '<section class="rep-floor-section rep-cov-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
      + '<div class="rep-overview">'
      +   '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +     '<img src="' + url + '" alt="Floor plan">'
      +     '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + cellsSvg + ringsSvg + pinsSvg + '</svg>'
      +   '</div>'
      +   renderCoverageFloorKey(opts)
      + '</div>'
      + '</section>';
  }

  function renderCoverageFloorKey(opts) {
    var items = [];
    if (opts.primaryCells !== false) items.push('<span class="rep-cov-key-swatch cell"></span> Primary cell (&minus;67 dBm)');
    if (opts.signalRings === true) {
      items.push('<span class="rep-cov-key-swatch ring-strong"></span> Strong &lt;&minus;55');
      items.push('<span class="rep-cov-key-swatch ring-fair"></span> Fair &lt;&minus;75');
      items.push('<span class="rep-cov-key-swatch ring-weak"></span> Weak &lt;&minus;80');
    }
    if (opts.bandColors !== false) {
      items.push('<span class="rep-cov-band-swatch two"></span> 2.4 GHz');
      items.push('<span class="rep-cov-band-swatch five"></span> 5 GHz');
      items.push('<span class="rep-cov-band-swatch six"></span> 6 GHz');
    }
    if (!items.length) return '';
    return '<div class="rep-cov-key">' + items.join(' &nbsp;·&nbsp; ') + '</div>';
  }

  function renderCoverageLegend(aps, opts, ctx, indexById) {
    var rows = '';
    aps.slice()
      .sort(function (a, b) { return (indexById[a.id] || 0) - (indexById[b.id] || 0); })
      .forEach(function (ap) {
        var r = _covApRadio(ap);
        if (!r) return;
        var ant = r.antennaTypeId ? proj.antennas[r.antennaTypeId] : null;
        var gain = ant && ant.maxGain != null ? ant.maxGain : 3;
        var txp = r.transmitPower != null ? r.transmitPower : 15;
        var eirp = txp + gain;
        var band = _covBandFromChannel(r.channelByCenterFrequencyDefinedNarrowChannels);
        var rGood = _covRadiusMeters(eirp, COV_THRESH_GOOD, band);
        var rWeak = _covRadiusMeters(eirp, COV_THRESH_WEAK, band);
        rows += '<tr>'
          + '<td class="rep-num">' + (indexById[ap.id] || '') + '</td>'
          + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
          + '<td>' + _covBandLabel(band) + '</td>'
          + '<td>' + fmt(txp, 1) + ' dBm</td>'
          + '<td>' + fmt(gain, 1) + ' dBi</td>'
          + '<td>' + fmt(eirp, 1) + ' dBm</td>'
          + '<td>' + fmt(rGood, 1) + ' m</td>'
          + '<td>' + fmt(rWeak, 1) + ' m</td>'
          + '</tr>';
      });
    if (!rows) return '';
    return '<section class="rep-legend rep-cov-legend">'
      + '<h2 class="rep-floor-title">Cell sizing per AP</h2>'
      + '<table class="rep-ap-table">'
      +   '<thead><tr>'
      +     '<th class="rep-num">#</th><th>AP name</th><th>Band</th>'
      +     '<th>TX power</th><th>Antenna gain</th><th>EIRP</th>'
      +     '<th>&minus;67 dBm radius</th><th>&minus;80 dBm radius</th>'
      +   '</tr></thead>'
      +   '<tbody>' + rows + '</tbody>'
      + '</table>'
      + '</section>';
  }

  function renderCoverageMethodology(opts) {
    return '<section class="rep-floor-section rep-cov-method">'
      + '<h2 class="rep-floor-title">Methodology &amp; caveats</h2>'
      + '<div class="rep-hotspot-method">'
      +   '<p><b>Model.</b> Cell radii use a simple log-distance path-loss model with exponent <b>n = 3</b> and per-band 1-metre baselines (40 dB at 2.4 GHz, 46.5 dB at 5 GHz, 48 dB at 6 GHz). Received signal is estimated as <b>RSSI = EIRP &minus; PathLoss(d)</b> and solved for the distance <b>d</b> at each threshold.</p>'
      +   '<p><b>Thresholds.</b> Strong &lt; &minus;55 dBm · Good &minus;55 to &minus;67 · Fair &minus;67 to &minus;75 · Weak &minus;75 to &minus;80. The filled primary cell is drawn at the &minus;67 dBm boundary — the standard threshold for reliable voice and video.</p>'
      +   '<p><b>What it does not model.</b> Walls, floors, and materials are not attenuated. Directional antennas are treated as omnidirectional for the purpose of cell radius — the extra gain enlarges the circle uniformly rather than shaping a sector. Interference, channel overlap, client-side sensitivity, and airtime utilisation are all outside the scope of this drawing.</p>'
      +   '<p><b>Read this report as.</b> An advisory sanity check for AP placement — "does the map look reasonable, and where are the obvious weak-signal gaps." Not a substitute for a measured predictive survey.</p>'
      + '</div>'
      + '</section>';
  }

  function autocropOverlay(overlayEl) {
    var img = overlayEl.querySelector('img');
    var svg = overlayEl.querySelector('svg');
    if (!img || !svg) return Promise.resolve();
    var vb = (svg.getAttribute('viewBox') || '').split(/\s+/).map(Number);
    if (vb.length !== 4 || !vb[2] || !vb[3]) return Promise.resolve();
    var VBX = vb[0], VBY = vb[1], VBW = vb[2], VBH = vb[3];

    return new Promise(function (resolve) {
      function ready() {
        try { doCrop(); } catch (e) { console.error('autocrop', e); }
        resolve();
      }
      if (img.complete && img.naturalWidth) ready();
      else { img.addEventListener('load', ready, {once: true});
             img.addEventListener('error', function () { resolve(); }, {once: true}); }
    });

    function doCrop() {
      var natW = img.naturalWidth, natH = img.naturalHeight;
      if (!natW || !natH) return;
      var scale = Math.min(1, 500 / Math.max(natW, natH));
      var sW = Math.max(1, Math.round(natW * scale));
      var sH = Math.max(1, Math.round(natH * scale));
      var c = document.createElement('canvas');
      c.width = sW; c.height = sH;
      var g = c.getContext('2d', {willReadFrequently: true});
      g.drawImage(img, 0, 0, sW, sH);
      var data;
      try { data = g.getImageData(0, 0, sW, sH).data; }
      catch (e) { return; }
      var minX = sW, minY = sH, maxX = -1, maxY = -1;
      for (var y = 0; y < sH; y++) {
        for (var x = 0; x < sW; x++) {
          var i = (y * sW + x) * 4;
          if (data[i] < 245 || data[i + 1] < 245 || data[i + 2] < 245) {
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
          }
        }
      }
      if (maxX < 0) return;
      var kx = VBW / sW, ky = VBH / sH;
      var cx0 = VBX + minX * kx;
      var cy0 = VBY + minY * ky;
      var cx1 = VBX + (maxX + 1) * kx;
      var cy1 = VBY + (maxY + 1) * ky;
      var plines = svg.querySelectorAll('polyline');
      for (var pi = 0; pi < plines.length; pi++) {
        var pts = (plines[pi].getAttribute('points') || '').trim().split(/\s+/);
        for (var pj = 0; pj < pts.length; pj++) {
          var xy = pts[pj].split(',');
          var px = +xy[0], py = +xy[1];
          if (!isFinite(px) || !isFinite(py)) continue;
          if (px < cx0) cx0 = px;
          if (px > cx1) cx1 = px;
          if (py < cy0) cy0 = py;
          if (py > cy1) cy1 = py;
        }
      }
      var pad = Math.max(8, Math.min(cx1 - cx0, cy1 - cy0) * 0.02);
      cx0 = Math.max(VBX, cx0 - pad);
      cy0 = Math.max(VBY, cy0 - pad);
      cx1 = Math.min(VBX + VBW, cx1 + pad);
      cy1 = Math.min(VBY + VBH, cy1 + pad);
      var cW = cx1 - cx0, cH = cy1 - cy0;
      if (cW / VBW > 0.9 && cH / VBH > 0.9) return;
      var srcX = Math.round(natW * (cx0 - VBX) / VBW);
      var srcY = Math.round(natH * (cy0 - VBY) / VBH);
      var srcW = Math.round(natW * cW / VBW);
      var srcH = Math.round(natH * cH / VBH);
      var outScale = Math.min(1, 2000 / Math.max(srcW, srcH));
      var out = document.createElement('canvas');
      out.width = Math.max(1, Math.round(srcW * outScale));
      out.height = Math.max(1, Math.round(srcH * outScale));
      out.getContext('2d').drawImage(img, srcX, srcY, srcW, srcH,
                                     0, 0, out.width, out.height);
      out.toBlob(function (blob) {
        if (!blob) return;
        var newUrl = URL.createObjectURL(blob);
        img.src = newUrl;
        overlayEl.style.setProperty('--w', cW);
        overlayEl.style.setProperty('--h', cH);
        svg.setAttribute('viewBox', cx0 + ' ' + cy0 + ' ' + cW + ' ' + cH);
      }, 'image/jpeg', 0.85);
    }
  }

  function applyHotspotAutocrop(host, opts) {
    if (!opts.autocrop) return;
    var overlays = host.querySelectorAll('.rep-overview-plan[data-crop-src]');
    for (var i = 0; i < overlays.length; i++) autocropOverlay(overlays[i]);
  }

  function renderApLocationReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points')
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points');

    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });

    var floorOrder = proj.floorPlans.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    if (byFloor['_none']) floorOrder.push({ id: '_none', name: '(No floor plan)' });

    var sections = '';
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      var sorted = floorAps.slice().sort(function (a, b) {
        return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
      });
      var out = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
      if (fp.id !== '_none') {
        out += renderApLocationOverview(fp, sorted, opts, ctx);
      }
      out += renderApLocationTable(sorted, fp, opts, ctx);
      out += '</section>';
      sections += out;
    });

    var audit = opts.nameAudit ? renderApNameAudit(aps, ctx) : '';

    return head + sections + audit
      + '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';
  }

  function renderApLocationOverview(fp, aps, opts, ctx) {
    var imgId = fp.bitmapImageId || fp.imageId;
    var url = proj.imageUrls[imgId];
    if (!url) return '<div class="rep-empty-small">Floor plan image not available.</div>';
    var W = fp.width || 1, H = fp.height || 1;

    if (opts.segmented) {
      var grid = computeAntennaGrid(W, H, aps, opts);
      if (grid.cols * grid.rows > 1) return renderApLocationSegmented(url, W, H, aps, opts, ctx, grid);
    }

    var markers = buildApLocationMarkers(aps, W, H, opts);
    return '<div class="rep-overview">'
      + '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key">AP positions from .esx design data. Labels show ' + (opts.shortLabels === false ? 'full AP name' : 'short designator from AP name') + '.</div>'
      + '</div>';
  }

  function buildApLocationMarkers(aps, W, H, opts) {
    var markers = '';
    var minDim = Math.min(W, H);
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var label = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      var labelFont = minDim * 0.018 * Math.min(1, 4 / Math.max(4, label.length));
      var padX = minDim * 0.005;
      var boxW = Math.max(minDim * 0.025, label.length * labelFont * 0.65) + padX * 2;
      var boxH = minDim * 0.024;
      var cornerR = minDim * 0.004;
      markers += '<g class="rep-mark rep-mark--loc" transform="translate(' + c.x + ',' + c.y + ')">'
        + '<rect class="rep-mark-dot" x="' + (-boxW / 2) + '" y="' + (-boxH / 2) + '" width="' + boxW + '" height="' + boxH + '" rx="' + cornerR + '" ry="' + cornerR + '"/>'
        + '<text class="rep-mark-label" y="' + (labelFont * 0.35) + '" text-anchor="middle" font-size="' + labelFont + '">' + WD.esc(label) + '</text></g>';
    });
    return markers;
  }

  function renderApLocationSegmented(url, W, H, aps, opts, ctx, grid) {
    var cols = grid.cols, rows = grid.rows;
    var cw = W / cols, ch = H / rows;
    var cells = [];
    for (var ri = 0; ri < rows; ri++) {
      for (var ci = 0; ci < cols; ci++) {
        cells.push({ col: ci, row: ri, x0: ci * cw, y0: ri * ch, x1: (ci + 1) * cw, y1: (ri + 1) * ch, aps: [] });
      }
    }
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var ci = Math.min(cols - 1, Math.max(0, Math.floor(c.x / cw)));
      var ri = Math.min(rows - 1, Math.max(0, Math.floor(c.y / ch)));
      cells[ri * cols + ci].aps.push(ap);
    });
    var nonEmpty = cells.filter(function (cell) { return cell.aps.length; });
    var emptyLabels = cells.filter(function (cell) { return !cell.aps.length; })
      .map(function (cell) { return segCellLabel(cell.col, cell.row); });

    var out = '<div class="rep-seg-note">Floor plan split into ' + nonEmpty.length + ' section' + (nonEmpty.length === 1 ? '' : 's')
      + ' (' + cols + '&times;' + rows + ' grid) so AP labels stay legible.'
      + (emptyLabels.length ? ' No APs in section' + (emptyLabels.length === 1 ? '' : 's') + ' ' + emptyLabels.join(', ') + ' — skipped.' : '')
      + '</div>';
    out += renderAntennaGridIndex(url, W, H, nonEmpty);
    nonEmpty.forEach(function (cell) {
      var label = segCellLabel(cell.col, cell.row);
      var cW = cell.x1 - cell.x0, cH = cell.y1 - cell.y0;
      var markers = buildApLocationMarkers(cell.aps, W, H, opts);
      out += '<div class="rep-overview rep-seg-cell">'
        + '<div class="rep-seg-cell-head">' + renderAntennaLocatorThumb(url, W, H, cell)
        +   '<h3 class="rep-seg-cell-title">Section ' + WD.esc(label)
        +     ' <span class="rep-seg-cell-count">— ' + cell.aps.length + ' AP' + (cell.aps.length === 1 ? '' : 's') + '</span></h3>'
        + '</div>'
        + '<div class="rep-overview-plan" data-seg="1" data-orig-w="' + W + '" data-orig-h="' + H
        +   '" data-seg-x0="' + cell.x0 + '" data-seg-y0="' + cell.y0 + '" data-seg-x1="' + cell.x1 + '" data-seg-y1="' + cell.y1
        +   '" style="--w:' + cW + ';--h:' + cH + '">'
        +   '<img src="' + url + '" alt="Floor plan section ' + WD.escAttr(label) + '">'
        +   '<svg viewBox="' + cell.x0 + ' ' + cell.y0 + ' ' + cW + ' ' + cH + '" preserveAspectRatio="none">' + markers + '</svg>'
        + '</div>'
        + '</div>';
    });
    return out;
  }

  function renderApLocationTable(aps, fp, opts, ctx) {
    var rows = '';
    aps.forEach(function (ap) {
      var lbl = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      var floorName = fp ? (fp.name || '—') : '—';
      var bf = fp && proj.buildingFloors[fp.id];
      var buildingName = bf && proj.buildings[bf.buildingId]
        ? proj.buildings[bf.buildingId].name || '—' : '—';
      var r = ctx.primaryRadio(ap.id);
      var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
      var nameIssue = '';
      if (opts.nameAudit) {
        if (!ap.name || !ap.name.trim()) nameIssue = 'Missing name';
        else if (/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(ap.name.trim())) nameIssue = 'MAC address as name';
        else if (/^AP\s*\d*$/i.test(ap.name.trim())) nameIssue = 'Generic name';
      }
      rows += '<tr' + (nameIssue ? ' class="rep-loc-warn-row"' : '') + '>'
        + '<td class="rep-num">' + WD.esc(lbl) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.name || '(unnamed)') + '</td>'
        + '<td>' + WD.esc(ap.vendor || '—') + '</td>'
        + '<td>' + WD.esc(ap.model || '—') + '</td>'
        + '<td>' + WD.esc(floorName) + '</td>'
        + '<td>' + WD.esc(buildingName) + '</td>'
        + (opts.nameAudit ? '<td class="rep-loc-warn">' + WD.esc(nameIssue) + '</td>' : '')
        + '</tr>';
    });

    return '<table class="rep-ap-table rep-loc-table">'
      + '<thead><tr>'
      + '<th class="rep-num">#</th><th>AP name</th><th>Vendor</th><th>Model</th>'
      + '<th>Floor</th><th>Building</th>'
      + (opts.nameAudit ? '<th>Naming issue</th>' : '')
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  function renderApNameAudit(aps, ctx) {
    var issues = [];
    aps.forEach(function (ap) {
      var name = (ap.name || '').trim();
      var issue = '';
      if (!name) issue = 'Missing name';
      else if (/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(name)) issue = 'MAC address as name';
      else if (/^AP\s*\d*$/i.test(name)) issue = 'Generic name (e.g. "AP1")';
      if (issue) {
        var fp = ctx.floorPlanForAp(ap);
        issues.push({ name: name || '(unnamed)', issue: issue, floor: fp ? fp.name : '—' });
      }
    });
    if (!issues.length) {
      return '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Naming audit</h2>'
        + '<div class="rep-seg-note" style="color:var(--green)">All ' + aps.length + ' APs have proper names — no issues detected.</div>'
        + '</section>';
    }
    var rows = issues.map(function (i) {
      return '<tr><td class="rep-name">' + WD.esc(i.name) + '</td>'
        + '<td>' + WD.esc(i.floor) + '</td>'
        + '<td class="rep-loc-warn">' + WD.esc(i.issue) + '</td></tr>';
    }).join('');
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Naming audit</h2>'
      + '<div class="rep-seg-note">' + issues.length + ' AP' + (issues.length === 1 ? '' : 's') + ' with naming issues found.</div>'
      + '<table class="rep-ap-table"><thead><tr><th>AP name</th><th>Floor</th><th>Issue</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>'
      + '</section>';
  }

  var PREVIEW_LOCATION = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#2563eb" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#2563eb"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="72" height="38" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<g fill="#2563eb">'
    +     '<rect x="17" y="40" width="10" height="5" rx="1.5"/>'
    +     '<rect x="33" y="36" width="8" height="5" rx="1.5"/>'
    +     '<rect x="47" y="44" width="12" height="5" rx="1.5"/>'
    +     '<rect x="63" y="38" width="9" height="5" rx="1.5"/>'
    +     '<rect x="25" y="54" width="11" height="5" rx="1.5"/>'
    +     '<rect x="50" y="56" width="10" height="5" rx="1.5"/>'
    +   '</g>'
    +   '<g fill="#fff" font-size="3.5" text-anchor="middle" font-weight="700">'
    +     '<text x="22" y="44.5">42</text><text x="37" y="40.5">07</text>'
    +     '<text x="53" y="48.5">128</text><text x="67.5" y="42.5">15</text>'
    +     '<text x="30.5" y="58.5">03</text><text x="55" y="60.5">91</text>'
    +   '</g>'
    +   '<rect x="10" y="74" width="72" height="3" rx="0.5" fill="#2563eb" opacity="0.55"/>'
    +   '<rect x="10" y="80" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="80" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="80" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="84" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="84" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="84" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="88" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="88" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="88" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="92" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="92" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="92" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="100" width="72" height="6" rx="1" fill="#eef7ee" stroke="#22c55e" stroke-width="0.3"/>'
    +   '<text x="46" y="104.5" text-anchor="middle" font-size="3" fill="#16a34a">All names OK</text>'
    + '</svg>';

  var PREVIEW_ANTENNA = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0668D9" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0668D9"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="24" width="55" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="34" width="72" height="34" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<g fill="#0668D9">'
    +     '<circle cx="20" cy="46" r="1.5"/><circle cx="34" cy="42" r="1.5"/>'
    +     '<circle cx="46" cy="50" r="1.5"/><circle cx="60" cy="46" r="1.5"/>'
    +     '<circle cx="72" cy="52" r="1.5"/><circle cx="28" cy="60" r="1.5"/>'
    +     '<circle cx="52" cy="62" r="1.5"/>'
    +   '</g>'
    +   '<path d="M46 50 L48 46 L50 50 Z" fill="#d97706"/>'
    +   '<rect x="10" y="74" width="72" height="3" rx="0.5" fill="#0668D9" opacity="0.55"/>'
    +   '<rect x="10" y="80" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="80" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="84" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="84" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="88" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="47" y="88" width="35" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="98" width="72" height="6" rx="1" fill="#eef2f7"/>'
    + '</svg>';

  var PREVIEW_SUMMARY = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0d9488" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0d9488"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<rect x="30" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<rect x="50" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<text x="18.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">42</text>'
    +   '<text x="18.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">APs</text>'
    +   '<text x="38.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">4</text>'
    +   '<text x="38.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">Floors</text>'
    +   '<text x="58.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">96</text>'
    +   '<text x="58.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">Radios</text>'
    +   '<rect x="10" y="50" width="30" height="1.8" rx="0.4" fill="#c8d4e0"/>'
    +   '<rect x="10" y="55" width="10" height="2.5" rx="0.4" fill="#0d9488"/>'
    +   '<rect x="22" y="55" width="60" height="2.5" rx="0.4" fill="#e0efee"/>'
    +   '<rect x="22" y="55" width="42" height="2.5" rx="0.4" fill="#0d9488" opacity="0.6"/>'
    +   '<rect x="10" y="60" width="10" height="2.5" rx="0.4" fill="#5fab4f"/>'
    +   '<rect x="22" y="60" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="22" y="60" width="52" height="2.5" rx="0.4" fill="#5fab4f" opacity="0.6"/>'
    +   '<rect x="10" y="65" width="10" height="2.5" rx="0.4" fill="#8b5cf6"/>'
    +   '<rect x="22" y="65" width="60" height="2.5" rx="0.4" fill="#eee7f9"/>'
    +   '<rect x="22" y="65" width="18" height="2.5" rx="0.4" fill="#8b5cf6" opacity="0.6"/>'
    +   '<rect x="10" y="75" width="34" height="1.8" rx="0.4" fill="#c8d4e0"/>'
    +   '<rect x="10" y="82" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="86" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="90" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="94" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef7f6"/>'
    + '</svg>';

  var PREVIEW_BOM = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#d97706" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#d97706"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="2.5" rx="0.3" fill="#fce9c8" stroke="#f0b85f" stroke-width="0.3"/>'
    +   '<text x="12" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">VENDOR</text>'
    +   '<text x="36" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">MODEL</text>'
    +   '<text x="72" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">QTY</text>'
    +   '<rect x="10" y="34" width="72" height="4" fill="#ffffff" stroke="#eee" stroke-width="0.2"/>'
    +   '<text x="12" y="36.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="36.8" font-size="1.9" fill="#333">C9166I-E</text>'
    +   '<text x="76" y="36.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">24</text>'
    +   '<rect x="10" y="38" width="72" height="4" fill="#fafafa"/>'
    +   '<text x="12" y="40.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="40.8" font-size="1.9" fill="#333">C9164I</text>'
    +   '<text x="76" y="40.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">12</text>'
    +   '<rect x="10" y="42" width="72" height="4" fill="#ffffff"/>'
    +   '<text x="12" y="44.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="44.8" font-size="1.9" fill="#333">C9130AXE</text>'
    +   '<text x="76" y="44.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">6</text>'
    +   '<rect x="10" y="47" width="72" height="0.5" fill="#d97706"/>'
    +   '<text x="12" y="50" font-size="2" font-weight="700" fill="#111">TOTAL ACCESS POINTS</text>'
    +   '<text x="76" y="50" font-size="2.4" font-weight="800" fill="#d97706" text-anchor="end">42</text>'
    +   '<rect x="10" y="58" width="72" height="2.5" rx="0.3" fill="#fce9c8" stroke="#f0b85f" stroke-width="0.3"/>'
    +   '<text x="12" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">ANTENNA</text>'
    +   '<text x="52" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">BAND</text>'
    +   '<text x="72" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">QTY</text>'
    +   '<rect x="10" y="63" width="72" height="4" fill="#ffffff"/>'
    +   '<text x="12" y="65.8" font-size="1.9" fill="#333">AIR-ANT2513P4M</text>'
    +   '<text x="52" y="65.8" font-size="1.9" fill="#333">2.4 GHz</text>'
    +   '<text x="76" y="65.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">18</text>'
    +   '<rect x="10" y="67" width="72" height="4" fill="#fafafa"/>'
    +   '<text x="12" y="69.8" font-size="1.9" fill="#333">AIR-ANT2568VG-N</text>'
    +   '<text x="52" y="69.8" font-size="1.9" fill="#333">5 GHz</text>'
    +   '<text x="76" y="69.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">18</text>'
    +   '<rect x="10" y="76" width="45" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="82" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="86" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="90" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#fce9c8"/>'
    + '</svg>';

  var PREVIEW_AIM = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#8b5cf6" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#8b5cf6"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="3" rx="0.3" fill="#efe6fd" stroke="#c9b3ee" stroke-width="0.3"/>'
    +   '<text x="12" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">AP</text>'
    +   '<text x="27" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">FLOOR</text>'
    +   '<text x="46" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">AZ°</text>'
    +   '<text x="58" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">TILT</text>'
    +   '<text x="70" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">HT</text>'
    +   '<rect x="10" y="33" width="72" height="3" fill="#ffffff"/>'
    +   '<text x="12" y="35.5" font-size="1.8" fill="#333">AP-01</text>'
    +   '<text x="27" y="35.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="35.5" font-size="1.8" fill="#333">137° SE</text>'
    +   '<text x="58" y="35.5" font-size="1.8" fill="#333">10°</text>'
    +   '<text x="70" y="35.5" font-size="1.8" fill="#333">3.0 m</text>'
    +   '<rect x="10" y="36" width="72" height="3" fill="#faf7fe"/>'
    +   '<text x="12" y="38.5" font-size="1.8" fill="#333">AP-02</text>'
    +   '<text x="27" y="38.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="38.5" font-size="1.8" fill="#333">225° SW</text>'
    +   '<text x="58" y="38.5" font-size="1.8" fill="#333">5°</text>'
    +   '<text x="70" y="38.5" font-size="1.8" fill="#333">2.8 m</text>'
    +   '<rect x="10" y="39" width="72" height="3" fill="#ffffff"/>'
    +   '<text x="12" y="41.5" font-size="1.8" fill="#333">AP-03</text>'
    +   '<text x="27" y="41.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="41.5" font-size="1.8" fill="#333">315° NW</text>'
    +   '<text x="58" y="41.5" font-size="1.8" fill="#333">0°</text>'
    +   '<text x="70" y="41.5" font-size="1.8" fill="#333">3.2 m</text>'
    +   '<rect x="10" y="42" width="72" height="3" fill="#faf7fe"/>'
    +   '<text x="12" y="44.5" font-size="1.8" fill="#333">AP-04</text>'
    +   '<text x="27" y="44.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="44.5" font-size="1.8" fill="#333">045° NE</text>'
    +   '<text x="58" y="44.5" font-size="1.8" fill="#333">10°</text>'
    +   '<text x="70" y="44.5" font-size="1.8" fill="#333">3.0 m</text>'
    +   '<rect x="10" y="48" width="72" height="12" fill="#f8f4ff" stroke="#c9b3ee" stroke-width="0.3"/>'
    +   '<circle cx="20" cy="54" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 20 54 L 25 51" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="35" cy="55" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 35 55 L 32 59" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="52" cy="53" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 52 53 L 56 50" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="68" cy="56" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 68 56 L 63 54" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<rect x="10" y="66" width="72" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="70" width="55" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="74" width="72" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="78" width="60" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#efe6fd"/>'
    + '</svg>';

  var PREVIEW_AUDIT = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#5fab4f" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#5fab4f"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="26" width="34" height="6" rx="0.6" fill="#eef6ec" stroke="#5fab4f" stroke-width="0.3"/>'
    +   '<text x="27" y="30" text-anchor="middle" font-size="2.2" font-weight="700" fill="#5fab4f">BEFORE</text>'
    +   '<rect x="48" y="26" width="34" height="6" rx="0.6" fill="#fef3e3" stroke="#d97706" stroke-width="0.3"/>'
    +   '<text x="65" y="30" text-anchor="middle" font-size="2.2" font-weight="700" fill="#d97706">AFTER</text>'
    +   '<rect x="10" y="34" width="72" height="2.5" fill="#eef6ec"/>'
    +   '<text x="12" y="36.2" font-size="1.7" fill="#333">🟢 42 APs</text>'
    +   '<text x="50" y="36.2" font-size="1.7" fill="#333">🟠 44 APs (+2)</text>'
    +   '<rect x="10" y="37" width="72" height="2.5" fill="#fdf9f4"/>'
    +   '<text x="12" y="39.2" font-size="1.7" fill="#333">🟢 96 radios</text>'
    +   '<text x="50" y="39.2" font-size="1.7" fill="#333">🟠 104 radios (+8)</text>'
    +   '<rect x="10" y="40" width="72" height="2.5" fill="#eef6ec"/>'
    +   '<text x="12" y="42.2" font-size="1.7" fill="#333">🟢 4 floors</text>'
    +   '<text x="50" y="42.2" font-size="1.7" fill="#333">🟠 4 floors</text>'
    +   '<rect x="10" y="46" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="50" width="14" height="2.5" rx="0.6" fill="#5fab4f"/>'
    +   '<text x="27" y="52.2" font-size="1.5" fill="#333">Removed 2 APs on Floor 1</text>'
    +   '<rect x="10" y="54" width="14" height="2.5" rx="0.6" fill="#d97706"/>'
    +   '<text x="27" y="56.2" font-size="1.5" fill="#333">Added 4 APs on Floor 3</text>'
    +   '<rect x="10" y="58" width="14" height="2.5" rx="0.6" fill="#1e77ac"/>'
    +   '<text x="27" y="60.2" font-size="1.5" fill="#333">Moved AP-07 (2.1m → 3.2m)</text>'
    +   '<rect x="10" y="62" width="14" height="2.5" rx="0.6" fill="#1e77ac"/>'
    +   '<text x="27" y="64.2" font-size="1.5" fill="#333">Re-aimed AP-12 (90° → 135°)</text>'
    +   '<rect x="10" y="70" width="72" height="16" fill="#f5faf3" stroke="#c9e0c3" stroke-width="0.3"/>'
    +   '<line x1="46" y1="70" x2="46" y2="86" stroke="#c9e0c3" stroke-width="0.3"/>'
    +   '<circle cx="20" cy="76" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="35" cy="80" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="30" cy="83" r="1.4" fill="#dc2626" opacity="0.6"/>'
    +   '<circle cx="55" cy="76" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="70" cy="80" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="60" cy="82" r="1.4" fill="#d97706"/>'
    +   '<circle cx="75" cy="84" r="1.4" fill="#d97706"/>'
    +   '<rect x="10" y="90" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="94" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="98" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef6ec"/>'
    + '</svg>';

  var PREVIEW_COVERAGE = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0d9488" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0d9488"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="52" rx="1" fill="#fafbfc" stroke="#c5d5e5" stroke-width="0.3"/>'
    +   '<circle cx="24" cy="42" r="9" fill="#0d9488" opacity="0.18"/>'
    +   '<circle cx="24" cy="42" r="6" fill="#0d9488" opacity="0.28"/>'
    +   '<circle cx="24" cy="42" r="3" fill="#0d9488" opacity="0.4"/>'
    +   '<circle cx="24" cy="42" r="1.4" fill="#0d9488"/>'
    +   '<circle cx="46" cy="52" r="10" fill="#8b5cf6" opacity="0.18"/>'
    +   '<circle cx="46" cy="52" r="7" fill="#8b5cf6" opacity="0.28"/>'
    +   '<circle cx="46" cy="52" r="3.5" fill="#8b5cf6" opacity="0.4"/>'
    +   '<circle cx="46" cy="52" r="1.4" fill="#8b5cf6"/>'
    +   '<circle cx="68" cy="44" r="9" fill="#0668D9" opacity="0.18"/>'
    +   '<circle cx="68" cy="44" r="6" fill="#0668D9" opacity="0.28"/>'
    +   '<circle cx="68" cy="44" r="3" fill="#0668D9" opacity="0.4"/>'
    +   '<circle cx="68" cy="44" r="1.4" fill="#0668D9"/>'
    +   '<circle cx="30" cy="66" r="9" fill="#d97706" opacity="0.18"/>'
    +   '<circle cx="30" cy="66" r="6" fill="#d97706" opacity="0.28"/>'
    +   '<circle cx="30" cy="66" r="3" fill="#d97706" opacity="0.4"/>'
    +   '<circle cx="30" cy="66" r="1.4" fill="#d97706"/>'
    +   '<circle cx="60" cy="70" r="9" fill="#5fab4f" opacity="0.18"/>'
    +   '<circle cx="60" cy="70" r="6" fill="#5fab4f" opacity="0.28"/>'
    +   '<circle cx="60" cy="70" r="3" fill="#5fab4f" opacity="0.4"/>'
    +   '<circle cx="60" cy="70" r="1.4" fill="#5fab4f"/>'
    +   '<rect x="10" y="84" width="72" height="8" rx="0.6" fill="#f5fbf9" stroke="#c0e0dc" stroke-width="0.3"/>'
    +   '<text x="12" y="87.5" font-size="1.8" font-weight="700" fill="#0d9488">LEGEND</text>'
    +   '<circle cx="18" cy="90" r="1.2" fill="#0d9488"/>'
    +   '<text x="21" y="90.5" font-size="1.5" fill="#333">Strong</text>'
    +   '<circle cx="35" cy="90" r="1.2" fill="#0668D9" opacity="0.4"/>'
    +   '<text x="38" y="90.5" font-size="1.5" fill="#333">Good</text>'
    +   '<circle cx="50" cy="90" r="1.2" fill="#d97706" opacity="0.28"/>'
    +   '<text x="53" y="90.5" font-size="1.5" fill="#333">Fair</text>'
    +   '<circle cx="65" cy="90" r="1.2" fill="#dc2626" opacity="0.18"/>'
    +   '<text x="68" y="90.5" font-size="1.5" fill="#333">Weak</text>'
    +   '<rect x="10" y="96" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="100" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#f5fbf9"/>'
    + '</svg>';

  var PREVIEW_HOTSPOT = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#1e77ac" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#1e77ac"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="72" height="36" rx="2" fill="#eef4fb" stroke="#c5d5e5" stroke-width="0.5"/>'
    +   '<path d="M 18 60 L 22 54 L 30 50 L 38 46 L 46 42 L 54 44 L 62 48 L 70 46 L 76 42 L 74 36 L 68 34"'
    +     ' fill="none" stroke="#1e77ac" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.75"/>'
    +   '<circle cx="22" cy="54" r="1.6" fill="#5d5b60"/>'
    +   '<circle cx="38" cy="46" r="1.6" fill="#5fab4f"/>'
    +   '<circle cx="54" cy="44" r="1.6" fill="#d97706"/>'
    +   '<circle cx="70" cy="46" r="1.6" fill="#dc2626"/>'
    +   '<circle cx="30" cy="50" r="1.6" fill="#5fab4f"/>'
    +   '<rect x="10" y="72" width="10" height="2.5" rx="1" fill="#5d5b60"/>'
    +   '<rect x="22" y="72" width="60" height="2.5" rx="0.4" fill="#eef2f5"/>'
    +   '<rect x="10" y="77" width="10" height="2.5" rx="1" fill="#5fab4f"/>'
    +   '<rect x="22" y="77" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="10" y="82" width="10" height="2.5" rx="1" fill="#d97706"/>'
    +   '<rect x="22" y="82" width="60" height="2.5" rx="0.4" fill="#fef3e3"/>'
    +   '<rect x="10" y="87" width="10" height="2.5" rx="1" fill="#dc2626"/>'
    +   '<rect x="22" y="87" width="60" height="2.5" rx="0.4" fill="#fef2f2"/>'
    +   '<rect x="10" y="92" width="10" height="2.5" rx="1" fill="#5fab4f"/>'
    +   '<rect x="22" y="92" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="10" y="97" width="10" height="2.5" rx="1" fill="#d97706"/>'
    +   '<rect x="22" y="97" width="60" height="2.5" rx="0.4" fill="#fef3e3"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef4fb"/>'
    + '</svg>';

  var PREVIEW_PREDICTIVE = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#9F1B58" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#9F1B58"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="70" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<line x1="46" y1="28" x2="46" y2="98" stroke="#d5dee7" stroke-width="0.5" stroke-dasharray="1.5,1.5"/>'
    +   '<line x1="10" y1="63" x2="82" y2="63" stroke="#d5dee7" stroke-width="0.5" stroke-dasharray="1.5,1.5"/>'
    +   '<text x="14" y="34" font-size="3" font-weight="700" fill="#9F1B58">A1</text>'
    +   '<text x="76" y="34" font-size="3" font-weight="700" fill="#9F1B58" text-anchor="end">B1</text>'
    +   '<text x="14" y="94" font-size="3" font-weight="700" fill="#9F1B58">A2</text>'
    +   '<text x="76" y="94" font-size="3" font-weight="700" fill="#9F1B58" text-anchor="end">B2</text>'
    +   '<g fill="#9F1B58">'
    +     '<circle cx="22" cy="42" r="1.8"/><circle cx="38" cy="48" r="1.8"/>'
    +     '<circle cx="58" cy="40" r="1.8"/><circle cx="72" cy="50" r="1.8"/>'
    +     '<circle cx="24" cy="76" r="1.8"/><circle cx="44" cy="82" r="1.8"/>'
    +     '<circle cx="64" cy="78" r="1.8"/>'
    +   '</g>'
    +   '<path d="M58 40 L60.5 34.5 L63 40 Z" fill="#d97706"/>'
    +   '<path d="M22 42 L24.5 36.5 L27 42 Z" fill="#d97706"/>'
    +   '<rect x="10" y="104" width="72" height="6" rx="1" fill="#f7e7ee"/>'
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
        { id: 'shortLabels',     label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers and in the # column. Turn off to always show the full AP name — safer when APs are named by MAC or free-form text.' },
        { id: 'segmented', label: 'Split large floor plans into zoomed sections', default: false,
          description: 'For very large buildings, break each floor plan overview into a grid of zoomed-in, lettered/numbered sections (with a locator map) so AP markers stay readable. Sections with no APs are skipped.' },
        { id: '_gridConfig', type: 'grid-button', label: 'Configure grid…',
          description: 'Choose how many rows and columns the segmented grid uses, with a live preview on your actual floor plan.' },
      ],
      render: renderAntennaReport,
      postRender: applyAntennaSegmentCrop,
    },
    predictive: {
      id: 'predictive',
      label: 'Predictive Design / AP Placement',
      description: 'Floor plan(s) with proposed AP placement, split into zoomed sections on large floors. No mount/azimuth/tilt detail — placement only.',
      docName: 'Predictive Design',
      coverBrand: 'Report · Predictive Design',
      status: 'ready',
      preview: PREVIEW_PREDICTIVE,
      bestFor: 'Handing exact AP placement to low-voltage installers before construction, and design sign-off before a build.',
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, AP + floor-plan counts, your logo, date.' },
        { icon: '📊', title: 'Summary strip',
          description: 'Quick AP / floor-plan / directional-omni counts before the visuals.' },
        { icon: '🗺️', title: 'Floor plan overview per floor',
          description: 'Every AP plotted on each floor plan with SVG direction arrows. Large floors split into zoomed, lettered/numbered sections (with a locator map) so placement stays exact.' },
      ],
      sidebar: [
        { id: 'summary',   label: 'Summary strip', default: true,
          description: 'AP count, floor-plan count, and directional/omni split above the floor plans.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Standard case — APs whose antennas have a specific azimuth.' },
        { id: 'inclOmni',        label: 'Include omni APs', default: true,
          description: 'This report covers the whole placement plan, not just aiming — omni APs are on by default so nothing is missing from the crew\'s copy.' },
        { id: 'shortLabels',     label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers. Turn off to always show the full AP name — safer when APs are named by MAC or free-form text.' },
        { id: 'segmented', label: 'Split large floor plans into zoomed sections', default: true,
          description: 'Breaks each floor plan into a grid of zoomed-in, lettered/numbered sections (with a locator map) so AP markers stay pinpoint-legible. On by default here since exact placement is the point of this report — turn off to force one full-page image per floor regardless of size.' },
        { id: '_gridConfig', type: 'grid-button', label: 'Configure grid…',
          description: 'Choose how many rows and columns the segmented grid uses, with a live preview on your actual floor plan.' },
      ],
      render: renderPredictiveReport,
      postRender: applyAntennaSegmentCrop,
    },
    summary: {
      id: 'summary',
      label: 'Site Summary Sheet',
      description: 'One-page executive overview of the project: APs, floors, buildings, radios, top models, antennas.',
      docName: 'Site Summary',
      coverBrand: 'Report · Site Summary',
      status: 'ready',
      preview: PREVIEW_SUMMARY,
      bestFor: 'Client-facing project overview, kickoff decks, quick site-scoping snapshot.',
      noApFilter: true,
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, total AP count, floor count, your logo, date.' },
        { icon: '📊', title: 'Project at a glance',
          description: 'APs, radios, floor plans, buildings, antenna types, survey/measurement counts.' },
        { icon: '🏢', title: 'Per-floor breakdown',
          description: 'AP count and canvas dimensions per floor, grouped by building when available.' },
        { icon: '📶', title: 'Radio band breakdown',
          description: 'Horizontal bar chart showing the 2.4 / 5 / 6 GHz radio split across the whole project.' },
        { icon: '🔝', title: 'Top AP models',
          description: 'Up to 10 most-used AP models with quantities — quick check of hardware mix.' },
        { icon: '📡', title: 'Antennas in use',
          description: 'Every antenna model referenced with band, coupling, gain, and beam width.' },
      ],
      sidebar: [
        { id: 'perFloor',      label: 'Per-floor breakdown table', default: true,
          description: 'Table listing each floor plan with its AP count and canvas dimensions.' },
        { id: 'bandBreakdown', label: 'Radio band breakdown', default: true,
          description: 'Bar chart of 2.4/5/6 GHz radio distribution.' },
        { id: 'topModels',     label: 'Top AP models', default: true,
          description: 'Ranked list of AP models by quantity.' },
        { id: 'antennas',      label: 'Antennas in use', default: true,
          description: 'Legend section describing every antenna model in this project.' },
      ],
      render: renderSummaryReport,
    },
    interference: {
      id: 'interference',
      label: 'Interference / Rogue Devices',
      description: 'Phone hotspots, MiFi, and wide-channel rogue Wi-Fi picked up in the passive survey, scored by severity.',
      docName: 'Interference',
      coverBrand: 'Report · Interference',
      status: 'ready',
      preview: PREVIEW_HOTSPOT,
      bestFor: 'Security walk-arounds, "someone\'s wide-channel hotspot is stomping the network" incidents, baseline handoffs.',
      noApFilter: true,
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, interferer count, your logo, survey date.' },
        { icon: '📊', title: 'Summary strip',
          description: 'Total, high-severity count, and per-category counts (iPhone / Android / Carrier / Wide-channel).' },
        { icon: '🗺️', title: 'Per-floor detection map',
          description: 'Floor plan with the surveyor walk path drawn on top, colored by the worst severity detected on that floor.' },
        { icon: '📋', title: 'Full device table',
          description: 'SSID, BSSID, band, channel width, severity, security, and which floors each device was seen on.' },
        { icon: '📖', title: 'Methodology',
          description: 'How each SSID was classified, how severity is scored, and what was intentionally excluded.' },
      ],
      sidebar: [
        { id: 'catIphone',  label: 'Include iPhone / iPad', default: true,
          description: 'SSIDs matching "iPhone", "iPad", or "’s iPhone" (iOS Personal Hotspot defaults).' },
        { id: 'catAndroid', label: 'Include Android', default: true,
          description: 'AndroidAP_XXXX, AndroidShare_XXXX, DIRECT-xx-AndroidAP, Samsung Galaxy device names.' },
        { id: 'catCarrier', label: 'Include Carrier / MiFi hotspots', default: true,
          description: 'HotspotXXXX, WiFi Hotspot NNNN, MiFi / Jetpack (Verizon and T-Mobile hotspot defaults).' },
        { id: 'catAtt',     label: 'Include AT&T (phone or gateway)', default: false,
          description: 'ATT[6-10 char] pattern — used by BOTH AT&T phone hotspots and AT&T home gateways, so off by default.' },
        { id: 'catWide',    label: 'Include wide-channel Wi-Fi (any SSID)', default: true,
          description: 'Any BSSID on a 40MHz+ channel, even if its SSID doesn\'t match a phone-naming pattern. This is what catches "someone plugged in a wide-channel rogue AP or hotspot."' },
        { id: 'overview',   label: 'Include per-floor detection map', default: true,
          description: 'Floor plan with the surveyor walk path drawn on top, colored by severity, one panel per floor.' },
        { id: 'autocrop',   label: 'Auto-crop empty margins around each floor plan', default: true,
          description: 'Ekahau sometimes saves a floor plan on an oversized canvas with lots of whitespace. When on, each overlay zooms to the actual drawn content (plus the walk path, so nothing is cut off).' },
        { id: 'channel',    label: 'Show channel numbers', default: false,
          description: 'Adds a Channel(s) column to the device table. Off by default — most readers just need the band and width.' },
      ],
      render: renderInterferenceReport,
      postRender: applyHotspotAutocrop,
    },
    bom: {
      id: 'bom',
      label: 'Bill of Materials',
      description: 'AP + antenna quantities for procurement handoff.',
      docName: 'Bill of Materials',
      coverBrand: 'Report · Bill of Materials',
      status: 'ready',
      preview: PREVIEW_BOM,
      bestFor: 'Procurement teams sizing purchase orders and cost estimates.',
      noApFilter: true,
      sections: [
        { icon: '📦', title: 'AP quantities',
          description: 'Grouped by vendor and model, with subtotals and a grand total.' },
        { icon: '📡', title: 'Antenna quantities',
          description: 'Grouped by antenna model, with band, coupling type (integrated/external), and gain.' },
        { icon: '📝', title: 'Procurement notes',
          description: 'What this BOM does and does not cover — mount hardware, cable runs, PoE injectors need manual work.' },
      ],
      sidebar: [
        { id: 'externalOnly', label: 'Show external antennas only', default: false,
          description: 'Filter to procurement-relevant antennas — hides built-in antennas that ship with the AP. Handy for orders like "AP + external antenna kit".' },
      ],
      render: renderBomReport,
    },
    aim: {
      id: 'aim',
      label: 'Antenna Aim Sheet',
      description: 'One flat table: every AP with azimuth, tilt, mount height, and floor — for a clipboard, not a binder.',
      docName: 'Antenna Aim Sheet',
      coverBrand: 'Report · Antenna Aim',
      status: 'ready',
      preview: PREVIEW_AIM,
      bestFor: 'On-site installers who want one printed page they can carry between mount locations.',
      sections: [
        { icon: '📋', title: 'Single-page table',
          description: 'Every directional AP as one row: AP name, floor, azimuth (with compass), tilt, mount height (meters + feet), antenna model.' },
        { icon: '🎯', title: 'Per-floor mini-map',
          description: 'Below the table, a compact floor plan per floor with AP dots and short direction ticks — a quick sanity check before climbing a ladder.' },
        { icon: '✅', title: 'Sign-off row',
          description: 'Installer initials + date column on the right side of each row, so the printed sheet doubles as an as-built.' },
      ],
      sidebar: [
        { id: 'overview', label: 'Per-floor mini-maps', default: true,
          description: 'Compact floor plan per floor below the table, with AP dots and direction ticks — sanity check before climbing a ladder.' },
        { id: 'signOff',  label: 'Sign-off columns (initials + date)', default: true,
          description: 'Right side of each row keeps two blank cells so the printed sheet doubles as an as-built.' },
        { id: 'imperial', label: 'Show mount heights in both units', default: true,
          description: 'Meters primary, feet in parentheses — e.g. "2.5 m (8\'2\")".' },
        { id: 'compass',  label: 'Show compass headings alongside azimuth', default: true,
          description: 'Azimuth shown as "137° (SE)" instead of just "137°".' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Standard case — APs whose antennas have a specific azimuth.' },
        { id: 'inclOmni',        label: 'Include omni APs', default: false,
          description: 'Adds omni-only APs with an "omni" placeholder in the azimuth cell. Off by default — this sheet is for aiming.' },
        { id: 'shortLabels',     label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers and in the # column. Turn off to always show the full AP name — safer when APs are named by MAC or free-form text.' },
      ],
      render: renderAimReport,
    },
    audit: {
      id: 'audit',
      label: 'Change / Audit Report',
      description: 'Diff between two .esx files (or two survey rounds) — what moved, what was added, what was removed.',
      docName: 'Change Report',
      coverBrand: 'Report · Change / Audit',
      status: 'coming-soon',
      preview: PREVIEW_AUDIT,
      bestFor: 'Post-remediation write-ups, redesign hand-offs, and "prove we did what we said" audits.',
      sections: [
        { icon: '🔍', title: 'Compare stats',
          description: 'Before-and-after side-by-side: AP counts, radio counts, floor counts, band mix. Deltas rendered with signed arrows.' },
        { icon: '➕', title: 'Added / removed / moved',
          description: 'One row per change with the AP name, floor, and what changed (position, azimuth, height, model, or presence).' },
        { icon: '🗺️', title: 'Overlay diff',
          description: 'Per-floor overlay showing removed APs faded, unchanged APs green, moved APs with a dotted line to their new position, added APs bright orange.' },
      ],
      sidebar: [],
    },
    coverage: {
      id: 'coverage',
      label: 'Coverage Cell Boundary',
      description: 'Per-floor overlay of each AP\'s coverage cell — where that AP is the primary, second-best, and where the signal gets weak.',
      docName: 'Coverage Cell Boundary',
      coverBrand: 'Report · Coverage Cell',
      status: 'ready',
      preview: PREVIEW_COVERAGE,
      bestFor: 'Client presentations, capacity conversations, "why do we need N APs on this floor" justifications.',
      sections: [
        { icon: '🗺️', title: 'Cell diagram per floor',
          description: 'Each AP gets a translucent circle sized by its estimated primary-service radius (−67 dBm). Overlapping cells show handoff zones.' },
        { icon: '📶', title: 'Signal strength bands',
          description: 'Optional concentric rings per AP: strong (< −55 dBm) / fair (< −75) / weak (< −80). Weak-signal gaps highlighted.' },
        { icon: '📊', title: 'Cell sizing table + methodology',
          description: 'Per-AP TX power, antenna gain, EIRP, and −67 / −80 dBm radii. Plus a plain-English methodology section covering the path-loss model and its limits.' },
      ],
      sidebar: [
        { id: 'primaryCells', label: 'Primary coverage cell (−67 dBm)', default: true,
          description: 'Filled translucent circle around each AP at the standard "reliable voice/video" threshold. Overlaps show handoff zones.' },
        { id: 'signalRings', label: 'Signal-strength rings', default: false,
          description: 'Adds outlined concentric rings at strong / fair / weak thresholds. Off by default because it gets busy fast on dense floors.' },
        { id: 'bandColors', label: 'Color-code by band', default: true,
          description: '2.4 GHz blue · 5 GHz green · 6 GHz purple. Off means everything uses the same neutral blue.' },
        { id: 'showApLabels', label: 'AP number labels', default: true,
          description: 'Numbered dot at each AP center — matches the row number in the "Cell sizing per AP" table.' },
        { id: 'legend', label: 'Cell sizing table', default: true,
          description: 'One row per AP with its TX power, antenna gain, EIRP, and computed −67 / −80 dBm radii.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Directional antennas are drawn as circles (radius uses their full EIRP). Angular beam shaping is not modelled — see methodology.' },
        { id: 'inclOmni', label: 'Include omni APs', default: true,
          description: 'Omni APs produce broadly circular cells and are usually the primary content of this report.' },
      ],
      render: renderCoverageReport,
    },
    location: {
      id: 'location',
      label: 'AP Location Map',
      description: 'Floor plan with every AP position labeled, plus a copyable AP name table. Use as a placement reference or naming audit.',
      docName: 'AP Location',
      coverBrand: 'Report · AP Location',
      status: 'ready',
      preview: PREVIEW_LOCATION,
      bestFor: 'Handing legacy AP positions to architects for drafted floor plans, auditing AP naming conventions, and correlating AP names to physical locations.',
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, AP + floor-plan counts, your logo, date.' },
        { icon: '🗺️', title: 'Scalable floor plan per floor',
          description: 'Every AP plotted with a labeled rounded marker. Large floors split into zoomed sections so labels stay legible.' },
        { icon: '📋', title: 'AP name table',
          description: 'Per-floor table of AP names, vendor, model, floor, and building — designed for copy/paste into spreadsheets.' },
        { icon: '🔍', title: 'Naming audit',
          description: 'Highlights APs with missing names, MAC addresses used as names, or generic "AP1"-style names that need renaming.' },
      ],
      sidebar: [
        { id: 'shortLabels', label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers. Turn off to always show the full AP name.' },
        { id: 'nameAudit', label: 'Include naming audit', default: true,
          description: 'Adds a column flagging APs with missing, MAC-address, or generic names. Also adds a summary section at the end.' },
        { id: 'segmented', label: 'Split large floor plans into zoomed sections', default: true,
          description: 'Breaks each floor plan into a grid of zoomed-in sections so AP labels stay readable at any scale.' },
        { id: '_gridConfig', type: 'grid-button', label: 'Configure grid…',
          description: 'Choose how many rows and columns the segmented grid uses, with a live preview on your actual floor plan.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true },
        { id: 'inclOmni', label: 'Include omni APs', default: true,
          description: 'This report is about location, not aiming — omni APs are on by default so every AP shows.' },
      ],
      render: renderApLocationReport,
      postRender: applyAntennaSegmentCrop,
    },
  };

  renderTemplateGallery();
})();
