(function () {
  'use strict';

  var API = WD.api;
  var settings = {};

  window.SP = {};

  function init() {
    API('settings/get', {}).then(function (r) {
      if (!r.ok) return;
      settings = r.settings;
      populate();
      checkCloud();
      openHashSection();
    });
  }

  function openHashSection() {
    var hash = location.hash.replace('#', '');
    if (!hash) return;
    var sec = document.getElementById('sec-' + hash);
    if (sec) sec.open = true;
  }

  function populate() {
    var g = settings.global || {};
    var o = settings.organizer || {};
    var c = settings.cloud || {};

    document.getElementById('sOutputDir').value = g.output_dir || '';
    renderSubfolders(g.subfolders || [], g.subfolder_names || {});
    renderCustomDests(g.custom_destinations || []);

    document.getElementById('sImageExt').value = (o.image_ext || []).join(', ');
    document.getElementById('sPlanExt').value = (o.plan_ext || []).join(', ');
    document.getElementById('sReportExt').value = (o.report_ext || []).join(', ');
    document.getElementById('sPdfKw').value = (o.report_keywords || []).join(', ');
    document.getElementById('sJsonKw').value = (o.json_report_keywords || []).join(', ');
    document.getElementById('sSkipDirs').value = (o.skip_dirs || []).join(', ');
    document.getElementById('sCreateTpl').value = o.create_folder_template || '';

    var rule = c.merge_rule || 'ask';
    var radios = document.querySelectorAll('input[name="mergeRule"]');
    for (var i = 0; i < radios.length; i++) {
      radios[i].checked = radios[i].value === rule;
    }
    document.getElementById('sLiveMs').value = String(c.live_interval_ms || 30000);
  }

  var _subfolders = [];
  var _subfolderNames = {};

  function renderSubfolders(keys, names) {
    if (keys) { _subfolders = keys.slice(); _subfolderNames = Object.assign({}, names); }
    var list = document.getElementById('sSfList');
    var effectiveNames = _subfolders.map(function (k) { return _subfolderNames[k] || k; });
    list.innerHTML = effectiveNames.map(function (name, i) {
      return '<li class="sf-item" data-idx="' + i + '">' +
        '<span class="sf-handle">&#9776;</span>' +
        '<input type="text" value="' + esc(name) + '" onchange="SP._updateSf(' + i + ', this.value)">' +
        (effectiveNames.length > 1 ? '<button class="sf-remove" onclick="SP._removeSf(' + i + ')">&times;</button>' : '') +
        '</li>';
    }).join('');
  }

  SP._updateSf = function (i, val) {
    _subfolderNames[_subfolders[i]] = val.trim() || _subfolders[i];
  };

  SP._removeSf = function (i) {
    var key = _subfolders.splice(i, 1)[0];
    delete _subfolderNames[key];
    renderSubfolders();
  };

  SP.addSubfolder = function () {
    var base = 'subfolder', key = base, n = 1;
    while (_subfolders.indexOf(key) !== -1) { key = base + n; n++; }
    _subfolders.push(key);
    _subfolderNames[key] = '';
    renderSubfolders();
    var items = document.querySelectorAll('#sSfList .sf-item input[type="text"]');
    var last = items[items.length - 1];
    if (last) { last.focus(); last.select(); }
  };

  function renderCustomDests(customs) {
    var host = document.getElementById('sCdList');
    host.innerHTML = '';
    (customs || []).forEach(function (c) { host.appendChild(buildCdRow(c)); });
  }

  function buildCdRow(c) {
    c = c || {};
    var row = document.createElement('div');
    row.className = 's-cd-row';
    row.innerHTML =
      '<div class="s-cd-grid">' +
        '<label>Folder name<input type="text" class="cd-name" value="' + esc(c.name || '') + '"></label>' +
        '<label>Extensions<input type="text" class="cd-exts" value="' + esc((c.exts || []).join(', ')) + '"></label>' +
        '<label>PDF keywords<input type="text" class="cd-pdfkw" value="' + esc((c.pdf_keywords || []).join(', ')) + '"></label>' +
        '<label>JSON keywords<input type="text" class="cd-jsonkw" value="' + esc((c.json_keywords || []).join(', ')) + '"></label>' +
      '</div>' +
      '<button class="s-cd-remove" title="Remove">&times;</button>';
    row.querySelector('.s-cd-remove').addEventListener('click', function () { row.remove(); });
    return row;
  }

  SP.addCustomDest = function () {
    document.getElementById('sCdList').appendChild(buildCdRow({}));
  };

  function collectCustomDests() {
    var rows = document.querySelectorAll('#sCdList .s-cd-row');
    var out = [];
    for (var i = 0; i < rows.length; i++) {
      var name = rows[i].querySelector('.cd-name').value.trim();
      if (!name) continue;
      out.push({
        name: name,
        exts: splitComma(rows[i].querySelector('.cd-exts').value),
        pdf_keywords: splitComma(rows[i].querySelector('.cd-pdfkw').value),
        json_keywords: splitComma(rows[i].querySelector('.cd-jsonkw').value)
      });
    }
    return out;
  }

  function splitComma(s) {
    return (s || '').split(',').map(function (x) { return x.trim(); }).filter(Boolean);
  }

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  SP.pickFolder = function () {
    API('cloud/pick_folder', {}).then(function (r) {
      if (r.path) document.getElementById('sOutputDir').value = r.path;
    });
  };

  SP.clearFolder = function () {
    document.getElementById('sOutputDir').value = '';
  };

  function checkCloud() {
    API('cloud/status', {}).then(function (r) {
      var el = document.getElementById('sCloudStatus');
      var txt = document.getElementById('sCloudStatusText');
      if (r.connected) {
        el.classList.add('connected');
        txt.textContent = 'Connected' + (r.email ? ' as ' + r.email : '');
      } else {
        el.classList.remove('connected');
        txt.textContent = 'Not connected';
      }
    });
  }

  SP.forgetLogin = function () {
    API('cloud/forget_login', {}).then(function () {
      WD.toast('Login forgotten', 'ok');
      checkCloud();
    });
  };

  SP.resetOrganizer = function () {
    if (!confirm('Reset all Squirrel settings to factory defaults?')) return;
    API('settings/get', {}).then(function (r) {
      var defaults = {
        image_ext: [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp", ".heic"],
        plan_ext: [".dwg", ".dxf", ".vsd", ".vsdx", ".pcp"],
        report_ext: [".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".csv", ".pptx", ".ppt", ".html", ".htm", ".txt", ".rtf"],
        report_keywords: ["report", "audit", "coverage", "validation", "bom", "as-built", "asbuilt", "summary"],
        json_report_keywords: ["waxframe", "checkpoint", "assessment", "report"],
        skip_dirs: ["backups", "backup", "output", "outputs", "archive", "archives", ".git", "images", "floorplans", "reports"],
        create_folder_template: "",
        rename: { strip_prefix: "", strip_suffix: "", regex_from: "", regex_to: "", separator: "", case: "", prefix: "", suffix: "" }
      };
      API('settings/update', { patch: { organizer: defaults } }).then(function (r2) {
        if (r2.ok) { settings = r2.settings; populate(); WD.toast('Organizer reset to defaults', 'ok'); }
      });
    });
  };

  SP.rerunSetup = function () {
    API('settings/reset_setup', {}).then(function () {
      window.location.href = '/setup';
    });
  };

  SP.save = function () {
    var cleanNames = {};
    var cleanKeys = _subfolders.filter(function (key) {
      var name = (_subfolderNames[key] || '').trim();
      if (!name) return false;
      cleanNames[key] = name;
      return true;
    });

    var mergeRule = 'ask';
    var radios = document.querySelectorAll('input[name="mergeRule"]');
    for (var i = 0; i < radios.length; i++) {
      if (radios[i].checked) { mergeRule = radios[i].value; break; }
    }

    var patch = {
      global: {
        output_dir: document.getElementById('sOutputDir').value,
        subfolders: cleanKeys,
        subfolder_names: cleanNames,
        custom_destinations: collectCustomDests()
      },
      organizer: {
        image_ext: splitComma(document.getElementById('sImageExt').value),
        plan_ext: splitComma(document.getElementById('sPlanExt').value),
        report_ext: splitComma(document.getElementById('sReportExt').value),
        report_keywords: splitComma(document.getElementById('sPdfKw').value),
        json_report_keywords: splitComma(document.getElementById('sJsonKw').value),
        skip_dirs: splitComma(document.getElementById('sSkipDirs').value),
        create_folder_template: document.getElementById('sCreateTpl').value
      },
      cloud: {
        merge_rule: mergeRule,
        live_interval_ms: parseInt(document.getElementById('sLiveMs').value, 10) || 30000
      }
    };

    API('settings/update', { patch: patch }).then(function (r) {
      if (r.ok) {
        settings = r.settings;
        WD.toast('Settings saved', 'ok');
      } else {
        WD.toast(r.error || 'Save failed', 'error');
      }
    });
  };

  init();
})();
