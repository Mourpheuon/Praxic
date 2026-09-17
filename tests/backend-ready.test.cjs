const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');
const { spawn } = require('child_process');
const { waitForBackend } = require('../electron/backend-ready');

test('missing executable reports spawn error', async () => {
    const child = spawn('praxic-intentionally-missing-executable');
    await assert.rejects(waitForBackend(child, 'http://127.0.0.1:1/', { timeoutMs: 2000 }), /ENOENT/);
});

test('a hung HTTP server cannot bypass the overall deadline', async t => {
    const server = http.createServer(() => {});
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)']);
    t.after(() => { child.kill(); server.closeAllConnections(); server.close(); });
    await assert.rejects(waitForBackend(child, `http://127.0.0.1:${server.address().port}/`, { timeoutMs: 100 }), /超时/);
});

test('early exit reports stdout traceback without waiting for timeout', async () => {
    const child = spawn(process.execPath, ['-e', "console.log('unrecognized arguments: -m uvicorn'); process.exit(2)"]);
    await assert.rejects(waitForBackend(child, 'http://127.0.0.1:1/', { timeoutMs: 2000 }),
        /code=2[\s\S]*unrecognized arguments/);
});

test('200 with expected status is healthy', async t => {
    const server = http.createServer((req, res) => res.end(JSON.stringify({ configured: false })));
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)']);
    t.after(() => { child.kill(); server.close(); });
    await waitForBackend(child, `http://127.0.0.1:${server.address().port}/`, { timeoutMs: 2000 });
});

test('500 response is not readiness', async t => {
    const server = http.createServer((req, res) => { res.statusCode = 500; res.end('broken backend'); });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)']);
    t.after(() => { child.kill(); server.close(); });
    await assert.rejects(waitForBackend(child, `http://127.0.0.1:${server.address().port}/`, { timeoutMs: 200, retryMs: 10 }), /HTTP 500/);
});
