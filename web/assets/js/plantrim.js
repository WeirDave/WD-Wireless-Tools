/* WD PlanTrim — crop empty canvas off Ekahau floor plans.
 *
 * Drop-in flow, the same shape as Quick Walls and Report: drop an .esx, see
 * what would change, save a new copy. The cropping itself is Python (Pillow),
 * so the bytes go to the local server and come back trimmed. The original file
 * on disk is never touched — you download a new one.
 */
(function () {
  'use strict';

  var state = { file: null, bytes: null, report: null, busy: false };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return WD.esc(s); }
  function toast(m, k) { WD.toast(m, k); }

  function mb(bytes) {
    if (bytes === null || bytes === undefined) return '';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  // The .esx goes up as raw bytes; base64 would inflate a 30 MB survey by a
  // third for no benefit.
  function postEsx(action, bytes, params) {
    var qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return fetch('/api/plantrim/' + action + qs, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-WD-Wireless-Tools': '1'
      },
      body: bytes
    });
  }

  function busy(on, label) {
    state.busy = on;
    var save = $('ptSaveBtn');
    if (save) {
      save.disabled = on || !state.report || !state.report.trimmedCount;
      if (label) save.textContent = label;
    }
    document.body.classList.toggle('pt-busy', on);
  }

  // ---------------------------------------------------------------- dropzone
  var dropzone = $('dropzone');
  var fileInput = $('fileInput');

  dropzone.addEventListener('click', function () { fileInput.click(); });
  dropzone.addEventListener('dragover', function (e) {
    e.preventDefault();
    dropzone.classList.add('dragover');
  });
  dropzone.addEventListener('dragleave', function () { dropzone.classList.remove('dragover'); });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function (e) {
    if (e.target.files.length) loadFile(e.target.files[0]);
  });

  window.ptLoadNewFile = function () {
    fileInput.value = '';
    fileInput.click();
  };

  function loadFile(file) {
    if (!/\.esx$/i.test(file.name)) {
      toast('Not an .esx file', 'error');
      return Promise.resolve();
    }
    state.file = file;
    state.report = null;
    return file.arrayBuffer().then(function (buf) {
      state.bytes = buf;
      dropzone.style.display = 'none';
      $('dzTopbar').style.display = 'none';
      $('editor').classList.add('active');
      $('fileBadge').textContent = file.name;
      return analyze();
    }).catch(function (e) { toast('Could not read that file: ' + e, 'error'); });
  }

  // ----------------------------------------------------------------- analyze
  function analyze() {
    busy(true, 'Reading…');
    $('ptFloors').innerHTML = '<div class="pt-empty">Reading floor plans…</div>';
    $('ptSizeNote').textContent = '';
    $('ptResult').hidden = true;

    return postEsx('analyze', state.bytes, { name: state.file.name })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (!res || !res.ok) {
          $('ptFloors').innerHTML = '<div class="pt-empty pt-bad">' +
            esc((res && res.error) || 'Could not read that project') + '</div>';
          busy(false, 'Save trimmed .esx');
          return;
        }
        state.report = res;
        renderFloors(res);
        busy(false, 'Save trimmed .esx');
      })
      .catch(function (e) {
        $('ptFloors').innerHTML = '<div class="pt-empty pt-bad">' + esc(String(e)) + '</div>';
        busy(false, 'Save trimmed .esx');
      });
  }

  function renderFloors(res) {
    if (!res.floors.length) {
      $('ptFloors').innerHTML = '<div class="pt-empty">This project has no floor plans.</div>';
      return;
    }
    $('ptFloors').innerHTML = res.floors.map(function (f) {
      var right, badge;
      if (f.action === 'trimmed') {
        badge = 'Trim';
        right = '<span class="pt-dims">' + f.oldSize[0] + '&times;' + f.oldSize[1] +
                ' <span class="pt-arrow">&rarr;</span> ' + f.newSize[0] + '&times;' + f.newSize[1] +
                '</span><span class="pt-saved">&minus;' + f.areaSavedPct + '% area</span>';
      } else {
        badge = f.action === 'skipped' ? 'Leave as is' : 'Refused';
        right = '<span class="pt-reason">' + esc(f.reason || f.action) + '</span>';
      }
      return '<div class="pt-floor is-' + f.action + '">' +
               '<span class="pt-badge">' + badge + '</span>' +
               '<span class="pt-floor-name">' + esc(f.name) + '</span>' +
               right +
             '</div>';
    }).join('');

    var n = res.trimmedCount;
    var note = $('ptSizeNote');
    if (!n) {
      note.textContent = 'Nothing to trim here — every floor plan is already tight, or cannot be ' +
                         'cropped safely.';
    } else {
      // Empty canvas already compresses to almost nothing inside the .esx, so
      // say up front that the file size will barely move. Otherwise a correct
      // result reads like the tool did nothing.
      note.innerHTML = n + ' of ' + res.floorCount + ' floor plan' +
        (res.floorCount === 1 ? '' : 's') + ' will be cropped. ' +
        '<strong>The file size will barely change</strong> — empty canvas already compresses to ' +
        'almost nothing. What you gain is a plan that fills its page instead of sitting in one ' +
        'corner of it.';
    }
  }

  // -------------------------------------------------------------------- trim
  window.ptTrim = function () {
    if (state.busy || !state.bytes || !state.report || !state.report.trimmedCount) return;
    busy(true, 'Trimming…');
    $('ptResult').hidden = true;

    var meta = null;
    postEsx('trim', state.bytes, { name: state.file.name })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (j) { throw new Error(j.error || 'Trim failed'); });
        }
        try {
          meta = JSON.parse(decodeURIComponent(r.headers.get('X-PlanTrim-Report') || ''));
        } catch (e) { meta = null; }
        return r.blob();
      })
      .then(function (blob) {
        busy(false, 'Save trimmed .esx');
        var name = state.file.name.replace(/\.esx$/i, '') + ' (trimmed).esx';
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);

        var count = meta ? meta.trimmedCount : state.report.trimmedCount;
        var box = $('ptResult');
        box.hidden = false;
        box.className = 'pt-result pt-good';
        box.innerHTML =
          '<strong>Saved — ' + count + ' floor plan' + (count === 1 ? '' : 's') + ' trimmed.</strong>' +
          '<div class="pt-result-path">' + esc(name) + '</div>' +
          (meta ? '<div class="pt-result-size">' + mb(meta.bytesBefore) + ' &rarr; ' +
                  mb(meta.bytesAfter) + '</div>' : '') +
          '<div class="pt-result-next">Open it in Ekahau to confirm it looks right before using it ' +
          'on real work. Your original file is untouched.</div>';
        toast('Trimmed ' + count + ' floor plan' + (count === 1 ? '' : 's'), 'success');
      })
      .catch(function (e) {
        busy(false, 'Save trimmed .esx');
        var box = $('ptResult');
        box.hidden = false;
        box.className = 'pt-result pt-bad';
        box.textContent = String(e.message || e);
        toast('Trim failed', 'error');
      });
  };

  // Diagnostics hook, same shape as Quick Walls' __wallsSwap.
  window.__plantrim = {
    loadFile: loadFile,
    getState: function () {
      return { name: state.file && state.file.name, busy: state.busy, report: state.report };
    }
  };
})();
