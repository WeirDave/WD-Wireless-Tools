/* WD Prep — get a new project ready in one pass.
 *
 * One file, one plan canvas, the stages down the left, one save. Trim the
 * canvas, put the requirement areas in, load the wall types: three errands,
 * three loads and three saves of a file that can run to a couple of hundred
 * megabytes, before a single wall gets drawn. docs/prep-workbench.md is the
 * plan this page is built to.
 *
 * Two things this page deliberately does not do.
 *
 * It does not decide the order the steps run in. The steps go to the server as
 * a set and come back in the order the pipeline says they have to run in - see
 * tools/prep_pipeline.py, where an area injected before the trim holds the crop
 * open and the trim then reports a tidy skip for a crop it was prevented from
 * making. A page that could set that order is a page that could get it wrong.
 *
 * It does not write to the file you loaded. Preparing builds a new copy, so
 * replacing the original stays a decision made in a file manager rather than
 * one made here. Every control on the page is a decision held until Prepare.
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
  var lastPlan = null;       // the newest preview the server sent
  var wallTemplates = [];
  var capTemplates = [];
  var previewSeq = 0;        // so a slow preview cannot land after a newer one
  var floorOcc = {};         // floorPlanId -> headcount typed for that floor
  var floorExist = {};       // floorPlanId -> keep / devices / reshape for that floor
  var stage = 'trim';        // the stage whose panel and overlay are showing
  var STAGES = ['trim', 'areas', 'walls'];
  // Settings → Capacity → Floors that already have devices. Read only: the
  // dropdown here changes one run and never writes back. A failed read or an
  // unknown value leaves "keep", which changes nothing he set.
  var EXISTING_CHOICES = ['keep', 'devices', 'reshape'];
  var savedExisting = 'keep';

  /* The boxes drawn on the Trim stage, in plan units, per floor.

     They are PlanTrim's boxes: saved under the project's own id in the same
     store, so a box drawn in either tool is the box both use. Until the first
     preview comes back the page does not know them, so it asks the server to
     use whatever is saved (`useBoxes=1`); from then on it sends its own set,
     an empty set meaning every floor is automatic. */
  var trim = { boxes: {}, loaded: false, projectId: '', suggestions: {} };

  /* The capacity template Capacity's "Make default" chose. Prep starts on it
     too, until a template is picked here by hand. */
  var savedCapTemplate = '';
  var capTplTouched = false;

  function selectDefaultCapTemplate() {
    var sel = $('prepCapTpl');
    if (!sel || capTplTouched || !savedCapTemplate) return false;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === savedCapTemplate) {
        if (sel.value === savedCapTemplate) return false;
        sel.value = savedCapTemplate;
        return true;
      }
    }
    return false;
  }

  function loadExistingDefault() {
    return WD.api('settings/get').then(function (r) {
      var cap = (r && r.settings && r.settings.capacity) || {};
      var v = cap.existing_devices;
      if (EXISTING_CHOICES.indexOf(v) >= 0) savedExisting = v;
      if (typeof cap.default_template === 'string') savedCapTemplate = cap.default_template;
    }).catch(function () { /* keep the shipped default */ }).then(function () {
      if ($('prepExisting')) $('prepExisting').value = savedExisting;
      if (selectDefaultCapTemplate()) syncStepUi();
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

  // "Normal, 10 ft" for the rail, out of the option's own label so the two
  // cannot say different things.
  function marginWords() {
    var sel = $('prepMargin');
    if (!sel) return '';
    if (sel.value === 'custom') return ($('prepMarginFt').value || '') + ' ft';
    var opt = sel.options && sel.options[sel.selectedIndex];
    var label = String((opt && opt.text) || sel.value || '');
    var m = /^(.*?)\s+—\s+([0-9.]+ ft)/.exec(label);
    return m ? m[1] + ', ' + m[2] : label;
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
      // Coming back from Quick Walls or Capacity reloads the lists, and what
      // he had picked stays picked while it still exists.
      var keepWall = $('prepWallTpl').value;
      var keepCap = $('prepCapTpl').value;
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
      var stillThere = wallTemplates.filter(function (t) { return t.file === keepWall; })[0];
      if (stillThere) chosen = stillThere;
      $('prepWallTpl').innerHTML = wallTemplates.length
        ? wallTemplates.map(function (t) {
            var sel = (chosen && t.file === chosen.file) ? ' selected' : '';
            return '<option value="' + escAttr(t.file) + '"' + sel + '>'
              + esc(WD.wallTemplateLabel(t)) + '</option>';
          }).join('')
        : '<option value="">No wall templates saved yet</option>';

      $('prepCapTpl').innerHTML = capTemplates.length
        ? capTemplates.map(function (t) {
            var want = capTplTouched ? keepCap : (savedCapTemplate || keepCap);
            var sel = t._file === want ? ' selected' : '';
            return '<option value="' + escAttr(t._file) + '"' + sel + '>' + esc(t.name) + '</option>';
          }).join('')
        : '<option value="">No capacity templates saved yet</option>';

      // A step with nothing to work from is switched off and says so, rather
      // than being offered and then refused by the server.
      if (!wallTemplates.length) disableStep('walls', 'Save one in Quick Walls first.');
      else enableStep('walls');
      if (!capTemplates.length) disableStep('areas', 'Build one in Capacity first.');
      else enableStep('areas');
      syncStepUi();
    }).catch(function () { /* the pickers stay empty; the notes explain */ });
  }

  function disableStep(step, why) {
    var box = $('prepStep-' + step);
    box.checked = false;
    box.disabled = true;
    $('prepNote-' + step).textContent = why;
  }

  // A template saved since - captured on the Areas stage, or in another tab -
  // gives a switched-off step something to work from again.
  function enableStep(step) {
    var box = $('prepStep-' + step);
    if (!box.disabled) return;
    box.disabled = false;
    box.checked = true;
    $('prepNote-' + step).textContent = '';
  }

  // ── file in ────────────────────────────────────────────────────────────────

  window.prepLoadNewFile = function () { $('fileInput').click(); };

  function openEditor(name) {
    fileName = name;
    floorOcc = {};             // floors belong to one project
    floorExist = {};
    trim = { boxes: {}, loaded: false, projectId: '', suggestions: {} };
    lastPlan = null;
    if ($('prepExisting')) $('prepExisting').value = savedExisting;
    $('dropzone').style.display = 'none';
    $('editor').classList.add('active');
    $('fileBadge').textContent = name;
    $('fileBadge').title = name;
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
      q += trim.loaded
        ? '&boxes=' + encodeURIComponent(JSON.stringify(trim.boxes))
        : '&useBoxes=1';
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
      if (Object.keys(floorExist).length) {
        q += '&floorExisting=' + encodeURIComponent(JSON.stringify(floorExist));
      }
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

  // The dropdown above covers every floor that has devices; choosing it
  // again resets any floor set on its own, the same as Capacity.
  window.prepExistingAll = function () {
    floorExist = {};
    preview();
  };

  window.prepFloorExisting = function (floorId, value) {
    if (EXISTING_CHOICES.indexOf(value) < 0) return;
    if (value === $('prepExisting').value) delete floorExist[floorId];
    else floorExist[floorId] = value;
    preview();
  };

  // Only a floor that already carries devices has anything to choose.
  function floorExistingHtml(f, i) {
    if (f.mode !== 'replace') return '';
    var id = 'prepFloorExist' + i;
    var cur = f.existingChoice || 'keep';
    var opts = [['keep', 'Keep them'], ['devices', 'Replace devices, keep outline'],
                ['reshape', 'Replace devices, redraw outline']];
    return '<br><span class="prep-floor-people">'
      + '<label for="' + id + '">This floor</label> '
      + '<select id="' + id + '" class="prep-input prep-input--sel" data-action-change="call"'
      + ' data-fn="prepFloorExisting" data-arg="' + escAttr(f.floorPlanId) + '"'
      + ' data-arg-value="1">'
      + opts.map(function (o) {
          return '<option value="' + o[0] + '"' + (o[0] === cur ? ' selected' : '') + '>'
            + o[1] + '</option>';
        }).join('')
      + '</select> <span class="prep-sub">already has ' + (f.existingDevices || 0) + ' '
      + plural(f.existingDevices || 0, 'device') + '</span></span>';
  }

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

  // A stage left out stays on the rail, dimmed and still openable: its
  // settings are where he goes to decide whether he wants it back.
  function syncStepUi() {
    ['trim', 'areas', 'walls'].forEach(function (s) {
      var card = $('prepStageCard-' + s);
      if (card && card.classList) card.classList.toggle('is-off', !$('prepStep-' + s).checked);
    });
    preview();
  }

  function loaded() { return fromDisk || !!fileBytes; }

  function preview() {
    if (!loaded()) return;
    var steps = chosenSteps();
    if (!steps.length) {
      $('prepPreview').innerHTML =
        '<div class="prep-empty">Pick at least one stage to run.</div>';
      setGo(false, 'Nothing is ticked, so there is nothing to write.');
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

  // One floor's line in the Trim panel's "All floors" list.
  function trimFloorLine(f) {
    var name = '<b>' + esc(f.name) + '</b>';
    var mine = f.source === 'manual' ? ' <span class="prep-badge prep-badge--do">your box</span>' : '';
    if (f.action !== 'trimmed' && f.repaired) {
      return name + ' — <span class="prep-sub">trimmed by an earlier version and lost the '
        + 'white page behind the drawing; it is put back</span>' + clearanceLine(f);
    }
    if (f.action === 'trimmed') {
      return name + mine + ' — ' + f.oldSize[0] + '×' + f.oldSize[1]
        + ' → ' + f.newSize[0] + '×' + f.newSize[1]
        + ' <span class="prep-sub">(' + f.areaSavedPct + '% of the sheet was empty)</span>'
        + clearanceLine(f);
    }
    return name + ' — <span class="prep-sub">'
      + esc(f.action + (f.reason ? ': ' + f.reason : '')) + '</span>'
      + clearanceLine(f);
  }

  /* Everything the preview decides, in one place: the rail's status lines,
     each stage's panel, the plan's floor strip and overlay, and the footer.

     A step that cannot run used to stop the whole prepare, so the button was
     disabled whenever one refused. It does not any more: the steps that can
     run do, and the refusal is reported. What the button must not offer is a
     run where *nothing* can happen. */
  function renderPreview(r) {
    var host = $('prepPreview');
    if (!r || !r.ok) {
      host.innerHTML = '<div class="prep-empty">'
        + esc((r && r.error) || 'Could not read that project.') + '</div>';
      setGo(false, '');
      return;
    }
    lastPlan = r;
    host.innerHTML = '';

    // The boxes the server used, the first time: after that the page's own
    // set is the one that counts, and it is the one it sends.
    var proj = r.project || {};
    if (!trim.loaded && proj.boxes) {
      trim.boxes = {};
      Object.keys(proj.boxes).forEach(function (id) { trim.boxes[id] = proj.boxes[id].slice(0, 4); });
      trim.loaded = true;
    }
    if (proj.projectId) trim.projectId = proj.projectId;

    var order = r.steps || [];
    var willDo = 0;
    var writes = [];
    var refused = [];

    // ── trim ──
    var t = order.indexOf('trim') >= 0 ? ((r.step && r.step.trim) || {}) : null;
    if (!t) {
      setStatus('trim', 'Not included', 'is-off');
      $('prepTrimFloors').innerHTML = '<div class="prep-empty">Tick the stage to crop the sheets.</div>';
    } else if (t.error) {
      setStatus('trim', 'Cannot run: ' + t.error, 'is-bad');
      $('prepTrimFloors').innerHTML = '<div class="prep-warn">' + esc(t.error) + '</div>';
      refused.push('the trim');
    } else {
      var n = t.trimmedCount || 0;
      var fixed = t.repairedCount || 0;
      var mine = (t.floors || []).filter(function (f) {
        return f.action === 'trimmed' && f.source === 'manual';
      }).length;
      willDo += n + fixed;
      var bits = [n + ' of ' + (t.floorCount || 0) + ' ' + plural(t.floorCount || 0, 'floor') + ' cropped',
                  marginWords()];
      if (mine) bits.push(mine + ' your ' + plural(mine, 'box', 'boxes'));
      if (fixed) bits.push(fixed + ' to repair');
      setStatus('trim', bits.join(' · '), (n || fixed) ? 'is-do' : '');
      if (n) writes.push('trim ' + n + ' ' + plural(n, 'floor'));
      if (fixed) writes.push('repair ' + fixed + ' ' + plural(fixed, 'plan'));
      var lines = (t.floors || []).map(trimFloorLine);
      $('prepTrimFloors').innerHTML = lines.length
        ? lines.map(function (l) { return '<div class="pb-item">' + l + '</div>'; }).join('')
        : '<div class="prep-empty">No floor plans in this project.</div>';
    }

    // ── areas ──
    var a = order.indexOf('areas') >= 0 ? ((r.step && r.step.areas) || {}) : null;
    if (!a) {
      setStatus('areas', 'Not included', 'is-off');
      $('prepAreaFloors').innerHTML = '<div class="prep-empty">Tick the stage to put a requirement area on each floor.</div>';
    } else if (!a.ok) {
      // The other steps still run. Saying so matters: the reader is looking
      // at a reason, and needs to know whether it costs them the whole pass
      // or just this part of it.
      setStatus('areas', 'Cannot run: ' + (a.error || 'could not work out the areas'), 'is-bad');
      $('prepAreaFloors').innerHTML = '<div class="prep-warn">'
        + esc(a.error || 'Could not work out the requirement areas.')
        + '<br><span class="prep-sub">The other stages still run and the file is still '
        + 'written — this part of it is what will be missing. Fix the project in Ekahau '
        + 'and prepare it again to add the areas.</span></div>';
      refused.push('the requirement areas');
    } else {
      willDo += a.willWrite || 0;
      var nFloors = (a.floors || []).length;
      var people = a.occupantsWritten != null ? a.occupantsWritten : a.occupants;
      setStatus('areas', [
        (a.willWrite || 0) + ' of ' + nFloors + ' ' + plural(nFloors, 'floor'),
        selectedText('prepCapTpl'),
        (people || 0) + ' ' + plural(people || 0, 'person', 'people'),
      ].join(' · '), a.willWrite ? 'is-do' : '');
      if (a.willWrite) writes.push('requirement areas on ' + a.willWrite + ' ' + plural(a.willWrite, 'floor'));
      var rows = (a.floors || []).map(function (f, i) {
        var size = f.widthFt
          ? ' <span class="prep-sub">(' + f.widthFt + ' × ' + f.heightFt + ' ft, from the '
            + esc(f.basis) + ')</span>'
          : '';
        return '<div class="pb-item"><b>' + esc(f.floorName || f.floorPlanId) + '</b> — '
          + esc(f.action) + size + '<br>' + floorPeopleHtml(f, i) + floorExistingHtml(f, i)
          + '</div>';
      });
      rows.push('<p class="pb-hint">' + (a.willWrite
        ? (a.devicesWritten != null ? a.devicesWritten : a.totalDevices) + ' devices for '
          + people + ' people across the floors being written.'
        : 'No floor is being written.')
        + (a.measuredBeforeTrim ? ' Sizes are measured on the plan as it is now; the trim '
          + 'runs first, so they are measured again on the cropped canvas when you prepare.' : '')
        + '</p>');
      $('prepAreaFloors').innerHTML = rows.join('');
    }

    // ── walls ──
    var w = order.indexOf('walls') >= 0 ? ((r.step && r.step.walls) || {}) : null;
    if (!w) {
      setStatus('walls', 'Not included', 'is-off');
      $('prepWallList').innerHTML = '<div class="prep-empty">Tick the stage to load a wall template.</div>';
    } else if (w.error) {
      setStatus('walls', 'Cannot run: ' + w.error, 'is-bad');
      $('prepWallList').innerHTML = '<div class="prep-warn">' + esc(w.error) + '</div>';
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
      setStatus('walls', selectedText('prepWallTpl') + ' · ' + (todo
        ? [add.length ? add.length + ' to add' : '', upd.length ? upd.length + ' to update' : '']
            .filter(Boolean).join(', ')
        : 'already in the project'), todo ? 'is-do' : '');
      var wb = [];
      if (add.length) wb.push(add.length + ' wall ' + plural(add.length, 'type') + ' added');
      if (upd.length) wb.push(upd.length + ' updated');
      if (wb.length) writes.push(wb.join(', '));
      // Chips, not a comma-joined list. Half the shipped names have a comma
      // in them - "Door, Hollow Wood", "Wall, Cinder Block" - so joining on
      // commas produces a run of words with no way to tell where one type
      // ends and the next begins.
      var wl = [];
      if (add.length) wl.push('<div class="pb-item"><b>Adding</b><br>' + chips(add) + '</div>');
      if (upd.length) {
        wl.push('<div class="pb-item"><b>Setting to the template’s version</b><br>' + chips(upd)
          + '<br><span class="prep-sub">Types the project already has, given the template’s '
          + 'colour, number key and attenuation. Walls drawn with them stay on them.</span></div>');
      }
      if (!todo) {
        wl.push('<div class="pb-item prep-sub">Every type in this template is already here, '
          + 'exactly as the template has it.</div>');
      } else if (w.unchanged) {
        wl.push('<div class="pb-item prep-sub">' + w.unchanged + ' already match the template.</div>');
      }
      if (skip.length) {
        wl.push('<div class="pb-item prep-sub">Not applied: ' + skip.map(function (x) {
          return esc(x.name + ' (' + x.why + ')');
        }).join('; ') + '</div>');
      }
      $('prepWallList').innerHTML = wl.join('');
    }

    renderMap(r);
    syncTrimControls();

    if (willDo) {
      setGo(true, '<b>Will write:</b> ' + esc(writes.join(' · ')) + '. '
        + (refused.length
          ? esc('Without ' + refused.join(' or ') + ' — that part cannot run on this project. ')
          : '')
        + esc(fromDisk ? 'A new copy is written beside the original.'
                       : 'A new copy is downloaded; your file is not touched.'));
    } else if (refused.length) {
      setGo(false, esc('Nothing can run on this project: ' + refused.join(' and ')
                     + ' cannot, and there is nothing else left to do.'));
    } else {
      setGo(false, 'This project is already prepared — there is nothing left to do.');
    }
  }

  function selectedText(id) {
    var sel = $(id);
    var opt = sel && sel.options && sel.options[sel.selectedIndex];
    return String((opt && opt.text) || (sel && sel.value) || '');
  }

  /* A step that cannot run says so on the rail in one line; the reason, which
     can run to a paragraph naming every missing profile, is in the step's own
     panel. Written whole on the rail it was a column of red text that pushed
     the other steps off the screen. */
  function setStatus(step, text, cls) {
    var el = $('prepStatus-' + step);
    if (!el) return;
    var bad = cls === 'is-bad';
    var long = bad && String(text).length > 90;
    el.textContent = long ? 'Cannot run \u2014 select this step to read why' : text;
    if ('title' in el) el.title = long ? String(text) : '';
    el.className = 'pb-stage-status' + (cls ? ' ' + cls : '');
    var reason = $('prepReason-' + step);
    if (reason) {
      reason.hidden = !bad;
      reason.textContent = bad ? String(text) : '';
    }
  }

  // The footer's note is markup the renderer built from escaped parts.
  function setGo(on, note) {
    $('prepGoBtn').disabled = !on;
    $('prepGoNote').innerHTML = note || '';
  }

  // ── stages ─────────────────────────────────────────────────────────────────

  window.prepStage = function (name) {
    if (STAGES.indexOf(name) < 0) return;
    stage = name;
    STAGES.forEach(function (s) {
      var panel = $('prepPanel-' + s);
      if (panel) panel.hidden = s !== name;
      var card = $('prepStageCard-' + s);
      if (card && card.classList) card.classList.toggle('is-current', s === name);
    });
    if (lastPlan) renderMap(lastPlan);
    syncTrimControls();
  };

  // ── the plan: one canvas for every stage ───────────────────────────────────
  //
  // The suite's shared plan canvas (WD.PlanView), so it zooms and pans the way
  // PlanTrim does and draws the plan on the same white page. What is drawn over
  // the plan follows the stage: the crop box and its handles on Trim, the
  // requirement area on Areas, and the cropped sheet as it will come out on
  // the others. Everything drawn comes out of the preview the panels are
  // quoting, so the picture and the numbers cannot disagree. WD.ProjectFile
  // fetches the floor images: from the dropped file with JSZip, or one floor at
  // a time from /api/prep/image when the project was opened from disk and is
  // deliberately not in the browser.

  var map = { floors: [], current: null, file: null, view: null, editor: null };

  function resetMap() {
    map.floors = [];
    map.current = null;
    map.file = null;
    if (map.view) map.view.setImage(null);
    var empty = $('prepMapEmpty');
    if (empty) { empty.hidden = false; empty.textContent = 'Reading the project…'; }
  }

  function mapFile() {
    if (!map.file) {
      map.file = fromDisk
        ? WD.ProjectFile.fromServer(function (id) {
            return '/api/prep/image?floor=' + encodeURIComponent(id);
          })
        : WD.ProjectFile.fromBytes(fileBytes);
    }
    return map.file;
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

  // What the trim does to one floor, for its button in the strip.
  function mapFloorState(f) {
    if (!f) return { cls: 'is-pending', word: '', detail: '' };
    if (f.action === 'trimmed') {
      return { cls: f.source === 'manual' ? 'is-manual' : 'is-auto',
               word: f.source === 'manual' ? 'Your box' : 'Trim',
               detail: '−' + f.areaSavedPct + '%' };
    }
    if (f.repaired) {
      return { cls: 'is-auto', word: 'Repair', detail: 'white page restored' };
    }
    if (f.action === 'skipped') return { cls: 'is-skip', word: 'Leave as is', detail: f.reason || '' };
    return { cls: 'is-refused', word: 'Refused', detail: f.reason || '' };
  }

  // What the areas step does to one floor, for its button in the strip.
  function areaFloorState(f) {
    if (!f) return { cls: 'is-pending', word: '', detail: '' };
    if (f.mode === 'none') return { cls: 'is-skip', word: 'nobody', detail: '' };
    if (f.skipped) {
      return { cls: 'is-skip', word: 'keeps ' + (f.existingDevices || 0) + ' '
               + plural(f.existingDevices || 0, 'device'), detail: '' };
    }
    var n = f.occupants || 0;
    return { cls: 'is-auto', word: n + ' ' + plural(n, 'person', 'people'),
             detail: (f.totalDevices || 0) + ' ' + plural(f.totalDevices || 0, 'device') };
  }

  function byId(list, key, id) {
    return (list || []).filter(function (x) { return x && x[key] === id; })[0] || null;
  }

  function trimFloor(id) {
    var t = lastPlan && lastPlan.step && lastPlan.step.trim;
    return byId(t && t.floors, 'id', id);
  }

  function areaFloor(id) {
    var a = lastPlan && lastPlan.step && lastPlan.step.areas;
    return byId(a && a.ok && a.floors, 'floorPlanId', id);
  }

  // The project's floors, from the facts the server sent and failing those
  // from whichever step listed them.
  function planFloors(r) {
    var proj = (r && r.project) || {};
    if (proj.floors && proj.floors.length) return proj.floors;
    var t = r && r.step && r.step.trim;
    if (t && t.floors && t.floors.length) {
      return t.floors.map(function (f) {
        return { id: f.id, name: f.name,
                 w: f.oldSize ? f.oldSize[0] : 0, h: f.oldSize ? f.oldSize[1] : 0 };
      });
    }
    var a = r && r.step && r.step.areas;
    return ((a && a.floors) || []).map(function (f) {
      return { id: f.floorPlanId, name: f.floorName || f.floorPlanId, w: 0, h: 0 };
    });
  }

  function renderMap(r) {
    var floors = planFloors(r);
    map.floors = floors;
    if (!floors.length) {
      $('prepMapStrip').innerHTML = '';
      var empty = $('prepMapEmpty');
      if (empty) { empty.hidden = false; empty.textContent = 'This project has no floor plans.'; }
      return;
    }
    var ids = floors.map(function (f) { return f.id; });
    if (ids.indexOf(map.current) < 0) {
      // Open on the first floor that is actually being cropped.
      var first = floors.filter(function (f) {
        var tf = trimFloor(f.id);
        return tf && tf.action === 'trimmed';
      })[0] || floors[0];
      map.current = first.id;
    }
    $('prepMapStrip').innerHTML = floors.map(function (f) {
      var st = stage === 'areas' ? areaFloorState(areaFloor(f.id)) : mapFloorState(trimFloor(f.id));
      return '<button type="button" class="pb-floor ' + st.cls
        + (f.id === map.current ? ' is-current' : '') + '"'
        + ' data-action="call" data-fn="prepMapSelect" data-arg="' + escAttr(f.id) + '"'
        + (st.detail ? ' title="' + escAttr(st.detail) + '"' : '') + '>'
        + '<span class="pb-floor-name">' + esc(f.name) + '</span>'
        + (st.word ? ' <span class="pb-floor-state">' + esc(st.word) + '</span>' : '')
        + '</button>';
    }).join('');
    showMapFloor();
  }

  window.prepMapSelect = function (id) {
    map.current = id;
    var strip = $('prepMapStrip');
    Array.prototype.forEach.call((strip && strip.children) || [], function (b) {
      b.classList.toggle('is-current', b.getAttribute('data-arg') === id);
    });
    showMapFloor();
    syncTrimControls();
  };

  function currentMapFloor() {
    return map.floors.filter(function (f) { return f.id === map.current; })[0] || null;
  }

  function showMapFloor() {
    var f = currentMapFloor();
    if (!f) return;
    captionFor(f);
    if (!WD.PlanView || !WD.ProjectFile) return;
    var id = f.id;
    var empty = $('prepMapEmpty');
    var file = mapFile();
    file.image(id).then(function (im) {
      if (map.current !== id || map.file !== file) return;
      empty.hidden = true;
      var pv = mapView();
      // The same floor again - a new preview, a changed margin - keeps the
      // view where he put it. Only another floor is framed afresh.
      if (pv.img === im) pv.draw();
      else pv.setImage(im);
      zoomReadout();
    }, function (e) {
      if (map.current !== id || map.file !== file) return;
      mapView().setImage(null);
      empty.hidden = false;
      empty.textContent = e.message || 'This floor plan could not be displayed.';
    });
  }

  function captionFor(f) {
    var cap = $('prepMapCaption');
    if (!cap) return;
    if (stage === 'trim' && $('prepStep-trim').checked) {
      cap.textContent = trim.boxes[f.id]
        ? 'Drag a handle or an edge to adjust your box, or drag inside it to move it. '
          + 'Space-drag, middle or right drag pans; the wheel zooms.'
        : 'The dashed line is what automatic keeps. Drag a rectangle to choose your own. '
          + 'Space-drag, middle or right drag pans; the wheel zooms.';
    } else if (stage === 'areas') {
      cap.textContent = 'The requirement area each floor gets, on the plan as it will be '
        + 'cropped. Drag to move the plan; the wheel zooms.';
    } else {
      cap.textContent = 'The sheet as it will come out of the trim. Drag to move the plan; '
        + 'the wheel zooms.';
    }
  }

  // Made on first use rather than at load, so the stage exists and has a size.
  function mapView() {
    if (!map.view) {
      map.editor = WD.BoxEditor.create({
        get: function () { return trim.boxes[map.current] || null; },
        set: function (b) {
          if (b) trim.boxes[map.current] = b;
          else delete trim.boxes[map.current];
        },
        commit: function () {
          delete trim.suggestions[map.current];
          boxesChanged();
        },
        size: function () { return floorSize(map.current); },
        proposed: function () { return autoBox(map.current); },
        enabled: function () { return stage === 'trim' && $('prepStep-trim').checked; },
      });
      map.view = WD.PlanView.create({
        canvas: $('prepMapCanvas'),
        stage: $('prepMapStage'),
        overlay: drawOverlay,
        dragPans: function () { return !(stage === 'trim' && $('prepStep-trim').checked); },
        onDown: function (e, p, pv) { return map.editor.onDown(e, p, pv); },
        onMove: function (e, p, pv, dragging) { map.editor.onMove(e, p, pv, dragging); },
        onUp: function (e, p, pv) { map.editor.onUp(e, p, pv); },
      });
    }
    return map.view;
  }

  // A floor's size in plan units: the space a box is drawn in and the report
  // is written in.
  function floorSize(id) {
    var f = byId(map.floors, 'id', id);
    if (f && f.w && f.h) return { w: f.w, h: f.h };
    var tf = trimFloor(id);
    if (tf && tf.oldSize) return { w: tf.oldSize[0], h: tf.oldSize[1] };
    return null;
  }

  // What automatic keeps on this floor, in plan units, or null.
  function autoBox(id) {
    var f = trimFloor(id);
    if (!f || f.action !== 'trimmed' || f.source === 'manual' || !f.offset || !f.newSize) return null;
    return [f.offset[0], f.offset[1], f.offset[0] + f.newSize[0], f.offset[1] + f.newSize[1]];
  }

  function drawOverlay(g, pv) {
    zoomReadout();
    if (stage === 'trim' && $('prepStep-trim').checked) {
      map.editor.overlay(g, pv);
      return;
    }
    var im = pv.img;
    var s = floorSize(map.current);
    if (!im || !s) return;
    var kx = im.width / s.w, ky = im.height / s.h;
    var dpr = window.devicePixelRatio || 1;
    var tf = $('prepStep-trim').checked ? trimFloor(map.current) : null;
    var kept = drawKept(g, pv, tf);
    var k0 = kept && pv.toScreen(kept[0], kept[1]);
    var k1 = kept && pv.toScreen(kept[2], kept[3]);
    if (stage !== 'areas' || !$('prepStep-areas').checked) return;
    var af = areaFloor(map.current);
    if (!af || af.mode === 'none') return;
    var pts = af.outline || af.polygon || [];
    // An area measured from the whole page is measured again on the cropped
    // page, so on a floor being trimmed it is the kept rectangle.
    var onScreen;
    if (kept && af.outlineIsNew && af.basis === 'canvas') {
      onScreen = [k0, { x: k1.x, y: k0.y }, k1, { x: k0.x, y: k1.y }];
    } else {
      onScreen = pts.map(function (p) { return pv.toScreen(p.x * kx, p.y * ky); });
    }
    if (onScreen.length < 3) return;
    g.save();
    if (kept) {
      g.beginPath();
      g.rect(k0.x, k0.y, k1.x - k0.x, k1.y - k0.y);
      g.clip();
    }
    g.beginPath();
    onScreen.forEach(function (p, i) { if (i) g.lineTo(p.x, p.y); else g.moveTo(p.x, p.y); });
    g.closePath();
    g.fillStyle = af.skipped ? 'rgba(148,163,184,0.18)' : 'rgba(236,72,153,0.18)';
    g.fill();
    g.strokeStyle = af.skipped ? '#94a3b8' : '#db2777';
    g.lineWidth = 2 * dpr;
    if (af.skipped) g.setLineDash([6 * dpr, 4 * dpr]);
    g.stroke();
    g.restore();
    // Labelled in points, not as a fraction of the drawing, so it reads the
    // same at any zoom.
    var st = areaFloorState(af);
    var label = 'Requirement area · ' + st.word + (st.detail ? ' · ' + st.detail : '');
    var x = Math.min.apply(null, onScreen.map(function (p) { return p.x; }));
    var y = Math.min.apply(null, onScreen.map(function (p) { return p.y; }));
    if (kept) { x = Math.max(x, k0.x); y = Math.max(y, k0.y); }
    g.save();
    g.font = (12 * dpr) + 'px system-ui, sans-serif';
    var tw = g.measureText(label).width;
    g.fillStyle = af.skipped ? '#64748b' : '#db2777';
    g.fillRect(x + 8 * dpr, y + 8 * dpr, tw + 14 * dpr, 20 * dpr);
    g.fillStyle = '#ffffff';
    g.textBaseline = 'middle';
    g.fillText(label, x + 15 * dpr, y + 18 * dpr);
    g.restore();
  }

  // The paper the trim takes away, shaded, and the edge of what is kept
  // dashed: the sheet as it will come out, which is what every stage after
  // the trim works on. Returns the kept box in image pixels, or null.
  function drawKept(g, pv, f) {
    var im = pv.img;
    var b = mapKeptBox(f, im && im.width, im && im.height);
    if (!b) return null;
    var dpr = window.devicePixelRatio || 1;
    var s0 = pv.toScreen(0, 0), s1 = pv.toScreen(im.width, im.height);
    var k0 = pv.toScreen(b[0], b[1]), k1 = pv.toScreen(b[2], b[3]);
    g.save();
    g.fillStyle = 'rgba(0,0,0,0.55)';
    g.beginPath();
    g.rect(s0.x, s0.y, s1.x - s0.x, s1.y - s0.y);
    g.rect(k0.x, k0.y, k1.x - k0.x, k1.y - k0.y);
    g.fill('evenodd');
    g.restore();
    g.save();
    g.strokeStyle = 'rgba(74,158,255,0.95)';
    g.lineWidth = 2 * dpr;
    g.setLineDash([7 * dpr, 5 * dpr]);
    g.strokeRect(k0.x, k0.y, k1.x - k0.x, k1.y - k0.y);
    g.restore();
    return b;
  }

  function zoomReadout() {
    var el = $('prepZoomLevel');
    if (!el || !map.view || !map.view.img) { if (el) el.textContent = ''; return; }
    el.textContent = Math.round(map.view.view.scale / (window.devicePixelRatio || 1) * 100) + '%';
  }

  window.prepMapFit = function () {
    if (map.view) map.view.reset();
  };

  window.prepMapZoom = function (dir) {
    var pv = map.view;
    if (!pv || !pv.img) return;
    var k = dir === 'in' ? WD.PlanView.ZOOM_STEP : 1 / WD.PlanView.ZOOM_STEP;
    pv.zoomAt(k, pv.canvas.width / 2, pv.canvas.height / 2);
  };

  // ── the Trim stage: PlanTrim's box editor ──────────────────────────────────

  // Saved where PlanTrim keeps them and previewed again, so the strip, the
  // panel and the footer describe the box he just let go of.
  function boxesChanged() {
    trim.loaded = true;
    if (trim.projectId) {
      WD.api('plantrim/boxes_save', { projectId: trim.projectId, boxes: trim.boxes })
        .catch(function () { /* a lost box is a redraw, not a failure worth a toast */ });
    }
    if (map.view) map.view.draw();
    syncTrimControls();
    preview();
  }

  function syncTrimControls() {
    var f = currentMapFloor();
    var on = !!$('prepStep-trim').checked;
    var b = f && trim.boxes[f.id];
    var tf = f && trimFloor(f.id);
    var title = $('prepTrimTitle');
    if (title) title.textContent = 'Trim' + (f ? ' · ' + f.name : '');
    var lead = $('prepTrimFloor');
    if (lead) {
      lead.textContent = !tf ? ''
        : tf.action === 'trimmed'
          ? tf.oldSize[0] + '×' + tf.oldSize[1] + ' → ' + tf.newSize[0] + '×' + tf.newSize[1]
            + ' · ' + tf.areaSavedPct + '% of the sheet is empty paper.'
          : (tf.repaired ? 'Not cropped again; the white page behind the drawing is put back.'
                         : 'Not cropped' + (tf.reason ? ': ' + tf.reason : '') + '.');
    }
    var same = f ? map.floors.filter(function (x) {
      return x.id !== f.id && x.w === f.w && x.h === f.h;
    }).length : 0;
    setDisabled('prepTrimSuggest', !on || map.floors.length < 1);
    setDisabled('prepTrimDraw', !on || !f);
    setDisabled('prepTrimAll', !on || !b || !same);
    setDisabled('prepTrimAuto', !on || !b);
    var hint = $('prepTrimHint');
    if (hint) {
      hint.textContent = !on ? 'The trim is not ticked, so every sheet is left as it is.'
        : b ? 'Your box keeps ' + Math.round(b[2] - b[0]) + ' × ' + Math.round(b[3] - b[1])
              + ' of this sheet.' + (same ? '' : ' No other floor is the same size, so it '
              + 'cannot be applied to them.')
          : 'Automatic: Prep finds the building and keeps it, with the space above around '
            + 'it - the dashed outline on the plan. To choose for yourself, drag a box on '
            + 'the plan around what to keep.';
    }
    showEvidence();
    if (f) captionFor(f);
  }

  function setDisabled(id, off) {
    var el = $(id);
    if (el) el.disabled = !!off;
  }

  function showEvidence() {
    var el = $('prepTrimEvidence');
    if (!el) return;
    var s = trim.suggestions[map.current];
    if (!s) { el.hidden = true; el.innerHTML = ''; return; }
    var label = s.basis === 'cross-sheet'
      ? 'Proposed from ' + s.sheets + ' sheets of this size'
      : (s.basis === 'single-sheet' ? 'Proposed from this sheet alone'
                                    : 'Nothing could be proposed');
    el.innerHTML = '<span class="ptb-ev-basis"><strong>' + esc(label) + '</strong></span>'
      + esc(s.evidence || '') + ' <em>Check it and drag if it is wrong — nothing is written '
      + 'until you press Prepare.</em>';
    el.hidden = false;
  }

  /* Suggestions are put on the plan, never taken on trust. The rectangle
     lands where it can be seen and dragged and the evidence for it is stated;
     it is used only because he can see it there, and nothing is written until
     Prepare. Detection that cannot be checked is what the box exists to
     escape, so it does not get to act on its own. */
  window.prepTrimSuggest = function () {
    if (!loaded()) return;
    var btn = $('prepTrimSuggest');
    var label = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Comparing sheets…';
    fetch('/api/prep/suggest?name=' + encodeURIComponent(fileName)
          + (fromDisk ? '&source=disk' : ''), {
      method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' },
      body: fromDisk ? null : fileBytes,
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (!res || !res.ok) {
        WD.toast((res && res.error) || 'Could not compare the sheets', 'error');
        return;
      }
      trim.suggestions = {};
      var filled = 0;
      (res.suggestions || []).forEach(function (s) {
        trim.suggestions[s.floorId] = s;
        if (s.box) { trim.boxes[s.floorId] = s.box.slice(0, 4); filled++; }
      });
      if (!filled) {
        WD.toast('Nothing to suggest from this set', 'error');
        showEvidence();
        return;
      }
      WD.toast('Proposed a box on ' + filled + ' ' + plural(filled, 'floor')
               + ' — check it before preparing', 'success');
      boxesChanged();
    }).catch(function () {
      WD.toast('Could not compare the sheets', 'error');
    }).then(function () {
      btn.textContent = label;
      syncTrimControls();
    });
  };

  // Starts from what automatic keeps, with handles on it - adjusting a box
  // that is nearly right is quicker than drawing one from nothing.
  window.prepTrimDraw = function () {
    var id = map.current;
    if (!id) return;
    if (trim.boxes[id]) {
      WD.toast('Drag a handle or an edge to adjust the box', 'success');
      return;
    }
    var auto = autoBox(id);
    var s = floorSize(id);
    if (auto) {
      trim.boxes[id] = auto.slice();
    } else if (s) {
      // Nothing detected to start from: an inset of the whole sheet, so every
      // handle is on the page and in reach.
      trim.boxes[id] = [s.w * 0.1, s.h * 0.1, s.w * 0.9, s.h * 0.9];
    } else {
      return;
    }
    boxesChanged();
  };

  window.prepTrimAuto = function () {
    if (!trim.boxes[map.current]) return;
    delete trim.boxes[map.current];
    delete trim.suggestions[map.current];
    boxesChanged();
  };

  // The same CAD set puts the title block in the same place on every sheet, so
  // the box carries over as-is - but only where the sheet is the same size. On
  // another size the numbers mean another part of the sheet.
  window.prepTrimApplyAll = function () {
    var here = currentMapFloor();
    var b = here && trim.boxes[here.id];
    if (!b) return;
    var applied = 0, skipped = 0;
    map.floors.forEach(function (f) {
      if (f.id === here.id) return;
      if (f.w !== here.w || f.h !== here.h) { skipped++; return; }
      trim.boxes[f.id] = b.slice();
      applied++;
    });
    if (!applied) {
      WD.toast('No other floor is the same size as this one', 'error');
      return;
    }
    WD.toast('Applied to ' + applied + ' ' + plural(applied, 'floor')
             + (skipped ? '; skipped ' + skipped + ' of a different size' : ''), 'success');
    boxesChanged();
  };

  // ── the Areas stage: capture a template without leaving ────────────────────

  var capture = { extracted: null, derived: null };

  window.prepCaptureOpen = function () {
    var input = $('prepCaptureInput');
    input.value = '';
    input.click();
  };

  window.prepCaptureClose = function () {
    $('prepCaptureModal').classList.remove('active');
    capture = { extracted: null, derived: null };
  };

  function captureFile(file) {
    file.arrayBuffer().then(function (buf) {
      return fetch('/api/capacity/analyze?name=' + encodeURIComponent(file.name), {
        method: 'POST', headers: { 'X-WD-Wireless-Tools': '1' }, body: buf,
      });
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r || !r.ok) {
        WD.toast((r && r.error) || 'Could not read that project', 'error');
        return;
      }
      if (!r.rows || !r.rows.length) {
        WD.toast('No capacity items in that project. Set the areas up in Ekahau first, '
                 + 'then capture from it.', 'error');
        return;
      }
      capture.extracted = r;
      $('prepCaptureName').value = file.name.replace(/\.esx(\.zip)?$/i, '');
      $('prepCaptureBody').innerHTML = '<p class="pb-lead">' + esc(file.name) + ': '
        + r.rows.length + ' ' + plural(r.rows.length, 'row') + ', ' + (r.totalDevices || 0)
        + ' ' + plural(r.totalDevices || 0, 'device') + '.</p>';
      $('prepCaptureModal').classList.add('active');
      window.prepCaptureDerive();
    }).catch(function (e) {
      WD.toast('Could not read that project: ' + e.message, 'error');
    });
  }

  window.prepCaptureDerive = function () {
    if (!capture.extracted) return;
    $('prepCaptureSave').disabled = true;
    fetch('/api/capacity/derive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify({ extracted: capture.extracted,
                             occupants: $('prepCapturePeople').value,
                             name: $('prepCaptureName').value }),
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r || !r.ok) {
        capture.derived = null;
        $('prepCaptureDerived').innerHTML = '<div class="prep-warn">'
          + esc((r && r.error) || 'Could not work that out.') + '</div>';
        return;
      }
      capture.derived = r;
      $('prepCaptureDerived').innerHTML = '<p class="pb-hint"><b>'
        + Number(r.devicesPerOccupant || 0).toFixed(2) + '</b> devices per person, across '
        + (r.items || []).length + ' ' + plural((r.items || []).length, 'profile') + '.</p>';
      $('prepCaptureSave').disabled = false;
    });
  };

  window.prepCaptureSave = function () {
    if (!capture.derived) return;
    var body = JSON.parse(JSON.stringify(capture.derived));
    body.name = $('prepCaptureName').value || body.name;
    fetch('/api/capacity/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
      body: JSON.stringify({ template: body }),
    }).then(function (r) { return r.json(); }).then(function (r) {
      if (!r || !r.ok) { WD.toast((r && r.error) || 'Could not save', 'error'); return; }
      WD.toast('Saved "' + body.name + '"', 'success');
      window.prepCaptureClose();
      // Selected by its file, which is how the list names it.
      $('prepCapTpl').value = r.file;
      $('prepCapTpl').innerHTML = '<option value="' + escAttr(r.file) + '" selected>'
        + esc(body.name) + '</option>';
      loadTemplates();
    });
  };

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
      if (!failed.trim && r.repaired) {
        bits.push('put the white page back behind <b>' + r.repaired + '</b> '
          + plural(r.repaired, 'floor plan') + ' an earlier version had trimmed');
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
      repaired: (step.trim || {}).repairedCount || 0,
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
    // A template picked here by hand wins over the saved default for the rest
    // of the visit.
    $('prepCapTpl').addEventListener('change', function () { capTplTouched = true; });

    $('fileInput').addEventListener('change', function (e) {
      if (e.target.files[0]) loadFile(e.target.files[0]);
      e.target.value = '';
    });
    var cap = $('prepCaptureInput');
    if (cap) {
      cap.addEventListener('change', function (e) {
        if (e.target.files[0]) captureFile(e.target.files[0]);
        e.target.value = '';
      });
    }
    // Templates edited in Quick Walls or Capacity - both links open a tab -
    // are picked up on the way back, without reopening the project.
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') loadTemplates();
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
