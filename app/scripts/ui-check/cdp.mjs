// Minimal Chrome DevTools Protocol client on Node 22's global WebSocket. No npm dependencies.
// Used by run.mjs; scenarios get a `page` with navigate / waitFor / click / tap / touchDrag / pinch / screenshot.
import { writeFileSync } from 'node:fs';

export async function connect(port, { browserPath, timeout = 10000, requestTimeout = 30000 } = {}) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid owned Chrome debugging port');
  const origin = `http://127.0.0.1:${port}`;
  const readJSON = async path => {
    const response = await fetch(origin + path, { signal: AbortSignal.timeout(timeout) });
    if (!response.ok) throw new Error(`CDP discovery ${path}: HTTP ${response.status}`);
    return response.json();
  };
  if (browserPath) {
    const version = await readJSON('/json/version');
    const browser = new URL(version.webSocketDebuggerUrl);
    if (browser.hostname !== '127.0.0.1' || Number(browser.port) !== port || browser.pathname !== browserPath) {
      throw new Error('Chrome endpoint does not match this run\'s DevToolsActivePort identity');
    }
  }
  const targets = await readJSON('/json');
  const target = targets.find(t => t.type === 'page');
  if (!target) throw new Error('Owned Chrome has no page target');
  const targetURL = new URL(target.webSocketDebuggerUrl);
  if (targetURL.protocol !== 'ws:' || targetURL.hostname !== '127.0.0.1' || Number(targetURL.port) !== port) {
    throw new Error('Unsafe CDP page endpoint');
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok, fail) => {
    const finish = (error) => {
      clearTimeout(timer); ws.onopen = null; ws.onerror = null; ws.onclose = null;
      if (error) { try { ws.close(); } catch {} fail(error); } else ok();
    };
    const timer = setTimeout(() => finish(new Error('CDP WebSocket connection timed out')), timeout);
    ws.onopen = () => finish();
    ws.onerror = () => finish(new Error('CDP WebSocket connection failed'));
    ws.onclose = () => finish(new Error('CDP WebSocket closed before connecting'));
  });
  let id = 0; const pending = new Map(); const console_ = []; const errors = [];
  ws.onmessage = ev => {
    let msg;
    try { msg = JSON.parse(ev.data); }
    catch { for (const { fail } of pending.values()) fail(new Error('Invalid CDP message')); pending.clear(); return; }
    if (msg.id && pending.has(msg.id)) { const { ok, fail } = pending.get(msg.id); pending.delete(msg.id); msg.error ? fail(new Error(JSON.stringify(msg.error))) : ok(msg.result); }
    else if (msg.method === 'Runtime.consoleAPICalled') {
      const line = `[${msg.params.type}] ${msg.params.args.map(a => a.value ?? a.description ?? '').join(' ')}`;
      console_.push(line);
      if (msg.params.type === 'error' || msg.params.type === 'assert') errors.push(line);
    }
    else if (msg.method === 'Runtime.exceptionThrown') errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
    else if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') errors.push(`[log] ${msg.params.entry.text} ${msg.params.entry.url || ''}`);
  };
  const REQUEST_TIMEOUT = requestTimeout;
  const send = (method, params = {}) => new Promise((ok, fail) => {
    if (ws.readyState !== WebSocket.OPEN) { fail(new Error('CDP connection is not open')); return; }
    const i = ++id;
    const timer = setTimeout(() => { if (pending.delete(i)) fail(new Error(`CDP ${method} timed out after ${REQUEST_TIMEOUT}ms`)); }, REQUEST_TIMEOUT);
    pending.set(i, { ok: v => { clearTimeout(timer); ok(v); }, fail: e => { clearTimeout(timer); fail(e); } });
    try { ws.send(JSON.stringify({ id: i, method, params })); }
    catch (error) { clearTimeout(timer); pending.delete(i); fail(error); }
  });
  ws.onclose = () => { for (const { fail } of pending.values()) fail(new Error('CDP connection closed')); pending.clear(); };
  ws.onerror = () => { for (const { fail } of pending.values()) fail(new Error('CDP connection failed')); pending.clear(); };
  try { await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable'); }
  catch (error) { ws.close(); throw error; }
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const evaluate = async (expression) => { const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'eval failed'); return r.result.value; };
  const page = {
    send, evaluate, sleep, console: console_, errors,
    async navigate(url) { await send('Page.navigate', { url: 'about:blank' }); await sleep(200); await send('Page.navigate', { url }); await sleep(500); },
    async waitFor(expression, timeout = 20000, step = 250) {
      // DOM nodes cannot be returned by value over CDP; coerce so `querySelector(...)` expressions work.
      const start = Date.now();
      while (Date.now() - start < timeout) { try { if (await evaluate(`Boolean(${expression})`)) return true; } catch {} await sleep(step); }
      throw new Error(`timeout waiting for: ${expression}`);
    },
    async screenshot(path, clip) { const r = await send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip: { ...clip, scale: 1 } } : {}) }); writeFileSync(path, Buffer.from(r.data, 'base64')); return path; },
    async mobile(on = true) {
      if (on) {
        await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true, screenWidth: 390, screenHeight: 844 });
        await send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
        await send('Emulation.setEmulatedMedia', { features: [{ name: 'pointer', value: 'coarse' }, { name: 'hover', value: 'none' }] });
      } else {
        await send('Emulation.clearDeviceMetricsOverride'); await send('Emulation.setTouchEmulationEnabled', { enabled: false }); await send('Emulation.setEmulatedMedia', { features: [] });
      }
    },
    async rect(selector) { return evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width / 2, cy: r.y + r.height / 2 }; })()`); },
    async click(selector) {
      await evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: 'center', behavior: 'instant' })`); await sleep(120);
      const r = await page.rect(selector); if (!r) throw new Error(`no element ${selector}`); await page.clickAt(r.cx, r.cy);
    },
    async clickAt(x, y) {
      await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y });
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
    },
    async tap(x, y) {
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    },
    async touchDrag(x, y0, y1, steps = 8) {
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y: y0 }] });
      for (let i = 1; i <= steps; i++) { await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x, y: y0 + (y1 - y0) * i / steps }] }); await sleep(16); }
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    },
    async pinch(cx, cy, from, to, steps = 10) {
      // two fingers on a horizontal line, distance `from` → `to`
      const pts = d => [{ x: cx - d / 2, y: cy, id: 0 }, { x: cx + d / 2, y: cy, id: 1 }];
      await send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: pts(from) });
      for (let i = 1; i <= steps; i++) { await send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: pts(from + (to - from) * i / steps) }); await sleep(16); }
      await send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    },
    async mouseDrag(x0, y0, x1, y1, steps = 8) {
      await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: x0, y: y0, button: 'left', clickCount: 1 });
      for (let i = 1; i <= steps; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: x0 + (x1 - x0) * i / steps, y: y0 + (y1 - y0) * i / steps, button: 'left' }); await sleep(16); }
      await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: x1, y: y1, button: 'left', clickCount: 1 });
    },
    close() { ws.close(); },
  };
  return page;
}
