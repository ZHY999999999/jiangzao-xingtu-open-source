#!/usr/bin/env node
/**
 * Supplemental, deterministic UI-state tests. This is NOT real speech playback.
 * Usage: node audio-state-selftest.mjs --app <path-to-app>
 * Loads actual TypeScript/TSX with the app's already-installed TypeScript;
 * no dependencies are installed, no files are written, and no network is used.
 * Browser SpeechSynthesis events and a small React hook host are controlled
 * fixtures. Keep real MP3/CDP acceptance and real-device TTS evidence separate.
 */
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname, join, relative, extname } from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import vm from 'node:vm';

const argIndex = process.argv.indexOf('--app');
const app = resolve(argIndex >= 0 ? process.argv[argIndex + 1] || '' : process.cwd());
const entry = join(app, 'src/components/CompanyAudio.tsx');
if (!existsSync(entry)) throw new Error('Pass --app pointing to the app directory containing src/components/CompanyAudio.tsx');
const requireApp = createRequire(join(app, 'package.json'));
const ts = requireApp('typescript');
const sourceHashes = new Map();
let assertions = 0;
const results = [];
const eq = (actual, expected, message) => { assertions++; assert.deepEqual(actual, expected, message); };
const ok = (value, message) => { assertions++; assert.ok(value, message); };

function createHookHost(fn, props) {
  const slots = [], effects = [];
  let cursor = 0, tree, mounted = true, writesAfterUnmount = 0;
  const changed = (a, b) => !a || !b || a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const hooks = {
    useState(initial) {
      const i = cursor++;
      if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial;
      return [slots[i], value => {
        if (!mounted) { writesAfterUnmount++; return; }
        slots[i] = typeof value === 'function' ? value(slots[i]) : value;
      }];
    },
    useRef(initial) { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useId() { const i = cursor++; if (!(i in slots)) slots[i] = `fixture-${i}`; return slots[i]; },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!slots[i] || changed(slots[i].deps, deps)) {
        const old = slots[i];
        slots[i] = { deps, cleanup: old?.cleanup };
        effects.push(() => { old?.cleanup?.(); slots[i].cleanup = effect(); });
      }
    },
    useMemo(factory, deps) {
      const i = cursor++;
      if (!slots[i] || changed(slots[i].deps, deps)) slots[i] = { deps, value: factory() };
      return slots[i].value;
    },
  };
  hooks.useCallback = (callback, deps) => hooks.useMemo(() => callback, deps);
  return {
    hooks,
    render(run) {
      cursor = 0;
      tree = run(() => fn(props));
      while (effects.length) effects.shift()();
      return tree;
    },
    unmount() {
      mounted = false;
      for (const value of slots) if (value && typeof value.cleanup === 'function') value.cleanup();
    },
    get tree() { return tree; },
    get writesAfterUnmount() { return writesAfterUnmount; },
  };
}

function createEnvironment() {
  let activeHooks;
  const spoken = [];
  const synthesis = {
    paused: false, speaking: false, pending: false, current: null,
    pauseCalls: 0, resumeCalls: 0, cancelCalls: 0,
    speak(utterance) { spoken.push(utterance); this.current = utterance; this.pending = true; this.speaking = true; },
    pause() { this.pauseCalls++; this.paused = true; },
    resume() { this.resumeCalls++; this.paused = false; },
    cancel() { this.cancelCalls++; this.current = null; this.speaking = false; this.pending = false; },
  };
  class SpeechSynthesisUtteranceFixture { constructor(text) { this.text = text; } }
  const react = new Proxy({}, { get: (_target, key) => (...args) => {
    if (!activeHooks || typeof activeHooks[key] !== 'function') throw new Error(`Unsupported hook in fixture: ${String(key)}`);
    return activeHooks[key](...args);
  } });
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
  const context = vm.createContext({
    URL, DOMException, console, setTimeout, clearTimeout,
    window: { location: { href: 'http://127.0.0.1:5181/#/company/FIXTURE' }, speechSynthesis: synthesis },
    SpeechSynthesisUtterance: SpeechSynthesisUtteranceFixture,
  });
  const cache = new Map();
  function load(file) {
    file = resolve(file);
    if (cache.has(file)) return cache.get(file).exports;
    const raw = readFileSync(file, 'utf8');
    sourceHashes.set(relative(app, file).replaceAll('\\', '/'), createHash('sha256').update(raw).digest('hex'));
    const compiled = ts.transpileModule(raw, {
      fileName: file,
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      reportDiagnostics: true,
    });
    const errors = (compiled.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error);
    if (errors.length) throw new Error(errors.map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n')).join('; '));
    const module = { exports: {} };
    cache.set(file, module);
    const requireFixture = name => {
      if (name === 'react') return react;
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: Symbol.for('fixture-fragment') };
      if (name === '@tabler/icons-react') return new Proxy({}, { get: (_object, key) => `fixture-icon-${String(key)}` });
      if (file === entry && name === './CompanyDetailParts') {
        // Anchor scrolling/focus is covered by browser acceptance, not this
        // speech-state fixture. Refuse invocation rather than fake a focus pass.
        return { jumpTo() { throw new Error('jumpTo is outside the speech-state fixture; use the browser focus test'); } };
      }
      if (name.endsWith('.css')) return {};
      if (name.startsWith('.')) {
        const base = resolve(dirname(file), name);
        const candidates = [base, `${base}.ts`, `${base}.tsx`, `${base}.js`];
        if (extname(base) === '.js') candidates.push(base.slice(0, -3) + '.ts', base.slice(0, -3) + '.tsx');
        const found = candidates.find(p => existsSync(p));
        if (found) return load(found);
      }
      throw new Error(`Fixture refuses unmocked dependency: ${name}`);
    };
    new vm.Script(`(function(require,module,exports){\n${compiled.outputText}\n})`, { filename: relative(app, file) }).runInContext(context)(requireFixture, module, module.exports);
    return module.exports;
  }
  function mount(props = {}) {
    const Component = load(entry).default;
    const outer = Component({
      companyCode: 'FIXTURE', companyName: '测试档案',
      audio: { transcript: '这是用于状态验证的短文稿。', browserTts: true, sourceIds: [], contentVersion: 'fixture-v1', durationSeconds: 12 },
      ...props,
    });
    if (!outer || typeof outer.type !== 'function') throw new Error('Expected CompanyAudio to render its stateful player');
    const host = createHookHost(outer.type, outer.props);
    const render = () => host.render(run => { activeHooks = host.hooks; try { return run(); } finally { activeHooks = null; } });
    render();
    return { host, render, get tree() { return host.tree; } };
  }
  function event(utterance, name) {
    if (name === 'onstart' && synthesis.current === utterance) synthesis.pending = false;
    if ((name === 'onend' || name === 'onerror') && synthesis.current === utterance) {
      synthesis.current = null; synthesis.pending = false; synthesis.speaking = false;
    }
    if (typeof utterance[name] !== 'function') throw new Error(`Missing ${name} handler`);
    utterance[name]({ type: name.slice(2), error: name === 'onerror' ? 'synthesis-failed' : undefined });
  }
  return { load, mount, synthesis, spoken, event };
}

function nodes(tree) {
  if (tree == null || typeof tree === 'boolean') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  if (typeof tree !== 'object') return [];
  return [tree, ...nodes(tree.props?.children)];
}
function find(tree, cls) {
  return nodes(tree).find(n => String(n.props?.className || '').split(/\s+/).includes(cls));
}
function text(tree) {
  if (tree == null || typeof tree === 'boolean') return '';
  if (Array.isArray(tree)) return tree.map(text).join('');
  return typeof tree === 'object' ? text(tree.props?.children) : String(tree);
}
function click(player, cls) {
  const button = find(player.tree, cls);
  assert.ok(button && typeof button.props.onClick === 'function', `Missing usable ${cls}`);
  button.props.onClick(); player.render();
}
function state(player) {
  return { playLabel: find(player.tree, 'ca-play')?.props['aria-label'], status: text(find(player.tree, 'ca-status')), expanded: find(player.tree, 'ca-play')?.props['aria-expanded'], nextVisible: Boolean(find(player.tree, 'ca-next')) };
}
function expectEnded(player) {
  eq(state(player).status, '播放结束', 'Natural end must become the visible completed state');
  ok(/重新|重播|再听/.test(state(player).playLabel || ''), 'The completed state must offer replay');
}
function start(env, player) {
  click(player, 'ca-play');
  const utterance = env.spoken.at(-1);
  ok(utterance, 'A user action must enqueue an utterance');
  env.event(utterance, 'onstart'); player.render();
  ok(/暂停/.test(state(player).playLabel || ''), 'Start must expose a pause action');
  return utterance;
}
function test(name, run) {
  const before = assertions;
  try { run(); results.push({ name, status: 'PASS', assertions: assertions - before }); }
  catch (error) { results.push({ name, status: 'FAIL', assertions: assertions - before, reason: error.message.split('\n')[0] }); }
}

test('audioKind: empty/whitespace, opt-in TTS, recording priority', () => {
  const { audioKind } = createEnvironment().load(join(app, 'src/lib/audio-label.ts'));
  for (const sample of [undefined, {}, { url: '' }, { url: ' \n\t ', transcript: ' \n', browserTts: true }, { transcript: '文稿' }, { transcript: '文稿', browserTts: false }]) eq(audioKind(sample), 'none');
  eq(audioKind({ url: ' ', transcript: ' 文稿 ', browserTts: true }), 'script');
  eq(audioKind({ url: '/audio/sample.mp3', transcript: '文稿', browserTts: true }), 'recording');
  eq(audioKind({ url: ' https://example.invalid/sample.mp3 ' }), 'recording');
});
test('audioMinutes: invalid values and positive rounding boundaries', () => {
  const { audioMinutes } = createEnvironment().load(join(app, 'src/lib/audio-label.ts'));
  for (const value of [undefined, null, NaN, Infinity, -Infinity, -1, 0, '', '120']) eq(audioMinutes(value), null);
  for (const [seconds, minutes] of [[0.1, 1], [29, 1], [60, 1], [89, 1], [90, 2], [169.758, 3]]) eq(audioMinutes(seconds), minutes);
});
test('audioLabel: kind, length form and unknown duration stay truthful', () => {
  const { audioLabel } = createEnvironment().load(join(app, 'src/lib/audio-label.ts'));
  eq(audioLabel('none', 180, 'short'), ''); eq(audioLabel('none', 180, 'long'), '');
  eq(audioLabel('recording', 180, 'short'), '录音讲解');
  eq(audioLabel('recording', 169.758, 'long'), '录音讲解 · 约 3 分钟');
  eq(audioLabel('script', 180, 'short'), '朗读稿');
  eq(audioLabel('script', 180, 'long'), '讲解稿 · 浏览器朗读 · 约 3 分钟');
  for (const invalid of [undefined, NaN, Infinity, -1, 0]) {
    eq(audioLabel('recording', invalid, 'long'), '录音讲解');
    eq(audioLabel('script', invalid, 'long'), '讲解稿 · 浏览器朗读');
  }
});
test('TTS initial start → natural end → fresh replay', () => {
  const env = createEnvironment(), player = env.mount();
  eq(nodes(player.tree).filter(n => n.type === 'audio').length, 0, 'TTS must not create a recording element');
  const first = start(env, player);
  env.event(first, 'onend'); player.render(); expectEnded(player);
  const completed = state(player);
  first.onerror({ error: 'interrupted' }); player.render();
  eq(state(player), completed, 'A completed utterance must ignore a late error');
  first.onstart({}); player.render();
  eq(state(player), completed, 'A completed utterance must ignore a late start');
  click(player, 'ca-play');
  eq(env.spoken.length, 2, 'Replay creates a fresh utterance');
  ok(env.spoken[1] !== first); ok(state(player).status !== '播放结束');
  player.host.unmount();
});
test('TTS pause → resume keeps the utterance and accepts its natural end', () => {
  const env = createEnvironment(), player = env.mount(), first = start(env, player);
  click(player, 'ca-play'); eq(env.synthesis.pauseCalls, 1); ok(!/暂停/.test(state(player).playLabel || ''));
  click(player, 'ca-play'); eq(env.synthesis.resumeCalls, 1); eq(env.spoken.length, 1, 'Resume must not restart the narration');
  env.event(first, 'onend'); player.render(); expectEnded(player);
  player.host.unmount();
});
test('TTS collapse → reopen/resume accepts end and preserves progress', () => {
  const env = createEnvironment(), player = env.mount(), first = start(env, player);
  click(player, 'ca-collapse'); eq(state(player).expanded, false); eq(env.synthesis.pauseCalls, 1);
  click(player, 'ca-play'); eq(state(player).expanded, true); eq(env.synthesis.resumeCalls, 1); eq(env.spoken.length, 1);
  env.event(first, 'onend'); player.render(); expectEnded(player);
  player.host.unmount();
});
test('TTS unmount invalidates already-queued callbacks before cancellation', () => {
  const env = createEnvironment(), player = env.mount(), first = start(env, player);
  const callbacks = [first.onstart, first.onend, first.onerror];
  const before = env.synthesis.cancelCalls;
  const cancel = env.synthesis.cancel.bind(env.synthesis);
  env.synthesis.cancel = () => {
    // Cancellation may synchronously deliver an already-queued callback. The
    // component must retire this utterance before invoking the native cancel.
    for (const callback of callbacks) callback({ error: 'interrupted' });
    cancel();
  };
  player.host.unmount(); ok(env.synthesis.cancelCalls > before);
  for (const callback of callbacks) callback({ error: 'interrupted' });
  eq(player.host.writesAfterUnmount, 0, 'Retired speech callbacks must be ignored, not merely rely on React ignoring setters');
});
test('TTS error → cancel/rebuild ignores old start/end/error callbacks', () => {
  const env = createEnvironment(), player = env.mount(), first = start(env, player);
  const oldCallbacks = [first.onstart, first.onend, first.onerror];
  env.event(first, 'onerror'); player.render(); ok(/失败|重试/.test(state(player).status));
  const failedState = state(player);
  first.onend({}); player.render();
  eq(state(player), failedState, 'A failed utterance must ignore a late end rather than show completion');
  const cancelCount = env.synthesis.cancelCalls;
  click(player, 'ca-play'); eq(env.spoken.length, 2); ok(env.synthesis.cancelCalls > cancelCount);
  const second = env.spoken[1]; ok(second !== first);
  env.event(second, 'onstart'); player.render();
  const before = state(player);
  for (const callback of oldCallbacks) { callback({ error: 'interrupted' }); player.render(); eq(state(player), before, 'A retired utterance must not alter the replacement playback'); }
  env.event(second, 'onend'); player.render(); expectEnded(player);
  player.host.unmount();
});
test('Collapsed entry keeps its visible text in the accessible name: idle, paused, ended, error', () => {
  for (const mode of ['idle', 'paused', 'ended', 'error']) {
    const env = createEnvironment(), player = env.mount();
    if (mode !== 'idle') {
      const utterance = start(env, player);
      if (mode === 'ended' || mode === 'error') {
        env.event(utterance, mode === 'ended' ? 'onend' : 'onerror'); player.render();
      }
      click(player, 'ca-collapse');
    }
    const entryNode = find(player.tree, 'ca-entry');
    const visibleLabel = text(nodes(entryNode).find(n => n.type === 'strong'));
    const accessibleLabel = String(find(player.tree, 'ca-play')?.props['aria-label'] || '');
    eq(state(player).expanded, false, `${mode}: test must inspect a collapsed entry`);
    eq(visibleLabel, '听这家公司的讲解', `${mode}: the visible entry must exist`);
    ok(accessibleLabel.includes(visibleLabel), `${mode}: accessible name must include the visible label`);
    ok(!accessibleLabel.includes('录音'), `${mode}: a TTS entry must not claim to be a recording`);
    player.host.unmount();
  }
});
test('TTS loading → cancel rejects a late start callback', () => {
  const env = createEnvironment(), player = env.mount();
  click(player, 'ca-play');
  const utterance = env.spoken[0];
  ok(utterance, 'Loading must have queued an utterance');
  ok(/取消.*加载/.test(state(player).playLabel || ''), 'Exercise loading before any start event');
  click(player, 'ca-play');
  eq(env.synthesis.pauseCalls, 1, 'Cancelling loading must pause speech');
  const cancelledState = state(player);
  ok(!/暂停/.test(cancelledState.playLabel || ''), 'Cancelled loading must not claim playback');
  env.event(utterance, 'onstart'); player.render();
  eq(state(player), cancelledState, 'A late start must not reactivate cancelled playback');
  player.host.unmount();
});
test('TTS loading → collapse rejects a late start callback', () => {
  const env = createEnvironment(), player = env.mount();
  click(player, 'ca-play');
  const utterance = env.spoken[0];
  ok(utterance, 'Loading must have queued an utterance');
  ok(/取消.*加载/.test(state(player).playLabel || ''), 'Exercise loading before any start event');
  click(player, 'ca-collapse');
  eq(state(player).expanded, false); eq(env.synthesis.pauseCalls, 1);
  const collapsedState = state(player);
  env.event(utterance, 'onstart'); player.render();
  eq(state(player), collapsedState, 'A late start must not change the collapsed state');
  // The collapsed accessible label intentionally hides the playback state.
  // Reopening distinguishes resume from the incorrect playing→pause branch.
  click(player, 'ca-play');
  eq(env.synthesis.resumeCalls, 1, 'After the ignored late start, reopening must resume rather than pause again');
  eq(env.synthesis.pauseCalls, 1, 'A late start must not set playing=true behind the collapsed entry');
  eq(env.spoken.length, 1, 'Reopening resumes the original queued utterance');
  player.host.unmount();
});


test('ended and error collapse resets the entry, next section and late callbacks', () => {
  for (const outcome of ['onend','onerror']) {
    const env=createEnvironment(), player=env.mount(), utterance=start(env,player);
    env.event(utterance,outcome); player.render();
    click(player,'ca-collapse');
    const collapsed=state(player);
    eq(collapsed.expanded,false); eq(collapsed.nextVisible,false);
    ok(!/重新|重试|播放结束|失败/.test(collapsed.playLabel + collapsed.status),'Collapse clears completed/error state');
    for (const callback of [utterance.onstart,utterance.onend,utterance.onerror]) {
      callback({error:'late'}); player.render(); eq(state(player),collapsed,'Retired event cannot undo reset');
    }
    player.host.unmount();
  }
});
test('active speech collapse ignores a late end/error without restoring completion', () => {
  for (const outcome of ['onend','onerror']) {
    const env=createEnvironment(), player=env.mount(), utterance=start(env,player);
    click(player,'ca-collapse'); const collapsed=state(player);
    env.event(utterance,outcome); player.render(); eq(state(player),collapsed);
    click(player,'ca-play'); eq(env.spoken.length,2,'Ended/failed retired speech starts a fresh utterance');
    player.host.unmount();
  }
});
test('recording ended/error resets on collapse; delayed media events stay hidden', () => {
  for (const outcome of ['onEnded','onError']) {
    const env=createEnvironment(), player=env.mount({audio:{url:'/audio/fixture.mp3',transcript:'fixture',sourceIds:[],contentVersion:'fixture'}});
    click(player,'ca-play');
    let media=nodes(player.tree).find(n=>n.type==='audio'); media.props[outcome](); player.render();
    click(player,'ca-collapse'); const collapsed=state(player);
    ok(!/重新|重试|播放结束|失败/.test(collapsed.playLabel + collapsed.status)); eq(collapsed.nextVisible,false);
    media=nodes(player.tree).find(n=>n.type==='audio'); media.props.onEnded(); media.props.onError(); player.render();
    eq(state(player),collapsed); player.host.unmount();
  }
});
test('seven-question narration is exact current visible text, unique current sources and no duration', () => {
  const env=createEnvironment(); const helpers=env.load(join(app,'src/lib/seven-question-audio.ts'));
  for (const code of JSON.parse(readFileSync(join(app,'content-selection.json'),'utf8')).sevenQuestions.map(r=>r.code)) {
    const raw=readFileSync(join(app,`content/company-seven-questions/${code}.json`));
    const content=JSON.parse(raw), digest=createHash('sha256').update(raw).digest('hex');
    const audio=helpers.sevenQuestionAudio(content,digest);
    eq(audio.transcript,[content.introduction,...content.answers.map(a=>a.text)].join('\n\n'));
    eq(audio.contentVersion,digest); eq(audio.browserTts,true); eq(audio.url,undefined); eq(audio.durationSeconds,undefined);
    eq(audio.sourceIds,content.sources.map(s=>`seven:${s.id}`));
    eq(helpers.sevenQuestionAudioSources(content).map(s=>s.id),audio.sourceIds);
  }
});

const failed = results.filter(row => row.status !== 'PASS');
console.log(JSON.stringify({
  testKind: 'simulated React state and SpeechSynthesis lifecycle; NOT real audio/TTS playback',
  status: failed.length ? 'FAIL' : 'PASS', cases: results.length,
  passed: results.length - failed.length, failed: failed.length, assertions,
  typescriptVersion: ts.version, sourceHashes: Object.fromEntries(sourceHashes), results,
  limitations: ['No browser layout, focus, audio audibility, voice availability, speech timing or native pause/resume behavior is certified.', 'CompanyAudio imports a narrow jumpTo stub that throws if called; CompanyDetailParts and its unrelated dependencies are not exercised.', 'No data files, server, network, filesystem mutations or dependency installation are performed by this test.', 'Invalid-URL protocol policy is not invented here: URL safety remains a separately reviewed renderer/catalogue contract.'],
}, null, 2));
process.exitCode = failed.length ? 1 : 0;
