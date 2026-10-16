#!/usr/bin/env node
// Repeatable fault tests for the sibling run.mjs/cdp.mjs. No browser or network.
// Run: node --experimental-vm-modules scripts/ui-check/selftest.mjs
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as path from 'node:path';
import * as url from 'node:url';
import vm from 'node:vm';

if (typeof vm.SourceTextModule !== 'function') {
  console.error('Run with: node --experimental-vm-modules scripts/ui-check/selftest.mjs');
  process.exit(2);
}
const here = path.dirname(url.fileURLToPath(import.meta.url));
const { connect } = await import(url.pathToFileURL(path.join(here, 'cdp.mjs')));
const checks = [];
async function test(name, run) {
  try { await run(); checks.push({ name, pass: true }); }
  catch (error) { checks.push({ name, pass: false, error: error.stack || error.message }); }
}

// CDP transport faults. The globals are restored before testing the runner.
const oldFetch = globalThis.fetch, oldWS = globalThis.WebSocket;
let socket, shouldOpen = true, shouldReply = true;
class FakeSocket {
  static OPEN = 1;
  readyState = 1;
  constructor() { socket = this; if (shouldOpen) queueMicrotask(() => this.onopen?.()); }
  send(raw) { const msg = JSON.parse(raw); if (shouldReply) queueMicrotask(() => this.onmessage?.({ data: JSON.stringify({ id: msg.id, result: {} }) })); }
  close() { this.readyState = 3; this.onclose?.(); }
}
const goodFetch = async address => ({ ok: true, json: async () => address.endsWith('/json/version')
  ? { webSocketDebuggerUrl: 'ws://127.0.0.1:4444/devtools/browser/owned' }
  : [{ type: 'page', webSocketDebuggerUrl: 'ws://127.0.0.1:4444/devtools/page/mock' }] });
const openPage = () => connect(4444, { browserPath: '/devtools/browser/owned', timeout: 40, requestTimeout: 40 });
async function transportTest(name, run) {
  await test(name, async () => {
    shouldOpen = true; shouldReply = true; socket = null;
    globalThis.fetch = goodFetch;
    try { await run(); } finally { socket?.close(); }
  });
}
try {
  globalThis.WebSocket = FakeSocket;
  await transportTest('console.error enters the failure list', async () => {
    const page = await openPage();
    socket.onmessage({ data: JSON.stringify({ method: 'Runtime.consoleAPICalled', params: { type: 'error', args: [{ value: 'synthetic error' }] } }) });
    assert.equal(page.errors.length, 1);
  });
  await transportTest('CDP requests have a finite deadline', async () => {
    const page = await openPage(); shouldReply = false;
    await assert.rejects(page.send('Runtime.test'), /timed out/);
  });
  await transportTest('Socket closure rejects pending work immediately', async () => {
    const page = await openPage(); shouldReply = false;
    const pending = page.send('Runtime.test'); socket.close();
    await assert.rejects(pending, /connection closed/);
  });
  await transportTest('Sending to a closed socket fails immediately', async () => {
    const page = await openPage(); socket.close();
    await assert.rejects(page.send('Runtime.test'), /not open/);
  });
  await transportTest('Foreign browser identity is refused before opening a page', async () => {
    await assert.rejects(connect(4444, { browserPath: '/devtools/browser/another', timeout: 40 }), /does not match/);
    assert.equal(socket, null);
  });
  await transportTest('WebSocket opening has a finite deadline', async () => {
    shouldOpen = false;
    await assert.rejects(openPage(), /connection timed out/);
  });
  await transportTest('HTTP discovery has an abort deadline', async () => {
    globalThis.fetch = async (address, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
    });
    // AbortSignal's timer is unref'ed; keep the mock process alive until it fires.
    const keepAlive = setTimeout(() => {}, 200);
    try { await assert.rejects(connect(4444, { timeout: 30 }), /timeout|aborted/i); }
    finally { clearTimeout(keepAlive); }
  });
} finally { globalThis.fetch = oldFetch; globalThis.WebSocket = oldWS; }

// Evaluate the real runner with mock process/filesystem/CDP modules. No Chrome,
// taskkill, files, or sockets are actually created or removed by these fixtures.
for (const phase of ['connect', 'contact-sheet', 'success', 'foreign-fixed-port']) {
  await test(`Runner ${phase}: report, exit status and owned-resource cleanup`, async () => {
    const state = { spawns: 0, kills: [], browserCloses: 0, socketCloses: 0, removed: [], files: new Map() };
    let now = 0;
    class FastDate extends Date { static now() { return now; } }
    const child = { pid: 2468, exitCode: null, signalCode: null, on() { return this; } };
    const argv = ['node', 'run.mjs', '--chrome', 'C:/owned-fixture/chrome.exe', '--out', 'C:/owned-fixture/out'];
    if (phase === 'foreign-fixed-port') argv.push('--port', '9333');
    const fakeProcess = { argv, platform: 'win32', env: {}, exitCode: undefined };
    const fakePage = {
      errors: [], close() { state.socketCloses++; },
      async send(method) { if (method === 'Browser.close') { state.browserCloses++; child.exitCode = 0; } return {}; },
      async mobile() { if (phase === 'contact-sheet') throw new Error('synthetic sheet failure'); },
      async screenshot() {}, async navigate() {}, async waitFor() {}, async evaluate() { return 600; }, async sleep() {},
    };
    const context = vm.createContext({ Date: FastDate, console: { log() {}, error() {} },
      setTimeout(fn, ms) { now += ms; queueMicrotask(fn); return 1; }, clearTimeout() {}, Buffer, process: fakeProcess });
    let profile;
    const exportsByName = {
      'node:child_process': {
        spawn(command, args, options) { state.spawns++; assert(args.includes('--remote-debugging-port=0')); assert(options.windowsHide); return child; },
        spawnSync(command, args) {
          if (command === 'taskkill') { state.kills.push(args); child.exitCode = 0; }
          return { status: 0, stdout: command === 'git' && args[0] === 'rev-parse' ? 'a'.repeat(40) + '\n' : '' };
        },
      },
      'node:fs': {
        existsSync: () => true, mkdirSync() {}, writeFileSync(name, content) { state.files.set(name, content); },
        readFileSync: () => '4444\n/devtools/browser/owned\n',
        mkdtempSync(prefix) { profile = prefix + 'owned'; return profile; },
        rmSync(name, options) { assert.equal(name, profile); assert(options.recursive); state.removed.push(name); },
        lstatSync: () => ({ isSymbolicLink: () => false }), realpathSync: name => path.resolve(name),
      },
      'node:path': path, 'node:url': url,
      './cdp.mjs': { connect: async (port, options) => {
        assert.equal(port, 4444); assert.equal(options.browserPath, '/devtools/browser/owned');
        if (phase === 'connect') throw new Error('synthetic connection failure'); return fakePage;
      } },
      './scenarios.mjs': { scenarios: [{ id: 'desktop', title: 'fixture', run: async ({ check, shot }) => { check('fixture', true); await shot('fixture'); } }] },
    };
    const source = path.join(here, 'run.mjs');
    const mod = new vm.SourceTextModule(readFileSync(source, 'utf8'), { context, initializeImportMeta(meta) { meta.url = url.pathToFileURL(source).href; } });
    await mod.link(async name => {
      const values = exportsByName[name];
      assert(values, 'unexpected import ' + name);
      return new vm.SyntheticModule(Object.keys(values), function () { for (const [key, value] of Object.entries(values)) this.setExport(key, value); }, { context });
    });
    await mod.evaluate();
    const text = [...state.files].find(([name]) => name.endsWith('report.json'))?.[1];
    assert(text, 'failure must still emit report.json');
    const report = JSON.parse(text);
    assert.equal(report.status, phase === 'success' ? 'PASS' : 'FAIL');
    assert.equal(fakeProcess.exitCode, phase === 'success' ? 0 : 1);
    if (phase === 'foreign-fixed-port') {
      assert.equal(state.spawns, 0); assert.equal(state.kills.length, 0); assert.equal(state.removed.length, 0);
    } else {
      assert.equal(state.removed.length, 1);
      assert(child.exitCode !== null, 'spawned Chrome must exit');
      if (phase === 'connect') assert.deepEqual(Array.from(state.kills[0]), ['/PID', '2468', '/T', '/F']);
      else { assert.equal(state.browserCloses, 1); assert.equal(state.socketCloses, 1); }
    }
  });
}

const failures = checks.filter(check => !check.pass);
console.log(JSON.stringify({ tests: checks.length, passed: checks.length - failures.length, failed: failures.length,
  realNetworkUsed: false, browserStarted: false, realDeletionPerformed: false,
  boundary: 'Fault-injection checks only; actual Windows Chrome UI scenarios are a separate acceptance step.', checks }, null, 2));
process.exitCode = failures.length ? 1 : 0;
