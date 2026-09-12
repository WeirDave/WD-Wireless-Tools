/* WD Prep — get a new project ready in one pass.
 *
 * Trim the canvas, put the requirement areas in, load the wall types. Three
 * errands today, three loads and three saves of a file that can run to a
 * couple of hundred megabytes, before a single wall gets drawn.
 *
 * Two things this page deliberately does not do.
 *
 * It does not decide the order the steps run in. The steps go to the server as
 * a set and come back in the order the pipeline says they have to run in - see
 * tools/prep_pipeline.py, where an area injected before the trim holds the crop
 * open and the trim then reports a tidy skip for a crop it was prevented from
 * making. A page that could set that order is a page that could get it wrong.
 *
 * It does not write to the file you loaded. Preparing builds a new copy and
 * downloads it, so replacing the original stays a decision made in a file
 * manager rather than one made here.
 */
(function () {
  'use strict';

  var fileBytes = null;      // the .esx currently loaded, as an ArrayBuffer
  var fileName = '';
  // Opened through the native picker rather than dropped. The server then has
  // the path and reads the file where it lies, so nothing is uploaded - which
  // for a two hundred megabyte project is the difference between a preview
  // that re-runs on every change and one that cannot. It also means the
  // prepared copy is written into the project folder rather than Downloads.
  var fromDisk = false;
  var lastWritten = null;
  var wallTemplates = [];
  var capTemplates = [];
  var previewSeq = 0;        // so a slow preview cannot land after a newer one

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(String(s == null ? '' : s)); }

  function plural(n, one, many) { return n === 1 ? one : (many || one + 's'); }

  // ── what the pickers are filled from ───────────────────────────────────────

  function loadTemplates() {
    return fetch('/api/prep/templates', {
      method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r || !r.ok) return;
      wallTemplates = r.wall || [];
      capTemplates = r.capacity || [];

      $('prepWallTpl').innerHTML = wallTemplates.length
        ? wallTemplates.map(function (t) {
            return '<option value="' + esc(t.file) + '">' + esc(t.name)
              + ' — ' + t.count + ' ' + plural(t.count, 'type') + '</option>';
          }).join('')
        : '<option value="">No wall templates saved yet</option>';

      $('prepCapTpl').innerHTML = capTemplates.length
        ? capTemplates.map(function (t) {
            return '<option value="' + esc(t._file) + '">' + esc(t.name) + '</option>';
          }).join('')
        : '<option value="">No capacity templates saved yet</option>';

      // A step with nothing to work from is switched off and says so, rather
      // than being offered and then refused by the server.
      if (!wallTemplates.length) disableStep('walls', 'Save one in Quick Walls first.');
      if (!capTemplates.length) disableStep('areas', 'Capture one in WD Capacity first.');
      syncStepUi();
    }).catch(function () { /* the pickers stay empty; the notes explain */ });
  }

  function disableStep(step, why) {
    var box = $('prepStep-' + step);
    box.checked = false;
    box.disabled = true;
    $('prepNote-' + step).textContent = why;
  }

  // ── file in ────────────────────────────────────────────────────────────────

  window.prepLoadNewFile = function () { $('fileInput').click(); };

  function openEditor(name) {
    fileName = name;
    $('dropzone').style.display = 'none';
    $('editor').classList.add('active');
    $('fileBadge').textContent = name;
    $('fileBadge').style.display = 'inline-block';
    $('prepResult').innerHTML = '';
    lastWritten = null;
  }

  window.prepOpenFromDisk = function () {
    fetch('/api/prep/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res || !res.ok) {
        if (res && res.error && res.error !== 'No file selected') {
          WD.toast(res.error, 'error');
        }
        return;
      }
      fromDisk = true;
      fileBytes = null;            // deliberately not read into the browser
      openEditor(res.name);
      $('fileBadge').title = res.dir;
      WD.toast('Opened from ' + res.dir, 'success');
      preview();
    }).catch(function (e) {
      WD.toast('Could not open that project: ' + e.message, 'error');
    });
  };

  function loadFile(file) {
    // A dropped file has no path, so anything the server remembered about a
    // previously picked one is now wrong.
    fromDisk = false;
    fetch('/api/prep/forget', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).catch(function () { /* nothing depends on it */ });
    fileName = file.name;
    file.arrayBuffer().then(function (buf) {
      fileBytes = buf;
      openEditor(file.name);
      preview();
    }).catch(function (e) {
      WD.toast('Could not read that file: ' + e.message, 'error');
    });
  }

  // ── what the run would do ──────────────────────────────────────────────────

  function chosenSteps() {
    return ['trim', 'areas', 'walls'].filter(function (s) {
      return $('prepStep-' + s).checked;
    });
  }

  function query() {
    var q = '?name=' + encodeURIComponent(fileName)
      + (fromDisk ? '&source=disk' : '')
      + '&steps=' + chosenSteps().join(',')
      + '&retighten=' + ($('prepRetighten').checked ? '1' : '0');
    if ($('prepStep-walls').checked) {
      q += '&wallTemplate=' + encodeURIComponent($('prepWallTpl').value);
    }
    if ($('prepStep-areas').checked) {
      q += '&capacityTemplate=' + encodeURIComponent($('prepCapTpl').value)
        + '&occupants=' + encodeURIComponent($('prepOccupants').value);
    }
    return q;
  }

  window.prepSyncStepUi = syncStepUi;

  function syncStepUi() {
    $('prepAreaOpts').hidden = !$('prepStep-areas').checked;
    $('prepWallOpts').hidden = !$('prepStep-walls').checked;
    preview();
  }

  function loaded() { return fromDisk || !!fileBytes; }

  function preview() {
    if (!loaded()) return;
    var steps = chosenSteps();
    if (!steps.length) {
      $('prepPreview').innerHTML =
        '<div class="prep-empty">Pick at least one thing to do.</div>';
      setGo(false, '');
      return;
    }
    var seq = ++previewSeq;
    $('prepPreview').innerHTML = '<div class="prep-empty">Reading the project…</div>';
    setGo(false, '');
    fetch('/api/prep/plan' + query(), {
      method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
      body: fromDisk ? null : fileBytes,
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (seq !== previewSeq) return;    // a newer preview has overtaken this one
      renderPreview(r);
    }).catch(function (e) {
      if (seq !== previewSeq) return;
      $('prepPreview').innerHTML = '<div class="prep-empty">'
        + esc('Could not read that project: ' + e.message) + '</div>';
    });
  }

  function stepCard(title, badge, badgeCls, lines) {
    return '<div class="prep-item">'
      + '<div class="prep-item-head"><span class="prep-item-name">' + esc(title) + '</span>'
      + '<span class="prep-badge prep-badge--' + badgeCls + '">' + esc(badge) + '</span></div>'
      + '<div class="prep-facts">' + lines.join('<br>') + '</div></div>';
  }

  function renderPreview(r) {
    var host = $('prepPreview');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-empty">'
        + esc((r && r.error) || 'Could not read that project.') + '</div>';
      setGo(false, '');
      return;
    }

    var cards = [];
    var willDo = 0;
    var order = r.steps || [];

    if (order.indexOf('trim') >= 0) {
      var t = (r.step && r.step.trim) || {};
      if (t.error) {
        cards.push(stepCard('Trim the canvas', 'cannot', 'skip', [esc(t.error)]));
      } else {
        var n = t.trimmedCount || 0;
        willDo += n;
        var lines = (t.floors || []).map(function (f) {
          if (f.action === 'trimmed') {
            return '<b>' + esc(f.name) + '</b> — ' + f.oldSize[0] + '×' + f.oldSize[1]
              + ' → ' + f.newSize[0] + '×' + f.newSize[1]
              + ' <span class="prep-sub">(' + f.areaSavedPct + '% of the sheet was empty)</span>';
          }
          return '<b>' + esc(f.name) + '</b> — <span class="prep-sub">'
            + esc(f.action + (f.reason ? ': ' + f.reason : '')) + '</span>';
        });
        cards.push(stepCard('Trim the canvas',
          n ? n + ' of ' + t.floorCount + ' ' + plural(t.floorCount, 'floor') : 'nothing to do',
          n ? 'do' : 'skip', lines.length ? lines : ['No floor plans in this project.']));
      }
    }

    if (order.indexOf('areas') >= 0) {
      var a = (r.step && r.step.areas) || {};
      if (!a.ok) {
        cards.push(stepCard('Requirement areas', 'cannot', 'skip',
          [esc(a.error || 'Could not work out the requirement areas.')]));
      } else {
        willDo += a.willWrite || 0;
        var rows = (a.floors || []).map(function (f) {
          var size = f.widthFt
            ? ' <span class="prep-sub">(' + f.widthFt + ' × ' + f.heightFt + ' ft, from the '
              + esc(f.basis) + ')</span>'
            : '';
          return '<b>' + esc(f.floorName || f.floorPlanId) + '</b> — ' + esc(f.action) + size;
        });
        rows.push('<span class="prep-sub">' + a.totalDevices + ' devices for '
          + a.occupants + ' people.</span>');
        cards.push(stepCard('Requirement areas',
          a.willWrite ? a.willWrite + ' ' + plural(a.willWrite, 'floor') : 'nothing to do',
          a.willWrite ? 'do' : 'skip', rows));
        if (a.measuredBeforeTrim) {
          cards.push('<p class="prep-hint">Those sizes are measured on the plan as it is '
            + 'now. Trimming runs first, so the areas are re-measured on the cropped '
            + 'canvas when you actually prepare the file.</p>');
        }
      }
    }

    if (order.indexOf('walls') >= 0) {
      var w = (r.step && r.step.walls) || {};
      if (w.error) {
        cards.push(stepCard('Wall types', 'cannot', 'skip', [esc(w.error)]));
      } else {
        var add = w.add || [], skip = w.skip || [];
        willDo += add.length;
        var wl = [];
        // Chips, not a comma-joined list. Half the shipped names have a comma
        // in them - "Door, Hollow Wood", "Wall, Cinder Block" - so joining on
        // commas produces a run of words with no way to tell where one type
        // ends and the next begins.
        wl.push(add.length
          ? 'Adding ' + add.map(function (x) {
              return '<span class="prep-chip">' + esc(x.name) + '</span>';
            }).join('')
          : '<span class="prep-sub">Every type in this template is already here.</span>');
        if (skip.length) {
          wl.push('<span class="prep-sub">' + skip.length + ' already in the project, left '
            + 'alone — replacing one would change the attenuation of walls already drawn '
            + 'with it.</span>');
        }
        cards.push(stepCard('Wall types',
          add.length ? add.length + ' to add' : 'nothing to do',
          add.length ? 'do' : 'skip', wl));
      }
    }

    host.innerHTML = cards.join('');
    if (willDo) {
      setGo(true, 'Builds a new .esx and downloads it. Your file is not touched.');
    } else {
      setGo(false, 'This project is already prepared — there is nothing left to do.');
    }
  }

  function setGo(on, note) {
    $('prepGoBtn').disabled = !on;
    $('prepGoNote').textContent = note || '';
  }

  // ── the run ────────────────────────────────────────────────────────────────

  window.prepRun = function () {
    if (!loaded()) return;
    var btn = $('prepGoBtn'), label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Preparing…';
    fetch('/api/prep/run' + query(), {
      method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
      body: fromDisk ? null : fileBytes,
    }).then(function (res) {
      // Opened from disk there is no download at all - the server wrote the
      // file beside the original and hands back where it put it.
      if (fromDisk) {
        return res.json().then(function (j) { renderWritten(j); });
      }
      var report = res.headers.get('X-WD-Prep-Report');
      if (!report) {
        // No file came back: either a refusal, or nothing needed doing.
        return res.json().then(function (j) { renderResult(j, null); });
      }
      return res.blob().then(function (blob) {
        renderResult(JSON.parse(decodeURIComponent(report)), blob);
      });
    }).catch(function (e) {
      WD.toast('Could not prepare that project: ' + e.message, 'error');
    }).finally(function () {
      btn.textContent = label;
      btn.disabled = false;
    });
  };

  function didWhat(r) {
    var bits = [];
    if (r.trimmed) {
      bits.push('trimmed <b>' + r.trimmed + '</b> of ' + r.floorCount + ' '
        + plural(r.floorCount, 'floor plan'));
    }
    if (r.areasWritten && r.areasWritten.length) {
      bits.push('put a requirement area on <b>' + r.areasWritten.length + '</b> '
        + plural(r.areasWritten.length, 'floor'));
    }
    if (r.areasRetightened && r.areasRetightened.length) {
      bits.push('re-measured <b>' + r.areasRetightened.length + '</b> '
        + plural(r.areasRetightened.length, 'area') + ' that still covered the whole plan');
    }
    if (r.wallTypesAdded && r.wallTypesAdded.length) {
      bits.push('added <b>' + r.wallTypesAdded.length + '</b> wall '
        + plural(r.wallTypesAdded.length, 'type'));
    }
    return bits.length ? bits.join(', ') : 'no changes were needed';
  }

  /* Opened from disk: the prepared copy is already sitting in the project
     folder, so the useful thing to say is where, and to offer to show it -
     the next thing he does is open it in Ekahau. */
  function renderWritten(r) {
    var host = $('prepResult');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-warn">'
        + esc((r && r.error) || 'Nothing was written.') + '</div>';
      return;
    }
    if (!r.written) {
      host.innerHTML = '<div class="prep-warn">' + esc(r.note || 'Nothing needed doing.')
        + '</div>';
      return;
    }
    lastWritten = r.path || null;
    var step = r.step || {};
    var summary = didWhat({
      trimmed: (step.trim || {}).trimmedCount,
      floorCount: (step.trim || {}).floorCount,
      areasWritten: (step.areas || {}).floorsWritten,
      areasRetightened: (step.retighten || []).map(function (x) { return x.floorName; }),
      wallTypesAdded: ((step.walls || {}).add || []).map(function (x) { return x.name; }),
    });
    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(r.filename || '') + '</b> — '
      + summary + '.'
      + '<br><span class="prep-sub">It is in <b>' + esc(r.dir || '') + '</b>, beside the '
      + 'original, which is unchanged. Open it in Ekahau and start drawing.</span>'
      + '<div class="prep-row" style="margin:10px 0 0">'
      + '<button class="btn btn-sec" onclick="prepReveal()">Show me the file</button>'
      + '</div></div>';
  }

  window.prepReveal = function () {
    fetch('/api/prep/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).catch(function () { /* cosmetic - the file is already written */ });
  };

  function renderResult(r, blob) {
    var host = $('prepResult');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-warn">'
        + esc((r && r.error) || 'Nothing was written.') + '</div>';
      return;
    }
    if (!blob) {
      host.innerHTML = '<div class="prep-warn">' + esc(r.note || 'Nothing needed doing.')
        + '</div>';
      return;
    }

    var name = (fileName.replace(/\.esx$/i, '') || 'project') + ' (prepared).esx';
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);

    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(name) + '</b> — '
      + didWhat(r) + '.'
      + '<br><span class="prep-sub">Your original is untouched. Open the downloaded copy '
      + 'in Ekahau and start drawing.</span></div>';
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    WD.applyVersions();
    loadTemplates();

    $('fileInput').addEventListener('change', function (e) {
      if (e.target.files[0]) loadFile(e.target.files[0]);
      e.target.value = '';
    });
    var dz = $('dropzone');
    dz.addEventListener('click', function () { $('fileInput').click(); });
    dz.addEventListener('dragover', function (e) {
      e.preventDefault(); dz.classList.add('dragover');
    });
    dz.addEventListener('dragleave', function () { dz.classList.remove('dragover'); });
    dz.addEventListener('drop', function (e) {
      e.preventDefault();
      dz.classList.remove('dragover');
      if (e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]);
    });
  });
})();
