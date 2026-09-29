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
  var floorOcc = {};         // floorPlanId -> headcount typed for that floor
  // Settings → Capacity → Floors that already have devices. Read only: the
  // dropdown here changes one run and never writes back. A failed read or an
  // unknown value leaves "keep", which changes nothing he set.
  var EXISTING_CHOICES = ['keep', 'devices', 'reshape'];
  var savedExisting = 'keep';

  function loadExistingDefault() {
    return WD.api('settings/get').then(function (r) {
      var v = r && r.settings && r.settings.capacity && r.settings.capacity.existing_devices;
      if (EXISTING_CHOICES.indexOf(v) >= 0) savedExisting = v;
    }).catch(function () { /* keep the shipped default */ }).then(function () {
      if ($('prepExisting')) $('prepExisting').value = savedExisting;
      // A project opened before the setting arrived previewed on "keep".
      if (loaded()) preview();
    });
  }

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(String(s == null ? '' : s)); }
  function escAttr(s) { return WD.escAttr(s); }

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
      var pt = (r && r.settings && r.settings.plantrim) || {};
      var sel = $('prepMargin');
      if (pt.margin_custom_ft && $('prepMarginFt')) {
        $('prepMarginFt').value = pt.margin_custom_ft;
      }
      if (pt.margin_preset && sel) sel.value = pt.margin_preset;
      syncMarginUi();
    }).catch(function () { /* settings unavailable - keep the shipped default */ });
  }

  function syncMarginUi() {
    var wrap = $('prepMarginCustomWrap');
    if (wrap) wrap.hidden = $('prepMargin').value !== 'custom';
  }

  // Its own handler rather than the shared one, so picking a margin saves it
  // and ticking an unrelated checkbox does not.
  window.prepSetMargin = function (value) {
    WD.api('settings/update', { patch: { plantrim: { margin_preset: value } } });
    syncMarginUi();
    syncStepUi();
  };

  window.prepSetCustomMargin = function (value) {
    var ft = Math.max(1, Math.min(2000, parseFloat(value) || 0));
    $('prepMarginFt').value = ft;
    WD.api('settings/update', { patch: { plantrim: { margin_custom_ft: ft } } });
    syncStepUi();
  };

  // What goes on the wire. A preset travels by name; a typed distance travels
  // as metres with an `m` on it, because a bare number still means pixels to
  // the trimmer and 60 pixels is not 60 feet.
  function marginParam() {
    var v = $('prepMargin').value;
    if (v !== 'custom') return v;
    var ft = parseFloat($('prepMarginFt').value) || WD.DEFAULT_CUSTOM_MARGIN_FT;
    return (ft * WD.METRES_PER_FOOT).toFixed(4) + 'm';
  }

  // Read before the list is built, because which option is selected depends
  // on it. An empty string means no saved default, not "use Ekahau's".
  var savedWallTemplateName = '';

  function loadTemplates() {
    return WD.savedWallTemplateName().then(function (name) {
      savedWallTemplateName = name || '';
      return fetch('/api/prep/templates', {
        method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
      });
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r || !r.ok) return;
      wallTemplates = r.wall || [];
      capTemplates = r.capacity || [];

      // His template first and selected; Ekahau's last, and chosen only when
      // there is nothing of his. The rule lives in WD so that Prep and Quick
      // Walls cannot drift apart again - this list used to render in the
      // order the server returned it, which put "Ekahau Default" first and
      // left the browser to select it, so preparing a project quietly applied
      // Ekahau's stock types unless he noticed the dropdown and changed it.
      wallTemplates = WD.wallTemplateOrder(wallTemplates);
      var chosen = WD.chooseWallTemplate(wallTemplates, savedWallTemplateName);
      $('prepWallTpl').innerHTML = wallTemplates.length
        ? wallTemplates.map(function (t) {
            var sel = (chosen && t.file === chosen.file) ? ' selected' : '';
            return '<option value="' + escAttr(t.file) + '"' + sel + '>'
              + esc(WD.wallTemplateLabel(t)) + '</option>';
          }).join('')
        : '<option value="">No wall templates saved yet</option>';

      $('prepCapTpl').innerHTML = capTemplates.length
        ? capTemplates.map(function (t) {
            return '<option value="' + escAttr(t._file) + '">' + esc(t.name) + '</option>';
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
    floorOcc = {};             // floors belong to one project
    if ($('prepExisting')) $('prepExisting').value = savedExisting;
    $('dropzone').style.display = 'none';
    $('editor').classList.add('active');
    $('fileBadge').textContent = name;
    $('fileBadge').style.display = 'inline-block';
    $('prepResult').innerHTML = '';
    lastWritten = null;
    resetMap();
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
      q += '&margin=' + encodeURIComponent(marginParam());
      if ($('prepUseBoxes').checked) q += '&useBoxes=1';
    }
    if ($('prepStep-walls').checked) {
      q += '&wallTemplate=' + encodeURIComponent($('prepWallTpl').value);
    }
    if ($('prepStep-areas').checked) {
      q += '&capacityTemplate=' + encodeURIComponent($('prepCapTpl').value)
        + '&occupants=' + encodeURIComponent($('prepOccupants').value)
        + '&existing=' + encodeURIComponent(
            EXISTING_CHOICES.indexOf($('prepExisting').value) >= 0
              ? $('prepExisting').value : 'keep');
      if (Object.keys(floorOcc).length) {
        q += '&floorOccupants=' + encodeURIComponent(JSON.stringify(floorOcc));
      }
    }
    return q;
  }

  // Same rule as Capacity: blank hands the floor back to the number above,
  // 0 means nobody works there and the floor is left alone.
  window.prepFloorOccupants = function (floorId, value) {
    var v = String(value == null ? '' : value).trim();
    if (v === '' || isNaN(Number(v)) || Number(v) < 0) delete floorOcc[floorId];
    else floorOcc[floorId] = Number(v);
    preview();
  };

  function floorPeopleHtml(f, i) {
    var id = 'prepFloorOcc' + i;
    var own = Object.prototype.hasOwnProperty.call(floorOcc, f.floorPlanId);
    return '<span class="prep-floor-people">'
      + '<label for="' + id + '">People on this floor</label> '
      + '<input type="number" id="' + id + '" class="prep-input prep-input--num" min="0" step="1"'
      + ' value="' + (own ? escAttr(String(floorOcc[f.floorPlanId])) : '') + '"'
      + ' placeholder="' + escAttr($('prepOccupants').value || '') + '"'
      + ' data-action-change="call" data-fn="prepFloorOccupants"'
      + ' data-arg="' + escAttr(f.floorPlanId) + '" data-arg-value="1"> '
      + '<span class="prep-sub">' + (f.mode === 'none' ? 'nobody here'
          : (own ? '' : 'the number above · ')
            + (f.totalDevices || 0) + ' ' + plural(f.totalDevices || 0, 'device'))
      + '</span></span>';
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
      $('prepMap').hidden = true;
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

  // How much drawing this sheet actually carries beyond the building, each
  // way. It is the only thing that answers "is 200 ft a real choice here" -
  // on a sheet with 80 ft of site on it, every margin above 80 is the same
  // margin, and without this the only way to find that out is to try one.
  function clearanceLine(f) {
    var c = f && f.clearance;
    if (!c) return '';
    var ft = function (m) { return Math.round(m * WD.FEET_PER_METRE) + ' ft'; };
    return '<br><span class="prep-sub">drawing beyond the building: '
      + ft(c.left) + ' left, ' + ft(c.right) + ' right, '
      + ft(c.top) + ' up, ' + ft(c.bottom) + ' down</span>';
  }

  function renderPreview(r) {
    var host = $('prepPreview');
    if (!r || !r.ok) {
      $('prepMap').hidden = true;
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

    renderMap(order.indexOf('trim') >= 0 ? (r.step && r.step.trim) : null);

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
              + ' <span class="prep-sub">(' + f.areaSavedPct + '% of the sheet was empty)</span>'
              + clearanceLine(f);
          }
          return '<b>' + esc(f.name) + '</b> — <span class="prep-sub">'
            + esc(f.action + (f.reason ? ': ' + f.reason : '')) + '</span>'
            + clearanceLine(f);
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
        var rows = (a.floors || []).map(function (f, i) {
          var size = f.widthFt
            ? ' <span class="prep-sub">(' + f.widthFt + ' × ' + f.heightFt + ' ft, from the '
              + esc(f.basis) + ')</span>'
            : '';
          return '<b>' + esc(f.floorName || f.floorPlanId) + '</b> — ' + esc(f.action) + size
            + '<br>' + floorPeopleHtml(f, i);
        });
        rows.push('<span class="prep-sub">' + (a.willWrite
          ? (a.devicesWritten != null ? a.devicesWritten : a.totalDevices) + ' devices for '
            + (a.occupantsWritten != null ? a.occupantsWritten : a.occupants)
            + ' people across the floors being written.'
          : 'No floor is being written.') + '</span>');
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
        var add = w.add || [], upd = w.update || [], skip = w.skip || [];
        var todo = add.length + upd.length;
        willDo += todo;
        var chips = function (xs) {
          return xs.map(function (x) {
            return '<span class="prep-chip">' + esc(x.name) + '</span>';
          }).join('');
        };
        var wl = [];
        // Chips, not a comma-joined list. Half the shipped names have a comma
        // in them - "Door, Hollow Wood", "Wall, Cinder Block" - so joining on
        // commas produces a run of words with no way to tell where one type
        // ends and the next begins.
        if (add.length) wl.push('Adding ' + chips(add));
        if (upd.length) {
          wl.push('Setting to the template’s version ' + chips(upd)
            + '<br><span class="prep-sub">Same types the project already has, with the '
            + 'template’s colour, number key and attenuation. Walls already drawn '
            + 'with them stay on them.</span>');
        }
        if (!todo) {
          wl.push('<span class="prep-sub">Every type in this template is already here, '
            + 'exactly as the template has it.</span>');
        } else if (w.unchanged) {
          wl.push('<span class="prep-sub">' + w.unchanged + ' already match the template.</span>');
        }
        if (skip.length) {
          wl.push('<span class="prep-sub">Not applied: ' + skip.map(function (x) {
            return esc(x.name + ' (' + x.why + ')');
          }).join('; ') + '</span>');
        }
        cards.push(stepCard('Wall types',
          todo ? [add.length ? add.length + ' to add' : '',
                  upd.length ? upd.length + ' to update' : '']
                   .filter(Boolean).join(', ') : 'nothing to do',
          todo ? 'do' : 'skip', wl));
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

  // ── the map: what the trim keeps, drawn on the plan ─────────────────────────
  //
  // PlanTrim's proposed-crop view, read-only. The box comes straight out of the
  // plan report the cards below are quoting, so the picture and the numbers
  // cannot disagree. A dropped project is already in the browser and is read
  // with JSZip; one opened from disk never is, so its images come one floor at
  // a time from /api/prep/image.

  var map = { floors: [], current: null, images: {}, zip: null };

  function resetMap() {
    map.floors = [];
    map.current = null;
    map.images = {};
    map.zip = null;
    $('prepMap').hidden = true;
  }

  /* The kept rectangle in the displayed image's own pixels, or null.

     The report is in the plan's coordinate space (`oldSize`), which for a
     raster is the image and for an SVG is its viewBox - and a browser renders
     an SVG at whatever size its root element asks for. Scaling by the ratio is
     what keeps the box on the drawing either way. */
  function mapKeptBox(f, iw, ih) {
    if (!f || f.action !== 'trimmed' || !f.offset || !f.newSize || !f.oldSize) return null;
    if (!f.oldSize[0] || !f.oldSize[1] || !iw || !ih) return null;
    var sx = iw / f.oldSize[0], sy = ih / f.oldSize[1];
    return [f.offset[0] * sx, f.offset[1] * sy,
            (f.offset[0] + f.newSize[0]) * sx, (f.offset[1] + f.newSize[1]) * sy];
  }
  window.__prepMapKeptBox = mapKeptBox;

  function mapFloorState(f) {
    if (f.action === 'trimmed') {
      return { cls: 'is-auto', word: 'Trim',
               detail: f.oldSize[0] + '×' + f.oldSize[1] + ' → '
                 + f.newSize[0] + '×' + f.newSize[1] };
    }
    if (f.action === 'skipped') return { cls: 'is-skip', word: 'Leave as is', detail: f.reason || '' };
    return { cls: 'is-refused', word: 'Refused', detail: f.reason || '' };
  }

  function renderMap(t) {
    var host = $('prepMap');
    var floors = (t && !t.error && t.floors) || [];
    if (!floors.length) { host.hidden = true; map.floors = []; return; }
    map.floors = floors;
    var ids = floors.map(function (f) { return f.id; });
    if (ids.indexOf(map.current) < 0) {
      // Open on the first floor that is actually being cropped.
      var first = floors.filter(function (f) { return f.action === 'trimmed'; })[0] || floors[0];
      map.current = first.id;
    }
    host.hidden = false;
    $('prepMapStrip').innerHTML = floors.map(function (f) {
      var st = mapFloorState(f);
      return '<button type="button" class="ptb-row ' + st.cls
        + (f.id === map.current ? ' is-current' : '') + '"'
        + ' data-action="call" data-fn="prepMapSelect" data-arg="' + escAttr(f.id) + '">'
        + '<span class="ptb-row-name">' + esc(f.name) + '</span>'
        + '<span class="ptb-row-state">' + esc(st.word) + '</span>'
        + '<span class="ptb-row-detail">' + esc(st.detail) + '</span>'
        + '</button>';
    }).join('');
    showMapFloor();
  }

  window.prepMapSelect = function (id) {
    map.current = id;
    Array.prototype.forEach.call($('prepMapStrip').children, function (b) {
      b.classList.toggle('is-current', b.getAttribute('data-arg') === id);
    });
    showMapFloor();
  };

  function currentMapFloor() {
    return map.floors.filter(function (f) { return f.id === map.current; })[0] || null;
  }

  function sniffImageType(bytes) {
    var i = 0;
    if (bytes[0] === 0xEF && bytes[1] === 0xBB && bytes[2] === 0xBF) i = 3;
    while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x0A
                                || bytes[i] === 0x0D || bytes[i] === 0x09)) i++;
    return bytes[i] === 0x3C ? 'image/svg+xml' : '';
  }

  function floorImageBlob(id) {
    if (fromDisk) {
      return fetch('/api/prep/image?floor=' + encodeURIComponent(id), {
        method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
      }).then(function (r) {
        if (!r.ok) {
          return r.json().then(function (j) { throw new Error(j.error || 'no image'); },
                               function () { throw new Error('no image'); });
        }
        return r.blob();
      });
    }
    if (!fileBytes || typeof JSZip === 'undefined') return Promise.reject(new Error('no image'));
    if (!map.zip) map.zip = JSZip.loadAsync(fileBytes);
    return map.zip.then(function (zip) {
      var fp = zip.file('floorPlans.json');
      if (!fp) throw new Error('This project has no floor plans.');
      return fp.async('string').then(function (txt) {
        var plan = (JSON.parse(txt).floorPlans || []).filter(function (p) { return p.id === id; })[0];
        var entry = plan && plan.imageId && zip.file('image-' + plan.imageId);
        if (!entry) throw new Error('This floor has no image in the archive.');
        return entry.async('uint8array');
      });
    }).then(function (bytes) {
      var type = sniffImageType(bytes);
      return new Blob([bytes], type ? { type: type } : undefined);
    });
  }

  function floorImage(id) {
    if (map.images[id]) return map.images[id];
    map.images[id] = floorImageBlob(id).then(function (blob) {
      return new Promise(function (resolve, reject) {
        var url = URL.createObjectURL(blob);
        var im = new Image();
        im.onload = function () { URL.revokeObjectURL(url); resolve(im); };
        im.onerror = function () {
          URL.revokeObjectURL(url);
          reject(new Error('This floor plan image could not be displayed.'));
        };
        im.src = url;
      });
    });
    return map.images[id];
  }

  function showMapFloor() {
    var f = currentMapFloor();
    if (!f) return;
    var id = f.id;
    var empty = $('prepMapEmpty');
    var st = mapFloorState(f);
    $('prepMapCaption').textContent = f.action === 'trimmed'
      ? f.name + ': ' + st.detail + ' — ' + f.areaSavedPct + '% of the sheet is cut away.'
      : f.name + ': not cropped' + (f.reason ? ' — ' + f.reason : '') + '.';
    floorImage(id).then(function (im) {
      if (map.current !== id) return;
      empty.hidden = true;
      drawMap(im, f);
    }, function (e) {
      if (map.current !== id) return;
      clearMapCanvas();
      empty.hidden = false;
      empty.textContent = e.message || 'This floor plan could not be displayed.';
    });
  }

  function clearMapCanvas() {
    var cv = $('prepMapCanvas');
    cv.getContext('2d').clearRect(0, 0, cv.width, cv.height);
  }

  function drawMap(im, f) {
    var cv = $('prepMapCanvas');
    var r = cv.getBoundingClientRect();
    var dpr = window.devicePixelRatio || 1;
    cv.width = Math.max(1, Math.round(r.width * dpr));
    cv.height = Math.max(1, Math.round(r.height * dpr));
    var g = cv.getContext('2d');
    g.clearRect(0, 0, cv.width, cv.height);
    var iw = im.naturalWidth || im.width, ih = im.naturalHeight || im.height;
    if (!iw || !ih) return;
    // The whole sheet, because what is being cut away is the point.
    var s = Math.min(cv.width / iw, cv.height / ih) * 0.97;
    var ox = (cv.width - iw * s) / 2, oy = (cv.height - ih * s) / 2;
    g.imageSmoothingEnabled = true;
    g.drawImage(im, ox, oy, iw * s, ih * s);

    var b = mapKeptBox(f, iw, ih);
    if (!b) return;
    var x = ox + b[0] * s, y = oy + b[1] * s;
    var w = (b[2] - b[0]) * s, h = (b[3] - b[1]) * s;
    g.save();
    g.fillStyle = 'rgba(0,0,0,0.55)';
    g.beginPath();
    g.rect(ox, oy, iw * s, ih * s);
    g.rect(x, y, w, h);
    g.fill('evenodd');
    g.restore();
    g.save();
    g.strokeStyle = 'rgba(74,158,255,0.95)';
    g.lineWidth = 2 * dpr;
    g.setLineDash([7 * dpr, 5 * dpr]);
    g.strokeRect(x, y, w, h);
    g.restore();
  }

  window.addEventListener('resize', function () {
    if (!$('prepMap').hidden && map.current) showMapFloor();
  });

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
      var nAdd = (r.wallTypesAdded || []).length, nUpd = (r.wallTypesUpdated || []).length;
      if (failed.walls) bits.push('<b>did not apply the wall types</b>');
      else if (nAdd || nUpd) {
        if (nAdd) bits.push('added <b>' + nAdd + '</b> wall ' + plural(nAdd, 'type'));
        if (nUpd) bits.push('set <b>' + nUpd + '</b> wall ' + plural(nUpd, 'type')
          + ' to the template’s version');
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
  // One summary builder for every path, because there are two report shapes
  // and three renderers, and the shapes are not interchangeable: the download
  // path reads a flat header, the open-from-disk path and the nothing-to-do
  // path get the pipeline's own nested `step` object.
  function summaryOf(r) {
    if (!r.step) return didWhat(r);            // the flat header shape
    var step = r.step;
    return didWhat({
      ran: r.ran,
      failed: r.failed,
      trimmed: (step.trim || {}).trimmedCount,
      floorCount: (step.trim || {}).floorCount,
      areasWritten: (step.areas || {}).floorsWritten,
      areasRetightened: (step.retighten || []).map(function (x) { return x.floorName; }),
      wallTypesAdded: ((step.walls || {}).add || []).map(function (x) { return x.name; }),
      wallTypesUpdated: ((step.walls || {}).update || []).map(function (x) { return x.name; }),
      wallTypesPresent: (step.walls || {}).unchanged || 0,
    });
  }

  // A pass that did two of three things is a success with a gap in it, and the
  // gap has to be as visible as the success - otherwise he opens the project
  // expecting areas that are not there.
  function missedBlock(r) {
    var missed = (r.failed || []).map(function (f) {
      return '<div class="prep-sub">&bull; ' + esc(f.error) + '</div>';
    }).join('');
    return missed ? '<div class="prep-warn" style="margin:8px 0">'
                    + '<b>One part of the pass did not run:</b>' + missed + '</div>' : '';
  }

  // Nothing to write is an outcome, not an absence of one. It used to print a
  // single generic line - "Nothing needed doing" - for all three steps at
  // once, which is the exact shape of "quickwalls not working inside prep":
  // his projects already carry his wall types, because he applies them in
  // Quick Walls first, so the step correctly adds nothing and the page said
  // nothing about it. Every step names itself here too.
  function renderNothingToDo(r, where) {
    return '<div class="prep-done"><b>Nothing needed writing.</b> '
      + summaryOf(r) + '.'
      + missedBlock(r)
      + '<br><span class="prep-sub">' + esc(where) + '</span></div>';
  }

  function renderWritten(r) {
    var host = $('prepResult');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-warn">'
        + esc((r && r.error) || 'Nothing was written.') + '</div>';
      return;
    }
    if (!r.written) {
      host.innerHTML = renderNothingToDo(
        r, 'The project was already prepared, so no copy was made and your '
           + 'original is untouched.');
      return;
    }
    lastWritten = r.path || null;
    var summary = summaryOf(r);
    var missed = missedBlock(r);
    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(r.filename || '') + '</b> — '
      + summary + '.'
      + missed
      + '<br><span class="prep-sub">It is in <b>' + esc(r.dir || '') + '</b>, beside the '
      + 'original, which is unchanged. Open it in Ekahau and start drawing.</span>'
      + '<div class="prep-row" style="margin:10px 0 0">'
      + '<button class="btn btn-sec" data-action="call" data-fn="prepReveal">Show me the file</button>'
      + '</div></div>';
  }

  /* The prepared file is already there. It may be last week's output, or it
     may be the file he opened in Ekahau this morning and has been drawing in -
     nothing in the archive tells them apart, so he does. */
  function confirmReplace(j) {
    $('prepResult').innerHTML = '<div class="prep-warn">' + esc(j.error)
      + '<div class="prep-row" style="margin:10px 0 0">'
      + '<button class="btn btn-primary" data-action="call" data-fn="prepReplace">Replace it</button>'
      + '<button class="btn btn-sec" data-action="call" data-fn="prepReveal">Show me the folder</button>'
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
      host.innerHTML = renderNothingToDo(
        r, 'The project was already prepared, so there was nothing to download '
           + 'and your original is untouched.');
      return;
    }

    var name = (fileName.replace(/\.esx$/i, '') || 'project') + ' (prepared).esx';
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);

    host.innerHTML = '<div class="prep-done">Wrote <b>' + esc(name) + '</b> — '
      + summaryOf(r) + '.'
      + missedBlock(r)
      + '<br><span class="prep-sub">Your original is untouched. Open the downloaded copy '
      + 'in Ekahau and start drawing.</span></div>';
  }

  // ── wiring ─────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    WD.applyVersions();
    loadTemplates();
    loadMargin();
    loadExistingDefault();

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
