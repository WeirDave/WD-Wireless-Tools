/* ============================================================
   WD Wireless Tools - wd-dev-actions.js

   **Every dev-toolbar button's markup and handler lives here**, which is
   WaxFrame's convention for `wf-debug.js`, adopted for the reason WaxFrame
   gives: a toolbar whose handlers are scattered across the app grows dead
   buttons, and a button that calls nothing is worse than no button.

   The buttons are wired declaratively - `data-action="call"` with
   `data-fn="WD.Dev.openRealign"` - and run by the dispatcher in wd-dev.js.
   That is WaxFrame's `data-fn="WF_DEBUG.bundleForScout"` shape, one for one.

   Why the labels are words rather than emoji with a tooltip
   ---------------------------------------------------------
   He opened the first build of this and said: *"there are items in here and I
   don't know what they do."* Fair. The buttons were `🔍 Preview Realign` and
   `✅ Align For Real` with the explanation in a `title`, and his standing
   rules are that every control says what it is and that nothing a decision
   depends on hides behind a hover.

   So: **the strip carries readable names, and nothing in the strip writes to
   anything.** Each button opens a panel - WaxFrame's modal, which is where
   WaxFrame already puts detail - and that panel explains in plain words what
   the action looks at, what it changes, what it backs up, and that the
   preview changes nothing. The controls live under that explanation, so he
   cannot reach a destructive one without having scrolled past what it does.

   The hover flyout went with it. It was WaxFrame's answer to nine buttons,
   and hover-to-reveal is exactly what he ruled out for anything a decision
   rests on.

   Read-only versus writes stays visible: the preview control is lime and says
   it changes nothing, the live one is pink and stays `disabled` until its own
   preview has come back clean.
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
     WaxFrame writes this into index.html; there is no single page here, so
     it is a string. Same elements, same attributes. Every label is a phrase
     a person can read cold, and the trailing ellipsis is the usual signal
     that the control opens something rather than doing something. */
  Dev.toolbarInnerHtml = function () {
    return '' +
      '<button id="wdRealignOpenBtn" type="button" ' +
              'data-action="call" data-fn="WD.Dev.openRealign" ' +
              'title="Open the realign panel">' +
        'Realign renamed cloud projects…</button>' +
      '<span class="dev-toolbar-sep">|</span>' +
      '<button id="wdHousekeepOpenBtn" type="button" ' +
              'data-action="call" data-fn="WD.Dev.openHousekeeping" ' +
              'title="Open the clean-up panel">' +
        'Clean up leftover files…</button>' +
      '<span class="dev-toolbar-sep">|</span>' +
      '<button id="wdDevAboutBtn" type="button" ' +
              'data-action="call" data-fn="WD.Dev.showWhereIAm" ' +
              'title="What dev mode is and how to leave it">' +
        'About dev mode</button>';
  };

  /* Nothing in the strip is armed, so there is no per-page state to reset;
     each panel arms its own live control when its own preview succeeds. */
  Dev.onMounted = function () {};

  /* What each panel found last time it ran, kept for as long as the page is
     open.

     **Closing the panel used to throw this away.** He looked, closed it, came
     back, and had to look again from scratch with the live button greyed out -
     "this is counterproductive", and he was right. Re-deriving a five-second
     survey is annoying; re-running a realign preview that downloads ninety
     cloud projects to prove them identical is worse.

     Keeping it is safe because **the client is not the guard**. Both
     endpoints re-derive their work at write time: `housekeeping.sweep` looks
     every path up in a fresh survey and skips anything that is no longer
     deletable, and `cloud_realign.realign` re-downloads and re-compares each
     pair before touching it. The armed button is a convenience; the server is
     the safety. Disarming on close bought nothing and cost him the result. */
  var lastRun = { realign: null, housekeeping: null };

  function stamp(at) {
    var mins = Math.floor((Date.now() - at) / 60000);
    if (mins < 1) return 'just now';
    if (mins === 1) return 'a minute ago';
    if (mins < 60) return mins + ' minutes ago';
    var hrs = Math.round(mins / 60);
    return hrs === 1 ? 'an hour ago' : hrs + ' hours ago';
  }

  /* One shape for every panel: a plain-language explanation, then the output.
     The controls are returned separately and go in the footer, outside the
     scroll, so they are reachable however long the report gets. `facts` is a
     list of {q, a} - the question he would ask, and the answer - because a
     wall of prose is not something anyone reads before clicking. */
  function panel(opts) {
    return '' +
      '<p class="dev-panel-lead">' + esc(opts.lead) + '</p>' +
      '<dl class="dev-panel-facts">' +
        opts.facts.map(function (f) {
          return '<dt>' + esc(f.q) + '</dt><dd>' + esc(f.a) + '</dd>';
        }).join('') +
      '</dl>' +
      '<div class="dev-panel-out" id="devPanelOut"></div>';
  }

  function safeBtn(id, fn, label, title) {
    return '<button type="button" class="dev-btn dev-btn-safe" id="' + id + '" ' +
           'data-action="call" data-fn="' + fn + '" title="' + esc(title) + '">' +
           esc(label) + '</button>';
  }

  function writeBtn(id, fn, label, title) {
    return '<button type="button" class="dev-btn dev-btn-write" id="' + id + '" ' +
           'disabled data-action="call" data-fn="' + fn + '" ' +
           'title="' + esc(title) + '">' + esc(label) + '</button>';
  }

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

  function fail(e) {
    Dev.setPanelOutput('<p class="dev-result-error">' +
      esc((e && e.message) || e) + '</p>');
  }

  /* ── Realign renamed cloud projects ──────────────────────────
     Roughly ninety pairs read "cloud newer" because the cloud projects were
     renamed and the local copies were not. Server side is
     `tools/cloud_realign.py`; it proves each pair identical by comparing
     contents, not names. */

  Dev.openRealign = function () {
    Dev.showResult('Realign renamed cloud projects', panel({
      lead: 'Renaming a project in Ekahau Cloud moves its modified date. ' +
            'The local copy did not change, so Cloud Manager starts ' +
            'reporting "cloud newer" on files whose designs are identical. ' +
            'This settles those pairs without pulling anything down.',
      facts: [
        { q: 'What it looks at',
          a: 'Every matched pair where the cloud side reads newer. For each ' +
             'one it downloads the cloud copy and compares every document ' +
             'and every floor plan image against your local file - not the ' +
             'names, which cannot prove the contents match.' },
        { q: 'What it changes',
          a: 'On pairs proved identical: the project name stored inside the ' +
             '.esx, and the file’s modified date, set to the cloud ' +
             'project’s own date. Nothing else in the file is touched.' },
        { q: 'How it writes',
          a: 'No copy is kept. The rebuilt .esx goes to a temporary file and ' +
             'is renamed over the top, so each file is either entirely the ' +
             'old one or entirely the new one, never half of either. The one ' +
             'field it changes is the project name, which the cloud also ' +
             'holds.' },
        { q: 'What it will not do',
          a: 'Nothing is uploaded and nothing is deleted from the cloud. ' +
             'Pairs whose designs genuinely differ are skipped and listed ' +
             'with the reason. It is safe to run again if it is interrupted.' },
        { q: 'Before you press anything',
          a: 'Preview first. It does the same downloading and comparing and ' +
             'then writes nothing, so what it lists is what the live run ' +
             'would do. The live button stays dead until a preview succeeds.' }
      ],
    }),
    safeBtn('wdRealignPreviewBtn', 'WD.Dev.realignPreview',
            'Preview — changes nothing',
            'Work out what would change and report it. Writes nothing.') +
    writeBtn('wdRealignRunBtn', 'WD.Dev.realignRun',
             'Align them for real',
             'Preview first. This rewrites the files the preview listed.'));

    // Put back what the last preview found, if there was one, so closing the
    // panel does not cost him the run.
    restore('realign', 'wdRealignRunBtn', function (r) {
      return 'Align ' + plural(r.aligned.length, 'project', 'projects') +
             ' for real';
    }, realignReport);
  };

  /* Re-render a remembered result and re-arm its live control. */
  function restore(key, runBtnId, labelFor, render) {
    var last = lastRun[key];
    if (!last) return;
    Dev.setPanelOutput(
      '<p class="dev-panel-stamp">Showing the ' +
      (last.isPreview ? 'check' : 'run') + ' from ' + esc(stamp(last.at)) +
      '. Run it again if anything has changed since — either way, the ' +
      'server re-checks every file before it writes.</p>' +
      render(last.result, last.isPreview));
    if (!last.isPreview || !last.armable) return;
    Dev.setEnabled(runBtnId, true);
    var btn = document.getElementById(runBtnId);
    if (btn) { btn.textContent = labelFor(last.result); delete btn.dataset.wasLabel; }
  }

  /* ── progress, while it runs ─────────────────────────────────
     **The server was already reporting this and nothing was listening.**
     `cloud_realign.realign` calls its `progress_cb` once per pair - "Checking
     34 of 90" - and `server.py` wires that to `/api/cloud/progress` keyed by
     an `opId`. The toolbar was not sending an `opId`, so ninety cloud
     downloads happened behind a button that said "Aligning..." and nothing
     else. On a fleet this size that is minutes of a screen that looks
     identical to a hung one.

     Same shape Cloud Manager uses: make an id, send it, poll every 250 ms,
     stop when the call returns. */
  var poller = null;

  function stopPolling() {
    if (poller) { clearInterval(poller); poller = null; }
  }

  function progressHtml(pct, message) {
    return '' +
      '<div class="progress-wrap">' +
        '<div class="progress-track">' +
          '<div class="progress-fill' + (pct == null ? ' indeterminate' : '') +
               '"' + (pct == null ? '' : ' style="width:' + pct + '%"') +
          '></div>' +
        '</div>' +
        '<div class="progress-label">' +
          '<span class="stage">' + esc(message || 'Working…') + '</span>' +
          '<span class="pct">' + (pct == null ? '' : pct + '%') + '</span>' +
        '</div>' +
      '</div>';
  }

  function startPolling(opId, lead) {
    stopPolling();
    Dev.setPanelOutput('<p class="dev-result-lead">' + esc(lead) + '</p>' +
                       progressHtml(null, 'Starting…'));
    poller = setInterval(function () {
      fetch('/api/cloud/progress?id=' + encodeURIComponent(opId))
        .then(function (r) { return r.json(); })
        .then(function (p) {
          if (!poller || !p) return;
          var pct = (typeof p.current === 'number' && p.total)
            ? Math.round(100 * p.current / p.total) : null;
          Dev.setPanelOutput('<p class="dev-result-lead">' + esc(lead) +
                             '</p>' + progressHtml(pct, p.message));
        })
        .catch(function () { /* a dropped poll is not a failed operation */ });
    }, 250);
  }

  function realignCall(dryRun, lead) {
    var opId = 'dev-realign-' + Date.now() + '-' +
               Math.random().toString(16).slice(2, 8);
    startPolling(opId, lead);
    return WD.api('cloud/realign_renamed', { dryRun: dryRun, opId: opId })
      .then(function (r) { stopPolling(); return r; })
      .catch(function (e) { stopPolling(); throw e; });
  }

  /* The report he decides on, at his scale - around ninety pairs.
     Full names, never truncated, and the skipped ones grouped by reason so
     the shape of the problem is visible without reading ninety lines. */
  function realignReport(r, isPreview) {
    if (!r) return '<p class="dev-result-error">No answer from the server.</p>';
    var aligned = r.aligned || [], skipped = r.skipped || [], failed = r.failed || [];
    var out = [];

    /* **"How will I know when it is done?"** A report appearing where a
       progress bar was is a weak signal, so the finished state says so in
       words, at the top, and says what it means for him - the whole reason he
       ran it was to stop those rows claiming there was work to pull. */
    if (isPreview) {
      out.push('<p class="dev-result-lead">' +
        'Checked ' + plural(r.examined || 0, 'pair', 'pairs') + '. ' +
        '<strong>Nothing has been changed.</strong></p>');
    } else {
      var done = aligned.length;
      out.push('<p class="dev-result-done">' +
        '<strong>Finished.</strong> ' +
        (done
          ? plural(done, 'project is', 'projects are') + ' now in step with ' +
            'the cloud — those rows will stop reporting the cloud as ' +
            'newer. Nothing was uploaded, and nothing was deleted from the ' +
            'cloud.'
          : 'No project needed changing.') +
        (failed.length
          ? ' ' + (failed.length === 1
                    ? 'One failed and is listed below'
                    : failed.length + ' failed and are listed below') +
            ' — running this again picks up what is left.'
          : '') +
        '</p>');
      out.push('<p class="dev-result-lead">Checked ' +
        plural(r.examined || 0, 'pair', 'pairs') + '.</p>');
    }

    out.push('<ul class="dev-result-tally">' +
      '<li><strong>' + aligned.length + '</strong> ' +
        (isPreview ? 'would be aligned' : 'aligned') + '</li>' +
      '<li><strong>' + skipped.length + '</strong> skipped</li>' +
      '<li><strong>' + failed.length + '</strong> failed</li></ul>');

    if (aligned.length) {
      out.push('<h4 class="dev-result-section">' +
        (isPreview ? 'Would align — ' : 'Aligned — ') +
        plural(aligned.length, 'project', 'projects') +
        '</h4><ul class="dev-result-list">' +
        aligned.map(function (f) {
          return '<li><span class="dev-result-name">' + esc(f.name) + '</span>' +
            (f.folder ? '<span class="dev-result-sub">' + esc(f.folder) + '</span>' : '') +
            ((f.actions || []).length
              ? '<ul class="dev-result-acts">' + f.actions.map(function (a) {
                  return '<li>' + esc(a) + '</li>'; }).join('') + '</ul>' : '') +
            (f.newDate ? '<span class="dev-result-sub">New date: ' +
              esc(f.newDate) + '</span>' : '') +
            (f.warning ? '<span class="dev-result-warn">' +
              esc(f.warning) + '</span>' : '') +
          '</li>';
        }).join('') + '</ul>');
    }

    if (skipped.length) {
      /* Grouped, because ninety pairs skipped one-by-one is a wall. The
         reason is the thing he is scanning for, so it is the heading. */
      var byReason = {};
      var order = [];
      skipped.forEach(function (f) {
        var key = f.reason || 'No reason given.';
        if (!byReason[key]) { byReason[key] = []; order.push(key); }
        byReason[key].push(f);
      });
      out.push('<h4 class="dev-result-section">Skipped — ' +
        plural(skipped.length, 'project', 'projects') + '</h4>');
      order.forEach(function (reason) {
        var group = byReason[reason];
        out.push('<p class="dev-result-reason">' + esc(reason) +
          ' <span class="dev-result-count">' +
          plural(group.length, 'project', 'projects') + '</span></p>' +
          '<ul class="dev-result-list">' + group.map(function (f) {
            return '<li><span class="dev-result-name">' + esc(f.name) + '</span>' +
              (f.folder ? '<span class="dev-result-sub">' + esc(f.folder) +
                '</span>' : '') + '</li>';
          }).join('') + '</ul>');
      });
    }

    if (failed.length) {
      out.push('<h4 class="dev-result-section">Failed — ' +
        plural(failed.length, 'project', 'projects') +
        '</h4><ul class="dev-result-list">' +
        failed.map(function (f) {
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
    busy('wdRealignPreviewBtn', true, 'Comparing…');
    Dev.setEnabled('wdRealignRunBtn', false);
    return realignCall(true,
        'Downloading each cloud copy and comparing it. This takes a moment ' +
        'per project, so a large fleet takes a few minutes.'
      ).then(function (r) {
      busy('wdRealignPreviewBtn', false);
      if (r && r.error) { fail(r.error); return; }
      Dev.setPanelOutput(realignReport(r, true));
      // The only path that arms the live button, and only on a clean
      // preview. A failed one leaves it dead, which is what we want.
      var n = (r && r.aligned && r.aligned.length) || 0;
      lastRun.realign = { result: r, isPreview: true, at: Date.now(),
                          armable: n > 0 };
      Dev.setEnabled('wdRealignRunBtn', n > 0);
      var btn = document.getElementById('wdRealignRunBtn');
      if (btn && n > 0) {
        // Name the number. "Align them for real" and "Align 87 projects for
        // real" are different amounts of information at the moment it counts.
        btn.textContent = 'Align ' + plural(n, 'project', 'projects') +
                          ' for real';
        delete btn.dataset.wasLabel;
      }
    }).catch(function (e) {
      busy('wdRealignPreviewBtn', false);
      fail(e);
    });
  };

  Dev.realignRun = function () {
    if (!window.confirm(
        'This rewrites the project name and modified date inside the local ' +
        '.esx files the preview listed, backing each one up first. ' +
        'Nothing is uploaded or deleted. Continue?')) return;
    busy('wdRealignRunBtn', true, 'Aligning…');
    return realignCall(false,
        'Re-checking each pair and writing the ones that are still identical. ' +
        'Every file is backed up before it is touched.'
      ).then(function (r) {
      busy('wdRealignRunBtn', false);
      Dev.setEnabled('wdRealignRunBtn', false);
      if (r && r.error) { fail(r.error); return; }
      lastRun.realign = { result: r, isPreview: false, at: Date.now(),
                          armable: false };
      Dev.setPanelOutput(realignReport(r, false));
      Dev.setPanelTitle('Realign — finished');
    }).catch(function (e) {
      busy('wdRealignRunBtn', false);
      Dev.setEnabled('wdRealignRunBtn', false);
      fail(e);
    });
  };

  /* ── Clean up leftover files ─────────────────────────────────
     "how do I know, once we've done all the work, when to be able to clean
     stuff up?" Server side is `tools/housekeeping.py`. */

  var sweepable = [];

  Dev.openHousekeeping = function () {
    // Deliberately does *not* clear `sweepable` - see `lastRun` above. A new
    // Look replaces it; reopening the panel keeps it.
    Dev.showResult('Clean up leftover files', panel({
      lead: 'Development sessions leave things behind - worktrees, scratch ' +
            'folders, temp directories, browser drivers, downloaded release ' +
            'ZIPs. This inventories them and says which are safe to remove.',
      facts: [
        { q: 'What it looks at',
          a: 'Only what our own tooling creates, matched by name. Anything ' +
             'it does not recognise is left out of the list entirely.' },
        { q: 'What it will not touch',
          a: 'Nothing in Dropbox, nothing in your project folders, nothing ' +
             'in ~/.wd_wireless_tools, and nothing on your Desktop - those ' +
             'are listed so you can deal with them yourself, never deleted.' },
        { q: 'What it leaves alone',
          a: 'Anything a running session is using: a registered worktree, or ' +
             'anything changed in the last few minutes. Each one is listed ' +
             'with the reason it was kept.' },
        { q: 'Your workplace data',
          a: 'Items carrying site codes, project names or work addresses are ' +
             'counted and reported first. The values themselves are never ' +
             'shown.' },
        { q: 'Before you press anything',
          a: 'Look first. The delete button stays dead until it has. The ' +
             'list is worked out again at delete time rather than trusted, ' +
             'so anything that became busy in between is skipped.' }
      ],
    }),
    safeBtn('wdHousekeepLookBtn', 'WD.Dev.housekeepLook',
            'Look — changes nothing',
            'Inventory what is there. Writes nothing.') +
    writeBtn('wdHousekeepSweepBtn', 'WD.Dev.housekeepSweep',
             'Delete what it listed',
             'Look first. Deletes the items marked safe to remove.'));

    restore('housekeeping', 'wdHousekeepSweepBtn', function () {
      return 'Delete ' + plural(sweepable.length, 'item', 'items');
    }, function (r, isPreview) {
      return isPreview ? surveyReport(r) : sweepReport(r);
    });
  };

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
        out.push('<p class="dev-result-reason">Kept</p>' +
          '<ul class="dev-result-list">' +
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
    busy('wdHousekeepLookBtn', true, 'Looking…');
    Dev.setEnabled('wdHousekeepSweepBtn', false);
    return WD.api('dev/housekeeping_survey', {}).then(function (r) {
      busy('wdHousekeepLookBtn', false);
      if (r && r.error) { fail(r.error); return; }
      (r && r.groups ? r.groups : []).forEach(function (g) {
        (g.entries || []).forEach(function (e) {
          if (e.deletable) sweepable.push(e.path);
        });
      });
      lastRun.housekeeping = { result: r, isPreview: true, at: Date.now(),
                               armable: sweepable.length > 0 };
      Dev.setPanelOutput(surveyReport(r));
      Dev.setEnabled('wdHousekeepSweepBtn', sweepable.length > 0);
      var btn = document.getElementById('wdHousekeepSweepBtn');
      if (btn && sweepable.length) {
        btn.textContent = 'Delete ' +
          plural(sweepable.length, 'item', 'items');
        delete btn.dataset.wasLabel;
      }
    }).catch(function (e) {
      busy('wdHousekeepLookBtn', false);
      fail(e);
    });
  };

  Dev.housekeepSweep = function () {
    if (!window.confirm(
        'This permanently deletes the items the look marked safe to remove. ' +
        'Nothing of yours, nothing in use, and nothing from your Desktop. ' +
        'Continue?')) return;
    busy('wdHousekeepSweepBtn', true, 'Deleting…');
    return WD.api('dev/housekeeping_sweep', { paths: sweepable })
      .then(function (r) {
        busy('wdHousekeepSweepBtn', false);
        Dev.setEnabled('wdHousekeepSweepBtn', false);
        if (r && r.error) { fail(r.error); return; }
        // The list it acted on is spent; the next Look builds a new one.
        sweepable = [];
        lastRun.housekeeping = { result: r, isPreview: false, at: Date.now(),
                                 armable: false, sweep: true };
        Dev.setPanelOutput(sweepReport(r));
      }).catch(function (e) {
        busy('wdHousekeepSweepBtn', false);
        Dev.setEnabled('wdHousekeepSweepBtn', false);
        fail(e);
      });
  };

  /* ── About dev mode ──────────────────────────────────────────── */

  Dev.showWhereIAm = function () {
    Dev.showResult('About dev mode', panel({
      lead: 'You are in dev mode. The tools themselves are unchanged — ' +
            'this strip is the only difference, and nothing on it writes to ' +
            'anything until you open a panel and press a live control.',
      facts: [
        { q: 'How it was turned on',
          a: 'Menu → Advanced → Dev Tools, with the password; or ' +
             '?dev=1 on the end of any page address.' },
        { q: 'How to leave',
          a: 'Menu → Advanced → Exit Dev Mode, or ?dev=0 on any ' +
             'page. It stays off until you turn it back on.' },
        { q: 'Moving the strip',
          a: 'Drag it by the DEV label. Where you leave it is remembered.' },
        { q: 'Anything that writes',
          a: 'Previews first. The live control stays dead until its own ' +
             'preview has come back clean, and disarms again after a run.' }
      ],
      controls: '',
    }));
  };

  /* Exposed for the tests, which run the real renderers against real payloads
     rather than reading this file. */
  Dev._realignReport = realignReport;
  Dev._surveyReport = surveyReport;
  Dev._sweepReport = sweepReport;
  Dev._housekeepingPending = function () { return sweepable.slice(); };
  Dev._lastRun = function (k) { return lastRun[k]; };
})();
