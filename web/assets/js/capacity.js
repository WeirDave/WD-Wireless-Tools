/* WD Capacity — put a device mix into a project, from a template.

 * A template is a list of devices: a device profile, a usage profile, and how
 * many of it each person carries. It is built and edited here, from the
 * profiles Ekahau puts in every project, or made from a project that already
 * has capacity set up. The default template is picked the moment a project
 * opens, so the usual run is open, check, apply.
 *
 *
 * Applying is gated behind the preview above it: the button does exactly what
 * the plan just described, and the file you loaded is never written to. The
 * result comes back as a download, so replacing the original stays a decision
 * the user makes in their file manager rather than one this page makes for them.
 */
(function () {
  'use strict';

  var fileBytes = null;      // the .esx currently loaded, as an ArrayBuffer
  var fileName = '';
  var extracted = null;      // what was read out of the open project
  var templates = [];
  var chosen = null;         // filename of the template selected for apply
  var floorOcc = {};         // floorPlanId -> headcount typed for that floor
  var floorExist = {};       // floorPlanId -> keep / devices / reshape for that floor

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(String(s == null ? '' : s)); }

  function api(action, body, query) {
    return fetch('/api/capacity/' + action + (query || ''), {
      method: 'POST',
      headers: { 'X-WD-Wireless-Tools': '1' },
      body: body,
    }).then(function (r) { return r.json(); });
  }

  function jsonApi(action, payload) {
    return fetch('/api/capacity/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify(payload || {}),
    }).then(function (r) { return r.json(); });
  }

  // ── file in ────────────────────────────────────────────────────────────────
  window.capLoadNewFile = function () { $('fileInput').click(); };

  function shortDevice(name) {
    return String(name || '').replace(/^Generic\s+/i, '');
  }

  function loadFile(file) {
    fileName = file.name;
    floorOcc = {};
    floorExist = {};
    // A new project starts from the saved defaults again.
    $('capExisting').value = savedExisting;
    file.arrayBuffer().then(function (buf) {
      fileBytes = buf;
      $('dropzone').style.display = 'none';
      $('editor').classList.add('active');
      $('fileBadge').textContent = fileName;
      $('fileBadge').title = fileName + '  —  click to open another .esx';
      $('fileBadge').style.display = 'inline-block';
      return api('analyze', buf, '?name=' + encodeURIComponent(fileName));
    }).then(function (r) {
      extracted = r && r.ok ? r : null;
      renderExtract(r);
      /* "once a template is [made] it would automatically load in that
         default template unless you chose or altered otherwise and then they
         could just immediately save". The default is picked and planned the
         moment the project opens, so Apply is ready without a click. */
      return loadTemplates().then(function () {
        if (!chosen && defaultTemplate && templateByFile(defaultTemplate)) chosen = defaultTemplate;
        // With a single template there is nothing to choose between.
        if (!chosen && templates.length === 1) chosen = templates[0]._file;
        renderTemplates();
        capPlan();
      });
    }).catch(function (e) {
      WD.toast('Could not read that file: ' + e.message, 'error');
    });
  }

  function renderExtract(r) {
    var host = $('capExtract');
    var fromBtn = $('capFromProject');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="cap-empty">' + esc((r && r.error) || 'Could not read that project.') + '</div>';
      fromBtn.hidden = true;
      return;
    }
    if (!r.rows.length) {
      host.innerHTML = '<div class="cap-empty">This project has no capacity set up yet - '
        + 'nothing in its requirement areas says how many devices to plan for. Pick a '
        + 'template in step 1 to add it.</div>';
      fromBtn.hidden = true;
      return;
    }
    var rows = r.rows.map(function (x) {
      return '<tr><td>' + esc(shortDevice(x.device)) + '</td><td class="cap-sub">'
        + esc(x.usage) + '</td><td class="cap-n">' + x.deviceCount + '</td></tr>';
    }).join('');
    host.innerHTML =
      '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
      + '<th style="text-align:right">Devices</th></tr></thead><tbody>' + rows
      + '<tr><td colspan="2" class="cap-total">Total</td><td class="cap-n cap-total">'
      + r.totalDevices + '</td></tr></tbody></table>'
      + (r.requirementName ? '<p class="cap-hint">Requirement: &ldquo;'
          + esc(r.requirementName) + '&rdquo;.</p>' : '')
      + warnings(r);
    fromBtn.hidden = false;
  }

  function warnings(r) {
    var out = '';
    if (r.orphanAreasSkipped) {
      out += '<div class="cap-warn">' + r.orphanAreasSkipped + ' area'
        + (r.orphanAreasSkipped === 1 ? '' : 's') + ' in this project belong'
        + (r.orphanAreasSkipped === 1 ? 's' : '') + ' to a floor plan that no longer exists. '
        + 'Ignored — they describe nothing.</div>';
    }
    if (r.otherAreasDiffer) {
      out += '<div class="cap-warn">More than one area carries capacity and they do not agree. '
        + 'The largest is shown; the others were left out rather than averaged into a '
        + 'mixture that describes no real space.</div>';
    }
    return out;
  }

  // ── templates ──────────────────────────────────────────────────────────────
  var defaultTemplate = '';

  function templateByFile(file) {
    for (var i = 0; i < templates.length; i++) if (templates[i]._file === file) return templates[i];
    return null;
  }

  function loadTemplates() {
    return jsonApi('templates', {}).then(function (r) {
      templates = (r && r.templates) || [];
      if (chosen && !templateByFile(chosen)) chosen = null;
      renderTemplates();
    });
  }

  function renderTemplates() {
    var host = $('capTemplates');
    if (!templates.length) {
      host.innerHTML = '<div class="cap-empty">No templates yet. Press <b>New template</b> '
        + 'to build one, or make one from a project that already has capacity set up.</div>';
    } else {
      host.innerHTML = templates.map(function (t) {
        var on = t._file === chosen;
        var isDefault = t._file === defaultTemplate;
        return '<button type="button" class="cap-tpl' + (on ? ' is-on' : '') + '" '
          + 'role="radio" aria-checked="' + (on ? 'true' : 'false') + '" '
          + 'data-action="call" data-fn="capChoose" data-arg="'
          + WD.escAttr(t._file) + '">'
          + '<span class="cap-tpl-dot" aria-hidden="true"></span>'
          + '<span class="cap-tpl-name">' + esc(t.name)
          + (isDefault ? ' <span class="cap-tpl-default">&#9733; default</span>' : '') + '</span>'
          + '<span class="cap-tpl-meta">' + Number(t.devicesPerOccupant || 0).toFixed(2)
          + ' devices per person' + (t._builtin ? ' &middot; shipped example' : '') + '</span></button>';
      }).join('');
    }
    renderTemplateView();
  }

  /* The mix the chosen template puts in, at this project's headcount - the
     thing to check before pressing Apply. */
  function renderTemplateView() {
    var t = templateByFile(chosen);
    var has = !!t;
    $('capEditBtn').disabled = !has;
    $('capDupBtn').disabled = !has;
    $('capMakeDefault').disabled = !has || chosen === defaultTemplate;
    $('capMakeDefault').textContent = has && chosen === defaultTemplate
      ? '★ This is the default' : '★ Make default';
    var del = $('capDeleteBtn');
    del.disabled = !has || t._builtin;
    del.title = has && t._builtin ? 'A shipped example cannot be deleted' : '';
    resetDelete();
    var host = $('capTplView');
    if (!t) {
      host.innerHTML = templates.length
        ? '<div class="cap-empty">Pick a template above.</div>' : '';
      return;
    }
    var people = Number($('capHeadcount').value) || 0;
    var n = devicesFor(t.items || [], people);
    var rows = (t.items || []).map(function (i, k) {
      return '<tr><td>' + esc(shortDevice(i.device)) + '</td><td class="cap-sub">' + esc(i.usage)
        + '</td><td class="cap-n">' + fmtPer(i.perOccupant) + '</td><td class="cap-n">'
        + (people ? n.rows[k] : '–') + '</td></tr>';
    }).join('');
    host.innerHTML = (t.description ? '<p class="cap-hint">' + esc(t.description) + '</p>' : '')
      + '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
      + '<th style="text-align:right">Per person</th><th style="text-align:right">For '
      + (people || '–') + ' people</th></tr></thead><tbody>' + rows
      + '<tr><td colspan="2" class="cap-total">Total</td><td class="cap-n cap-total">'
      + fmtPer(t.devicesPerOccupant) + '</td><td class="cap-n cap-total">'
      + (people ? n.total : '–')
      + '</td></tr></tbody></table>';
  }

  /* Devices per row at a headcount, and their total, as `apply_headcount` in
     capacity_profiles.py writes them: each row rounded half up, the total the
     sum of the rows. Rounding the total on its own showed 75 where the file
     got 78. */
  function devicesFor(items, people) {
    var rows = items.map(function (i) {
      return Math.floor((Number(i.perOccupant != null ? i.perOccupant : i.per) || 0) * people + 0.5);
    });
    return { rows: rows, total: rows.reduce(function (a, b) { return a + b; }, 0) };
  }

  function fmtPer(n) {
    n = Number(n) || 0;
    var s = n.toFixed(2);
    return s.replace(/0$/, '').replace(/\.0?$/, '');
  }

  window.capChoose = function (file) {
    chosen = file;
    renderTemplates();
    capPlan();
  };

  window.capMakeDefault = function () {
    if (!chosen) return;
    WD.api('settings/update', { patch: { capacity: { default_template: chosen } } })
      .then(function () {
        defaultTemplate = chosen;
        renderTemplates();
        WD.toast('"' + (templateByFile(chosen) || {}).name + '" is picked whenever a project is opened', 'success');
      }).catch(function () { WD.toast('Could not save the default', 'error'); });
  };

  /* Delete asks by changing the button rather than opening a dialog: the
     first press names what will go, the second deletes. A template file is
     not in any project, so this cannot change a project. */
  var _deleteArmed = null;
  function resetDelete() {
    var del = $('capDeleteBtn');
    if (_deleteArmed) clearTimeout(_deleteArmed);
    _deleteArmed = null;
    del.textContent = 'Delete';
    del.classList.remove('is-armed');
  }
  window.capDeleteChosen = function () {
    var t = templateByFile(chosen);
    if (!t || t._builtin) return;
    var del = $('capDeleteBtn');
    if (!_deleteArmed) {
      del.textContent = 'Press again to delete “' + t.name + '”';
      del.classList.add('is-armed');
      _deleteArmed = setTimeout(resetDelete, 5000);
      return;
    }
    resetDelete();
    jsonApi('delete', { file: t._file }).then(function (r) {
      if (!r || !r.ok) { WD.toast((r && r.error) || 'Could not delete', 'error'); return; }
      WD.toast('Deleted "' + t.name + '"', 'success');
      if (defaultTemplate === t._file) {
        defaultTemplate = '';
        WD.api('settings/update', { patch: { capacity: { default_template: '' } } });
      }
      chosen = null;
      loadTemplates().then(capPlan);
    });
  };

  /* The rail's steps. They only scrolled, and on a tall window every card was
     already on screen, so pressing one visibly did nothing - "you can't click
     on it or anything". Now the step is marked current, its card is scrolled
     to and outlined. */
  window.capGoTo = function (id) {
    var card = $(id);
    document.querySelectorAll('.pb-rail .pb-stage').forEach(function (st) {
      st.classList.toggle('is-current', st.getAttribute('data-step') === id);
    });
    if (!card) return;
    card.scrollIntoView({ block: 'start', behavior: 'smooth' });
    card.classList.remove('is-flash');
    void card.offsetWidth;
    card.classList.add('is-flash');
  };

  // ── the editor ─────────────────────────────────────────────────────────────
  /* A template is a list of devices: a device profile, a usage profile, and
     how many of that each person carries. The profiles offered are the ones
     in the open project - Ekahau puts its stock profiles in every project -
     plus any the template already names. "it needs to be built utilizing the
     stuff that's in [Ekahau] So that they can choose you know the device
     types the amount of devices etc And then how many people And then how
     many devices per people". */
  var ed = null;   // { replaces, rows: [{device, usage, per, count}], fromProject, defs }

  function edDefs(base) {
    var avail = (extracted && extracted.available && extracted.available.defs) || {};
    var defs = { devices: {}, usages: {}, requirement: [] };
    var bd = (base && base.profileDefs) || {};
    ['devices', 'usages'].forEach(function (k) {
      Object.keys(bd[k] || {}).forEach(function (n) { defs[k][n] = bd[k][n]; });
      Object.keys(avail[k] || {}).forEach(function (n) { defs[k][n] = avail[k][n]; });
    });
    defs.requirement = bd.requirement
      || (extracted && extracted.profileDefs && extracted.profileDefs.requirement) || [];
    return defs;
  }

  function choices(kind) {
    var names = {};
    ((extracted && extracted.available && extracted.available[kind]) || [])
      .forEach(function (n) { names[n] = true; });
    if (ed) ed.rows.forEach(function (r) {
      var v = kind === 'devices' ? r.device : r.usage;
      if (v) names[v] = true;
    });
    return Object.keys(names).sort(function (a, b) { return a.toLowerCase() < b.toLowerCase() ? -1 : 1; });
  }

  function openEditor(title, intro, name, desc, rows, opts) {
    ed = { rows: rows, replaces: opts.replaces || null, fromProject: !!opts.fromProject,
           defs: edDefs(opts.base), base: opts.base || null };
    $('capEdTitle').textContent = title;
    $('capEdIntro').textContent = intro;
    $('capEdName').value = name;
    $('capEdDesc').value = desc || '';
    $('capEdFrom').hidden = !ed.fromProject;
    $('capEdError').hidden = true;
    renderEditorRows();
    $('capEditor').classList.add('active');
    setTimeout(function () { $('capEdName').focus(); }, 0);
  }

  function rowsFromTemplate(t) {
    return (t.items || []).map(function (i) {
      return { device: i.device, usage: i.usage, per: Number(i.perOccupant) || 0 };
    });
  }

  /* The file a name is saved under - `_safe_filename` in capacity_profiles.py,
     which drops punctuation, so "Lab #1" and "Lab 1" are one file. Letters
     and digits of every script are kept, as there. */
  function templateFileFor(name) {
    var stem = String(name).replace(/[^\p{L}\p{N} _-]+/gu, '').trim() || 'capacity';
    return stem.replace(/ /g, '_') + '_capacitytemplate.json';
  }

  /* A name for a copy that no template already has. Duplicating twice used
     to propose "<name> (copy)" both times, and the second save went over the
     first copy. The server refuses that now; this keeps it from coming up. */
  function freeTemplateName(base, tag) {
    var taken = {};
    templates.forEach(function (t) {
      if (t._builtin) return;
      taken[String(t._file).toLowerCase()] = true;
      taken[templateFileFor(t.name).toLowerCase()] = true;
    });
    for (var n = 1; ; n++) {
      var name = base + ' (' + tag + (n > 1 ? ' ' + n : '') + ')';
      if (!taken[templateFileFor(name).toLowerCase()]) return name;
    }
  }

  window.capEditChosen = function () {
    var t = templateByFile(chosen);
    if (!t) return;
    if (t._builtin) {
      openEditor('Edit a copy of "' + t.name + '"',
        'This is a shipped example, so your changes are saved as a template of your own.',
        freeTemplateName(t.name.replace(/\s*\(example\)\s*$/i, ''), 'my copy'), t.description,
        rowsFromTemplate(t), { base: t });
      return;
    }
    openEditor('Edit "' + t.name + '"', '', t.name, t.description,
               rowsFromTemplate(t), { base: t, replaces: t._file });
  };

  window.capDuplicateChosen = function () {
    var t = templateByFile(chosen);
    if (!t) return;
    openEditor('New template from "' + t.name + '"', 'A copy to change; the original stays as it is.',
               freeTemplateName(t.name, 'copy'), t.description, rowsFromTemplate(t), { base: t });
  };

  window.capNewTemplate = function () {
    var dev = choices('devices'), use = choices('usages');
    openEditor('New template',
      'Add a row for each kind of device a person carries, and how many of it per person.',
      '', '', [{ device: dev[0] || '', usage: use[0] || '', per: 1 }], {});
  };

  window.capTemplateFromProject = function () {
    if (!extracted || !extracted.rows || !extracted.rows.length) return;
    $('capEdPeople').value = '100';
    var rows = extracted.rows.map(function (r) {
      return { device: r.device, usage: r.usage, count: r.deviceCount, per: r.deviceCount / 100 };
    });
    openEditor('New template from this project',
      'Starts from the devices this project already has. Enter how many people it was designed for, then check the numbers per person.',
      fileName.replace(/\.esx(\.zip)?$/i, ''), '', rows,
      { fromProject: true, base: { profileDefs: extracted.profileDefs } });
  };

  window.capEdPeople = function (value) {
    var people = Number(value) || 0;
    if (!ed || people <= 0) return;
    ed.rows.forEach(function (r) { if (r.count != null) r.per = r.count / people; });
    renderEditorRows();
  };

  window.capEditorClose = function () {
    $('capEditor').classList.remove('active');
    ed = null;
  };

  window.capEdAdd = function () {
    if (!ed) return;
    var dev = choices('devices'), use = choices('usages');
    ed.rows.push({ device: dev[0] || '', usage: use[0] || '', per: 1 });
    renderEditorRows();
  };

  window.capEdRemove = function (i) {
    if (!ed) return;
    ed.rows.splice(Number(i), 1);
    renderEditorRows();
  };

  window.capEdSet = function (i, field, value) {
    if (!ed || !ed.rows[Number(i)]) return;
    var row = ed.rows[Number(i)];
    if (field === 'per') {
      row.per = Number(value);
      delete row.count;   // typed by hand: no longer tied to the project's count
    } else {
      row[field] = value;
    }
    renderEditorTotals();
  };

  function optionList(names, current) {
    return names.map(function (n) {
      return '<option value="' + WD.escAttr(n) + '"' + (n === current ? ' selected' : '') + '>'
        + esc(n) + '</option>';
    }).join('');
  }

  function renderEditorRows() {
    if (!ed) return;
    var dev = choices('devices'), use = choices('usages');
    $('capEdRows').innerHTML = ed.rows.map(function (r, i) {
      return '<tr>'
        + '<td><select class="cap-input" aria-label="Device profile" data-action-change="call"'
        + ' data-fn="capEdSet" data-arg="' + i + '" data-arg2="device" data-arg-value="1">'
        + optionList(dev, r.device) + '</select></td>'
        + '<td><select class="cap-input" aria-label="Usage profile" data-action-change="call"'
        + ' data-fn="capEdSet" data-arg="' + i + '" data-arg2="usage" data-arg-value="1">'
        + optionList(use, r.usage) + '</select></td>'
        + '<td class="cap-n"><input type="number" class="cap-input cap-input--num" min="0" step="0.05"'
        + ' aria-label="Devices per person" value="' + WD.escAttr(fmtPer(r.per)) + '"'
        + ' data-action-input="call" data-fn="capEdSet" data-arg="' + i + '" data-arg2="per"'
        + ' data-arg-value="1"></td>'
        + '<td class="cap-n cap-ed-for" data-row="' + i + '"></td>'
        + '<td><button type="button" class="btn btn-sec cap-ed-remove" title="Remove this row"'
        + ' data-action="call" data-fn="capEdRemove" data-arg="' + i + '">Remove</button></td>'
        + '</tr>';
    }).join('');
    renderEditorTotals();
  }

  function renderEditorTotals() {
    if (!ed) return;
    var people = Number($('capHeadcount').value) || 200;
    $('capEdForHead').textContent = 'For ' + people + ' people';
    var total = 0;
    var n = devicesFor(ed.rows, people);
    ed.rows.forEach(function (r, i) {
      total += Number(r.per) || 0;
      var cell = document.querySelector('.cap-ed-for[data-row="' + i + '"]');
      if (cell) cell.textContent = String(n.rows[i]);
    });
    $('capEdTotal').textContent = ed.rows.length
      ? 'In total ' + fmtPer(total) + ' device' + (total === 1 ? '' : 's') + ' per person — '
        + n.total + ' for ' + people + ' people.'
      : 'No devices yet.';
  }

  window.capEdSave = function () {
    if (!ed) return;
    var spec = {
      name: $('capEdName').value,
      description: $('capEdDesc').value,
      items: ed.rows.map(function (r) {
        return { device: r.device, usage: r.usage, perOccupant: r.per };
      }),
      defs: ed.defs,
      capturedFrom: ed.fromProject ? fileName : ((ed.base && ed.base.capturedFrom) || ''),
      requirementName: (ed.base && ed.base.requirementName)
        || (extracted && extracted.requirementName) || '',
    };
    jsonApi('build', { spec: spec, replaces: ed.replaces }).then(function (r) {
      if (!r || !r.ok) {
        var box = $('capEdError');
        box.textContent = (r && r.error) || 'Could not save the template.';
        box.hidden = false;
        return;
      }
      WD.toast('Saved "' + spec.name.trim() + '"', 'success');
      if (ed.replaces && defaultTemplate === ed.replaces && r.file !== ed.replaces) {
        defaultTemplate = r.file;
        WD.api('settings/update', { patch: { capacity: { default_template: r.file } } });
      }
      chosen = r.file;
      window.capEditorClose();
      loadTemplates().then(capPlan);
    });
  };

  function applyQuery() {
    return '?name=' + encodeURIComponent(fileName)
      + '&template=' + encodeURIComponent(chosen)
      + '&occupants=' + encodeURIComponent($('capHeadcount').value)
      + '&existing=' + encodeURIComponent($('capExisting').value || 'keep')
      + (Object.keys(floorExist).length
          ? '&floorExisting=' + encodeURIComponent(JSON.stringify(floorExist)) : '')
      + (Object.keys(floorOcc).length
          ? '&floorOccupants=' + encodeURIComponent(JSON.stringify(floorOcc)) : '');
  }

  // A blank field hands the floor back to the building headcount; 0 means
  // nobody works there and the floor is left alone.
  window.capFloorOccupants = function (floorId, value) {
    var v = String(value == null ? '' : value).trim();
    if (v === '' || isNaN(Number(v)) || Number(v) < 0) delete floorOcc[floorId];
    else floorOcc[floorId] = Number(v);
    capPlan();
  };

  // The choice at the top applies to every floor that has devices; picking it
  // again resets any floor that was set on its own.
  window.capExistingAll = function () {
    floorExist = {};
    capPlan();
  };

  window.capFloorExisting = function (floorId, value) {
    if (value === $('capExisting').value) delete floorExist[floorId];
    else floorExist[floorId] = value;
    capPlan();
  };

  // ── apply preview ──────────────────────────────────────────────────────────
  // The headcount box plans on every keystroke, and replies can come back in
  // any order: a late answer for "20" landing after the one for "200" left a
  // card describing a headcount Apply would not write. Each plan is numbered,
  // only the newest one's reply is drawn, and Apply waits for it.
  var planSeq = 0;

  window.capPlan = function () {
    var seq = ++planSeq;
    renderTemplateView();
    var host = $('capPlan');
    $('capResult').innerHTML = '';
    if (!fileBytes || !chosen) {
      host.innerHTML = '<div class="cap-empty">Pick a template to see what applying it here would do.</div>';
      setApply(false, chosen ? 'Load a project first.' : 'Pick a template first.');
      return;
    }
    setApply(false, 'Working out what applying it would do…');
    api('plan', fileBytes, applyQuery()).then(function (r) {
      if (seq !== planSeq) return;
      if (!r || !r.ok) {
        host.innerHTML = '<div class="cap-empty">' + esc((r && r.error) || 'Could not plan that.') + '</div>';
        // The reason is in the card above; the footer points at it rather
        // than repeat a paragraph, and never just says "nothing".
        setApply(false, 'This template cannot be applied to this project - the reason is under '
          + '2 — Apply it to this project.');
        $('capApplyBtn').textContent = 'Apply and download';
        return;
      }
      // The button says what it will do, so the count is on the button rather
      // than only in the paragraph underneath it.
      if (r.willWrite) {
        setApply(true, 'Builds a new .esx and downloads it. Your file is not touched.');
        $('capApplyBtn').textContent = 'Apply to ' + r.willWrite + ' floor'
          + (r.willWrite === 1 ? '' : 's') + ' and download';
      } else {
        setApply(false, 'No floor would be written: each one is kept as it is or set '
          + 'to 0 people. Choose Replace for floors that already have devices.');
        $('capApplyBtn').textContent = 'Apply and download';
      }
      var counts = r.rows.map(function (x) {
        return '<tr><td>' + esc(shortDevice(x.device)) + '</td><td class="cap-sub">' + esc(x.usage)
          + '</td><td class="cap-n">' + x.deviceCount + '</td></tr>';
      }).join('');
      var floors = r.floors.map(function (f, i) {
        var cls = f.skipped ? 'skip' : (f.mode === 'populate' ? 'yours'
                 : f.mode === 'replace' ? 'replace' : 'create');
        var size = f.widthFt
          ? f.widthFt + ' &times; ' + f.heightFt + ' ft'
          : 'size unknown — this floor plan has no scale set';
        // What happens to THIS floor, in the terms that matter to him: whether
        // his own outline is being used, and whether anything of his is at
        // risk. The computed extent is only relevant when we are making one.
        var facts;
        if (f.mode === 'none') {
          facts = 'Set to 0 people, so nothing is written to this floor.';
        } else if (f.mode === 'populate') {
          facts = 'Using the area you drew'
            + (f.targetAreaName ? ' (<b>' + esc(f.targetAreaName) + '</b>)' : '')
            + (f.targetVertexCount ? ', ' + f.targetVertexCount + ' points' : '')
            + ' — the outline is not changed, only the devices are written into it.';
        } else if (f.mode === 'replace') {
          var many = (f.existingAreaCount || 1) > 1;
          facts = 'Already carries <b>' + (f.existingDevices || 0) + '</b> device'
            + (f.existingDevices === 1 ? '' : 's')
            + (many ? ' across <b>' + f.existingAreaCount + '</b> capacity areas' : '') + '. '
            + (f.existingChoice === 'keep'
                ? 'Kept as it is.'
                : 'Set to <b>' + (f.totalDevices || 0) + '</b> &mdash; replaced, not added to'
                  + (f.existingChoice === 'reshape'
                      ? '; the outline is redrawn from <b>' + esc(basisWords(f.basis)) + '</b>'
                      : '; the outline is kept')
                  + (many ? ', and the other ' + (f.existingAreaCount - 1)
                      + ' area' + (f.existingAreaCount === 2 ? ' is' : 's are')
                      + ' cleared of devices so ' + (f.existingAreaCount === 2 ? 'it stops' : 'they stop')
                      + ' counting twice' : '')
                  + '.')
            + existingPickHtml(f, i);
        } else {
          facts = 'Area from <b>' + esc(basisWords(f.basis)) + '</b>'
            + (f.padMeters ? ' plus ' + f.padMeters + ' m padding' : '')
            + ' &mdash; <b>' + size + '</b>'
            + (f.fractionOfCanvas != null
                ? ' <span class="cap-sub">(' + (f.fractionOfCanvas * 100).toFixed(1)
                  + '% of the page)</span>' : '');
        }
        return '<div class="cap-floor">'
          + '<div class="cap-floor-head"><span class="cap-floor-name">'
          + esc(f.floorName || 'Floor plan') + '</span>'
          + '<span class="cap-badge cap-badge--' + cls + '">' + esc(f.action) + '</span></div>'
          + '<div class="cap-facts">' + facts + '</div>'
          + floorPeopleHtml(f, i, r.devicesPerPerson) + '</div>';
      }).join('');
      var perFloorTable = r.rows.length
        ? '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
          + '<th style="text-align:right">Devices</th></tr></thead><tbody>' + counts
          + '<tr><td colspan="2" class="cap-total">Per floor, '
          + multiplierText(r.occupants, r.devicesPerPerson, r.totalDevices) + '</td>'
          + '<td class="cap-n cap-total">' + r.totalDevices + '</td></tr></tbody></table>'
        : '';
      var existingNote = r.floorsWithDevices
        ? '<div class="cap-warn">' + r.floorsWithDevices + ' floor'
          + (r.floorsWithDevices === 1 ? ' already has' : 's already have')
          + ' devices on it. Choose what happens to '
          + (r.floorsWithDevices === 1 ? 'it' : 'them')
          + ' in <b>Floors that already have devices</b> above, or floor by floor below.</div>'
        : '';
      host.innerHTML = perFloorTable + existingNote
        + '<div style="margin-top:14px">' + floors + '</div>'
        + '<p class="cap-hint">' + r.willWrite + ' floor'
        + (r.willWrite === 1 ? '' : 's') + ' would be written, '
        + r.willSkip + ' left alone'
        + (r.willWrite ? ' &mdash; <b>' + fmtPeople(r.occupantsWritten) + ' people, '
            + r.devicesWritten + ' devices</b> across the floors written' : '')
        + '.'
        + (r.orphanAreasIgnored ? ' ' + r.orphanAreasIgnored
            + ' orphaned area ignored.' : '') + '</p>';
    }).catch(function (e) {
      if (seq !== planSeq) return;
      host.innerHTML = '<div class="cap-empty">' + esc('Could not plan that: ' + e.message) + '</div>';
      setApply(false, 'The plan could not be worked out, so there is nothing to apply.');
    });
  };

  function existingPickHtml(f, i) {
    var id = 'capFloorExist' + i;
    var cur = f.existingChoice || 'keep';
    var opts = [['keep', 'Keep them'], ['devices', 'Replace devices, keep outline'],
                ['reshape', 'Replace devices, redraw outline']];
    return '<div class="cap-row cap-floor-people">'
      + '<label for="' + id + '">This floor</label>'
      + '<select id="' + id + '" class="cap-input" data-action-change="call"'
      + ' data-fn="capFloorExisting" data-arg="' + WD.escAttr(f.floorPlanId) + '"'
      + ' data-arg-value="1">'
      + opts.map(function (o) {
          return '<option value="' + o[0] + '"' + (o[0] === cur ? ' selected' : '') + '>'
            + o[1] + '</option>';
        }).join('')
      + '</select></div>';
  }

  /* People, the template's devices per person, and the devices that come to.
     The multiplier is the point: 250 people on a 3-per-person template read
     as 750 "people" stacked on the building number when only the people and
     the devices were shown. Each device row is rounded on its own (see
     devicesFor), so at small headcounts the total can sit a few above or
     below people x per; that is said rather than shown as a wrong sum. */
  function multiplierText(people, per, total) {
    var devices = total + ' device' + (total === 1 ? '' : 's');
    if (per == null || people == null) return devices;
    var exact = Math.floor(Number(people) * Number(per) + 0.5) === total;
    return fmtPeople(people) + ' people &times; ' + fmtPer(per) + ' devices each '
      + (exact ? '= ' : '&asymp; ') + devices
      + (exact ? '' : ' (each device type is rounded on its own)');
  }

  function fmtPeople(n) {
    n = Number(n) || 0;
    return n === Math.round(n) ? String(n) : n.toFixed(1);
  }

  // Each floor takes its own headcount. Left blank, it uses the building
  // number above - shown as the placeholder so the fallback is visible.
  function floorPeopleHtml(f, i, per) {
    var id = 'capFloorOcc' + i;
    var own = Object.prototype.hasOwnProperty.call(floorOcc, f.floorPlanId);
    return '<div class="cap-row cap-floor-people">'
      + '<label for="' + id + '">People on this floor</label>'
      + '<input type="number" id="' + id + '" class="cap-input cap-input--num" min="0" step="1"'
      + ' value="' + (own ? WD.escAttr(String(floorOcc[f.floorPlanId])) : '') + '"'
      + ' placeholder="' + WD.escAttr($('capHeadcount').value || '') + '"'
      + ' data-action-change="call" data-fn="capFloorOccupants"'
      + ' data-arg="' + WD.escAttr(f.floorPlanId) + '" data-arg-value="1">'
      + '<span class="cap-sub">' + (f.mode === 'none' ? 'nobody here'
          : (own ? '' : 'building number &middot; ')
            + multiplierText(f.occupants, per, f.totalDevices || 0))
      + '</span></div>';
  }

  function setApply(on, note) {
    $('capApplyBtn').disabled = !on;
    $('capApplyNote').textContent = note || '';
  }

  // ── apply ──────────────────────────────────────────────────────────────────
  window.capApply = function () {
    if (!fileBytes || !chosen) return;
    var btn = $('capApplyBtn'), label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Applying…';
    fetch('/api/capacity/apply' + applyQuery(), {
      method: 'POST',
      headers: { 'X-WD-Wireless-Tools': '1' },
      body: fileBytes,
    }).then(function (res) {
      var report = res.headers.get('X-WD-Capacity-Report');
      if (!report) {
        // No file came back: either a refusal, or nothing needed writing.
        return res.json().then(function (j) { renderResult(j, null); });
      }
      return res.blob().then(function (blob) {
        renderResult(JSON.parse(decodeURIComponent(report)), blob);
      });
    }).catch(function (e) {
      WD.toast('Could not apply: ' + e.message, 'error');
    }).then(function () {
      btn.textContent = label;
      btn.disabled = false;
    });
  };

  function renderResult(r, blob) {
    var host = $('capResult');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="cap-warn">' + esc((r && r.error) || 'Could not apply that.') + '</div>';
      return;
    }
    if (!blob) {
      host.innerHTML = '<div class="cap-warn">' + esc(r.note || 'Nothing needed writing.') + '</div>';
      return;
    }
    var name = fileName.replace(/\.esx$/i, '') + ' (capacity).esx';
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);

    var bits = ['Wrote <b>' + esc(name) + '</b> — '
      + r.floorsWritten.length + ' floor'
      + (r.floorsWritten.length === 1 ? '' : 's') + ', '
      + r.devicesWritten + ' devices for ' + fmtPeople(r.occupantsWritten) + ' people'
      + (r.devicesPerPerson != null ? ' at ' + fmtPer(r.devicesPerPerson) + ' devices each' : '')
      + '.'];
    if (r.floorsSkipped.length) {
      bits.push(r.floorsSkipped.length + ' floor'
        + (r.floorsSkipped.length === 1 ? '' : 's') + ' left alone: '
        + esc(r.floorsSkipped.join(', ')) + '.');
    }
    if (r.areasReplaced) {
      bits.push('Replaced the devices on ' + r.areasReplaced + ' area'
        + (r.areasReplaced === 1 ? '' : 's')
        + (r.areasReshaped ? ', ' + r.areasReshaped + ' of them with a redrawn outline' : '')
        + '.');
    }
    if (r.areasCleared) {
      bits.push('Cleared the devices from ' + r.areasCleared + ' other capacity area'
        + (r.areasCleared === 1 ? '' : 's') + ' so the floor total is not counted twice.');
    }
    if (r.areasLeftInPlace) {
      // Worth saying out loud: "replace" did not mean "delete every area".
      bits.push(r.areasLeftInPlace + ' area'
        + (r.areasLeftInPlace === 1 ? ' that carries' : 's that carry')
        + ' a requirement but no capacity ' + (r.areasLeftInPlace === 1 ? 'was' : 'were')
        + ' left where they are.');
    }
    if (r.profilesCreated && r.profilesCreated.length) {
      bits.push('Added ' + r.profilesCreated.length + ' profile'
        + (r.profilesCreated.length === 1 ? '' : 's') + ' this project did not have: '
        + esc(r.profilesCreated.join(', ')) + '.');
    }
    if (r.orphanAreasIgnored) {
      bits.push(r.orphanAreasIgnored + ' orphaned area left untouched.');
    }
    host.innerHTML = '<div class="cap-done">' + bits.join('<br>') + '</div>';
  }

  function basisWords(basis) {
    if (basis === 'walls') return 'the walls you drew';
    if (basis === 'aps') return 'where the APs are';
    if (basis === 'image') return 'the floor plan image';
    return 'the whole page';
  }

  // The saved default from Settings → Capacity. Read only: the dropdown on
  // this page changes one run and never writes back. Any failure leaves the
  // shipped "keep", which changes nothing he set.
  var EXISTING_CHOICES = ['keep', 'devices', 'reshape'];
  var savedExisting = 'keep';

  function loadExistingDefault() {
    return WD.api('settings/get').then(function (r) {
      var cap = (r && r.settings && r.settings.capacity) || {};
      var v = cap.existing_devices;
      if (EXISTING_CHOICES.indexOf(v) >= 0) savedExisting = v;
      if (typeof cap.default_template === 'string') defaultTemplate = cap.default_template;
    }).catch(function () { /* keep the shipped default */ }).then(function () {
      $('capExisting').value = savedExisting;
    });
  }

  // ── wiring ─────────────────────────────────────────────────────────────────
  function init() {
    var dz = $('dropzone'), input = $('fileInput');
    dz.addEventListener('click', function () { input.click(); });
    dz.addEventListener('dragover', function (e) { e.preventDefault(); dz.classList.add('dragover'); });
    dz.addEventListener('dragleave', function () { dz.classList.remove('dragover'); });
    dz.addEventListener('drop', function (e) {
      e.preventDefault(); dz.classList.remove('dragover');
      if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', function () {
      if (input.files.length) loadFile(input.files[0]);
    });
    if (document.addEventListener) {
      document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && $('capEditor').classList.contains('active')) window.capEditorClose();
      });
    }
    loadExistingDefault().then(loadTemplates).then(capPlan);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
