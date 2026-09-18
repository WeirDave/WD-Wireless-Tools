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

  /* ── Housekeeping: what our own tooling has left lying around ──
     His question, and it was a fair one: "how do I know, once we've
     done all the work, when to be able to clean stuff up? Because
     now I feel like we've got files fucking everywhere across the
     board, and I don't know if you clean up your own work or not."

     The answer was no, we do not, reliably. So this is the surface
     that makes it answerable in five seconds instead of a script he
     would have to be walked through.

     The server side is `tools/housekeeping.py`. Everything about
     what is safe to remove is decided there and re-decided at sweep
     time; this file renders the answer and sends back a list of
     paths to act on.
     ──────────────────────────────────────────────────────────── */

  /* The paths the preview offered, kept so the live run sends exactly what
     he was shown. Cleared at the start of every preview, so a stale list
     from an earlier look can never be submitted. */
  var _sweepable = [];

  function mb(bytes) {
    if (!bytes) return '0 MB';
    if (bytes < 1048576) return (bytes / 1024).toFixed(0) + ' KB';
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(2) + ' GB';
  }

  function idle(hours) {
    if (hours == null) return '';
    if (hours < 1) return 'under an hour idle';
    if (hours < 48) return Math.round(hours) + 'h idle';
    return Math.round(hours / 24) + ' days idle';
  }

  function entryLine(e, showWhy) {
    var bits = '<span class="wd-dev-file-folder">' + esc(mb(e.sizeBytes)) +
               ' · ' + esc(idle(e.idleHours)) + '</span>';
    if (e.dataFindings) {
      bits += '<span class="wd-dev-file-warn">Carries workplace data — ' +
              esc(plural(e.dataFindings, 'signal', 'signals')) + '</span>';
    }
    if (showWhy && e.liveReason) {
      bits += '<span class="wd-dev-file-reason">' + esc(e.liveReason) + '</span>';
    }
    if (showWhy && e.note) {
      bits += '<span class="wd-dev-file-reason">' + esc(e.note) + '</span>';
    }
    return '<li class="wd-dev-file">' +
      '<span class="wd-dev-file-name">' + esc(e.name || e.path) + '</span>' +
      bits + '</li>';
  }

  function capped(entries, limit, render) {
    var shown = entries.slice(0, limit).map(render).join('');
    if (entries.length > limit) {
      shown += '<li class="wd-dev-file"><span class="wd-dev-file-folder">' +
        '… and ' + (entries.length - limit) + ' more of the same' +
        '</span></li>';
    }
    return shown;
  }

  function renderSurvey(r) {
    if (!r) return '<p class="wd-dev-error">No answer from the server.</p>';
    var groups = r.groups || [];
    var t = r.totals || {};
    var parts = [];

    /* The data question first, because it is the one that matters to him.
       It is not about disk space - it is that copies of his site data
       should not be scattered around. Counts only, never the values. */
    if (t.withData) {
      parts.push('<p class="wd-dev-headline wd-dev-error">' +
        '<strong>' + plural(t.withData, 'item carries', 'items carry') +
        ' workplace data</strong> — ' +
        plural(t.dataFindings || 0, 'signal', 'signals') + ' in total. ' +
        'The values are deliberately not shown.' +
        (r.dataScanComplete === false
          ? ' The scan hit its time budget, so treat this as a floor.' : '') +
        '</p>');
    } else {
      parts.push('<p class="wd-dev-headline">No workplace data found in ' +
        'anything listed here.' +
        (r.dataScanComplete === false
          ? ' The scan hit its time budget, so that is a partial answer.' : '') +
        '</p>');
    }

    parts.push('<ul class="wd-dev-tally">' +
      '<li><strong>' + (t.count || 0) + '</strong> items</li>' +
      '<li><strong>' + esc(mb(t.sizeBytes)) + '</strong> total</li>' +
      '<li><strong>' + (t.deletable || 0) + '</strong> safe to remove ' +
        '(' + esc(mb(t.deletableBytes)) + ')</li>' +
      '<li><strong>' + (t.live || 0) + '</strong> in use, left alone</li>' +
    '</ul>');

    groups.forEach(function (g) {
      var gt = g.totals || {};
      parts.push('<h5 class="wd-dev-section">' + esc(g.title) + ' — ' +
        gt.count + ', ' + esc(mb(gt.sizeBytes)) + '</h5>');
      var del = g.entries.filter(function (e) { return e.deletable; });
      var keep = g.entries.filter(function (e) { return !e.deletable; });
      if (del.length) {
        parts.push('<ul class="wd-dev-files">' +
          capped(del, 8, function (e) { return entryLine(e, false); }) +
        '</ul>');
      }
      if (keep.length) {
        parts.push('<p class="wd-dev-action-detail">Kept:</p>' +
          '<ul class="wd-dev-files">' +
          capped(keep, 6, function (e) { return entryLine(e, true); }) +
        '</ul>');
      }
    });

    var procs = r.processes || [];
    if (procs.length) {
      parts.push('<h5 class="wd-dev-section">Processes still running</h5>' +
        '<ul class="wd-dev-files">' + procs.map(function (p) {
          return '<li class="wd-dev-file">' +
            '<span class="wd-dev-file-name">' + esc(p.name) +
            ' (pid ' + esc(p.pid) + ')</span>' +
            '<span class="wd-dev-file-reason">' + esc(p.why) + '</span>' +
          '</li>';
        }).join('') + '</ul>');
    }

    if (!t.count && !procs.length) {
      parts.push('<p class="wd-dev-headline">Nothing to clean up.</p>');
    }
    return parts.join('');
  }

  function renderSweep(r) {
    if (!r) return '<p class="wd-dev-error">No answer from the server.</p>';
    var removed = r.removed || [], skipped = r.skipped || [], failed = r.failed || [];
    var parts = ['<p class="wd-dev-headline">Removed ' +
      plural(removed.length, 'item', 'items') + ', freeing ' +
      esc(mb(r.freedBytes)) + '.</p>'];

    parts.push('<ul class="wd-dev-tally">' +
      '<li><strong>' + removed.length + '</strong> removed</li>' +
      '<li><strong>' + skipped.length + '</strong> skipped</li>' +
      '<li><strong>' + failed.length + '</strong> failed</li></ul>');

    if (skipped.length) {
      parts.push('<h5 class="wd-dev-section">Skipped, and why</h5>' +
        '<ul class="wd-dev-files">' + capped(skipped, 10, function (e) {
          return '<li class="wd-dev-file">' +
            '<span class="wd-dev-file-name">' + esc(e.name || e.path) + '</span>' +
            '<span class="wd-dev-file-reason">' +
              esc(e.reason || 'No reason given.') + '</span></li>';
        }) + '</ul>');
    }
    if (failed.length) {
      parts.push('<h5 class="wd-dev-section">Failed</h5>' +
        '<ul class="wd-dev-files">' + capped(failed, 10, function (e) {
          return '<li class="wd-dev-file">' +
            '<span class="wd-dev-file-name">' + esc(e.name || e.path) + '</span>' +
            '<span class="wd-dev-file-error">' +
              esc(e.error || 'Unknown error.') + '</span></li>';
        }) + '</ul>');
    }
    return parts.join('');
  }

  WD.Dev.register({
    id: 'housekeeping',
    group: 'Housekeeping',
    label: 'Find what our tooling has left lying around',

    summary: 'Inventories worktrees, scratch folders, leaked temp ' +
             'directories, browser drivers and downloaded release ZIPs, ' +
             'newest first, and says which are safe to remove.',

    detail: 'Anything a running session is using is marked and never ' +
            'offered — a registered worktree, or something changed in ' +
            'the last few minutes. Items carrying your workplace data are ' +
            'counted and reported first; the values are never shown. It ' +
            'only ever removes things our own tooling created: nothing in ' +
            'Dropbox, nothing in your project folders, nothing in ' +
            '~/.wd_wireless_tools, and nothing from your Desktop — ' +
            'those are listed so you can deal with them yourself. The ' +
            'list is worked out again at delete time rather than trusted.',

    previewLabel: 'Look - changes nothing',
    runLabel: 'Delete what it listed',
    runTitle: 'Remove the items the preview marked safe. Re-checked first.',
    confirm: 'This permanently deletes the items the preview marked safe to ' +
             'remove. Nothing of yours, nothing in use, and nothing from ' +
             'your Desktop. Continue?',

    preview: function () {
      _sweepable = [];
      return WD.api('dev/housekeeping_survey', {}).then(function (r) {
        if (r && r.groups) {
          r.groups.forEach(function (g) {
            (g.entries || []).forEach(function (e) {
              if (e.deletable) _sweepable.push(e.path);
            });
          });
        }
        return r;
      });
    },

    run: function () {
      return WD.api('dev/housekeeping_sweep', { paths: _sweepable });
    },

    render: function (result, isPreview) {
      return isPreview ? renderSurvey(result) : renderSweep(result);
    }
  });

  /* Both renderers, plus the pending list, for the tests that run them
     against real payloads rather than reading this file. */
  WD.Dev._renderHousekeepingSurvey = renderSurvey;
  WD.Dev._renderHousekeepingSweep = renderSweep;
  WD.Dev._housekeepingPending = function () { return _sweepable.slice(); };
})();
