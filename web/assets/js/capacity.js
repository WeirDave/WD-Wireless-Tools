/* WD Capacity — capture a device mix from one project, apply it to another.
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
  var extracted = null;      // what capture read out of it
  var derived = null;        // that, turned into per-person ratios
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
    // A new project starts from the saved default again.
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
      capDerive();
      capPlan();
    }).catch(function (e) {
      WD.toast('Could not read that file: ' + e.message, 'error');
    });
  }

  function renderExtract(r) {
    var host = $('capExtract');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="cap-empty">' + esc((r && r.error) || 'Could not read that project.') + '</div>';
      $('capDeriveCard').hidden = true;
      return;
    }
    if (!r.rows.length) {
      host.innerHTML = '<div class="cap-empty">No capacity items in this project. '
        + 'Set the areas up in Ekahau first — device counts, device profiles and usage '
        + 'profiles — then capture from it.</div>';
      $('capDeriveCard').hidden = true;
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
      + '<p class="cap-hint">'
      + esc(r.rows.length) + ' rows, ' + esc(r.deviceProfileCount) + ' device profile'
      + (r.deviceProfileCount === 1 ? '' : 's') + ' across ' + esc(r.usageProfileCount)
      + ' usage profile' + (r.usageProfileCount === 1 ? '' : 's')
      + (r.requirementName ? ', requirement &ldquo;' + esc(r.requirementName) + '&rdquo;' : '')
      + '. Rows are shown exactly as authored — two rows can share a device and a usage '
      + 'profile and still mean different things.</p>'
      + warnings(r);
    $('capDeriveCard').hidden = false;
    if (!$('capName').value) {
      $('capName').value = fileName.replace(/\.esx(\.zip)?$/i, '');
    }
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
        + 'The largest was captured; the others were left out rather than averaged into a '
        + 'mixture that describes no real space.</div>';
    }
    return out;
  }

  // ── capture → ratios ───────────────────────────────────────────────────────
  window.capDerive = function () {
    var host = $('capDerived');
    if (!extracted) { host.innerHTML = ''; derived = null; return; }
    jsonApi('derive', {
      extracted: extracted,
      occupants: $('capOccupants').value,
      name: $('capName').value,
    }).then(function (r) {
      if (!r || !r.ok) {
        derived = null;
        host.innerHTML = '<div class="cap-empty">' + esc((r && r.error) || 'Could not work that out.') + '</div>';
        return;
      }
      derived = r;
      var rows = r.items.map(function (i) {
        return '<tr><td>' + esc(shortDevice(i.device)) + '</td><td class="cap-sub">' + esc(i.usage)
          + '</td><td class="cap-n">' + i.capturedCount + '</td><td class="cap-n"><b>'
          + i.perOccupant.toFixed(2) + '</b></td><td class="cap-n cap-sub">'
          + (i.shareOfTotal * 100).toFixed(1) + '%</td></tr>';
      }).join('');
      host.innerHTML =
        '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
        + '<th style="text-align:right">Captured</th><th style="text-align:right">Per person</th>'
        + '<th style="text-align:right">Share</th></tr></thead><tbody>' + rows
        + '<tr><td colspan="3" class="cap-total">Devices per person</td>'
        + '<td class="cap-n cap-total">' + r.devicesPerOccupant.toFixed(2) + '</td><td></td></tr>'
        + '</tbody></table>';
    });
  };

  window.capSave = function () {
    if (!derived) { WD.toast('Nothing to save yet', 'warn'); return; }
    var body = JSON.parse(JSON.stringify(derived));
    body.name = $('capName').value || body.name;
    jsonApi('save', { template: body }).then(function (r) {
      if (!r || !r.ok) { WD.toast((r && r.error) || 'Could not save', 'error'); return; }
      WD.toast('Saved "' + body.name + '"', 'success');
      loadTemplates();
    });
  };

  // ── templates ──────────────────────────────────────────────────────────────
  function loadTemplates() {
    jsonApi('templates', {}).then(function (r) {
      templates = (r && r.templates) || [];
      var host = $('capTemplates');
      if (!templates.length) {
        host.innerHTML = '<div class="cap-empty">No templates yet. Open a project that has '
          + 'requirement areas and save one in step 3.</div>';
        return;
      }
      host.innerHTML = templates.map(function (t) {
        var on = t._file === chosen;
        return '<button type="button" class="cap-tpl' + (on ? ' is-on' : '') + '" '
          + 'role="radio" aria-checked="' + (on ? 'true' : 'false') + '" '
          + 'data-action="call" data-fn="capChoose" data-arg="'
          + WD.escAttr(t._file) + '">'
          + '<span class="cap-tpl-dot" aria-hidden="true"></span>'
          + '<span class="cap-tpl-name">' + esc(t.name) + '</span>'
          + '<span class="cap-tpl-meta">' + Number(t.devicesPerOccupant || 0).toFixed(2)
          + ' per person · ' + (t.items || []).length + ' rows'
          + (t._builtin ? ' · example' : '') + '</span></button>';
      }).join('');
    });
  }

  /* The rail's steps. They only scrolled, and on a tall window every card was
     already on screen, so pressing one visibly did nothing - "you can't click
     on it or anything". Now the step is marked current, its card is scrolled
     to and outlined, and a step that is not open yet says why. */
  window.capGoTo = function (id) {
    var card = $(id);
    document.querySelectorAll('.pb-rail .pb-stage').forEach(function (st) {
      st.classList.toggle('is-current', st.getAttribute('data-step') === id);
    });
    if (!card) return;
    if (card.hidden) {
      WD.toast('Saving a template opens once a project with requirement areas '
        + 'is open - step 2 shows what this one has.', 'info');
      return;
    }
    card.scrollIntoView({ block: 'start', behavior: 'smooth' });
    card.classList.remove('is-flash');
    void card.offsetWidth;
    card.classList.add('is-flash');
  };

  window.capChoose = function (file) {
    chosen = file;
    loadTemplates();
    capPlan();
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
  window.capPlan = function () {
    var host = $('capPlan');
    $('capResult').innerHTML = '';
    if (!fileBytes || !chosen) {
      host.innerHTML = '<div class="cap-empty">Pick a template to see what applying it here would do.</div>';
      setApply(false, chosen ? 'Load a project first.' : 'Pick a template first.');
      return;
    }
    api('plan', fileBytes, applyQuery()).then(function (r) {
      if (!r || !r.ok) {
        host.innerHTML = '<div class="cap-empty">' + esc((r && r.error) || 'Could not plan that.') + '</div>';
        setApply(false, 'Nothing to apply.');
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
          + floorPeopleHtml(f, i) + '</div>';
      }).join('');
      var perFloorTable = r.rows.length
        ? '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
          + '<th style="text-align:right">Devices</th></tr></thead><tbody>' + counts
          + '<tr><td colspan="2" class="cap-total">Per floor, for ' + r.occupants + ' people</td>'
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

  function fmtPeople(n) {
    n = Number(n) || 0;
    return n === Math.round(n) ? String(n) : n.toFixed(1);
  }

  // Each floor takes its own headcount. Left blank, it uses the building
  // number above - shown as the placeholder so the fallback is visible.
  function floorPeopleHtml(f, i) {
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
            + (f.totalDevices || 0) + ' device' + (f.totalDevices === 1 ? '' : 's'))
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
      + r.devicesWritten + ' devices for ' + fmtPeople(r.occupantsWritten) + ' people.'];
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
      var v = r && r.settings && r.settings.capacity && r.settings.capacity.existing_devices;
      if (EXISTING_CHOICES.indexOf(v) >= 0) savedExisting = v;
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
    $('capName').addEventListener('input', function () { /* name is read at save */ });
    loadTemplates();
    loadExistingDefault().then(capPlan);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
