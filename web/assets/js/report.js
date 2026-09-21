(function () {
  'use strict';

  var showToast = WD.toast;
  var M_TO_FT = 3.28084;
  var DEFAULT_REPORT_ID = 'location';

  var esxZip = null;
  var fileName = '';
  /* The "before" project for the Change / Audit report, and the name it came
     from. Null until one is chosen, which is the report's ordinary starting
     state rather than an error - the page says what it needs and offers the
     picker rather than rendering an empty document. Cleared whenever a new
     main project is opened, because a baseline belongs to the comparison it
     was chosen for and silently carrying it across two projects would be a
     comparison nobody asked for. */
  var baseline = null;
  var baselineName = '';
  var baselineError = '';
  // The name of the folder the .esx was opened from, when that is knowable.
  // Empty on a drag-and-drop or on the hosted build - a browser hands over a
  // bare file name and nothing else - so everything downstream treats it as
  // the best available answer rather than a required one.
  var projectFolder = '';
  // Why the folder is not in the name, when it is not: '' once one is
  // known, otherwise the reason locate_project_folder gave back.
  var folderLookup = '';
  var proj = {
    accessPoints: [],
    radios: [],
    antennas: {},
    floorPlans: [],
    buildings: {},
    buildingFloors: {},
    images: {},
    imageUrls: {},
    measurements: [],
    measuredRadios: [],
    surveys: [],
    projectName: '',
  };
  var apDisabled = new Set();
  var currentReportId = DEFAULT_REPORT_ID;
  var currentOpts = {};

  var apGroupBy = 'none';
  var apSearch = '';
  var collapsedGroups = new Set();

  var currentStage = 'template';
  var templateConfirmed = false;
  var configureDirty = true;

  // ── Report settings: organisation defaults, and per-report overrides ───────
  // These belong to the install, not to a browser. The same company, the same
  // person preparing the work and the same cover image go on every report this
  // machine produces, so they live on disk beside the wall templates in
  // ~/.wd_wireless_tools -- outside the install tree, where no update can reach
  // them. Browser storage was the wrong home: it is per-browser and per-profile,
  // so clearing site data or opening Edge instead of Chrome lost the lot.
  var SETTING_IDS = ['clientName', 'preparedBy', 'projectRef', 'revision'];
  // The server speaks snake_case; the option ids are camelCase.
  var SETTING_FIELD = {
    clientName: 'client_name',
    preparedBy: 'prepared_by',
    projectRef: 'project_ref',
    revision: 'revision',
  };
  var LEGACY_DETAILS_KEY = 'wd-report-details';   // pre-2.17 text defaults
  var LEGACY_SETTINGS_KEY = 'wd-report-settings'; // 2.17 text defaults
  var LEGACY_LOGO_KEY = 'wd-report-logo';         // pre-2.17 cover image
  var LEGACY_IDB_NAME = 'wd-report';              // 2.17 cover image

  var reportSettings = {};      // camelCase view of the stored defaults
  var includeRevisionInName = true;
  var optOverrides = {};        // id -> true once this report deliberately differs
  var coverImage = null;        // { url, name, bytes } once one is stored
  var settingsAvailable = false; // false when there is no server behind the page
  // The AP Labeler stores the Structured naming pattern it last used. The
  // label reference page uses it to say what each segment of a name means -
  // and only when a real name actually matches that pattern, so it never
  // guesses at a name that came from somewhere else.
  var labelerPattern = null;
  // Feet or metres. Stored with the rest of the suite settings rather than per
  // report, because it describes how this person works, not this document.
  var unitsPref = 'feet';

  function settingDefault(id) { return reportSettings[id] || ''; }

  function applySettingsPayload(rep) {
    rep = rep || {};
    SETTING_IDS.forEach(function (id) {
      var v = rep[SETTING_FIELD[id]];
      if (typeof v === 'string' && v) reportSettings[id] = v;
      else delete reportSettings[id];
    });
    includeRevisionInName = rep.include_revision_in_filename !== false;
    if (rep.report_defaults && typeof rep.report_defaults === 'object') {
      savedReportDefaults = rep.report_defaults;
      /* Saved options for a retired template are folded into its survivor
         rather than left orphaned - he would otherwise silently lose settings
         he had deliberately saved. Only options the survivor actually has are
         carried, and anything it already has wins. */
      Object.keys(RETIRED_REPORTS).forEach(function (old) {
        var from = savedReportDefaults[old];
        if (!from) return;
        var to = RETIRED_REPORTS[old];
        var survivor = REPORTS[to];
        if (survivor) {
          var known = {};
          (survivor.sidebar || []).forEach(function (o) { known[o.id] = true; });
          savedReportDefaults[to] = savedReportDefaults[to] || {};
          Object.keys(from).forEach(function (k) {
            if (known[k] && !(k in savedReportDefaults[to])) {
              savedReportDefaults[to][k] = from[k];
            }
          });
        }
        delete savedReportDefaults[old];
      });
    }
    // A page turned on purpose should still be turned tomorrow.
    if (rep.page_orient && typeof rep.page_orient === 'object') {
      savedPageOrient = rep.page_orient;
    }
  }
  var savedPageOrient = {};
  /* Sidebar options this person has saved, per report type. Seeded into
     currentOpts when a report is chosen, so the same boxes do not have to be
     ticked on every single report - which is the whole complaint this
     answers. */
  var savedReportDefaults = {};
  function reportOptionDefaults(id) {
    var d = savedReportDefaults && savedReportDefaults[id];
    return (d && typeof d === 'object') ? d : {};
  }

  function fetchSettings() {
    return WD.api('settings/get').then(function (r) {
      if (!r || !r.ok) throw new Error('settings unavailable');
      settingsAvailable = true;
      applySettingsPayload(r.settings && r.settings.report);
      var ar = r.settings && r.settings.aprename;
      labelerPattern = (ar && ar.defaults) || null;
      var u = r.settings && r.settings.report && r.settings.report.units;
      if (u === 'feet' || u === 'meters') unitsPref = u;
      var sg = r.settings && r.settings.report && r.settings.report.segment_granularity;
      if (sg && SEG_GRANULARITY[sg]) segGranularityPref = sg;
      /* The banner is rendered by the template gallery, which paints before
         this fetch comes back, and nothing repainted it afterwards - so it
         read "Not set" for four values that were saved. It was survivable
         while the only way to change them was a modal on this page, because
         saving there repainted it. They are set on the Settings page now, so
         the first thing anyone sees on returning is this banner, and a banner
         saying "Not set" about a value that is set reads as a save that did
         not work. */
      renderSettingsBanner();
    });
  }

  function pushSettings(patch) {
    return WD.api('settings/update', { patch: { report: patch } }).then(function (r) {
      if (!r || !r.ok) throw new Error((r && r.error) || 'could not save settings');
      applySettingsPayload(r.settings && r.settings.report);
      return r;
    });
  }

  // Seeds the fields this report has not deliberately changed, so a settings
  // edit shows up in an open Configure stage.
  function seedSettingDefaults() {
    SETTING_IDS.forEach(function (id) {
      if (!optOverrides[id]) {
        var d = settingDefault(id);
        if (d) currentOpts[id] = d;
        else delete currentOpts[id];
      }
    });
  }

  // ── Cover image ───────────────────────────────────────────────────────────
  var COVER_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif,image/svg+xml';

  function humanBytes(n) {
    if (!(n > 0)) return '0 KB';
    if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + ' KB';
    return (n / (1024 * 1024)).toFixed(1) + ' MB';
  }

  function refreshCoverInfo() {
    return fetch('/api/report/cover/info', { headers: { 'X-WD-Wireless-Tools': '1' } })
      .then(function (r) { return r.json(); })
      .then(function (info) {
        coverImage = (info && info.exists)
          // The version token is the file's mtime, so a replacement is fetched
          // rather than served from cache.
          ? { url: '/api/report/cover?v=' + info.version, name: info.name, bytes: info.bytes }
          : null;
        return coverImage;
      })
      .catch(function () { coverImage = null; return null; });
  }

  function uploadCover(file) {
    var fd = new FormData();
    fd.append('file', file, file.name || 'cover');
    return fetch('/api/report/cover', {
      method: 'POST',
      headers: { 'X-WD-Wireless-Tools': '1' },
      body: fd,
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok || !body || !body.ok) {
          throw new Error((body && body.error) || 'The image could not be saved.');
        }
        return body;
      });
    });
  }

  function deleteCover() {
    return fetch('/api/report/cover', {
      method: 'DELETE',
      headers: { 'X-WD-Wireless-Tools': '1' },
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok || !body || !body.ok) throw new Error((body && body.error) || 'Could not remove the image.');
        return body;
      });
    });
  }

  // ── Migration off browser storage ─────────────────────────────────────────
  // Two earlier homes to clear: the pre-2.17 localStorage keys and the 2.17
  // IndexedDB blob. Anything already typed or uploaded moves to disk once, then
  // the old copies go so they cannot come back and shadow the real settings.
  function readLegacyText() {
    var out = {};
    [LEGACY_SETTINGS_KEY, LEGACY_DETAILS_KEY].forEach(function (key) {
      var raw = null;
      try { raw = localStorage.getItem(key); } catch (e) {}
      if (!raw) return;
      try {
        var parsed = JSON.parse(raw);
        SETTING_IDS.forEach(function (id) {
          if (!out[id] && typeof parsed[id] === 'string' && parsed[id]) out[id] = parsed[id];
        });
      } catch (e) {}
    });
    return out;
  }

  function clearLegacyText() {
    [LEGACY_SETTINGS_KEY, LEGACY_DETAILS_KEY].forEach(function (k) {
      try { localStorage.removeItem(k); } catch (e) {}
    });
  }

  function readLegacyIdbCover() {
    if (!window.indexedDB) return Promise.resolve(null);
    // Opening by name creates the database when it does not exist, which would
    // leave an empty one behind on every install that never ran 2.17 -- and an
    // empty database at version 1 then blocks a real one being made later. Ask
    // first where the browser can say.
    var known = indexedDB.databases
      ? indexedDB.databases().catch(function () { return null; })
      : Promise.resolve(null);
    return known.then(function (list) {
      if (list && !list.some(function (d) { return d.name === LEGACY_IDB_NAME; })) return null;
      return new Promise(function (resolve) {
        var rq;
        try { rq = indexedDB.open(LEGACY_IDB_NAME); } catch (e) { resolve(null); return; }
        rq.onerror = function () { resolve(null); };
        rq.onsuccess = function () {
          var db = rq.result;
          if (!db.objectStoreNames.contains('assets')) { db.close(); dropLegacyIdb(); resolve(null); return; }
          try {
            var g = db.transaction('assets', 'readonly').objectStore('assets').get('coverImage');
            g.onsuccess = function () { db.close(); resolve(g.result || null); };
            g.onerror = function () { db.close(); resolve(null); };
          } catch (e) { db.close(); resolve(null); }
        };
      });
    });
  }

  function dropLegacyIdb() {
    try { indexedDB.deleteDatabase(LEGACY_IDB_NAME); } catch (e) {}
  }

  function dataUrlToBlob(dataUrl) {
    try {
      var parts = String(dataUrl).split(',');
      var meta = parts[0] || '';
      var type = (meta.match(/data:([^;]+)/) || [])[1] || 'image/png';
      if (meta.indexOf('base64') === -1) return null;
      var bin = atob(parts[1] || '');
      var arr = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      return new Blob([arr], { type: type });
    } catch (e) { return null; }
  }

  function migrateBrowserStorage() {
    var text = readLegacyText();
    var chain = Promise.resolve();
    if (Object.keys(text).length) {
      // Only fills gaps: whatever is already on disk wins.
      var patch = {};
      SETTING_IDS.forEach(function (id) {
        if (text[id] && !settingDefault(id)) patch[SETTING_FIELD[id]] = text[id];
      });
      chain = Object.keys(patch).length ? pushSettings(patch) : chain;
      chain = chain.then(clearLegacyText, clearLegacyText);
    }
    return chain.then(function () {
      if (coverImage) { dropLegacyIdb(); return null; }   // disk already has one
      return readLegacyIdbCover().then(function (rec) {
        if (rec && rec.blob) {
          return uploadCover(new File([rec.blob], rec.name || 'cover', { type: rec.type || rec.blob.type }))
            .then(function () { dropLegacyIdb(); });
        }
        var legacy = null;
        try { legacy = localStorage.getItem(LEGACY_LOGO_KEY); } catch (e) {}
        if (!legacy) return null;
        var blob = dataUrlToBlob(legacy);
        if (!blob) { try { localStorage.removeItem(LEGACY_LOGO_KEY); } catch (e) {} return null; }
        return uploadCover(new File([blob], 'cover', { type: blob.type }))
          .then(function () { try { localStorage.removeItem(LEGACY_LOGO_KEY); } catch (e) {} });
      }).then(refreshCoverInfo);
    }).catch(function () { /* a failed migration must not block the tool */ });
  }

  /* Settings are changed in a panel over this page now, so this page is still
     here when they change - and has to notice. Without this he changes the
     units, closes the panel, and the report he is configuring still renders in
     the unit he just stopped using, which is worse than the navigation the
     panel replaced: at least a reload picked the new value up.

     Everything here is a re-read and a repaint. The project, the stage and any
     option he set for this report are untouched. */
  if (window.WD && WD.onSettingsChanged) {
    WD.onSettingsChanged(function () {
      return fetchSettings().then(function () {
        seedSettingDefaults();     // options inheriting a default, not overridden
        configureDirty = true;     // the preview is rebuilt from the new values
        renderReportOpts();
        renderSettingsBanner();
        renderFilenamePreview();
      }).catch(function () { /* the tool keeps the values it already had */ });
    });
  }

  function initReportSettings() {
    return fetchSettings()
      .then(refreshCoverInfo)
      .then(migrateBrowserStorage)
      .catch(function () {
        // No server behind this page: the tool still works, the panel says why.
        settingsAvailable = false;
      })
      .then(function () {
        if (typeof renderReportOpts === 'function') renderReportOpts();
        renderCoverSummary();
      });
  }

  // ── Settings panel ────────────────────────────────────────────────────────
  function renderCoverSummary() {
    var host = document.getElementById('coverSummary');
    if (host) {
      host.innerHTML = coverImage
        ? '<img class="rep-cover-thumb" src="' + WD.escAttr(coverImage.url) + '" alt="Cover image">'
          + '<span class="rep-cover-thumb-meta">' + WD.esc(coverImage.name)
          + ' · ' + humanBytes(coverImage.bytes) + '</span>'
        : '<span class="rep-cover-thumb-empty">No cover image set</span>';
    }
    var prev = document.getElementById('setCoverPreview');
    if (prev) {
      prev.innerHTML = coverImage
        ? '<img src="' + WD.escAttr(coverImage.url) + '" alt="Cover image">'
        : '<span class="rep-cover-thumb-empty">No cover image set</span>';
    }
    var meta = document.getElementById('setCoverMeta');
    if (meta) {
      meta.textContent = coverImage
        ? coverImage.name + ' · ' + humanBytes(coverImage.bytes)
        : 'PNG, JPEG, WebP, GIF or SVG, up to 25 MB. Stored with your wall templates.';
    }
    var rm = document.getElementById('setCoverRemove');
    if (rm) rm.hidden = !coverImage;
  }

  function setCoverStatus(msg, kind) {
    var el = document.getElementById('setCoverStatus');
    if (!el) return;
    el.textContent = msg || '';
    el.className = 'rep-set-status' + (kind ? ' is-' + kind : '');
    el.hidden = !msg;
  }

  // ── Saved filename ────────────────────────────────────────────────────────
  // Windows and macOS both refuse a handful of characters outright, and a
  // trailing dot or space is silently dropped by Explorer, so the pieces are
  // cleaned before they are joined rather than after.
  function fileSafe(part) {
    return String(part == null ? '' : part)
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, ' ')
      .replace(/\s+/g, ' ')
      .replace(/^[\s.]+|[\s.]+$/g, '')
      .trim();
  }

  /* Report - <report name> - <site> - [<revision>].

     The site follows the report name directly. That is the whole point of the
     name and it took three asks to arrive: the revision used to sit third, so
     typing one pushed the site away from the name it is supposed to follow,
     and the .esx stem used to be appended after the folder so the name ran on
     past the site into a repeat of most of it. The revision is a suffix on a
     finished name now, and the folder is the whole site.

     "Report" leads, and it is deliberate rather than left over. v2.140.0 took
     it off, reading "the report name and then a dash and then the folder" as
     the whole name; asked directly, he wants it kept - it says what the file
     is before it says which report, which is the clarification someone handed
     the PDF needs. It also matches how Ekahau names its own, which is where
     the convention came from in the first place (v1.7.1).

     Empty pieces drop out entirely, so turning the revision off - or leaving
     it blank - leaves no dangling separator behind. */
  function buildDocTitle(docName, revision, siteLabel, withRevision) {
    return ['Report', docName, siteLabel, withRevision ? revision : '']
      .map(fileSafe)
      .filter(Boolean)
      .join(' - ');
  }

  /* Folder names that are where a file happens to sit rather than what the
     job is called. Matched whole, so "Downloads" is rejected and "Downtown
     Campus" is not. */
  var GENERIC_FOLDER = new RegExp('^(' + [
    'downloads?', 'desktop', 'documents', 'onedrive', 'dropbox', 'box',
    'google ?drive', 'icloud ?drive', 'temp', 'tmp',
    'new folder( \\(\\d+\\))?', 'esx', 'files?', 'projects?',
    'surveys?', 'ekahau( projects)?', 'work', 'stuff', 'misc'
  ].join('|') + ')$', 'i');

  // The same test the file stem has always used: a name that says nothing
  // about the job.
  var GENERIC_STEM = /^(untitled|copy|new|final|draft|test|temp|project|report)([ _-]*\d*)$/i;

  /* The site segment of the file name, and where it came from.

     The folder is the site, and when it is known it is the whole answer. A job
     is kept in a folder named for the client, the building and the address,
     and the .esx inside it is called whatever the site or the discipline is -
     so the folder is the one that names the report.

     It used to return the folder *and* the .esx stem joined together, on the
     reading that the stem carried a discipline worth keeping. Asked for
     directly, the wanted name is "<report name> - <site>" and nothing else:
     the stem repeats most of the folder, and the part it does not repeat
     belongs to the file rather than to the sheet someone is handed. So the
     folder wins outright now, and the stem is a fallback rather than an
     addition.

     The stem is the answer whenever the folder is unknown, and it is kept
     whole - "ACME2 - SITE-03 - 100 Example St, Springfield, IL 62701 - B01 -
     PD" stays as it is.

     project.json's own name catches a file renamed to something that says
     nothing. The typed Client / Company setting is the last resort, and with
     nothing at all the segment drops out rather than leaving a dangling
     separator behind. */
  function projectNameSource() {
    var folderRaw = fileSafe(projectFolder || '');
    var folderIsGeneric = !!folderRaw && GENERIC_FOLDER.test(folderRaw);
    var folder = (folderRaw && !folderIsGeneric) ? folderRaw : '';

    var stemRaw = fileSafe(String(fileName || '').replace(/[.]esx$/i, ''));
    var stem = (stemRaw && !GENERIC_STEM.test(stemRaw)) ? stemRaw : '';

    if (folder) return { name: folder, from: 'the folder it was opened from' };
    if (stem) {
      return { name: stem, from: 'the .esx file name',
               skippedFolder: folderIsGeneric ? folderRaw : '' };
    }
    var fromFile = fileSafe(proj.projectName || '');
    if (fromFile) return { name: fromFile, from: 'the name inside the project' };
    if (stemRaw) return { name: stemRaw, from: 'the .esx file name' };
    var client = fileSafe(settingDefault('clientName') || '');
    if (client) return { name: client, from: 'the Client / company setting' };
    return { name: '', from: '' };
  }

  function projectName() {
    return projectNameSource().name;
  }

  function currentRevisionValue() {
    var v = ('revision' in currentOpts) ? currentOpts.revision : settingDefault('revision');
    return v || '';
  }

  function reportDocTitle() {
    return buildDocTitle(currentReport().docName, currentRevisionValue(),
                         projectName(), includeRevisionInName);
  }

  /* The saved file name is whatever document.title says at the moment the
     print dialog opens, so it has to be right whenever that can happen - not
     only at the end of a successful render. It was set in one place, after the
     report body was built, which left it stale or unwritten on every path that
     returned early or never re-rendered. */
  function syncDocTitle() {
    try { document.title = reportDocTitle(); } catch (e) {}
  }
  window.syncDocTitle = syncDocTitle;

  /* Why the site is not in the name. A drop cannot tell the browser where the
     file came from, so the server is asked instead — and each way that can come
     back empty needs a different thing done about it. Saying "no folder" and
     stopping is what made this read as broken rather than as unanswered. */
  function folderMissingReason() {
    if (folderLookup === 'no_root') {
      return 'This file was dragged in, so its folder had to be looked up — and '
           + 'no Local project folder is set. Set one in Settings → General, or '
           + 'open the file with “Open another…” instead.';
    }
    if (folderLookup === 'not_found') {
      return 'This file was dragged in and was not found under the Local project '
           + 'folder, so which folder it came from is unknown. Open it with '
           + '“Open another…” and the folder comes with it.';
    }
    if (folderLookup === 'ambiguous') {
      return 'This file was dragged in and more than one project of that name was '
           + 'found, so which folder it came from would be a guess. Open it with '
           + '“Open another…” and the folder comes with it.';
    }
    if (folderLookup === 'too_big') {
      return 'This file was dragged in and the Local project folder was too large '
           + 'to search. Open it with “Open another…” and the folder comes with it.';
    }
    return 'No folder is in the name because this file was dragged in — a drop '
         + 'hands the browser a bare file name. Open it with “Open another…” and '
         + 'the folder comes with it.';
  }

  // Shows both spellings at once so the effect of the switch is settled by
  // looking rather than by describing it.
  function renderFilenamePreview() {
    var host = document.getElementById('setNamePreview');
    if (!host) return;
    var docName = (typeof currentReportId !== 'undefined' && currentReportId)
      ? currentReport().docName : 'AP Installation';
    // The revision is set on the Settings page now, so this reads the saved
    // value rather than a field beside it.
    var rev = settingDefault('revision');
    // The real project name once one is open, so the preview is the actual
    // file name rather than a shape.
    var site = '', from = '', why = '';
    try {
      var picked = projectNameSource();
      site = picked.name || '';
      from = picked.from || '';
      /* The rule that decides this has been invisible, and "I can't get you
         to include the folder name" is what that costs. Every reason a folder
         is missing is printed where the name is. */
      if (picked.skippedFolder) {
        why = 'The folder it is in, \u201c' + picked.skippedFolder + '\u201d, is a place '
            + 'rather than a job, so it is left out.';
      } else if (!projectFolder) {
        why = folderMissingReason();
      }
    } catch (e) {}
    if (!site) { site = 'Project name'; from = ''; }
    var on = buildDocTitle(docName, rev, site, true);
    var off = buildDocTitle(docName, rev, site, false);
    var withRev = includeRevisionInName;
    host.innerHTML =
      '<div class="rep-set-name-row' + (withRev ? ' is-active' : '') + '">'
      + '<span class="rep-set-name-tag">With version</span>'
      + '<code>' + WD.esc(on) + '.pdf</code></div>'
      + '<div class="rep-set-name-row' + (withRev ? '' : ' is-active') + '">'
      + '<span class="rep-set-name-tag">Without</span>'
      + '<code>' + WD.esc(off) + '.pdf</code></div>'
      // Which of the four sources supplied the last segment. Worth saying:
      // the answer changes with how the file was opened, and that is not
      // something anyone would guess from looking at the name.
      + (from ? '<div class="rep-set-name-src">Project name taken from '
                + WD.esc(from) + '.'
                + (why ? ' ' + WD.esc(why) : '') + '</div>' : '');
  }
  window.renderFilenamePreview = renderFilenamePreview;

  function renderSettingsBanner() {
    var host = document.getElementById('settingsBanner');
    if (!host) return;
    var fields = [
      { key: 'clientName', label: 'Client / company' },
      { key: 'preparedBy', label: 'Prepared by' },
      { key: 'projectRef', label: 'Project reference' },
      { key: 'revision',   label: 'Revision' },
    ];
    var coverHtml = coverImage
      ? '<img class="rep-sb-thumb" src="' + WD.escAttr(coverImage.url) + '" alt="">'
      : '<span class="rep-sb-empty">No image</span>';
    var fieldsHtml = '';
    fields.forEach(function (f) {
      var val = settingDefault(f.key);
      fieldsHtml += '<div class="rep-sb-field">'
        + '<b>' + WD.esc(f.label) + '</b>'
        + (val ? '<span class="val">' + WD.esc(val) + '</span>'
               : '<span class="empty">Not set</span>')
        + '</div>';
    });
    /* Two actions, because the two halves of this banner are now edited in
       two places. The four values beside it are on the Settings page; the
       cover image and the file-name preview are still here, because the
       preview names the project that is open. One button for each, each
       saying where it goes - a single button reading "Edit report settings"
       would open the panel that no longer holds four of the five things
       above it. */
    host.innerHTML =
      '<div class="rep-sb-cover">' + coverHtml + '</div>'
      + '<div class="rep-sb-fields">' + fieldsHtml + '</div>'
      + '<div class="rep-sb-actions">'
      + '<a class="btn btn-secondary btn-sm" href="/settings#report">'
      + '⚙ Report settings…</a>'
      + '<button type="button" class="btn btn-secondary btn-sm" data-action="call" data-fn="openReportSettings">'
      + 'Cover image…</button></div>';
  }

  /* The four identity defaults and the file-name switch moved to the Settings
     page in v2.150.0, so this holds the cover image and the file-name preview -
     the preview stays because it names the project that is open, which the
     Settings page cannot know. */
  window.openReportSettings = function () {
    var modal = document.getElementById('reportSettingsModal');
    if (!modal) return;
    var warn = document.getElementById('setNoServer');
    if (warn) warn.hidden = settingsAvailable;
    setCoverStatus('');
    renderCoverSummary();
    renderFilenamePreview();
    modal.hidden = false;
  };

  window.closeReportSettings = function () {
    var modal = document.getElementById('reportSettingsModal');
    if (modal) modal.hidden = true;
  };

  /* `saveReportSettings` was removed in v2.150.0 along with the fields it read.
     The Settings page writes those five now, and the cover image has always
     saved itself the moment it is chosen rather than waiting for a button. */

  window.pickCoverImage = function () {
    var picker = document.createElement('input');
    picker.type = 'file';
    picker.accept = COVER_ACCEPT;
    picker.onchange = function () {
      var f = picker.files && picker.files[0];
      if (!f) return;
      setCoverStatus('Uploading ' + f.name + '…');
      uploadCover(f)
        .then(refreshCoverInfo)
        .then(function () {
          renderCoverSummary();
          renderSettingsBanner();
          configureDirty = true;
          setCoverStatus('Saved to ' + (coverImage ? coverImage.name : 'disk'), 'ok');
        })
        .catch(function (err) {
          setCoverStatus(err && err.message ? err.message : 'That image could not be saved.', 'err');
        });
    };
    picker.click();
  };

  window.removeCoverImage = function () {
    deleteCover()
      .then(refreshCoverInfo)
      .then(function () {
        renderCoverSummary();
        renderSettingsBanner();
        configureDirty = true;
        setCoverStatus('Cover image removed', 'ok');
      })
      .catch(function (err) {
        setCoverStatus(err && err.message ? err.message : 'Could not remove the image.', 'err');
      });
  };

  /* Capture the sidebar as it stands, for this report type only.

     One button rather than a saved default per control: he configures a
     report the way he wants it once and presses this, instead of visiting a
     settings page forty-one times. A sidebar change on its own stays with
     this document - the same split the Cloud Manager owner filter settled on,
     for the same reason. A stray click must not become permanent. */
  /* Person-level preferences that happen to be shown in the sidebar. They are
     saved once, for the person, and must not also be copied into the
     per-report store - a setting living in two places is how the Settings page
     came to display a value that was not in force. */
  var PERSON_LEVEL_OPTS = ['units', 'segGranularity'];

  function collectSidebarValues() {
    var r = currentReport();
    var out = {};
    (r.sidebar || []).forEach(function (opt) {
      if (opt.id.charAt(0) === '_') return;              // grid button, not a value
      if (SETTING_IDS.indexOf(opt.id) !== -1) return;    // shared, stored globally
      if (PERSON_LEVEL_OPTS.indexOf(opt.id) !== -1) return;
      if (opt.type === 'text') return;
      out[opt.id] = (opt.id in currentOpts) ? currentOpts[opt.id]
                  : optStartValue(opt);
    });
    return out;
  }

  function optionsDifferingFromSaved() {
    var saved = reportOptionDefaults(currentReportId);
    var now = collectSidebarValues();
    return Object.keys(now).filter(function (k) {
      return !(k in saved) ? now[k] !== shippedDefaultFor(k) : now[k] !== saved[k];
    });
  }

  /* Units and section size are suite settings with a per-report override, so
     "what this option starts at" is the setting rather than the value shipped
     in the option definition. Everything else starts at its own default.

     This existed implicitly and only by accident: `setOpt` wrote the suite
     setting at the same time as the per-report value, so the two agreed for
     the rest of the session. With that write gone, a panel reading the
     shipped default would have shown "Feet" while the report rendered in
     metres - the render path has always used the setting (see `buildOpts`). */
  function suitePrefFor(id) {
    if (id === 'units') return unitsPref;
    if (id === 'segGranularity') return segGranularityPref;
    return undefined;
  }
  function optStartValue(opt) {
    // `suitePrefFor` is the whole gate. A separate list of which ids are
    // suite-backed was tried and removed: it agreed with this function by
    // hand, so the two could disagree, and adding an id to it changed nothing
    // - which a mutation proved by passing.
    var pref = suitePrefFor(opt.id);
    if (pref !== undefined && pref !== null && pref !== '') return pref;
    return opt.type === 'select' ? (opt.default || '') : !!opt.default;
  }

  function shippedDefaultFor(id) {
    var r = currentReport();
    var opt = (r.sidebar || []).filter(function (o) { return o.id === id; })[0];
    if (!opt) return undefined;
    return optStartValue(opt);
  }

  window.saveReportOptionDefaults = function () {
    if (!settingsAvailable) { showToast('No server, so there is nowhere to save these', 'warn'); return; }
    var next = {};
    Object.keys(savedReportDefaults || {}).forEach(function (k) { next[k] = savedReportDefaults[k]; });
    next[currentReportId] = collectSidebarValues();
    pushSettings({ report_defaults: next })
      .then(function () { renderReportOpts(); showToast('Saved as your default for this report', 'success'); })
      .catch(function (e) { showToast(e.message || 'Could not save', 'error'); });
  };

  window.clearReportOptionDefaults = function () {
    if (!settingsAvailable) return;
    var next = {};
    Object.keys(savedReportDefaults || {}).forEach(function (k) {
      if (k !== currentReportId) next[k] = savedReportDefaults[k];
    });
    pushSettings({ report_defaults: next })
      .then(function () {
        currentOpts = {};
        optOverrides = {};
        renderReportOpts();
        showToast('Back to the shipped defaults for this report', 'success');
      })
      .catch(function (e) { showToast(e.message || 'Could not save', 'error'); });
  };

  // ── Auto-save per-report options ─────────────────────────────────────────
  var _autoSaveTimer = null;
  var AUTO_SAVE_DELAY = 1500;

  function scheduleAutoSave() {
    if (!settingsAvailable) return;
    if (_autoSaveTimer) clearTimeout(_autoSaveTimer);
    _autoSaveTimer = setTimeout(function () {
      _autoSaveTimer = null;
      var next = {};
      Object.keys(savedReportDefaults || {}).forEach(function (k) { next[k] = savedReportDefaults[k]; });
      next[currentReportId] = collectSidebarValues();
      pushSettings({ report_defaults: next })
        .then(function () {
          savedReportDefaults = next;
          refreshRememberedState();
          var dot = document.getElementById('autoSaveIndicator');
          if (dot) {
            dot.textContent = 'Saved';
            dot.classList.add('is-saved');
            setTimeout(function () { dot.classList.remove('is-saved'); }, 1200);
          }
        })
        .catch(function () {});
    }, AUTO_SAVE_DELAY);
  }

  // ── Report preview (what this report produces) ─────────────────────────
  function renderReportPreview() {
    var host = document.getElementById('reportPreviewCard');
    if (!host) return;
    var r = currentReport();
    var sections = r.sections || [];
    if (!sections.length) { host.hidden = true; return; }
    host.hidden = false;
    var html = '<div class="rep-config-card-head">'
      + '<span class="rep-config-icon">📄</span>'
      + '<span>What this report produces</span></div>'
      + '<p class="rep-preview-desc">' + WD.esc(r.description || '') + '</p>'
      + '<ul class="rep-preview-sections">';
    sections.forEach(function (s) {
      html += '<li class="rep-preview-section">'
        + '<span class="rep-preview-icon">' + (s.icon || '') + '</span>'
        + '<span class="rep-preview-body">'
        + '<b>' + WD.esc(s.title) + '</b>'
        + '<span>' + WD.esc(s.description || '') + '</span>'
        + '</span></li>';
    });
    html += '</ul>';
    if (r.readBy) {
      html += '<div class="rep-preview-meta">'
        + '<b>For:</b> ' + WD.esc(r.readBy)
        + (r.output ? ' · <b>You get:</b> ' + WD.esc(r.output) : '')
        + '</div>';
    }
    host.innerHTML = html;
  }

  // Per-report override controls -------------------------------------------
  function settingState(id) {
    var def = settingDefault(id);
    var val = (id in currentOpts) ? (currentOpts[id] || '') : '';
    if (optOverrides[id] && val !== def) return 'overridden';
    if (def) return 'inherited';
    return 'unset';
  }

  function settingBadgeHtml(id) {
    var state = settingState(id);
    var label = state === 'overridden' ? 'Changed for this report'
              : state === 'inherited' ? 'From settings'
              : 'No default saved';
    return '<span class="rep-set-state" data-state="' + state + '" data-for="' + WD.escAttr(id) + '">'
      + '<span class="rep-set-badge">' + label + '</span>'
      + (state === 'overridden'
          ? '<button type="button" class="rep-set-revert" data-action="call" data-fn="revertOptToDefault" data-arg="' + WD.escAttr(id) + '">Use default</button>'
          : '')
      + '</span>';
  }

  // Updated in place rather than by re-rendering, because these fields update on
  // every keystroke and a re-render would take the caret with it.
  function refreshSettingBadge(id) {
    var host = document.querySelector('.rep-set-state[data-for="' + id + '"]');
    if (!host) return;
    var wrap = document.createElement('div');
    wrap.innerHTML = settingBadgeHtml(id);
    host.replaceWith(wrap.firstChild);
  }

  window.revertOptToDefault = function (id) {
    delete optOverrides[id];
    var def = settingDefault(id);
    if (def) currentOpts[id] = def; else delete currentOpts[id];
    var input = document.getElementById('opt-' + id);
    if (input) input.value = def;
    refreshSettingBadge(id);
    configureDirty = true;
  };

  var STAGE_ORDER = ['template', 'configure', 'review'];
  var STAGE_ELS = {};

  window.goStage = function (name) {
    if (STAGE_ORDER.indexOf(name) === -1) return;
    if (name === 'configure' && !templateConfirmed) return;
    if (name === 'review' && !templateConfirmed) return;
    showStage(name);
  };

  function showStage(name) {
    currentStage = name;
    STAGE_ORDER.forEach(function (s) {
      var el = STAGE_ELS[s] || (STAGE_ELS[s] = document.getElementById('stage' + s.charAt(0).toUpperCase() + s.slice(1)));
      if (!el) return;
      if (s === name) el.removeAttribute('hidden');
      else el.setAttribute('hidden', '');
    });
    updateStepper();
    if (name === 'review') {
      if (configureDirty) renderReport();
      syncDocTitle();
      configureDirty = false;
      window.scrollTo({ top: 0, behavior: 'auto' });
    }
  }

  function updateStepper() {
    var stepper = document.getElementById('stepper');
    if (!stepper) return;
    var currentIdx = STAGE_ORDER.indexOf(currentStage);
    STAGE_ORDER.forEach(function (s, i) {
      var pill = stepper.querySelector('[data-stage="' + s + '"]');
      if (!pill) return;
      pill.classList.remove('active', 'done');
      if (i < currentIdx) pill.classList.add('done');
      else if (i === currentIdx) pill.classList.add('active');
      var reachable = (s === 'template')
        || (s === 'configure' && templateConfirmed)
        || (s === 'review' && templateConfirmed);
      if (reachable) pill.removeAttribute('disabled');
      else pill.setAttribute('disabled', '');
    });
  }

  window.markConfigDirty = function () { configureDirty = true; };
  window.toggleAllAps = function (checked) {
    proj.accessPoints.forEach(function (ap) {
      if (checked) apDisabled.delete(ap.id); else apDisabled.add(ap.id);
    });
    renderApFilter();
    configureDirty = true;
  };

  var dropzone = document.getElementById('dropzone');
  var fileInput = document.getElementById('fileInput');
  dropzone.addEventListener('click', function () { window.loadNewFile(); });
  dropzone.addEventListener('dragover', function (e) { e.preventDefault(); dropzone.classList.add('dragover'); });
  dropzone.addEventListener('dragleave', function () { dropzone.classList.remove('dragover'); });
  dropzone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropzone.classList.remove('dragover');
    if (e.dataTransfer.files.length) loadFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function (e) {
    if (e.target.files.length) loadFile(e.target.files[0]);
  });
  var baselineInput = document.getElementById('baselineInput');
  if (baselineInput) {
    baselineInput.addEventListener('change', function (e) {
      if (e.target.files.length) loadBaselineFile(e.target.files[0]);
    });
  }
  /* Opening from disk, in the one way that knows which folder the file is in.

     A browser file input cannot answer that - File carries a name and no path
     - so on the desktop app the native picker runs instead and the bytes come
     back through the server. Anything that fails or is unavailable falls
     through to the plain input: the hosted build has no server at all, and a
     cancelled picker must not leave the page doing nothing. */
  async function openViaNativePicker() {
    if (!settingsAvailable) return false;       // hosted build, no server
    var picked;
    try {
      picked = await WD.api('organizer/pick_esx_file', {});
    } catch (e) { return false; }
    if (!picked || !picked.ok || !picked.path) {
      /* A picker that could not open is not a cancel, and until the server
         started saying which was which, every failure arrived here looking
         like one - so the fall-through promised in the comment above could
         never fire and the click did nothing at all. Returning false hands the
         caller back to the plain file input. */
      if (picked && picked.code === 'picker_unavailable') {
        showToast(picked.error + ' Use the drop zone instead.', 'error');
        return false;
      }
      return true;                                          // cancelled: done
    }

    var resp;
    try {
      resp = await fetch('/api/report/open_esx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-WD-Wireless-Tools': '1' },
        body: JSON.stringify({ path: picked.path })
      });
    } catch (e) { return false; }
    if (!resp.ok) {
      var why = '';
      try { why = (await resp.json()).error || ''; } catch (e) {}
      showToast(why || 'That file could not be opened', 'error');
      return true;
    }
    var dec = function (h) {
      try { return decodeURIComponent(resp.headers.get(h) || ''); } catch (e) { return ''; }
    };
    var folder = dec('X-WD-Project-Folder');
    var name = dec('X-WD-File-Name') || 'project.esx';
    var blob = await resp.blob();
    await loadFile(new File([blob], name), folder);
    return true;
  }

  window.loadNewFile = async function () {
    if (await openViaNativePicker()) return;
    fileInput.value = '';
    fileInput.click();
  };

  /* The folder for a file that arrived without one.

     A drop hands the browser a name and some bytes, never a path, so this asks
     the server to look the file up under the Local project folder. It answers
     only for a single match on name *and* byte size: two buildings surveyed
     from one template is a real shape, and a wrong site printed on an
     installer's drawing is worse than no site at all.

     Anything that fails leaves the name exactly as it was before this existed
     - the .esx stem - so a missing setting, a moved file or no server at all
     costs nothing. The reason is kept so the settings preview can say it out
     loud rather than leaving him looking at a name with no site in it and no
     way to find out why. */
  async function recoverProjectFolder(file) {
    if (!settingsAvailable) { folderLookup = 'no_server'; return; }
    var res;
    try {
      res = await WD.api('report/find_folder',
                         { name: file.name, size: file.size });
    } catch (e) { folderLookup = 'failed'; return; }
    if (res && res.ok && res.folder) {
      projectFolder = res.folder;
      folderLookup = '';
      return;
    }
    folderLookup = (res && res.reason) || 'failed';
  }

  async function loadFile(file, folderName) {
    if (!file.name.toLowerCase().endsWith('.esx')) {
      showToast('Not an .esx file', 'error'); return;
    }
    try {
      var data = await file.arrayBuffer();
      esxZip = await JSZip.loadAsync(data);
      fileName = file.name;
      /* Only the native picker hands this over. A drop or a plain file input
         leaves it empty, and the drop zone is the front page - so most reports
         were named without their site in them. The file is on this machine
         either way, so when the folder did not arrive with it the server is
         asked to find it. */
      projectFolder = folderName || '';
      folderLookup = folderName ? '' : 'pending';
      if (!projectFolder) await recoverProjectFolder(file);
      await parseEsx();
      // Needs proj.projectId, so it cannot run before the parse. Coming back
      // with nothing is the ordinary state, not a failure.
      await loadFloorGrids();

      templateConfirmed = false;
      configureDirty = true;
      currentStage = 'template';
      // A baseline belongs to the comparison it was chosen for. Carrying it
      // across to a different project would silently compare two files nobody
      // put together.
      baseline = null; baselineName = ''; baselineError = '';

      dropzone.hidden = true;
      document.getElementById('dzTopbar').hidden = true;
      document.getElementById('workspace').classList.add('active');
      syncDocTitle();
      var badge = document.getElementById('fileBadge');
      badge.textContent = fileName;
      badge.style.display = 'inline-block';

      var sub = proj.accessPoints.length + ' APs across '
        + proj.floorPlans.length + ' floor plan'
        + (proj.floorPlans.length === 1 ? '' : 's');
      var tSub = document.getElementById('templateStageSub');
      if (tSub) tSub.textContent = siteName() + ' — ' + sub;
      var cSub = document.getElementById('configStageSub');
      if (cSub) cSub.textContent = siteName() + ' — ' + sub;

      renderTemplateGallery();
      renderApFilter();
      renderReportOpts();
      showStage('template');
    } catch (err) {
      showToast('Error reading file: ' + err.message, 'error');
      console.error(err);
    }
  }

  /* *zip* defaults to the open project. The Change / Audit report reads a
     second .esx through the same parser, and one parser reading two files is
     the point: an extraction that drifts between two copies is how the same
     project comes to have two different AP counts depending on which code
     path asked. */
  async function readJson(name, zip) {
    var f = (zip || esxZip).file(name);
    if (!f) return null;
    return JSON.parse(await f.async('string'));
  }

  async function readImageAsUrl(imageId) {
    if (!imageId) return null;
    if (proj.imageUrls[imageId]) return proj.imageUrls[imageId];
    var entry = esxZip.file('image-' + imageId);
    if (!entry) return null;
    var blob = await entry.async('blob');
    var meta = proj.images[imageId] || {};
    var mime = meta.imageFormat === 'SVG' ? 'image/svg+xml'
      : meta.imageFormat === 'JPEG' ? 'image/jpeg'
      : meta.imageFormat === 'PNG' ? 'image/png'
      : 'image/*';
    var typed = new Blob([blob], { type: mime });
    var url = URL.createObjectURL(typed);
    proj.imageUrls[imageId] = url;
    return url;
  }

  /* Read one .esx into *proj*, the open project, loading its floor plan
     images ready to draw. */
  async function parseEsx() {
    await parseInto(proj, esxZip, { images: true });
  }

  /* Choose the "before" .esx for the Change / Audit report.

     Its own input, not the drop zone: the drop zone replaces the project being
     reported on, and a wrong drop there would throw away the work of setting
     the report up. A file that is not an .esx, or that carries no access
     points, is refused *here* with the reason on the control, rather than
     accepted and then rendered as a comparison against nothing. */
  window.chooseBaseline = async function () {
    var input = document.getElementById('baselineInput');
    if (!input) return;
    input.value = '';
    input.click();
  };

  async function loadBaselineFile(file) {
    baselineError = '';
    if (!file) return;
    if (!/\.esx$/i.test(file.name)) {
      baselineError = 'That is not an .esx file.';
      baseline = null; baselineName = '';
      renderReportOpts(); window.renderReport(); return;
    }
    try {
      var zip = await JSZip.loadAsync(await file.arrayBuffer());
      var parsed = await parseInto({}, zip, { images: false });
      if (!parsed.accessPoints.length) {
        baselineError = 'That .esx has no access points in it, so there is '
          + 'nothing to compare against.';
        baseline = null; baselineName = '';
      } else {
        baseline = parsed;
        baselineName = file.name;
      }
    } catch (err) {
      baseline = null; baselineName = '';
      baselineError = 'Could not read that file: ' + err.message;
    }
    baselineChanged();
  }

  window.clearBaseline = function () {
    baseline = null; baselineName = ''; baselineError = '';
    baselineChanged();
  };

  /* Redraw the control, and the document if it is the thing on screen.

     Choosing a file from the Configure step must still leave the Review step
     correct when it is reached, which is what ``configureDirty`` is for -
     ``showStage`` re-renders on it. Rendering unconditionally would build the
     whole document into a hidden canvas on every pick, and on a project with
     floor plans that is real work for something nobody is looking at. */
  function baselineChanged() {
    configureDirty = true;
    renderReportOpts();
    if (currentStage === 'review') {
      window.renderReport();
      configureDirty = false;
    }
  }

  /* Read one .esx into *target*.

     The Change / Audit report needs a second project parsed the same way, and
     only the same way: a baseline whose AP list was built by slightly
     different code would report differences that are the parser's rather than
     the design's. Images are the one part it does not need - the overlay is
     drawn on the *current* floor plan, with the old positions marked on it -
     so ``opts.images`` is off for a baseline and a 40 MB before-file costs no
     object URLs. */
  async function parseInto(target, zip, popts) {
    var ap = await readJson('accessPoints.json', zip);
    var rad = await readJson('simulatedRadios.json', zip);
    var ant = await readJson('antennaTypes.json', zip);
    var fp = await readJson('floorPlans.json', zip);
    var img = await readJson('images.json', zip);
    var bld = await readJson('buildings.json', zip);
    var bf = await readJson('buildingFloors.json', zip);
    var nts = await readJson('notes.json', zip);
    var apm = await readJson('accessPointMeasurements.json', zip);
    var mr = await readJson('measuredRadios.json', zip);
    var sv = await readJson('surveys.json', zip);
    var perSurveyFiles = zip.file(/^survey-[a-f0-9\-]+\.json$/);
    var perSurveyArrays = [];
    for (var psi = 0; psi < perSurveyFiles.length; psi++) {
      try {
        var body = JSON.parse(await perSurveyFiles[psi].async('string'));
        if (body && Array.isArray(body.surveys)) perSurveyArrays.push(body.surveys);
      } catch (e) {}
    }

    // Only used when the .esx has been renamed to something that says nothing
    // about the job, so a report never ends up named after "final.esx".
    var pj = null;
    try { pj = await readJson('project.json', zip); } catch (e) {}
    target.projectName = (pj && pj.project && (pj.project.name || pj.project.title)) || '';
    /* Ekahau's own id for this project. It survives every rename, upload and
       download, which is why the column grid calibration is filed under it -
       renaming the file, or the project inside it, must not cost the two
       clicks that set the grid up. */
    target.projectId = (pj && pj.project && pj.project.id) || '';

    target.accessPoints = (ap && ap.accessPoints) || [];
    target.radios = (rad && rad.simulatedRadios) || [];
    target.antennas = {};
    ((ant && ant.antennaTypes) || []).forEach(function (a) { target.antennas[a.id] = a; });
    target.floorPlans = (fp && fp.floorPlans) || [];
    target.images = {};
    ((img && img.images) || []).forEach(function (i) { target.images[i.id] = i; });
    target.buildings = {};
    ((bld && bld.buildings) || []).forEach(function (b) { target.buildings[b.id] = b; });
    target.buildingFloors = {};
    ((bf && bf.buildingFloors) || []).forEach(function (x) { target.buildingFloors[x.floorPlanId] = x; });
    // Notes hang off an AP by id. There is no separate pictureNotes.json in a
    // real project - verified against one carrying both a text note and a
    // photo note: a note is a picture note when its imageIds is non-empty, and
    // such a note can carry no text at all.
    target.notes = {};
    ((nts && nts.notes) || []).forEach(function (n) {
      if (n && n.id) target.notes[n.id] = n;
    });
    target.measurements = (apm && apm.accessPointMeasurements) || [];
    target.measuredRadios = (mr && mr.measuredRadios) || [];
    target.surveys = (sv && sv.surveys) ? sv.surveys.slice() : [];
    for (var psj = 0; psj < perSurveyArrays.length; psj++) {
      for (var psk = 0; psk < perSurveyArrays[psj].length; psk++) {
        target.surveys.push(perSurveyArrays[psj][psk]);
      }
    }
    target.imageUrls = {};

    if (popts && popts.images) {
      apDisabled = new Set();
      for (var i = 0; i < target.floorPlans.length; i++) {
        var f = target.floorPlans[i];
        await readImageAsUrl(f.bitmapImageId || f.imageId);
      }
    }
    return target;
  }

  /* The "#" column is 0.58in wide because it holds a number. When a name
     carries no "APnn" this used to return the whole name, so the map marker
     printed "Access Point" while the table printed "Access Poi" - the marker
     pill grows to fit and a table cell clips. Both surfaces call this
     function, so the disagreement was never in the derivation; it was that
     the derivation could return something no "#" column can hold.

     A trailing number anywhere in the name is used if there is one. Failing
     that the name is cut here, once, so that every surface shows the same
     cut - and the full name is beside it in the AP name column. */
  var SHORT_LABEL_MAX = 7;

  function apLabel(ap, mode) {
    var n = (ap && ap.name) || '';
    if (mode === 'full') return n;
    // Ekahau appends "-001" when an AP is duplicated, so the number is not
    // always the last thing in the name. Anchoring on end-of-string made
    // ACME1-01-00-01-AP05-001 fail to match and fall through to the whole
    // name - in a column sized for two characters, and on the map marker.
    var m = n.match(/AP[\-_\s]?(\d+[A-Za-z]?)(?:[\-_](\d+))?\s*$/i);
    if (m) return m[2] ? m[1] + '-' + m[2] : m[1];
    // No "APnn" at all. A trailing number is still a number somebody wrote.
    var t = n.match(/(\d+)\s*$/);
    if (t) return t[1];
    var trimmed = n.trim();
    return trimmed.length > SHORT_LABEL_MAX
      ? trimmed.slice(0, SHORT_LABEL_MAX - 1) + '\u2026'
      : trimmed;
  }

  /* A floor plan imported from CAD carries a generated name like
     "200 Sample TF_Overall Plan background_2026-08-14". The full name
     belongs in the floor heading, which has a whole line for it; repeating it
     in a table cell sized for a few characters is what made rows explode. */
  function shortFloorLabel(name) {
    var s = String(name || '').trim();
    if (!s) return '';
    s = s.replace(/[_\s]*\d{4}-\d{2}-\d{2}\s*$/, '');   // trailing export date
    var cut = s.indexOf('_');
    if (cut > 2) s = s.slice(0, cut);
    s = s.replace(/\s+/g, ' ').trim();
    return s.length > 24 ? s.slice(0, 23) + '\u2026' : s;
  }
  function antennaIsDirectional(ant) {
    if (!ant) return false;
    if (ant.directional === true) return true;
    if (ant.directional === false) return false;
    return !/omni/i.test(ant.name || '');
  }
  function radioIsDirectional(r) {
    if (!r || r.antennaDirection == null) return false;
    return antennaIsDirectional(proj.antennas[r.antennaTypeId]);
  }
  function apIsOmniOnly(ap) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === ap.id; });
    if (!rs.length) return false;
    return rs.every(function (r) {
      if (!r.antennaTypeId) return true;
      var a = proj.antennas[r.antennaTypeId];
      if (!a) return true;
      return !antennaIsDirectional(a);
    });
  }
  function hasAnyBeamWidth(p) {
    var ids = Object.keys(p.antennas || {});
    return ids.some(function (id) {
      var a = p.antennas[id];
      return a && (a.beamWidthHorizontal != null || a.beamWidthVertical != null);
    });
  }

  function primaryRadio(apId) {
    var rs = proj.radios.filter(function (r) { return r.accessPointId === apId; });
    return rs.find(function (r) { return r.radioTechnology === 'IEEE802_11'; }) || rs[0] || null;
  }
  function compass(deg) {
    var dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'];
    var norm = ((deg % 360) + 360) % 360;
    return dirs[Math.floor((norm + 11.25) / 22.5) % 16];
  }
  function metersToFt(m) { return m * M_TO_FT; }

  /* Every length in an .esx is stored in metres - metersPerUnit is the only
     scale the file carries - so metric leaks into the output unless something
     converts it deliberately. The project file has no display-unit field of
     its own (projectConfiguration.displayOptions carries one unrelated key),
     so Ekahau keeps that preference in the application and the report cannot
     read it. It is a setting here instead, defaulting to feet.

     One unit, not two. These pages are read on a ladder, and "7.62 m (25 ft)"
     is two numbers to scan where one will do. */
  function fmtLength(meters, opts, digits) {
    if (meters == null || isNaN(meters)) return '—';
    // A foot is a small enough step that one decimal is plenty; a metre is
    // three feet, so metric needs two to say the same thing. 3.048 m is
    // "10 ft" or "3.05 m", never a bare "3 m".
    if (unitsOf(opts) === 'meters') return fmtFixed(meters, digits == null ? 2 : digits) + ' m';
    return fmtFixed(meters * M_TO_FT, digits == null ? 1 : digits) + ' ft';
  }

  function unitsOf(opts) {
    opts = opts || {};
    if (opts.units === 'meters' || opts.units === 'feet') return opts.units;
    // Pre-2.32 reports carried a boolean "show both units" flag; anyone who
    // had turned it off wanted metric only.
    if (opts.imperial === false) return 'meters';
    return 'feet';
  }
  /* Drop a trailing zero that says nothing - 12.50 is 12.5 - but only after a
     decimal point.

     The old form was `toFixed(dp).replace(/\.?0+$/, '')`, which with no
     decimals to work on ate the number's own digits: `fmt(20, 0)` returned
     "2" and `fmt(180, 0)` returned "18". One caller did that in shipped
     output - the transmit power on an AP Placement Map label - so a design
     carrying 20 dBm printed "2 dBm" on the drawing an installer works from,
     and 10 dBm printed "1 dBm". Every other call asks for a decimal, where
     the point stops the match early, which is why this survived. */
  function fmt(n, dp) {
    var s = Number(n).toFixed(dp);
    return s.indexOf('.') === -1 ? s : s.replace(/0+$/, '').replace(/\.$/, '');
  }
  // Same, but keeps the decimal it was asked for. A column of heights reads as
  // a column when they all have one.
  function fmtFixed(n, dp) { return Number(n).toFixed(dp); }
  function formatReadableDate(d) {
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }
  function freqToChannel(freqMHz) {
    if (!freqMHz) return '—';
    if (freqMHz >= 2412 && freqMHz <= 2484) return Math.round((freqMHz - 2407) / 5);
    if (freqMHz >= 5170 && freqMHz <= 5885) return Math.round((freqMHz - 5000) / 5);
    if (freqMHz >= 5955 && freqMHz <= 7115) return Math.round((freqMHz - 5950) / 5);
    return freqMHz;
  }
  function floorPlanForAp(ap) {
    if (!ap.location) return null;
    return proj.floorPlans.find(function (f) { return f.id === ap.location.floorPlanId; }) || null;
  }

  var REPORT_FOOTER = '<footer class="rep-doc-foot">Generated by WD Report · WD Wireless Tools</footer>';

  function groupApsByFloor(aps, ctx) {
    var byFloor = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      var key = fp ? fp.id : '_none';
      (byFloor[key] = byFloor[key] || []).push(ap);
    });
    return byFloor;
  }

  function sortedFloorOrder(byFloor) {
    var order = proj.floorPlans.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    if (byFloor['_none']) order.push({ id: '_none', name: '(No floor plan)' });
    return order;
  }

  /* ══ Comparing two projects ═══════════════════════════════════════════════

     What the Change / Audit report rests on. Kept as plain functions over two
     parsed projects, with no DOM and no module state, because the awkward
     parts here are arithmetic and they are worth being able to test directly.

     **Matching is by id first and name second, and never by position.**
     Ekahau's AP id survives every edit, so where the after-file is a
     descendant of the before-file - somebody opened the design, moved things
     and saved, which is the ordinary case - every AP matches exactly and the
     name is free to have changed. Name matching is the fallback for an AP that
     was deleted and re-added, and for two files with no shared lineage.
     Position is deliberately not a key: a moved AP is the thing being looked
     for, so matching on where it is would hide exactly what the report is for.

     **The trap this has to survive is a re-cropped floor plan.** Coordinates
     live in full image pixel space, so trimming a plan between the two saves
     - which is what PlanTrim is for, and he uses it - shifts every coordinate
     on that floor by the crop offset. Reported naively that is seventy APs
     that all moved, which is worse than useless: it buries the two that really
     did. So where a floor's image has changed size the two coordinate spaces
     are known not to be comparable, the shift is measured as the median
     displacement of the matched APs, and it is taken out and *said on the
     page*. Where the image is the same size the spaces are the same and a
     displacement is a real move. */

  // Below this, a difference is a nudge in the design rather than a decision
  // to put the AP somewhere else. In metres, because that is what an .esx
  // stores; the option that sets it names both units.
  var DEFAULT_MOVE_THRESHOLD_M = 0.5;

  function apCoord(ap) {
    var loc = ap && ap.location;
    return (loc && loc.coord) || null;
  }

  function normName(ap) {
    return String((ap && ap.name) || '').trim().toLowerCase();
  }

  /* Pair the APs of two projects. Returns matched pairs plus what is left over
     on each side. *byName* carries the fallback so a caller can report how a
     pair was found - an id match and a name match do not deserve equal trust,
     and the report says which it was. */
  function matchAccessPoints(beforeAps, afterAps) {
    var matched = [];
    var afterById = {};
    afterAps.forEach(function (a) { if (a && a.id) afterById[a.id] = a; });

    var usedAfter = {};
    var leftoverBefore = [];
    beforeAps.forEach(function (b) {
      var a = b && b.id ? afterById[b.id] : null;
      if (a && !usedAfter[a.id]) {
        usedAfter[a.id] = true;
        matched.push({ before: b, after: a, by: 'id' });
      } else {
        leftoverBefore.push(b);
      }
    });

    /* Name is a weaker key and is only allowed to match one-to-one. Two APs
       called "AP" on either side must not pair off arbitrarily: an ambiguous
       name is treated as no match, so they surface as one removed and one
       added, which is true, rather than as a pair that silently invented a
       relationship. */
    var freeAfter = afterAps.filter(function (a) { return !usedAfter[a.id]; });
    var afterByName = {};
    freeAfter.forEach(function (a) {
      var k = normName(a);
      if (!k) return;
      afterByName[k] = afterByName[k] === undefined ? a : null;   // null = ambiguous
    });
    var beforeNameCount = {};
    leftoverBefore.forEach(function (b) {
      var k = normName(b);
      if (k) beforeNameCount[k] = (beforeNameCount[k] || 0) + 1;
    });

    var removed = [];
    leftoverBefore.forEach(function (b) {
      var k = normName(b);
      var a = k && beforeNameCount[k] === 1 ? afterByName[k] : null;
      if (a && !usedAfter[a.id]) {
        usedAfter[a.id] = true;
        matched.push({ before: b, after: a, by: 'name' });
      } else {
        removed.push(b);
      }
    });

    var added = afterAps.filter(function (a) { return !usedAfter[a.id]; });
    return { matched: matched, added: added, removed: removed };
  }

  /* Pair the floors of two projects: by id, then by name. A floor whose id
     changed but whose name did not is the same floor to everyone except the
     file. */
  function matchFloors(beforeFloors, afterFloors) {
    var pairs = [];
    var usedAfter = {};
    var byId = {};
    afterFloors.forEach(function (f) { if (f && f.id) byId[f.id] = f; });
    beforeFloors.forEach(function (b) {
      var a = b && b.id ? byId[b.id] : null;
      if (a && !usedAfter[a.id]) { usedAfter[a.id] = true; pairs.push({ before: b, after: a }); }
    });
    var freeAfter = afterFloors.filter(function (f) { return !usedAfter[f.id]; });
    beforeFloors.forEach(function (b) {
      if (pairs.some(function (p) { return p.before === b; })) return;
      var a = freeAfter.find(function (f) {
        return !usedAfter[f.id]
          && String(f.name || '').trim().toLowerCase() === String(b.name || '').trim().toLowerCase()
          && String(f.name || '').trim() !== '';
      });
      if (a) { usedAfter[a.id] = true; pairs.push({ before: b, after: a }); }
    });
    return pairs;
  }

  function median(values) {
    if (!values.length) return 0;
    var s = values.slice().sort(function (a, b) { return a - b; });
    var m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /* The offset to take out of one floor's before-coordinates, or null.

     Only ever non-null when the floor plan image has *changed size*, which is
     the observable fact that says the two coordinate spaces are different.
     Where it has not, a displacement is a real move and must not be explained
     away - a compensation that fired on an ordinary floor would hide every
     move on it, which is the more dangerous of the two failures. */
  function cropShiftFor(pair, pairsOnFloor) {
    var b = pair.before, a = pair.after;
    if (!b || !a) return null;
    var sameSize = Number(b.width) === Number(a.width)
                && Number(b.height) === Number(a.height);
    if (sameSize) return null;
    var dxs = [], dys = [];
    pairsOnFloor.forEach(function (p) {
      var cb = apCoord(p.before), ca = apCoord(p.after);
      if (cb && ca) { dxs.push(ca.x - cb.x); dys.push(ca.y - cb.y); }
    });
    // Two points cannot tell a shift from a pair of moves.
    if (dxs.length < 3) return null;
    return { dx: median(dxs), dy: median(dys), count: dxs.length };
  }

  function deg(v) { return typeof v === 'number' && isFinite(v) ? v : null; }

  /* How far apart two angles are, the short way round. 359 and 1 are two
     degrees apart, not three hundred and fifty eight - and an antenna nudged
     across north is the case that gets this wrong. */
  function angleDelta(a, b) {
    if (a === null || b === null) return null;
    var d = ((a - b) % 360 + 360) % 360;
    return d > 180 ? 360 - d : d;
  }

  /* The radio a comparison reads, for either project. ``primaryRadio`` above
     answers the same question for the open project only, off module state; a
     baseline has its own radio list and cannot use it. */
  function radioIndexFor(project) {
    var byAp = {};
    ((project && project.radios) || []).forEach(function (r) {
      if (!r || !r.accessPointId) return;
      var cur = byAp[r.accessPointId];
      if (!cur || (r.radioTechnology === 'IEEE802_11' && cur.radioTechnology !== 'IEEE802_11')) {
        byAp[r.accessPointId] = r;
      }
    });
    return byAp;
  }

  /* What is different about one matched pair. An empty list means the AP is
     unchanged, which is most of them on a real comparison and is why the
     report leads with the changes rather than the inventory. */
  function changesFor(pair, ctxInfo) {
    var b = pair.before, a = pair.after;
    var rb = ctxInfo.beforeRadios[b.id] || null;
    var ra = ctxInfo.afterRadios[a.id] || null;
    var out = [];

    if (String(b.name || '') !== String(a.name || '')) {
      out.push({ kind: 'renamed', from: b.name || '(unnamed)', to: a.name || '(unnamed)' });
    }
    if (String(b.model || '') !== String(a.model || '')) {
      out.push({ kind: 'model', from: b.model || '—', to: a.model || '—' });
    }
    if (String(b.vendor || '') !== String(a.vendor || '')) {
      out.push({ kind: 'vendor', from: b.vendor || '—', to: a.vendor || '—' });
    }

    var lb = b.location || {}, la = a.location || {};
    var floorChanged = ctxInfo.floorKeyOf(lb.floorPlanId, 'before')
                    !== ctxInfo.floorKeyOf(la.floorPlanId, 'after');
    if (floorChanged) {
      out.push({ kind: 'floor',
                 from: ctxInfo.floorNameOf(lb.floorPlanId, 'before'),
                 to: ctxInfo.floorNameOf(la.floorPlanId, 'after') });
    }

    var cb = apCoord(b), ca = apCoord(a);
    if (cb && ca && !floorChanged) {
      var shift = ctxInfo.shiftFor(la.floorPlanId) || { dx: 0, dy: 0 };
      var dx = ca.x - (cb.x + shift.dx);
      var dy = ca.y - (cb.y + shift.dy);
      var px = Math.sqrt(dx * dx + dy * dy);
      var mpu = ctxInfo.metersPerUnitOf(la.floorPlanId);
      var metres = mpu ? px * mpu : null;
      if (metres !== null && metres >= ctxInfo.threshold) {
        out.push({ kind: 'moved', metres: metres, dx: dx, dy: dy });
      }
    } else if ((cb && !ca) || (!cb && ca)) {
      out.push({ kind: cb ? 'unplaced' : 'placed' });
    }

    var azB = deg(rb && rb.antennaDirection), azA = deg(ra && ra.antennaDirection);
    var dAz = angleDelta(azA, azB);
    if (dAz !== null && dAz >= 1) {
      out.push({ kind: 'azimuth', from: azB, to: azA, delta: dAz });
    }
    var tB = deg(rb && rb.antennaTilt), tA = deg(ra && ra.antennaTilt);
    if (tB !== null && tA !== null && Math.abs(tA - tB) >= 1) {
      out.push({ kind: 'tilt', from: tB, to: tA });
    }
    var hB = deg(rb && rb.antennaHeight), hA = deg(ra && ra.antennaHeight);
    if (hB !== null && hA !== null && Math.abs(hA - hB) >= 0.05) {
      out.push({ kind: 'height', from: hB, to: hA });
    }
    var mB = (rb && rb.antennaMounting) || '', mA = (ra && ra.antennaMounting) || '';
    if (String(mB) !== String(mA)) {
      out.push({ kind: 'mount', from: mB || '—', to: mA || '—' });
    }
    var atB = (rb && rb.antennaTypeId) || '', atA = (ra && ra.antennaTypeId) || '';
    if (String(atB) !== String(atA)) {
      out.push({ kind: 'antenna',
                 from: ctxInfo.antennaNameOf(atB, 'before'),
                 to: ctxInfo.antennaNameOf(atA, 'after') });
    }
    return out;
  }

  /* Compare two parsed projects.

     Pure: it reads the two objects it is handed and nothing else, which is what
     makes it testable without a browser. *opts.threshold* is in metres. */
  function compareProjects(before, after, opts) {
    opts = opts || {};
    var threshold = typeof opts.threshold === 'number'
      ? opts.threshold : DEFAULT_MOVE_THRESHOLD_M;

    var beforeFloors = (before.floorPlans || []);
    var afterFloors = (after.floorPlans || []);
    var floorPairs = matchFloors(beforeFloors, afterFloors);

    // One key per floor, shared by both sides, so "did it change floor" is
    // asked of the building rather than of two unrelated id spaces.
    var keyByBefore = {}, keyByAfter = {};
    floorPairs.forEach(function (p, i) {
      keyByBefore[p.before.id] = 'pair-' + i;
      keyByAfter[p.after.id] = 'pair-' + i;
    });
    function floorKeyOf(id, side) {
      if (!id) return '_none';
      var m = side === 'before' ? keyByBefore[id] : keyByAfter[id];
      return m || (side + ':' + id);
    }
    function floorObj(id, side) {
      var list = side === 'before' ? beforeFloors : afterFloors;
      return list.find(function (f) { return f.id === id; }) || null;
    }
    function floorNameOf(id, side) {
      var f = floorObj(id, side);
      return (f && f.name) || '(no floor plan)';
    }
    function antennaNameOf(id, side) {
      if (!id) return '—';
      var map = (side === 'before' ? before.antennas : after.antennas) || {};
      return (map[id] && map[id].name) || id;
    }
    function metersPerUnitOf(id) {
      var f = floorObj(id, 'after');
      var v = f && Number(f.metersPerUnit);
      return v && isFinite(v) && v > 0 ? v : null;
    }

    var paired = matchAccessPoints(before.accessPoints || [], after.accessPoints || []);

    /* Crop shifts are worked out per floor, and they need the pairs on that
       floor, so this runs before the per-AP comparison rather than inside it. */
    var shifts = {};
    var floorNotes = [];
    floorPairs.forEach(function (fp) {
      var on = paired.matched.filter(function (m) {
        var la = (m.after.location || {}).floorPlanId;
        var lb = (m.before.location || {}).floorPlanId;
        return la === fp.after.id && lb === fp.before.id;
      });
      var shift = cropShiftFor(fp, on);
      if (shift && (Math.abs(shift.dx) > 0.5 || Math.abs(shift.dy) > 0.5)) {
        shifts[fp.after.id] = shift;
        floorNotes.push({
          floorId: fp.after.id,
          name: fp.after.name || '(unnamed)',
          beforeSize: [Number(fp.before.width) || 0, Number(fp.before.height) || 0],
          afterSize: [Number(fp.after.width) || 0, Number(fp.after.height) || 0],
          dx: shift.dx, dy: shift.dy, count: shift.count,
        });
      }
    });

    var info = {
      beforeRadios: radioIndexFor(before),
      afterRadios: radioIndexFor(after),
      floorKeyOf: floorKeyOf,
      floorNameOf: floorNameOf,
      antennaNameOf: antennaNameOf,
      metersPerUnitOf: metersPerUnitOf,
      shiftFor: function (id) { return shifts[id] || null; },
      threshold: threshold,
    };

    var changed = [];
    var unchanged = [];
    paired.matched.forEach(function (m) {
      var ch = changesFor(m, info);
      var rec = { before: m.before, after: m.after, by: m.by, changes: ch,
                  floorId: (m.after.location || {}).floorPlanId || '_none' };
      if (ch.length) changed.push(rec); else unchanged.push(rec);
    });

    return {
      threshold: threshold,
      matched: paired.matched.length,
      matchedByName: paired.matched.filter(function (m) { return m.by === 'name'; }).length,
      added: paired.added,
      removed: paired.removed,
      changed: changed,
      unchanged: unchanged,
      floorPairs: floorPairs,
      floorNotes: floorNotes,
      addedFloors: afterFloors.filter(function (f) {
        return !floorPairs.some(function (p) { return p.after.id === f.id; });
      }),
      removedFloors: beforeFloors.filter(function (f) {
        return !floorPairs.some(function (p) { return p.before.id === f.id; });
      }),
    };
  }

  window.WDCompare = {
    match: matchAccessPoints,
    matchFloors: matchFloors,
    compare: compareProjects,
    angleDelta: angleDelta,
  };

  // Ekahau records the storey number on buildingFloors, not on the floor plan
  // itself, and plenty of projects never set it. Returns null when there is no
  // usable number so callers can fall back to the plain section label.
  function floorNumberFor(fp) {
    if (!fp || fp.id === '_none') return null;
    var bf = proj.buildingFloors && proj.buildingFloors[fp.id];
    var raw = bf ? bf.floorNumber : null;
    if (raw === null || raw === undefined || raw === '') return null;
    var n = Number(raw);
    return isFinite(n) ? n : null;
  }

  function floorPlanImageUrl(fp) {
    var imgId = fp.bitmapImageId || fp.imageId;
    return proj.imageUrls[imgId] || null;
  }

  function collectUsedAntennas(aps, ctx) {
    var used = {};
    if (aps && ctx) {
      aps.forEach(function (ap) {
        if (!ctx.primaryRadio(ap.id)) return;
        proj.radios.filter(function (x) { return x.accessPointId === ap.id; })
          .forEach(function (x) { if (x.antennaTypeId) used[x.antennaTypeId] = true; });
      });
    } else {
      proj.radios.forEach(function (r) { if (r.antennaTypeId) used[r.antennaTypeId] = true; });
    }
    return Object.keys(used);
  }

  /* An antenna code, and why the table does not print the name.

     A real external antenna is called something like "Vendor ANT-4x4-D1314
     Dual-Band Narrow Sector 13.5 dBi" - around fifty characters. The AP
     installation table has eleven columns on a portrait sheet, and there is
     no width at which that string fits on one line. It was truncated with an
     ellipsis, which on screen has a tooltip behind it and on paper has
     nothing: "Aruba ANT-4x4-D13\u2026" does not identify a part to order or to
     check against what is in the box.

     Letting it wrap was measured and is worse. With eleven columns Firefox
     cannot satisfy `width: 100%` once a cell may wrap, so it shrinks the
     whole sheet to 75% - every value on the page smaller, to widen one
     column.

     So the column carries a code and "Antennas in use" carries the code
     beside the full name, which is what a drawing does with anything too long
     for the field it belongs in. The code is assigned in the order the
     legend lists them, from the same list, so the two cannot drift. */
  function antennaKeys(ids) {
    var map = {};
    (ids || []).forEach(function (id, i) { map[id] = 'A' + (i + 1); });
    return map;
  }

  function renderAntennaTable(ids, apCountMap) {
    if (!ids.length) return '';
    var hasCount = apCountMap && Object.keys(apCountMap).length > 0;
    var keys = antennaKeys(ids);
    var rows = '';
    ids.forEach(function (id) {
      var a = proj.antennas[id]; if (!a) return;
      var bits = [];
      if (a.frequencyBand) bits.push(a.frequencyBand);
      if (a.apCoupling) bits.push(a.apCoupling.replace(/_/g, ' ').toLowerCase());
      if (a.maxGain != null) bits.push(a.maxGain + ' dBi max gain');
      if (a.beamWidthHorizontal != null) bits.push(a.beamWidthHorizontal + '° h-beam');
      if (a.beamWidthVertical != null) bits.push(a.beamWidthVertical + '° v-beam');
      var countCell = hasCount
        ? '<td class="rep-num">' + (apCountMap[id] || 0) + ' AP' + ((apCountMap[id] || 0) === 1 ? '' : 's') + '</td>'
        : '';
      rows += '<tr><td class="rep-az">' + WD.esc(keys[id] || '') + '</td>'
        + '<td class="rep-name">' + WD.esc(a.name || id) + '</td><td>'
        + WD.esc(bits.join(' · ')) + '</td>' + countCell + '</tr>';
    });
    var countHeader = hasCount ? '<th class="rep-num">Qty</th>' : '';
    /* The antenna name is the longest value on any of these sheets, so it is
       given the room explicitly rather than an even share. */
    var cols = hasCount
      ? '<colgroup><col style="width:8%"><col style="width:47%"><col style="width:32%">'
        + '<col style="width:13%"></colgroup>'
      : '<colgroup><col style="width:9%"><col style="width:53%"><col style="width:38%"></colgroup>';
    return '<table class="rep-ap-table">' + cols
      + '<thead><tr><th class="rep-num">Code</th><th>Antenna</th><th>Specs</th>'
      + countHeader + '</tr></thead>'
      + '<tbody>' + rows + '</tbody></table>';
  }

  function siteName() {
    var stem = fileName.replace(/\.esx$/i, '');
    var i = stem.lastIndexOf(' - ');
    if (i > 0) {
      var suffix = stem.slice(i + 3);
      if (suffix.length <= 30 && suffix.indexOf(',') === -1) return stem.slice(0, i);
    }
    return stem;
  }

  function apModelDesignator(ap) {
    var v = ap.vendor || '';
    var m = ap.model || '';
    if (v && m) return v + ' · ' + m;
    return v || m || 'Unknown model';
  }

  function apGroupKey(ap, dim) {
    if (dim === 'color') return ap.color || '__nocolor';
    if (dim === 'model') return (ap.vendor || 'Unknown') + '|' + (ap.model || 'Unknown');
    if (dim === 'floor') return (ap.location && ap.location.floorPlanId) || '__nofloor';
    if (dim === 'building') {
      var floorId = ap.location && ap.location.floorPlanId;
      var bf = proj.buildingFloors && proj.buildingFloors[floorId];
      return (bf && bf.buildingId) || '__nobuilding';
    }
    return '__none';
  }
  function apGroupLabel(key, dim) {
    if (dim === 'color') {
      /* The stored value is a hex, so this printed "#6B6B6B" as a section
         heading where Ekahau says "Gray". He reported seeing a hex code
         instead of a name and it was still here, because the fix went into
         the Labeler and this is a second place that renders a colour to the
         reader. Both go through the shared table now. */
      if (key === '__nocolor') return WD.ekahauColorName(WD.CLEAR_KEY);
      return WD.ekahauColorName(WD.ekahauColorKey(key));
    }
    if (dim === 'model') {
      if (key === 'Unknown|Unknown') return 'Unknown model';
      return key.replace('|', ' · ');
    }
    if (dim === 'floor') {
      if (key === '__nofloor') return 'No floor';
      var fp = proj.floorPlans.find(function (f) { return f.id === key; });
      return (fp && fp.name) || 'Unnamed floor';
    }
    if (dim === 'building') {
      if (key === '__nobuilding') return 'No building';
      var b = proj.buildings && proj.buildings[key];
      return (b && b.name) || 'Unnamed building';
    }
    return key;
  }

  function renderApFilter() {
    var host = document.getElementById('apFilterList');
    var countHost = document.getElementById('apCount');
    if (!host) return;
    if (!proj.accessPoints.length) {
      host.innerHTML = '<div class="rep-ap-empty">No APs found in this .esx.</div>';
      if (countHost) countHost.textContent = '0 APs';
      return;
    }

    var r = currentReport();
    var sidebarDefaults = {};
    (r.sidebar || []).forEach(function (o) { sidebarDefaults[o.id] = !!o.default; });
    var inclDirectional = ('inclDirectional' in currentOpts) ? currentOpts.inclDirectional
      : ('inclDirectional' in sidebarDefaults) ? sidebarDefaults.inclDirectional : true;
    var inclOmni = ('inclOmni' in currentOpts) ? currentOpts.inclOmni
      : ('inclOmni' in sidebarDefaults) ? sidebarDefaults.inclOmni : false;
    var eligible = proj.accessPoints.filter(function (ap) {
      var omni = apIsOmniOnly(ap);
      if (omni && !inclOmni) return false;
      if (!omni && !inclDirectional) return false;
      return true;
    });

    var q = apSearch.trim().toLowerCase();
    var filtered = q
      ? eligible.filter(function (ap) { return (ap.name || '').toLowerCase().indexOf(q) !== -1; })
      : eligible.slice();

    if (countHost) {
      var eligibleChecked = eligible.filter(function (a) { return !apDisabled.has(a.id); }).length;
      var suffix = (eligible.length !== proj.accessPoints.length)
        ? ' (' + (proj.accessPoints.length - eligible.length) + ' hidden by filter)'
        : '';
      countHost.textContent = eligibleChecked + ' of ' + eligible.length + ' checked' + suffix;
    }

    if (!filtered.length) {
      host.innerHTML = '<div class="rep-ap-empty">No APs match "' + WD.esc(apSearch) + '"</div>';
      return;
    }

    filtered.sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); });

    if (apGroupBy === 'none') {
      host.innerHTML = '<div class="rep-ap-grid">' + filtered.map(apRowHtml).join('') + '</div>';
      return;
    }

    var groups = {};
    var groupOrder = [];
    filtered.forEach(function (ap) {
      var k = apGroupKey(ap, apGroupBy);
      if (!groups[k]) { groups[k] = []; groupOrder.push(k); }
      groups[k].push(ap);
    });
    groupOrder.sort(function (a, b) {
      var la = apGroupLabel(a, apGroupBy), lb = apGroupLabel(b, apGroupBy);
      return la.localeCompare(lb);
    });

    var autoCollapse = proj.accessPoints.length > 30;

    var html = '<div class="rep-ap-groups">';
    groupOrder.forEach(function (k) {
      var aps = groups[k];
      var label = apGroupLabel(k, apGroupBy);
      var checkedInGroup = aps.filter(function (a) { return !apDisabled.has(a.id); }).length;
      var collapsed = collapsedGroups.has(k) || (autoCollapse && !collapsedGroups.has('__expanded:' + k));
      var swatch = '';
      if (apGroupBy === 'color') {
        swatch = (k !== '__nocolor')
          ? '<span class="rep-ap-group-swatch" style="--swatch:' + WD.escAttr(k) + '"></span>'
          : '<span class="rep-ap-group-swatch rep-ap-group-swatch--empty"></span>';
      }
      html += '<div class="rep-ap-group' + (collapsed ? ' is-collapsed' : '') + '" data-group-key="' + WD.escAttr(k) + '">'
        +   '<div class="rep-ap-group-head" data-action="call" data-fn="toggleGroupCollapse" data-arg="' + WD.escAttr(k) + '">'
        +     '<span class="rep-ap-group-chevron">▾</span>'
        +     swatch
        +     '<span class="rep-ap-group-label">' + WD.esc(label) + '</span>'
        +     '<span class="rep-ap-group-count">' + checkedInGroup + ' of ' + aps.length + '</span>'
        +     '<button type="button" class="rep-ap-group-toggle" '
        +       'data-action="call" data-fn="toggleGroupAll" data-stop="1" data-arg="' + WD.escAttr(k) + '">Toggle all</button>'
        +   '</div>'
        +   '<div class="rep-ap-group-body">' + aps.map(apRowHtml).join('') + '</div>'
        + '</div>';
    });
    html += '</div>';
    host.innerHTML = html;
  }

  function apRowHtml(ap) {
    return '<label class="rep-ap-row">'
      + '<input type="checkbox" data-ap-id="' + WD.escAttr(ap.id) + '" '
      + (apDisabled.has(ap.id) ? '' : 'checked')
      + ' data-action-change="call" data-fn="toggleAp" data-arg-this="1">'
      + '<span class="rep-ap-row-body">'
      +   '<span class="rep-ap-row-name">' + WD.esc(ap.name) + '</span>'
      +   '<span class="rep-ap-row-model">' + WD.esc(apModelDesignator(ap)) + '</span>'
      + '</span></label>';
  }

  window.toggleAp = function (cb) {
    var id = cb.getAttribute('data-ap-id');
    if (cb.checked) apDisabled.delete(id); else apDisabled.add(id);
    var countHost = document.getElementById('apCount');
    if (countHost) {
      var count = proj.accessPoints.length - apDisabled.size;
      countHost.textContent = count + ' of ' + proj.accessPoints.length + ' checked';
    }
    if (apGroupBy !== 'none') {
      var ap = proj.accessPoints.find(function (a) { return a.id === id; });
      if (ap) {
        var k = apGroupKey(ap, apGroupBy);
        var group = document.querySelector('.rep-ap-group[data-group-key="' + CSS.escape(k) + '"]');
        if (group) {
          var apsInGroup = proj.accessPoints.filter(function (a) { return apGroupKey(a, apGroupBy) === k; });
          var checkedInGroup = apsInGroup.filter(function (a) { return !apDisabled.has(a.id); }).length;
          var badge = group.querySelector('.rep-ap-group-count');
          if (badge) badge.textContent = checkedInGroup + ' of ' + apsInGroup.length;
        }
      }
    }
    configureDirty = true;
  };

  window.setGroupBy = function (dim) {
    apGroupBy = dim;
    collapsedGroups = new Set();
    document.querySelectorAll('.rep-groupby-pill').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-group') === dim);
    });
    renderApFilter();
  };

  window.setApSearch = function (v) {
    apSearch = v || '';
    renderApFilter();
  };

  window.toggleGroupCollapse = function (key) {
    if (collapsedGroups.has(key)) {
      collapsedGroups.delete(key);
      collapsedGroups.add('__expanded:' + key);
    } else if (collapsedGroups.has('__expanded:' + key)) {
      collapsedGroups.delete('__expanded:' + key);
      collapsedGroups.add(key);
    } else {
      var autoCollapsed = proj.accessPoints.length > 30;
      if (autoCollapsed) collapsedGroups.add('__expanded:' + key);
      else collapsedGroups.add(key);
    }
    renderApFilter();
  };

  window.toggleGroupAll = function (key) {
    var apsInGroup = proj.accessPoints.filter(function (ap) { return apGroupKey(ap, apGroupBy) === key; });
    var anyChecked = apsInGroup.some(function (a) { return !apDisabled.has(a.id); });
    apsInGroup.forEach(function (a) {
      if (anyChecked) apDisabled.add(a.id); else apDisabled.delete(a.id);
    });
    configureDirty = true;
    renderApFilter();
  };

  initReportSettings();

  var REPORT_CATEGORIES = [
    { key: 'install', label: 'Installation & Placement',
      ids: ['placement', 'antenna', 'aim', 'location'] },
    { key: 'analysis', label: 'Site Analysis',
      ids: ['summary', 'coverage', 'interference', 'bom'] },
    { key: 'audit', label: 'Audit & Change',
      ids: ['audit'] },
  ];

  var expandedTemplateId = null;

  function renderTemplateGallery() {
    var host = document.getElementById('templateGallery');
    if (!host) return;
    var html = '';
    REPORT_CATEGORIES.forEach(function (cat) {
      var catReports = cat.ids.filter(function (id) { return REPORTS[id]; });
      if (!catReports.length) return;
      html += '<div class="rep-cat-group">'
        + '<h3 class="rep-cat-heading">' + WD.esc(cat.label) + '</h3>'
        + '<div class="rep-cat-list">';
      catReports.forEach(function (id) {
        var r = REPORTS[id];
        var isSoon = r.status === 'coming-soon';
        var isSelected = templateConfirmed && id === currentReportId;
        var isExpanded = expandedTemplateId === id;
        var pill = isSoon
          ? '<span class="rep-template-pill soon">Coming soon</span>'
          : (isSelected
            ? '<span class="rep-template-pill selected">Selected</span>'
            : '<span class="rep-template-pill available">Available</span>');

        var sections = (r.sections || []).map(function (s) {
          return '<li class="rep-template-section">'
            + '<span class="rep-template-section-icon">' + WD.esc(s.icon || '·') + '</span>'
            + '<span class="rep-template-section-body">'
            +   '<b>' + WD.esc(s.title) + '</b>'
            +   '<span>' + WD.esc(s.description || '') + '</span>'
            + '</span></li>';
        }).join('');

        var bestFor = r.bestFor
          ? '<div class="rep-template-best-for"><b>Best for:</b> ' + WD.esc(r.bestFor) + '</div>'
          : '';

        var cta = isSoon
          ? '<div class="rep-template-soon-note">In progress — check back soon</div>'
          : '<div class="rep-template-cta"><button type="button" class="btn btn-blue" '
            + 'data-action="call" data-fn="selectReport" data-stop="1" data-arg="' + WD.escAttr(id) + '">'
            + (isSelected ? 'Continue with this template' : 'Use this template')
            + '</button></div>';

        var detailToggle = '<button type="button" class="rep-template-expand" data-action="call" data-fn="toggleTemplateDetail" data-stop="1" data-arg="' + WD.escAttr(id) + '">'
          + (isExpanded ? '▾ Less' : '▸ Details') + '</button>';

        html += '<div class="rep-template-card tpl-' + WD.escAttr(id)
          + (isSoon ? ' is-coming-soon' : '')
          + (isSelected ? ' is-selected' : '')
          + (isExpanded ? ' is-expanded' : '')
          + '"' + (isSoon ? '' : ' data-action="call" data-fn="selectReport" data-arg="' + WD.escAttr(id) + '"')
          + '>'
          +   '<div class="rep-template-card-top">'
          +     '<div class="rep-template-preview">' + (r.preview || '') + '</div>'
          +     '<div class="rep-template-titles">'
          +       pill
          +       '<h3 class="rep-template-title">' + WD.esc(r.label) + '</h3>'
          +       '<p class="rep-template-subtitle">' + WD.esc(r.description || '') + '</p>'
          /* Who it is for and how many pages land on the desk, on the face of
             the card rather than behind the Details toggle. Nine reports that
             all put APs on a floor plan cannot be told apart by expanding nine
             cards one at a time - and the thing that separates them is not
             what they contain, it is who reads the sheet. */
          +       (r.readBy ? '<p class="rep-template-facts">'
                + '<span class="rep-template-fact"><b>For</b> ' + WD.esc(r.readBy) + '</span>'
                + (r.output ? '<span class="rep-template-fact"><b>You get</b> '
                    + WD.esc(r.output) + '</span>' : '')
                + '</p>' : '')
          +     '</div>'
          +     '<div class="rep-template-actions">'
          +       detailToggle
          +     '</div>'
          +   '</div>'
          +   '<div class="rep-template-detail"' + (isExpanded ? '' : ' hidden') + '>'
          +     (sections ? '<div class="rep-template-sections-head">What\'s inside</div>'
            + '<ul class="rep-template-sections">' + sections + '</ul>' : '')
          +     bestFor
          +     cta
          +   '</div>'
          + '</div>';
      });
      html += '</div></div>';
    });

    var uncategorized = Object.keys(REPORTS).filter(function (id) {
      return !REPORT_CATEGORIES.some(function (cat) { return cat.ids.indexOf(id) !== -1; });
    });
    if (uncategorized.length) {
      html += '<div class="rep-cat-group"><h3 class="rep-cat-heading">Other</h3><div class="rep-cat-list">';
      uncategorized.forEach(function (id) {
        var r = REPORTS[id];
        html += '<div class="rep-template-card tpl-' + WD.escAttr(id) + '" data-action="call" data-fn="selectReport" data-arg="' + WD.escAttr(id) + '">'
          + '<div class="rep-template-card-top"><div class="rep-template-preview">' + (r.preview || '') + '</div>'
          + '<div class="rep-template-titles"><span class="rep-template-pill available">Available</span>'
          + '<h3 class="rep-template-title">' + WD.esc(r.label) + '</h3>'
          + '<p class="rep-template-subtitle">' + WD.esc(r.description || '') + '</p>'
          + '</div></div></div>';
      });
      html += '</div></div>';
    }

    host.innerHTML = html;
    renderSettingsBanner();
  }

  window.toggleTemplateDetail = function (id) {
    expandedTemplateId = expandedTemplateId === id ? null : id;
    renderTemplateGallery();
  };

  /* Predictive Design and the AP Placement Map were two templates whose only
     real difference was whether large floors got split - which is a setting,
     not a template. They are one now, and anything still asking for the old id
     lands on the survivor rather than on an error.

     Worth recording what former Predictive users gain: its floor sections were
     plain blocks with no page key, so they never had per-page orientation, a
     key plan or match lines. All three come with the merge. The one thing it
     had that the map did not - the summary strip - came across as an option. */
  var RETIRED_REPORTS = { predictive: 'placement' };

  window.selectReport = function (id) {
    id = RETIRED_REPORTS[id] || id;
    if (!REPORTS[id]) return;
    if (REPORTS[id].status === 'coming-soon') return;
    if (id !== currentReportId) {
      currentReportId = id;
      currentOpts = {};
      optOverrides = {};
      // Saved options are inherited, not overrides, so optOverrides stays
      // empty - the card footer is what says they came from settings.
      var saved = reportOptionDefaults(id);
      Object.keys(saved).forEach(function (k) {
        // `collectSidebarValues` stops these two being written here, but a
        // settings file from before that guard can still hold them - and a
        // stored copy that is read is a second store however it got there.
        // Skipping them on the way in is what makes "one copy" true of the
        // data rather than only of the code that writes it.
        if (PERSON_LEVEL_OPTS.indexOf(k) !== -1) return;
        currentOpts[k] = saved[k];
      });
    }
    templateConfirmed = true;
    configureDirty = true;
    renderTemplateGallery();
    renderReportPreview();
    renderReportOpts();
    renderCoverSummary();
    renderApFilter();
    /* The tab name is the file name the print dialog offers, so it follows the
       report you have picked rather than the one you last rendered. Measured
       before this line existed: picking a report left the title naming the
       previous one until a render replaced it, so the whole select and
       configure stage sat under a stale name. The app's own Print button syncs
       first and was never wrong - this is the tab, and Ctrl+P. */
    syncDocTitle();
    goStage('configure');
  };

  function renderOptHtml(opt) {
    var disabled = typeof opt.disabledWhen === 'function' ? !!opt.disabledWhen(proj) : false;
    var desc = opt.description || '';
    var reason = disabled && opt.disabledReason ? opt.disabledReason(proj) : '';
    if (reason) desc = (desc ? desc + ' ' : '') + '— ' + reason;
    if (opt.type === 'grid-button') {
      var gc = (currentOpts.segCols || '') + '';
      var gr = (currentOpts.segRows || '') + '';
      var gridLabel = (gc && gr) ? gc + ' × ' + gr : 'Auto';
      if (currentOpts.cropBoxes && Object.keys(currentOpts.cropBoxes).length) gridLabel += ' (cropped)';
      return '<div class="rep-check with-desc">'
        + '<span class="rep-check-body">'
        +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        + '</span>'
        + '<button type="button" class="btn btn-secondary btn-sm rep-btn-right" '
        + 'data-action="call" data-fn="openGridConfig">' + gridLabel + '</button>'
        + '</div>';
    }
    /* Says how many floors are set up, because that is the only question
       anyone has at this control - "is this on for this project?" - and
       because the checkbox above it does nothing until at least one is. */
    if (opt.type === 'gridref-button') {
      var nFloors = (proj.floorPlans || []).length;
      var nGrid = Object.keys(_floorGrids).length;
      var gridRefLabel = nGrid
        ? nGrid + ' of ' + nFloors + ' floor' + (nFloors === 1 ? '' : 's')
        : 'Not set up';
      return '<div class="rep-check with-desc">'
        + '<span class="rep-check-body">'
        +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        + '</span>'
        + '<button type="button" class="btn btn-secondary btn-sm rep-btn-right" '
        + 'data-action="call" data-fn="openGridRef">' + WD.esc(gridRefLabel) + '</button>'
        + '</div>';
    }
    /* The before-file. The button carries the chosen file's name rather than
       a fixed word, because "which file am I comparing against" is the only
       question at this control and reading it off the button beats opening a
       dialog to find out. A refusal is shown here too, in the sentence the
       loader wrote - a file rejected silently reads as a picker that does
       nothing. */
    if (opt.type === 'baseline-button') {
      var chosen = !!baseline;
      var btnLabel = chosen ? baselineName : 'Choose the earlier .esx…';
      return '<div class="rep-check with-desc">'
        + '<span class="rep-check-body">'
        +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        +   (baselineError
              ? '<span class="rep-check-desc rep-warn">' + WD.esc(baselineError) + '</span>'
              : '')
        +   (chosen
              ? '<span class="rep-check-desc">Comparing <b>' + WD.esc(fileName)
                + '</b> against <b>' + WD.esc(baselineName) + '</b>, in that order: '
                + 'the file open in this tool is the "after".</span>'
              : '')
        + '</span>'
        + '<span class="rep-btn-right">'
        + '<button type="button" class="btn btn-secondary btn-sm" '
        + 'data-action="call" data-fn="chooseBaseline">' + WD.esc(btnLabel) + '</button>'
        + (chosen
            ? ' <button type="button" class="btn btn-secondary btn-sm" '
              + 'data-action="call" data-fn="clearBaseline">Clear</button>'
            : '')
        + '</span>'
        + '</div>';
    }
    if (opt.type === 'text') {
      var textVal = (opt.id in currentOpts) ? (currentOpts[opt.id] || '') : (opt.default || '');
      var isSetting = SETTING_IDS.indexOf(opt.id) !== -1;
      return '<div class="rep-check with-desc">'
        + '<span class="rep-check-body">'
        +   '<label class="rep-check-label" for="opt-' + WD.escAttr(opt.id) + '">' + WD.esc(opt.label) + '</label>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        +   (isSetting ? settingBadgeHtml(opt.id) : '')
        + '</span>'
        + '<input type="text" id="opt-' + WD.escAttr(opt.id) + '" data-opt-id="' + WD.escAttr(opt.id) + '" data-opt-type="text" '
        + 'value="' + WD.escAttr(textVal) + '" placeholder="' + WD.escAttr(opt.placeholder || '') + '" '
        + 'class="rep-input-text" '
        + 'data-action-change="call" data-action-input="call" data-fn="setOpt" data-arg-this="1">'
        + '</div>';
    }
    if (opt.type === 'select') {
      var selVal = (opt.id in currentOpts) ? currentOpts[opt.id] : optStartValue(opt);
      return '<div class="rep-check with-desc">'
        + '<span class="rep-check-body">'
        +   '<label class="rep-check-label" for="opt-' + WD.escAttr(opt.id) + '">' + WD.esc(opt.label) + '</label>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        + '</span>'
        + '<select id="opt-' + WD.escAttr(opt.id) + '" data-opt-id="' + WD.escAttr(opt.id) + '" '
        + 'data-opt-type="select" class="rep-input-text" data-action-change="call" data-fn="setOpt" data-arg-this="1">'
        + (opt.options || []).map(function (o) {
            return '<option value="' + WD.escAttr(o.value) + '"'
              + (String(o.value) === String(selVal) ? ' selected' : '') + '>'
              + WD.esc(o.label) + '</option>';
          }).join('')
        + '</select>'
        + '</div>';
    }
    if (opt.type === 'number') {
      var numVal = (opt.id in currentOpts) ? currentOpts[opt.id] : (opt.default || '');
      return '<div class="rep-check with-desc' + (disabled ? ' is-disabled' : '') + '">'
        + '<span class="rep-check-body">'
        +   '<label class="rep-check-label" for="opt-' + WD.escAttr(opt.id) + '">' + WD.esc(opt.label) + '</label>'
        +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
        + '</span>'
        + '<input type="number" id="opt-' + WD.escAttr(opt.id) + '" data-opt-id="' + WD.escAttr(opt.id) + '" data-opt-type="number" '
        + 'value="' + WD.escAttr(String(numVal)) + '" min="' + (opt.min || 1) + '" max="' + (opt.max || 20) + '" '
        + 'class="rep-input-sm" '
        + (disabled ? 'disabled' : '')
        + ' data-action-change="call" data-action-input="call" data-fn="setOpt" data-arg-this="1">'
        + '</div>';
    }
    var checked = (opt.id in currentOpts) ? currentOpts[opt.id] : !!opt.default;
    return '<label class="rep-check with-desc' + (disabled ? ' is-disabled' : '') + '"'
      + (disabled ? ' title="' + WD.escAttr(reason || 'Not available for this project') + '"' : '') + '>'
      + '<input type="checkbox" data-opt-id="' + WD.escAttr(opt.id) + '" '
      + (checked ? 'checked' : '') + (disabled ? ' disabled' : '')
      + ' data-action-change="call" data-fn="setOpt" data-arg-this="1">'
      + '<span class="rep-check-body">'
      +   '<span class="rep-check-label">' + WD.esc(opt.label) + '</span>'
      +   (desc ? '<span class="rep-check-desc">' + WD.esc(desc) + '</span>' : '')
      + '</span></label>';
  }

  function renderReportOpts() {
    var host = document.getElementById('reportOptsSlot');
    var detailsHost = document.getElementById('reportDetailsSlot');
    if (!host) return;
    seedSettingDefaults();
    var r = currentReport();
    var apCard = document.getElementById('apFilterCard');
    if (apCard) apCard.hidden = !!r.noApFilter;

    var settingItems = [];
    var optionItems = [];
    (r.sidebar || []).forEach(function (opt) {
      if (SETTING_IDS.indexOf(opt.id) !== -1) settingItems.push(opt);
      else optionItems.push(opt);
    });

    // ── Left card: Your details + Cover page ──
    if (detailsHost) {
      /* Only four of the eight reports carry identity fields, and the other
         four were getting a "Your details" heading with nothing under it,
         sitting directly on top of the Cover page heading. An empty heading
         reads as a section that failed to load, so the card is titled for
         what it actually contains. */
      var dHtml = '';
      if (settingItems.length) {
        dHtml += '<div class="rep-config-card-head">'
          + '<span class="rep-config-icon">📝</span>'
          + '<span>Your details</span></div>';
        settingItems.forEach(function (opt) { dHtml += renderOptHtml(opt); });
        dHtml += '<div class="rep-opts-subhead-note">'
          + 'From your report settings. Changing one here affects this report only. '
          + '<button type="button" class="rep-remembered-clear" data-action="call" data-fn="openReportSettings">Edit defaults…</button>'
          + '</div>'
          + '<div class="rep-opts-divider"></div>';
      }
      dHtml += '<div class="rep-config-card-head"'
        + (settingItems.length ? ' style="margin-top:4px"' : '') + '>'
        + '<span class="rep-config-icon">🖼️</span>'
        + '<span>Cover page</span></div>'
        + '<label class="rep-check">'
        + '<input type="checkbox" id="optCover" checked data-action-change="call" data-fn="markConfigDirty">'
        + '<span>Include cover page</span></label>'
        + '<div class="rep-cover-summary" id="coverSummary"></div>'
        + '<div class="rep-logo-row">'
        + '<button class="btn btn-secondary rep-logo-btn" data-action="call" data-fn="openReportSettings">Cover image &amp; defaults…</button>'
        + '</div>';
      detailsHost.innerHTML = dHtml;
    }

    // ── Right card: Report options ──
    if (!optionItems.length) {
      host.innerHTML = '<div class="rep-config-card-head">'
        + '<span class="rep-config-icon">📋</span>'
        + '<span>' + WD.esc(r.docName) + ' options</span></div>'
        + '<div class="rep-empty-small">No extra options for this report.</div>';
      return;
    }

    var html = '<div class="rep-config-card-head">'
      + '<span class="rep-config-icon">📋</span>'
      + '<span>' + WD.esc(r.docName) + ' options</span></div>';

    optionItems.forEach(function (opt) { html += renderOptHtml(opt); });

    var hasReportOpts = optionItems.some(function (o) {
      return o.id.charAt(0) !== '_' && o.type !== 'text';
    });
    if (hasReportOpts) {
      var savedCount = Object.keys(reportOptionDefaults(currentReportId)).length;
      html += '<div class="rep-remembered rep-remembered-opts">'
        + '<span class="rep-remembered-state">'
        + (savedCount ? 'Your saved defaults.' : 'Using the shipped defaults.')
        + '</span>'
        + '<span id="autoSaveIndicator" class="rep-autosave-dot"></span>'
        + (savedCount ? '<button type="button" class="rep-remembered-clear" '
            + 'data-action="call" data-fn="clearReportOptionDefaults">Reset to shipped defaults</button>' : '')
        + '</div>';
    }

    host.innerHTML = html;
  }
  window.setOpt = function (cb) {
    var id = cb.getAttribute('data-opt-id');
    var optType = cb.getAttribute('data-opt-type');
    if (optType === 'number') {
      currentOpts[id] = cb.value === '' ? '' : parseInt(cb.value, 10);
    } else if (optType === 'select') {
      /* Just this report. Units and section size used to write the suite-wide
         preference from here as well, so switching one report to metres made
         metres the starting point for every report afterwards - the same
         implicit write that made the default wall template whatever was last
         applied. Both are set on the Settings page now, under Report. */
      currentOpts[id] = cb.value;
    } else if (optType === 'text') {
      currentOpts[id] = cb.value;
      if (SETTING_IDS.indexOf(id) !== -1) {
        if (cb.value === settingDefault(id)) delete optOverrides[id];
        else optOverrides[id] = true;
        refreshSettingBadge(id);
      }
    } else {
      currentOpts[id] = cb.checked;
    }
    configureDirty = true;
    if (id.charAt(0) !== '_' && SETTING_IDS.indexOf(id) === -1 && optType !== 'text') {
      scheduleAutoSave();
    }
    // Re-rendering the whole card would take the focus off the control that
    // was just clicked, so only the sentence that went stale is rewritten.
    refreshRememberedState();
    if (id === 'inclOmni' || id === 'inclDirectional') renderApFilter();
  };

  function refreshRememberedState() {
    var wrap = document.querySelector('.rep-remembered-opts');
    if (!wrap || !currentReportId) return;
    var savedCount = Object.keys(reportOptionDefaults(currentReportId)).length;
    var el = wrap.querySelector('.rep-remembered-state');
    if (el) el.textContent = savedCount ? 'Your saved defaults.' : 'Using the shipped defaults.';
    var existing = wrap.querySelector('.rep-remembered-clear');
    if (savedCount && !existing) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'rep-remembered-clear';
      btn.textContent = 'Reset to shipped defaults';
      btn.setAttribute('onclick', 'clearReportOptionDefaults()');
      wrap.appendChild(btn);
    } else if (!savedCount && existing) {
      existing.remove();
    }
  }

  /* ── Column grid references ────────────────────────────────────────────

     A warehouse section page shows an AP floating in empty slab with nothing
     to locate it against. Construction crews locate everything off the column
     grid - lettered one way, numbered the other, bubbled on the drawing - so a
     grid reference is the coordinate system the person on the ladder already
     has. This is the third of the three AEC conventions, after the Key Plan
     (v2.60.0) and match lines (v2.62.0).

     **Nothing is read off the drawing.** Finding the bubbles automatically
     needs circle detection, OCR of the letters and numbers, and line tracing.
     There is no OCR in this stack, and a mis-read bubble produces a
     confidently wrong reference - which is worse than none, because the
     installer has no way to tell. So the grid is *declared*: two clicks and
     two labels.

     Two is enough because a column grid is regular by construction - that is
     what a structural bay is. Given intersection A-1 here and G-7 there, the
     spacing and the origin follow, and the grid extends across the plan.

     **What two points cannot settle is which axis the letters run along.**
     A-1 and G-7 is six letter-steps and six number-steps, and that is equally
     consistent with letters running across the plan or down it. Rather than
     guess, the picker draws the grid it derived over the floor plan and offers
     one switch. Being able to see it is also what covers the cases this
     deliberately cannot model - an interrupted bay, a skewed or rotated grid,
     a building with two grids of its own - because a grid that does not sit on
     the drawn columns is obvious on sight, and the answer there is to turn the
     reference off for that floor rather than print something plausible. */

  // A, B ... Z, AA, AB ... - the spreadsheet sequence, which is what drawings
  // use once a building runs past 26 lines.
  function gridColumnIndex(label) {
    var s = String(label == null ? '' : label).trim().toUpperCase();
    if (!/^[A-Z]+$/.test(s)) return null;
    var n = 0;
    for (var i = 0; i < s.length; i++) n = n * 26 + (s.charCodeAt(i) - 64);
    return n - 1;
  }

  function gridColumnLabel(index) {
    var n = Math.round(index);
    if (!isFinite(n) || n < 0) return '';
    var out = '';
    n += 1;
    while (n > 0) {
      var rem = (n - 1) % 26;
      out = String.fromCharCode(65 + rem) + out;
      n = Math.floor((n - 1) / 26);
    }
    return out;
  }

  /* Split "A-1", "A1", "a 1" into its two halves. Drawings are written every
     one of those ways and the difference is not meaningful. */
  function parseGridLabel(text) {
    var m = /^\s*([A-Za-z]+)\s*[-_/ ]?\s*(\d+)\s*$/.exec(String(text || ''));
    if (!m) return null;
    var col = gridColumnIndex(m[1]);
    if (col == null) return null;
    return { col: col, row: parseInt(m[2], 10) };
  }

  /* Turn two labelled intersections into something that can answer "which
     grid square is this point in".

     Returns `{ok: false, reason}` rather than throwing, because every reason
     is something to say on screen: a reference that is quietly wrong is the
     failure this whole feature is written around. */
  function buildGridSolver(a, b, lettersAxis, span) {
    if (!a || !b) return { ok: false, reason: 'Two intersections are needed.' };
    var dCol = b.col - a.col;
    var dRow = b.row - a.row;
    if (!dCol) {
      return { ok: false, reason: 'Both points are on the same lettered line, '
        + 'so there is nothing to measure the letter spacing against. Pick two '
        + 'intersections that differ in both directions.' };
    }
    if (!dRow) {
      return { ok: false, reason: 'Both points are on the same numbered line, '
        + 'so there is nothing to measure the number spacing against. Pick two '
        + 'intersections that differ in both directions.' };
    }

    var lettersAlongX = lettersAxis !== 'y';
    var dx = b.x - a.x, dy = b.y - a.y;
    // Letters along x means the letter step is an x distance and the number
    // step is a y distance; along y it is the other way round.
    var colStep = lettersAlongX ? dx / dCol : dy / dCol;
    var rowStep = lettersAlongX ? dy / dRow : dx / dRow;

    if (!isFinite(colStep) || !isFinite(rowStep) || !colStep || !rowStep) {
      return { ok: false, reason: 'Those two points do not describe a grid.' };
    }
    /* Two clicks almost on top of each other, which is a mis-click rather than
       a building: any error in either one is then multiplied across the whole
       plan.

       **Measured against the plan rather than in plan units.** A floor plan is
       in whatever units it was authored in - a raster is in thousands of
       pixels, a vector import can be in single figures - so "less than one
       unit" means something different on every drawing, and on some of them it
       means nothing at all. `span` is the floor's own width and height, and
       the two points have to be at least a fiftieth of it apart on each axis.
       Without a span there is no guard, because a number that cannot be
       interpreted is worse than none. */
    if (span && span.w && span.h) {
      var minX = Math.abs(span.w) / 50, minY = Math.abs(span.h) / 50;
      if (Math.abs(dx) < minX || Math.abs(dy) < minY) {
        return { ok: false, reason: 'Those two points are too close together to '
          + 'measure a bay from. Pick intersections further apart.' };
      }
    }

    return {
      ok: true,
      lettersAlongX: lettersAlongX,
      colStep: colStep,
      rowStep: rowStep,
      // Where line "A" and line "1" sit, in plan units.
      colOrigin: (lettersAlongX ? a.x : a.y) - a.col * colStep,
      rowOrigin: (lettersAlongX ? a.y : a.x) - (a.row - 1) * rowStep,
    };
  }

  /* The nearest intersection, which is how a grid reference is spoken: "it is
     at C-4" sends somebody to a column they can see and stand under. A bay is
     forty-odd feet, so the worst case is half a bay of walking - against no
     reference at all, which is what the section pages give them today. */
  function gridRefForPoint(solver, x, y) {
    if (!solver || !solver.ok) return '';
    var along = solver.lettersAlongX ? x : y;
    var across = solver.lettersAlongX ? y : x;
    var col = Math.round((along - solver.colOrigin) / solver.colStep);
    var row = Math.round((across - solver.rowOrigin) / solver.rowStep) + 1;
    if (col < 0 || row < 1) return '';
    var label = gridColumnLabel(col);
    return label ? label + '-' + row : '';
  }

  /* The calibrations for the open project, and the solvers built from them.

     Loaded once when a project opens and kept in memory: a report redraws on
     every option change, and a disk round trip per redraw would be felt. The
     picker replaces this map when it saves, so nothing has to be re-fetched. */
  var _floorGrids = {};
  var _floorSolvers = {};

  function resetFloorGrids(map) {
    _floorGrids = map || {};
    _floorSolvers = {};
  }

  async function loadFloorGrids() {
    resetFloorGrids({});
    if (!settingsAvailable || !proj.projectId) return;
    try {
      var res = await WD.api('report/grid/get', { projectId: proj.projectId });
      if (res && res.ok) resetFloorGrids(res.floors || {});
    } catch (e) { /* uncalibrated is a legal state, not an error */ }
  }

  /* The solver for one floor, or null. Built on first use and cached, because
     an AP table asks per row and a large floor is several hundred rows. */
  function gridSolverForFloor(floorId) {
    if (!floorId) return null;
    if (Object.prototype.hasOwnProperty.call(_floorSolvers, floorId)) {
      return _floorSolvers[floorId];
    }
    var saved = _floorGrids[floorId];
    var solver = null;
    if (saved && saved.a && saved.b) {
      var built = buildGridSolver(saved.a, saved.b, saved.lettersAxis);
      solver = built.ok ? built : null;
    }
    _floorSolvers[floorId] = solver;
    return solver;
  }

  function anyFloorHasGrid() {
    return Object.keys(_floorGrids).length > 0;
  }

  /* The reference for one access point, or '' - never a placeholder that could
     be mistaken for a bay. An AP with no coordinates, on a floor with no
     calibration, or outside the lettered area all give nothing, and the table
     prints a dash. */
  function gridRefForAp(ap) {
    var loc = ap && ap.location;
    var c = loc && loc.coord;
    if (!c) return '';
    var solver = gridSolverForFloor(loc.floorPlanId);
    if (!solver) return '';
    return gridRefForPoint(solver, c.x, c.y);
  }

  /* Whether the Grid column appears at all. Both have to be true: the option
     is on, and at least one floor in this project has been calibrated. A
     column of dashes on every row of every table is worse than no column,
     because it reads as a broken feature rather than an unused one. */
  function showsGridColumn(opts) {
    return !!(opts && opts.gridRef) && anyFloorHasGrid();
  }

  window.WDGrid = {
    columnIndex: gridColumnIndex,
    columnLabel: gridColumnLabel,
    parseLabel: parseGridLabel,
    solver: buildGridSolver,
    refFor: gridRefForPoint,
  };

  // ── Column grid picker ──
  //
  // Two clicks and two labels per floor. It shares the section-grid modal's
  // canvas idiom - same container classes, same wheel-zoom and space-pan
  // helpers - rather than growing a fourth way of looking at a floor plan.
  //
  // **The check is the drawing, not a dialog.** Once both points have labels
  // the derived grid is drawn over the plan, so a grid that does not sit on
  // the columns is obvious on sight. That is what covers the cases two points
  // cannot describe - an interrupted bay, a rotated plan, a building with two
  // grids of its own - without pretending to detect them.

  var _grFloorIdx = 0;
  var _grZoom = 1, _grPanX = 0, _grPanY = 0;
  var _grPanState = null, _grSpaceUnsub = null;
  var _grPicking = '';                 // 'a', 'b' or '' when not picking
  var _grPoints = { a: null, b: null };
  var _grAxis = 'x';

  window.openGridRef = function () {
    var modal = document.getElementById('gridRefModal');
    if (!modal) return;
    if (!settingsAvailable) {
      showToast('The column grid is saved on this machine, and there is no '
                + 'server behind this page.', 'warn');
      return;
    }
    var fps = proj.floorPlans || [];
    if (!fps.length) { showToast('No floor plans in this project.', 'warn'); return; }

    var sel = document.getElementById('gridRefFloorSelect');
    sel.innerHTML = '';
    fps.forEach(function (f, i) {
      var opt = document.createElement('option');
      opt.value = i;
      opt.textContent = (f.name || ('Floor ' + (i + 1)))
        + (_floorGrids[f.id] ? '  ✓' : '');
      sel.appendChild(opt);
    });
    _grFloorIdx = 0;
    sel.value = '0';
    loadGridRefFloor();
    modal.hidden = false;
  };

  window.closeGridRef = function () {
    var modal = document.getElementById('gridRefModal');
    if (modal) modal.hidden = true;
    releaseGridRefKeys();
    _grPicking = '';
    // The button under the checkbox counts calibrated floors, so it is stale
    // the moment one is saved or cleared.
    if (typeof renderReportOpts === 'function') renderReportOpts();
  };

  /* Put the floor's saved calibration back on screen, or clear the fields. */
  function loadGridRefFloor() {
    var fp = proj.floorPlans[_grFloorIdx];
    _grPicking = '';
    _grPoints = { a: null, b: null };
    _grAxis = 'x';
    var saved = fp && _floorGrids[fp.id];
    if (saved) {
      _grPoints = { a: saved.a, b: saved.b };
      _grAxis = saved.lettersAxis === 'y' ? 'y' : 'x';
    }
    var axisSel = document.getElementById('gridRefAxis');
    if (axisSel) axisSel.value = _grAxis;
    ['a', 'b'].forEach(function (k) {
      var input = document.getElementById('gridRefLabel' + k.toUpperCase());
      if (!input) return;
      var pt = _grPoints[k];
      input.value = pt ? (gridColumnLabel(pt.col) + '-' + pt.row) : '';
    });
    _grZoom = 1; _grPanX = 0; _grPanY = 0;
    updateGridRefPreview();
  }

  window.gridRefFloorChanged = function (sel) {
    _grFloorIdx = parseInt(sel.value, 10) || 0;
    loadGridRefFloor();
  };

  window.gridRefAxisChanged = function (sel) {
    _grAxis = sel.value === 'y' ? 'y' : 'x';
    updateGridRefPreview();
  };

  window.gridRefPick = function (which) {
    _grPicking = which;
    updateGridRefPreview();
  };

  window.gridRefLabelChanged = function (which, input) {
    var parsed = parseGridLabel(input.value);
    var pt = _grPoints[which];
    if (pt && parsed) { pt.col = parsed.col; pt.row = parsed.row; }
    else if (pt) { pt.col = null; pt.row = null; }
    updateGridRefPreview();
  };

  /* Both points placed, both labelled, and the two labels differ in both
     directions. Returns the solver or the reason there isn't one. */
  function currentGridRefSolver() {
    var a = _grPoints.a, b = _grPoints.b;
    if (!a || !b) {
      return { ok: false, reason: a || b
        ? 'Click the second intersection.'
        : 'Click an intersection on the plan, then type what the drawing calls it.' };
    }
    if (a.col == null || b.col == null) {
      return { ok: false, reason: 'Both intersections need a label, such as A-1.' };
    }
    var fp = proj.floorPlans[_grFloorIdx];
    return buildGridSolver(a, b, _grAxis,
                           fp ? { w: fp.width, h: fp.height } : null);
  }

  function updateGridRefPreview() {
    var fp = proj.floorPlans[_grFloorIdx];
    if (!fp) return;
    var url = floorPlanImageUrl(fp) || '';
    var W = fp.width || 1, H = fp.height || 1;
    var vw = 1000, vh = 1000 * (H / W);
    var toView = function (v, span) { return v / span * (span === W ? vw : vh); };

    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + vw + ' ' + vh + '" '
      + 'class="grid-svg-fill" id="gridRefSvg" '
      + 'data-dw="' + vw + '" data-dh="' + vh + '">';
    svg += '<image href="' + WD.escAttr(url) + '" width="' + vw + '" height="' + vh + '" />';

    var solved = currentGridRefSolver();

    /* The derived grid, drawn so it can be compared with the columns in the
       drawing underneath. Lines are extended across the whole sheet rather
       than only between the two picked points, because the question being
       answered is "does this grid fit the building", not "did the two clicks
       land". */
    if (solved.ok) {
      var lineW = Math.max(1.5, vw * 0.0022);
      var fontSize = Math.max(10, vw * 0.016);
      var lines = '', labels = '';
      var alongSpan = solved.lettersAlongX ? W : H;
      var acrossSpan = solved.lettersAlongX ? H : W;

      /* Which lines fall on the sheet, worked out rather than searched for.

         The first version walked a fixed range with a tangle of continue and
         break conditions, and drew any line within one bay of the edge - so a
         spacing that does not divide the sheet evenly put columns outside the
         drawing. Photographed on a 1600-unit plan with 183-unit bays: it drew
         A..J, and I and J were off the plan entirely. */
      var lineIndexes = function (origin, step, span) {
        var first = Math.ceil((0 - origin) / step);
        var last = Math.floor((span - origin) / step);
        if (step < 0) { var t = first; first = last; last = t; }
        first = Math.max(0, first);
        // A mis-calibration must not ask for ten thousand lines.
        last = Math.min(last, first + 200);
        return { first: first, last: last };
      };

      var colRange = lineIndexes(solved.colOrigin, solved.colStep, alongSpan);
      for (var ci = colRange.first; ci <= colRange.last; ci++) {
        var at = solved.colOrigin + ci * solved.colStep;
        var lx = solved.lettersAlongX ? toView(at, W) : 0;
        var ly = solved.lettersAlongX ? 0 : toView(at, H);
        lines += solved.lettersAlongX
          ? '<line x1="' + lx + '" y1="0" x2="' + lx + '" y2="' + vh + '"/>'
          : '<line x1="0" y1="' + ly + '" x2="' + vw + '" y2="' + ly + '"/>';
        labels += '<text x="' + (solved.lettersAlongX ? lx + 4 : 4) + '" '
          + 'y="' + (solved.lettersAlongX ? fontSize : ly - 4) + '" '
          + 'font-size="' + fontSize + '">' + WD.esc(gridColumnLabel(ci)) + '</text>';
      }

      var rowRange = lineIndexes(solved.rowOrigin, solved.rowStep, acrossSpan);
      for (var ri = rowRange.first; ri <= rowRange.last; ri++) {
        var rat = solved.rowOrigin + ri * solved.rowStep;
        var rx = solved.lettersAlongX ? 0 : toView(rat, W);
        var ry = solved.lettersAlongX ? toView(rat, H) : 0;
        lines += solved.lettersAlongX
          ? '<line x1="0" y1="' + ry + '" x2="' + vw + '" y2="' + ry + '"/>'
          : '<line x1="' + rx + '" y1="0" x2="' + rx + '" y2="' + vh + '"/>';
        labels += '<text x="' + (solved.lettersAlongX ? 4 : rx + 4) + '" '
          + 'y="' + (solved.lettersAlongX ? ry - 4 : fontSize) + '" '
          + 'font-size="' + fontSize + '">' + (ri + 1) + '</text>';
      }
      svg += '<g class="grid-ref-lines" stroke-width="' + lineW + '">' + lines + '</g>'
           + '<g class="grid-ref-labels">' + labels + '</g>';
    }

    // The two picked intersections, on top of the grid so they stay findable.
    ['a', 'b'].forEach(function (k) {
      var pt = _grPoints[k];
      if (!pt) return;
      var px = toView(pt.x, W), py = toView(pt.y, H);
      var r = Math.max(6, vw * 0.008);
      svg += '<g class="grid-ref-pin' + (_grPicking === k ? ' is-picking' : '') + '">'
        + '<circle cx="' + px + '" cy="' + py + '" r="' + r + '"/>'
        + '<line x1="' + (px - r * 2) + '" y1="' + py + '" x2="' + (px + r * 2) + '" y2="' + py + '"/>'
        + '<line x1="' + px + '" y1="' + (py - r * 2) + '" x2="' + px + '" y2="' + (py + r * 2) + '"/>'
        + '</g>';
    });

    svg += '</svg>';
    document.getElementById('gridRefPreviewImage').innerHTML = svg;

    var container = document.getElementById('gridRefPreviewContainer');
    if (container) container.classList.toggle('is-picking', !!_grPicking);

    // What the two buttons say, so the step you are on is on the control.
    ['a', 'b'].forEach(function (k) {
      var btn = document.getElementById('gridRefPick' + k.toUpperCase());
      if (!btn) return;
      var n = k === 'a' ? '1' : '2';
      btn.textContent = _grPicking === k
        ? 'Click the plan…'
        : (_grPoints[k] ? n + '. Move this point'
                        : n + (k === 'a' ? '. Click an intersection' : '. Click another'));
      btn.classList.toggle('is-active', _grPicking === k);
    });

    var status = document.getElementById('gridRefStatus');
    if (status) {
      status.textContent = solved.ok
        ? 'Grid drawn. Check it sits on the columns in the drawing.'
        : (solved.reason || '');
      status.classList.toggle('is-warn', !solved.ok);
    }
    var save = document.getElementById('gridRefSaveBtn');
    if (save) save.disabled = !solved.ok;

    applyGridRefZoom();
    bindGridRefCanvas();
  }

  function applyGridRefZoom() {
    var svgEl = document.getElementById('gridRefSvg');
    if (!svgEl) return;
    svgEl.style.transform = 'translate(' + _grPanX + 'px,' + _grPanY + 'px) scale(' + _grZoom + ')';
    svgEl.style.transformOrigin = '0 0';
  }

  window.resetGridRefZoom = function () {
    _grZoom = 1; _grPanX = 0; _grPanY = 0;
    applyGridRefZoom();
  };

  function bindGridRefCanvas() {
    var container = document.getElementById('gridRefPreviewContainer');
    if (!container || container._grBound) return;
    container._grBound = true;

    container.addEventListener('wheel', function (e) {
      e.preventDefault();
      var svgEl = document.getElementById('gridRefSvg');
      if (!svgEl) return;
      var rect = svgEl.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var sx = (mx - _grPanX) / _grZoom, sy = (my - _grPanY) / _grZoom;
      var newZoom = Math.max(1, Math.min(8, _grZoom + (e.deltaY > 0 ? -0.15 : 0.15) * _grZoom));
      if (newZoom <= 1.01) newZoom = 1;
      _grPanX = mx - sx * newZoom;
      _grPanY = my - sy * newZoom;
      _grZoom = newZoom;
      if (_grZoom === 1) { _grPanX = 0; _grPanY = 0; }
      applyGridRefZoom();
    }, { passive: false });

    container.addEventListener('mousedown', function (e) {
      /* Space, middle-drag and right-drag pan, exactly as on the section grid.
         Zoomed in to place a point precisely, panning is the whole job.

         Plain left-drag pans too, but only when no point is being placed -
         otherwise the drag that was meant to position the map would consume
         the click. Without this the left button did nothing at all outside
         picking mode, which is not how the other plan canvases in the suite
         behave. */
      if (WD.PanZoom.isPanGesture(e) || e.button !== 0 || !_grPicking) {
        e.preventDefault();
        startGridRefPan(e);
      }
    });
    container.addEventListener('contextmenu', function (e) { e.preventDefault(); });

    /* A plain left click places the point being picked. It is a click rather
       than a drag so that a click landing during a pan does not move a point:
       the pan path above returns before this fires. */
    container.addEventListener('click', function (e) {
      if (!_grPicking) return;
      if (WD.PanZoom.isHeld()) return;
      var svgEl = document.getElementById('gridRefSvg');
      if (!svgEl) return;
      var fp = proj.floorPlans[_grFloorIdx];
      if (!fp) return;
      /* Screen point to plan coordinate, through the SVG's own matrix.

         Doing this by hand needs three things at once: the viewBox scale, the
         letterbox offset where the plan's aspect does not match the box it is
         drawn in, and the CSS transform carrying the pan and zoom. The first
         attempt used getBoundingClientRect and subtracted the pan - which
         double-counts, because the rect is already transformed - and ignored
         the letterbox entirely. Measured, that put a click at 20% of the plan
         at 39% in Firefox, 74% in Chrome and 67% in Edge: wrong, and wrong by
         a different amount in each, which is the signature of an aspect-ratio
         assumption rather than an arithmetic slip.

         getScreenCTM accounts for all three and is what the browser itself
         uses, so there is nothing left to get wrong per engine. */
      var ctm = svgEl.getScreenCTM();
      if (!ctm) return;
      var pt = svgEl.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      var loc = pt.matrixTransform(ctm.inverse());
      // The viewBox is 1000 wide for a plan that is fp.width across.
      var vbW = parseFloat(svgEl.getAttribute('data-dw')) || 1;
      var vbH = parseFloat(svgEl.getAttribute('data-dh')) || 1;
      var x = loc.x / vbW * (fp.width || 1);
      var y = loc.y / vbH * (fp.height || 1);
      var existing = _grPoints[_grPicking];
      _grPoints[_grPicking] = {
        x: x, y: y,
        col: existing ? existing.col : null,
        row: existing ? existing.row : null,
      };
      // A point placed before its label is typed keeps whatever is in the box.
      var input = document.getElementById('gridRefLabel' + _grPicking.toUpperCase());
      if (input) {
        var parsed = parseGridLabel(input.value);
        if (parsed) {
          _grPoints[_grPicking].col = parsed.col;
          _grPoints[_grPicking].row = parsed.row;
        }
      }
      _grPicking = '';
      updateGridRefPreview();
      if (input && !input.value) input.focus();
    });

    _grSpaceUnsub = WD.PanZoom.onChange(function (isHeld) {
      var el = document.getElementById('gridRefPreviewContainer');
      if (!el) return;
      el.classList.toggle('space-pan', isHeld);
      if (!isHeld && _grPanState && _grPanState.viaSpace) endGridRefPan();
    });
  }

  function startGridRefPan(e) {
    var container = document.getElementById('gridRefPreviewContainer');
    if (container) container.classList.add('pan-active');
    _grPanState = {
      startX: e.clientX, startY: e.clientY,
      origPX: _grPanX, origPY: _grPanY,
      viaSpace: WD.PanZoom.isHeld(),
    };
    document.addEventListener('mousemove', onGridRefPan);
    document.addEventListener('mouseup', endGridRefPan);
  }

  function onGridRefPan(e) {
    if (!_grPanState) return;
    _grPanX = _grPanState.origPX + (e.clientX - _grPanState.startX);
    _grPanY = _grPanState.origPY + (e.clientY - _grPanState.startY);
    applyGridRefZoom();
  }

  function endGridRefPan() {
    _grPanState = null;
    var container = document.getElementById('gridRefPreviewContainer');
    if (container) container.classList.remove('pan-active');
    document.removeEventListener('mousemove', onGridRefPan);
    document.removeEventListener('mouseup', endGridRefPan);
  }

  // Closing hands Space back to the page; without this the key stays swallowed
  // for the rest of the session.
  function releaseGridRefKeys() {
    if (_grSpaceUnsub) { _grSpaceUnsub(); _grSpaceUnsub = null; }
    var container = document.getElementById('gridRefPreviewContainer');
    if (container) {
      container.classList.remove('space-pan', 'pan-active', 'is-picking');
      container._grBound = false;
    }
    endGridRefPan();
  }

  window.saveGridRefFloor = async function () {
    var fp = proj.floorPlans[_grFloorIdx];
    var solved = currentGridRefSolver();
    if (!fp || !solved.ok) { showToast(solved.reason || 'Not ready to save.', 'warn'); return; }
    var res;
    try {
      res = await WD.api('report/grid/save', {
        projectId: proj.projectId, floorId: fp.id,
        grid: { a: _grPoints.a, b: _grPoints.b, lettersAxis: _grAxis },
      });
    } catch (e) { showToast('That could not be saved.', 'error'); return; }
    if (!res || !res.ok) { showToast((res && res.error) || 'That could not be saved.', 'error'); return; }
    resetFloorGrids(res.floors || {});
    configureDirty = true;
    showToast('Column grid saved for ' + (fp.name || 'this floor') + '.', 'success');
    // The tick in the floor list, and the button's count, both just changed.
    var sel = document.getElementById('gridRefFloorSelect');
    if (sel) {
      (proj.floorPlans || []).forEach(function (f, i) {
        if (sel.options[i]) {
          sel.options[i].textContent = (f.name || ('Floor ' + (i + 1)))
            + (_floorGrids[f.id] ? '  ✓' : '');
        }
      });
    }
  };

  window.clearGridRefFloor = async function () {
    var fp = proj.floorPlans[_grFloorIdx];
    if (!fp) return;
    if (!_floorGrids[fp.id]) {
      // Nothing saved, so this is the field-clearing button rather than a
      // delete. Say nothing and just reset.
      _grPoints = { a: null, b: null };
      loadGridRefFloor();
      return;
    }
    if (!confirm('Turn the column grid reference off for "'
                 + (fp.name || 'this floor') + '"?\n\n'
                 + 'APs on this floor will show a dash instead of a grid '
                 + 'reference. Other floors are not affected.')) return;
    var res;
    try {
      res = await WD.api('report/grid/clear', {
        projectId: proj.projectId, floorId: fp.id });
    } catch (e) { showToast('That could not be cleared.', 'error'); return; }
    if (!res || !res.ok) { showToast((res && res.error) || 'That could not be cleared.', 'error'); return; }
    resetFloorGrids(res.floors || {});
    configureDirty = true;
    loadGridRefFloor();
    showToast('Column grid turned off for ' + (fp.name || 'this floor') + '.', 'info');
  };


  // ── Grid configuration modal ──

  var _gridCols = 0, _gridRows = 0, _gridFloorIdx = 0;
  var _cropBox = { x: 0, y: 0, w: 1, h: 1 };
  var _cropBoxes = {};
  var _dragState = null;
  var _gridZoom = 1, _gridPanX = 0, _gridPanY = 0;
  var _spaceUnsub = null;
  var _panState = null;

  window.openGridConfig = function () {
    var modal = document.getElementById('gridConfigModal');
    if (!modal) return;
    var fps = proj.floorPlans || [];
    if (!fps.length) { alert('No floor plans in this project.'); return; }
    _gridFloorIdx = 0;
    var fp = fps[0];
    var aps = filterApsForFloor(fp);
    var auto = computeAntennaGrid(fp.width, fp.height, aps, {}, fp.metersPerUnit);
    _gridCols = (currentOpts.segCols > 0) ? currentOpts.segCols : auto.cols;
    _gridRows = (currentOpts.segRows > 0) ? currentOpts.segRows : auto.rows;
    _cropBoxes = {};
    var saved = currentOpts.cropBoxes || {};
    (proj.floorPlans || []).forEach(function (f) {
      if (saved[f.id]) _cropBoxes[f.id] = { x: saved[f.id].x, y: saved[f.id].y, w: saved[f.id].w, h: saved[f.id].h };
    });
    var fc = _cropBoxes[fp.id];
    _cropBox = fc ? { x: fc.x, y: fc.y, w: fc.w, h: fc.h } : { x: 0, y: 0, w: 1, h: 1 };

    var sel = document.getElementById('gridFloorSelect');
    sel.innerHTML = '';
    fps.forEach(function (f, i) {
      var opt = document.createElement('option');
      opt.value = i;
      opt.textContent = f.name || ('Floor ' + (i + 1));
      sel.appendChild(opt);
    });
    sel.value = '0';

    _gridZoom = 1; _gridPanX = 0; _gridPanY = 0;
    updateGridPreview();
    modal.hidden = false;
  };

  function filterApsForFloor(fp) {
    return (proj.accessPoints || []).filter(function (ap) {
      return ap.location && ap.location.floorPlanId === fp.id;
    });
  }

  window.gridFloorChanged = function (sel) {
    saveCurrentFloorCrop();
    _gridFloorIdx = parseInt(sel.value, 10) || 0;
    _gridZoom = 1; _gridPanX = 0; _gridPanY = 0;
    var newFp = proj.floorPlans[_gridFloorIdx];
    var fc = newFp && _cropBoxes[newFp.id];
    _cropBox = fc ? { x: fc.x, y: fc.y, w: fc.w, h: fc.h } : { x: 0, y: 0, w: 1, h: 1 };
    updateGridPreview();
  };

  window.adjustGridCols = function (delta) {
    _gridCols = Math.max(1, Math.min(20, _gridCols + delta));
    updateGridPreview();
  };

  window.adjustGridRows = function (delta) {
    _gridRows = Math.max(1, Math.min(20, _gridRows + delta));
    updateGridPreview();
  };

  window.resetCropBox = function () {
    _cropBox = { x: 0, y: 0, w: 1, h: 1 };
    rebalanceGridForCrop();
  };

  function updateGridPreview() {
    var fp = proj.floorPlans[_gridFloorIdx];
    if (!fp) return;
    var url = floorPlanImageUrl(fp) || '';
    var W = fp.width, H = fp.height;
    var aps = filterApsForFloor(fp);

    document.getElementById('gridColsVal').textContent = _gridCols;
    document.getElementById('gridRowsVal').textContent = _gridRows;
    document.getElementById('gridCellCount').textContent =
      _gridCols * _gridRows + ' cells, ' + aps.length + ' APs on this floor';

    var vw = 1000, vh = 1000 * (H / W);

    var bx = _cropBox.x * vw, by = _cropBox.y * vh;
    var bw = _cropBox.w * vw, bh = _cropBox.h * vh;

    var letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + vw + ' ' + vh + '" '
      + 'class="grid-svg-fill" '
      + 'id="gridSvg" data-dw="' + vw + '" data-dh="' + vh + '">';
    svg += '<image href="' + WD.escAttr(url) + '" width="' + vw + '" height="' + vh + '" />';

    // dim area outside crop box
    svg += '<path d="M0,0 H' + vw + ' V' + vh + ' H0 Z '
      + 'M' + bx + ',' + by + ' V' + (by + bh) + ' H' + (bx + bw) + ' V' + by + ' Z" '
      + 'fill="rgba(0,0,0,0.45)" fill-rule="evenodd" pointer-events="none"/>';

    /* The same grid the printed section index draws, from the same classes.

       It used to be a second implementation: inline rgba(59,130,246,0.7) at
       1.5 units in a 1000-unit viewBox, with labels at half opacity. Over a
       white CAD plan that is very nearly nothing, so the one view where the
       division is actually being decided was the one view where the divisions
       could not be seen - while the printed index, which is only reference
       furniture, came out bold.

       Weight is the single deliberate difference between the two, and it is in
       the stylesheet under #gridSvg rather than duplicated here. Each cell also
       gets a white halo underneath, because a CAD plan is white paper *and*
       black linework and a single colour loses against one of them - the same
       fix the AP labels needed. */
    var cw = bw / _gridCols, ch = bh / _gridRows;
    var glw = Math.max(2.5, vw * 0.0035);

    // Which sections will actually produce a page, so the choice can be made
    // with that visible rather than discovered afterwards.
    var hasApsAt = {};
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var px = c.x / W * vw, py = c.y / H * vh;
      if (px < bx || px > bx + bw || py < by || py > by + bh) return;
      var ci3 = Math.min(_gridCols - 1, Math.max(0, Math.floor((px - bx) / cw)));
      var ri3 = Math.min(_gridRows - 1, Math.max(0, Math.floor((py - by) / ch)));
      hasApsAt[ci3 + ',' + ri3] = true;
    });

    var cells = '', cellLabels = '';
    for (var ri = 0; ri < _gridRows; ri++) {
      for (var ci = 0; ci < _gridCols; ci++) {
        var cxr = bx + ci * cw, cyr = by + ri * ch;
        var used = !!hasApsAt[ci + ',' + ri];
        cells += '<rect x="' + cxr + '" y="' + cyr + '" width="' + cw + '" height="' + ch
          + '" class="rep-grid-halo" stroke-width="' + (glw * 2.6) + '" pointer-events="none"/>';
        cells += '<rect x="' + cxr + '" y="' + cyr + '" width="' + cw + '" height="' + ch
          + '" class="rep-grid-cell' + (used ? '' : ' rep-grid-cell--empty')
          + '" stroke-width="' + glw + '" pointer-events="none"/>';
        var lbl = (ci < 26 ? letters[ci] : 'C' + (ci + 1)) + (ri + 1);
        cellLabels += '<text x="' + (cxr + cw / 2) + '" y="' + (cyr + ch / 2) + '"'
          + ' text-anchor="middle" dominant-baseline="central"'
          + ' class="rep-grid-label' + (used ? '' : ' rep-grid-label--empty') + '"'
          + ' font-size="' + Math.max(12, Math.min(30, cw * 0.32)) + '"'
          + ' pointer-events="none">' + lbl + '</text>';
      }
    }
    svg += cells + cellLabels;

    // AP dots
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var px = c.x / W * vw, py = c.y / H * vh;
      svg += '<circle cx="' + px + '" cy="' + py + '" r="3" fill="rgba(239,68,68,0.8)" stroke="#fff" stroke-width="0.5" pointer-events="none"/>';
    });

    // crop box border - haloed for the same reason as the cells
    svg += '<rect x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh
      + '" class="rep-grid-halo" stroke-width="' + (glw * 3) + '" pointer-events="none"/>';
    svg += '<rect x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh
      + '" class="grid-crop-border" stroke-width="' + (glw * 1.2) + '" pointer-events="none"/>';

    // move area rendered FIRST so edges and corners sit on top in SVG z-order
    svg += '<rect data-edge="move" x="' + bx + '" y="' + by + '" width="' + bw + '" height="' + bh
      + '" fill="transparent" cursor="move"/>';

    // drag handles — edges (wide hit areas for easy grabbing)
    var ht = 20;
    var cs = 18;
    svg += '<rect class="crop-handle" data-edge="left" x="' + (bx - ht / 2) + '" y="' + (by + cs) + '" width="' + ht + '" height="' + (bh - cs * 2) + '" fill="transparent" cursor="ew-resize"/>';
    svg += '<rect class="crop-handle" data-edge="right" x="' + (bx + bw - ht / 2) + '" y="' + (by + cs) + '" width="' + ht + '" height="' + (bh - cs * 2) + '" fill="transparent" cursor="ew-resize"/>';
    svg += '<rect class="crop-handle" data-edge="top" x="' + (bx + cs) + '" y="' + (by - ht / 2) + '" width="' + (bw - cs * 2) + '" height="' + ht + '" fill="transparent" cursor="ns-resize"/>';
    svg += '<rect class="crop-handle" data-edge="bottom" x="' + (bx + cs) + '" y="' + (by + bh - ht / 2) + '" width="' + (bw - cs * 2) + '" height="' + ht + '" fill="transparent" cursor="ns-resize"/>';

    // drag handles — corners (visible blue squares, on top of everything)
    svg += '<rect class="crop-handle" data-edge="tl" x="' + (bx - cs / 2) + '" y="' + (by - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nwse-resize"/>';
    svg += '<rect class="crop-handle" data-edge="tr" x="' + (bx + bw - cs / 2) + '" y="' + (by - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nesw-resize"/>';
    svg += '<rect class="crop-handle" data-edge="bl" x="' + (bx - cs / 2) + '" y="' + (by + bh - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nesw-resize"/>';
    svg += '<rect class="crop-handle" data-edge="br" x="' + (bx + bw - cs / 2) + '" y="' + (by + bh - cs / 2) + '" width="' + cs + '" height="' + cs + '" fill="#3b82f6" rx="2" cursor="nwse-resize"/>';

    svg += '</svg>';
    document.getElementById('gridPreviewImage').innerHTML = svg;
    applyGridZoom();
    bindCropHandles();
    bindGridZoomPan();
  }

  function applyGridZoom() {
    var svgEl = document.getElementById('gridSvg');
    if (!svgEl) return;
    svgEl.style.transform = 'translate(' + _gridPanX + 'px,' + _gridPanY + 'px) scale(' + _gridZoom + ')';
    svgEl.style.transformOrigin = '0 0';
  }

  function bindGridZoomPan() {
    var container = document.getElementById('gridPreviewContainer');
    if (!container || container._zoomBound) return;
    container._zoomBound = true;

    container.addEventListener('wheel', function (e) {
      e.preventDefault();
      var svgEl = document.getElementById('gridSvg');
      if (!svgEl) return;
      var rect = svgEl.getBoundingClientRect();
      var mx = e.clientX - rect.left, my = e.clientY - rect.top;
      var svgX = (mx - _gridPanX) / _gridZoom;
      var svgY = (my - _gridPanY) / _gridZoom;
      var delta = e.deltaY > 0 ? -0.15 : 0.15;
      var newZoom = Math.max(1, Math.min(8, _gridZoom + delta * _gridZoom));
      if (newZoom <= 1.01) { newZoom = 1; }
      _gridPanX = mx - svgX * newZoom;
      _gridPanY = my - svgY * newZoom;
      _gridZoom = newZoom;
      if (_gridZoom === 1) { _gridPanX = 0; _gridPanY = 0; }
      applyGridZoom();
    }, { passive: false });

    container.addEventListener('mousedown', function (e) {
      // Space, middle-drag and right-drag pan over anything, crop handles
      // included -- that is what makes them a modifier rather than a mode.
      // Plain left-drag still pans the empty parts of the map as it always has.
      var forced = WD.PanZoom.isPanGesture(e);
      if (!forced) {
        if (e.button !== 0) return;
        if (e.target.closest('[data-edge]')) return;
      }
      e.preventDefault();
      startGridPan(e);
    });

    // Right-drag pans, so the context menu would only ever land mid-gesture.
    container.addEventListener('contextmenu', function (e) { e.preventDefault(); });

    // Held Space shows the open hand before the drag starts, and letting go
    // mid-drag drops the map where it is instead of leaving it stuck to the
    // pointer.
    _spaceUnsub = WD.PanZoom.onChange(function (isHeld) {
      var el = document.getElementById('gridPreviewContainer');
      if (!el) return;
      el.classList.toggle('space-pan', isHeld);
      if (!isHeld && _panState && _panState.viaSpace) endGridPan();
    });
  }

  function startGridPan(e) {
    var container = document.getElementById('gridPreviewContainer');
    if (container) container.classList.add('pan-active');
    _panState = {
      startX: e.clientX, startY: e.clientY,
      origPX: _gridPanX, origPY: _gridPanY,
      viaSpace: WD.PanZoom.isHeld(),
    };
    document.addEventListener('mousemove', onGridPan);
    document.addEventListener('mouseup', endGridPan);
  }

  window.resetGridZoom = function () {
    _gridZoom = 1; _gridPanX = 0; _gridPanY = 0;
    applyGridZoom();
  };

  function onGridPan(e) {
    if (!_panState) return;
    var dx = e.clientX - _panState.startX;
    var dy = e.clientY - _panState.startY;
    _gridPanX = _panState.origPX + dx;
    _gridPanY = _panState.origPY + dy;
    applyGridZoom();
  }

  function endGridPan() {
    _panState = null;
    var container = document.getElementById('gridPreviewContainer');
    if (container) container.classList.remove('pan-active');
    document.removeEventListener('mousemove', onGridPan);
    document.removeEventListener('mouseup', endGridPan);
  }

  // Closing the modal hands Space back to the page; without this the key would
  // stay swallowed for the rest of the session.
  function releaseGridPanKeys() {
    if (_spaceUnsub) { _spaceUnsub(); _spaceUnsub = null; }
    var container = document.getElementById('gridPreviewContainer');
    if (container) {
      container.classList.remove('space-pan', 'pan-active');
      container._zoomBound = false;
    }
    endGridPan();
  }

  function bindCropHandles() {
    var svgEl = document.getElementById('gridSvg');
    if (!svgEl) return;
    var handles = svgEl.querySelectorAll('[data-edge]');
    for (var i = 0; i < handles.length; i++) {
      handles[i].addEventListener('mousedown', startCropDrag);
    }
  }

  function getSvgScale(svgEl) {
    var dw = parseFloat(svgEl.getAttribute('data-dw'));
    var dh = parseFloat(svgEl.getAttribute('data-dh'));
    var rect = svgEl.getBoundingClientRect();
    var imgAspect = dw / dh;
    var boxAspect = rect.width / rect.height;
    var renderedW, renderedH;
    if (imgAspect > boxAspect) {
      renderedW = rect.width;
      renderedH = rect.width / imgAspect;
    } else {
      renderedH = rect.height;
      renderedW = rect.height * imgAspect;
    }
    return { dw: dw, dh: dh, scaleX: dw / renderedW, scaleY: dh / renderedH };
  }

  function startCropDrag(e) {
    // Space makes the whole map a pan surface. These handles stop propagation,
    // so unless they stand down here the gesture dies on them: the container
    // never sees the mousedown and nothing pans.
    if (WD.PanZoom.isHeld()) return;
    e.preventDefault();
    e.stopPropagation();
    var edge = e.target.getAttribute('data-edge');
    var svgEl = document.getElementById('gridSvg');
    var s = getSvgScale(svgEl);

    _dragState = {
      edge: edge,
      startX: e.clientX, startY: e.clientY,
      origBox: { x: _cropBox.x, y: _cropBox.y, w: _cropBox.w, h: _cropBox.h },
      scaleX: s.scaleX, scaleY: s.scaleY, dw: s.dw, dh: s.dh
    };

    document.addEventListener('mousemove', onCropDrag);
    document.addEventListener('mouseup', endCropDrag);
  }

  function onCropDrag(e) {
    if (!_dragState) return;
    var ds = _dragState;
    var dx = (e.clientX - ds.startX) * ds.scaleX / ds.dw;
    var dy = (e.clientY - ds.startY) * ds.scaleY / ds.dh;
    var ob = ds.origBox;
    var minSize = 0.05;

    var nx = ob.x, ny = ob.y, nw = ob.w, nh = ob.h;

    switch (ds.edge) {
      case 'left':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        break;
      case 'right':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        break;
      case 'top':
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'bottom':
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'tl':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'tr':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        ny = Math.max(0, Math.min(ob.y + ob.h - minSize, ob.y + dy));
        nh = ob.h - (ny - ob.y);
        break;
      case 'bl':
        nx = Math.max(0, Math.min(ob.x + ob.w - minSize, ob.x + dx));
        nw = ob.w - (nx - ob.x);
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'br':
        nw = Math.max(minSize, Math.min(1 - ob.x, ob.w + dx));
        nh = Math.max(minSize, Math.min(1 - ob.y, ob.h + dy));
        break;
      case 'move':
        nx = Math.max(0, Math.min(1 - ob.w, ob.x + dx));
        ny = Math.max(0, Math.min(1 - ob.h, ob.y + dy));
        break;
    }

    _cropBox = { x: nx, y: ny, w: nw, h: nh };
    updateGridPreview();
  }

  function endCropDrag() {
    var edge = _dragState && _dragState.edge;
    _dragState = null;
    document.removeEventListener('mousemove', onCropDrag);
    document.removeEventListener('mouseup', endCropDrag);
    if (edge && edge !== 'move') rebalanceGridForCrop();
  }

  function rebalanceGridForCrop() {
    var fp = proj.floorPlans[_gridFloorIdx];
    var cropW = _cropBox.w * fp.width;
    var cropH = _cropBox.h * fp.height;
    if (cropW <= 0 || cropH <= 0) return;
    var totalCells = _gridCols * _gridRows;
    var aspect = cropW / cropH;
    var newCols = Math.max(1, Math.round(Math.sqrt(totalCells * aspect)));
    var newRows = Math.max(1, Math.round(totalCells / newCols));
    _gridCols = newCols;
    _gridRows = newRows;
    updateGridPreview();
  }

  function saveCurrentFloorCrop() {
    var curFp = proj.floorPlans[_gridFloorIdx];
    if (!curFp) return;
    var full = _cropBox.x < 0.001 && _cropBox.y < 0.001 && _cropBox.w > 0.999 && _cropBox.h > 0.999;
    if (full) delete _cropBoxes[curFp.id];
    else _cropBoxes[curFp.id] = { x: _cropBox.x, y: _cropBox.y, w: _cropBox.w, h: _cropBox.h };
  }

  window.applyGridFloor = function (allFloors) {
    if (allFloors) {
      var full = _cropBox.x < 0.001 && _cropBox.y < 0.001 && _cropBox.w > 0.999 && _cropBox.h > 0.999;
      var crop = full ? null : { x: _cropBox.x, y: _cropBox.y, w: _cropBox.w, h: _cropBox.h };
      _cropBoxes = {};
      if (crop) {
        (proj.floorPlans || []).forEach(function (f) {
          _cropBoxes[f.id] = { x: crop.x, y: crop.y, w: crop.w, h: crop.h };
        });
      }
      var fps = proj.floorPlans || [];
      var msg = 'Crop applied to all ' + fps.length + ' floors.';
      if (fps.length > 1) msg += ' Check each floor — images may not be aligned.';
      showToast(msg);
    } else {
      saveCurrentFloorCrop();
      var name = (proj.floorPlans[_gridFloorIdx] || {}).name || 'Floor';
      showToast('Crop applied to ' + name + '.');
    }
  };

  window.doneGridConfig = function () {
    saveCurrentFloorCrop();
    currentOpts.segCols = _gridCols;
    currentOpts.segRows = _gridRows;
    currentOpts.cropBoxes = Object.keys(_cropBoxes).length ? _cropBoxes : null;
    configureDirty = true;
    releaseGridPanKeys();
    document.getElementById('gridConfigModal').hidden = true;
    renderReportOpts();
  };

  window.resetGridToAuto = function () {
    var fp = proj.floorPlans[_gridFloorIdx];
    var aps = filterApsForFloor(fp);
    var auto = computeAntennaGrid(fp.width, fp.height, aps, {}, fp.metersPerUnit);
    _gridCols = auto.cols;
    _gridRows = auto.rows;
    _cropBox = { x: 0, y: 0, w: 1, h: 1 };
    if (fp) delete _cropBoxes[fp.id];
    updateGridPreview();
  };

  window.closeGridConfig = function () {
    _dragState = null;
    document.removeEventListener('mousemove', onCropDrag);
    document.removeEventListener('mouseup', endCropDrag);
    releaseGridPanKeys();
    document.getElementById('gridConfigModal').hidden = true;
  };

  function currentReport() { return REPORTS[currentReportId] || REPORTS[DEFAULT_REPORT_ID]; }

  function collectOpts() {
    var opts = {};
    var coverEl = document.getElementById('optCover');
    opts.cover = coverEl ? coverEl.checked : true;
    var r = currentReport();
    (r.sidebar || []).forEach(function (o) {
      if (o.id === 'units') {
        // the remembered preference wins over the option's built-in default
        opts.units = (o.id in currentOpts) ? currentOpts[o.id] : unitsPref;
      } else if (o.type === 'text' || o.type === 'select') {
        opts[o.id] = (o.id in currentOpts) ? (currentOpts[o.id] || '') : (o.default || '');
      } else {
        opts[o.id] = (o.id in currentOpts) ? currentOpts[o.id] : !!o.default;
      }
    });
    opts.segGranularity = ('segGranularity' in currentOpts)
      ? currentOpts.segGranularity : segGranularityPref;
    if (currentOpts.segCols > 0) opts.segCols = currentOpts.segCols;
    if (currentOpts.segRows > 0) opts.segRows = currentOpts.segRows;
    if (currentOpts.cropBoxes) opts.cropBoxes = currentOpts.cropBoxes;
    // Whatever was saved, with anything changed this session on top.
    if (!currentOpts.pageOrient) {
      currentOpts.pageOrient = Object.assign({}, savedPageOrient);
    }
    opts.pageOrient = currentOpts.pageOrient;
    return opts;
  }

  function renderCover(count, dateStr, r, countLabel, opts, ctx) {
    var logo = (coverImage && coverImage.url)
      ? '<div class="rep-cover-logo-wrap"><img class="rep-cover-logo" src="' + WD.escAttr(coverImage.url) + '" alt="Cover image"></div>'
      : '';
    var floorLabel = proj.floorPlans.length === 1 ? 'Floor plan' : 'Floor plans';
    var meta = '';
    if (opts) {
      var metaRows = [];
      if (opts.clientName) metaRows.push('<div><b>Client:</b> ' + WD.esc(opts.clientName) + '</div>');
      if (opts.preparedBy) metaRows.push('<div><b>Prepared by:</b> ' + WD.esc(opts.preparedBy) + '</div>');
      if (opts.projectRef) metaRows.push('<div><b>Project ref:</b> ' + WD.esc(opts.projectRef) + '</div>');
      if (opts.revision)   metaRows.push('<div><b>Revision:</b> ' + WD.esc(opts.revision) + '</div>');
      if (metaRows.length) meta = '<div class="rep-cover-meta">' + metaRows.join('') + '</div>';
    }
    var displayDate = (ctx && ctx.dateReadable) ? ctx.dateReadable : dateStr;
    return '<section class="rep-cover">'
      + logo
      + '<div class="rep-cover-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-cover-title">' + WD.esc(siteName()) + '</h1>'
      + meta
      + '<div class="rep-cover-stats">'
      +   '<div class="rep-cover-stat"><b>' + count + '</b><span>' + WD.esc(countLabel || 'Access points') + '</span></div>'
      +   '<div class="rep-cover-stat"><b>' + proj.floorPlans.length + '</b><span>' + floorLabel + '</span></div>'
      + '</div>'
      + '<div class="rep-cover-date">Generated ' + WD.esc(displayDate) + '</div>'
      + '</section>';
  }
  function renderInlineHeader(count, dateStr, r, countLabel) {
    return '<header class="rep-doc-head">'
      + '<div class="rep-doc-brand"><img class="rep-brand-icon" src="../assets/report-v8.0-560x560.png" alt=""> ' + WD.esc(r.coverBrand) + '</div>'
      + '<h1 class="rep-doc-title">' + WD.esc(siteName()) + '</h1>'
      + '<div class="rep-doc-meta">'
      + '<span><b>' + WD.esc(countLabel || 'APs') + ':</b> ' + count + '</span>'
      + '<span><b>Floor plans:</b> ' + proj.floorPlans.length + '</span>'
      + '<span><b>Generated:</b> ' + WD.esc(dateStr) + '</span>'
      + '</div></header>';
  }

  window.renderReport = function () {
    var host = document.getElementById('reportCanvas');
    var r = currentReport();
    syncDocTitle();
    if (!proj.accessPoints.length && !r.noApFilter) {
      host.innerHTML = '<div class="rep-empty">Drop an .esx to render a report.</div>';
      return;
    }

    var opts = collectOpts();
    var inclDirectional = ('inclDirectional' in opts) ? opts.inclDirectional : true;
    var inclOmni        = ('inclOmni'        in opts) ? opts.inclOmni        : false;
    var aps = proj.accessPoints.filter(function (a) {
      if (apDisabled.has(a.id)) return false;
      var omni = apIsOmniOnly(a);
      if (omni && !inclOmni) return false;
      if (!omni && !inclDirectional) return false;
      return true;
    });
    if (!aps.length && !r.noApFilter) {
      host.innerHTML = '<div class="rep-empty">'
        + WD.esc(emptyApReason(inclOmni, inclDirectional)) + '</div>';
      return;
    }
    var today = new Date();
    var dateStr = today.toISOString().slice(0, 10);
    var dateReadable = formatReadableDate(today);
    var ctx = {
      report: r,
      dateStr: dateStr,
      dateReadable: dateReadable,
      proj: proj,
      coverImage: coverImage,
      cover: function (count, ds, label, opts2, ctx2) { return renderCover(count, ds, r, label, opts2, ctx2); },
      inlineHeader: function (count, ds, label) { return renderInlineHeader(count, ds, r, label); },
      primaryRadio: primaryRadio,
      compass: compass, metersToFt: metersToFt, fmt: fmt,
      fmtLength: fmtLength, unitsOf: unitsOf,
      floorPlanForAp: floorPlanForAp,
    };
    host.innerHTML = r.render(aps, opts, ctx);
    // Every report, not only the one whose postRender happened to ask.
    applyPageOrientation(host, opts);
    document.title = reportDocTitle();
    if (typeof r.postRender === 'function') {
      try {
        Promise.resolve(r.postRender(host, opts, ctx)).catch(function (e) { console.error('postRender', e); });
      } catch (e) { console.error('postRender', e); }
    }
  };

  // Label text is composable so one report can show just the name while another
  // carries the detail an installer needs without a second lookup.
  /* Why the AP list came out empty, naming the thing to change.

     "No APs selected - check the AP filter panel" was printed for every cause,
     including the two where the panel was never touched and the report's own
     option did the hiding. On an all-omni project the Antenna Aim Sheet said it
     in front of 44 access points, telling him to go and fix a panel that was
     correct. Found by printing the same report in Chrome, Edge and Firefox and
     reading what came out. */
  function emptyApReason(inclOmni, inclDirectional) {
    var all = proj.accessPoints || [];
    if (!all.length) return 'This project has no access points in it.';

    var enabled = all.filter(function (a) { return !apDisabled.has(a.id); });
    if (!enabled.length) {
      return 'Every access point is unticked in the AP filter panel below. '
        + 'Tick the ones this report should cover.';
    }

    var omni = enabled.filter(apIsOmniOnly).length;
    var dir = enabled.length - omni;
    if (!inclOmni && omni && !dir) {
      return 'All ' + omni + ' access point' + (omni === 1 ? ' here is' : 's here are')
        + ' omni, and this report is set to leave omni units out. '
        + 'Turn on "Include omni APs" to list them.';
    }
    if (!inclDirectional && dir && !omni) {
      return 'All ' + dir + ' access point' + (dir === 1 ? ' here is' : 's here are')
        + ' directional, and this report is set to leave directional units out. '
        + 'Turn on "Include directional APs" to list them.';
    }
    return 'No access point matches the current options. Check "Include omni APs" '
      + 'and "Include directional APs", and the AP filter panel below.';
  }

  function apMarkerLabel(ap, opts, ctx) {
    var main = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
    var extra = [];
    /* First of the extras on purpose. The others describe the AP; this one
       says where to stand to find it, which is the question somebody holding
       the drawing is actually asking. An AP with no coordinates, on a floor
       with no calibration, or outside the lettered area contributes nothing
       rather than a placeholder - a bare dash printed on a plan reads as a
       grid reference somebody failed to fill in. */
    if (opts.labelGrid) {
      var gref = gridRefForAp(ap);
      if (gref) extra.push(gref);
    }
    if (opts.labelModel && ap.model) extra.push(ap.model);
    if (opts.labelRadio && ctx) {
      var r = ctx.primaryRadio(ap.id);
      var ch = r && r.channelByCenterFrequencyDefinedNarrowChannels;
      // Ekahau stores these as centre frequencies in MHz. The label said
      // "ch 2412" - which is channel 1 - while the AP table on a later page of
      // the same document said "ch 1", because the table converts and this did
      // not. An installer reading a frequency where the word "ch" is printed
      // has no way to tell which of the two is lying.
      if (ch && ch.length) extra.push('ch ' + ch.map(freqToChannel).join('+'));
      if (r && typeof r.transmitPower === 'number') extra.push(fmt(r.transmitPower, 0) + ' dBm');
    }
    if (opts.labelHeight && ctx) {
      var rh = ctx.primaryRadio(ap.id);
      if (rh && typeof rh.antennaHeight === 'number') {
        extra.push(fmtLength(rh.antennaHeight, opts, 1));
      }
    }
    return { main: main, sub: extra.join(' · ') };
  }

  function buildAntennaMarkers(aps, scaleW, scaleH, opts, ctx, cellBounds, stats) {
    var minDim = Math.min(scaleW, scaleH);
    var edgeMargin = minDim * 0.06;
    var sw = minDim * 0.0025;
    var coneSw = sw * 0.67;
    var dotSize = minDim * 0.018;
    var pillH = minDim * 0.028;
    var gap = minDim * 0.008;
    var cornerR = minDim * 0.005;
    var dotR = dotSize * 0.25;
    var padX = minDim * 0.006;
    var showCones = opts.showCones !== false;

    // Reading order keeps placement deterministic: the same project renders the
    // same way every time, and the top-left AP gets first claim on its space.
    var ordered = aps.filter(function (ap) { return ap.location && ap.location.coord; })
      .slice()
      .sort(function (a, b) {
        var d = a.location.coord.y - b.location.coord.y;
        return d !== 0 ? d : a.location.coord.x - b.location.coord.x;
      });

    /* What makes a pill wide is the second line, not the number: "42" is two
       characters and "Catalyst 9166 · 9.8 ft" is twenty-two, so a pill carrying
       model and height is about ten times the width of one carrying the number.
       On an open floor that is fine. Where six APs sit within a pill's width of
       each other it is not: there is no arrangement of six room-wide boxes that
       leaves all six readable, so no amount of cleverness in the placement
       search below can rescue it.

       So in a crowded neighbourhood the marker keeps its number and drops the
       rest. The number is what ties it to the AP table and to the name key
       page, both of which carry the model and the height in full. The
       reduction is counted and said under the map rather than done quietly. */
    var crowdRadius = minDim * 0.075;
    var crowded = {};
    var reduced = 0;
    aps.forEach(function (ap) {
      if (!ap.location || !ap.location.coord) return;
      var near = 0;
      aps.forEach(function (other) {
        if (other === ap || !other.location || !other.location.coord) return;
        var dx = other.location.coord.x - ap.location.coord.x;
        var dy = other.location.coord.y - ap.location.coord.y;
        if (Math.sqrt(dx * dx + dy * dy) < crowdRadius) near++;
      });
      if (near >= 2) crowded[ap.id] = true;
    });

    // Labels already placed, in plan units. A label is never dropped -- on an
    // installer's map an unlabelled AP is worse than a crowded one -- so when
    // every near position is taken the pill moves further out and a leader line
    // is drawn back to the dot.
    var placed = [];

    /* Every dot's own square is reserved before any label is placed, not as
       each marker is reached. Reserving them as we went meant a label could be
       put down on ground where a later AP's dot was going to be drawn - legal
       at the time, covered by the time the map was finished. In a tight group
       that is what buried two of the numbers: the pills did not overlap each
       other at all, they were behind dots. */
    aps.forEach(function (ap) {
      if (!ap.location || !ap.location.coord) return;
      placed.push({ x: ap.location.coord.x - dotSize / 2,
                    y: ap.location.coord.y - dotSize / 2,
                    w: dotSize, h: dotSize });
    });
    function collides(r) {
      return placed.some(function (q) {
        return r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y;
      });
    }

    /* The edge of the map, which a placement has to respect as much as it
       respects the other labels.

       collides() only ever asked whether a label sat on another label or on a
       dot. Nothing asked whether it was still on the plan. The search below
       walks outwards in sixteen directions over three rings looking for clear
       ground, so a tight group near an edge would find its first unoccupied
       position off the side of the map - and the SVG clips at its viewBox, so
       the label did not spill onto the sheet where someone would notice it. It
       silently vanished, and an AP with no number on a drawing an installer
       works from is the worst thing this renderer can produce.

       Segmented maps already had these bounds and used them, but only to nudge
       a preference. They are a constraint, not a preference, and on a
       full-plan map there were no bounds at all. */
    /* Inset by half a stroke. An SVG stroke straddles the shape's edge, so a
       pill sitting exactly on the boundary still has half its outline outside
       it and loses that hairline to the clip. */
    var edgeInset = sw / 2;
    var labelBounds = cellBounds
      ? { x0: cellBounds.x0 + edgeInset, y0: cellBounds.y0 + edgeInset,
          x1: cellBounds.x1 - edgeInset, y1: cellBounds.y1 - edgeInset }
      : { x0: edgeInset, y0: edgeInset,
          x1: scaleW - edgeInset, y1: scaleH - edgeInset };
    function onPlan(r) {
      return r.x >= labelBounds.x0 && r.y >= labelBounds.y0
          && r.x + r.w <= labelBounds.x1 && r.y + r.h <= labelBounds.y1;
    }
    function pullOntoPlan(r) {
      r.x = Math.min(Math.max(r.x, labelBounds.x0), labelBounds.x1 - r.w);
      r.y = Math.min(Math.max(r.y, labelBounds.y0), labelBounds.y1 - r.h);
      return r;
    }

    var markers = '';
    ordered.forEach(function (ap) {
      var c = ap.location.coord;
      var r = ctx ? ctx.primaryRadio(ap.id) : null;
      var isDirectional = ctx ? radioIsDirectional(r) : false;
      var cls = !ctx ? 'rep-mark rep-mark--loc'
        : isDirectional ? 'rep-mark rep-mark--dir' : 'rep-mark rep-mark--omni';
      /* Resolve to hex before anything is painted or measured. An .esx may
         store "GREEN", and a browser reads that as CSS green (#008000), not
         Ekahau's #00FF00 - so the printed marker was the wrong colour, and the
         contrast helper, handed a word it cannot parse, put white lettering on
         all of them. */
      var apColor = WD.resolveApColor(ap.color) || '';
      var dir = (isDirectional && r) ? r.antennaDirection : null;

      var parts = apMarkerLabel(ap, opts, ctx);
      var label = parts.main;
      var sub = parts.sub;
      if (sub && crowded[ap.id]) { sub = ''; reduced++; }
      // The old rule shrank the type in proportion to the name, which put a
      // ten-character AP name at roughly 3pt on a printed page -- unreadable,
      // and on this report the name is the whole point. Shrink only to a floor
      // that still prints legibly, and let the pill grow instead; crowding is
      // what the placement search below is for.
      // Whatever is being drawn -- a whole floor or one zoomed cell -- prints
      // about 7.2in across, so a floor of 1.35% of the long edge lands near 7pt
      // on paper. Anything smaller than that is not worth printing.
      var legibleFloor = Math.max(scaleW, scaleH) * 0.0135;
      var labelFont = Math.max(legibleFloor,
                               minDim * 0.02 * Math.min(1, 4 / Math.max(4, label.length)));
      var subFont = labelFont * 0.72;
      var textW = Math.max(label.length * labelFont * 0.62, sub.length * subFont * 0.6);
      var pillW = Math.max(minDim * 0.03, textW) + padX * 2;
      var boxH = sub ? pillH + subFont * 1.25 : pillH;

      // The preferred side still follows the antenna and the page edge; the
      // fallbacks fan out from there.
      var preferAbove = false, preferSide = 0;
      if (dir != null) {
        var norm = ((dir % 360) + 360) % 360;
        if (norm > 90 && norm < 270) preferAbove = true;
        if (norm > 180 && norm < 360) preferSide = 1;
        else if (norm > 0 && norm < 180) preferSide = -1;
      }
      if (cellBounds) {
        if ((cellBounds.y1 - c.y) < edgeMargin && (c.y - cellBounds.y0) >= edgeMargin) preferAbove = true;
        if ((cellBounds.x1 - c.x) < edgeMargin + pillW / 2) preferSide = -1;
        else if ((c.x - cellBounds.x0) < edgeMargin + pillW / 2) preferSide = 1;
      }

      var near = dotSize / 2 + gap;
      var cands = [];
      function push(dx, dy, lead) { cands.push({ x: dx, y: dy, lead: !!lead }); }
      var vFirst = preferAbove ? -(near + boxH) : near;
      var vSecond = preferAbove ? near : -(near + boxH);
      var hFirst = preferSide >= 0 ? 0 : -pillW;
      push(-pillW / 2 + hFirst * 0.5, vFirst);
      push(-pillW / 2 + hFirst * 0.5, vSecond);
      push(near, -boxH / 2);
      push(-(near + pillW), -boxH / 2);
      push(near * 0.6, vFirst);
      push(-(pillW + near * 0.6), vFirst);
      push(near * 0.6, vSecond);
      push(-(pillW + near * 0.6), vSecond);
      // Further out, with a leader line so the pill still reads as this AP's.
      var far = near + boxH * 1.1;
      push(-pillW / 2, preferAbove ? -(far + boxH) : far, true);
      push(far, -boxH / 2, true);
      push(-(far + pillW), -boxH / 2, true);
      push(-pillW / 2, preferAbove ? far : -(far + boxH), true);

      /* Rings of positions around the dot, widening. Overlapping two labels
         makes both unreadable, so it is worth walking a long way out first -
         a leader line costs a reader one glance, a covered label costs them the
         AP. Sixteen angles over three rings is a few hundred rectangle tests
         for a floor of this size, which is nothing. */
      for (var ring = 1; ring <= 3; ring++) {
        var rad = far + ring * (boxH * 1.6 + gap);
        for (var a = 0; a < 16; a++) {
          var ang = (a / 16) * Math.PI * 2 + (preferAbove ? Math.PI : 0);
          push(Math.cos(ang) * rad - pillW / 2,
               Math.sin(ang) * rad - boxH / 2, true);
        }
      }

      var chosen = null;
      for (var i = 0; i < cands.length; i++) {
        var rect = { x: c.x + cands[i].x, y: c.y + cands[i].y, w: pillW, h: boxH };
        if (onPlan(rect) && !collides(rect)) { chosen = cands[i]; placed.push(rect); break; }
      }
      if (!chosen) {
        /* Every clear position on the map is taken, so this one doubles up -
           but it doubles up *on the map*. Off the edge is not a worse-looking
           label, it is no label, which is the one outcome worth ruling out. */
        var rect = pullOntoPlan({ x: c.x - pillW / 2, y: c.y + vFirst,
                                  w: pillW, h: boxH });
        chosen = { x: rect.x - c.x, y: rect.y - c.y, lead: true };
        placed.push(rect);
      }

      markers += '<g class="' + cls + '" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional && showCones) {
        var len = minDim * 0.06;
        var coneFill = apColor ? ' fill="' + WD.escAttr(apColor) + '" fill-opacity="0.35" stroke="' + WD.escAttr(apColor) + '"' : '';
        markers += '<g transform="rotate(' + dir + ')">'
          + '<path class="rep-mark-cone" d="M 0 0 L ' + (-len * 0.35) + ' ' + (-len) + ' L ' + (len * 0.35) + ' ' + (-len) + ' Z" stroke-width="' + coneSw + '"' + coneFill + '/></g>';
      }
      if (chosen.lead) {
        var lx = chosen.x + pillW / 2;
        var ly = chosen.y + (chosen.y > 0 ? 0 : boxH);
        var leadStroke = apColor ? ' stroke="' + WD.escAttr(apColor) + '"' : '';
        markers += '<line class="rep-mark-lead" x1="0" y1="0" x2="' + lx + '" y2="' + ly
          + '" stroke-width="' + (sw * 0.9) + '"' + leadStroke + '/>';
      }
      var dotFill = apColor ? ' fill="' + WD.escAttr(apColor) + '"' : '';
      var pillFill = apColor ? ' fill="' + WD.escAttr(apColor) + '"' : '';
      var darkText = apColor && WD.needsDarkText(apColor);
      var labelFill = darkText ? ' style="fill:#111"' : '';
      var subFill   = darkText ? ' style="fill:#333"' : '';
      /* These print. The stylesheet strokes both shapes white, which reads on
         screen and vanishes on paper as soon as the AP colour is pale - a
         yellow pill outlined in white on a white sheet is not a marker. Darken
         the stroke in proportion to how close the fill is to the page. */
      var edge = apColor ? ' stroke="' + WD.escAttr(WD.outlineOn(apColor)) + '"' : '';
      markers += '<rect class="rep-mark-dot" x="' + (-dotSize / 2) + '" y="' + (-dotSize / 2) + '" width="' + dotSize + '" height="' + dotSize + '" rx="' + dotR + '" ry="' + dotR + '" stroke-width="' + sw + '"' + dotFill + edge + '/>'
        + '<rect class="rep-mark-pill" x="' + chosen.x + '" y="' + chosen.y + '" width="' + pillW + '" height="' + boxH + '" rx="' + cornerR + '" ry="' + cornerR + '" stroke-width="' + sw + '"' + pillFill + edge + '/>'
        + '<text class="rep-mark-label" x="' + (chosen.x + pillW / 2) + '" y="' + (chosen.y + pillH / 2 + labelFont * 0.35) + '" text-anchor="middle" font-size="' + labelFont + '"' + labelFill + '>' + WD.esc(label) + '</text>';
      if (sub) {
        markers += '<text class="rep-mark-sub" x="' + (chosen.x + pillW / 2) + '" y="' + (chosen.y + pillH + subFont * 0.55) + '" text-anchor="middle" font-size="' + subFont + '"' + subFill + '>' + WD.esc(sub) + '</text>';
      }
      markers += '</g>';
    });
    if (stats) stats.reduced = reduced;
    return markers;
  }

  function antennaLabelHint(opts) {
    return opts.shortLabels === false
      ? 'Labels: full AP name.'
      : 'Labels: trailing "APnn" from each AP name (e.g. "42" for "…AP42"). Names without that suffix show the full name.';
  }

  // Distinct marker colours in the order they first appear, plus whether any
  // marker is falling back to the brand colour because its AP has none.
  function markerColours(aps) {
    var seen = {}, out = [], anyDefault = false;
    (aps || []).forEach(function (ap) {
      var raw = ap && ap.color;
      if (!raw) { anyDefault = true; return; }
      var c = WD.safeColor(raw);
      if (!seen[c]) { seen[c] = 1; out.push(c); }
    });
    return { colours: out, anyDefault: anyDefault };
  }

  // One colour on the map means one swatch in that colour. Several means the
  // legend shows all of them: a single swatch would be picking one AP's colour
  // to stand for the rest, which is worse than the mismatch it replaced.
  function keySwatch(cls, aps) {
    var info = markerColours(aps);
    var swatches = info.colours.slice(0, 6).map(function (c) {
      return '<span class="rep-key-swatch ' + cls + '" style="background:' + WD.escAttr(c) + '"></span>';
    });
    if (info.anyDefault || !swatches.length) {
      swatches.unshift('<span class="rep-key-swatch ' + cls + '"></span>');
    }
    var extra = info.colours.length - 6;
    return swatches.join('') + (extra > 0 ? '<span class="rep-key-more">+' + extra + '</span>' : '');
  }

  function antennaKeyHtml(opts, aps, ctx) {
    var dirAps = [], omniAps = [];
    (aps || []).forEach(function (ap) {
      if (ctx && radioIsDirectional(ctx.primaryRadio(ap.id))) dirAps.push(ap); else omniAps.push(ap);
    });
    return keySwatch('dir', dirAps) + ' Directional antenna &nbsp;·&nbsp; '
      + keySwatch('omni', omniAps) + ' Omni / ceiling &nbsp;·&nbsp; ' + WD.esc(antennaLabelHint(opts));
  }

  function renderAntennaOverview(fp, aps, opts, ctx, keyHtml) {
    var url = floorPlanImageUrl(fp);
    if (!url) return '<div class="rep-empty-small">Floor plan image not available.</div>';
    var W = fp.width || 1, H = fp.height || 1;
    if (!keyHtml) keyHtml = antennaKeyHtml(opts, aps, ctx);

    if (opts.segmented) {
      var grid = computeAntennaGrid(W, H, aps, opts, fp.metersPerUnit);
      if (grid.cols * grid.rows > 1) {
        opts.cropBox = (opts.cropBoxes && opts.cropBoxes[fp.id]) || null;
        opts.floorName = fp.name || 'Floor plan';
        opts.floorNumber = floorNumberFor(fp);
        return renderAntennaSegmentedOverview(url, W, H, aps, opts, ctx, grid, keyHtml);
      }
    }

    var stats = {};
    var markers = buildAntennaMarkers(aps, W, H, opts, ctx, null, stats);
    // Said out loud, next to the key, so nobody wonders why one marker carries
    // a model and its neighbour does not.
    var note = stats.reduced
      ? '<div class="rep-overview-note">' + stats.reduced + ' marker'
        + (stats.reduced === 1 ? '' : 's')
        + ' in tight groups show the number only — model and mount height for '
        + 'every AP are in the AP table.</div>'
      : '';
    return '<div class="rep-overview">'
      + '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +   '<img src="' + url + '" alt="Floor plan">'
      +   '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key">' + keyHtml + note + '</div>'
      + '</div>';
  }






  /* How much ground one section sheet covers.

     "standard" is the figure the tool has always used, so upgrading changes
     nobody's page count. The coarser settings are what construction asked for
     after seeing a warehouse come out as a stack of sheets each showing an AP
     floating in empty slab - fewer pages, more around each AP to place it by.

     Labelled by what you get rather than by an abstract scale, because "fine"
     and "coarse" do not tell you which way the page count moves. */
  var SEG_GRANULARITY = {
    fine:     { sqft:  60000, label: 'More detail \u2014 smaller sections' },
    standard: { sqft: 120000, label: 'Standard' },
    coarse:   { sqft: 250000, label: 'Fewer pages \u2014 larger sections' },
    coarsest: { sqft: 500000, label: 'Fewest pages \u2014 largest sections' },
  };
  function segSqFtPerPage(opts) {
    var g = SEG_GRANULARITY[(opts && opts.segGranularity) || segGranularityPref];
    return (g || SEG_GRANULARITY.standard).sqft;
  }
  var segGranularityPref = 'standard';
  var SEG_APS_PER_PAGE = 14;
  var SEG_MAX_CELLS = 24;

  /* How many sections a floor is split into.

     The size term used to be W * H * 10.7639 - plan units multiplied by the
     square feet in a square metre, as though a plan unit were a metre. It is
     not: a length in plan units becomes metres only after multiplying by that
     plan's own metersPerUnit, which on a CAD import is about 0.025. So a
     10000x7500 plan was measured as 807 million square feet instead of half a
     million, out by a factor of 1584, and every plan of any size ran into the
     24-cell cap.

     The effect was that segmentation never adapted to anything. A 1,708 sq ft
     apartment was cut into the same 24 sections as a 2.2 million sq ft
     warehouse, and the density term never influenced the answer because the
     size term always won. Construction asking for "fewer pages with more on
     them" was asking for this to work, not for a different default.

     Without a scale there is no honest way to know how big a building is, so
     the count falls back to AP density alone, which needs none. */
  function computeAntennaGrid(W, H, aps, opts, mPerUnit) {
    var userCols = parseInt(opts && opts.segCols, 10);
    var userRows = parseInt(opts && opts.segRows, 10);
    if (userCols > 0 && userRows > 0) return { cols: userCols, rows: userRows };
    var byDensity = Math.ceil(aps.length / SEG_APS_PER_PAGE) || 1;
    var bySize = 1;
    var scale = (typeof mPerUnit === 'number' && mPerUnit > 0) ? mPerUnit : 0;
    if (scale) {
      var areaSqFt = (W * scale) * (H * scale) * 10.7639;
      bySize = Math.ceil(areaSqFt / segSqFtPerPage(opts)) || 1;
    }
    var target = Math.min(SEG_MAX_CELLS, Math.max(byDensity, bySize, 1));
    if (target <= 1) return { cols: 1, rows: 1 };
    var cols = Math.max(1, Math.round(Math.sqrt(target * (W / H))));
    var rows = Math.max(1, Math.ceil(target / cols));
    return { cols: cols, rows: rows };
  }

  function segCellLabel(col, row) {
    var letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    var letter = col < 26 ? letters[col] : ('C' + (col + 1));
    return letter + (row + 1);
  }

  function renderAntennaSegmentedOverview(url, W, H, aps, opts, ctx, grid, keyHtml) {
    var cols = grid.cols, rows = grid.rows;
    var cb = opts.cropBox || { x: 0, y: 0, w: 1, h: 1 };
    var ox = cb.x * W, oy = cb.y * H;
    var rw = cb.w * W, rh = cb.h * H;
    var cw = rw / cols, ch = rh / rows;

    var cells = [];
    for (var ri = 0; ri < rows; ri++) {
      for (var ci = 0; ci < cols; ci++) {
        cells.push({ col: ci, row: ri, x0: ox + ci * cw, y0: oy + ri * ch, x1: ox + (ci + 1) * cw, y1: oy + (ri + 1) * ch, aps: [] });
      }
    }
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      if (c.x < ox || c.x > ox + rw || c.y < oy || c.y > oy + rh) return;
      var ci = Math.min(cols - 1, Math.max(0, Math.floor((c.x - ox) / cw)));
      var ri = Math.min(rows - 1, Math.max(0, Math.floor((c.y - oy) / ch)));
      cells[ri * cols + ci].aps.push(ap);
    });

    var nonEmpty = cells.filter(function (cell) { return cell.aps.length; });
    var emptyLabels = cells.filter(function (cell) { return !cell.aps.length; })
      .map(function (cell) { return segCellLabel(cell.col, cell.row); });

    var out = '<div class="rep-seg-note">Floor plan split into ' + nonEmpty.length + ' section' + (nonEmpty.length === 1 ? '' : 's')
      + ' (' + cols + '&times;' + rows + ' grid) so AP markers stay legible.'
      + (emptyLabels.length ? ' No APs in section' + (emptyLabels.length === 1 ? '' : 's') + ' ' + emptyLabels.join(', ') + ' — skipped.' : '')
      + '</div>';
    out += renderAntennaGridIndex(url, W, H, cells, nonEmpty, cb, segFloorHeading(opts));
    nonEmpty.forEach(function (cell) {
      out += renderAntennaSegmentCell(url, W, H, cell, opts, ctx, keyHtml, cells);
    });
    return out;
  }

  // What the grid overview page calls the floor. The storey number is what an
  // installer is told to go to, so it wins; a project that never set one still
  // gets the plan's own name rather than an unlabelled page.
  function segFloorHeading(opts) {
    if (opts.floorNumber !== null && opts.floorNumber !== undefined) return 'Floor ' + opts.floorNumber;
    return opts.floorName || '';
  }

  function renderAntennaGridIndex(url, W, H, allCells, nonEmptyCells, cb, floorHeading) {
    var gx = cb.x * W, gy = cb.y * H, gw = cb.w * W, gh = cb.h * H;
    var margin = Math.min(gw, gh) * 0.02;
    var vx = Math.max(0, gx - margin), vy = Math.max(0, gy - margin);
    var vW = Math.min(W - vx, gw + margin * 2), vH = Math.min(H - vy, gh + margin * 2);

    var nonEmptySet = {};
    nonEmptyCells.forEach(function (cell) { nonEmptySet[cell.col + ',' + cell.row] = true; });

    var lw = Math.min(gw, gh) * 0.004;
    var lines = '';
    allCells.forEach(function (cell) {
      var hasAps = nonEmptySet[cell.col + ',' + cell.row];
      lines += '<rect x="' + cell.x0 + '" y="' + cell.y0 + '" width="' + (cell.x1 - cell.x0) + '" height="' + (cell.y1 - cell.y0)
        + '" class="rep-grid-cell' + (hasAps ? '' : ' rep-grid-cell--empty') + '" stroke-width="' + lw + '"/>';
    });
    var dots = '';
    var dotR = Math.min(gw, gh) * 0.006;
    var defaultDotColor = '#78716c';
    allCells.forEach(function (cell) {
      if (!cell.aps) return;
      cell.aps.forEach(function (ap) {
        var c = ap.location && ap.location.coord; if (!c) return;
        var dotColor = ap.color || defaultDotColor;
        dots += '<circle cx="' + c.x + '" cy="' + c.y + '" r="' + dotR + '" fill="' + WD.escAttr(dotColor) + '" stroke="#fff" stroke-width="1"/>';
      });
    });
    var labels = '';
    var fontSize = Math.min(gw / (allCells.length > 0 ? Math.sqrt(allCells.length) : 1), gh / (allCells.length > 0 ? Math.sqrt(allCells.length) : 1)) * 0.4;
    allCells.forEach(function (cell) {
      var cx = (cell.x0 + cell.x1) / 2, cy = (cell.y0 + cell.y1) / 2;
      var hasAps = nonEmptySet[cell.col + ',' + cell.row];
      labels += '<text x="' + cx + '" y="' + cy + '" text-anchor="middle" dominant-baseline="middle" class="rep-grid-label' + (hasAps ? '' : ' rep-grid-label--empty') + '" font-size="' + fontSize + '">'
        + segCellLabel(cell.col, cell.row) + '</text>';
    });
    return '<div class="rep-overview rep-seg-index">'
      + (floorHeading ? '<div class="rep-seg-floor">' + WD.esc(floorHeading) + '</div>' : '')
      + '<div class="rep-overview-plan" data-seg="1" data-orig-w="' + W + '" data-orig-h="' + H
      +   '" data-seg-x0="' + vx + '" data-seg-y0="' + vy + '" data-seg-x1="' + (vx + vW) + '" data-seg-y1="' + (vy + vH)
      +   '" style="--w:' + vW + ';--h:' + vH + '">'
      +   '<img src="' + url + '" alt="Floor plan section index">'
      +   '<svg viewBox="' + vx + ' ' + vy + ' ' + vW + ' ' + vH + '" preserveAspectRatio="none">' + lines + dots + labels + '</svg>'
      + '</div>'
      + '<div class="rep-overview-key">Section index — each labeled cell is detailed on its own page below.</div>'
      + '</div>';
  }

  /* The Key Plan.

     Standard name, deliberately: a construction reader recognises "Key Plan"
     on sight and learns nothing from a label we invented. It is the companion
     to the match lines at the sheet edges - the match line answers "where does
     this join", the key plan answers "where am I in the building".

     It already shaded the current section. What it did not do was draw the
     others, so it told you which rectangle you were in without telling you
     what was next to it - which is most of what someone lost in a warehouse
     actually needs. Every section is now outlined and lettered, with this one
     filled. */
  function renderAntennaLocatorThumb(url, W, H, cell, cropBox, cells) {
    var cb = cropBox || { x: 0, y: 0, w: 1, h: 1 };
    var margin = Math.min(cb.w * W, cb.h * H) * 0.03;
    var vx = Math.max(0, cb.x * W - margin), vy = Math.max(0, cb.y * H - margin);
    var vW = Math.min(W - vx, cb.w * W + margin * 2), vH = Math.min(H - vy, cb.h * H + margin * 2);
    var lw = Math.min(vW, vH) * 0.008;

    var others = '';
    var all = cells || [];
    // Only worth lettering when the letters will be readable at thumbnail size.
    var labelAt = Math.min(vW, vH) * 0.055;
    var showLabels = all.length > 1 && all.length <= 30;
    all.forEach(function (c) {
      var isThis = (c.col === cell.col && c.row === cell.row);
      if (!isThis) {
        others += '<rect x="' + c.x0 + '" y="' + c.y0 + '" width="' + (c.x1 - c.x0)
          + '" height="' + (c.y1 - c.y0) + '" class="rep-seg-locator-other"'
          + ' stroke-width="' + (lw * 0.6) + '"/>';
      }
      if (showLabels) {
        others += '<text x="' + ((c.x0 + c.x1) / 2) + '" y="' + ((c.y0 + c.y1) / 2)
          + '" class="rep-seg-locator-label' + (isThis ? ' is-here' : '') + '"'
          + ' font-size="' + labelAt + '" text-anchor="middle"'
          + ' dominant-baseline="central">' + WD.esc(segCellLabel(c.col, c.row)) + '</text>';
      }
    });

    /* The caption sits outside the framed thumbnail, not inside it: the frame
       carries aspect-ratio and overflow:hidden so the plan keeps its shape,
       and anything else put in there is clipped away without trace. */
    return '<div class="rep-seg-keyplan">'
      + '<div class="rep-seg-locator" style="--w:' + vW + ';--h:' + vH + '">'
      +   '<svg viewBox="' + vx + ' ' + vy + ' ' + vW + ' ' + vH + '">'
      +     '<image href="' + WD.escAttr(url) + '" x="0" y="0" width="' + W + '" height="' + H + '" preserveAspectRatio="none"/>'
      +     others
      +     '<rect x="' + cell.x0 + '" y="' + cell.y0 + '" width="' + (cell.x1 - cell.x0) + '" height="' + (cell.y1 - cell.y0)
      +     '" class="rep-seg-locator-rect" stroke-width="' + lw + '"/>'
      +   '</svg>'
      + '</div>'
      + '<div class="rep-seg-locator-caption">Key Plan</div>'
      + '</div>';
  }

  /* Match lines: the other half of the pair the Key Plan belongs to.

     The key plan answers "where am I in the building". A match line answers
     "where does this drawing continue", at the edge where the reader runs out
     of paper. Standard name, drawn dashed along the shared edge and labelled
     with the section that carries on - which is how someone follows a run of
     racking from sheet to sheet.

     Only edges that actually continue get one. A section with no APs is never
     given a page, so an edge onto an empty section leads nowhere and marking
     it would be a promise of a sheet that does not exist. The building
     perimeter gets nothing either, for the same reason. */
  /* Where the label goes, and why it is not on the drawing any more.

     It used to be SVG text inside the plan, sized `min(cellW, cellH) * 0.045`.
     Those are source-image pixels mapped onto the sheet, so the size came out
     at 4.5% of the printed plan on every sheet size - about 24pt on a Letter
     section - and it sat just inside the edge it marked. On the bottom edge
     that runs it straight through the AP markers and their labels, and an
     installer cannot read the AP identifiers underneath it, which is the one
     thing the sheet exists for.

     So: the dashed line stays exactly where it is, because it marks the real
     cut and is part of the drawing. The label is HTML in the gutter outside
     the image, set in points so it is the same size on every sheet. Nothing
     that is not part of the drawing gets painted over the drawing. */
  function matchLinesFor(cell, cells, cW, cH) {
    var empty = { svg: '', labels: '' };
    if (!cells || cells.length < 2) return empty;
    var byPos = {};
    cells.forEach(function (c) { byPos[c.col + ',' + c.row] = c; });
    var at = function (dc, dr) {
      var c = byPos[(cell.col + dc) + ',' + (cell.row + dr)];
      return (c && c.aps && c.aps.length) ? c : null;
    };
    var dash = Math.min(cW, cH) * 0.035;
    var sw = Math.min(cW, cH) * 0.006;
    var svg = '', labels = '';

    function edge(neighbour, side, x1, y1, x2, y2) {
      if (!neighbour) return;
      svg += '<line class="rep-matchline" x1="' + x1 + '" y1="' + y1
        + '" x2="' + x2 + '" y2="' + y2 + '" stroke-width="' + sw
        + '" stroke-dasharray="' + dash + ',' + (dash * 0.6) + '"/>';
      labels += '<div class="rep-matchline-edge is-' + side + '">'
        + 'MATCH LINE \u2014 SECTION '
        + WD.esc(segCellLabel(neighbour.col, neighbour.row)) + '</div>';
    }

    edge(at(1, 0),  'right',  cell.x1, cell.y0, cell.x1, cell.y1);
    edge(at(-1, 0), 'left',   cell.x0, cell.y0, cell.x0, cell.y1);
    edge(at(0, 1),  'bottom', cell.x0, cell.y1, cell.x1, cell.y1);
    edge(at(0, -1), 'top',    cell.x0, cell.y0, cell.x1, cell.y0);
    return { svg: svg, labels: labels };
  }

  function renderAntennaSegmentCell(url, W, H, cell, opts, ctx, keyHtml, cells) {
    var cW = cell.x1 - cell.x0, cH = cell.y1 - cell.y0;
    var bleed = Math.min(cW, cH) * 0.03;
    var vx = Math.max(0, cell.x0 - bleed), vy = Math.max(0, cell.y0 - bleed);
    var vx2 = Math.min(W, cell.x1 + bleed), vy2 = Math.min(H, cell.y1 + bleed);
    var vW = vx2 - vx, vH = vy2 - vy;
    var label = segCellLabel(cell.col, cell.row);
    var match = matchLinesFor(cell, cells, cW, cH);
    var markers = buildAntennaMarkers(cell.aps, cW, cH, opts, ctx, cell) + match.svg;
    return '<div class="rep-overview rep-seg-cell">'
      + '<div class="rep-seg-cell-head">' + renderAntennaLocatorThumb(url, W, H, cell, opts.cropBox, cells)
      +   '<h3 class="rep-seg-cell-title">Section ' + WD.esc(label)
      +     (opts.floorName ? ' <span class="rep-seg-cell-floor">— ' + WD.esc(opts.floorName) + '</span>' : '')
      +     ' <span class="rep-seg-cell-count">— ' + cell.aps.length + ' AP' + (cell.aps.length === 1 ? '' : 's') + '</span></h3>'
      + '</div>'
      + '<div class="rep-seg-plan-wrap">'
      +   match.labels
      +   '<div class="rep-overview-plan" data-seg="1" data-orig-w="' + W + '" data-orig-h="' + H
      +     '" data-seg-x0="' + vx + '" data-seg-y0="' + vy + '" data-seg-x1="' + vx2 + '" data-seg-y1="' + vy2
      +     '" style="--w:' + vW + ';--h:' + vH + '">'
      +     '<img src="' + url + '" alt="Floor plan section ' + WD.escAttr(label) + '">'
      +     '<svg viewBox="' + vx + ' ' + vy + ' ' + vW + ' ' + vH + '" preserveAspectRatio="none">' + markers + '</svg>'
      +   '</div>'
      + '</div>'
      + (keyHtml ? '<div class="rep-overview-key">' + keyHtml + '</div>' : '')
      + '</div>';
  }

  function cropAntennaSegment(overlayEl) {
    sizeAntennaSegmentForPrint(overlayEl);
    if (overlayEl._segCropPromise) return overlayEl._segCropPromise;
    if (overlayEl.getAttribute('data-seg-cropped') === '1') return Promise.resolve();
    var img = overlayEl.querySelector('img');
    if (!img) return Promise.resolve();
    var W = parseFloat(overlayEl.getAttribute('data-orig-w'));
    var H = parseFloat(overlayEl.getAttribute('data-orig-h'));
    var x0 = parseFloat(overlayEl.getAttribute('data-seg-x0'));
    var y0 = parseFloat(overlayEl.getAttribute('data-seg-y0'));
    var x1 = parseFloat(overlayEl.getAttribute('data-seg-x1'));
    var y1 = parseFloat(overlayEl.getAttribute('data-seg-y1'));
    if (!W || !H) return Promise.resolve();

    overlayEl._segCropPromise = new Promise(function (resolve) {
      function ready() {
        try { doCrop(resolve); } catch (e) { console.error('segment crop', e); resolve(); }
      }
      if (img.complete && img.naturalWidth) ready();
      else { img.addEventListener('load', ready, {once: true});
             img.addEventListener('error', function () { resolve(); }, {once: true}); }
    });
    return overlayEl._segCropPromise;

    function doCrop(done) {
      var natW = img.naturalWidth, natH = img.naturalHeight;
      if (!natW || !natH) { done(); return; }
      var srcX = Math.max(0, Math.round(natW * x0 / W));
      var srcY = Math.max(0, Math.round(natH * y0 / H));
      var srcW = Math.min(natW - srcX, Math.max(1, Math.round(natW * (x1 - x0) / W)));
      var srcH = Math.min(natH - srcY, Math.max(1, Math.round(natH * (y1 - y0) / H)));
      var outScale = Math.min(2, 1800 / Math.max(srcW, srcH));
      var c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(srcW * outScale));
      c.height = Math.max(1, Math.round(srcH * outScale));
      c.getContext('2d').drawImage(img, srcX, srcY, srcW, srcH, 0, 0, c.width, c.height);
      c.toBlob(function (blob) {
        if (!blob) { done(); return; }
        var croppedUrl = URL.createObjectURL(blob);
        function settled() {
          overlayEl.setAttribute('data-seg-cropped', '1');
          done();
        }
        img.addEventListener('load', settled, {once: true});
        img.addEventListener('error', settled, {once: true});
        img.src = croppedUrl;
      }, 'image/jpeg', 0.9);
    }
  }

  function sizeAntennaSegmentForPrint(overlayEl) {
    var x0 = parseFloat(overlayEl.getAttribute('data-seg-x0'));
    var y0 = parseFloat(overlayEl.getAttribute('data-seg-y0'));
    var x1 = parseFloat(overlayEl.getAttribute('data-seg-x1'));
    var y1 = parseFloat(overlayEl.getAttribute('data-seg-y1'));
    var ratio = (x1 - x0) / (y1 - y0);
    if (!isFinite(ratio) || ratio <= 0) return;

    /* Fit both US Letter and A4 portrait after the page chrome around the map,
       less the gutter the match line labels now sit in: .rep-seg-plan-wrap
       pads 0.26in at the sides and below and 0.16in above, and the plan has to
       give that back or the wrapper is wider than the sheet. */
    var maxWidthIn = 6.9;
    // The index page now carries the large floor header above the map, so it
    // has about 0.6in less to work with than it used to.
    var maxHeightIn = overlayEl.closest('.rep-seg-index') ? 7.13 : 7.48;
    var widthIn = Math.min(maxWidthIn, maxHeightIn * ratio);
    var heightIn = widthIn / ratio;
    overlayEl.style.setProperty('--print-w', widthIn.toFixed(3) + 'in');
    overlayEl.style.setProperty('--print-h', heightIn.toFixed(3) + 'in');
  }

  function applyAntennaSegmentCrop(host, opts) {
    if (!opts.segmented) return Promise.resolve();
    var overlays = host.querySelectorAll('.rep-overview-plan[data-seg="1"]');
    var pending = [];
    for (var i = 0; i < overlays.length; i++) pending.push(cropAntennaSegment(overlays[i]));
    return Promise.all(pending);
  }

  window.printReport = async function () {
    syncDocTitle();
    var host = document.getElementById('reportCanvas');
    await applyAntennaSegmentCrop(host, collectOpts());
    var images = Array.prototype.slice.call(host.querySelectorAll('img'));
    await Promise.all(images.map(function (img) {
      if (img.complete) return Promise.resolve();
      return new Promise(function (resolve) {
        img.addEventListener('load', resolve, {once: true});
        img.addEventListener('error', resolve, {once: true});
      });
    }));
    window.print();
  };





  // ── AP Placement Map ──────────────────────────────────────────────────────
  // One floor, one page, the plan and the APs on it. Everything the other
  // placement reports add -- section grids, aiming cones, tables, audits -- is
  // deliberately absent unless asked for: this is the sheet that goes in a
  // folder or on a wall, and it has to survive being printed and read at arm's
  // length in a corridor.
  function renderPlacementFloorSection(fp, aps, opts, ctx, floorIdx) {
    var sorted = aps.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var heading = fp.id === '_none' ? '' : segFloorHeading({
      floorNumber: floorNumberFor(fp),
      floorName: fp.name || 'Floor plan',
    });
    var count = sorted.length + ' AP' + (sorted.length === 1 ? '' : 's');
    var fid = WD.escAttr(fp.id);
    var out = '<section class="rep-floor-section rep-placement-page rep-oriented"'
      + ' data-floor-idx="' + (floorIdx % 5) + '"'
      + ' data-floor-id="' + fid + '"'
      + ' data-page-key="placement:' + fid + '" data-page-kind="plan">'
      + orientPickerHtml('placement:' + fp.id, opts)
      + '<div class="rep-placement-sheet">';
    if (heading) {
      out += '<div class="rep-seg-floor rep-placement-head">' + WD.esc(heading)
        + '<span class="rep-placement-sub">' + WD.esc((fp.name || '') + ' · ' + count) + '</span></div>';
    } else {
      out += '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
    }
    out += (fp.id !== '_none')
      ? renderAntennaOverview(fp, sorted, opts, ctx, placementKeyHtml(opts, sorted))
      : '<div class="rep-empty-small">No floor plan assigned to these APs.</div>';
    out += renderReportFooter(opts, ctx);
    return out + '</div></section>';
  }

  /* Orientation belongs to a page, not to a floor.

     It started on the placement map, keyed by floor id, because that was the
     only page that could want turning. Every page can want it: a thirteen-
     column table wants landscape on a sheet where the map beside it wants
     portrait. So the key is now whatever identifies the page - "cover",
     "loc-table", "key:<floor>", "placement:<floor>" - and the map is the same
     map, which is why settings saved before this still load. */
  function pageOrientMode(pageKey, opts) {
    var map = opts && opts.pageOrient;
    return (map && map[pageKey]) || 'auto';
  }
  var floorOrientMode = pageOrientMode;   // the name the placement map used

  /* What a page wants when nobody has said. Decided per page type, because the
     question is different for each: a plan asks which way round it prints
     bigger, a table asks whether its columns fit across a portrait sheet.

     Anything not listed stays portrait, which is the safe default - a page that
     fitted before this change still fits. */
  // The printable width of a portrait sheet, in CSS pixels at 96 per inch.
  // Same figure the plan sizing uses, expressed in the units a DOM measurement
  // comes back in. Read through a function because SHEET_W_IN is declared
  // further down the file: computing it here at load time would take the
  // hoisted `undefined` and quietly give NaN, and every comparison against a
  // NaN is false, so every table would have come out portrait and looked
  // deliberate.
  function portraitContentPx() { return SHEET_W_IN * 96; }
  // Turning the paper costs the reader something, so a table has to be
  // properly over the line rather than a few pixels over it.
  var TABLE_TURN_MARGIN = 1.08;
  // Used only when the table cannot be measured - a rough stand-in, not the
  // rule.
  var WIDE_TABLE_COLUMNS = 9;

  /* How wide the table wants to be, with nothing squeezing it.

     Measuring it where it sits answers the wrong question: on screen the
     report is about 900px across and a printed portrait sheet is about 715,
     so a table that looks comfortable is not necessarily one that fits. What
     matters is the width the content asks for, which is what max-content
     reports, measured off-screen so the reader sees nothing. */
  function naturalTableWidth(table) {
    if (!table || !table.cloneNode) return 0;
    var probe = document.createElement('div');
    probe.style.cssText = 'position:absolute;left:-99999px;top:0;' +
      'width:max-content;visibility:hidden;pointer-events:none';
    var copy = table.cloneNode(true);
    // The print stylesheet fixes the layout and sets column widths; neither
    // says anything about what the text actually needs.
    copy.style.tableLayout = 'auto';
    copy.style.width = 'max-content';
    var cg = copy.querySelector('colgroup');
    if (cg) cg.remove();
    probe.appendChild(copy);
    document.body.appendChild(probe);
    var w = 0;
    try { w = copy.getBoundingClientRect().width || copy.scrollWidth || 0; }
    catch (e) { w = 0; }
    probe.remove();
    return w;
  }

  function autoOrientationFor(page) {
    var kind = page.getAttribute('data-page-kind') || '';

    if (kind === 'plan') return null;      // the plan pass below decides

    if (kind === 'table') {
      var table = page.querySelector('table');
      var natural = naturalTableWidth(table);
      if (natural > 0) {
        // Two narrow columns of short values want portrait however many rows
        // they run to; thirteen columns of AP detail want the long edge.
        return natural > portraitContentPx() * TABLE_TURN_MARGIN
          ? 'landscape' : 'portrait';
      }
      var head = page.querySelector('thead tr');
      var cols = head ? head.children.length : 0;
      return cols >= WIDE_TABLE_COLUMNS ? 'landscape' : 'portrait';
    }
    return 'portrait';
  }

  function orientPickerHtml(fpId, opts) {
    var mode = pageOrientMode(fpId, opts);
    var btn = function (val, label) {
      return '<button type="button" class="rep-orient-btn' + (mode === val ? ' is-on' : '') + '"'
        + ' data-action="call" data-fn="setPageOrient" data-arg="' + WD.escAttr(fpId) + '" data-arg2="' + WD.escAttr(val) + '">' + label + '</button>';
    };
    /* "Match all pages to this" is here because it is the correct thing to do
        in a browser that cannot mix, and because doing it by hand across a
        dozen pages is what he ended up doing.

        Mixing orientations within one document is driven by named @page rules.
        Chrome and Edge honour them - measured by printing the same six-page
        document from each and reading the sheet sizes back out of the PDF.

        What happens elsewhere is NOT established. Firefox reports the `page`
        property as supported, so it may well honour them too; a headless print
        could not be driven here to find out. Until someone checks, this button
        is offered as the remedy for a report that comes out clipped rather
        than as a claim about any particular browser. */
    return '<div class="rep-orient noprint" data-for="' + WD.escAttr(fpId) + '">'
      + '<span class="rep-orient-label">Page</span>'
      + btn('auto', 'Auto') + btn('portrait', 'Portrait') + btn('landscape', 'Landscape')
      + '<span class="rep-orient-now"></span>'
      + '<button type="button" class="rep-orient-all"'
      +   ' data-action="call" data-fn="matchAllPageOrient" data-arg="' + WD.escAttr(fpId) + '"'
      +   ' title="Give every page in this report the orientation this one is using.'
      +   ' Mixing portrait and landscape in one document is verified in Chrome'
      +   ' and Edge. If pages come out clipped in another browser, use this to'
      +   ' put the whole report one way round.">Match all pages</button>'
      + '</div>';
  }

  /* Every orientable page in the report takes the orientation this one has
     resolved to. "Auto" is deliberately resolved first rather than copied: the
     point is that every page ends up the same way round, and copying "auto"
     would leave each page free to decide differently again. */
  window.matchAllPageOrient = function (fpId) {
    var host = document.getElementById('reportCanvas');
    if (!host) return;
    var src = host.querySelector('[data-page-key="' + fpId + '"]');
    var mode = pageOrientMode(fpId, currentOpts);
    if (mode === 'auto') {
      mode = (src && src.classList.contains('is-landscape')) ? 'landscape' : 'portrait';
    }
    if (!currentOpts.pageOrient) currentOpts.pageOrient = {};
    var keys = host.querySelectorAll('[data-page-key]');
    for (var i = 0; i < keys.length; i++) {
      currentOpts.pageOrient[keys[i].getAttribute('data-page-key')] = mode;
    }
    sizePlacementPlansForPrint(host, currentOpts);
    applyPageOrientation(host, currentOpts);
    persistPageOrient();
    configureDirty = true;
    var n = keys.length;
    showToast('All ' + n + ' page' + (n === 1 ? '' : 's') + ' set to ' + mode, 'success');
    // The buttons on every other picker are now wrong.
    var pickers = host.querySelectorAll('.rep-orient');
    for (var p = 0; p < pickers.length; p++) {
      var btns = pickers[p].querySelectorAll('.rep-orient-btn');
      for (var b = 0; b < btns.length; b++) {
        btns[b].classList.toggle('is-on', btns[b].textContent.toLowerCase() === mode);
      }
    }
  };

  window.setPageOrient = function (fpId, mode) {
    if (!currentOpts.pageOrient) currentOpts.pageOrient = {};
    currentOpts.pageOrient[fpId] = mode;
    var host = document.getElementById('reportCanvas');
    if (!host) return;
    var picker = host.querySelector('.rep-orient[data-for="' + fpId + '"]');
    if (picker) {
      var btns = picker.querySelectorAll('.rep-orient-btn');
      for (var i = 0; i < btns.length; i++) {
        btns[i].classList.toggle('is-on', btns[i].textContent.toLowerCase() === mode);
      }
    }
    // Sizing is the only thing orientation changes, so recompute rather than
    // rebuilding the report and losing the reader's scroll position.
    sizePlacementPlansForPrint(host, currentOpts);
    applyPageOrientation(host, currentOpts);
    persistPageOrient();
    configureDirty = true;
  };
  window.setFloorOrient = window.setPageOrient;   // the older name

  /* Kept with the rest of the report settings so a document that needed one
     portrait page in a landscape run does not need setting up again next time.
     Failing to save is not worth interrupting anyone over. */
  /* Through pushSettings, so the patch envelope is applied in one place.

     This used to post { report: {...} } directly. The server reads
     d.get("patch", {}), so it merged an empty dict: the save succeeded, ok
     came back, nothing was written, and nothing complained. Every per-page
     orientation choice was therefore lost at the end of the session, which
     looked exactly like the orientation feature not working - and no amount
     of checking it inside one session would have shown it. */
  var _orientSaveTimer = null;
  function persistPageOrient() {
    if (!settingsAvailable) return;
    /* Coalesced, because "Match all pages" changes a dozen at once and each
       change used to post its own save.

       Saving is read-modify-write on one file with no lock, so concurrent
       posts race and the last writer wins - carrying whatever map it read,
       which need not be the newest. Setting four pages in quick succession
       reliably stored three. One trailing save per burst removes the race at
       the only place that creates it, and it always carries the final map. */
    clearTimeout(_orientSaveTimer);
    _orientSaveTimer = setTimeout(function () {
      pushSettings({ page_orient: currentOpts.pageOrient || {} })
        .catch(function () {});
    }, 350);
  }

  /* Turn every page that has an opinion, then let the plan pass size the maps
     inside whichever way round they ended up. */
  function applyPageOrientation(host, opts) {
    var pages = host.querySelectorAll('[data-page-key]');
    for (var i = 0; i < pages.length; i++) {
      var page = pages[i];
      var mode = pageOrientMode(page.getAttribute('data-page-key'), opts || {});
      var want = mode === 'auto' ? autoOrientationFor(page) : mode;
      if (want === null) continue;         // a plan; sized separately
      page.classList.toggle('is-landscape', want === 'landscape');
      var now = page.querySelector('.rep-orient-now');
      if (now) now.textContent = (mode === 'auto' ? 'auto \u2192 ' : '') + want;
    }
  }

  function placementKeyHtml(opts, aps) {
    var bits = [keySwatch('omni', aps) + ' Access point'];
    if (opts.showCones) bits.push(keySwatch('dir', aps) + ' Directional, arrow shows aim');
    return bits.join(' &nbsp;·&nbsp; ');
  }

  /* Split a structured AP name into labelled segments, but only when it
     really is one.

     This read the Labeler's old fixed CLLI / Building / Floor / Suite fields.
     Those stopped being written when the Labeler moved to a draggable segment
     list, so pat.clli and friends have been undefined ever since and this
     could never match a five-part name - the Naming scheme header simply
     stopped appearing, silently, for everyone on the current version.

     It reads the segment list now, which is what the Labeler actually saves:
     an ordered run of text / floor / counter parts. A name is still only
     annotated when it genuinely matches - same separator, same count, fixed
     parts equal to what was saved, a number where the counter goes - and
     anything else returns null rather than guessing at a name that came from
     somewhere else. */
  function structuredSegments(name, pat) {
    if (!name || !pat || !pat.segments || !pat.segments.length) return null;
    var sep = pat.sepS || '-';
    if (sep.length !== 1) return null;
    var parts = String(name).split(sep);
    // A text segment with no value contributes nothing to the built name.
    var segs = pat.segments.filter(function (sg) {
      return !(sg.type === 'text' && !sg.value);
    });
    if (parts.length !== segs.length) return null;

    var out = [];
    for (var i = 0; i < segs.length; i++) {
      var part = parts[i], sg = segs[i];
      if (sg.type === 'text') {
        if (part !== sg.value) return null;
        out.push({ label: '', value: part });
      } else if (sg.type === 'floor') {
        // A fixed floor override has to match exactly; an automatic one only
        // has to look like a floor.
        if (sg.value) { if (part !== sg.value) return null; }
        else if (!/^[0-9A-Za-z]+$/.test(part)) return null;
        out.push({ label: 'Floor', value: part });
      } else {
        var tag = sg.tag || '';
        var tagRe = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        if (tag && !new RegExp('^' + tagRe + '\\d+', 'i').test(part)) return null;
        if (!tag && !/^\d+$/.test(part)) return null;
        out.push({ label: 'AP', value: part });
      }
    }
    return out;
  }

  // Compact markers are the reason this page exists: the plan shows "01" and
  // the installer needs the name that goes with it.
  function markersAreCompact(aps, opts) {
    if (opts.shortLabels === false) return false;
    return aps.some(function (ap) {
      var full = apLabel(ap, 'full');
      var short = apLabel(ap, 'short');
      return short && full && short !== full;
    });
  }

  function wantsNameKey(aps, opts) {
    var mode = opts.nameKey || 'auto';
    if (mode === 'never') return false;
    if (mode === 'always') return true;
    return markersAreCompact(aps, opts);
  }

  /* One page per floor, in the same order and with the same heading as the map
     it belongs to. Names are never shortened or wrapped here - the installer
     copies them onto a physical label - so the column is sized for the longest
     name on the floor and the page scrolls to two columns rather than
     squeezing one. */
  /* A reference page names itself first, then says which floor it belongs to.

     Both of these pages used to take the floor heading as their title, which
     on a plan with no floor number resolves to the floor's own name - printed
     at 30px as if it were the page title, then repeated in the line beneath,
     while nothing on the page said what the page actually was. The compass
     reference gets this right: a descriptive title in .rep-floor-title, and
     that is the treatment these now share. */
  function referencePageHead(title, fp, countText) {
    var heading = fp.id === '_none' ? '' : segFloorHeading({
      floorNumber: floorNumberFor(fp),
      floorName: fp.name || 'Floor plan',
    });
    var bits = [];
    if (heading) bits.push(heading);
    // Only add the floor name when the heading is not already it.
    if (fp.name && fp.name !== heading) bits.push(fp.name);
    if (countText) bits.push(countText);
    return '<h2 class="rep-floor-title">' + WD.esc(title) + '</h2>'
      + (bits.length
          ? '<p class="rep-ref-sub">' + WD.esc(bits.join(' · ')) + '</p>'
          : '');
  }

  function renderApNameKeySection(fp, aps, opts, ctx, floorIdx) {
    var sorted = aps.slice().sort(function (a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var count = sorted.length + ' AP' + (sorted.length === 1 ? '' : 's');

    var sample = null;
    for (var i = 0; i < sorted.length && !sample; i++) {
      sample = structuredSegments(sorted[i].name, labelerPattern);
    }
    var scheme = '';
    if (sample) {
      scheme = '<div class="rep-key-scheme"><div class="rep-key-scheme-lbl">Naming scheme</div>'
        + '<div class="rep-key-scheme-row">'
        /* The separator is whatever the Labeler used, not always a hyphen.
           And only the segments we can actually name are labelled: the
           Labeler has no name for a text segment, so captioning three of them
           "Text" says nothing and reads as noise. The value is the point. */
        + sample.map(function (seg, k) {
            var sep = (labelerPattern && labelerPattern.sepS) || '-';
            return (k ? '<span class="rep-key-sep">' + WD.esc(sep) + '</span>' : '')
              + '<span class="rep-key-seg"><b>' + WD.esc(seg.value) + '</b>'
              + (seg.label ? '<i>' + WD.esc(seg.label) + '</i>' : '')
              + '</span>';
          }).join('')
        + '</div></div>';
    }

    var rows = sorted.map(function (ap) {
      var num = apLabel(ap, 'short');
      var full = apLabel(ap, 'full') || '(unnamed)';
      return '<tr><td class="rep-key-num">' + WD.esc(num) + '</td>'
        + '<td class="rep-key-name">' + WD.esc(full) + '</td></tr>';
    }).join('');

    var out = '<section class="rep-floor-section rep-key-page rep-oriented"'
      + ' data-page-key="key:' + WD.escAttr(fp.id) + '" data-page-kind="table"'
      + ' data-floor-idx="' + (floorIdx % 5) + '">'
      + orientPickerHtml('key:' + fp.id, opts)
      + referencePageHead('AP Labels', fp, count);
    out += '<p class="rep-key-intro">The plan shows the number. Write the full name on the label.</p>'
      + scheme
      + '<table class="rep-key-table"><thead><tr>'
      + '<th class="rep-key-num">#</th><th>Full AP name</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>'
      + renderReportFooter(opts, ctx);
    return out + '</section>';
  }

  /* ── AP notes pages ────────────────────────────────────────────────────
     Notes an engineer typed on site against an AP. They exist in the project
     and had no way out of it, which is the whole reason this page exists.

     Text only, deliberately. A note carrying an image is still listed - with
     its text if it has any, and a marker saying an image is attached - because
     silently dropping a note is how an installer misses the one that mattered.
     The image itself is not rendered and no layout path exists for one. */
  function notesForAp(ap, ctx) {
    var store = (ctx.proj && ctx.proj.notes) || {};
    var ids = (ap && ap.noteIds) || [];
    var out = [];
    for (var i = 0; i < ids.length; i++) {
      var n = store[ids[i]];
      if (!n) continue;                       // dangling id: nothing to show
      var text = String(n.text == null ? '' : n.text).trim();
      var images = (n.imageIds || []).length;
      if (!text && !images) continue;         // an empty note is not a note
      out.push({ text: text, images: images });
    }
    return out;
  }

  function apsWithNotes(aps, ctx) {
    return aps.filter(function (ap) { return notesForAp(ap, ctx).length > 0; });
  }

  /* Auto / Always / Never, the same shape the compass and label-reference
     pages use. It was a checkbox until v2.98.8, so a saved default is still a
     boolean for anyone who set one: false is the person who deliberately
     turned notes off and must keep getting no notes pages, true is the person
     who turned them on. Reading those as 'auto' would put site notes into a
     deliverable for someone who had switched them off, which is the one
     mistake this option exists to avoid. */
  function apNotesMode(opts) {
    var v = (opts || {}).apNotes;
    if (v === true) return 'always';
    if (v === false) return 'never';
    return v || 'auto';
  }

  function wantsApNotes(aps, opts, ctx) {
    var mode = apNotesMode(opts);
    if (mode === 'never') return false;
    if (mode === 'always') return true;
    return apsWithNotes(aps, ctx).length > 0;
  }

  /* Every report can carry the notes pages, so the per-floor loop lives here
     rather than being copied into each renderer. A floor with no notes
     contributes nothing, so "always" on a project without notes is simply an
     empty answer rather than a page saying nothing. */
  function apNotesPages(aps, opts, ctx) {
    if (!wantsApNotes(aps, opts, ctx)) return '';
    var byFloor = groupApsByFloor(aps, ctx);
    var out = '';
    var idx = 0;
    sortedFloorOrder(byFloor).forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      var sec = renderApNotesSection(fp, floorAps, opts, ctx, idx);
      if (sec) { out += sec; idx++; }
    });
    return out;
  }

  /* One page per floor, same order and same heading as the map it belongs to,
     so a note sits with the plan it was written on. */
  function renderApNotesSection(fp, aps, opts, ctx, floorIdx) {
    var withNotes = apsWithNotes(aps, ctx);
    if (!withNotes.length) return '';

    var sorted = withNotes.slice().sort(function (a, b) {
      return String(apLabel(a, 'full')).localeCompare(String(apLabel(b, 'full')),
        undefined, { numeric: true, sensitivity: 'base' });
    });

    var count = withNotes.length + (withNotes.length === 1 ? ' AP with notes' : ' APs with notes');

    var rows = sorted.map(function (ap) {
      var items = notesForAp(ap, ctx).map(function (n) {
        var body = n.text
          ? '<span class="rep-note-text">' + WD.esc(n.text) + '</span>'
          : '<span class="rep-note-empty">No text on this note.</span>';
        var flag = n.images
          ? '<span class="rep-note-img">Image attached'
            + (n.images > 1 ? ' ×' + n.images : '')
            + ' — not shown in this report</span>'
          : '';
        return '<li class="rep-note-item">' + body + flag + '</li>';
      }).join('');
      return '<tr>'
        + '<td class="rep-note-ap">' + WD.esc(apLabel(ap, 'full') || '(unnamed)') + '</td>'
        + '<td class="rep-note-body"><ul class="rep-note-list">' + items + '</ul></td>'
        + '</tr>';
    }).join('');

    var out = '<section class="rep-floor-section rep-notes-page rep-oriented"'
      + ' data-page-key="notes:' + WD.escAttr(fp.id) + '" data-page-kind="table"'
      + ' data-floor-idx="' + (floorIdx % 5) + '">'
      + orientPickerHtml('notes:' + fp.id, opts)
      + referencePageHead('AP Notes', fp, count);
    out += '<p class="rep-notes-intro">Notes recorded against an access point in the survey.</p>'
      + '<table class="rep-notes-table"><thead><tr>'
      + '<th class="rep-note-ap">Access point</th><th>Note</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table>'
      + renderReportFooter(opts, ctx);
    return out + '</section>';
  }

  function renderPlacementReport(aps, opts, ctx) {
    var head = opts.cover ? ctx.cover(aps.length, ctx.dateStr, 'Access points')
                          : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points');
    // Carried over from Predictive Design when the two templates merged, so
    // nobody who relied on it lost it.
    head += opts.summary ? renderSummaryStrip(aps, ctx) : '';
    var byFloor = groupApsByFloor(aps, ctx);
    var floorOrder = sortedFloorOrder(byFloor);
    var sections = '';
    var idx = 0;
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderPlacementFloorSection(fp, floorAps, opts, ctx, idx);
      idx++;
    });
    // The label reference follows the maps, one page per floor in the same
    // order, so an installer working a floor finds its names right after its
    // plan.
    if (wantsNameKey(aps, opts)) {
      var kidx = 0;
      floorOrder.forEach(function (fp) {
        var floorAps = byFloor[fp.id];
        if (!floorAps || !floorAps.length) return;
        sections += renderApNameKeySection(fp, floorAps, opts, ctx, kidx);
        kidx++;
      });
    }
    if (!sections) sections = '<div class="rep-empty-small">No APs with a position on a floor plan.</div>';
    var compassPage = wantsCompassRef(aps, opts) ? renderCompassReferencePage(opts, ctx) : '';
    // Notes go last, after the compass page, and that ordering is a decision
    // rather than a layout preference: the notes section is **unbounded**. It
    // is short text tables today, but a survey that photographs every AP - the
    // way Mist's installer app requires - could carry one note and one image
    // per access point, and an open-ended section cannot be allowed to push
    // fixed reference material around. Every other report already ended with
    // it; this one printed the compass sheet after it, so a document could end
    // on a reference page whose position depended on how many notes the
    // project happened to have.
    return head + sections + compassPage + apNotesPages(aps, opts, ctx);
  }

  // A full-page plan has no segment cropping to size it, so without this the
  // image keeps its own aspect and a tall floor runs onto a second sheet.
  // The printable area, in inches, of a portrait sheet after the @page margins.
  // Letter is 8.5x11 and A4 is 8.27x11.7, so the narrower width and the shorter
  // height keep one report correct on either.
  // A4 is the narrower of the two (8.27in) and Letter the shorter (11in), so
  // taking the width from A4 and the height from Letter keeps one report
  // correct on either without a second layout.
  var SHEET_W_IN = 7.45;
  var SHEET_H_IN = 10.0;
  /* What the floor header, the key line and the footer cost, off whichever edge
     runs vertically. Measured off a printed page rather than estimated, because
     estimating it is what went wrong twice.

     At 1.15in the key landed on a sheet of its own. At 1.5in the key fitted but
     the footer did not, and it went to a page of its own carrying nothing but
     the running header - the map was taking every inch the estimate left, so
     anything the estimate had missed had nowhere to go. Measuring a printed
     landscape sheet: heading 0.64in, key 0.24in, footer with the
     confidentiality line 0.57in, and the section's own bottom padding 0.23in,
     which the old figure had not counted at all. That is 1.68in against 1.5in
     allowed, and the 0.18in it overran by was the whole bug.

     The padding is now dropped in print - it is wasted on a sheet - and this
     figure carries slack on top of the 1.45in the furniture actually needs, so
     a footer that wraps to a second line still has somewhere to go. */
  var SHEET_CHROME_IN = 1.5;
  /* Held apart from the figure above on purpose. That one decides whether
     turning the sheet is worth it, by comparing two scales against each other,
     and it has been right about that since 2.28. This one is only about how
     much room the map may actually take, and raising the shared figure to make
     the map fit moved the rotate decision as a side effect - a floor that
     should print landscape started printing portrait. */
  var SHEET_SLACK_IN = 0.2;
  // A turned sheet has to earn it. Below this much extra scale the reader is
  // rotating paper for nothing.
  var ROTATE_GAIN = 1.15;

  // The aspect that matters is the one on screen. A plan that PlanTrim has
  // cropped is a different shape from the canvas it came out of, and the image
  // is the thing that got cropped, so measure that and fall back to the stored
  // dimensions only when it has not loaded.
  function planAspect(el) {
    var img = el.querySelector('img');
    if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
      return img.naturalWidth / img.naturalHeight;
    }
    var w = parseFloat(el.style.getPropertyValue('--w'));
    var h = parseFloat(el.style.getPropertyValue('--h'));
    return (w > 0 && h > 0) ? w / h : 0;
  }

  function sizePlacementPlansForPrint(host, opts) {
    var pages = host.querySelectorAll('.rep-placement-page');
    for (var i = 0; i < pages.length; i++) {
      var page = pages[i];
      var el = page.querySelector('.rep-overview-plan:not([data-seg="1"])');
      if (!el) continue;
      var ratio = planAspect(el);
      if (!(ratio > 0)) continue;

      // Two ways the plan can sit on the sheet. Compare the scale each gives it
      // rather than the aspect ratio alone, so the decision is about how big the
      // map actually prints.
      var upW = SHEET_W_IN, upH = SHEET_H_IN - SHEET_CHROME_IN;
      var rotW = SHEET_H_IN, rotH = SHEET_W_IN - SHEET_CHROME_IN;
      var upright = Math.min(upW / ratio, upH);        // printed height, upright
      var turned = Math.min(rotW / ratio, rotH);       // printed height, turned
      var wants = turned > upright * ROTATE_GAIN;

      var mode = pageOrientMode(page.getAttribute('data-page-key'), opts || {});
      var rotate = mode === 'landscape' ? true : mode === 'portrait' ? false : wants;

      var boxW = rotate ? rotW : upW;
      var boxH = (rotate ? rotH : upH) - SHEET_SLACK_IN;
      var hIn = Math.min(boxH, boxW / ratio);
      var wIn = hIn * ratio;

      // The page itself turns, via a named @page rule. Rotating the content
      // instead was tried and rejected: it does print the map larger, but it
      // leaves half the sheet blank and every label lying on its side.
      page.classList.toggle('is-landscape', rotate);
      el.style.setProperty('--print-w', wIn.toFixed(3) + 'in');
      el.style.setProperty('--print-h', hIn.toFixed(3) + 'in');
      // Named pages are a Chromium feature. Where they are not honoured the
      // sheet stays portrait, so the map has to be able to fall back to fitting
      // the width it actually gets rather than overflowing the one it asked
      // for. The ratio drives the height so it stays undistorted either way.
      el.style.setProperty('--print-ratio', ratio.toFixed(4));

      var now = page.querySelector('.rep-orient-now');
      if (now) {
        now.textContent = (mode === 'auto' ? 'auto \u2192 ' : '') + (rotate ? 'landscape' : 'portrait');
      }
    }
  }

  function renderSummaryStrip(aps, ctx) {
    var floorIds = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      floorIds[fp ? fp.id : '_none'] = true;
    });
    var floorCount = Object.keys(floorIds).length;
    var directional = aps.filter(function (ap) { return !apIsOmniOnly(ap); }).length;
    var omni = aps.length - directional;
    var bits = [aps.length + ' AP' + (aps.length === 1 ? '' : 's') + ' planned across ' + floorCount + ' floor plan' + (floorCount === 1 ? '' : 's')];
    if (directional) bits.push(directional + ' directional');
    if (omni) bits.push(omni + ' omni');
    return '<div class="rep-seg-note">' + WD.esc(bits.join(' · ')) + '.</div>';
  }

  function renderAntennaLegend(aps, ctx) {
    var ids = collectUsedAntennas(aps, ctx);
    var countMap = {};
    if (aps && ctx) {
      aps.forEach(function (ap) {
        proj.radios.filter(function (x) { return x.accessPointId === ap.id; })
          .forEach(function (x) {
            if (x.antennaTypeId) countMap[x.antennaTypeId] = (countMap[x.antennaTypeId] || 0) + 1;
          });
      });
    }
    var tbl = renderAntennaTable(ids, countMap);
    if (!tbl) return '';
    return '<section class="rep-legend"><h2 class="rep-floor-title">Antennas in use</h2>' + tbl + '</section>';
  }

  function renderSummaryReport(aps, opts, ctx) {


    var head = opts.cover ? ctx.cover(proj.accessPoints.length, ctx.dateStr, 'Access points')
                          : ctx.inlineHeader(proj.accessPoints.length, ctx.dateStr, 'Access points');


    var buildingCount = Object.keys(proj.buildings || {}).length;
    var radiosCount = (proj.radios || []).length;
    var antennaTypesUsed = new Set();
    proj.radios.forEach(function (r) { if (r.antennaTypeId) antennaTypesUsed.add(r.antennaTypeId); });
    var measuredCount = (proj.measuredRadios || []).length;
    var surveyCount = (proj.surveys || []).length;

    var stats = [];
    stats.push({ label: 'Access points', value: proj.accessPoints.length, cls: 'total' });
    stats.push({ label: 'Radios', value: radiosCount, cls: 'iphone' });
    stats.push({ label: 'Floor plans', value: proj.floorPlans.length, cls: 'android' });
    if (buildingCount) stats.push({ label: 'Buildings', value: buildingCount, cls: 'carrier' });
    stats.push({ label: 'Antenna types', value: antennaTypesUsed.size, cls: 'total' });
    if (surveyCount) stats.push({ label: 'Surveys', value: surveyCount, cls: 'iphone' });
    if (measuredCount) stats.push({ label: 'Measured radios', value: measuredCount, cls: 'android' });

    var statHtml = '<div class="rep-hotspot-stats">'
      + stats.map(function (s) {
          return '<div class="rep-hotspot-stat rep-hotspot-stat--' + s.cls + '"><b>'
            + WD.esc(String(s.value)) + '</b><span>' + WD.esc(s.label) + '</span></div>';
        }).join('')
      + '</div>';

    var strip = '<section class="rep-floor-section rep-summary-hero">'
      + '<h2 class="rep-floor-title">Project at a glance</h2>'
      + statHtml
      + '</section>';


    var perFloorSection = '';
    if (opts.perFloor !== false && proj.floorPlans.length) {
      var apByFloor = {};
      proj.accessPoints.forEach(function (a) {
        var fp = ctx.floorPlanForAp(a);
        var key = fp ? fp.id : '_unplaced';
        (apByFloor[key] = apByFloor[key] || []).push(a);
      });
      var rows = '';
      proj.floorPlans.forEach(function (f) {
        var apList = apByFloor[f.id] || [];
        var bf = proj.buildingFloors[f.id];
        var buildingName = bf && proj.buildings[bf.buildingId]
          ? proj.buildings[bf.buildingId].name || '' : '';
        var wm = f.width || 0, hm = f.height || 0;
        var sizeStr = (wm && hm)
          ? Math.round(wm) + ' × ' + Math.round(hm) + ' px'
          : '—';
        rows += '<tr>'
          + '<td class="rep-name">' + WD.esc(f.name || 'Untitled') + '</td>'
          + '<td>' + WD.esc(buildingName) + '</td>'
          + '<td class="rep-az">' + apList.length + '</td>'
          + '<td class="rep-az">' + WD.esc(sizeStr) + '</td>'
          + '</tr>';
      });
      var unplaced = (apByFloor['_unplaced'] || []).length;
      if (unplaced) {
        rows += '<tr><td class="rep-name"><em>Unplaced</em></td><td></td>'
          + '<td class="rep-az">' + unplaced + '</td>'
          + '<td class="rep-az">—</td></tr>';
      }
      perFloorSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Per-floor breakdown</h2>'
        + '<table class="rep-ap-table"><thead><tr>'
        + '<th>Floor</th><th>Building</th><th class="rep-num">APs</th><th class="rep-num">Canvas</th>'
        + '</tr></thead><tbody>' + rows + '</tbody></table>'
        + '</section>';
    }


    var bandSection = '';
    if (opts.bandBreakdown !== false && radiosCount) {
      var bandCounts = {};
      var total = 0;
      proj.radios.forEach(function (r) {
        var ant = r.antennaTypeId && proj.antennas[r.antennaTypeId];
        var band = (ant && ant.frequencyBand) || 'Unspecified';
        bandCounts[band] = (bandCounts[band] || 0) + 1;
        total += 1;
      });
      var order = ['TWO', 'FIVE', 'SIX', 'Unspecified'];
      var pretty = { TWO: '2.4 GHz', FIVE: '5 GHz', SIX: '6 GHz' };
      var sortedBands = Object.keys(bandCounts).sort(function (a, b) {
        var ia = order.indexOf(a), ib = order.indexOf(b);
        if (ia === -1) ia = 99; if (ib === -1) ib = 99;
        return ia - ib || a.localeCompare(b);
      });
      var barRows = sortedBands.map(function (b) {
        var count = bandCounts[b];
        var pct = total ? Math.round(count / total * 100) : 0;
        var label = pretty[b] || b.replace(/_/g, ' ');
        return '<tr>'
          + '<td class="rep-name">' + WD.esc(label) + '</td>'
          + '<td><div class="rep-summary-bar-outer"><div class="rep-summary-bar-inner" style="width:' + pct + '%"></div></div></td>'
          + '<td class="rep-az">' + count + '</td>'
          + '<td class="rep-az">' + pct + '%</td>'
          + '</tr>';
      }).join('');
      bandSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Radio band breakdown</h2>'
        + '<p class="rep-summary-hint">One row per radio. Each AP typically has one 2.4 and one 5 GHz radio; 6 GHz appears on Wi-Fi 6E hardware only.</p>'
        + '<table class="rep-ap-table"><thead><tr>'
        + '<th>Band</th><th></th><th class="rep-num">Radios</th><th class="rep-num">Share</th>'
        + '</tr></thead><tbody>' + barRows + '</tbody></table>'
        + '</section>';
    }


    var modelsSection = '';
    if (opts.topModels !== false && proj.accessPoints.length) {
      var modelCounts = {};
      proj.accessPoints.forEach(function (a) {
        var m = (a.model || a.vendor || '').trim() || 'Unknown';
        modelCounts[m] = (modelCounts[m] || 0) + 1;
      });
      var entries = Object.keys(modelCounts).map(function (k) { return { model: k, count: modelCounts[k] }; })
        .sort(function (a, b) { return b.count - a.count || a.model.localeCompare(b.model); })
        .slice(0, 10);
      var modelRows = entries.map(function (e) {
        return '<tr><td class="rep-name">' + WD.esc(e.model) + '</td>'
          + '<td class="rep-az">' + e.count + '</td></tr>';
      }).join('');
      modelsSection = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Top AP models</h2>'
        + '<table class="rep-ap-table"><thead><tr><th>Model</th><th class="rep-num">Quantity</th></tr></thead>'
        + '<tbody>' + modelRows + '</tbody></table>'
        + '</section>';
    }


    var antennasSection = opts.antennas !== false ? summaryAntennas() : '';


    return head + strip + perFloorSection + bandSection + modelsSection + antennasSection + apNotesPages(aps, opts, ctx)
      + REPORT_FOOTER;
  }

  function summaryAntennas() {
    /* It listed the models and not how many of each, while the same table in
       the AP Installation report and the Bill of Materials both carry a
       quantity. Someone reading the summary to size an order got the shorter
       answer for no reason. */
    var ids = collectUsedAntennas();
    var counts = {};
    proj.radios.forEach(function (r) {
      if (r.antennaTypeId) counts[r.antennaTypeId] = (counts[r.antennaTypeId] || 0) + 1;
    });
    var tbl = renderAntennaTable(ids, counts);
    if (!tbl) return '';
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Antennas in use</h2>' + tbl + '</section>';
  }

  function renderBomReport(aps, opts, ctx) {

    var head = opts.cover ? ctx.cover(proj.accessPoints.length, ctx.dateStr, 'Access points')
                          : ctx.inlineHeader(proj.accessPoints.length, ctx.dateStr, 'Access points');

    var externalOnly = !!opts.externalOnly;


    var apGroups = {};
    proj.accessPoints.forEach(function (a) {
      var vendor = (a.vendor || '').trim() || '—';
      var model = (a.model || '').trim() || 'Unknown';
      var key = vendor + '\u0000' + model;
      if (!apGroups[key]) apGroups[key] = { vendor: vendor, model: model, count: 0 };
      apGroups[key].count += 1;
    });
    var apRows = Object.values(apGroups)
      .sort(function (a, b) {
        return a.vendor.localeCompare(b.vendor) || b.count - a.count || a.model.localeCompare(b.model);
      });
    var apRowsHtml = apRows.map(function (g) {
      return '<tr>'
        + '<td>' + WD.esc(g.vendor) + '</td>'
        + '<td class="rep-name">' + WD.esc(g.model) + '</td>'
        + '<td class="rep-az">' + g.count + '</td>'
        + '</tr>';
    }).join('');
    var apTotal = proj.accessPoints.length;
    var apTotalRow = '<tr class="rep-bom-total"><td></td><td class="rep-name">Total access points</td><td class="rep-az">' + apTotal + '</td></tr>';
    var apSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Access point quantities</h2>'
      + '<table class="rep-ap-table">'
      + '<colgroup><col style="width:28%"><col style="width:57%"><col style="width:15%"></colgroup>'
      + '<thead><tr>'
      + '<th>Vendor</th><th>Model</th><th class="rep-num">Qty</th>'
      + '</tr></thead><tbody>' + apRowsHtml + apTotalRow + '</tbody></table>'
      + '</section>';


    /* Per floor, because he orders for the whole site and installs a floor at
       a time. The project total above answers "what do I buy"; this answers
       "what turns up on FLR3 on Tuesday", which is the count somebody was
       doing by hand off the placement maps.

       Model strings are written exactly as the project records them - a
       prettified model name is one nobody can paste into a purchase order. */
    var byFloorBom = groupApsByFloor(proj.accessPoints, ctx);
    var floorOrderBom = sortedFloorOrder(byFloorBom);
    var floorRowsHtml = '';
    floorOrderBom.forEach(function (fp) {
      var list = byFloorBom[fp.id];
      if (!list || !list.length) return;
      var groups = {};
      list.forEach(function (a) {
        var vendor = (a.vendor || '').trim() || '\u2014';
        var model = (a.model || '').trim() || 'Unknown';
        var key = vendor + '\u0000' + model;
        if (!groups[key]) groups[key] = { vendor: vendor, model: model, count: 0 };
        groups[key].count += 1;
      });
      var rows = Object.values(groups).sort(function (a, b) {
        return a.vendor.localeCompare(b.vendor) || b.count - a.count
            || a.model.localeCompare(b.model);
      });
      rows.forEach(function (g, i) {
        floorRowsHtml += '<tr>'
          + '<td class="rep-name">' + (i === 0 ? WD.esc(fp.name || 'Floor plan') : '') + '</td>'
          + '<td>' + WD.esc(g.vendor) + '</td>'
          + '<td class="rep-name">' + WD.esc(g.model) + '</td>'
          + '<td class="rep-az">' + g.count + '</td>'
          + '</tr>';
      });
      floorRowsHtml += '<tr class="rep-bom-total"><td></td><td></td>'
        + '<td class="rep-name">' + WD.esc(fp.name || 'Floor plan') + ' total</td>'
        + '<td class="rep-az">' + list.length + '</td></tr>';
    });
    var perFloorSection = floorOrderBom.length > 1
      ? '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Access points per floor</h2>'
        + '<table class="rep-ap-table">'
        + '<colgroup><col style="width:24%"><col style="width:20%">'
        +   '<col style="width:41%"><col style="width:15%"></colgroup>'
        + '<thead><tr><th>Floor</th><th>Vendor</th><th>Model</th>'
        +   '<th class="rep-num">Qty</th></tr></thead>'
        + '<tbody>' + floorRowsHtml + '</tbody></table>'
        + '</section>'
      : '';

    /* Mounts are orderable parts, and Ekahau records one per radio. An AP
       whose radio carries no mounting is counted under "Not recorded" rather
       than dropped - a BOM that is quietly short is worse than one that says
       where it is short. */
    var mountGroups = {};
    var mountMissing = 0;
    proj.accessPoints.forEach(function (a) {
      var r = ctx.primaryRadio(a.id);
      var m = r && r.antennaMounting ? String(r.antennaMounting) : '';
      if (!m) { mountMissing += 1; return; }
      var label = m.replace(/_/g, ' ').toLowerCase();
      label = label.charAt(0).toUpperCase() + label.slice(1);
      mountGroups[label] = (mountGroups[label] || 0) + 1;
    });
    var mountRows = Object.keys(mountGroups).sort(function (a, b) {
      return mountGroups[b] - mountGroups[a] || a.localeCompare(b);
    });
    var mountSection = (mountRows.length || mountMissing)
      ? '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Mount types</h2>'
        + '<p class="rep-summary-hint">One per access point, from the mounting '
        +   'recorded against its radio.</p>'
        + '<table class="rep-ap-table">'
        + '<colgroup><col style="width:70%"><col style="width:30%"></colgroup>'
        + '<thead><tr><th>Mount</th><th class="rep-num">Qty</th></tr></thead><tbody>'
        + mountRows.map(function (k) {
            return '<tr><td class="rep-name">' + WD.esc(k) + '</td>'
              + '<td class="rep-az">' + mountGroups[k] + '</td></tr>';
          }).join('')
        + (mountMissing
            ? '<tr><td class="rep-name">Not recorded</td><td class="rep-az">'
              + mountMissing + '</td></tr>'
            : '')
        + '<tr class="rep-bom-total"><td class="rep-name">Total access points</td>'
        +   '<td class="rep-az">' + proj.accessPoints.length + '</td></tr>'
        + '</tbody></table>'
        + '</section>'
      : '';

    var antGroups = {};
    var totalAntennas = 0;
    proj.radios.forEach(function (r) {
      if (!r.antennaTypeId) return;
      var a = proj.antennas[r.antennaTypeId];
      if (!a) return;
      if (externalOnly && a.apCoupling !== 'EXTERNAL_ANTENNA') return;
      var key = a.id;
      if (!antGroups[key]) antGroups[key] = { antenna: a, count: 0 };
      antGroups[key].count += 1;
      totalAntennas += 1;
    });
    var antRows = Object.values(antGroups)
      .sort(function (a, b) {
        return b.count - a.count || (a.antenna.name || '').localeCompare(b.antenna.name || '');
      });
    var antRowsHtml = antRows.map(function (g) {
      var a = g.antenna;
      var coupling = (a.apCoupling || '').replace(/_/g, ' ').toLowerCase() || '—';
      var band = a.frequencyBand ? ({TWO:'2.4', FIVE:'5', SIX:'6'})[a.frequencyBand] + ' GHz' : '—';
      var gain = (a.maxGain != null) ? a.maxGain + ' dBi' : '—';
      return '<tr>'
        + '<td class="rep-name">' + WD.esc(a.name || a.id) + '</td>'
        + '<td>' + WD.esc(coupling) + '</td>'
        + '<td>' + WD.esc(band) + '</td>'
        + '<td>' + WD.esc(gain) + '</td>'
        + '<td class="rep-az">' + g.count + '</td>'
        + '</tr>';
    }).join('');
    var antTotalLabel = externalOnly ? 'Total external antennas' : 'Total antennas (all)';
    var antTotalRow = '<tr class="rep-bom-total"><td class="rep-name">' + antTotalLabel
      + '</td><td></td><td></td><td></td><td class="rep-az">' + totalAntennas + '</td></tr>';
    var antIntro = externalOnly
      ? '<p class="rep-summary-hint">Showing external (procurement-relevant) antennas only. Toggle in the sidebar to see the full antenna list.</p>'
      : '<p class="rep-summary-hint">All antennas including integrated (built-in) ones. Toggle "External only" in the sidebar for a procurement-ready view.</p>';
    var antSection = antRows.length
      ? '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Antenna quantities</h2>'
        + antIntro
        + '<table class="rep-ap-table">'
        /* An antenna part number is the longest thing on this sheet and a
           band is five characters; five equal columns is what put the name
           on top of the coupling value. */
        + '<colgroup><col style="width:46%"><col style="width:17%"><col style="width:12%">'
        +   '<col style="width:13%"><col style="width:12%"></colgroup>'
        + '<thead><tr>'
        + '<th>Antenna</th><th>Coupling</th><th>Band</th><th>Gain</th><th class="rep-num">Qty</th>'
        + '</tr></thead><tbody>' + antRowsHtml + antTotalRow + '</tbody></table>'
        + '</section>'
      : '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Antenna quantities</h2>'
        + '<p class="rep-empty-small">No antennas match the current filter. Try turning off "External only" in the sidebar.</p>'
        + '</section>';


    var notes = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Notes for procurement</h2>'
      + '<ul class="rep-summary-notes">'
      + '<li>Antenna quantities count each radio-to-antenna assignment. An AP with a dual-band external antenna kit is counted per radio (2×), not per physical part — cross-check against your antenna kit\'s inclusions.</li>'
      + '<li>The mount table above is the mounting recorded in Ekahau, which is a mount <i>type</i> and not a part number. The bracket, cable runs, cable ties, PoE injectors and switch ports are <b>not</b> in the file at all — add those per your rack/ceiling standard.</li>'
      + '<li>External-antenna APs typically ship without their antennas; verify the AP part number matches your procurement SKU (e.g. Cisco C9166I-B vs. C9166I-E for internal vs. external).</li>'
      + '<li>This BOM reflects the design shown in the .esx as of ' + WD.esc(ctx.dateStr) + '. Cross-reference with the final walked design before ordering.</li>'
      + '</ul>'
      + '</section>';

    return head + apSection + perFloorSection + antSection + mountSection + notes
      + apNotesPages(aps, opts, ctx)
      + REPORT_FOOTER;
  }

  function classifyHotspot(ssid) {
    if (!ssid) return null;
    var s = String(ssid).trim();
    var low = s.toLowerCase();
    if (/['’]s\s+i(phone|pad|pod)\b/.test(low)) return 'iPhone';
    if (/\bi(phone|pad|pod)\b/.test(low)) return 'iPhone';
    if (/^androidap[_\-]/.test(low)) return 'Android';
    if (/^androidshare[_\-]/.test(low)) return 'Android';
    if (/direct-.{1,3}-androidap/.test(low)) return 'Android';
    if (/^galaxy\s/.test(low)) return 'Android';
    if (/^samsung\s+galaxy/.test(low)) return 'Android';
    if (/^hotspot[a-z0-9]{3,8}$/.test(low)) return 'Carrier hotspot';
    if (/^wi-?fi\s+hotspot\s+\d+/.test(low)) return 'Carrier hotspot';
    if (/mifi|jetpack/.test(low)) return 'Carrier hotspot';
    if (/[_\-]hotspot\b/.test(low)) return 'Carrier hotspot';
    if (/^att[a-z0-9]{6,10}$/.test(s)) return 'ATT (phone or gateway)';
    return null;
  }

  function hotspotBand(chans) {
    if (!chans || !chans.length) return '—';
    var bands = {};
    chans.forEach(function (c) {
      if (c < 3000) bands['2.4'] = 1;
      else if (c >= 5955) bands['6'] = 1;
      else bands['5'] = 1;
    });
    return Object.keys(bands).sort().join(' / ') + ' GHz';
  }

  function hotspotChannel(chans) {
    if (!chans || !chans.length) return '';
    return chans.map(function (c) {
      if (c >= 2412 && c <= 2484) return 'ch' + (c === 2484 ? 14 : (c - 2407) / 5);
      if (c >= 5000 && c <= 5900) return 'ch' + ((c - 5000) / 5);
      if (c >= 5955) return 'ch' + ((c - 5950) / 5) + '(6E)';
      return String(c);
    }).join(', ');
  }




  function channelWidthMHz(chans) {
    return (chans && chans.length) ? chans.length * 20 : null;
  }






  function interferenceSeverity(chans) {
    var widthMHz = channelWidthMHz(chans);
    if (!widthMHz) return 'Low';
    var has24 = chans.some(function (c) { return c < 3000; });
    if (widthMHz >= 80) return 'High';
    if (widthMHz === 40) return has24 ? 'High' : 'Medium';
    return 'Low';
  }

  var SEV_RANK = { High: 2, Medium: 1, Low: 0 };
  var SEV_CLASS = { High: 'rep-sev-chip--high', Medium: 'rep-sev-chip--medium', Low: 'rep-sev-chip--low' };
  function sevChip(sev) {
    return '<span class="rep-sev-chip ' + SEV_CLASS[sev] + '">' + sev + '</span>';
  }

  function buildMeasurementToFloors() {
    var out = {};
    proj.surveys.forEach(function (sv) {
      var fpid = sv.floorPlanId;
      if (!fpid) return;
      (sv.wifiTracks || []).forEach(function (wt) {
        (wt.accessPointMeasurementIds || []).forEach(function (mid) {
          if (!out[mid]) out[mid] = {};
          out[mid][fpid] = 1;
        });
      });
    });
    return out;
  }

  function surveyPolylinesForFloor(fpId, extraClass) {
    var out = '';
    proj.surveys.forEach(function (sv) {
      if (sv.floorPlanId !== fpId) return;
      (sv.routePoints || []).forEach(function (seg) {
        var pts = (seg || []).filter(function (rp) { return rp && rp.location; })
          .map(function (rp) { return rp.location.x.toFixed(1) + ',' + rp.location.y.toFixed(1); });
        if (pts.length >= 2) {
          out += '<polyline class="rep-hotspot-walk' + (extraClass || '') + '" points="' + pts.join(' ') + '"/>';
        }
      });
    });
    return out;
  }

  var HOTSPOT_CHIP_CLASS = {
    'iPhone':                 'rep-hotspot-chip--iphone',
    'Android':                'rep-hotspot-chip--android',
    'Carrier hotspot':        'rep-hotspot-chip--carrier',
    'ATT (phone or gateway)': 'rep-hotspot-chip--att',
    'Wide-channel Wi-Fi':     'rep-hotspot-chip--wide',
  };

  function renderInterferenceReport(aps, opts, ctx) {
    if (!proj.measurements.length) {
      return (opts.cover ? ctx.cover(0, ctx.dateStr, 'Interferers detected') : ctx.inlineHeader(0, ctx.dateStr, 'Interferers detected'))
        + '<section class="rep-floor-section">'
        +   '<h2 class="rep-floor-title">No survey data</h2>'
        +   '<div class="rep-empty-small">This .esx contains only design/planning data — no measured APs to report on. '
        +     'Open a project file that includes an Ekahau Survey walk.</div>'
        + '</section>'
        + REPORT_FOOTER;
    }

    var accept = {
      'iPhone': !!opts.catIphone,
      'Android': !!opts.catAndroid,
      'Carrier hotspot': !!opts.catCarrier,
      'ATT (phone or gateway)': !!opts.catAtt,
    };
    var acceptWide = !!opts.catWide;

    var floorMap = buildMeasurementToFloors();
    var hotspots = [];
    proj.measurements.forEach(function (m) {
      var chans = m.channelByCenterFrequencyDefinedNarrowChannels;
      var widthMHz = channelWidthMHz(chans);
      var isWide = widthMHz != null && widthMHz >= 40;
      var cat = classifyHotspot(m.ssid);
      if (cat) {
        if (!accept[cat]) return;
      } else if (isWide && acceptWide) {
        cat = 'Wide-channel Wi-Fi';
      } else {
        return;
      }
      var floors = Object.keys(floorMap[m.id] || {});
      var floorNames = floors.map(function (fid) {
        var f = proj.floorPlans.find(function (x) { return x.id === fid; });
        return f ? f.name : '';
      }).filter(Boolean);
      hotspots.push({
        ssid: m.ssid || '(hidden)',
        mac: m.mac || '—',
        category: cat,
        security: m.security || '—',
        band: hotspotBand(chans),
        channel: hotspotChannel(chans),
        widthMHz: widthMHz,
        severity: interferenceSeverity(chans),
        floorIds: floors,
        floorNames: floorNames,
      });
    });

    var catRank = { 'iPhone': 0, 'Android': 1, 'Carrier hotspot': 2, 'ATT (phone or gateway)': 3, 'Wide-channel Wi-Fi': 4 };
    hotspots.sort(function (a, b) {
      return (SEV_RANK[b.severity] - SEV_RANK[a.severity])
        || (catRank[a.category] - catRank[b.category])
        || (a.ssid || '').toLowerCase().localeCompare((b.ssid || '').toLowerCase());
    });

    function chip(cat) {
      return '<span class="rep-hotspot-chip ' + HOTSPOT_CHIP_CLASS[cat] + '">' + WD.esc(cat) + '</span>';
    }

    var head = opts.cover
      ? ctx.cover(hotspots.length, ctx.dateStr, 'Interferers detected')
      : ctx.inlineHeader(hotspots.length, ctx.dateStr, 'Interferers detected');

    var counts = { 'iPhone': 0, 'Android': 0, 'Carrier hotspot': 0, 'ATT (phone or gateway)': 0, 'Wide-channel Wi-Fi': 0 };
    var highCount = 0;
    hotspots.forEach(function (h) { counts[h.category]++; if (h.severity === 'High') highCount++; });
    var summary = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Summary</h2>'
      + '<div class="rep-hotspot-stats">'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--total">'
      +     '<b>' + hotspots.length + '</b><span>Total interferers</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--severity">'
      +     '<b>' + highCount + '</b><span>High severity</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--iphone">'
      +     '<b>' + counts['iPhone'] + '</b><span>iPhone / iPad</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--android">'
      +     '<b>' + counts['Android'] + '</b><span>Android</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--carrier">'
      +     '<b>' + (counts['Carrier hotspot'] + counts['ATT (phone or gateway)']) + '</b>'
      +     '<span>Carrier / MiFi</span></div>'
      +   '<div class="rep-hotspot-stat rep-hotspot-stat--wide">'
      +     '<b>' + counts['Wide-channel Wi-Fi'] + '</b><span>Wide-channel Wi-Fi</span></div>'
      + '</div></section>';

    var overlays = '';
    if (opts.overview) {
      var floorSevRank = {};
      hotspots.forEach(function (h) {
        h.floorIds.forEach(function (fid) {
          var r = SEV_RANK[h.severity];
          if (r > (floorSevRank[fid] || 0)) floorSevRank[fid] = r;
        });
      });
      proj.floorPlans.forEach(function (fp) {
        var url = proj.imageUrls[fp.bitmapImageId || fp.imageId];
        if (!url) return;
        var floorHotspots = hotspots.filter(function (h) {
          return h.floorIds.indexOf(fp.id) !== -1;
        });
        var flagged = floorHotspots.filter(function (h) { return h.severity !== 'Low'; })
          .sort(function (a, b) { return SEV_RANK[b.severity] - SEV_RANK[a.severity]; });
        var flaggedChips = flagged.slice(0, 6).map(function (h) {
          return sevChip(h.severity) + ' <span class="rep-hotspot-floor-flag-ssid">' + WD.esc(h.ssid) + '</span>';
        }).join(' &nbsp; ');
        if (flagged.length > 6) flaggedChips += ' &nbsp; <span class="rep-hotspot-floor-flag-ssid">+' + (flagged.length - 6) + ' more</span>';
        var rank = floorSevRank[fp.id] || 0;
        var walkClass = rank === 2 ? ' rep-hotspot-walk--high' : rank === 1 ? ' rep-hotspot-walk--medium' : '';
        var polylines = surveyPolylinesForFloor(fp.id, walkClass);
        overlays += '<section class="rep-floor-section">'
          + '<h2 class="rep-floor-title">Floor ' + WD.esc(fp.name || 'plan')
          +   ' <span class="rep-hotspot-floor-count">- '
          +   floorHotspots.length + ' interferer' + (floorHotspots.length === 1 ? '' : 's') + ' detected</span>'
          + '</h2>'
          + (flaggedChips ? '<div class="rep-hotspot-floor-flags">' + flaggedChips + '</div>' : '')
          + '<div class="rep-overview"><div class="rep-overview-plan rep-hotspot-fp" '
          +   'data-crop-src="' + WD.escAttr(url) + '" '
          +   'style="--w:' + fp.width + ';--h:' + fp.height + '">'
          +   '<img src="' + url + '" alt="Floor plan">'
          +   '<svg viewBox="0 0 ' + fp.width + ' ' + fp.height + '" preserveAspectRatio="none">'
          +     polylines
          +   '</svg>'
          + '</div>'
          + '<div class="rep-overview-key">Walk path = where scans were captured on this floor '
          +   '(blue = normal, amber = a medium-severity interferer was seen here, red = a high-severity one). '
          +   'This traces the walk, not the interferer&#39;s exact position - see &quot;How we classified these&quot; below.</div>'
          + '</div></section>';
      });
    }

    var showChannel = !!opts.channel;
    var rows = hotspots.map(function (h) {
      return '<tr><td>' + chip(h.category) + '</td>'
        + '<td class="rep-name">' + WD.esc(h.ssid) + '</td>'
        + '<td class="rep-az">' + WD.esc(h.mac) + '</td>'
        + '<td>' + WD.esc(h.band) + '</td>'
        + (showChannel ? '<td>' + WD.esc(h.channel) + '</td>' : '')
        + '<td>' + (h.widthMHz ? h.widthMHz + ' MHz' : '—') + '</td>'
        + '<td>' + sevChip(h.severity) + '</td>'
        + '<td>' + WD.esc(h.security) + '</td>'
        + '<td>' + (h.floorNames.length ? h.floorNames.map(function (n) { return 'Fl ' + WD.esc(n); }).join(', ') : '—') + '</td>'
        + '</tr>';
    }).join('');

    var colCount = showChannel ? 9 : 8;
    var tableSection = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">All detected interferers</h2>'
      + '<table class="rep-ap-table">'
      +   '<thead><tr>'
      +     '<th>Category</th><th>SSID</th><th>BSSID</th><th>Band</th>'
      +     (showChannel ? '<th>Channel(s)</th>' : '')
      +     '<th>Width</th><th>Severity</th><th>Security</th><th>Seen on</th>'
      +   '</tr></thead>'
      +   '<tbody>' + (rows || '<tr><td colspan="' + colCount + '" class="rep-empty-small">No interferers matched the selected categories.</td></tr>') + '</tbody>'
      + '</table></section>';

    var method = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">How we classified these</h2>'
      + '<div class="rep-hotspot-method">'
      +   'Each row is a unique BSSID picked up during the passive survey walk. '
      +   'An SSID was flagged as a phone/carrier hotspot when it matched one of the default naming patterns, '
      +   'or as <b>Wide-channel Wi-Fi</b> when it did not match a naming pattern but was still transmitting on '
      +   'a 40MHz+ channel - wide enough to be a plausible interference source on its own:'
      +   '<ul>'
      +     '<li><b>iPhone / iPad</b> — SSID contains iPhone, iPad, or "’s iPhone" (default iOS Personal Hotspot naming).</li>'
      +     '<li><b>Android</b> — AndroidAP_XXXX, AndroidShare_XXXX, DIRECT-xx-AndroidAP, or a Samsung Galaxy device name.</li>'
      +     '<li><b>Carrier hotspot / MiFi</b> — HotspotXXXX, WiFi Hotspot NNNN, or SSIDs containing MiFi / Jetpack (Verizon and T-Mobile default names for standalone hotspot devices).</li>'
      +     '<li><b>ATT (phone or gateway)</b> — SSIDs matching ATT[6-10 chars]. This pattern is used by both AT&amp;T phone hotspots and AT&amp;T home gateways, so treat as suggestive rather than definitive.</li>'
      +     '<li><b>Wide-channel Wi-Fi</b> - any other BSSID using a 40MHz or wider channel. Catches rogue APs and hotspots that do not match a phone-naming pattern.</li>'
      +   '</ul>'
      +   '<p><b>Severity</b> is channel width plus band, not a comparison against your own APs&#39; assigned channels (this tool does not have a reliable read on those from the .esx design data): '
      +   '<b>High</b> = 80MHz+ anywhere, or 40MHz in the crowded 2.4GHz band. <b>Medium</b> = 40MHz in 5/6GHz. <b>Low</b> = 20MHz or unknown.</p>'
      +   '<p><b>Excluded intentionally:</b> car head units (Uconnect, MBUX, CarPlay, CarLink), dashcams (ROVE, VANTRUE, 70mai), printers/scanners, T-Mobile CellSpot femtocells, and other non-phone personal Wi-Fi devices.</p>'
      +   '<p><b>The floor plan overlay is a detection map, not a signal-strength heat map.</b> It shows the surveyor&#39;s walk path colored by the worst severity detected while walking that floor - it does not pinpoint the interferer&#39;s physical location, because the .esx does not expose per-point signal readings tied to coordinates.</p>'
      + '</div>'
      + '</section>';

    return head + summary + overlays + tableSection + method + apNotesPages(aps, opts, ctx)
      + REPORT_FOOTER;
  }





  /* ══ Change / Audit report ════════════════════════════════════════════════

     Two .esx files, and what is different between them. The comparison itself
     is ``compareProjects`` further up, which is deliberately free of the DOM;
     everything here is presentation. */

  var CHANGE_WORDS = {
    renamed: 'Renamed', model: 'Model', vendor: 'Vendor', floor: 'Floor',
    moved: 'Moved', azimuth: 'Azimuth', tilt: 'Tilt', height: 'Height',
    mount: 'Mount', antenna: 'Antenna', unplaced: 'Taken off the plan',
    placed: 'Placed on the plan',
  };

  function describeChange(c, opts, ctx) {
    // No digit count: fmtLength's own default is one decimal in feet and two
    // in metres, which is what every other table in this suite prints, and a
    // report that rounds differently from its siblings reads as a different
    // measurement rather than the same one.
    if (c.kind === 'moved') return fmtLength(c.metres, opts);
    if (c.kind === 'height') {
      return fmtLength(c.from, opts) + ' → ' + fmtLength(c.to, opts);
    }
    if (c.kind === 'azimuth') {
      return fmt(c.from, 0) + '° → ' + fmt(c.to, 0) + '° ('
        + fmt(c.delta, 0) + '°)';
    }
    if (c.kind === 'tilt') {
      return fmt(c.from, 0) + '° → ' + fmt(c.to, 0) + '°';
    }
    if (c.kind === 'unplaced' || c.kind === 'placed') return '';
    return String(c.from) + ' → ' + String(c.to);
  }

  /* One line naming every difference on one AP, so the table holds a row per
     AP rather than a row per difference. An AP that was renamed *and* moved is
     one decision somebody made, and splitting it across two rows makes the
     reader reassemble it. */
  function changeSummaryCell(rec, opts, ctx) {
    return rec.changes.map(function (c) {
      var word = CHANGE_WORDS[c.kind] || c.kind;
      var detail = describeChange(c, opts, ctx);
      return '<span class="rep-chg rep-chg--' + WD.escAttr(c.kind) + '">'
        + WD.esc(word) + (detail ? ' ' + WD.esc(detail) : '') + '</span>';
    }).join(' ');
  }

  function deltaCell(before, after) {
    var d = after - before;
    var sign = d > 0 ? '+' : d < 0 ? '−' : '';
    var cls = d > 0 ? 'rep-delta-up' : d < 0 ? 'rep-delta-down' : 'rep-delta-same';
    return '<span class="' + cls + '">' + sign + (d === 0 ? '0' : Math.abs(d)) + '</span>';
  }

  /* The overlay: the current floor plan, with where things used to be marked
     on it. Drawn on the *after* plan on purpose - that is the drawing somebody
     is holding, and rendering the old one would put the changes on a plan that
     no longer matches the building. */
  function renderAuditOverlay(fp, result, opts, ctx) {
    var url = floorPlanImageUrl(fp);
    if (!url) return '';
    var W = fp.width || 1, H = fp.height || 1;
    var minDim = Math.min(W, H);
    var dotR = minDim * 0.012;
    var sw = minDim * 0.003;
    var shift = null;
    result.floorNotes.forEach(function (n) { if (n.floorId === fp.id) shift = n; });

    function onThisFloor(loc) { return loc && loc.floorPlanId === fp.id; }
    var g = '';
    var drew = 0;

    result.changed.forEach(function (rec) {
      if (!onThisFloor(rec.after.location)) return;
      var ca = apCoord(rec.after);
      if (!ca) return;
      var moved = rec.changes.find(function (c) { return c.kind === 'moved'; });
      if (moved) {
        var cb = apCoord(rec.before);
        if (cb) {
          var fx = cb.x + (shift ? shift.dx : 0);
          var fy = cb.y + (shift ? shift.dy : 0);
          g += '<circle class="rep-aud-was" cx="' + fx + '" cy="' + fy + '" r="' + dotR
            + '" stroke-width="' + sw + '"/>'
            + '<line class="rep-aud-move" x1="' + fx + '" y1="' + fy + '" x2="' + ca.x
            + '" y2="' + ca.y + '" stroke-width="' + sw + '"/>';
        }
      }
      g += '<circle class="rep-aud-changed" cx="' + ca.x + '" cy="' + ca.y + '" r="' + dotR
        + '" stroke-width="' + sw + '"/>';
      drew++;
    });
    result.added.forEach(function (ap) {
      if (!onThisFloor(ap.location)) return;
      var c = apCoord(ap); if (!c) return;
      g += '<circle class="rep-aud-added" cx="' + c.x + '" cy="' + c.y + '" r="' + dotR
        + '" stroke-width="' + sw + '"/>';
      drew++;
    });
    /* A removed AP is drawn where it used to be, corrected for a re-crop if
       this floor had one - otherwise it lands wherever the old coordinate
       space happened to put it, which on a trimmed plan is off the sheet. */
    result.removed.forEach(function (ap) {
      var loc = ap.location || {};
      var pairedBefore = result.floorPairs.find(function (p) { return p.after.id === fp.id; });
      if (!pairedBefore || loc.floorPlanId !== pairedBefore.before.id) return;
      var c = apCoord(ap); if (!c) return;
      var x = c.x + (shift ? shift.dx : 0), y = c.y + (shift ? shift.dy : 0);
      g += '<g class="rep-aud-removed" transform="translate(' + x + ',' + y + ')">'
        + '<line x1="' + (-dotR) + '" y1="' + (-dotR) + '" x2="' + dotR + '" y2="' + dotR
        + '" stroke-width="' + sw + '"/>'
        + '<line x1="' + (-dotR) + '" y1="' + dotR + '" x2="' + dotR + '" y2="' + (-dotR)
        + '" stroke-width="' + sw + '"/></g>';
      drew++;
    });
    result.unchanged.forEach(function (rec) {
      if (!onThisFloor(rec.after.location)) return;
      var c = apCoord(rec.after); if (!c) return;
      g += '<circle class="rep-aud-same" cx="' + c.x + '" cy="' + c.y + '" r="' + (dotR * 0.6)
        + '" stroke-width="' + (sw * 0.6) + '"/>';
    });

    if (!drew) return '';
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + ' — what changed</h2>'
      + '<div class="rep-overview">'
      +   '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +     '<img src="' + url + '" alt="Floor plan">'
      +     '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + g + '</svg>'
      +   '</div>'
      +   '<div class="rep-overview-key rep-aud-key">'
      +     '<span class="rep-aud-k rep-aud-k--added">Added</span>'
      +     '<span class="rep-aud-k rep-aud-k--changed">Changed</span>'
      +     '<span class="rep-aud-k rep-aud-k--was">Was here</span>'
      +     '<span class="rep-aud-k rep-aud-k--removed">Removed</span>'
      +     '<span class="rep-aud-k rep-aud-k--same">Unchanged</span>'
      +   '</div>'
      + '</div>'
      + '</section>';
  }

  function renderAuditReport(aps, opts, ctx) {
    /* No baseline is the report's ordinary starting state, not a fault. It
       says which control chooses one and where that control is, because a
       page reading "nothing to show" sends somebody looking for a file they
       have already got. */
    if (!baseline) {
      return '<div class="rep-empty rep-empty--wide">'
        + '<h2>Choose the earlier .esx to compare against</h2>'
        + '<p>This report needs two files: the project open in this tool is the '
        + '<b>after</b>, and the one you choose is the <b>before</b>.</p>'
        + '<p>Use <b>Choose the earlier .esx…</b> in the options panel on the '
        + 'left, under <b>Earlier project to compare against</b>. Nothing is '
        + 'written to either file, and the earlier one is only read.</p>'
        + (baselineError ? '<p class="rep-warn">' + WD.esc(baselineError) + '</p>' : '')
        + '</div>';
    }

    var threshold = Number(opts.moveThreshold);
    if (!isFinite(threshold) || threshold < 0) threshold = DEFAULT_MOVE_THRESHOLD_M;
    var result = compareProjects(baseline, proj, { threshold: threshold });

    var head = opts.cover
      ? ctx.cover(proj.accessPoints.length, ctx.dateStr, 'Access points')
      : ctx.inlineHeader(proj.accessPoints.length, ctx.dateStr, 'Access points');

    /* ── which two files, in which order ─────────────────────────────────── */
    var nBefore = baseline.accessPoints.length;
    var nAfter = proj.accessPoints.length;
    var whichFiles = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">What is being compared</h2>'
      + '<table class="rep-ap-table">'
      + '<colgroup><col style="width:18%"><col style="width:46%"><col style="width:36%"></colgroup>'
      + '<thead><tr><th></th><th>File</th><th>Project name</th></tr></thead><tbody>'
      + '<tr><td class="rep-name">Before</td><td class="rep-name">' + WD.esc(baselineName)
      +   '</td><td class="rep-name">' + WD.esc(baseline.projectName || '—') + '</td></tr>'
      + '<tr><td class="rep-name">After</td><td class="rep-name">' + WD.esc(fileName)
      +   '</td><td class="rep-name">' + WD.esc(proj.projectName || '—') + '</td></tr>'
      + '</tbody></table>'
      + '<p class="rep-aud-note">A movement counts as a move at '
      +   WD.esc(fmtLength(threshold, opts)) + ' or more. Smaller differences are '
      +   'left out, because a design nudged by a few centimetres is not an access '
      +   'point somebody put somewhere else.</p>'
      + (result.matchedByName
          ? '<p class="rep-aud-note">' + result.matchedByName + ' access point'
            + (result.matchedByName === 1 ? ' was' : 's were')
            + ' paired by name rather than by the id Ekahau gives them, which '
            + 'happens when one is deleted and re-added. Those pairings are a '
            + 'judgement rather than a fact.</p>'
          : '')
      + '</section>';

    /* ── the counts ──────────────────────────────────────────────────────── */
    var bRadios = radioIndexFor(baseline), aRadios = radioIndexFor(proj);
    function countDirectional(project, idx) {
      return (project.accessPoints || []).filter(function (a) {
        return radioIsDirectional(idx[a.id]);
      }).length;
    }
    var statRows = [
      ['Access points', nBefore, nAfter],
      ['Floor plans', (baseline.floorPlans || []).length, (proj.floorPlans || []).length],
      ['Directional APs', countDirectional(baseline, bRadios), countDirectional(proj, aRadios)],
      ['Radios', (baseline.radios || []).length, (proj.radios || []).length],
    ];
    var stats = '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Before and after</h2>'
      + '<table class="rep-ap-table">'
      + '<colgroup><col style="width:46%"><col style="width:18%"><col style="width:18%"><col style="width:18%"></colgroup>'
      + '<thead><tr><th>Count</th><th class="rep-num">Before</th>'
      +   '<th class="rep-num">After</th><th class="rep-num">Change</th></tr></thead><tbody>'
      + statRows.map(function (r) {
          return '<tr><td class="rep-name">' + WD.esc(r[0]) + '</td>'
            + '<td class="rep-az">' + r[1] + '</td>'
            + '<td class="rep-az">' + r[2] + '</td>'
            + '<td class="rep-az">' + deltaCell(r[1], r[2]) + '</td></tr>';
        }).join('')
      + '<tr><td class="rep-name">Added</td><td class="rep-az">—</td>'
      +   '<td class="rep-az">' + result.added.length + '</td><td class="rep-az"></td></tr>'
      + '<tr><td class="rep-name">Removed</td><td class="rep-az">' + result.removed.length
      +   '</td><td class="rep-az">—</td><td class="rep-az"></td></tr>'
      + '<tr><td class="rep-name">Changed</td><td class="rep-az">—</td>'
      +   '<td class="rep-az">' + result.changed.length + '</td><td class="rep-az"></td></tr>'
      + '<tr><td class="rep-name">Unchanged</td><td class="rep-az">—</td>'
      +   '<td class="rep-az">' + result.unchanged.length + '</td><td class="rep-az"></td></tr>'
      + '</tbody></table>'
      + '</section>';

    /* ── a re-cropped plan, said out loud ────────────────────────────────── */
    var cropNote = '';
    if (result.floorNotes.length) {
      cropNote = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Floor plans that were re-cropped</h2>'
        + '<p class="rep-aud-note">Positions inside an .esx are measured from the '
        + 'corner of the floor plan image, so trimming a plan moves every '
        + 'coordinate on it by the same amount. These floors changed size between '
        + 'the two files. The shift has been measured and taken out, so what is '
        + 'listed below is movement relative to the building rather than to the '
        + 'image — without that, every access point on these floors would be '
        + 'reported as having moved.</p>'
        + '<table class="rep-ap-table">'
        + '<colgroup><col style="width:34%"><col style="width:22%"><col style="width:22%"><col style="width:22%"></colgroup>'
        + '<thead><tr><th>Floor</th><th class="rep-num">Before</th>'
        +   '<th class="rep-num">After</th><th class="rep-num">Shift taken out</th></tr></thead><tbody>'
        + result.floorNotes.map(function (n) {
            return '<tr><td class="rep-name">' + WD.esc(n.name) + '</td>'
              + '<td class="rep-az">' + n.beforeSize[0] + '×' + n.beforeSize[1] + '</td>'
              + '<td class="rep-az">' + n.afterSize[0] + '×' + n.afterSize[1] + '</td>'
              + '<td class="rep-az">' + fmt(n.dx, 0) + ', ' + fmt(n.dy, 0) + ' px</td></tr>';
          }).join('')
        + '</tbody></table></section>';
    }

    /* ── the changes, per floor ──────────────────────────────────────────── */
    function apRowsTable(title, rows, withChanges) {
      if (!rows.length) return '';
      return '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">' + WD.esc(title) + ' (' + rows.length + ')</h2>'
        + '<table class="rep-ap-table">'
        + (withChanges
            ? '<colgroup><col style="width:30%"><col style="width:20%"><col style="width:50%"></colgroup>'
              + '<thead><tr><th>Access point</th><th>Floor</th><th>What changed</th></tr></thead>'
            : '<colgroup><col style="width:34%"><col style="width:24%"><col style="width:42%"></colgroup>'
              + '<thead><tr><th>Access point</th><th>Floor</th><th>Model</th></tr></thead>')
        + '<tbody>' + rows.join('') + '</tbody></table></section>';
    }

    function floorNameForAp(ap, project) {
      var id = (ap.location || {}).floorPlanId;
      var f = (project.floorPlans || []).find(function (x) { return x.id === id; });
      return (f && f.name) || '—';
    }

    var changedRows = result.changed.slice().sort(function (a, b) {
      return String(a.after.name || '').localeCompare(String(b.after.name || ''),
                                                      undefined, { numeric: true });
    }).map(function (rec) {
      return '<tr>'
        + '<td class="rep-name">' + WD.esc(rec.after.name || '(unnamed)') + '</td>'
        + '<td class="rep-name">' + WD.esc(floorNameForAp(rec.after, proj)) + '</td>'
        + '<td>' + changeSummaryCell(rec, opts, ctx) + '</td>'
        + '</tr>';
    });
    var addedRows = result.added.slice().sort(function (a, b) {
      return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true });
    }).map(function (ap) {
      return '<tr><td class="rep-name">' + WD.esc(ap.name || '(unnamed)') + '</td>'
        + '<td class="rep-name">' + WD.esc(floorNameForAp(ap, proj)) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.model || '—') + '</td></tr>';
    });
    var removedRows = result.removed.slice().sort(function (a, b) {
      return String(a.name || '').localeCompare(String(b.name || ''), undefined, { numeric: true });
    }).map(function (ap) {
      return '<tr><td class="rep-name">' + WD.esc(ap.name || '(unnamed)') + '</td>'
        + '<td class="rep-name">' + WD.esc(floorNameForAp(ap, baseline)) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.model || '—') + '</td></tr>';
    });

    var nothingChanged = '';
    if (!result.changed.length && !result.added.length && !result.removed.length) {
      nothingChanged = '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Nothing changed</h2>'
        + '<p class="rep-aud-note">All ' + result.unchanged.length + ' access point'
        + (result.unchanged.length === 1 ? ' is' : 's are')
        + ' the same in both files: same place, same aim, same mount, same hardware. '
        + 'That is a result, not an empty report.</p></section>';
    }

    var floorSections = '';
    if (opts.overlay !== false) {
      sortedFloorOrder({}).forEach(function (fp) {
        if (fp.id === '_none') return;
        floorSections += renderAuditOverlay(fp, result, opts, ctx);
      });
    }

    /* The notes pages are unbounded, so they go last and they go in the return
       expression - see tests/test_ap_notes_last.py, and the AP Placement Map
       that appended them twenty lines early and put the compass page after
       the lot. */
    return head + whichFiles + stats + cropNote
      + nothingChanged
      + apRowsTable('Changed', changedRows, true)
      + apRowsTable('Added', addedRows, false)
      + apRowsTable('Removed', removedRows, false)
      + floorSections
      + REPORT_FOOTER
      /* Every access point, not the filtered list. This report hides the AP
         filter panel (``noApFilter``), and with it hidden ``renderReport``
         defaults "include omni" to off - so passing the filtered list here
         would quietly drop the notes on every omni AP in the project, on a
         page nobody had a control to correct. */
      + apNotesPages(proj.accessPoints, opts, ctx);
  }

  function renderAimReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points to aim')
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points to aim');

    if (!aps.length) {
      return head
        + '<section class="rep-floor-section">'
        +   '<h2 class="rep-floor-title">No directional APs</h2>'
        +   '<div class="rep-empty-small">This report only lists APs that need aiming. Enable "Include omni APs" in the sidebar if you want the omni units on the sheet too.</div>'
        + '</section>'
        + REPORT_FOOTER;
    }

    var byFloor = groupApsByFloor(aps, ctx);
    var floorOrder = sortedFloorOrder(byFloor);

    var sorted = [];
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      floorAps.slice()
        .sort(function (a, b) { return (a.name || '').localeCompare(b.name || ''); })
        .forEach(function (ap) { sorted.push({ ap: ap, floor: fp }); });
    });

    var showSignOff = opts.signOff !== false;
    var showGrid = showsGridColumn(opts);
    var rows = '';
    sorted.forEach(function (item, i) {
      var ap = item.ap;
      var r = ctx.primaryRadio(ap.id);
      var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
      var dir = r ? r.antennaDirection : null;
      var tilt = r ? r.antennaTilt : null;
      var height = r ? r.antennaHeight : null;

      var heightStr = ctx.fmtLength(height, opts, 1);
      var azStr = dir == null ? '<span class="rep-alt">omni</span>'
        : (opts.compass !== false
            ? ctx.fmt(dir, 1) + '° <span class="rep-alt">(' + ctx.compass(dir) + ')</span>'
            : ctx.fmt(dir, 1) + '°');
      var tiltStr = tilt == null ? '—' : ctx.fmt(tilt, 1) + '°';

      var lbl = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      rows += '<tr>'
        + '<td class="rep-num">' + WD.esc(lbl) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
        + '<td>' + WD.esc(item.floor.name || '—') + '</td>'
        + (showGrid ? '<td class="rep-grid-ref">'
            + WD.esc(gridRefForAp(ap) || '—') + '</td>' : '')
        + '<td class="rep-az">' + azStr + '</td>'
        + '<td>' + tiltStr + '</td>'
        + '<td>' + heightStr + '</td>'
        + '<td>' + WD.esc(ant ? ant.name : '—') + '</td>'
        + (showSignOff ? '<td class="rep-aim-signoff"></td><td class="rep-aim-signoff"></td>' : '')
        + '</tr>';
    });

    /* Column widths, because `table-layout: fixed` without them divides the
       sheet evenly and Tilt gets as much room as an external antenna's part
       number. What that looked like: "BLDG01-FL01-AP003" overflowing the AP
       name column and printing on top of the Floor value beside it, and the
       sign-off header clipped to "INSTALLER INITI" running into "DATE". The
       weights are content classes, not guesses - a name and an antenna model
       are long, a tilt is four characters. */
    var cols = showSignOff
      ? [5, 22, 9, 12, 6, 8, 22, 8, 8]
      : [6, 26, 11, 14, 8, 10, 25];
    /* "AA-12" is the widest a reference gets, so the column is narrow - and it
       is inserted where the header is rather than appended, or it would sit
       under Azimuth. The width comes off AP name and Antenna, which are the
       two that have any to give. */
    if (showGrid) {
      cols = cols.slice();
      cols.splice(3, 0, 7);          // after Floor, which is where the header is
      cols[1] -= 4;                  // AP name
      cols[7] -= 3;                  // Antenna, which is index 7 either way
    }
    var colGroup = '<colgroup>'
      + cols.map(function (w) { return '<col style="width:' + w + '%">'; }).join('')
      + '</colgroup>';

    var table = '<section class="rep-aim-table-section">'
      + '<table class="rep-ap-table rep-aim-table">'
      +   colGroup
      +   '<thead><tr>'
      +     '<th class="rep-num">#</th>'
      +     '<th>AP name</th>'
      +     '<th>Floor</th>'
      +     (showGrid ? '<th>Grid</th>' : '')
      +     '<th>Azimuth</th>'
      +     '<th>Tilt</th>'
      +     '<th>Height</th>'
      +     '<th>Antenna</th>'
      +     (showSignOff ? '<th class="rep-aim-signoff-head">Initials</th><th class="rep-aim-signoff-head">Date</th>' : '')
      +   '</tr></thead>'
      +   '<tbody>' + rows + '</tbody>'
      + '</table>'
      + '</section>';

    var maps = '';
    if (opts.overview !== false) {
      floorOrder.forEach(function (fp) {
        var floorAps = byFloor[fp.id];
        if (!floorAps || !floorAps.length || fp.id === '_none') return;
        maps += renderAimMiniMap(fp, floorAps, opts, ctx);
      });
    }

    var compassPage = wantsCompassRef(aps, opts) ? renderCompassReferencePage(opts, ctx) : '';

    return head + table + maps + compassPage + apNotesPages(aps, opts, ctx)
      + REPORT_FOOTER;
  }

  function renderAimMiniMap(fp, floorAps, opts, ctx) {
    var url = floorPlanImageUrl(fp);
    if (!url) return '';
    var W = fp.width || 1, H = fp.height || 1;
    var tickLen = Math.min(W, H) * 0.05;
    var dotR = Math.min(W, H) * 0.014;

    var minDim = Math.min(W, H);
    var markers = '';
    floorAps.forEach(function (ap) {
      var c = ap.location && ap.location.coord; if (!c) return;
      var r = ctx.primaryRadio(ap.id);
      var dir = r ? r.antennaDirection : null;
      var isDirectional = radioIsDirectional(r);
      markers += '<g class="rep-aim-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      if (isDirectional) {
        markers += '<g transform="rotate(' + dir + ')">'
          + '<line class="rep-aim-tick" x1="0" y1="0" x2="0" y2="' + (-tickLen) + '"/>'
          + '</g>';
      }
      var label = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      /* Same legibility floor the placement map uses, and for the same
         reason: a fraction of the short edge is not a size on paper. On a
         1152x506 floor this printed at 5.4pt - the map is a sanity check
         before climbing a ladder, and a number you cannot read is not one.
         1.35% of the long edge lands near 7pt at the width these print. */
      var legibleFloor = Math.max(W, H) * 0.0135;
      var labelFont = Math.max(legibleFloor,
                               minDim * 0.022 * Math.min(1, 3 / Math.max(3, label.length)));
      var padX = minDim * 0.006;
      var boxW = Math.max(minDim * 0.03, label.length * labelFont * 0.65) + padX * 2;
      var boxH = Math.max(minDim * 0.028, labelFont * 1.5);
      var cornerR = minDim * 0.005;
      markers += '<rect class="rep-aim-dot" x="' + (-boxW / 2) + '" y="' + (-boxH / 2) + '" width="' + boxW + '" height="' + boxH + '" rx="' + cornerR + '" ry="' + cornerR + '"/>'
        + '<text class="rep-aim-num" y="' + (labelFont * 0.35) + '" text-anchor="middle" font-size="' + labelFont + '">'
        + WD.esc(label) + '</text></g>';
    });

    var labelHint = antennaLabelHint(opts);
    return '<section class="rep-floor-section rep-aim-map-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
      + '<div class="rep-overview">'
      +   '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +     '<img src="' + url + '" alt="Floor plan">'
      +     '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + markers + '</svg>'
      +   '</div>'
      +   '<div class="rep-overview-key">' + WD.esc(labelHint) + '</div>'
      + '</div>'
      + '</section>';
  }






  var COV_THRESH_STRONG = -55;
  var COV_THRESH_GOOD   = -67;
  var COV_THRESH_FAIR   = -75;
  var COV_THRESH_WEAK   = -80;

  function _covBandFromChannel(channels) {
    if (!channels || !channels.length) return 'FIVE';
    var f = channels[0];
    if (f < 3000) return 'TWO';
    if (f < 5950) return 'FIVE';
    return 'SIX';
  }

  function _covBandLabel(band) {
    if (band === 'TWO') return '2.4 GHz';
    if (band === 'SIX') return '6 GHz';
    return '5 GHz';
  }

  function _covBandColor(band) {
    if (band === 'TWO') return '#1e77ac';
    if (band === 'SIX') return '#8b5cf6';
    return '#5fab4f';
  }



  function _covPlBase(band) {
    if (band === 'TWO') return 40.0;
    if (band === 'SIX') return 48.0;
    return 46.5;
  }

  function _covRadiusMeters(eirp, rssiTarget, band) {
    var pl = eirp - rssiTarget;
    var expo = (pl - _covPlBase(band)) / 30.0;
    var r = Math.pow(10, expo);
    if (!isFinite(r) || r < 0.1) return 0.1;
    if (r > 500) return 500;
    return r;
  }

  function _covApRadio(ap) {


    var r = primaryRadio(ap.id);
    if (r) return r;
    var rs = proj.radios.filter(function (x) { return x.accessPointId === ap.id; });
    return rs[0] || null;
  }

  function renderCoverageReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points')
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points');

    var byFloor = groupApsByFloor(aps, ctx);

    var sections = '';
    var indexById = {};
    var seq = 0;
    (proj.floorPlans || []).forEach(function (fp) {
      (byFloor[fp.id] || []).forEach(function (ap) { indexById[ap.id] = ++seq; });
    });
    (byFloor['_none'] || []).forEach(function (ap) { indexById[ap.id] = ++seq; });

    (proj.floorPlans || []).forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      sections += renderCoverageFloorSection(fp, floorAps, opts, ctx, indexById);
    });

    var legend = opts.legend !== false ? renderCoverageLegend(aps, opts, ctx, indexById) : '';
    var method = renderCoverageMethodology(opts);

    return head + sections + legend + method + apNotesPages(aps, opts, ctx)
      + REPORT_FOOTER;
  }

  function renderCoverageFloorSection(fp, aps, opts, ctx, indexById) {
    var url = floorPlanImageUrl(fp);
    if (!url) {
      return '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
        + '<div class="rep-empty-small">Floor plan image not available.</div>'
        + '</section>';
    }
    var W = fp.width || 1, H = fp.height || 1;
    var mPerU = fp.metersPerUnit || 0.05;
    var showCells = opts.primaryCells !== false;
    var showRings = opts.signalRings === true;
    var showLabels = opts.showApLabels !== false;
    var bandTint = opts.bandColors !== false;
    var minDim = Math.min(W, H);

    var cellsSvg = '', ringsSvg = '', pinsSvg = '';
    aps.forEach(function (ap) {
      var c = ap.location && ap.location.coord;
      if (!c) return;
      var r = _covApRadio(ap);
      if (!r) return;
      var ant = r.antennaTypeId ? proj.antennas[r.antennaTypeId] : null;
      var gain = ant && ant.maxGain != null ? ant.maxGain : 3;
      var txp = r.transmitPower != null ? r.transmitPower : 15;
      var eirp = txp + gain;
      var band = _covBandFromChannel(r.channelByCenterFrequencyDefinedNarrowChannels);
      var color = bandTint ? _covBandColor(band) : '#0668D9';

      var rGood   = _covRadiusMeters(eirp, COV_THRESH_GOOD,   band) / mPerU;
      if (showCells) {
        cellsSvg += '<circle class="rep-cov-cell" cx="' + c.x + '" cy="' + c.y + '" r="' + rGood + '" fill="' + color + '" fill-opacity="0.13" stroke="' + color + '" stroke-opacity="0.55" stroke-width="' + (minDim * 0.0015) + '"/>';
      }
      if (showRings) {
        var rStrong = _covRadiusMeters(eirp, COV_THRESH_STRONG, band) / mPerU;
        var rFair   = _covRadiusMeters(eirp, COV_THRESH_FAIR,   band) / mPerU;
        var rWeak   = _covRadiusMeters(eirp, COV_THRESH_WEAK,   band) / mPerU;
        var sw = minDim * 0.0015;
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rStrong + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.9"/>';
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rFair   + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.55" stroke-dasharray="' + (minDim * 0.008) + ' ' + (minDim * 0.005) + '"/>';
        ringsSvg += '<circle class="rep-cov-ring" cx="' + c.x + '" cy="' + c.y + '" r="' + rWeak   + '" fill="none" stroke="' + color + '" stroke-width="' + sw + '" stroke-opacity="0.35" stroke-dasharray="' + (minDim * 0.003) + ' ' + (minDim * 0.006) + '"/>';
      }
      var covLabel = String(indexById[ap.id] || '');
      /* The number here is what ties a cell on the map to its row in the
         "Cell sizing per AP" table, so it has to survive printing. Floored
         the same way as every other marker in this file. */
      var covFont = Math.max(Math.max(W, H) * 0.0135, minDim * 0.022);
      var covPadX = minDim * 0.006;
      var covBoxW = Math.max(minDim * 0.03, covLabel.length * covFont * 0.65) + covPadX * 2;
      var covBoxH = Math.max(minDim * 0.028, covFont * 1.5);
      var covCornerR = minDim * 0.005;
      pinsSvg += '<g class="rep-cov-mark" transform="translate(' + c.x + ',' + c.y + ')">';
      pinsSvg += '<rect class="rep-cov-dot" x="' + (-covBoxW / 2) + '" y="' + (-covBoxH / 2) + '" width="' + covBoxW + '" height="' + covBoxH + '" rx="' + covCornerR + '" ry="' + covCornerR + '" fill="' + color + '" stroke="#fff" stroke-width="' + (minDim * 0.003) + '"/>';
      if (showLabels) {
        pinsSvg += '<text class="rep-cov-num" y="' + (covFont * 0.35) + '" text-anchor="middle" font-size="' + covFont + '" fill="#fff" font-weight="700">' + covLabel + '</text>';
      }
      pinsSvg += '</g>';
    });

    return '<section class="rep-floor-section rep-cov-section">'
      + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>'
      + '<div class="rep-overview">'
      +   '<div class="rep-overview-plan" style="--w:' + W + ';--h:' + H + '">'
      +     '<img src="' + url + '" alt="Floor plan">'
      +     '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + cellsSvg + ringsSvg + pinsSvg + '</svg>'
      +   '</div>'
      +   renderCoverageFloorKey(opts)
      + '</div>'
      + '</section>';
  }

  function renderCoverageFloorKey(opts) {
    var items = [];
    if (opts.primaryCells !== false) items.push('<span class="rep-cov-key-swatch cell"></span> Primary cell (&minus;67 dBm)');
    if (opts.signalRings === true) {
      items.push('<span class="rep-cov-key-swatch ring-strong"></span> Strong &lt;&minus;55');
      items.push('<span class="rep-cov-key-swatch ring-fair"></span> Fair &lt;&minus;75');
      items.push('<span class="rep-cov-key-swatch ring-weak"></span> Weak &lt;&minus;80');
    }
    if (opts.bandColors !== false) {
      items.push('<span class="rep-cov-band-swatch two"></span> 2.4 GHz');
      items.push('<span class="rep-cov-band-swatch five"></span> 5 GHz');
      items.push('<span class="rep-cov-band-swatch six"></span> 6 GHz');
    }
    if (!items.length) return '';
    return '<div class="rep-cov-key">' + items.join(' &nbsp;·&nbsp; ') + '</div>';
  }

  function renderCoverageLegend(aps, opts, ctx, indexById) {
    var rows = '';
    aps.slice()
      .sort(function (a, b) { return (indexById[a.id] || 0) - (indexById[b.id] || 0); })
      .forEach(function (ap) {
        var r = _covApRadio(ap);
        if (!r) return;
        var ant = r.antennaTypeId ? proj.antennas[r.antennaTypeId] : null;
        var gain = ant && ant.maxGain != null ? ant.maxGain : 3;
        var txp = r.transmitPower != null ? r.transmitPower : 15;
        var eirp = txp + gain;
        var band = _covBandFromChannel(r.channelByCenterFrequencyDefinedNarrowChannels);
        var rGood = _covRadiusMeters(eirp, COV_THRESH_GOOD, band);
        var rWeak = _covRadiusMeters(eirp, COV_THRESH_WEAK, band);
        rows += '<tr>'
          + '<td class="rep-num">' + (indexById[ap.id] || '') + '</td>'
          + '<td class="rep-name">' + WD.esc(ap.name) + '</td>'
          + '<td>' + _covBandLabel(band) + '</td>'
          + '<td>' + fmt(txp, 1) + ' dBm</td>'
          + '<td>' + fmt(gain, 1) + ' dBi</td>'
          + '<td>' + fmt(eirp, 1) + ' dBm</td>'
          + '<td>' + fmt(rGood, 1) + ' m</td>'
          + '<td>' + fmt(rWeak, 1) + ' m</td>'
          + '</tr>';
      });
    if (!rows) return '';
    return '<section class="rep-legend rep-cov-legend">'
      + '<h2 class="rep-floor-title">Cell sizing per AP</h2>'
      + '<table class="rep-ap-table">'
      +   '<thead><tr>'
      +     '<th class="rep-num">#</th><th>AP name</th><th>Band</th>'
      +     '<th>TX power</th><th>Antenna gain</th><th>EIRP</th>'
      +     '<th>&minus;67 dBm radius</th><th>&minus;80 dBm radius</th>'
      +   '</tr></thead>'
      +   '<tbody>' + rows + '</tbody>'
      + '</table>'
      + '</section>';
  }

  function renderCoverageMethodology(opts) {
    return '<section class="rep-floor-section rep-cov-method">'
      + '<h2 class="rep-floor-title">Methodology &amp; caveats</h2>'
      + '<div class="rep-hotspot-method">'
      +   '<p><b>Model.</b> Cell radii use a simple log-distance path-loss model with exponent <b>n = 3</b> and per-band 1-metre baselines (40 dB at 2.4 GHz, 46.5 dB at 5 GHz, 48 dB at 6 GHz). Received signal is estimated as <b>RSSI = EIRP &minus; PathLoss(d)</b> and solved for the distance <b>d</b> at each threshold.</p>'
      +   '<p><b>Thresholds.</b> Strong &lt; &minus;55 dBm · Good &minus;55 to &minus;67 · Fair &minus;67 to &minus;75 · Weak &minus;75 to &minus;80. The filled primary cell is drawn at the &minus;67 dBm boundary — the standard threshold for reliable voice and video.</p>'
      +   '<p><b>What it does not model.</b> Walls, floors, and materials are not attenuated. Directional antennas are treated as omnidirectional for the purpose of cell radius — the extra gain enlarges the circle uniformly rather than shaping a sector. Interference, channel overlap, client-side sensitivity, and airtime utilisation are all outside the scope of this drawing.</p>'
      +   '<p><b>Read this report as.</b> An advisory sanity check for AP placement — "does the map look reasonable, and where are the obvious weak-signal gaps." Not a substitute for a measured predictive survey.</p>'
      + '</div>'
      + '</section>';
  }

  function autocropOverlay(overlayEl) {
    var img = overlayEl.querySelector('img');
    var svg = overlayEl.querySelector('svg');
    if (!img || !svg) return Promise.resolve();
    var vb = (svg.getAttribute('viewBox') || '').split(/\s+/).map(Number);
    if (vb.length !== 4 || !vb[2] || !vb[3]) return Promise.resolve();
    var VBX = vb[0], VBY = vb[1], VBW = vb[2], VBH = vb[3];

    return new Promise(function (resolve) {
      function ready() {
        try { doCrop(); } catch (e) { console.error('autocrop', e); }
        resolve();
      }
      if (img.complete && img.naturalWidth) ready();
      else { img.addEventListener('load', ready, {once: true});
             img.addEventListener('error', function () { resolve(); }, {once: true}); }
    });

    function doCrop() {
      var natW = img.naturalWidth, natH = img.naturalHeight;
      if (!natW || !natH) return;
      var scale = Math.min(1, 500 / Math.max(natW, natH));
      var sW = Math.max(1, Math.round(natW * scale));
      var sH = Math.max(1, Math.round(natH * scale));
      var c = document.createElement('canvas');
      c.width = sW; c.height = sH;
      var g = c.getContext('2d', {willReadFrequently: true});
      g.drawImage(img, 0, 0, sW, sH);
      var data;
      try { data = g.getImageData(0, 0, sW, sH).data; }
      catch (e) { return; }
      var minX = sW, minY = sH, maxX = -1, maxY = -1;
      for (var y = 0; y < sH; y++) {
        for (var x = 0; x < sW; x++) {
          var i = (y * sW + x) * 4;
          if (data[i] < 245 || data[i + 1] < 245 || data[i + 2] < 245) {
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
          }
        }
      }
      if (maxX < 0) return;
      var kx = VBW / sW, ky = VBH / sH;
      var cx0 = VBX + minX * kx;
      var cy0 = VBY + minY * ky;
      var cx1 = VBX + (maxX + 1) * kx;
      var cy1 = VBY + (maxY + 1) * ky;
      var plines = svg.querySelectorAll('polyline');
      for (var pi = 0; pi < plines.length; pi++) {
        var pts = (plines[pi].getAttribute('points') || '').trim().split(/\s+/);
        for (var pj = 0; pj < pts.length; pj++) {
          var xy = pts[pj].split(',');
          var px = +xy[0], py = +xy[1];
          if (!isFinite(px) || !isFinite(py)) continue;
          if (px < cx0) cx0 = px;
          if (px > cx1) cx1 = px;
          if (py < cy0) cy0 = py;
          if (py > cy1) cy1 = py;
        }
      }
      var pad = Math.max(8, Math.min(cx1 - cx0, cy1 - cy0) * 0.02);
      cx0 = Math.max(VBX, cx0 - pad);
      cy0 = Math.max(VBY, cy0 - pad);
      cx1 = Math.min(VBX + VBW, cx1 + pad);
      cy1 = Math.min(VBY + VBH, cy1 + pad);
      var cW = cx1 - cx0, cH = cy1 - cy0;
      if (cW / VBW > 0.9 && cH / VBH > 0.9) return;
      var srcX = Math.round(natW * (cx0 - VBX) / VBW);
      var srcY = Math.round(natH * (cy0 - VBY) / VBH);
      var srcW = Math.round(natW * cW / VBW);
      var srcH = Math.round(natH * cH / VBH);
      var outScale = Math.min(1, 2000 / Math.max(srcW, srcH));
      var out = document.createElement('canvas');
      out.width = Math.max(1, Math.round(srcW * outScale));
      out.height = Math.max(1, Math.round(srcH * outScale));
      out.getContext('2d').drawImage(img, srcX, srcY, srcW, srcH,
                                     0, 0, out.width, out.height);
      out.toBlob(function (blob) {
        if (!blob) return;
        var newUrl = URL.createObjectURL(blob);
        img.src = newUrl;
        overlayEl.style.setProperty('--w', cW);
        overlayEl.style.setProperty('--h', cH);
        svg.setAttribute('viewBox', cx0 + ' ' + cy0 + ' ' + cW + ' ' + cH);
      }, 'image/jpeg', 0.85);
    }
  }

  function applyHotspotAutocrop(host, opts) {
    if (!opts.autocrop) return;
    var overlays = host.querySelectorAll('.rep-overview-plan[data-crop-src]');
    for (var i = 0; i < overlays.length; i++) autocropOverlay(overlays[i]);
  }

  /* ── Compass Reference Page ────────────────────────────────────────────
     One printable page with a compass rose and practical guidance for
     aligning directional APs to the azimuth values in the report. */
  function renderCompassReferencePage(opts, ctx) {
    var R = 140, cx = 160, cy = 160;

    var ticks = '', labels = '';
    for (var d = 0; d < 360; d += 5) {
      var rad = d * Math.PI / 180;
      var isMajor = d % 90 === 0;
      var isMid   = d % 45 === 0 && !isMajor;
      var isMinor = d % 15 === 0 && !isMajor && !isMid;
      var inner = isMajor ? R - 22 : isMid ? R - 16 : isMinor ? R - 12 : R - 7;
      var x1 = cx + inner * Math.sin(rad), y1 = cy - inner * Math.cos(rad);
      var x2 = cx + R * Math.sin(rad),     y2 = cy - R * Math.cos(rad);
      var cls = isMajor ? 'rep-comp-major' : isMid ? 'rep-comp-mid' : isMinor ? 'rep-comp-minor' : 'rep-comp-fine';
      ticks += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" class="' + cls + '"/>';
    }

    var cardinals = [
      { deg:   0, lbl: 'N',   cls: 'rep-comp-n' },
      { deg:  90, lbl: 'E',   cls: '' },
      { deg: 180, lbl: 'S',   cls: '' },
      { deg: 270, lbl: 'W',   cls: '' },
    ];
    var intercardinals = [
      { deg:  45, lbl: 'NE' }, { deg: 135, lbl: 'SE' },
      { deg: 225, lbl: 'SW' }, { deg: 315, lbl: 'NW' },
    ];

    cardinals.forEach(function (c) {
      var rad = c.deg * Math.PI / 180;
      var lr = R + 18;
      var x = cx + lr * Math.sin(rad), y = cy - lr * Math.cos(rad);
      labels += '<text x="' + x + '" y="' + y + '" class="rep-comp-cardinal ' + c.cls
        + '" text-anchor="middle" dominant-baseline="central">' + c.lbl + '</text>';
    });
    intercardinals.forEach(function (c) {
      var rad = c.deg * Math.PI / 180;
      var lr = R + 16;
      var x = cx + lr * Math.sin(rad), y = cy - lr * Math.cos(rad);
      labels += '<text x="' + x + '" y="' + y + '" class="rep-comp-intercard"'
        + ' text-anchor="middle" dominant-baseline="central">' + c.lbl + '</text>';
    });

    var degLabels = '';
    for (var a = 0; a < 360; a += 30) {
      var aRad = a * Math.PI / 180;
      var lr2 = R - 32;
      var dx = cx + lr2 * Math.sin(aRad), dy = cy - lr2 * Math.cos(aRad);
      degLabels += '<text x="' + dx + '" y="' + dy + '" class="rep-comp-deg"'
        + ' text-anchor="middle" dominant-baseline="central"'
        + ' transform="rotate(' + a + ' ' + dx + ' ' + dy + ')">' + a + '°</text>';
    }

    var needle = '<polygon points="' + cx + ',' + (cy - R + 30) + ' '
      + (cx - 6) + ',' + cy + ' ' + (cx + 6) + ',' + cy + '" class="rep-comp-needle-n"/>'
      + '<polygon points="' + cx + ',' + (cy + R - 30) + ' '
      + (cx - 6) + ',' + cy + ' ' + (cx + 6) + ',' + cy + '" class="rep-comp-needle-s"/>';

    var svg = '<svg viewBox="0 0 320 320" class="rep-comp-rose"'
      + ' xmlns="http://www.w3.org/2000/svg">'
      + '<circle cx="' + cx + '" cy="' + cy + '" r="' + R + '" class="rep-comp-ring"/>'
      + '<circle cx="' + cx + '" cy="' + cy + '" r="4" class="rep-comp-center"/>'
      + ticks + degLabels + needle + labels
      + '</svg>';

    return '<section class="rep-floor-section rep-compass-page rep-oriented"'
      + ' data-page-key="compass" data-page-kind="page">'
      + orientPickerHtml('compass', opts)
      + '<h2 class="rep-floor-title">Compass &amp; Antenna Alignment Reference</h2>'
      + '<div class="rep-compass-body">'
      +   '<div class="rep-compass-left">'
      +     svg
      +     '<p class="rep-compass-caption">Azimuth is measured clockwise from north (0°).<br>'
      +     'The compass heading in your report (N, NE, E, etc.) is shorthand for the degree range.</p>'
      +   '</div>'
      +   '<div class="rep-compass-right">'
      +     '<div class="rep-compass-sect">'
      +       '<h3>Reading azimuth values in this report</h3>'
      +       '<p>Each directional AP in the tables has an <b>azimuth</b> value — the compass bearing '
      +       'the antenna\'s main beam should point toward, measured in degrees clockwise from north '
      +       '(0° = north, 90° = east, 180° = south, 270° = west).</p>'
      +       '<p>These azimuths are relative to the <b>floor plan\'s orientation</b>, where "up" '
      +       'on the page is the plan\'s north. Plan north may not match the building\'s true north '
      +       '— architects often rotate floor plans for readability. To find the offset: pick a straight '
      +       'feature on the plan (a long wall, a corridor), measure its compass bearing in the real '
      +       'building, and compare. Apply that offset to every azimuth.</p>'
      +     '</div>'
      +     '<div class="rep-compass-sect">'
      +       '<h3>Internal-antenna APs</h3>'
      +       '<p>Many modern APs (Cisco 9136, Aruba AP-367, Ruckus R770) have built-in directional '
      +       'antennas — the AP body itself determines the beam direction.</p>'
      +       '<ul>'
      +         '<li>Check the AP\'s installation guide for the <b>antenna reference arrow</b> or '
      +         'marking — this indicates the primary beam direction.</li>'
      +         '<li>Wall-mount APs: rotate the body on the bracket so the reference arrow points '
      +         'toward the azimuth bearing.</li>'
      +         '<li>Ceiling-mount APs: align the reference mark with the intended azimuth. For '
      +         'APs with no mark, the Ethernet port or LED bar is typically treated as the '
      +         '0° reference in the design tool.</li>'
      +         '<li>Even "omni" ceiling APs have a reference orientation — internal MIMO antenna '
      +         'arrays are not perfectly symmetric, and the design plan assumes a specific '
      +         'rotation.</li>'
      +       '</ul>'
      +     '</div>'
      +     '<div class="rep-compass-sect">'
      +       '<h3>External-antenna APs</h3>'
      +       '<p>When the AP uses separate patch, panel, or sector antennas:</p>'
      +       '<ul>'
      +         '<li>Mount the AP body in any convenient orientation — only the <b>antenna face</b> '
      +         'matters for beam direction.</li>'
      +         '<li>Point the flat face (radiating side) of the antenna toward the azimuth bearing. '
      +         'The cable connector side faces away from the target area.</li>'
      +         '<li>Set the <b>down-tilt</b> to the tilt value in the report. A tilt of 0° '
      +         'is horizontal; negative values angle the beam downward. Aim for the main lobe '
      +         'to cross desk height (~1 m) at roughly the midpoint of the cell radius.</li>'
      +         '<li>For MIMO with multiple external antennas, orient them at different angles '
      +         '(e.g. one vertical, one at 45°) for polarization diversity — not all parallel.</li>'
      +       '</ul>'
      +     '</div>'
      +     '<div class="rep-compass-sect">'
      +       '<h3>Using a compass on site</h3>'
      +       '<ul>'
      +         '<li><b>Best technique for ceiling mounts:</b> take your compass bearing while '
      +         'standing on the floor directly below the mount point (less metal interference), '
      +         'identify a visible landmark in the target direction (a doorway, column, window), '
      +         'then align the AP\'s reference arrow toward that landmark while on the ladder.</li>'
      +         '<li><b>Metal interference:</b> steel beams, cable trays, and conduit near the '
      +         'ceiling deflect a magnetic compass. Hold your compass at least 30 cm from metal '
      +         'surfaces. If readings jump or spin, fall back to visual alignment against '
      +         'known building features.</li>'
      +         '<li><b>Phone compass apps:</b> calibrate first (figure-8 motion). Most apps '
      +         'compensate for magnetic declination automatically — verify this in the app\'s '
      +         'settings. Keep the phone away from magnetic cases and mounting hardware.</li>'
      +         '<li><b>Physical compass:</b> reads magnetic north. The difference from true north '
      +         '(declination) is 1–15° across the continental US — usually smaller than the '
      +         'antenna beam width and can be ignored for indoor deployments.</li>'
      +         '<li><b>Verify with the floor plan:</b> sight along the antenna toward a visible '
      +         'landmark that you can also identify on the plan. If the landmark lines up, the '
      +         'bearing is correct — this is more reliable than any compass reading indoors.</li>'
      +       '</ul>'
      +     '</div>'
      +   '</div>'
      + '</div>'
      + '</section>';
  }

  function wantsCompassRef(aps, opts) {
    if (opts.compassRef === 'never') return false;
    if (opts.compassRef === 'always') return true;
    return aps.some(function (ap) { return !apIsOmniOnly(ap); });
  }

  function renderReportFooter(opts, ctx) {
    var rev = (opts && opts.revision) ? ' — ' + opts.revision : '';
    var title = (ctx.report.docName || 'Report') + ' — ' + siteName() + rev;
    var conf = opts.confidential
      ? '<div class="rep-foot-conf">CONFIDENTIAL — Distribution restricted to project stakeholders</div>'
      : '';
    return '<footer class="rep-doc-foot">'
      + '<div class="rep-foot-title">' + WD.esc(title) + '</div>'
      + conf
      + '</footer>';
  }

  function renderLocationTOC(byFloor, floorOrder, opts) {
    var items = '';
    floorOrder.forEach(function (fp) {
      if (!byFloor[fp.id] || !byFloor[fp.id].length) return;
      var apCount = byFloor[fp.id].length;
      var parts = [];
      if (opts.segmented && fp.id !== '_none') {
        var W = fp.width || 1, H = fp.height || 1;
        var grid = computeAntennaGrid(W, H, byFloor[fp.id], opts, fp.metersPerUnit);
        if (grid.cols * grid.rows > 1) {
          parts.push('Sectional grid overview');
          parts.push((grid.cols * grid.rows) + ' detail sections with AP placement maps');
        } else {
          parts.push('Full floor plan with AP placements');
        }
      } else {
        parts.push('Floor plan with AP placements');
      }
      parts.push('Installation table — ' + apCount + ' AP' + (apCount === 1 ? '' : 's'));
      items += '<li><b>' + WD.esc(fp.name || 'Floor plan') + '</b>'
        + '<div class="rep-toc-detail">' + parts.join('<br>') + '</div></li>';
    });
    var extra = '';
    if (opts.nameAudit) extra += '<li><b>AP name audit</b><div class="rep-toc-detail">Naming pattern analysis and outlier detection</div></li>';
    if (opts.specs) extra += '<li><b>Antenna reference</b><div class="rep-toc-detail">Antenna models, specs, and usage counts</div></li>';
    if (opts.signOff !== false) extra += '<li><b>Sign-off</b><div class="rep-toc-detail">Prepared / Reviewed / Approved</div></li>';
    return '<section class="rep-floor-section rep-toc">'
      + '<h2 class="rep-floor-title">Contents</h2>'
      + '<p class="rep-toc-subtitle">Access point installation — sectional placement maps, installation details, and antenna reference for each floor.</p>'
      + '<ol class="rep-toc-list">' + items + extra + '</ol>'
      + '</section>';
  }

  function renderLocationSummary(aps, ctx) {
    var floorIds = {};
    aps.forEach(function (ap) {
      var fp = ctx.floorPlanForAp(ap);
      floorIds[fp ? fp.id : '_none'] = true;
    });
    var floorCount = Object.keys(floorIds).length;
    var buildingIds = {};
    proj.floorPlans.forEach(function (fp) {
      var bf = proj.buildingFloors[fp.id];
      if (bf && bf.buildingId) buildingIds[bf.buildingId] = true;
    });
    var buildingCount = Object.keys(buildingIds).length;
    var directional = aps.filter(function (ap) { return !apIsOmniOnly(ap); }).length;
    var omni = aps.length - directional;
    var antennaIds = collectUsedAntennas(aps, ctx);

    var tiles = '';
    tiles += '<div class="rep-hotspot-stat"><b>' + aps.length + '</b><span>Access points</span></div>';
    tiles += '<div class="rep-hotspot-stat"><b>' + floorCount + '</b><span>Floor plans</span></div>';
    if (buildingCount > 1) {
      tiles += '<div class="rep-hotspot-stat"><b>' + buildingCount + '</b><span>Buildings</span></div>';
    }
    if (directional > 0 && omni > 0) {
      tiles += '<div class="rep-hotspot-stat"><b>' + directional + '</b><span>Directional</span></div>';
      tiles += '<div class="rep-hotspot-stat"><b>' + omni + '</b><span>Omni</span></div>';
    }
    tiles += '<div class="rep-hotspot-stat"><b>' + antennaIds.length + '</b><span>Antenna types</span></div>';

    return '<section class="rep-floor-section rep-summary-hero">'
      + '<h2 class="rep-floor-title">Project overview</h2>'
      + '<div class="rep-hotspot-stats">' + tiles + '</div>'
      + '</section>';
  }

  function renderFloorMatrix(byFloor, floorOrder, ctx) {
    var rows = '';
    var totalAps = 0, totalDir = 0, totalOmni = 0;
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      var bf = proj.buildingFloors[fp.id];
      var buildingName = bf && proj.buildings[bf.buildingId]
        ? proj.buildings[bf.buildingId].name || '—' : '—';
      var dir = floorAps.filter(function (ap) { return !apIsOmniOnly(ap); }).length;
      var omni = floorAps.length - dir;
      totalAps += floorAps.length;
      totalDir += dir;
      totalOmni += omni;
      rows += '<tr>'
        + '<td>' + WD.esc(fp.name || 'Floor plan') + '</td>'
        + '<td>' + WD.esc(buildingName) + '</td>'
        + '<td class="rep-num">' + floorAps.length + '</td>'
        + '<td class="rep-num">' + dir + '</td>'
        + '<td class="rep-num">' + omni + '</td>'
        + '</tr>';
    });
    rows += '<tr class="rep-matrix-total">'
      + '<td colspan="2"><b>Total</b></td>'
      + '<td class="rep-num"><b>' + totalAps + '</b></td>'
      + '<td class="rep-num"><b>' + totalDir + '</b></td>'
      + '<td class="rep-num"><b>' + totalOmni + '</b></td>'
      + '</tr>';
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Floor summary</h2>'
      + '<table class="rep-ap-table">'
      + '<thead><tr><th>Floor</th><th>Building</th><th>APs</th><th>Directional</th><th>Omni</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>'
      + '</section>';
  }

  function renderSignOff() {
    return '<section class="rep-floor-section rep-signoff">'
      + '<h2 class="rep-floor-title">Approval</h2>'
      + '<table class="rep-signoff-table">'
      + '<thead><tr><th></th><th>Name</th><th>Signature</th><th>Date</th></tr></thead>'
      + '<tbody>'
      + '<tr><td class="rep-signoff-role">Prepared by</td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td></tr>'
      + '<tr><td class="rep-signoff-role">Reviewed by</td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td></tr>'
      + '<tr><td class="rep-signoff-role">Approved by</td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td><td class="rep-signoff-line"></td></tr>'
      + '</tbody></table>'
      + '</section>';
  }

  function renderApLocationReport(aps, opts, ctx) {
    var head = opts.cover
      ? ctx.cover(aps.length, ctx.dateStr, 'Access points', opts, ctx)
      : ctx.inlineHeader(aps.length, ctx.dateStr, 'Access points');

    var byFloor = groupApsByFloor(aps, ctx);
    var floorOrder = sortedFloorOrder(byFloor);

    // One map for the whole document, from the same call the legend makes,
    // so a code means the same antenna on every floor and in the legend.
    var antKeys = antennaKeys(collectUsedAntennas(aps, ctx));

    var sections = '';
    var floorIdx = 0;
    floorOrder.forEach(function (fp) {
      var floorAps = byFloor[fp.id];
      if (!floorAps || !floorAps.length) return;
      var sorted = floorAps.slice().sort(function (a, b) {
        return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
      });
      var idx = floorIdx % 5;
      /* Without a map there is nothing above the table, and the table starts
         its own sheet - so "(No floor plan)" was printing as a heading alone
         on an otherwise blank page. Marked here so the print rule can let the
         table follow its heading. */
      var noMap = fp.id === '_none';
      var out = '<section class="rep-floor-section' + (noMap ? ' rep-floor-nomap' : '')
        + '" data-floor-idx="' + idx + '">'
        + '<h2 class="rep-floor-title">' + WD.esc(fp.name || 'Floor plan') + '</h2>';
      if (!noMap) {
        out += renderApLocationOverview(fp, sorted, opts, ctx);
      }
      out += renderApLocationTable(sorted, fp, opts, ctx, antKeys);
      out += '</section>';
      sections += out;
      floorIdx++;
    });

    var toc = opts.cover ? renderLocationTOC(byFloor, floorOrder, opts) : '';
    var summary = renderLocationSummary(aps, ctx);
    var matrix = renderFloorMatrix(byFloor, floorOrder, ctx);
    var audit = opts.nameAudit ? renderApNameAudit(aps, ctx) : '';
    var legend = opts.specs ? renderAntennaLegend(aps, ctx) : '';
    var signoff = opts.signOff !== false ? renderSignOff() : '';
    var foot = renderReportFooter(opts, ctx);

    var compassPage = wantsCompassRef(aps, opts) ? renderCompassReferencePage(opts, ctx) : '';

    return head + toc + summary + matrix + sections + audit + legend + compassPage
      + apNotesPages(aps, opts, ctx) + signoff + foot;
  }

  function renderApLocationOverview(fp, aps, opts, ctx) {
    return renderAntennaOverview(fp, aps, opts, ctx);
  }

  function renderApLocationTable(aps, fp, opts, ctx, antKeys) {
    antKeys = antKeys || {};
    /* The table starts its own sheet, which is right when a map sits above
       it and wrong when nothing does - '(No floor plan)' was printing as a
       heading alone on an otherwise blank page. Inline, because the rule it
       has to beat is a plain stylesheet declaration and this is the one
       place that knows whether there is a map. */
    var breakStyle = (fp && fp.id === '_none')
      ? ' style="page-break-before:auto;break-before:auto"'
      : '';
    var showDir = aps.some(function (ap) { return !apIsOmniOnly(ap); });
    var showCP = opts.showChannelPower !== false;
    var showGrid = showsGridColumn(opts);

    /* This table is rendered per floor and the floor name is already the
       heading directly above it, so a Floor column repeats one value on every
       row. With thirteen columns on a portrait sheet that repetition is not
       free - it was the column whose long generated value collapsed the whole
       table. The same goes for Building when a floor sits in one building.
       Both are dropped when constant and stated once in the caption instead. */
    var tableFloor = fp ? (fp.name || '—') : '—';
    var buildingsSeen = {};
    aps.forEach(function (ap) {
      var b = fp && proj.buildingFloors[fp.id];
      var nm = b && proj.buildings[b.buildingId] ? (proj.buildings[b.buildingId].name || '—') : '—';
      buildingsSeen[nm] = 1;
    });
    var buildingNames = Object.keys(buildingsSeen);
    var oneFloor = true;                       // one fp per table by construction
    var oneBuilding = buildingNames.length <= 1;
    var tableBuilding = buildingNames.length === 1 ? buildingNames[0] : '';

    var rows = '';
    aps.forEach(function (ap) {
      var lbl = apLabel(ap, opts.shortLabels === false ? 'full' : 'short');
      var floorName = fp ? (fp.name || '—') : '—';
      var bf = fp && proj.buildingFloors[fp.id];
      var buildingName = bf && proj.buildings[bf.buildingId]
        ? proj.buildings[bf.buildingId].name || '—' : '—';
      var r = ctx.primaryRadio(ap.id);
      var ant = r && proj.antennas[r.antennaTypeId] ? proj.antennas[r.antennaTypeId] : null;
      var nameIssue = '';
      if (opts.nameAudit) {
        if (!ap.name || !ap.name.trim()) nameIssue = 'Missing name';
        else if (/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(ap.name.trim())) nameIssue = 'MAC address as name';
        else if (/^AP\s*\d*$/i.test(ap.name.trim())) nameIssue = 'Generic name';
      }
      var cpCells = '';
      if (showCP) {
        var radios = proj.radios.filter(function (x) { return x.accessPointId === ap.id; });
        var txParts = [], chParts = [];
        radios.forEach(function (rd) {
          var txp = rd.transmitPower != null ? rd.transmitPower : 15;
          var band = _covBandFromChannel(rd.channelByCenterFrequencyDefinedNarrowChannels);
          var bandLabel = _covBandLabel(band);
          txParts.push(ctx.fmt(txp, 1) + ' dBm');
          var ch = rd.channelByCenterFrequencyDefinedNarrowChannels;
          if (ch && ch.length) {
            chParts.push(freqToChannel(ch[0]) + ' <span class="rep-alt">(' + bandLabel + ')</span>');
          }
        });
        cpCells = '<td class="rep-nowrap">' + (txParts.length ? txParts.join(', ') : '—') + '</td>'
          + '<td class="rep-nowrap">' + (chParts.length ? chParts.join(', ') : '—') + '</td>';
      }
      var dirCells = '';
      if (showDir) {
        var dir = r ? r.antennaDirection : null;
        var tilt = r ? r.antennaTilt : null;
        var height = r ? r.antennaHeight : null;
        var mount = r ? r.antennaMounting : '—';
        var isOmni = apIsOmniOnly(ap);
        var heightStr = ctx.fmtLength(height, opts, 1);
        var azStr = isOmni ? '<span class="rep-alt">Omni</span>'
          : dir == null ? '—'
          : (opts.compass
              ? ctx.fmt(dir, 1) + '° <span class="rep-alt">(' + ctx.compass(dir) + ')</span>'
              : ctx.fmt(dir, 1) + '°');
        var tiltStr = isOmni ? '—' : (tilt == null ? '—' : ctx.fmt(tilt, 1) + '°');
        // Azimuth and tilt genuinely do not apply to an omni, but mount and
        // height do - an omni still hangs at a height off a ceiling, and the
        // installer needs both. These used to be blanked for omni APs purely
        // because they sat in the directional branch.
        dirCells = '<td>' + WD.esc(mount || '—') + '</td>'
          + '<td class="rep-nowrap-print">' + heightStr + '</td>'
          + '<td class="rep-az">' + azStr + '</td>'
          + '<td>' + tiltStr + '</td>'
          /* The code, not the name. A part number is around fifty characters
             and this sheet has eleven columns; see `antennaKeys` for what
             printing it here costs. "Antennas in use" carries the same code
             beside the full name, and the tooltip still has it on screen. */
          + '<td class="rep-az" title="' + WD.escAttr(ant ? ant.name : '') + '">'
          + WD.esc(ant ? (antKeys[ant.id] || ant.name) : '—') + '</td>';
      }
      rows += '<tr' + (nameIssue ? ' class="rep-loc-warn-row"' : '') + '>'
        + '<td class="rep-num">' + WD.esc(lbl) + '</td>'
        + '<td class="rep-name">' + WD.esc(ap.name || '(unnamed)') + '</td>'
        + '<td class="rep-ellip">' + WD.esc(ap.vendor || '—') + '</td>'
        + '<td class="rep-ellip">' + WD.esc(ap.model || '—') + '</td>'
        + (oneFloor ? '' : '<td class="rep-ellip" title="' + WD.escAttr(floorName) + '">'
            + WD.esc(shortFloorLabel(floorName) || '—') + '</td>')
        + (oneBuilding ? '' : '<td class="rep-ellip" title="' + WD.escAttr(buildingName) + '">'
            + WD.esc(buildingName) + '</td>')
        + (showGrid ? '<td class="rep-grid-ref">'
            + WD.esc(gridRefForAp(ap) || '—') + '</td>' : '')
        + cpCells
        + dirCells
        + (opts.nameAudit ? '<td class="rep-loc-warn">' + WD.esc(nameIssue) + '</td>' : '')
        + '</tr>';
    });

    var dirHeaders = showDir
      ? '<th>Mount</th><th>Height</th><th>Azimuth</th><th>Tilt</th><th>Ant.</th>'
      : '';
    var cpHeaders = showCP ? '<th>TX Power</th><th>Channel</th>' : '';
    /* The footer spans the table, so a column added above and not counted here
       leaves the subtotal row short and the last column hanging outside it. */
    var colCount = 4 + (oneFloor ? 0 : 1) + (oneBuilding ? 0 : 1)
      + (showGrid ? 1 : 0)
      + (showCP ? 2 : 0) + (showDir ? 5 : 0) + (opts.nameAudit ? 1 : 0);

    // Relative print widths. These are normalized below so optional columns
    // still consume exactly 100% without making the whole PDF scale down.
    // Weights are roughly the widest value each column has to hold. The AP
    // name is the one column that must never be shortened - the installer
    // copies it onto a label - so it gets the largest share and the columns
    // that can be abbreviated give way to it.
    var printCols = [
      { key: 'num', weight: 9 },
      { key: 'name', weight: 30 },
      { key: 'vendor', weight: 12 },
      { key: 'model', weight: 12 },
    ];
    if (!oneFloor) printCols.push({ key: 'floor', weight: 16 });
    if (!oneBuilding) printCols.push({ key: 'building', weight: 14 });
    // "AA-12" at the very widest, so it needs almost nothing. The weights are
    // normalised below, so adding one takes a proportional slice off the rest
    // rather than pushing the table past the sheet.
    if (showGrid) printCols.push({ key: 'grid', weight: 8 });
    if (showCP) {
      printCols.push({ key: 'tx', weight: 20 });
      printCols.push({ key: 'channel', weight: 22 });
    }
    if (showDir) {
      printCols.push({ key: 'mount', weight: 12 });
      printCols.push({ key: 'height', weight: 17 });
      printCols.push({ key: 'azimuth', weight: 12 });
      printCols.push({ key: 'tilt', weight: 8 });
      // An antenna part number is the longest value in the row and "14 dBm"
      // is not, so the width follows the content rather than the header.
      // It holds a code now, not a part number, so it needs almost nothing -
      // and the AP name and model get the width back.
      printCols.push({ key: 'antenna', weight: 10 });
    }
    if (opts.nameAudit) printCols.push({ key: 'audit', weight: 12 });
    var printWeight = printCols.reduce(function (sum, col) { return sum + col.weight; }, 0);
    var colgroup = '<colgroup>' + printCols.map(function (col) {
      return '<col class="rep-col-' + col.key + '" style="--print-col-w:'
        + (col.weight * 100 / printWeight).toFixed(2) + '%">';
    }).join('') + '</colgroup>';

    // One key per floor. Sharing a single "loc-table" key meant turning one
    // floor's table turned every other floor's too, which is the opposite of
    // what per-page orientation is for.
    var locKey = 'loc-table:' + ((fp && fp.id) || 'all');
    return '<section class="rep-loc-page rep-oriented"' + breakStyle
      + ' data-page-key="' + WD.escAttr(locKey) + '" data-page-kind="table">'
      + orientPickerHtml(locKey, opts)
      + '<table class="rep-ap-table rep-loc-table">'
      + colgroup
      + '<thead><tr>'
      + '<th class="rep-num">#</th><th>AP name</th><th>Vendor</th><th>Model</th>'
      + (oneFloor ? '' : '<th>Floor</th>')
      + (oneBuilding ? '' : '<th>Building</th>')
      + (showGrid ? '<th>Grid</th>' : '')
      + cpHeaders
      + dirHeaders
      + (opts.nameAudit ? '<th>Naming issue</th>' : '')
      + '</tr></thead>'
      + '<tbody>' + rows + '</tbody>'
      + '<tfoot><tr><td colspan="' + colCount + '" class="rep-subtotal">'
      + aps.length + ' access point' + (aps.length === 1 ? '' : 's') + ' on this floor'
      + (oneBuilding && tableBuilding && tableBuilding !== '—'
          ? ' \u00b7 ' + WD.esc(tableBuilding) : '')
      + '</td></tr></tfoot></table></section>';
  }

  function renderApNameAudit(aps, ctx) {
    var issues = [];
    aps.forEach(function (ap) {
      var name = (ap.name || '').trim();
      var issue = '';
      if (!name) issue = 'Missing name';
      else if (/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/i.test(name)) issue = 'MAC address as name';
      else if (/^AP\s*\d*$/i.test(name)) issue = 'Generic name (e.g. "AP1")';
      if (issue) {
        var fp = ctx.floorPlanForAp(ap);
        issues.push({ name: name || '(unnamed)', issue: issue, floor: fp ? fp.name : '—' });
      }
    });
    if (!issues.length) {
      return '<section class="rep-floor-section">'
        + '<h2 class="rep-floor-title">Naming audit</h2>'
        + '<div class="rep-seg-note rep-seg-note--ok">All ' + aps.length + ' APs have proper names — no issues detected.</div>'
        + '</section>';
    }
    var rows = issues.map(function (i) {
      return '<tr><td class="rep-name">' + WD.esc(i.name) + '</td>'
        + '<td>' + WD.esc(i.floor) + '</td>'
        + '<td class="rep-loc-warn">' + WD.esc(i.issue) + '</td></tr>';
    }).join('');
    return '<section class="rep-floor-section">'
      + '<h2 class="rep-floor-title">Naming audit</h2>'
      + '<div class="rep-seg-note">' + issues.length + ' AP' + (issues.length === 1 ? '' : 's') + ' with naming issues found.</div>'
      + '<table class="rep-ap-table"><thead><tr><th>AP name</th><th>Floor</th><th>Issue</th></tr></thead>'
      + '<tbody>' + rows + '</tbody></table>'
      + '</section>';
  }

  var PREVIEW_LOCATION = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#2563eb" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#2563eb"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="72" height="38" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<g fill="#2563eb">'
    +     '<rect x="17" y="40" width="10" height="5" rx="1.5"/>'
    +     '<rect x="33" y="36" width="8" height="5" rx="1.5"/>'
    +     '<rect x="47" y="44" width="12" height="5" rx="1.5"/>'
    +     '<rect x="63" y="38" width="9" height="5" rx="1.5"/>'
    +     '<rect x="25" y="54" width="11" height="5" rx="1.5"/>'
    +     '<rect x="50" y="56" width="10" height="5" rx="1.5"/>'
    +   '</g>'
    +   '<g fill="#fff" font-size="3.5" text-anchor="middle" font-weight="700">'
    +     '<text x="22" y="44.5">42</text><text x="37" y="40.5">07</text>'
    +     '<text x="53" y="48.5">128</text><text x="67.5" y="42.5">15</text>'
    +     '<text x="30.5" y="58.5">03</text><text x="55" y="60.5">91</text>'
    +   '</g>'
    +   '<rect x="10" y="74" width="72" height="3" rx="0.5" fill="#2563eb" opacity="0.55"/>'
    +   '<rect x="10" y="80" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="80" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="80" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="84" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="84" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="84" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="88" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="88" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="88" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="92" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="42" y="92" width="20" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="64" y="92" width="18" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="100" width="72" height="6" rx="1" fill="#eef7ee" stroke="#22c55e" stroke-width="0.3"/>'
    +   '<text x="46" y="104.5" text-anchor="middle" font-size="3" fill="#16a34a">All names OK</text>'
    + '</svg>';

  var PREVIEW_SUMMARY = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0d9488" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0d9488"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<rect x="30" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<rect x="50" y="30" width="17" height="14" rx="1.5" fill="#eef7f6" stroke="#0d9488" stroke-width="0.3"/>'
    +   '<text x="18.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">42</text>'
    +   '<text x="18.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">APs</text>'
    +   '<text x="38.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">4</text>'
    +   '<text x="38.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">Floors</text>'
    +   '<text x="58.5" y="38" text-anchor="middle" font-size="4" font-weight="700" fill="#0d9488">96</text>'
    +   '<text x="58.5" y="42.5" text-anchor="middle" font-size="1.6" fill="#666">Radios</text>'
    +   '<rect x="10" y="50" width="30" height="1.8" rx="0.4" fill="#c8d4e0"/>'
    +   '<rect x="10" y="55" width="10" height="2.5" rx="0.4" fill="#0d9488"/>'
    +   '<rect x="22" y="55" width="60" height="2.5" rx="0.4" fill="#e0efee"/>'
    +   '<rect x="22" y="55" width="42" height="2.5" rx="0.4" fill="#0d9488" opacity="0.6"/>'
    +   '<rect x="10" y="60" width="10" height="2.5" rx="0.4" fill="#5fab4f"/>'
    +   '<rect x="22" y="60" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="22" y="60" width="52" height="2.5" rx="0.4" fill="#5fab4f" opacity="0.6"/>'
    +   '<rect x="10" y="65" width="10" height="2.5" rx="0.4" fill="#8b5cf6"/>'
    +   '<rect x="22" y="65" width="60" height="2.5" rx="0.4" fill="#eee7f9"/>'
    +   '<rect x="22" y="65" width="18" height="2.5" rx="0.4" fill="#8b5cf6" opacity="0.6"/>'
    +   '<rect x="10" y="75" width="34" height="1.8" rx="0.4" fill="#c8d4e0"/>'
    +   '<rect x="10" y="82" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="86" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="90" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="94" width="72" height="2" rx="0.3" fill="#eef7f6"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef7f6"/>'
    + '</svg>';

  var PREVIEW_BOM = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#d97706" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#d97706"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="2.5" rx="0.3" fill="#fce9c8" stroke="#f0b85f" stroke-width="0.3"/>'
    +   '<text x="12" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">VENDOR</text>'
    +   '<text x="36" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">MODEL</text>'
    +   '<text x="72" y="30.2" font-size="1.8" font-weight="700" fill="#d97706">QTY</text>'
    +   '<rect x="10" y="34" width="72" height="4" fill="#ffffff" stroke="#eee" stroke-width="0.2"/>'
    +   '<text x="12" y="36.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="36.8" font-size="1.9" fill="#333">C9166I-E</text>'
    +   '<text x="76" y="36.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">24</text>'
    +   '<rect x="10" y="38" width="72" height="4" fill="#fafafa"/>'
    +   '<text x="12" y="40.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="40.8" font-size="1.9" fill="#333">C9164I</text>'
    +   '<text x="76" y="40.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">12</text>'
    +   '<rect x="10" y="42" width="72" height="4" fill="#ffffff"/>'
    +   '<text x="12" y="44.8" font-size="1.9" fill="#333">Cisco</text>'
    +   '<text x="36" y="44.8" font-size="1.9" fill="#333">C9130AXE</text>'
    +   '<text x="76" y="44.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">6</text>'
    +   '<rect x="10" y="47" width="72" height="0.5" fill="#d97706"/>'
    +   '<text x="12" y="50" font-size="2" font-weight="700" fill="#111">TOTAL ACCESS POINTS</text>'
    +   '<text x="76" y="50" font-size="2.4" font-weight="800" fill="#d97706" text-anchor="end">42</text>'
    +   '<rect x="10" y="58" width="72" height="2.5" rx="0.3" fill="#fce9c8" stroke="#f0b85f" stroke-width="0.3"/>'
    +   '<text x="12" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">ANTENNA</text>'
    +   '<text x="52" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">BAND</text>'
    +   '<text x="72" y="60.2" font-size="1.8" font-weight="700" fill="#d97706">QTY</text>'
    +   '<rect x="10" y="63" width="72" height="4" fill="#ffffff"/>'
    +   '<text x="12" y="65.8" font-size="1.9" fill="#333">AIR-ANT2513P4M</text>'
    +   '<text x="52" y="65.8" font-size="1.9" fill="#333">2.4 GHz</text>'
    +   '<text x="76" y="65.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">18</text>'
    +   '<rect x="10" y="67" width="72" height="4" fill="#fafafa"/>'
    +   '<text x="12" y="69.8" font-size="1.9" fill="#333">AIR-ANT2568VG-N</text>'
    +   '<text x="52" y="69.8" font-size="1.9" fill="#333">5 GHz</text>'
    +   '<text x="76" y="69.8" font-size="1.9" font-weight="700" fill="#333" text-anchor="end">18</text>'
    +   '<rect x="10" y="76" width="45" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="82" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="86" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="90" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#fce9c8"/>'
    + '</svg>';

  var PREVIEW_AIM = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#8b5cf6" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#8b5cf6"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="3" rx="0.3" fill="#efe6fd" stroke="#c9b3ee" stroke-width="0.3"/>'
    +   '<text x="12" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">AP</text>'
    +   '<text x="27" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">FLOOR</text>'
    +   '<text x="46" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">AZ°</text>'
    +   '<text x="58" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">TILT</text>'
    +   '<text x="70" y="30.5" font-size="1.7" font-weight="700" fill="#8b5cf6">HT</text>'
    +   '<rect x="10" y="33" width="72" height="3" fill="#ffffff"/>'
    +   '<text x="12" y="35.5" font-size="1.8" fill="#333">AP-01</text>'
    +   '<text x="27" y="35.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="35.5" font-size="1.8" fill="#333">137° SE</text>'
    +   '<text x="58" y="35.5" font-size="1.8" fill="#333">10°</text>'
    +   '<text x="70" y="35.5" font-size="1.8" fill="#333">3.0 m</text>'
    +   '<rect x="10" y="36" width="72" height="3" fill="#faf7fe"/>'
    +   '<text x="12" y="38.5" font-size="1.8" fill="#333">AP-02</text>'
    +   '<text x="27" y="38.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="38.5" font-size="1.8" fill="#333">225° SW</text>'
    +   '<text x="58" y="38.5" font-size="1.8" fill="#333">5°</text>'
    +   '<text x="70" y="38.5" font-size="1.8" fill="#333">2.8 m</text>'
    +   '<rect x="10" y="39" width="72" height="3" fill="#ffffff"/>'
    +   '<text x="12" y="41.5" font-size="1.8" fill="#333">AP-03</text>'
    +   '<text x="27" y="41.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="41.5" font-size="1.8" fill="#333">315° NW</text>'
    +   '<text x="58" y="41.5" font-size="1.8" fill="#333">0°</text>'
    +   '<text x="70" y="41.5" font-size="1.8" fill="#333">3.2 m</text>'
    +   '<rect x="10" y="42" width="72" height="3" fill="#faf7fe"/>'
    +   '<text x="12" y="44.5" font-size="1.8" fill="#333">AP-04</text>'
    +   '<text x="27" y="44.5" font-size="1.8" fill="#333">F1</text>'
    +   '<text x="46" y="44.5" font-size="1.8" fill="#333">045° NE</text>'
    +   '<text x="58" y="44.5" font-size="1.8" fill="#333">10°</text>'
    +   '<text x="70" y="44.5" font-size="1.8" fill="#333">3.0 m</text>'
    +   '<rect x="10" y="48" width="72" height="12" fill="#f8f4ff" stroke="#c9b3ee" stroke-width="0.3"/>'
    +   '<circle cx="20" cy="54" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 20 54 L 25 51" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="35" cy="55" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 35 55 L 32 59" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="52" cy="53" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 52 53 L 56 50" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<circle cx="68" cy="56" r="1.5" fill="#8b5cf6"/>'
    +   '<path d="M 68 56 L 63 54" stroke="#8b5cf6" stroke-width="0.6"/>'
    +   '<rect x="10" y="66" width="72" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="70" width="55" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="74" width="72" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="78" width="60" height="2.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#efe6fd"/>'
    + '</svg>';

  var PREVIEW_AUDIT = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#5fab4f" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#5fab4f"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="26" width="34" height="6" rx="0.6" fill="#eef6ec" stroke="#5fab4f" stroke-width="0.3"/>'
    +   '<text x="27" y="30" text-anchor="middle" font-size="2.2" font-weight="700" fill="#5fab4f">BEFORE</text>'
    +   '<rect x="48" y="26" width="34" height="6" rx="0.6" fill="#fef3e3" stroke="#d97706" stroke-width="0.3"/>'
    +   '<text x="65" y="30" text-anchor="middle" font-size="2.2" font-weight="700" fill="#d97706">AFTER</text>'
    +   '<rect x="10" y="34" width="72" height="2.5" fill="#eef6ec"/>'
    +   '<text x="12" y="36.2" font-size="1.7" fill="#333">🟢 42 APs</text>'
    +   '<text x="50" y="36.2" font-size="1.7" fill="#333">🟠 44 APs (+2)</text>'
    +   '<rect x="10" y="37" width="72" height="2.5" fill="#fdf9f4"/>'
    +   '<text x="12" y="39.2" font-size="1.7" fill="#333">🟢 96 radios</text>'
    +   '<text x="50" y="39.2" font-size="1.7" fill="#333">🟠 104 radios (+8)</text>'
    +   '<rect x="10" y="40" width="72" height="2.5" fill="#eef6ec"/>'
    +   '<text x="12" y="42.2" font-size="1.7" fill="#333">🟢 4 floors</text>'
    +   '<text x="50" y="42.2" font-size="1.7" fill="#333">🟠 4 floors</text>'
    +   '<rect x="10" y="46" width="30" height="1.5" rx="0.3" fill="#c8d4e0"/>'
    +   '<rect x="10" y="50" width="14" height="2.5" rx="0.6" fill="#5fab4f"/>'
    +   '<text x="27" y="52.2" font-size="1.5" fill="#333">Removed 2 APs on Floor 1</text>'
    +   '<rect x="10" y="54" width="14" height="2.5" rx="0.6" fill="#d97706"/>'
    +   '<text x="27" y="56.2" font-size="1.5" fill="#333">Added 4 APs on Floor 3</text>'
    +   '<rect x="10" y="58" width="14" height="2.5" rx="0.6" fill="#1e77ac"/>'
    +   '<text x="27" y="60.2" font-size="1.5" fill="#333">Moved AP-07 (2.1m → 3.2m)</text>'
    +   '<rect x="10" y="62" width="14" height="2.5" rx="0.6" fill="#1e77ac"/>'
    +   '<text x="27" y="64.2" font-size="1.5" fill="#333">Re-aimed AP-12 (90° → 135°)</text>'
    +   '<rect x="10" y="70" width="72" height="16" fill="#f5faf3" stroke="#c9e0c3" stroke-width="0.3"/>'
    +   '<line x1="46" y1="70" x2="46" y2="86" stroke="#c9e0c3" stroke-width="0.3"/>'
    +   '<circle cx="20" cy="76" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="35" cy="80" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="30" cy="83" r="1.4" fill="#dc2626" opacity="0.6"/>'
    +   '<circle cx="55" cy="76" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="70" cy="80" r="1.4" fill="#5fab4f"/>'
    +   '<circle cx="60" cy="82" r="1.4" fill="#d97706"/>'
    +   '<circle cx="75" cy="84" r="1.4" fill="#d97706"/>'
    +   '<rect x="10" y="90" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="94" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="98" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef6ec"/>'
    + '</svg>';

  var PREVIEW_COVERAGE = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#0d9488" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#0d9488"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="52" rx="1" fill="#fafbfc" stroke="#c5d5e5" stroke-width="0.3"/>'
    +   '<circle cx="24" cy="42" r="9" fill="#0d9488" opacity="0.18"/>'
    +   '<circle cx="24" cy="42" r="6" fill="#0d9488" opacity="0.28"/>'
    +   '<circle cx="24" cy="42" r="3" fill="#0d9488" opacity="0.4"/>'
    +   '<circle cx="24" cy="42" r="1.4" fill="#0d9488"/>'
    +   '<circle cx="46" cy="52" r="10" fill="#8b5cf6" opacity="0.18"/>'
    +   '<circle cx="46" cy="52" r="7" fill="#8b5cf6" opacity="0.28"/>'
    +   '<circle cx="46" cy="52" r="3.5" fill="#8b5cf6" opacity="0.4"/>'
    +   '<circle cx="46" cy="52" r="1.4" fill="#8b5cf6"/>'
    +   '<circle cx="68" cy="44" r="9" fill="#0668D9" opacity="0.18"/>'
    +   '<circle cx="68" cy="44" r="6" fill="#0668D9" opacity="0.28"/>'
    +   '<circle cx="68" cy="44" r="3" fill="#0668D9" opacity="0.4"/>'
    +   '<circle cx="68" cy="44" r="1.4" fill="#0668D9"/>'
    +   '<circle cx="30" cy="66" r="9" fill="#d97706" opacity="0.18"/>'
    +   '<circle cx="30" cy="66" r="6" fill="#d97706" opacity="0.28"/>'
    +   '<circle cx="30" cy="66" r="3" fill="#d97706" opacity="0.4"/>'
    +   '<circle cx="30" cy="66" r="1.4" fill="#d97706"/>'
    +   '<circle cx="60" cy="70" r="9" fill="#5fab4f" opacity="0.18"/>'
    +   '<circle cx="60" cy="70" r="6" fill="#5fab4f" opacity="0.28"/>'
    +   '<circle cx="60" cy="70" r="3" fill="#5fab4f" opacity="0.4"/>'
    +   '<circle cx="60" cy="70" r="1.4" fill="#5fab4f"/>'
    +   '<rect x="10" y="84" width="72" height="8" rx="0.6" fill="#f5fbf9" stroke="#c0e0dc" stroke-width="0.3"/>'
    +   '<text x="12" y="87.5" font-size="1.8" font-weight="700" fill="#0d9488">LEGEND</text>'
    +   '<circle cx="18" cy="90" r="1.2" fill="#0d9488"/>'
    +   '<text x="21" y="90.5" font-size="1.5" fill="#333">Strong</text>'
    +   '<circle cx="35" cy="90" r="1.2" fill="#0668D9" opacity="0.4"/>'
    +   '<text x="38" y="90.5" font-size="1.5" fill="#333">Good</text>'
    +   '<circle cx="50" cy="90" r="1.2" fill="#d97706" opacity="0.28"/>'
    +   '<text x="53" y="90.5" font-size="1.5" fill="#333">Fair</text>'
    +   '<circle cx="65" cy="90" r="1.2" fill="#dc2626" opacity="0.18"/>'
    +   '<text x="68" y="90.5" font-size="1.5" fill="#333">Weak</text>'
    +   '<rect x="10" y="96" width="72" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="100" width="55" height="1.5" rx="0.3" fill="#e5e5e7"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#f5fbf9"/>'
    + '</svg>';

  var PREVIEW_HOTSPOT = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#1e77ac" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#1e77ac"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="30" width="72" height="36" rx="2" fill="#eef4fb" stroke="#c5d5e5" stroke-width="0.5"/>'
    +   '<path d="M 18 60 L 22 54 L 30 50 L 38 46 L 46 42 L 54 44 L 62 48 L 70 46 L 76 42 L 74 36 L 68 34"'
    +     ' fill="none" stroke="#1e77ac" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" opacity="0.75"/>'
    +   '<circle cx="22" cy="54" r="1.6" fill="#5d5b60"/>'
    +   '<circle cx="38" cy="46" r="1.6" fill="#5fab4f"/>'
    +   '<circle cx="54" cy="44" r="1.6" fill="#d97706"/>'
    +   '<circle cx="70" cy="46" r="1.6" fill="#dc2626"/>'
    +   '<circle cx="30" cy="50" r="1.6" fill="#5fab4f"/>'
    +   '<rect x="10" y="72" width="10" height="2.5" rx="1" fill="#5d5b60"/>'
    +   '<rect x="22" y="72" width="60" height="2.5" rx="0.4" fill="#eef2f5"/>'
    +   '<rect x="10" y="77" width="10" height="2.5" rx="1" fill="#5fab4f"/>'
    +   '<rect x="22" y="77" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="10" y="82" width="10" height="2.5" rx="1" fill="#d97706"/>'
    +   '<rect x="22" y="82" width="60" height="2.5" rx="0.4" fill="#fef3e3"/>'
    +   '<rect x="10" y="87" width="10" height="2.5" rx="1" fill="#dc2626"/>'
    +   '<rect x="22" y="87" width="60" height="2.5" rx="0.4" fill="#fef2f2"/>'
    +   '<rect x="10" y="92" width="10" height="2.5" rx="1" fill="#5fab4f"/>'
    +   '<rect x="22" y="92" width="60" height="2.5" rx="0.4" fill="#e9f4e6"/>'
    +   '<rect x="10" y="97" width="10" height="2.5" rx="1" fill="#d97706"/>'
    +   '<rect x="22" y="97" width="60" height="2.5" rx="0.4" fill="#fef3e3"/>'
    +   '<rect x="10" y="104" width="45" height="4" rx="1" fill="#eef4fb"/>'
    + '</svg>';

  var PREVIEW_PREDICTIVE = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#9F1B58" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="50" height="4" rx="1" fill="#9F1B58"/>'
    +   '<rect x="10" y="20" width="70" height="2" rx="1" fill="#c8d4e0"/>'
    +   '<rect x="10" y="28" width="72" height="70" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<line x1="46" y1="28" x2="46" y2="98" stroke="#d5dee7" stroke-width="0.5" stroke-dasharray="1.5,1.5"/>'
    +   '<line x1="10" y1="63" x2="82" y2="63" stroke="#d5dee7" stroke-width="0.5" stroke-dasharray="1.5,1.5"/>'
    +   '<text x="14" y="34" font-size="3" font-weight="700" fill="#9F1B58">A1</text>'
    +   '<text x="76" y="34" font-size="3" font-weight="700" fill="#9F1B58" text-anchor="end">B1</text>'
    +   '<text x="14" y="94" font-size="3" font-weight="700" fill="#9F1B58">A2</text>'
    +   '<text x="76" y="94" font-size="3" font-weight="700" fill="#9F1B58" text-anchor="end">B2</text>'
    +   '<g fill="#9F1B58">'
    +     '<circle cx="22" cy="42" r="1.8"/><circle cx="38" cy="48" r="1.8"/>'
    +     '<circle cx="58" cy="40" r="1.8"/><circle cx="72" cy="50" r="1.8"/>'
    +     '<circle cx="24" cy="76" r="1.8"/><circle cx="44" cy="82" r="1.8"/>'
    +     '<circle cx="64" cy="78" r="1.8"/>'
    +   '</g>'
    +   '<path d="M58 40 L60.5 34.5 L63 40 Z" fill="#d97706"/>'
    +   '<path d="M22 42 L24.5 36.5 L27 42 Z" fill="#d97706"/>'
    +   '<rect x="10" y="104" width="72" height="6" rx="1" fill="#f7e7ee"/>'
    + '</svg>';

  var PREVIEW_PLACEMENT = ''
    + '<svg viewBox="0 0 92 116" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    +   '<rect x="4" y="4" width="84" height="108" rx="3" fill="#ffffff" stroke="#9F1B58" stroke-width="0.8"/>'
    +   '<rect x="10" y="12" width="34" height="6" rx="1" fill="#9F1B58"/>'
    +   '<rect x="10" y="21" width="72" height="1.5" rx="0.7" fill="#9F1B58" opacity="0.5"/>'
    +   '<rect x="10" y="28" width="72" height="76" rx="2" fill="#eef2f7" stroke="#d5dee7" stroke-width="0.5"/>'
    +   '<g fill="#9F1B58">'
    +     '<rect x="20" y="40" width="3" height="3" rx="0.8"/><rect x="44" y="36" width="3" height="3" rx="0.8"/>'
    +     '<rect x="66" y="44" width="3" height="3" rx="0.8"/><rect x="26" y="66" width="3" height="3" rx="0.8"/>'
    +     '<rect x="50" y="72" width="3" height="3" rx="0.8"/><rect x="70" y="86" width="3" height="3" rx="0.8"/>'
    +   '</g>'
    +   '<g fill="#ffffff" stroke="#9F1B58" stroke-width="0.4">'
    +     '<rect x="16" y="45" width="11" height="5" rx="1"/><rect x="40" y="41" width="11" height="5" rx="1"/>'
    +     '<rect x="62" y="49" width="11" height="5" rx="1"/><rect x="22" y="71" width="11" height="5" rx="1"/>'
    +     '<rect x="46" y="77" width="11" height="5" rx="1"/><rect x="66" y="91" width="11" height="5" rx="1"/>'
    +   '</g>'
    +   '<g fill="#9F1B58" font-size="3" text-anchor="middle">'
    +     '<text x="21.5" y="48.8">101</text><text x="45.5" y="44.8">102</text>'
    +     '<text x="67.5" y="52.8">103</text><text x="27.5" y="74.8">104</text>'
    +     '<text x="51.5" y="80.8">105</text><text x="71.5" y="94.8">106</text>'
    +   '</g>'
    + '</svg>';

  var REPORTS = {
    placement: {
      id: 'placement',
      label: 'AP Placement Map',
      description: 'The plan, every AP where it actually goes, and its number. Large floors can be split into lettered sections with a key plan and match lines.',
      readBy: 'Whoever mounts the hardware, and whoever signs off the design',
      output: 'One page per floor, or several if you turn on section splitting',
      docName: 'AP Placement Map',
      coverBrand: 'Report \u00b7 AP Placement Map',
      status: 'ready',
      preview: PREVIEW_PLACEMENT,
      bestFor: 'The sheet that goes in the folder or on the wall \u2014 handing an installer where the APs go, dropping a clean placement map into a design package, or handing exact placement to low-voltage installers before construction.',
      sections: [
        { icon: '\ud83d\uddfa\ufe0f', title: 'One page per floor',
          description: 'The full floor plan with every AP marked at its real position and labelled. The floor number is printed large at the top so a loose sheet still says where it belongs.' },
        { icon: '\ud83c\udff7\ufe0f', title: 'Labels that stay readable',
          description: 'Labels move around their AP to avoid each other, and step further out with a leader line when a floor is dense. No AP is ever left unlabelled.' },
      ],
      sidebar: [
        { id: 'clientName', type: 'text', label: 'Client / company', default: '',
          placeholder: 'e.g. Acme Corp' },
        { id: 'preparedBy', type: 'text', label: 'Prepared by', default: '',
          placeholder: 'e.g. Jane Smith' },
        { id: 'projectRef', type: 'text', label: 'Project reference', default: '',
          placeholder: 'e.g. PO-2026-0042' },
        { id: 'revision', type: 'text', label: 'Revision', default: '',
          placeholder: 'e.g. v2.0' },
        { id: 'nameKey', type: 'select', label: 'AP label reference pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the plan shows numbers' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing each marker number against the full AP name, so the installer can write the label correctly.' },
        { id: 'shortLabels', label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "\u2026AP42"), show just the "42". Turn off to print the full AP name.' },
        { id: 'summary', label: 'Summary strip', default: false,
          description: 'AP count, floor-plan count, and the directional/omni split, above the floor plans.' },
        { id: 'labelModel', label: 'Add the AP model to each label', default: false,
          description: 'A second line under the name, e.g. "AP-515". Useful when a floor mixes hardware.' },
        { id: 'labelRadio', label: 'Add channel & TX power to each label', default: false,
          description: 'A second line under the name, e.g. "ch 36 \u00b7 15 dBm".' },
        { id: 'labelHeight', label: 'Add mount height to each label', default: false,
          description: 'A second line under the name, e.g. "3.0 m".' },
        { id: 'labelGrid', label: 'Add the column grid reference to each label', default: false,
          description: 'A second line under the name, e.g. "C-4" — the nearest column-grid intersection, which is the coordinate system the crew on site already uses. Set the grid up first with the button below; until at least one floor is calibrated this adds nothing.' },
        { id: '_gridRefSetup', type: 'gridref-button', label: 'Set up column grid…',
          description: 'Click two intersections you can name on each floor plan. Nothing is read off the drawing. This is the building’s own column grid — not the section grid above, which only decides how a large floor is split across pages.' },
        { id: 'showCones', label: 'Show aiming arrows on directional APs', default: false,
          description: 'Off by default \u2014 this map is about where the APs go. The Antenna Aim Sheet covers aiming.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'All AP types are on by default so nothing is missing from the map.' },
        { id: 'inclOmni', label: 'Include omni APs', default: true,
          description: 'All AP types are on by default so nothing is missing from the map.' },
        { id: 'confidential', label: 'Confidentiality notice in footer', default: false,
          description: 'Adds "CONFIDENTIAL" to the report footer.' },
        { id: 'segmented', label: 'Split large floor plans into zoomed sections', default: false,
          description: 'Off by default \u2014 one page per floor is the point of this report. Turn on for a very large plan where one page cannot hold readable labels.' },
        { id: 'segGranularity', type: 'select', label: 'Section size on large floors', default: 'standard',
          options: [
            { value: 'fine',     label: 'More detail — smaller sections' },
            { value: 'standard', label: 'Standard' },
            { value: 'coarse',   label: 'Fewer pages — larger sections' },
            { value: 'coarsest', label: 'Fewest pages — largest sections' },
          ],
          description: 'How much ground one section sheet covers. Construction asked for fewer pages with more around each AP; this is that dial. Remembered for you, not per report.' },
        { id: '_gridConfig', type: 'grid-button', label: 'Configure grid\u2026',
          description: 'Only used when the split above is on.' },
        { id: 'compassRef', type: 'select', label: 'Compass reference page', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto \u2014 when directional APs exist' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A one-page compass rose with practical guidance for aligning directional antennas to the azimuth values in this report.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderPlacementReport,
      postRender: function (host, opts) {
        applyPageOrientation(host, opts);
        sizePlacementPlansForPrint(host, opts);
        if (opts.segmented) applyAntennaSegmentCrop.apply(null, arguments);
      },
    },
    summary: {
      id: 'summary',
      label: 'Site Summary Sheet',
      description: 'One page of totals — APs, floors, buildings, radios, common models, antennas.',
      readBy: 'Clients, and anyone who will not open a floor plan',
      output: 'One page, whole project',
      docName: 'Site Summary',
      coverBrand: 'Report · Site Summary',
      status: 'ready',
      preview: PREVIEW_SUMMARY,
      bestFor: 'Client-facing project overview, kickoff decks, quick site-scoping snapshot.',
      noApFilter: true,
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, total AP count, floor count, your logo, date.' },
        { icon: '📊', title: 'Project at a glance',
          description: 'APs, radios, floor plans, buildings, antenna types, survey/measurement counts.' },
        { icon: '🏢', title: 'Per-floor breakdown',
          description: 'AP count and canvas dimensions per floor, grouped by building when available.' },
        { icon: '📶', title: 'Radio band breakdown',
          description: 'Horizontal bar chart showing the 2.4 / 5 / 6 GHz radio split across the whole project.' },
        { icon: '🔝', title: 'Top AP models',
          description: 'Up to 10 most-used AP models with quantities — quick check of hardware mix.' },
        { icon: '📡', title: 'Antennas in use',
          description: 'Every antenna model referenced with band, coupling, gain, and beam width.' },
      ],
      sidebar: [
        { id: 'perFloor',      label: 'Per-floor breakdown table', default: true,
          description: 'Table listing each floor plan with its AP count and canvas dimensions.' },
        { id: 'bandBreakdown', label: 'Radio band breakdown', default: true,
          description: 'Bar chart of 2.4/5/6 GHz radio distribution.' },
        { id: 'topModels',     label: 'Top AP models', default: true,
          description: 'Ranked list of AP models by quantity.' },
        { id: 'antennas',      label: 'Antennas in use', default: true,
          description: 'Legend section describing every antenna model in this project.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderSummaryReport,
    },
    interference: {
      id: 'interference',
      label: 'Interference / Rogue Devices',
      description: 'Phone hotspots, MiFi and wide-channel rogue Wi-Fi found in the passive survey, scored by severity.',
      readBy: 'Whoever has to go and find them',
      output: 'A scored list, plus per-floor detection maps if you want them',
      docName: 'Interference',
      coverBrand: 'Report · Interference',
      status: 'ready',
      preview: PREVIEW_HOTSPOT,
      bestFor: 'Security walk-arounds, "someone\'s wide-channel hotspot is stomping the network" incidents, baseline handoffs.',
      noApFilter: true,
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, interferer count, your logo, survey date.' },
        { icon: '📊', title: 'Summary strip',
          description: 'Total, high-severity count, and per-category counts (iPhone / Android / Carrier / Wide-channel).' },
        { icon: '🗺️', title: 'Per-floor detection map',
          description: 'Floor plan with the surveyor walk path drawn on top, colored by the worst severity detected on that floor.' },
        { icon: '📋', title: 'Full device table',
          description: 'SSID, BSSID, band, channel width, severity, security, and which floors each device was seen on.' },
        { icon: '📖', title: 'Methodology',
          description: 'How each SSID was classified, how severity is scored, and what was intentionally excluded.' },
      ],
      sidebar: [
        { id: 'catIphone',  label: 'Include iPhone / iPad', default: true,
          description: 'SSIDs matching "iPhone", "iPad", or "’s iPhone" (iOS Personal Hotspot defaults).' },
        { id: 'catAndroid', label: 'Include Android', default: true,
          description: 'AndroidAP_XXXX, AndroidShare_XXXX, DIRECT-xx-AndroidAP, Samsung Galaxy device names.' },
        { id: 'catCarrier', label: 'Include Carrier / MiFi hotspots', default: true,
          description: 'HotspotXXXX, WiFi Hotspot NNNN, MiFi / Jetpack (Verizon and T-Mobile hotspot defaults).' },
        { id: 'catAtt',     label: 'Include AT&T (phone or gateway)', default: false,
          description: 'ATT[6-10 char] pattern — used by BOTH AT&T phone hotspots and AT&T home gateways, so off by default.' },
        { id: 'catWide',    label: 'Include wide-channel Wi-Fi (any SSID)', default: true,
          description: 'Any BSSID on a 40MHz+ channel, even if its SSID doesn\'t match a phone-naming pattern. This is what catches "someone plugged in a wide-channel rogue AP or hotspot."' },
        { id: 'overview',   label: 'Include per-floor detection map', default: true,
          description: 'Floor plan with the surveyor walk path drawn on top, colored by severity, one panel per floor.' },
        { id: 'autocrop',   label: 'Auto-crop empty margins around each floor plan', default: true,
          description: 'Ekahau sometimes saves a floor plan on an oversized canvas with lots of whitespace. When on, each overlay zooms to the actual drawn content (plus the walk path, so nothing is cut off).' },
        { id: 'channel',    label: 'Show channel numbers', default: false,
          description: 'Adds a Channel(s) column to the device table. Off by default — most readers just need the band and width.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderInterferenceReport,
      postRender: applyHotspotAutocrop,
    },
    bom: {
      id: 'bom',
      label: 'Bill of Materials',
      description: 'AP, antenna and mount quantities for procurement — per model, for the project and per floor.',
      readBy: 'Whoever raises the purchase order',
      output: 'Model counts for the project and per floor, plus antennas and mounts',
      docName: 'Bill of Materials',
      coverBrand: 'Report · Bill of Materials',
      status: 'ready',
      preview: PREVIEW_BOM,
      bestFor: 'Procurement teams sizing purchase orders and cost estimates.',
      noApFilter: true,
      sections: [
        { icon: '📦', title: 'AP quantities',
          description: 'Grouped by vendor and model, with subtotals and a grand total. An AP with no model recorded is counted as "Unknown" rather than dropped.' },
        { icon: '🏢', title: 'Access points per floor',
          description: 'The same model counts again, a floor at a time, with a per-floor total — you order for the site and install a floor at a time.' },
        { icon: '📡', title: 'Antenna quantities',
          description: 'Grouped by antenna model, with band, coupling type (integrated/external), and gain.' },
        { icon: '🔩', title: 'Mount types',
          description: 'One per access point, from the mounting recorded against its radio. Mounts with nothing recorded are counted under "Not recorded".' },
        { icon: '📝', title: 'Procurement notes',
          description: 'What this BOM does and does not cover — cable runs, PoE injectors and switch ports still need manual work.' },
      ],
      sidebar: [
        { id: 'externalOnly', label: 'Show external antennas only', default: false,
          description: 'Filter to procurement-relevant antennas — hides built-in antennas that ship with the AP. Handy for orders like "AP + external antenna kit".' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderBomReport,
    },
    aim: {
      id: 'aim',
      label: 'Antenna Aim Sheet',
      description: 'One flat table — every directional AP with azimuth, tilt, mount height and floor.',
      readBy: 'Whoever is physically aiming the antennas',
      output: 'One table plus a compass reference page, sized for a clipboard',
      docName: 'Antenna Aim Sheet',
      coverBrand: 'Report · Antenna Aim',
      status: 'ready',
      preview: PREVIEW_AIM,
      bestFor: 'On-site installers who want one printed page they can carry between mount locations.',
      sections: [
        { icon: '📋', title: 'Single-page table',
          description: 'Every directional AP as one row: AP name, floor, azimuth (with compass), tilt, mount height (meters + feet), antenna model.' },
        { icon: '🎯', title: 'Per-floor mini-map',
          description: 'Below the table, a compact floor plan per floor with AP dots and short direction ticks — a quick sanity check before climbing a ladder.' },
        { icon: '✅', title: 'Sign-off row',
          description: 'Installer initials + date column on the right side of each row, so the printed sheet doubles as an as-built.' },
      ],
      sidebar: [
        { id: 'overview', label: 'Per-floor mini-maps', default: true,
          description: 'Compact floor plan per floor below the table, with AP dots and direction ticks — sanity check before climbing a ladder.' },
        { id: 'signOff',  label: 'Sign-off columns (initials + date)', default: true,
          description: 'Right side of each row keeps two blank cells so the printed sheet doubles as an as-built.' },
        { id: 'gridRef', type: 'check', label: 'Column grid reference', default: false,
          description: 'Adds a Grid column giving each AP its nearest column-grid intersection, such as C-4 — the coordinate system the crew on site already uses. Set the grid up first with the button below; until at least one floor is calibrated this does nothing.' },
        { id: '_gridRefSetup', type: 'gridref-button', label: 'Set up column grid…',
          description: 'Click two intersections you can name on each floor plan. Nothing is read off the drawing.' },
        { id: 'units', type: 'select', label: 'Measurement units', default: 'feet',
          options: [
            { value: 'feet',   label: 'Feet' },
            { value: 'meters', label: 'Metres' },
          ],
          description: 'Heights and distances are written in this unit. An .esx stores everything in metres, so this is a display choice; it does not change the project.' },
        { id: 'compass',  label: 'Show compass headings alongside azimuth', default: true,
          description: 'Azimuth shown as "137° (SE)" instead of just "137°".' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Standard case — APs whose antennas have a specific azimuth.' },
        { id: 'inclOmni',        label: 'Include omni APs', default: false,
          description: 'Adds omni-only APs with an "omni" placeholder in the azimuth cell. Off by default — this sheet is for aiming.' },
        { id: 'shortLabels',     label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers and in the # column. Turn off to always show the full AP name — safer when APs are named by MAC or free-form text.' },
        { id: 'compassRef', type: 'select', label: 'Compass reference page', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when directional APs exist' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A one-page compass rose with practical guidance for aligning directional antennas to the azimuth values in this report.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderAimReport,
    },
    audit: {
      id: 'audit',
      label: 'Change / Audit Report',
      description: 'What moved, what was added and what was removed between two .esx files.',
      readBy: 'Whoever has to show the build matches the design',
      output: 'A diff, with the changes listed per floor',
      docName: 'Change Report',
      coverBrand: 'Report · Change / Audit',
      status: 'ready',
      preview: PREVIEW_AUDIT,
      bestFor: 'Post-remediation write-ups, redesign hand-offs, and "prove we did what we said" audits.',
      noApFilter: true,
      sections: [
        { icon: '🔍', title: 'Compare stats',
          description: 'Before-and-after side-by-side: access point, radio and floor counts, with the change on each.' },
        { icon: '➕', title: 'Added / removed / changed',
          description: 'One row per access point with the name, floor, and everything that changed on it — position, azimuth, tilt, height, mount, antenna, model or name.' },
        { icon: '🗺️', title: 'Overlay diff',
          description: 'Per-floor overlay on the current plan: added, changed with a line back to where it was, removed, and unchanged.' },
      ],
      sidebar: [
        { id: '_baseline', type: 'baseline-button',
          label: 'Earlier project to compare against',
          description: 'The "before" file. The project open in this tool is the "after". Neither file is written to.' },
        { id: 'moveThreshold', type: 'select', label: 'Count as moved when it moved', default: '0.5',
          options: [
            { value: '0',   label: 'Any distance at all' },
            { value: '0.5', label: '0.5 m (1.6 ft) or more' },
            { value: '1',   label: '1 m (3.3 ft) or more' },
            { value: '3',   label: '3 m (9.8 ft) or more' },
          ],
          description: 'Below this, a difference in position is treated as a nudge in the design rather than a decision to put the access point somewhere else. Stated on the report itself, so whoever reads it knows what was left out.' },
        { id: 'overlay', label: 'Per-floor overlay drawings', default: true,
          description: 'The current floor plan with the changes marked on it: added, changed, where a moved AP used to be, and removed. Off makes this a tables-only document.' },
        { id: 'units', type: 'select', label: 'Measurement units', default: 'feet',
          options: [
            { value: 'feet',   label: 'Feet' },
            { value: 'meters', label: 'Metres' },
          ],
          description: 'Distances and heights are written in this unit. An .esx stores everything in metres, so this is a display choice; it does not change either project.' },
        { id: 'cover', label: 'Cover page', default: true,
          description: 'A title page naming both files. Off puts the same information in a header strip instead.' },
        { id: 'confidential', label: 'Confidentiality notice in footer', default: false,
          description: 'Adds "CONFIDENTIAL" to the report footer.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'never',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. Defaults to Never here, because a change report is usually the document that gets handed over and site notes are often your own working annotations. Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderAuditReport,
      postRender: function (host, opts) { applyPageOrientation(host, opts); },
    },
    coverage: {
      id: 'coverage',
      label: 'Coverage Cell Boundary',
      description: 'Each AP\'s coverage cell drawn on the plan, so the AP count explains itself.',
      readBy: 'Clients and budget holders',
      output: 'One overlay per floor',
      docName: 'Coverage Cell Boundary',
      coverBrand: 'Report · Coverage Cell',
      status: 'ready',
      preview: PREVIEW_COVERAGE,
      bestFor: 'Client presentations, capacity conversations, "why do we need N APs on this floor" justifications.',
      sections: [
        { icon: '🗺️', title: 'Cell diagram per floor',
          description: 'Each AP gets a translucent circle sized by its estimated primary-service radius (−67 dBm). Overlapping cells show handoff zones.' },
        { icon: '📶', title: 'Signal strength bands',
          description: 'Optional concentric rings per AP: strong (< −55 dBm) / fair (< −75) / weak (< −80). Weak-signal gaps highlighted.' },
        { icon: '📊', title: 'Cell sizing table + methodology',
          description: 'Per-AP TX power, antenna gain, EIRP, and −67 / −80 dBm radii. Plus a plain-English methodology section covering the path-loss model and its limits.' },
      ],
      sidebar: [
        { id: 'primaryCells', label: 'Primary coverage cell (−67 dBm)', default: true,
          description: 'Filled translucent circle around each AP at the standard "reliable voice/video" threshold. Overlaps show handoff zones.' },
        { id: 'signalRings', label: 'Signal-strength rings', default: false,
          description: 'Adds outlined concentric rings at strong / fair / weak thresholds. Off by default because it gets busy fast on dense floors.' },
        { id: 'bandColors', label: 'Color-code by band', default: true,
          description: '2.4 GHz blue · 5 GHz green · 6 GHz purple. Off means everything uses the same neutral blue.' },
        { id: 'showApLabels', label: 'AP number labels', default: true,
          description: 'Numbered dot at each AP center — matches the row number in the "Cell sizing per AP" table.' },
        { id: 'legend', label: 'Cell sizing table', default: true,
          description: 'One row per AP with its TX power, antenna gain, EIRP, and computed −67 / −80 dBm radii.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'Directional antennas are drawn as circles (radius uses their full EIRP). Angular beam shaping is not modelled — see methodology.' },
        { id: 'inclOmni', label: 'Include omni APs', default: true,
          description: 'Omni APs produce broadly circular cells and are usually the primary content of this report.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderCoverageReport,
    },
    location: {
      id: 'location',
      label: 'AP Installation',
      description: 'The full installer package: maps, plus per-floor tables with mount height, azimuth and tilt.',
      readBy: 'The crew doing the work, and whoever verifies it afterwards',
      output: 'Maps plus tables, so several pages per floor',
      docName: 'AP Installation',
      coverBrand: 'Report · AP Installation',
      status: 'ready',
      preview: PREVIEW_LOCATION,
      bestFor: 'Installer handoff with placement maps, directional aiming detail, and AP naming verification — handles omni, directional, and mixed buildings in one report.',
      sections: [
        { icon: '📄', title: 'Cover page',
          description: 'Site name, client, preparer, project ref, AP + floor-plan counts, your logo, date.' },
        { icon: '📑', title: 'Table of contents & project overview',
          description: 'Section listing, key stats, and a floor-by-floor AP summary matrix.' },
        { icon: '🗺️', title: 'Scalable floor plan per floor',
          description: 'Every AP plotted with a labeled rounded marker and directional arrows. Large floors split into zoomed sections so labels stay legible.' },
        { icon: '📋', title: 'Per-floor AP table',
          description: 'AP names, vendor, model, floor, building, TX power, channel. When directional APs exist, adds mount, height, azimuth, tilt, and antenna columns.' },
        { icon: '📡', title: 'Antenna specs reference',
          description: 'Gain, beam width, and AP usage count for each antenna model.' },
        { icon: '🔍', title: 'Naming audit',
          description: 'Highlights APs with missing names, MAC addresses used as names, or generic "AP1"-style names that need renaming.' },
        { icon: '🧭', title: 'Compass reference',
          description: 'Compass rose with practical guidance for aligning directional antennas to the azimuth values in the report — internal vs. external antennas, compass use, and floor plan orientation.' },
        { icon: '✍️', title: 'Sign-off block',
          description: 'Prepared / Reviewed / Approved signature lines for formal handoff.' },
      ],
      sidebar: [
        { id: 'clientName', type: 'text', label: 'Client / company', default: '',
          placeholder: 'e.g. Acme Corp' },
        { id: 'preparedBy', type: 'text', label: 'Prepared by', default: '',
          placeholder: 'e.g. Jane Smith' },
        { id: 'projectRef', type: 'text', label: 'Project reference', default: '',
          placeholder: 'e.g. PO-2026-0042' },
        { id: 'revision', type: 'text', label: 'Revision', default: '',
          placeholder: 'e.g. Rev A' },
        { id: 'showChannelPower', label: 'Show channel & TX power columns', default: true,
          description: 'Adds per-radio TX power and channel columns to the AP table.' },
        { id: 'gridRef', type: 'check', label: 'Column grid reference', default: false,
          description: 'Adds a Grid column giving each AP its nearest column-grid intersection, such as C-4 — the coordinate system the crew on site already uses. Set the grid up first with the button below; until at least one floor is calibrated this does nothing.' },
        { id: '_gridRefSetup', type: 'gridref-button', label: 'Set up column grid…',
          description: 'Click two intersections you can name on each floor plan. Nothing is read off the drawing.' },
        { id: 'signOff', label: 'Include sign-off / approval block', default: true,
          description: 'Adds a Prepared / Reviewed / Approved signature table at the end.' },
        { id: 'confidential', label: 'Confidentiality notice in footer', default: false,
          description: 'Adds "CONFIDENTIAL" to the report footer.' },
        { id: 'shortLabels', label: 'Short number labels on the plan', default: true,
          description: 'When your AP names end with an "AP" designator (e.g. "…AP42"), show just the "42" on markers. Turn off to always show the full AP name.' },
        { id: 'specs',    label: 'Antenna specs reference', default: true,
          description: 'Final table listing every antenna model with gain and beam width.',
          disabledWhen: function (p) { return !hasAnyBeamWidth(p); },
          disabledReason: function () { return 'No beam-width data in this project (all-integrated antennas).'; } },
        { id: 'units', type: 'select', label: 'Measurement units', default: 'feet',
          options: [
            { value: 'feet',   label: 'Feet' },
            { value: 'meters', label: 'Metres' },
          ],
          description: 'Heights and distances are written in this unit. An .esx stores everything in metres, so this is a display choice; it does not change the project.' },
        { id: 'compass',  label: 'Show compass headings alongside azimuth', default: true,
          description: 'Azimuth shown as "137° (SE)" instead of just "137°".' },
        { id: 'nameAudit', label: 'Include naming audit', default: false,
          description: 'Adds a column flagging APs with missing, MAC-address, or generic names. Also adds a summary section at the end.' },
        { id: 'segmented', label: 'Split large floor plans into zoomed sections', default: true,
          description: 'Breaks each floor plan into a grid of zoomed-in sections so AP labels stay readable at any scale.' },
        { id: 'segGranularity', type: 'select', label: 'Section size on large floors', default: 'standard',
          options: [
            { value: 'fine',     label: 'More detail — smaller sections' },
            { value: 'standard', label: 'Standard' },
            { value: 'coarse',   label: 'Fewer pages — larger sections' },
            { value: 'coarsest', label: 'Fewest pages — largest sections' },
          ],
          description: 'How much ground one section sheet covers. Construction asked for fewer pages with more around each AP; this is that dial. Remembered for you, not per report.' },
        { id: '_gridConfig', type: 'grid-button', label: 'Configure grid…',
          description: 'Choose how many rows and columns the segmented grid uses, with a live preview on your actual floor plan.' },
        { id: 'inclDirectional', label: 'Include directional APs', default: true,
          description: 'All AP types are on by default so every AP appears on the installation report.' },
        { id: 'inclOmni', label: 'Include omni APs', default: true,
          description: 'All AP types are on by default so every AP appears on the installation report.' },
        { id: 'compassRef', type: 'select', label: 'Compass reference page', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when directional APs exist' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A one-page compass rose with practical guidance for aligning directional antennas to the azimuth values in this report.' },
        { id: 'apNotes', type: 'select', label: 'AP notes pages', default: 'auto',
          options: [
            { value: 'auto',   label: 'Auto — when the project has notes' },
            { value: 'always', label: 'Always include' },
            { value: 'never',  label: 'Never include' },
          ],
          description: 'A page per floor listing the notes recorded against each AP on site. '
            + 'Independent of every other option here: site notes are often your own working '
            + 'annotations — mounting caveats, access problems — and are not always meant for a '
            + 'client or an installer, so set this to Never on a document you are handing over. '
            + 'Text only; a note with a photo is listed and marked, but the image is not printed.' },
      ],
      render: renderApLocationReport,
      postRender: applyAntennaSegmentCrop,
    },
  };

  renderTemplateGallery();
})();
