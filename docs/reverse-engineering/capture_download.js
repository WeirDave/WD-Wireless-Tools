// Paste into the browser console on ekahau.cloud BEFORE hitting Download.
// Rewrite: previous version missed the download because Ekahau likely
// triggers downloads via an anchor click / window.location (which bypass
// fetch and XMLHttpRequest). This version uses PerformanceObserver to
// catch EVERY resource the browser fetches, including anchor-triggered
// downloads, alongside the fetch/XHR interceptors.

(function () {
    console.log('%c[WD Capture DL v2] Monitoring all network activity...', 'color: #0f0; font-size: 14px');
    console.log('%c[WD Capture DL v2] Now hit "Download" on a project in Ekahau UI.', 'color: #0f0');

    const captured = [];

    const isInteresting = (url) => {
        const u = String(url || '');
        return u.includes('/esxfileapi/')
            || u.includes('/projectapi/')
            || u.includes('amazonaws.com')
            || u.includes('/download')
            || u.includes('.esx')
            || u.toLowerCase().includes('download');
    };

    // --- PerformanceObserver: catches EVERYTHING (anchor clicks, window.location, fetch, XHR) ---
    try {
        const obs = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
                if (!isInteresting(entry.name)) continue;
                const rec = {
                    source: 'PerformanceObserver',
                    url: entry.name,
                    initiatorType: entry.initiatorType,
                    duration: Math.round(entry.duration),
                    transferSize: entry.transferSize,
                    encodedBodySize: entry.encodedBodySize,
                    decodedBodySize: entry.decodedBodySize,
                    startTime: Math.round(entry.startTime),
                };
                captured.push(rec);
                console.log('%c[WD Capture DL v2] resource ' + entry.initiatorType + ' ' + entry.name, 'color: #ff0');
                console.log(JSON.stringify(rec, null, 2));
            }
        });
        obs.observe({ entryTypes: ['resource'] });
    } catch (e) {
        console.log('%c[WD Capture DL v2] PerformanceObserver failed: ' + e.message, 'color: #f00');
    }

    // --- Intercept anchor clicks (some downloads use <a download href=...>) ---
    document.addEventListener('click', function (e) {
        const a = e.target.closest && e.target.closest('a[href]');
        if (!a) return;
        const rec = {
            source: 'anchor click',
            href: a.href,
            download: a.getAttribute('download'),
            target: a.target,
            text: (a.textContent || '').trim().slice(0, 100),
        };
        if (isInteresting(a.href) || a.download != null) {
            captured.push(rec);
            console.log('%c[WD Capture DL v2] <a> click → ' + a.href, 'color: #f0f');
            console.log(JSON.stringify(rec, null, 2));
        }
    }, true);

    // --- Intercept window.open (popup-triggered downloads) ---
    const origOpen = window.open;
    window.open = function (url, ...rest) {
        if (isInteresting(url)) {
            const rec = { source: 'window.open', url: url, args: rest };
            captured.push(rec);
            console.log('%c[WD Capture DL v2] window.open → ' + url, 'color: #f0f');
            console.log(JSON.stringify(rec, null, 2));
        }
        return origOpen.apply(this, arguments);
    };

    // --- Intercept location assignment (some downloads use location.href = ...) ---
    // Can't easily monkey-patch location.href setter, but we can watch for
    // navigation events via beforeunload — rare in single-page apps so if
    // the download uses this pattern we'll see it.
    window.addEventListener('beforeunload', function () {
        console.log('%c[WD Capture DL v2] beforeunload — a navigation is happening', 'color: #f80');
    });

    // --- Intercept fetch() ---
    const origFetch = window.fetch;
    window.fetch = async function (input, init = {}) {
        const url = typeof input === 'string' ? input : input.url;
        const method = (init.method || 'GET').toUpperCase();
        if (!isInteresting(url)) return origFetch.apply(this, arguments);

        const entry = {
            source: 'fetch',
            method: method,
            url: url,
            headers: {},
            bodyPreview: null,
            status: null,
            responseHeaders: {},
            responsePreview: null,
        };
        if (init.headers) {
            if (init.headers instanceof Headers) init.headers.forEach((v, k) => entry.headers[k] = v);
            else if (typeof init.headers === 'object') entry.headers = { ...init.headers };
        }
        if (typeof init.body === 'string') entry.bodyPreview = init.body.length > 1000 ? init.body.slice(0, 1000) + '...' : init.body;

        console.log('%c[WD Capture DL v2] fetch ' + method + ' ' + url, 'color: #ff0');
        const resp = await origFetch.apply(this, arguments);
        entry.status = resp.status;
        resp.headers.forEach((v, k) => entry.responseHeaders[k] = v);
        try {
            const clone = resp.clone();
            const ct = (resp.headers.get('content-type') || '');
            if (ct.includes('json') || ct.includes('text') || ct === '') {
                const text = await clone.text();
                entry.responsePreview = text.length > 3000 ? text.slice(0, 3000) + '...' : text;
            } else {
                entry.responsePreview = '<binary body, content-type=' + ct + ', bytes=' + (resp.headers.get('content-length') || '?') + '>';
            }
        } catch (e) {
            entry.responsePreview = '<could not read: ' + e.message + '>';
        }
        captured.push(entry);
        console.log('%c[WD Capture DL v2] ← ' + entry.status + ' ' + (entry.responseHeaders['content-type'] || ''), 'color: #0ff');
        console.log(JSON.stringify(entry, null, 2));
        return resp;
    };

    // --- Intercept XMLHttpRequest ---
    const origXhrOpen = XMLHttpRequest.prototype.open;
    const origXhrSend = XMLHttpRequest.prototype.send;
    const origXhrHeader = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.open = function (method, url) {
        this._wdMethod = method.toUpperCase(); this._wdUrl = url; this._wdHeaders = {};
        return origXhrOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
        if (this._wdHeaders) this._wdHeaders[name] = value;
        return origXhrHeader.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
        if (!isInteresting(this._wdUrl)) return origXhrSend.apply(this, arguments);
        const entry = {
            source: 'XMLHttpRequest',
            method: this._wdMethod, url: this._wdUrl,
            headers: this._wdHeaders,
            bodyPreview: typeof body === 'string' ? body.slice(0, 1000) : (body && body.constructor && body.constructor.name),
            status: null, responsePreview: null,
        };
        console.log('%c[WD Capture DL v2] XHR ' + this._wdMethod + ' ' + this._wdUrl, 'color: #ff0');
        this.addEventListener('load', function () {
            entry.status = this.status;
            const ct = this.getResponseHeader('content-type') || '';
            if (ct.includes('json') || ct.includes('text') || ct === '') {
                const text = this.responseText || '';
                entry.responsePreview = text.length > 3000 ? text.slice(0, 3000) + '...' : text;
            } else {
                entry.responsePreview = '<binary body, content-type=' + ct + '>';
            }
            captured.push(entry);
            console.log('%c[WD Capture DL v2] ← ' + entry.status + ' ' + ct, 'color: #0ff');
            console.log(JSON.stringify(entry, null, 2));
        });
        return origXhrSend.apply(this, arguments);
    };

    window.wdDump = function () {
        console.log('%c[WD Capture DL v2] === ALL CAPTURED ===', 'color: #0f0; font-size: 14px');
        const out = JSON.stringify(captured, null, 2);
        console.log(out);
        try { copy(out); console.log('%c[WD Capture DL v2] Copied to clipboard!', 'color: #0f0'); }
        catch (e) { console.log('%c[WD Capture DL v2] Could not copy — select the JSON above manually.', 'color: #f80'); }
        return captured;
    };

    console.log('%c[WD Capture DL v2] Ready. After downloading, run wdDump() to copy the trace.', 'color: #0f0; font-size: 14px');
})();
