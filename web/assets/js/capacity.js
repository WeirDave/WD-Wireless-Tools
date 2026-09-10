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
    file.arrayBuffer().then(function (buf) {
      fileBytes = buf;
      $('dropzone').style.display = 'none';
      $('editor').classList.add('active');
      $('fileBadge').textContent = fileName;
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
        host.innerHTML = '<div class="cap-empty">No templates yet. Capture one above.</div>';
        return;
      }
      host.innerHTML = templates.map(function (t) {
        return '<div class="cap-tpl' + (t._file === chosen ? ' is-on' : '') + '" '
          + 'onclick="capChoose(\'' + WD.escJsStr(t._file) + '\')">'
          + '<span class="cap-tpl-name">' + esc(t.name) + '</span>'
          + '<span class="cap-tpl-meta">' + Number(t.devicesPerOccupant || 0).toFixed(2)
          + ' per person · ' + (t.items || []).length + ' rows'
          + (t._builtin ? ' · example' : '') + '</span></div>';
      }).join('');
    });
  }

  window.capChoose = function (file) {
    chosen = file;
    loadTemplates();
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
    var q = '?name=' + encodeURIComponent(fileName)
      + '&template=' + encodeURIComponent(chosen)
      + '&occupants=' + encodeURIComponent($('capHeadcount').value)
      + '&replace=' + ($('capReplace').checked ? '1' : '0');
    api('plan', fileBytes, q).then(function (r) {
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
        setApply(false, 'Every floor already has a requirement area. Tick the box above '
          + 'to replace them.');
        $('capApplyBtn').textContent = 'Apply and download';
      }
      var counts = r.rows.map(function (x) {
        return '<tr><td>' + esc(shortDevice(x.device)) + '</td><td class="cap-sub">' + esc(x.usage)
          + '</td><td class="cap-n">' + x.deviceCount + '</td></tr>';
      }).join('');
      var floors = r.floors.map(function (f) {
        var cls = f.skipped ? 'skip' : (f.hasExistingRequirement ? 'replace' : 'create');
        var size = f.widthFt
          ? f.widthFt + ' &times; ' + f.heightFt + ' ft'
          : 'size unknown — this floor plan has no scale set';
        return '<div class="cap-floor">'
          + '<div class="cap-floor-head"><span class="cap-floor-name">'
          + esc(f.floorName || 'Floor plan') + '</span>'
          + '<span class="cap-badge cap-badge--' + cls + '">' + esc(f.action) + '</span></div>'
          + '<div class="cap-facts">'
          + 'Area from <b>' + esc(basisWords(f.basis)) + '</b>'
          + (f.padMeters ? ' plus ' + f.padMeters + ' m padding' : '')
          + ' &mdash; <b>' + size + '</b>'
          + (f.fractionOfCanvas != null
              ? ' <span class="cap-sub">(' + (f.fractionOfCanvas * 100).toFixed(1)
                + '% of the page)</span>' : '')
          + '</div></div>';
      }).join('');
      host.innerHTML =
        '<table class="cap-table"><thead><tr><th>Device profile</th><th>Usage profile</th>'
        + '<th style="text-align:right">Devices</th></tr></thead><tbody>' + counts
        + '<tr><td colspan="2" class="cap-total">Total for ' + r.occupants + ' people</td>'
        + '<td class="cap-n cap-total">' + r.totalDevices + '</td></tr></tbody></table>'
        + '<div style="margin-top:14px">' + floors + '</div>'
        + '<p class="cap-hint">' + r.willWrite + ' floor'
        + (r.willWrite === 1 ? '' : 's') + ' would get a requirement area, '
        + r.willSkip + ' left alone.'
        + (r.orphanAreasIgnored ? ' ' + r.orphanAreasIgnored
            + ' orphaned area ignored.' : '') + '</p>';
    });
  };

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
    var q = '?name=' + encodeURIComponent(fileName)
      + '&template=' + encodeURIComponent(chosen)
      + '&occupants=' + encodeURIComponent($('capHeadcount').value)
      + '&replace=' + ($('capReplace').checked ? '1' : '0');
    fetch('/api/capacity/apply' + q, {
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
      + r.totalDevices + ' devices for ' + r.occupants + ' people.'];
    if (r.floorsSkipped.length) {
      bits.push(r.floorsSkipped.length + ' floor'
        + (r.floorsSkipped.length === 1 ? '' : 's') + ' left alone: '
        + esc(r.floorsSkipped.join(', ')) + '.');
    }
    if (r.areasReplaced) {
      bits.push('Replaced ' + r.areasReplaced + ' capacity area'
        + (r.areasReplaced === 1 ? '' : 's') + '.');
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
    capPlan();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
