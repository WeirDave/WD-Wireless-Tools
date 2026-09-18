/* ============================================================
   WD Wireless Tools - wd-dev-actions.js

   Every dev-toolbar action is registered here, and this is the only
   file that has to be edited to add one. WaxFrame keeps the same
   convention for the same reason: a toolbar whose handlers are
   scattered across the app grows dead buttons, and a button that
   calls nothing is worse than no button.

   Loaded after wd-dev.js, which owns `WD.Dev.register`.
   ============================================================ */
(function () {
  'use strict';

  var WD = window.WD;
  if (!WD || !WD.Dev) return;

  function esc(s) { return WD.esc(s); }

  /* ── Cloud Manager: realign renamed projects ──────────────────
     The first action, and the reason the toolbar exists now.

     Roughly ninety pairs read "cloud newer" because the cloud
     projects were renamed and the local copies were not. Ekahau
     stamps `history.modifiedAt` on a rename, that stamp is what
     Cloud Manager compares, and so a batch of identical designs
     all started claiming there was work to pull.

     The server side is `tools/cloud_realign.py`. It proves each
     pair identical by unzipping both copies and comparing them -
     not by the name heuristic, which its own docstring says does
     not prove content - and skips anything that genuinely differs.
     ──────────────────────────────────────────────────────────── */

  function call(dryRun) {
    return WD.api('cloud/realign_renamed', { dryRun: dryRun });
  }

  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : many);
  }

  function fileLine(f, extra) {
    return '<li class="wd-dev-file">' +
      '<span class="wd-dev-file-name">' + esc(f.name || '(unnamed)') + '</span>' +
      (f.folder ? '<span class="wd-dev-file-folder">' + esc(f.folder) + '</span>' : '') +
      (extra || '') +
    '</li>';
  }

  function renderReport(r, isPreview) {
    if (!r) return '<p class="wd-dev-error">No answer from the server.</p>';

    var aligned = r.aligned || [];
    var skipped = r.skipped || [];
    var failed = r.failed || [];
    var parts = [];

    parts.push('<p class="wd-dev-headline">' +
      (isPreview
        ? 'Examined ' + plural(r.examined || 0, 'pair', 'pairs') + '. ' +
          'Nothing has been changed.'
        : 'Examined ' + plural(r.examined || 0, 'pair', 'pairs') + '.') +
      '</p>');

    parts.push('<ul class="wd-dev-tally">' +
      '<li><strong>' + aligned.length + '</strong> ' +
        (isPreview ? 'would be aligned' : 'aligned') + '</li>' +
      '<li><strong>' + skipped.length + '</strong> skipped</li>' +
      '<li><strong>' + failed.length + '</strong> failed</li>' +
    '</ul>');

    if (aligned.length) {
      parts.push('<h5 class="wd-dev-section">' +
        (isPreview ? 'Would align' : 'Aligned') + '</h5><ul class="wd-dev-files">' +
        aligned.map(function (f) {
          var acts = (f.actions || []).map(function (a) {
            return '<li>' + esc(a) + '</li>';
          }).join('');
          return fileLine(f,
            (acts ? '<ul class="wd-dev-file-actions">' + acts + '</ul>' : '') +
            (f.newDate ? '<span class="wd-dev-file-date">New date: ' +
              esc(f.newDate) + '</span>' : '') +
            (f.backup ? '<span class="wd-dev-file-backup">Backed up to ' +
              esc(f.backup) + '</span>' : '') +
            (f.warning ? '<span class="wd-dev-file-warn">' +
              esc(f.warning) + '</span>' : ''));
        }).join('') + '</ul>');
    }

    if (skipped.length) {
      parts.push('<h5 class="wd-dev-section">Skipped, and why</h5>' +
        '<ul class="wd-dev-files">' + skipped.map(function (f) {
          return fileLine(f, '<span class="wd-dev-file-reason">' +
            esc(f.reason || 'No reason given.') + '</span>');
        }).join('') + '</ul>');
    }

    if (failed.length) {
      parts.push('<h5 class="wd-dev-section">Failed</h5>' +
        '<ul class="wd-dev-files">' + failed.map(function (f) {
          return fileLine(f, '<span class="wd-dev-file-error">' +
            esc(f.error || 'Unknown error.') + '</span>');
        }).join('') + '</ul>');
    }

    if (!aligned.length && !skipped.length && !failed.length) {
      parts.push('<p class="wd-dev-headline">Nothing to do - no pair is ' +
        'reporting the cloud as newer.</p>');
    }

    return parts.join('');
  }

  WD.Dev.register({
    id: 'cloud-realign-renamed',
    group: 'Cloud Manager',
    label: 'Realign projects the cloud only looks newer than',

    summary: 'Renaming a cloud project moves its modified date, so a local ' +
             'copy that never changed starts reporting "cloud newer". This ' +
             'settles those pairs without pulling anything.',

    detail: 'Each candidate is proved identical by downloading the cloud ' +
            'copy and comparing every document and every floor plan image ' +
            'against the local file - not by the names, which cannot prove ' +
            'content. Pairs that genuinely differ are skipped and listed. ' +
            'For the rest it corrects the project name stored inside the ' +
            '.esx and sets its modified date to the cloud project’s own, ' +
            'backing up each file it rewrites into your backups folder ' +
            'first. Nothing is uploaded and nothing is deleted from the ' +
            'cloud; it is safe to run again if it is interrupted.',

    previewLabel: 'Preview - changes nothing',
    runLabel: 'Align them for real',
    runTitle: 'Rewrite the files the preview listed. Each one is backed up first.',
    confirm: 'This rewrites the project name and modified date inside the ' +
             'local .esx files the preview listed, backing each one up first. ' +
             'Nothing is uploaded or deleted. Continue?',

    preview: function () { return call(true); },
    run: function () { return call(false); },
    render: renderReport
  });

  /* Exposed for the tests, which render the real report and read it back
     rather than asserting that this file contains the word "aligned". */
  WD.Dev._renderRealignReport = renderReport;
})();
