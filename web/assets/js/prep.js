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

  // The trim margin is ONE setting, shared with PlanTrim, not a second one
  // that happens to offer the same words. PlanTrim already saves the chosen
  // preset to `plantrim.margin_preset`; a Prep that opened on its own
  // hardcoded default would crop every new site differently from the tool he
  // set his preference in, silently, with nothing on screen saying the two
  // disagreed. He runs Prep on every new site and cannot easily go and look.
  function loadMargin() {
    return WD.api('settings/get').then(function (r) {
      var preset = r && r.settings && r.settings.plantrim
                && r.settings.plantrim.margin_preset;
      var sel = $('prepMargin');
      if (preset && sel) sel.value = preset;
    }).catch(function () { /* settings unavailable - keep the shipped default */ });
  }

  // Its own handler rather than the shared one, so picking a margin saves it
  // and ticking an unrelated checkbox does not.
  window.prepSetMargin = function (value) {
    WD.api('settings/update', { patch: { plantrim: { margin_preset: value } } });
    syncStepUi();
  };

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

  /* Opening from disk, and what happens when that cannot be done.

     The native dialog runs on the server - a browser file input hands over a
     name with no path, and the whole point of this route is knowing which
     folder the project sits in. So there are three outcomes and the page has
     to tell them apart:

       chose a file   - open it
       cancelled      - say nothing; that is the right answer
       never opened   - say so, and fall through to the ordinary browse dialog

     The third used to be reported as the second, which made this button do
     literally nothing: measured in Chrome, Edge and Firefox, the page did not
     change by one character after clicking it. Falling through matters more
     than the message - a tool he cannot get a file into is not usable, and the
     plain input works everywhere. */
  window.prepOpenFromDisk = function () {
    var btn = document.querySelector('.dropzone-open-disk');
    var label = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Opening…'; }
    var done = function () {
      if (btn) { btn.disabled = false; btn.textContent = label; }
    };
    fetch('/api/prep/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: '{}',
    }).then(function (r) { return r.json(); }).then(function (res) {
      done();
      if (!res || !res.ok) {
        if (res && res.code === 'picker_unavailable') {
          WD.toast(res.error + ' Use the drop zone instead.', 'error');
          $('fileInput').value = '';
          $('fileInput').click();
          return;
        }
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
      done();
      WD.toast('Could not open that project: ' + e.message
               + ' Use the drop zone instead.', 'error');
      $('fileInput').value = '';
      $('fileInput').click();
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
    if ($('prepStep-trim').checked) {
      // A preset name, the same vocabulary PlanTrim sends, resolved against the
      // plan's own metersPerUnit at the far end so it means a real distance
      // rather than a pixel count. Prep used to send the bare 10-pixel
      // DEFAULT_MARGIN here, which is the `tight` preset by another name - that
      // is why prepared plans came back cropped hard against the building.
      q += '&margin=' + encodeURIComponent($('prepMargin').value);
      if ($('prepUseBoxes').checked) q += '&useBoxes=1';
    }
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
    $('prepTrimOpts').hidden = !$('prepStep-trim').checked;
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

  // PlanTrim remembers the rectangles he cropped, per project. Prep can reuse
  // them rather than asking him to draw again - the one part of PlanTrim that
  // cannot be a batch control is drawing a box, but a box already drawn is just
  // data. The row stays hidden unless this project has some.
  function syncSavedBoxes(r) {
    var row = $('prepUseBoxesRow');
    if (!row) return;
    var n = (r && r.savedBoxes) || 0;
    row.hidden = !n;
    if (!n) {
      $('prepUseBoxes').checked = false;
      return;
    }
    $('prepUseBoxesLabel').textContent =
      'Use the ' + n + ' rectangle' + (n === 1 ? '' : 's') + ' I drew in PlanTrim'
      + ' (instead of finding the drawing automatically)';
  }

  function renderPreview(r) {
    var host = $('prepPreview');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-empty">'
        + esc((r && r.error) || 'Could not read that project.') + '</div>';
      setGo(false, '');
      return;
    }

    syncSavedBoxes(r);
    var cards = [];
    var willDo = 0;
    // A step that cannot run used to stop the whole prepare, so the button was
    // disabled whenever one refused. It does not any more: the steps that can
    // run do, and the refusal is reported. What the button must not offer is a
    // run where *nothing* can happen.
    var refused = [];
    var order = r.steps || [];

    if (order.indexOf('trim') >= 0) {
      var t = (r.step && r.step.trim) || {};
      if (t.error) {
        cards.push(stepCard('Trim the canvas', 'cannot', 'skip', [esc(t.error)]));
        refused.push('the trim');
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
        // The other steps still run. Saying so matters: the reader is looking
        // at a reason, and needs to know whether it costs them the whole pass
        // or just this part of it.
        cards.push(stepCard('Requirement areas', 'cannot', 'skip',
          [esc(a.error || 'Could not work out the requirement areas.'),
           '<span class="prep-sub">The other steps still run and the file is '
           + 'still written — this part of it is what will be missing. Fix the '
           + 'project in Ekahau and prepare it again to add the areas.</span>']));
        refused.push('the requirement areas');
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
        refused.push('the wall types');
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
      setGo(true, refused.length
        ? 'Builds a new .esx without ' + refused.join(' or ')
          + ' — that part cannot run on this project. Your file is not touched.'
        : 'Builds a new .esx and downloads it. Your file is not touched.');
    } else if (refused.length) {
      setGo(false, 'Nothing can run on this project: ' + refused.join(' and ')
                 + ' cannot, and there is nothing else left to do.');
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
        return res.json().then(function (j) {
          if (j && j.code === 'exists') return confirmReplace(j);
          renderWritten(j);
        });
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
    var ran = r.ran || [];
    var failed = {};
    (r.failed || []).forEach(function (f) { failed[f.step] = f.error; });

    if (ran.indexOf('trim') >= 0) {
      if (failed.trim) bits.push('<b>did not trim</b>');
      else if (r.trimmed) {
        bits.push('trimmed <b>' + r.trimmed + '</b> of ' + r.floorCount + ' '
          + plural(r.floorCount, 'floor plan'));
      } else {
        bits.push('<b>no floor plan needed trimming</b>');
      }
    }

    if (ran.indexOf('areas') >= 0) {
      if (failed.areas) bits.push('<b>did not add requirement areas</b>');
      else if (r.areasWritten && r.areasWritten.length) {
        bits.push('put a requirement area on <b>' + r.areasWritten.length + '</b> '
          + plural(r.areasWritten.length, 'floor'));
      } else {
        bits.push('<b>every floor already had a requirement area</b>');
      }
      if (r.areasRetightened && r.areasRetightened.length) {
        bits.push('re-measured <b>' + r.areasRetightened.length + '</b> '
          + plural(r.areasRetightened.length, 'area') + ' that still covered the whole plan');
      }
    }

    if (ran.indexOf('walls') >= 0) {
      if (failed.walls) bits.push('<b>did not add wall types</b>');
      else if (r.wallTypesAdded && r.wallTypesAdded.length) {
        bits.push('added <b>' + r.wallTypesAdded.length + '</b> wall '
          + plural(r.wallTypesAdded.length, 'type'));
      } else if (r.wallTypesPresent) {
        bits.push('<b>all ' + r.wallTypesPresent + '</b> wall '
          + plural(r.wallTypesPresent, 'type') + ' from that template '
          + (r.wallTypesPresent === 1 ? 'was' : 'were') + ' already in the project');
      } else {
        bits.push('<b>no wall types to add</b>');
      }
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
      ran: r.ran,
      failed: r.failed,
      trimmed: (step.trim || {}).trimmedCount,
      floorCount: (step.trim || {}).floorCount,
      areasWritten: (step.areas || {}).floorsWritten,
      areasRetightened: (step.retighten || []).map(function (x) { return x.floorName; }),
      wallTypesAdded: ((step.walls || {}).add || []).map(function (x) { return x.name; }),
      wallTypesPresent: ((step.walls || {}).skip || []).length,
    });
    // A pass that did two of three things is a success with a gap in it, and
    // the gap has to be as visible as the success - otherwise he opens the
    // project expecting areas that are not there.
    var missed = (r.failed || []).map(function (f) {
      return '<div class="prep-sub">&bull; ' + esc(f.error) + '</div>';
    }).join('');
    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(r.filename || '') + '</b> — '
      + summary + '.'
      + (missed ? '<div class="prep-warn" style="margin:8px 0">'
                  + '<b>One part of the pass did not run:</b>' + missed + '</div>' : '')
      + '<br><span class="prep-sub">It is in <b>' + esc(r.dir || '') + '</b>, beside the '
      + 'original, which is unchanged. Open it in Ekahau and start drawing.</span>'
      + '<div class="prep-row" style="margin:10px 0 0">'
      + '<button class="btn btn-sec" onclick="prepReveal()">Show me the file</button>'
      + '</div></div>';
  }

  /* The prepared file is already there. It may be last week's output, or it
     may be the file he opened in Ekahau this morning and has been drawing in -
     nothing in the archive tells them apart, so he does. */
  function confirmReplace(j) {
    $('prepResult').innerHTML = '<div class="prep-warn">' + esc(j.error)
      + '<div class="prep-row" style="margin:10px 0 0">'
      + '<button class="btn btn-primary" onclick="prepReplace()">Replace it</button>'
      + '<button class="btn btn-sec" onclick="prepReveal()">Show me the folder</button>'
      + '</div></div>';
  }

  window.prepReplace = function () {
    var btn = $('prepGoBtn'), label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Preparing…';
    fetch('/api/prep/run' + query() + '&replace=1', {
      method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
    }).then(function (r) { return r.json(); })
      .then(renderWritten)
      .catch(function (e) {
        WD.toast('Could not prepare that project: ' + e.message, 'error');
      })
      .finally(function () { btn.textContent = label; btn.disabled = false; });
  };

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

    // The same gap has to be visible on this path as on the write-to-disk one:
    // two of three steps is a success with something missing from it, and he
    // opens the project expecting all three.
    var missed = (r.failed || []).map(function (f) {
      return '<div class="prep-sub">&bull; ' + esc(f.error) + '</div>';
    }).join('');
    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(name) + '</b> — '
      + didWhat(r) + '.'
      + (missed ? '<div class="prep-warn" style="margin:8px 0">'
                  + '<b>One part of the pass did not run:</b>' + missed + '</div>' : '')
      + '<br><span class="prep-sub">Your original is untouched. Open the downloaded copy '
      + 'in Ekahau and start drawing.</span></div>';
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    WD.applyVersions();
    loadTemplates();
    loadMargin();

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
