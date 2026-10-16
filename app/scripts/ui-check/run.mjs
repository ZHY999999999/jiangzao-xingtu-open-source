#!/usr/bin/env node
// UI acceptance runner. Node 22 and Chrome; no npm dependencies.
// node scripts/ui-check/run.mjs --base http://127.0.0.1:5181/ [--out <directory>]
//   [--board 881121.TI] [--company 601138.SH] [--plain 000014.SZ] [--tts 000977.SZ] [--chrome <path>] [--only desktop|mobile|reading]
// An OS-assigned debug port and a fresh profile identify this run's Chrome.
// Reports survive runner failures; only the spawned browser/profile are cleaned.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, writeFileSync, readFileSync, mkdtempSync, rmSync, lstatSync, realpathSync } from 'node:fs';
import { resolve, dirname, join, basename, relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { connect } from './cdp.mjs';
import { scenarios } from './scenarios.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).flatMap((a, i, all) => a.startsWith('--') ? [[a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]] : []));
const base = (args.base || 'http://127.0.0.1:5181/').replace(/\/?$/, '/');
const stamp = new Date().toISOString().replace(/[-:.]/g, '');
const out = resolve(args.out || join(here, '../../../diagnostics/ui-check', stamp));
const data = { board: args.board || '881121.TI', company: args.company || '601138.SH', plain: args.plain || '000014.SZ', tts: args.tts || '000977.SZ' };
mkdirSync(out, { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
const results = [], shots = [];
let page, proc, profile, spawnError, consoleErrors = [], contactSheet = null;
let browserOwned = false;
const processExited = child => !child?.pid || child.exitCode !== null || child.signalCode !== null;
const waitForExit = async (child, timeout) => {
  const until = Date.now() + timeout;
  while (!processExited(child) && Date.now() < until) await sleep(50);
  return processExited(child);
};

async function cleanup() {
  // Browser.close addresses only the endpoint authenticated against our fresh
  // profile. Never discover or kill an unrelated Chrome by name or port.
  if (page) {
    try { await Promise.race([page.send('Browser.close').catch(() => {}), sleep(1500)]); } catch {}
    try { page.close(); } catch {}
  }
  if (proc && !await waitForExit(proc, 1500)) {
    if (process.platform === 'win32') {
      spawnSync('taskkill', ['/PID', String(proc.pid), '/T', '/F'], { windowsHide: true, timeout: 5000, stdio: 'ignore' });
    } else {
      // Linux/macOS child was spawned in its own process group.
      try { process.kill(-proc.pid, 'SIGKILL'); } catch (error) { if (error.code !== 'ESRCH') throw error; }
    }
    if (!await waitForExit(proc, 3000)) throw new Error('The owned Chrome process did not exit; profile retained for inspection');
  }
  if (profile && existsSync(profile)) {
    // A newly-created, exact child directory is the only recursive-delete target.
    if (dirname(resolve(profile)) !== out || !basename(profile).startsWith('.chrome-profile-') ||
        lstatSync(profile).isSymbolicLink() || dirname(realpathSync(profile)) !== realpathSync(out)) {
      throw new Error('Refusing cleanup of an unexpected profile path');
    }
    rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
}

try {
  if (args.port && String(args.port) !== '0') throw new Error('Fixed --port is unsupported: this runner always allocates its own debug port');
  if (args.only && !scenarios.some(s => s.id === args.only)) throw new Error(`--only must be ${scenarios.map(s => s.id).join(' | ')}`);
  const onPath = name => { const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', [name], { encoding: 'utf8', windowsHide: true, timeout: 5000 }); return r.status === 0 ? r.stdout.split(/\r?\n/)[0].trim() : null; };
  const installPaths = process.platform === 'win32'
    ? [join(process.env['PROGRAMFILES'] || 'C:\\Program Files', 'Google/Chrome/Application/chrome.exe'), join(process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)', 'Google/Chrome/Application/chrome.exe'), join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe')]
    : process.platform === 'darwin' ? ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'] : [];
  const chrome = [args.chrome, process.env.CHROME_BIN].filter(Boolean).find(existsSync)
    || installPaths.find(existsSync)
    || ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome'].map(onPath).find(Boolean);
  if (!chrome) throw new Error('找不到 Chrome：用 --chrome <路径> 或 CHROME_BIN 指定');
  profile = mkdtempSync(join(out, '.chrome-profile-'));
  proc = spawn(chrome, ['--headless=new', '--no-sandbox', '--hide-scrollbars', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--window-size=1440,900',
    `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore', windowsHide: true, detached: process.platform !== 'win32' });
  proc.on('error', error => { spawnError = error; });
  let endpoint;
  const until = Date.now() + 15000;
  while (Date.now() < until) {
    if (spawnError) throw new Error(`无法启动 Chrome：${spawnError.message}`);
    if (processExited(proc)) throw new Error(`Chrome exited before readiness (code ${proc.exitCode}, signal ${proc.signalCode})`);
    try {
      const [portText, browserPath] = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').trim().split(/\r?\n/);
      const port = Number(portText);
      if (Number.isInteger(port) && port > 0 && port <= 65535 && /^\/devtools\/browser\/[a-zA-Z0-9-]+$/.test(browserPath)) { endpoint = { port, browserPath }; break; }
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    await sleep(100);
  }
  if (!endpoint) throw new Error('Owned Chrome did not produce DevToolsActivePort within 15s');
  page = await connect(endpoint.port, { browserPath: endpoint.browserPath });
  browserOwned = true;
  for (const scenario of scenarios) {
    if (args.only && args.only !== scenario.id) continue;
    const check = (name, ok, detail = '') => results.push({ scenario: scenario.id, name, ok: Boolean(ok), detail: String(detail ?? '') });
    const skip = (name, reason) => results.push({ scenario: scenario.id, name, ok: null, detail: reason });
    const shot = async name => { const file = join(out, `${name}.png`); await page.screenshot(file); shots.push({ name, file }); };
    try { await scenario.run({ page, base, shot, check, skip, data }); }
    catch (error) { results.push({ scenario: scenario.id, name: `场景中断：${error.message.split('\n')[0]}`, ok: false, detail: '' }); try { await shot(`${scenario.id}-at-failure`); } catch {} }
  }
  consoleErrors = page.errors.slice();
  results.push({ scenario: 'global', name: '页面控制台无错误', ok: consoleErrors.length === 0, detail: consoleErrors.length ? `${consoleErrors.length} 条，见下` : '' });
  if (!shots.length) throw new Error('No screenshots produced; contact sheet cannot be accepted');
  const sheetHtml = `<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#222;font:12px system-ui;color:#ddd}
    .g{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;padding:8px}.c{background:#111;padding:6px}.c img{width:100%;height:auto;display:block}.c p{margin:4px 0 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}</style>
    <div class="g">${shots.map(s => `<div class="c"><img src="${pathToFileURL(s.file).href}"><p>${s.name}</p></div>`).join('')}</div>`;
  const sheetFile = join(out, 'contact-sheet.html');
  writeFileSync(sheetFile, sheetHtml);
  await page.mobile(false);
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 100, deviceScaleFactor: 1, mobile: false });
  await page.navigate(pathToFileURL(sheetFile).href);
  await page.waitFor(`document.images.length > 0 && [...document.images].every(i => i.complete && i.naturalWidth > 0)`, 10000);
  const height = await page.evaluate('document.documentElement.scrollHeight');
  if (!Number.isFinite(height) || height <= 0 || height > 12000) throw new Error(`Invalid/oversized contact-sheet height: ${height}`);
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1600, height, deviceScaleFactor: 1, mobile: false });
  await page.sleep(300);
  await page.screenshot(join(out, 'contact-sheet.png'));
  contactSheet = 'contact-sheet.png';
} catch (error) {
  results.push({ scenario: 'global', name: 'UI runner completed', ok: false, detail: error.message });
} finally {
  try { await cleanup(); }
  catch (error) { results.push({ scenario: 'global', name: 'Owned browser/profile cleanup', ok: false, detail: error.message }); }
}

const git = (...command) => spawnSync('git', command, { encoding: 'utf8', cwd: here, windowsHide: true, timeout: 5000 });
const head = git('rev-parse', 'HEAD').stdout?.trim() || 'unknown';
const status = git('status', '--porcelain');
const dirty = status.status === 0 ? Boolean(status.stdout?.trim()) : null;
const failed = results.filter(r => r.ok === false), skipped = results.filter(r => r.ok === null), ran = results.filter(r => r.ok !== null);
const mark = row => row.ok === null ? '[-]' : row.ok ? '[x]' : '[ ]';
const lines = [`# ui-check · ${stamp} · ${base} · 代码 ${head}${dirty ? '（工作区有改动）' : ''}`, '', `${ran.length - failed.length}/${ran.length} PASS · ${skipped.length} SKIP · 控制台错误 ${consoleErrors.length}`, ''];
for (const scenario of [...scenarios, { id: 'global', title: '全局' }]) {
  const rows = results.filter(r => r.scenario === scenario.id);
  if (rows.length) lines.push(`## ${scenario.title}`, ...rows.map(r => `- ${mark(r)} ${r.name}${r.detail ? ` — ${r.detail}` : ''}`), '');
}
if (consoleErrors.length) lines.push('## 控制台错误', ...consoleErrors.slice(0, 10).map(e => `- ${e.slice(0, 200)}`), '');
const relativeOutput = relative(resolve(here, '../../..'), out).replaceAll('\\', '/');
const evidenceDirectory = relativeOutput.startsWith('../') ? `本地证据/${basename(out)}` : relativeOutput;
lines.push(`截图 ${shots.length} 张，拼图 ${contactSheet || '未完成'}；目录 ${evidenceDirectory}`);
writeFileSync(join(out, 'report.md'), lines.join('\n') + '\n');
writeFileSync(join(out, 'report.json'), JSON.stringify({ stamp, base, head, dirty, data,
  status: failed.length ? 'FAIL' : skipped.length ? 'PASS_WITH_SKIPS' : 'PASS',
  browserOwned, results, consoleErrors, shots: shots.map(s => s.name), contactSheet }, null, 2) + '\n');
console.log(lines.join('\n'));
process.exitCode = failed.length || !ran.length ? 1 : 0;
