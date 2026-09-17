// No Electron dependency: readiness and failure handling are tested with real HTTP.
const http = require('http');

function waitForBackend(child, url, { timeoutMs = 60000, retryMs = 300, requestTimeoutMs = 2000 } = {}) {
    return new Promise((resolve, reject) => {
        let settled = false;
        let output = '';
        let retry;
        let request;
        let lastStatus = '';
        const capture = data => { output = (output + data.toString()).slice(-8000); };
        child.stdout?.on('data', capture);
        child.stderr?.on('data', capture);
        const finish = error => {
            if (settled) return;
            settled = true;
            clearTimeout(deadline);
            clearTimeout(retry);
            request?.destroy();
            // Keep draining stdout/stderr for the lifetime of the child.
            if (error) reject(new Error(`${error}\n\n后端输出:\n${output || '(无输出)'}`));
            else resolve();
        };
        const deadline = setTimeout(() => finish(`后端超时未就绪 (${timeoutMs}ms) ${lastStatus}`), timeoutMs);
        child.once('error', error => finish(`无法启动后端: ${error.message}`));
        // 'close' follows final stdout/stderr data; do not lose the last traceback.
        child.once('close', (code, signal) => finish(`后端提前退出 (code=${code}, signal=${signal})`));
        const schedule = () => {
            clearTimeout(retry);
            if (!settled) retry = setTimeout(poll, retryMs);
        };
        const poll = () => {
            if (settled) return;
            request = http.get(url, res => {
                let body = '';
                res.setEncoding('utf8');
                res.on('data', chunk => { body = (body + chunk).slice(-16384); });
                res.on('end', () => {
                    let valid = false;
                    try { valid = typeof JSON.parse(body).configured === 'boolean'; } catch {}
                    if (res.statusCode === 200 && valid) finish();
                    else {
                        lastStatus = `HTTP ${res.statusCode}: ${body.slice(-500)}`;
                        schedule();
                    }
                });
                res.on('error', schedule);
            });
            request.on('error', schedule);
            request.setTimeout(requestTimeoutMs, () => request.destroy(new Error('request timeout')));
        };
        poll();
    });
}

module.exports = { waitForBackend };
