(function () {
  'use strict';

  var API = WD.api;
  var STEPS = ['welcome', 'folder', 'subfolders', 'cloud'];
  var PROGRESS_STEPS = ['folder', 'subfolders', 'cloud'];

  var state = {
    outputDir: '',
    subfolders: ['images', 'floorplans', 'reports'],
    subfolder_names: { images: 'images', floorplans: 'floorplans', reports: 'reports' },
    cloudConnected: false
  };

  function init() {
    API('settings/get', {}).then(function (r) {
      if (r.settings) {
        var g = r.settings.global || {};
        if (g.output_dir) state.outputDir = g.output_dir;
        if (g.subfolders) state.subfolders = g.subfolders.slice();
        if (g.subfolder_names) state.subfolder_names = Object.assign({}, g.subfolder_names);
      }
      renderSubfolders();
      if (state.outputDir) document.getElementById('setupFolder').value = state.outputDir;
    });
    checkCloudStatus();
  }

  function renderProgress(currentStep) {
    PROGRESS_STEPS.forEach(function (s) {
      var el = document.getElementById('prog-' + s);
      if (!el) return;
      var idx = PROGRESS_STEPS.indexOf(currentStep);
      el.innerHTML = PROGRESS_STEPS.map(function (ps, i) {
        var cls = 'setup-dot';
        if (i < idx) cls += ' done';
        else if (i === idx) cls += ' current';
        return '<span class="' + cls + '"></span>';
      }).join('');
    });
  }

  window.goStep = function (step) {
    STEPS.concat(['done']).forEach(function (s) {
      var el = document.getElementById('step-' + s);
      if (el) el.classList.toggle('active', s === step);
    });
    renderProgress(step);
    if (step === 'subfolders') renderSubfolders();
  };

  window.pickFolder = function () {
    API('cloud/pick_folder', {}).then(function (r) {
      if (r.path) {
        state.outputDir = r.path;
        document.getElementById('setupFolder').value = r.path;
      }
    });
  };

  function renderSubfolders() {
    var list = document.getElementById('sfList');
    var names = effectiveNames();
    list.innerHTML = names.map(function (name, i) {
      return '<li class="sf-item" data-idx="' + i + '">' +
        '<span class="sf-handle" title="Drag to reorder">&#9776;</span>' +
        '<input type="text" value="' + escHtml(name) + '" onchange="updateSubfolder(' + i + ', this.value)">' +
        (names.length > 1 ? '<button class="sf-remove" onclick="removeSubfolder(' + i + ')" title="Remove">&times;</button>' : '') +
        '</li>';
    }).join('');
  }

  function effectiveNames() {
    return state.subfolders.map(function (key) {
      return (state.subfolder_names[key] || key);
    });
  }

  function escHtml(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  window.updateSubfolder = function (idx, val) {
    var key = state.subfolders[idx];
    state.subfolder_names[key] = val.trim() || key;
  };

  window.removeSubfolder = function (idx) {
    var key = state.subfolders.splice(idx, 1)[0];
    delete state.subfolder_names[key];
    renderSubfolders();
  };

  window.addSubfolder = function () {
    var base = 'subfolder';
    var key = base;
    var n = 1;
    while (state.subfolders.indexOf(key) !== -1) { key = base + n; n++; }
    state.subfolders.push(key);
    state.subfolder_names[key] = '';
    renderSubfolders();
    var items = document.querySelectorAll('.sf-item input[type="text"]');
    var last = items[items.length - 1];
    if (last) { last.focus(); last.select(); }
  };

  function checkCloudStatus() {
    API('cloud/status', {}).then(function (r) {
      var el = document.getElementById('cloudStatus');
      var txt = document.getElementById('cloudStatusText');
      if (r.connected) {
        state.cloudConnected = true;
        el.classList.add('connected');
        txt.textContent = 'Connected' + (r.email ? ' as ' + r.email : '');
      } else {
        state.cloudConnected = false;
        el.classList.remove('connected');
        txt.textContent = 'Not connected';
      }
    });
  }

  window.openCloudLogin = function () {
    API('cloud/open_login', {}).then(function () {
      setTimeout(checkCloudStatus, 3000);
    });
  };

  window.finishSetup = function () {
    var cleanNames = {};
    state.subfolders = state.subfolders.filter(function (key) {
      var name = (state.subfolder_names[key] || '').trim();
      if (!name) return false;
      cleanNames[key] = name;
      return true;
    });
    state.subfolder_names = cleanNames;

    var patch = {
      global: {
        output_dir: state.outputDir,
        subfolders: state.subfolders,
        subfolder_names: state.subfolder_names
      }
    };

    API('settings/complete_setup', { patch: patch }).then(function () {
      var summary = '';
      if (state.outputDir) {
        summary += '<strong>Project folder:</strong> ' + escHtml(state.outputDir) + '<br>';
      } else {
        summary += '<strong>Project folder:</strong> Not set (pick one from any tool)<br>';
      }
      summary += '<strong>Subfolders:</strong> ' + effectiveNames().join(', ') + '<br>';
      summary += '<strong>Cloud:</strong> ' + (state.cloudConnected ? 'Connected' : 'Not connected') + '<br>';
      document.getElementById('setupSummary').innerHTML = summary;
      goStep('done');
    });
  };

  init();
})();
