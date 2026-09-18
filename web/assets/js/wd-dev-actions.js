/* ============================================================
   WD Wireless Tools - wd-dev-actions.js

   **Every dev-toolbar button's markup and handler lives here**, which
   is WaxFrame's convention for `wf-debug.js`, adopted for the reason
   WaxFrame gives: a toolbar whose handlers are scattered across the
   app grows dead buttons, and a button that calls nothing is worse
   than no button.

   The buttons are written as markup - emoji, short label, `title` -
   and wired declaratively with `data-action="call"` and
   `data-fn="WD.Dev.something"`, resolved by the dispatcher in
   wd-dev.js. That is WaxFrame's `data-fn="WF_DEBUG.bundleForScout"`
   shape, one for one.

   Two groups, separated by `|` the way WaxFrame separates its Deep
   Dive / Bundle / Clear cluster from its Force Truncate / Refresh
   Pricing one. The Cloud group uses a hover flyout, which is what
   WaxFrame does with its five Scenes buttons.

   Adding an action: one button in `toolbarInnerHtml`, one handler
   below it. An action that writes gets two buttons - a preview and a
   live one rendered `disabled` - because the live one must not be
   pressable until its own preview has come back clean.
   ============================================================ */
(function () {
  'use strict';

  var WD = window.WD;
  if (!WD || !WD.Dev) return;
  var Dev = WD.Dev;

  function esc(s) { return WD.esc(s); }

  function plural(n, one, many) {
    return n + ' ' + (n === 1 ? one : many);
  }

  /* ── the strip ───────────────────────────────────────────────
     WaxFrame writes this into index.html; there is no single page
     here, so it is a string. Same elements, same attributes. */
  Dev.toolbarInnerHtml = function () {
    return '' +
      '<div class="dev-flyout">' +
        '<button class="dev-flyout-trigger" type="button" ' +
                'title="Cloud Manager maintenance — hover for menu">' +
          '☁ Cloud</button>' +
        '<div class="dev-flyout-panel">' +
          '<button id="wdRealignPreviewBtn" type="button" ' +
                  'data-action="call" data-fn="WD.Dev.realignPreview" ' +
                  'title="Work out which pairs read ‘cloud newer’ only because ' +
                  'the cloud project was renamed, and report what would change. ' +
                  'Downloads each cloud copy to prove the designs are identical. ' +
                  'Writes nothing.">' +
            '🔍 Preview Realign</button>' +
          '<button id="wdRealignRunBtn" type="button" disabled ' +
                  'data-action="call" data-fn="WD.Dev.realignRun" ' +
                  'title="Preview first. Rewrites the project name and modified date ' +
                  'inside the local .esx files the preview listed, backing each one ' +
                  'up first. Nothing is uploaded or deleted.">' +
            '✅ Align For Real</button>' +
        '</div>' +
      '</div>' +
      '<span class="dev-toolbar-sep">|</span>' +
      '<button id="wdHousekeepLookBtn" type="button" ' +
              'data-action="call" data-fn="WD.Dev.housekeepLook" ' +
              'title="Inventory what our tooling has left behind — worktrees, ' +
              'scratch folders, leaked temp directories, drivers, downloaded ' +
              'release ZIPs. Marks anything in use, counts anything carrying ' +
              'workplace data, and writes nothing.">' +
        '🔎 Look</button>' +
      '<button id="wdHousekeepSweepBtn" type="button" disabled ' +
              'data-action="call" data-fn="WD.Dev.housekeepSweep" ' +
              'title="Look first. Deletes the items marked safe to remove. Never ' +
              'touches Dropbox, your project folders, ~/.wd_wireless_tools, your ' +
              'Desktop, or anything a session is using.">' +
        '🗑 Delete Listed</button>' +
      '<span class="dev-toolbar-sep">|</span>' +
      '<button id="wdDevAboutBtn" type="button" ' +
              'data-action="call" data-fn="WD.Dev.showWhereIAm" ' +
              'title="What dev mode is, how it was turned on, and how to leave it.">' +
        'ℹ About Dev</button>';
  };

  /* Re-assert every button's armed state whenever the toolbar mounts.
     A page navigation rebuilds the strip, and a live button must come
     back disabled - the preview it was armed by belongs to the page
     that has gone. */
  Dev.onMounted = function () {
    Dev.setEnabled('wdRealignRunBtn', false);
    Dev.setEnabled('wdHousekeepSweepBtn', false);
  };

  function busy(id, on, label) {
    var btn = document.getElementById(id);
    if (!btn) return;
    btn.disabled = !!on;
    if (on) {
      btn.dataset.wasLabel = btn.textContent;
      btn.textContent = label || 'Working…';
    } else if (btn.dataset.wasLabel) {
      btn.textContent = btn.dataset.wasLabel;
    }
  }

  function fail(title, e) {
    Dev.showResult(title,
      '<p class="dev-result-error">' + esc((e && e.message) || e) + '</p>');
  }

  /* ── Cloud: realign renamed projects ─────────────────────────
     Roughly ninety pairs read "cloud newer" because the cloud
     projects were renamed and the local copies were not. The server
     side is `tools/cloud_realign.py`; it proves each pair identical
     by comparing contents, not names. */

  function realignCall(dryRun) {
    return WD.api('cloud/realign_renamed', { dryRun: dryRun });
  }

  function realignReport(r, isPreview) {
    if (!r) return '<p class="dev-result-error">No answer from the server.</p>';
    var aligned = r.aligned || [], skipped = r.skipped || [], failed = r.failed || [];
    var out = [];

    out.push('<p class="dev-result-lead">' +
      'Examined ' + plural(r.examined || 0, 'pair', 'pairs') + '.' +
      (isPreview ? ' Nothing has been changed.' : '') + '</p>');

    out.push('<ul class="dev-result-tally">' +
      '<li><strong>' + aligned.length + '</strong> ' +
        (isPreview ? 'would be aligned' : 'aligned') + '</li>' +
      '<li><strong>' + skipped.length + '</strong> skipped</li>' +
      '<li><strong>' + failed.length + '</strong> failed</li></ul>');

    if (aligned.length) {
      out.push('<h4 class="dev-result-section">' +
        (isPreview ? 'Would align' : 'Aligned') + '</h4><ul class="dev-result-list">' +
        aligned.map(function (f) {
          return '<li><span class="dev-result-name">' + esc(f.name) + '</span>' +
            (f.folder ? '<span class="dev-result-sub">' + esc(f.folder) + '</span>' : '') +
            ((f.actions || []).length
              ? '<ul class="dev-result-acts">' + f.actions.map(function (a) {
                  return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' : '') +
            (f.newDate ? '<span class="dev-result-sub">New date: ' +
              esc(f.newDate) + '</span>' : '') +
            (f.backup ? '<span class="dev-result-sub">Backed up to ' +
              esc(f.backup) + '</span>' : '') +
            (f.warning ? '<span class="dev-result-warn">' +
              esc(f.warning) + '</span>' : '') +
          '</li>';
        }).join('') + '</ul>');
    }
    if (skipped.length) {
      out.push('<h4 class="dev-result-section">Skipped, and why</h4>' +
        '<ul class="dev-result-list">' + skipped.map(function (f) {
          return '<li><span class="dev-result-name">' + esc(f.name) + '</span>' +
            '<span class="dev-result-sub">' +
              esc(f.reason || 'No reason given.') + '</span></li>';
        }).join('') + '</ul>');
    }
    if (failed.length) {
      out.push('<h4 class="dev-result-section">Failed</h4>' +
        '<ul class="dev-result-list">' + failed.map(function (f) {
          return '<li><span class="dev-result-name">' + esc(f.name) + '</span>' +
            '<span class="dev-result-error">' +
              esc(f.error || 'Unknown error.') + '</span></li>';
        }).join('') + '</ul>');
    }
    if (!aligned.length && !skipped.length && !failed.length) {
      out.push('<p class="dev-result-lead">Nothing to do — no pair is ' +
        'reporting the cloud as newer.</p>');
    }
    return out.join('');
  }

  Dev.realignPreview = function () {
    busy('wdRealignPreviewBtn', true);
    Dev.setEnabled('wdRealignRunBtn', false);
    return realignCall(true).then(function (r) {
      busy('wdRealignPreviewBtn', false);
      if (r && r.error) { fail('Realign — preview', r.error); return; }
      Dev.showResult('Realign — preview', realignReport(r, true));
      // The only path that arms the live button, and only on a clean
      // preview. A failed one leaves it dead, which is what we want on a
      // bad day.
      Dev.setEnabled('wdRealignRunBtn', true);
    }).catch(function (e) {
      busy('wdRealignPreviewBtn', false);
      fail('Realign — preview', e);
    });
  };

  Dev.realignRun = function () {
    if (!window.confirm(
        'This rewrites the project name and modified date inside the local ' +
        '.esx files the preview listed, backing each one up first. ' +
        'Nothing is uploaded or deleted. Continue?')) return;
    busy('wdRealignRunBtn', true);
    return realignCall(false).then(function (r) {
      busy('wdRealignRunBtn', false);
      Dev.setEnabled('wdRealignRunBtn', false);
      if (r && r.error) { fail('Realign', r.error); return; }
      Dev.showResult('Realign — done', realignReport(r, false));
    }).catch(function (e) {
      busy('wdRealignRunBtn', false);
      Dev.setEnabled('wdRealignRunBtn', false);
      fail('Realign', e);
    });
  };

  /* ── Housekeeping: what our tooling left behind ───────────────
     "how do I know, once we've done all the work, when to be able to
     clean stuff up?" The server side is `tools/housekeeping.py`. */

  /* The paths the look offered, so the sweep sends exactly what he was
     shown. Cleared at the start of every look, so a stale list from an
     earlier one can never be submitted. */
  var sweepable = [];

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

  function line(e, showWhy) {
    var bits = '<span class="dev-result-sub">' + esc(mb(e.sizeBytes)) +
               ' · ' + esc(idle(e.idleHours)) + '</span>';
    if (e.dataFindings) {
      bits += '<span class="dev-result-warn">Carries workplace data — ' +
              esc(plural(e.dataFindings, 'signal', 'signals')) + '</span>';
    }
    if (showWhy && e.liveReason) {
      bits += '<span class="dev-result-sub">' + esc(e.liveReason) + '</span>';
    }
    if (showWhy && e.note) {
      bits += '<span class="dev-result-sub">' + esc(e.note) + '</span>';
    }
    return '<li><span class="dev-result-name">' + esc(e.name || e.path) +
           '</span>' + bits + '</li>';
  }

  function capped(entries, limit, render) {
    var shown = entries.slice(0, limit).map(render).join('');
    if (entries.length > limit) {
      shown += '<li><span class="dev-result-sub">… and ' +
        (entries.length - limit) + ' more of the same</span></li>';
    }
    return shown;
  }

  function surveyReport(r) {
    if (!r) return '<p class="dev-result-error">No answer from the server.</p>';
    var t = r.totals || {};
    var out = [];

    /* The data question first: it is not about disk space, it is that
       copies of his site data should not be scattered around. Counts
       only, never the values. */
    if (t.withData) {
      out.push('<p class="dev-result-lead dev-result-error">' +
        '<strong>' + plural(t.withData, 'item carries', 'items carry') +
        ' workplace data</strong> — ' +
        plural(t.dataFindings || 0, 'signal', 'signals') + ' in total. ' +
        'The values are deliberately not shown.' +
        (r.dataScanComplete === false
          ? ' The scan hit its time budget, so treat this as a floor.' : '') +
        '</p>');
    } else {
      out.push('<p class="dev-result-lead">No workplace data found in ' +
        'anything listed here.' +
        (r.dataScanComplete === false
          ? ' The scan hit its time budget, so that is a partial answer.' : '') +
        '</p>');
    }

    out.push('<ul class="dev-result-tally">' +
      '<li><strong>' + (t.count || 0) + '</strong> items</li>' +
      '<li><strong>' + esc(mb(t.sizeBytes)) + '</strong> total</li>' +
      '<li><strong>' + (t.deletable || 0) + '</strong> safe to remove (' +
        esc(mb(t.deletableBytes)) + ')</li>' +
      '<li><strong>' + (t.live || 0) + '</strong> in use, left alone</li></ul>');

    (r.groups || []).forEach(function (g) {
      var gt = g.totals || {};
      out.push('<h4 class="dev-result-section">' + esc(g.title) + ' — ' +
        gt.count + ', ' + esc(mb(gt.sizeBytes)) + '</h4>');
      var del = g.entries.filter(function (e) { return e.deletable; });
      var keep = g.entries.filter(function (e) { return !e.deletable; });
      if (del.length) {
        out.push('<ul class="dev-result-list">' +
          capped(del, 8, function (e) { return line(e, false); }) + '</ul>');
      }
      if (keep.length) {
        out.push('<p class="dev-result-sub">Kept:</p><ul class="dev-result-list">' +
          capped(keep, 6, function (e) { return line(e, true); }) + '</ul>');
      }
    });

    var procs = r.processes || [];
    if (procs.length) {
      out.push('<h4 class="dev-result-section">Processes still running</h4>' +
        '<ul class="dev-result-list">' + procs.map(function (p) {
          return '<li><span class="dev-result-name">' + esc(p.name) +
            ' (pid ' + esc(p.pid) + ')</span><span class="dev-result-sub">' +
            esc(p.why) + '</span></li>';
        }).join('') + '</ul>');
    }
    if (!t.count && !procs.length) {
      out.push('<p class="dev-result-lead">Nothing to clean up.</p>');
    }
    return out.join('');
  }

  function sweepReport(r) {
    if (!r) return '<p class="dev-result-error">No answer from the server.</p>';
    var removed = r.removed || [], skipped = r.skipped || [], failed = r.failed || [];
    var out = ['<p class="dev-result-lead">Removed ' +
      plural(removed.length, 'item', 'items') + ', freeing ' +
      esc(mb(r.freedBytes)) + '.</p>'];

    out.push('<ul class="dev-result-tally">' +
      '<li><strong>' + removed.length + '</strong> removed</li>' +
      '<li><strong>' + skipped.length + '</strong> skipped</li>' +
      '<li><strong>' + failed.length + '</strong> failed</li></ul>');

    if (skipped.length) {
      out.push('<h4 class="dev-result-section">Skipped, and why</h4>' +
        '<ul class="dev-result-list">' + capped(skipped, 10, function (e) {
          return '<li><span class="dev-result-name">' +
            esc(e.name || e.path) + '</span><span class="dev-result-sub">' +
            esc(e.reason || 'No reason given.') + '</span></li>';
        }) + '</ul>');
    }
    if (failed.length) {
      out.push('<h4 class="dev-result-section">Failed</h4>' +
        '<ul class="dev-result-list">' + capped(failed, 10, function (e) {
          return '<li><span class="dev-result-name">' +
            esc(e.name || e.path) + '</span><span class="dev-result-error">' +
            esc(e.error || 'Unknown error.') + '</span></li>';
        }) + '</ul>');
    }
    return out.join('');
  }

  Dev.housekeepLook = function () {
    sweepable = [];
    busy('wdHousekeepLookBtn', true);
    Dev.setEnabled('wdHousekeepSweepBtn', false);
    return WD.api('dev/housekeeping_survey', {}).then(function (r) {
      busy('wdHousekeepLookBtn', false);
      if (r && r.error) { fail('Housekeeping', r.error); return; }
      (r && r.groups ? r.groups : []).forEach(function (g) {
        (g.entries || []).forEach(function (e) {
          if (e.deletable) sweepable.push(e.path);
        });
      });
      Dev.showResult('Housekeeping', surveyReport(r));
      Dev.setEnabled('wdHousekeepSweepBtn', true);
    }).catch(function (e) {
      busy('wdHousekeepLookBtn', false);
      fail('Housekeeping', e);
    });
  };

  Dev.housekeepSweep = function () {
    if (!window.confirm(
        'This permanently deletes the items the look marked safe to remove. ' +
        'Nothing of yours, nothing in use, and nothing from your Desktop. ' +
        'Continue?')) return;
    busy('wdHousekeepSweepBtn', true);
    return WD.api('dev/housekeeping_sweep', { paths: sweepable })
      .then(function (r) {
        busy('wdHousekeepSweepBtn', false);
        Dev.setEnabled('wdHousekeepSweepBtn', false);
        if (r && r.error) { fail('Housekeeping — delete', r.error); return; }
        Dev.showResult('Housekeeping — done', sweepReport(r));
      }).catch(function (e) {
        busy('wdHousekeepSweepBtn', false);
        Dev.setEnabled('wdHousekeepSweepBtn', false);
        fail('Housekeeping — delete', e);
      });
  };

  /* ── About dev mode ──────────────────────────────────────────── */

  Dev.showWhereIAm = function () {
    Dev.showResult('Dev mode',
      '<p class="dev-result-lead">You are in dev mode. The tools themselves ' +
      'are unchanged — this strip is the only difference.</p>' +
      '<ul class="dev-result-list">' +
        '<li><span class="dev-result-name">How it was turned on</span>' +
        '<span class="dev-result-sub">Menu → Advanced → Dev Tools, ' +
        'with the password; or <code>?dev=1</code> on any page.</span></li>' +
        '<li><span class="dev-result-name">How to leave</span>' +
        '<span class="dev-result-sub">Menu → Advanced → Exit Dev ' +
        'Mode, or <code>?dev=0</code> on any page.</span></li>' +
        '<li><span class="dev-result-name">Moving the strip</span>' +
        '<span class="dev-result-sub">Drag it by the ⚙ DEV label. Where ' +
        'you leave it is remembered.</span></li>' +
        '<li><span class="dev-result-name">Anything that writes</span>' +
        '<span class="dev-result-sub">Previews first. The live button stays ' +
        'dead until its own preview has come back clean.</span></li>' +
      '</ul>');
  };

  /* Exposed for the tests, which run the real renderers against real
     payloads rather than reading this file. */
  Dev._realignReport = realignReport;
  Dev._surveyReport = surveyReport;
  Dev._sweepReport = sweepReport;
  Dev._housekeepingPending = function () { return sweepable.slice(); };
})();
