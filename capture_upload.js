// Paste this into the browser console on ekahau.cloud BEFORE uploading a project.
// It intercepts fetch and XMLHttpRequest calls and logs upload-related requests.

(function() {
    console.log('%c[WD Capture] Monitoring for upload requests...', 'color: #0f0; font-size: 14px');
    console.log('%c[WD Capture] Now upload a project through the Ekahau UI.', 'color: #0f0');

    const captured = [];

    // --- Intercept fetch() ---
    const origFetch = window.fetch;
    window.fetch = async function(input, init = {}) {
        const url = typeof input === 'string' ? input : input.url;
        const method = (init.method || 'GET').toUpperCase();

        // Log anything that looks like an upload (POST/PUT with a body)
        if (method === 'POST' || method === 'PUT') {
            const entry = {
                type: 'fetch',
                method: method,
                url: url,
                headers: {},
                bodyType: null,
                bodyPreview: null
            };

            // Capture headers
            if (init.headers) {
                if (init.headers instanceof Headers) {
                    init.headers.forEach((v, k) => entry.headers[k] = v);
                } else if (typeof init.headers === 'object') {
                    entry.headers = { ...init.headers };
                }
            }

            // Describe the body
            if (init.body instanceof FormData) {
                entry.bodyType = 'FormData';
                entry.bodyPreview = {};
                for (const [key, val] of init.body.entries()) {
                    if (val instanceof File) {
                        entry.bodyPreview[key] = {
                            type: 'File',
                            name: val.name,
                            size: val.size,
                            mimeType: val.type
                        };
                    } else {
                        entry.bodyPreview[key] = val;
                    }
                }
            } else if (init.body instanceof Blob) {
                entry.bodyType = 'Blob';
                entry.bodyPreview = { size: init.body.size, mimeType: init.body.type };
            } else if (init.body instanceof ArrayBuffer || init.body instanceof Uint8Array) {
                entry.bodyType = 'Binary';
                entry.bodyPreview = { size: init.body.byteLength || init.body.length };
            } else if (typeof init.body === 'string') {
                entry.bodyType = 'String';
                entry.bodyPreview = init.body.length > 2000 ? init.body.slice(0, 2000) + '...' : init.body;
            }

            captured.push(entry);
            console.log('%c[WD Capture] fetch ' + method + ' ' + url, 'color: #ff0; font-size: 12px');
            console.log(JSON.stringify(entry, null, 2));
        }

        // Also log the response status
        const resp = await origFetch.apply(this, arguments);
        if (method === 'POST' || method === 'PUT') {
            console.log('%c[WD Capture] Response: ' + resp.status + ' ' + resp.statusText, 'color: #0ff');
            // Clone and try to log response body
            try {
                const clone = resp.clone();
                const text = await clone.text();
                const preview = text.length > 3000 ? text.slice(0, 3000) + '...' : text;
                console.log('%c[WD Capture] Response body:', 'color: #0ff');
                console.log(preview);
            } catch(e) {}
        }
        return resp;
    };

    // --- Intercept XMLHttpRequest ---
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function(method, url) {
        this._wdMethod = method.toUpperCase();
        this._wdUrl = url;
        this._wdHeaders = {};
        return origOpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        if (this._wdHeaders) this._wdHeaders[name] = value;
        return origSetHeader.apply(this, arguments);
    };

    XMLHttpRequest.prototype.send = function(body) {
        if (this._wdMethod === 'POST' || this._wdMethod === 'PUT') {
            const entry = {
                type: 'XMLHttpRequest',
                method: this._wdMethod,
                url: this._wdUrl,
                headers: this._wdHeaders,
                bodyType: null,
                bodyPreview: null
            };

            if (body instanceof FormData) {
                entry.bodyType = 'FormData';
                entry.bodyPreview = {};
                for (const [key, val] of body.entries()) {
                    if (val instanceof File) {
                        entry.bodyPreview[key] = {
                            type: 'File',
                            name: val.name,
                            size: val.size,
                            mimeType: val.type
                        };
                    } else {
                        entry.bodyPreview[key] = val;
                    }
                }
            } else if (body instanceof Blob) {
                entry.bodyType = 'Blob';
                entry.bodyPreview = { size: body.size, mimeType: body.type };
            } else if (typeof body === 'string') {
                entry.bodyType = 'String';
                entry.bodyPreview = body.length > 2000 ? body.slice(0, 2000) + '...' : body;
            }

            captured.push(entry);
            console.log('%c[WD Capture] XHR ' + this._wdMethod + ' ' + this._wdUrl, 'color: #ff0; font-size: 12px');
            console.log(JSON.stringify(entry, null, 2));

            // Log response when done
            this.addEventListener('load', function() {
                console.log('%c[WD Capture] XHR Response: ' + this.status, 'color: #0ff');
                const text = this.responseText;
                const preview = text && text.length > 3000 ? text.slice(0, 3000) + '...' : text;
                console.log(preview);
            });
        }
        return origSend.apply(this, arguments);
    };

    // Helper to dump all captured requests
    window.wdDump = function() {
        console.log('%c[WD Capture] === ALL CAPTURED REQUESTS ===', 'color: #0f0; font-size: 14px');
        console.log(JSON.stringify(captured, null, 2));
        // Also copy to clipboard
        try {
            copy(JSON.stringify(captured, null, 2));
            console.log('%c[WD Capture] Copied to clipboard!', 'color: #0f0');
        } catch(e) {
            console.log('%c[WD Capture] Could not copy to clipboard. Select the JSON above manually.', 'color: #f80');
        }
    };

    console.log('%c[WD Capture] Ready. After uploading, type wdDump() to get all captured requests.', 'color: #0f0; font-size: 14px');
})();
