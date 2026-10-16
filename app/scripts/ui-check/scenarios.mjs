// UI acceptance scenarios. Each scenario receives { page, base, shot, check, data } and exercises one surface.
// `check(name, ok, detail)` records a PASS/FAIL line; `shot(name)` saves a screenshot for the contact sheet.
// Codes default to boards/companies that exist in every runtime snapshot; override with --board / --stock / --company.

const css = (page, sel, prop) => page.evaluate(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); return e ? getComputedStyle(e).${prop} : null; })()`);
const text = (page, sel) => page.evaluate(`document.querySelector(${JSON.stringify(sel)})?.textContent ?? null`);
const atlasReady = `document.querySelector('#app') && !document.getElementById('boot') && Number(document.getElementById('s-node')?.textContent) > 0`;

export const scenarios = [
  {
    id: 'desktop', title: '桌面 · 目录 → 档案 → 星图 → 抽屉 → 关系卡',
    async run({ page, base, shot, check, skip, data }) {
      await page.mobile(false);
      await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

      await page.navigate(`${base}#/companies`);
      await page.waitFor(`document.querySelectorAll('.cl-company-result').length > 0`, 40000);
      check('公司目录渲染', (await page.evaluate(`document.querySelectorAll('.cl-company-result').length`)) >= 1, `目录计数 ${await text(page, '.cl-directory-counts strong')}`);
      check('页头 · 公司目录高亮', (await text(page, '.company-library .site-header .site-nav a[aria-current=page]')) === '公司目录');
      await shot('companies-light');

      await page.navigate(`${base}#/company/${data.company}`);
      await page.waitFor(`document.querySelector('.cr-document h1')`, 40000);
      check('公司档案渲染', true, `${await text(page, '.cr-document h1')} · 七问 ${await text(page, '.cq-progress')}`);
      const headerH = await page.evaluate(`document.querySelector('.site-header')?.getBoundingClientRect().height`);
      check('章节导航贴在页头下方', Math.abs(parseFloat(await css(page, '.cr-chapter-nav', 'top')) - headerH) < 1, `页头 ${headerH}px`);
      await shot('company-light');

      await page.navigate(`${base}#kind=industry`);
      await page.waitFor(atlasReady, 40000); await page.sleep(1500);
      check('星图渲染', true, `节点 ${await text(page, '#s-node')} · 边 ${await text(page, '#s-edge')}`);
      check('工具条无主题按钮，页头有', await page.evaluate(`!document.getElementById('t-theme') && !!document.querySelector('#app .site-header .site-theme')`));

      await page.click(`.directory-row[data-code="${data.board}"]`);
      await page.waitFor(`document.querySelector('#drawer h2')`, 10000);
      const drill = await page.rect('.dr-head .drillbtn');
      check('抽屉 · 主行动在头部首屏', drill && drill.y < 600, `y=${Math.round(drill?.y)}`);
      check('抽屉 · 数据说明默认折叠', (await page.evaluate(`document.querySelector('.data-notes')?.open`)) === false);
      check('抽屉 · 候选 ≤3 张', (await page.evaluate(`document.querySelectorAll('.candidate-card').length`)) <= 3);
      check('路由记住板块', (await page.evaluate('location.hash')).includes(`n=${data.board}`));
      await shot('atlas-board-light');

      await page.click('.dr-head .drillbtn');
      await page.waitFor(`document.querySelector('.crumb b')`, 15000); await page.sleep(1500);
      check('展开个股星图', (await page.evaluate('location.hash')).includes(`c=${data.board}`), await text(page, '.atlas-context p'));
      await page.click('.directory-row');
      await page.waitFor(`document.querySelector('#drawer .drillbtn')?.textContent?.includes('打开公司档案')`, 10000);
      check('个股抽屉 · 打开公司档案在头部，速览无重复按钮', await page.evaluate(`document.querySelector('#drawer .dr-head .drillbtn')?.textContent?.includes('打开公司档案') && !document.querySelector('.company-peek .company-read-button')`), await text(page, '#drawer h2'));
      if (await page.evaluate(`!!document.querySelector('.relation-row')`)) {
        await page.click('.relation-row'); await page.waitFor(`!!document.getElementById('relation-card')`, 8000);
        check('关系卡打开', true, await text(page, '#relation-card .pair-heading'));
      } else skip('关系卡打开', '该个股没有直接连线，无法在此数据上演示');
      await page.click('#app .site-header .site-theme'); await page.sleep(300);
      check('页头主题切换', (await page.evaluate('document.documentElement.dataset.theme')) === 'dark');
      await shot('atlas-stock-dark');
      await page.click('#app .site-header .site-theme');
    },
  },
  {
    id: 'mobile', title: '手机 390px · 顶栏 / 底部面板 / 触摸手势',
    async run({ page, base, shot, check, skip, data }) {
      await page.mobile(true);
      await page.navigate(`${base}#kind=industry`);
      await page.waitFor(atlasReady, 40000); await page.sleep(1500);
      const stage = await page.rect('#stage'), sheet = await page.rect('.side-list');
      check('舞台全宽', stage && Math.round(stage.w) === 390 && stage.x === 0, `${Math.round(stage?.w)}×${Math.round(stage?.h)}`);
      check('目录面板收起 60px 贴底', sheet && Math.round(sheet.h) === 60 && Math.round(sheet.y + sheet.h) === 844);
      check('工具条精简', (await css(page, '#t-spin', 'display')) === 'none');
      check('无横向溢出', await page.evaluate('document.documentElement.scrollWidth <= 390'));
      await shot('mobile-peek-light');

      const handle = await page.rect('.sheet-handle');
      await page.touchDrag(handle.cx, handle.cy, handle.cy - 120); await page.sleep(500);
      check('上滑展开目录面板', (await page.rect('.side-list')).h > 400);
      await shot('mobile-sheet-open-light');

      const row = await page.rect(`.directory-row[data-code="${data.board}"]`);
      await page.tap(row.cx, row.cy);
      await page.waitFor(`document.querySelector('#drawer h2')`, 10000); await page.sleep(500);
      const drawer = await page.rect('#drawer');
      check('点选后面板收起、详情为底部面板、工具条隐藏', (await css(page, '.side-list', 'display')) === 'none' && (await css(page, '#tools', 'display')) === 'none' && drawer.h > 500);
      await shot('mobile-drawer-light');
      await page.click('.drawer-close'); await page.waitFor(`!document.querySelector('#drawer h2')`, 5000); await page.sleep(400);

      // Rotation evidence: with auto-spin off, the projected label positions must move after a one-finger drag.
      if (await page.evaluate(`document.getElementById('t-spin').classList.contains('on')`)) await page.evaluate(`document.getElementById('t-spin').click()`);
      await page.sleep(600);
      const labelPos = () => page.evaluate(`[...document.querySelectorAll('#labels .lab')].filter(e => e.style.opacity !== '0').slice(0, 12).map(e => e.style.transform || e.style.left + '/' + e.style.top).join('|')`);
      const before = await labelPos();
      await page.touchDrag(195, 400, 480); await page.sleep(500);
      const after = await labelPos();
      check('单指拖拽旋转视角（标签投影位置变化）', before && after && before !== after, `${before.split('|').length} 个标签位置${before === after ? '未变' : '已变'}`);
      const z0 = parseInt(await text(page, '#zlvl'));
      await page.pinch(195, 420, 80, 240); await page.sleep(400);
      const z1 = parseInt(await text(page, '#zlvl'));
      await page.pinch(195, 420, 240, 100); await page.sleep(400);
      const z2 = parseInt(await text(page, '#zlvl'));
      check('双指张开拉近、捏合拉远', z1 > z0 && z2 < z1, `${z0}% → ${z1}% → ${z2}%`);
      check('捏合不触发选中', (await text(page, '#hud-sel')) === '未选中');
      await shot('mobile-after-pinch-light');

      await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'pointer', value: 'coarse' }, { name: 'prefers-reduced-motion', value: 'reduce' }] });
      await page.navigate(`${base}#kind=industry`); await page.waitFor(atlasReady, 40000); await page.sleep(800);
      const rm = await page.evaluate(`[document.getElementById('t-spin').classList.contains('on'), document.getElementById('t-flow').classList.contains('on')]`);
      check('减少动态 · 自转与光点默认关', rm[0] === false && rm[1] === false);

      await page.evaluate(`localStorage.removeItem('a-share-knowledge-theme')`);
      await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: 'dark' }] });
      await page.navigate(`${base}#/home`); await page.waitFor(`document.querySelector('.brand-home')`, 20000); await page.sleep(500);
      check('系统深色 · 无保存偏好时为夜间', (await page.evaluate('document.documentElement.dataset.theme')) === 'dark');
      await shot('mobile-home-system-dark');
      await page.navigate(`${base}#/company/${data.company}`); await page.waitFor(`document.querySelector('.cr-document h1')`, 40000); await page.sleep(500);
      check('手机档案页无横向溢出', await page.evaluate('document.documentElement.scrollWidth <= 390'));
      await shot('mobile-company-dark');
    },
  },
  {
    id: 'reading', title: '试听与阅读转化 · 入口 / 接着读 / 样板桥',
    async run({ page, base, shot, check, data }) {
      const names = [
        '讲解入口有文字', '入口命中区 ≥44px', '点击前不加载录音', '真实播放开始',
        '播完出现「接着读」', '下一家指向另一家已核读公司', '讲解依据可打开', '对照七个答案',
        '朗读稿入口', '无解读档案有样板桥', '有解读档案无样板桥', '目录显示讲解徽标',
        '手机 · 入口占满一行', '手机 · 播完无横向溢出', '手机 · 样板桥单列无溢出', '朗读稿不称录音',
      ];
      const results = new Map();
      const company = data.company, plain = data.plain, tts = data.tts;
      const errorText = error => String(error?.message ?? error).split('\n')[0];
      const require = (ok, detail) => { if (!ok) throw new Error(detail); };
      const attempt = async (label, action) => {
        try { return { ok: true, value: await action() }; }
        catch (error) { return { ok: false, error: `${label}：${errorText(error)}` }; }
      };
      const verify = async (id, action) => {
        const result = await attempt(`R${id}`, action);
        results.set(id, { ok: result.ok, detail: result.ok ? String(result.value ?? '') : result.error });
        return result.ok;
      };
      const need = result => { require(result?.ok, result?.error || '前置状态不可用'); return result.value; };
      const visible = selector => page.evaluate(`(() => {
        const e = document.querySelector(${JSON.stringify(selector)});
        if (!e) return false;
        const r = e.getBoundingClientRect(), s = getComputedStyle(e);
        return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && Number(s.opacity) !== 0;
      })()`);
      const setTheme = async theme => {
        if (await page.evaluate('document.documentElement.dataset.theme') !== theme) {
          await page.click('.site-header .site-theme');
          await page.waitFor(`document.documentElement.dataset.theme === ${JSON.stringify(theme)}`, 3000);
        }
      };
      const open = async (route, ready, theme = 'light', mobile = false) => {
        await page.mobile(mobile);
        if (!mobile) await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
        await page.navigate(`${base}${route}`);
        await page.waitFor(`location.hash === ${JSON.stringify(route)} && (${ready})`, 40000);
        await setTheme(theme);
      };
      const openCompany = async (code, theme = 'light', mobile = false) => {
        require(typeof code === 'string' && /^\d{6}\.[A-Z]+$/.test(code), '缺少或无效的公司数据参数');
        await open(`#/company/${code}`, `document.querySelector('.cr-document h1')`, theme, mobile);
        if (code === company || code === tts) {
          await page.waitFor(`document.querySelector('.company-audio[data-company-code="${code}"] .ca-play')`, 15000);
        }
      };
      const capture = async (name, id, selector) => {
        const result = await attempt(`截图 ${name}`, async () => {
          if (selector) await page.evaluate(`document.querySelector(${JSON.stringify(selector)})?.scrollIntoView({ block: 'center', behavior: 'instant' })`);
          await shot(name);
        });
        const previous = results.get(id) || { ok: true, detail: '' };
        results.set(id, { ok: previous.ok && result.ok, detail: [previous.detail, result.ok ? `截图 ${name}` : result.error].filter(Boolean).join('；') });
      };
      const startRecording = async () => {
        require(await page.evaluate(`!!document.querySelector('.company-audio audio')`), '缺少录音 audio 元素');
        require(await visible('.ca-play'), '缺少可点击的播放入口');
        // CDP mouse events provide the user gesture; never call audio.play() from evaluation.
        await page.click('.ca-play');
        await page.waitFor(`(() => { const a = document.querySelector('.company-audio audio'); return a && !a.paused && a.currentTime > 0; })()`, 15000);
        return page.evaluate(`(() => { const a = document.querySelector('.company-audio audio'); return { paused: a.paused, currentTime: a.currentTime, duration: a.duration }; })()`);
      };
      const finishRecording = async () => {
        // Seek is allowed by R5. Only a trusted native ended event plus audio.ended counts.
        const started = Date.now();
        const ended = await page.evaluate(`new Promise(resolve => {
          const a = document.querySelector('.company-audio audio');
          if (!a || a.paused || !Number.isFinite(a.duration) || a.duration <= 0) {
            resolve({ ok: false, reason: '录音未在播放或没有可定位时长' }); return;
          }
          let timer;
          const done = value => { clearTimeout(timer); a.removeEventListener('ended', onEnd); a.removeEventListener('error', onError); resolve(value); };
          const onEnd = event => {
            if (!event.isTrusted) return;
            done({ ok: a.ended && a.currentTime > 0, trusted: event.isTrusted, ended: a.ended, currentTime: a.currentTime, duration: a.duration });
          };
          const onError = () => done({ ok: false, reason: '定位后发生真实媒体错误' });
          a.addEventListener('ended', onEnd); a.addEventListener('error', onError);
          timer = setTimeout(() => done({ ok: false, reason: '14 秒内未收到真实 ended' }), 14000);
          try { a.currentTime = Math.max(0, a.duration - 0.5); }
          catch (error) { done({ ok: false, reason: error.message }); }
        })`);
        require(ended?.ok && ended.trusted && ended.ended, ended?.reason || '未确认真实播放结束');
        await page.waitFor(`(() => { const e = document.querySelector('.ca-next'); return e && e.getBoundingClientRect().height > 0 && getComputedStyle(e).visibility !== 'hidden'; })()`, Math.max(1, 15000 - (Date.now() - started)));
        const actions = await page.evaluate(`['.ca-next-quickread', '.ca-next-sources', '.ca-next-company'].map(selector => {
          const e = document.querySelector('.ca-next ' + selector), r = e?.getBoundingClientRect();
          return Boolean(e && r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden');
        })`);
        require(actions.length === 3 && actions.every(Boolean), '接着读缺少可见的三项动作');
        return JSON.stringify(ended);
      };
      const searchResult = async code => {
        require(typeof code === 'string' && /^\d{6}\.[A-Z]+$/.test(code), '缺少或无效的目录数据参数');
        await page.click('.cl-search-input input');
        await page.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
        await page.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'a', code: 'KeyA', windowsVirtualKeyCode: 65, modifiers: 2 });
        await page.send('Input.insertText', { text: code.slice(0, 6) });
        const row = `[...document.querySelectorAll('.cl-company-result')].find(e => e.querySelector('.cl-company-code')?.textContent?.trim() === ${JSON.stringify(code.slice(0, 6))})`;
        await page.waitFor(row, 10000);
        return page.evaluate(`(() => { const e = ${row}; return { text: e.textContent, badge: e.querySelector('.cl-audio-badge')?.textContent ?? null }; })()`);
      };
      let fatal = '';
      try {
        const catalog = await attempt('首页样板目录', async () => {
          await open('#/home', `document.querySelector('.brand-home')`);
          await page.waitFor(`document.querySelectorAll('.hv-sample-list a[href^="#/company/"]').length > 0`, 10000);
          return page.evaluate(`[...document.querySelectorAll('.hv-sample-list a')].map(e => /^#\\/company\\/([^/?#]+)$/.exec(e.getAttribute('href') || '')?.[1]).filter(Boolean)`);
        });
        const sampleCodes = () => { const codes = need(catalog); require(codes.length > 0, '首页样板目录为空'); return codes; };
        const recordingPage = await attempt('桌面录音档案', () => openCompany(company));
        await verify(1, async () => {
          need(recordingPage); const entry = await text(page, '.ca-play .ca-entry');
          require(await visible('.ca-play .ca-entry') && entry?.includes('听这家公司的讲解') && entry.includes('录音讲解 · 约'), '缺少可见的入口主行或录音时长称呼');
          return entry;
        });
        await verify(2, async () => {
          need(recordingPage); const r = await page.rect('.ca-play');
          require(await visible('.ca-play') && r?.w >= 44 && r.h >= 44, '播放入口宽或高不足 44px'); return JSON.stringify(r);
        });
        await verify(3, async () => {
          need(recordingPage);
          require(await page.evaluate(`(() => { const a = document.querySelector('.company-audio audio'); return !!a && !a.hasAttribute('src'); })()`), '缺少 audio 或点击前已带 src 属性');
          return 'audio 存在，点击前无 src 属性';
        });
        await capture('reading-entry-light', 3, '.ca-play');
        let desktopPlayback;
        await verify(4, async () => { need(recordingPage); desktopPlayback = await startRecording(); return JSON.stringify(desktopPlayback); });
        await verify(5, async () => { require(desktopPlayback, 'R4 未确认真实播放，不能验证 ended'); return finishRecording(); });
        await verify(6, async () => {
          need(recordingPage); const codes = sampleCodes();
          const href = await page.evaluate(`document.querySelector('.ca-next-company')?.getAttribute('href') ?? null`);
          const next = /^#\/company\/([^/?#]+)$/.exec(href || '')?.[1];
          const currentIndex = codes.indexOf(company);
          require(currentIndex >= 0, '当前录音公司不在首页样板目录');
          const expectedNext = [...codes.slice(currentIndex + 1), ...codes.slice(0, currentIndex)].find(code => code !== company);
          require(await visible('.ca-next-company') && expectedNext && next === expectedNext, '下一家未按首页样板顺序循环或未排除当前公司');
          return `${href}；目录顺序期望 ${expectedNext}`;
        });
        await verify(7, async () => {
          need(recordingPage); require(await visible('.ca-next-sources'), '缺少可见的讲解依据动作');
          try {
            await page.click('.ca-next-sources');
            await page.waitFor(`document.querySelectorAll('.cr-source-drawer[open] .cr-source-card').length >= 1`, 5000);
            return `出处卡片 ${await page.evaluate(`document.querySelectorAll('.cr-source-drawer[open] .cr-source-card').length`)}`;
          } finally {
            if (await page.evaluate(`!!document.querySelector('.cr-source-drawer[open]')`)) {
              await page.click('.cr-source-drawer[open] button[aria-label="关闭资料出处"]');
              await page.waitFor(`!document.querySelector('.cr-source-drawer[open]')`, 3000);
            }
          }
        });
        await capture('reading-ended-light', 7, '.ca-next');
        await verify(8, async () => {
          need(recordingPage); require(await visible('.ca-next-quickread'), '缺少可见的七问动作');
          await page.click('.ca-next-quickread');
          const anchorState = `(() => {
            const e = document.getElementById('cq-title'), r = e?.getBoundingClientRect();
            const coveredBottom = Math.max(0, ...[...document.querySelectorAll('.site-header, .cr-chapter-nav')].map(item => {
              const s = getComputedStyle(item), box = item.getBoundingClientRect();
              return ['fixed', 'sticky'].includes(s.position) && box.top < innerHeight && box.bottom > 0 ? box.bottom : 0;
            }));
            return { exists: !!r, top: r?.top, height: r?.height, coveredBottom, focused: document.activeElement === e, viewportHeight: innerHeight };
          })()`;
          await page.waitFor(`(() => { const s = ${anchorState}; return s.exists && s.height > 0 && s.focused && s.top >= s.coveredBottom && s.top < s.viewportHeight; })()`, 5000);
          return JSON.stringify(await page.evaluate(anchorState));
        });
        await verify(9, async () => {
          await openCompany(tts, 'dark'); const entry = await text(page, '.ca-entry');
          require(await visible('.ca-entry') && entry?.includes('讲解稿 · 浏览器朗读'), '缺少可见的浏览器朗读入口称呼');
          require(await page.evaluate(`!document.querySelector('.company-audio audio')`), '朗读稿不应创建 audio 元素'); return entry;
        });
        await capture('reading-tts-dark', 9, '.ca-play');
        const plainPage = await attempt('无解读档案', () => openCompany(plain));
        await verify(10, async () => {
          need(plainPage); const codes = sampleCodes(); require(!codes.includes(plain), '--plain 不能是已核读样板');
          require(await visible('.cr-sample-bridge'), '无解读档案未出现可见样板桥');
          const hrefs = await page.evaluate(`[...document.querySelectorAll('.cr-sample-bridge .cr-sample-card')].map(e => e.getAttribute('href'))`);
          require(hrefs.length >= 1 && hrefs.length <= 3 && hrefs.every(href => { const code = /^#\/company\/([^/?#]+)$/.exec(href || '')?.[1]; return code && code !== plain && codes.includes(code); }), '样板桥卡片数量或目的公司不符合要求');
          return hrefs.join('，');
        });
        // Capture the plain page before R11 navigates away from it.
        await capture('reading-plain-bridge-light', 10, '.cr-sample-bridge');
        await verify(11, async () => {
          await openCompany(company); require(sampleCodes().includes(company), '--company 不在已核读样板目录');
          require(await page.evaluate(`!document.querySelector('.cr-sample-bridge')`), '有解读档案不应出现样板桥'); return '已核读档案无样板桥';
        });
        await verify(12, async () => {
          await open('#/companies', `document.querySelector('.cl-company-result')`);
          const recorded = await searchResult(company), script = await searchResult(tts);
          require(recorded.badge?.includes('录音讲解') && script.badge?.includes('朗读稿'), '两家公司缺少相应目录讲解徽标');
          return `录音公司：${recorded.badge}；朗读公司：${script.badge}`;
        });
        const mobilePage = await attempt('手机录音档案', () => openCompany(company, 'dark', true));
        await verify(13, async () => {
          need(mobilePage);
          const layout = await page.evaluate(`(() => {
            const button = document.querySelector('.ca-play'), parent = document.querySelector('.cr-name-audio'), h1 = parent?.querySelector('h1');
            if (!button || !parent || !h1) return null;
            const b = button.getBoundingClientRect(), p = parent.getBoundingClientRect(), h = h1.getBoundingClientRect();
            return { buttonWidth: b.width, parentWidth: p.width, top: b.top, headingBottom: h.bottom, collapsed: button.getAttribute('aria-expanded') === 'false', entry: !!button.querySelector('.ca-entry') };
          })()`);
          require(layout?.collapsed && layout.entry && Math.abs(layout.buttonWidth - layout.parentWidth) <= 1 && layout.top >= layout.headingBottom, '收起态入口未满宽或不在公司名下方');
          return JSON.stringify(layout);
        });
        await verify(14, async () => {
          need(mobilePage); const playback = await startRecording();
          // Expanded controls use a 44px round button; R13 measured the collapsed full-width entry separately.
          const expanded = await page.evaluate(`(() => { const b = document.querySelector('.ca-play'), r = b?.getBoundingClientRect(); return b && { width: r.width, height: r.height, radius: getComputedStyle(b).borderRadius, expanded: b.getAttribute('aria-expanded') === 'true', entry: !!b.querySelector('.ca-entry') }; })()`);
          const ended = await finishRecording();
          const width = await page.evaluate('document.documentElement.scrollWidth');
          require(expanded?.expanded && !expanded.entry && Math.abs(expanded.width - 44) <= 1 && Math.abs(expanded.height - 44) <= 1 && parseFloat(expanded.radius) >= 22, '展开态未恢复 44px 圆钮');
          require(await visible('.ca-next') && width <= 390, `播完后横向宽度 ${width}px`);
          return `播放 ${JSON.stringify(playback)}；真实结束 ${ended}；展开 ${JSON.stringify(expanded)}；scrollWidth=${width}`;
        });
        await capture('mobile-reading-ended-dark', 14, '.ca-next');
        await verify(15, async () => {
          await openCompany(plain, 'light', true); const codes = sampleCodes(); require(!codes.includes(plain), '--plain 不能是已核读样板');
          require(await visible('.cr-sample-bridge'), '手机无可见样板桥');
          const cards = await page.evaluate(`[...document.querySelectorAll('.cr-sample-bridge .cr-sample-card')].map(e => { const r = e.getBoundingClientRect(); return { x: r.x, width: r.width, height: r.height }; })`);
          const width = await page.evaluate('document.documentElement.scrollWidth');
          require(cards.length >= 1 && cards.length <= 3 && cards.every(r => r.width > 0 && r.height > 0 && Math.abs(r.x - cards[0].x) <= 1) && width <= 390, `卡片未单列或横向溢出：${JSON.stringify(cards)}，scrollWidth=${width}`);
          return `卡片 ${cards.length}，x=${cards[0].x}，scrollWidth=${width}`;
        });
        await capture('mobile-plain-bridge-light', 15, '.cr-sample-bridge');
        await verify(16, async () => {
          // Inspect all four script surfaces even if an earlier surface is wrong or unavailable.
          const surfaces = [];
          surfaces.push(await attempt('档案入口与七问层', async () => {
            await openCompany(tts);
            const labels = await page.evaluate(`(() => { const b = document.querySelector('.ca-play'); return { button: b?.textContent, aria: b?.getAttribute('aria-label'), layers: document.querySelector('.cq-layers')?.textContent }; })()`);
            require(labels.button?.includes('讲解稿 · 浏览器朗读') && labels.aria?.includes('讲解稿 · 浏览器朗读') && labels.layers?.includes('讲解稿 · 浏览器朗读') && Object.values(labels).every(v => v && !v.includes('录音')), '朗读稿入口、无障碍名或七问层缺失/含录音/称呼不符');
            return '入口文本、无障碍名、七问层均为朗读稿';
          }));
          surfaces.push(await attempt('目录结果', async () => {
            await open('#/companies', `document.querySelector('.cl-company-result')`); const result = await searchResult(tts);
            require(result.badge?.includes('朗读稿') && result.text && !result.text.includes('录音'), '朗读目录结果缺失、徽标错误或含录音'); return '目录结果为朗读稿';
          }));
          surfaces.push(await attempt('首页样板卡', async () => {
            await open('#/home', `document.querySelector('.brand-home')`);
            const card = await page.evaluate(`document.querySelector('.hv-sample-list a[href="#/company/${tts}"]')?.textContent ?? null`);
            require(card?.includes('讲解稿 · 浏览器朗读') && !card.includes('录音'), '朗读首页卡缺失、称呼错误或含录音'); return '首页样板卡为浏览器朗读';
          }));
          surfaces.push(await attempt('录音入口正向对照', async () => {
            await openCompany(company); const entry = await text(page, '.ca-entry');
            require(await visible('.ca-entry') && entry?.includes('录音讲解'), '录音公司入口缺少录音讲解称呼'); return '录音入口保留录音讲解';
          }));
          const detail = surfaces.map(s => s.ok ? s.value : s.error).join('；');
          require(surfaces.every(s => s.ok), detail); return detail;
        });
      } catch (error) { fatal = errorText(error); }
      finally {
        const cleanup = await attempt('恢复浅色与媒体模拟', async () => {
          await page.send('Emulation.setEmulatedMedia', { features: [] });
          await setTheme('light');
          await page.mobile(false);
        });
        if (!cleanup.ok) {
          const previous = results.get(16);
          results.set(16, { ok: false, detail: [previous?.detail, cleanup.error].filter(Boolean).join('；') });
        }
        // Exactly 16 real PASS/FAIL records, including missing prerequisites; never use SKIP.
        names.forEach((name, index) => {
          const id = index + 1, result = results.get(id) || { ok: false, detail: `未能执行：${fatal || '前置步骤中断'}` };
          check(`R${id} · ${name}`, result.ok, result.detail);
        });
      }
    },
  },
];
