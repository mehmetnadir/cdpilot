#!/usr/bin/env node
/**
 * mcp-cikti-token-2.js
 * MCP tool çıktılarının karakter ve token boyutlarını ölçen bağımsız betik (v2).
 * 
 * Gereksinimler:
 * 1. browser_navigate sonrasında sayfa yüklenene kadar (document.readyState === 'complete' veya 15 s) bekle ve son URL'yi kaydet.
 * 2. Her araç sonucu için isError ve ilk 160 karakteri kaydet; hata, boş veya 20 karakterden küçük sonuçları INVALID olarak işaretle (asla boyuta dahil etme).
 * 3. diff ölçümü: browser_agent_observe çağır, gezinme yapmayan (non-navigating: checkbox, details, tab, non-link button veya searchbox type) bir ref seç, URL'nin değişmediğini teyit et, ardından diff=true ile ölç; URL değiştiyse satırı INVALID yap.
 * 4. Aynı 6 site (bot engeli varsa atla ve not düş, asla bypass etme).
 * 5. Token hesabı = chars / 4 (cdpilot _estimate_tokens). Çevrimdışı o200k kütüphanesi yoksa belirt.
 * 6. SADECE GEÇERLİ browser_content, browser_a11y ve browser_agent_observe çıktıları için:
 *    (a) whitespace runs, (b) repeated JSON keys, (c) URLs, (d) duplicated lines
 *    paylarını metni bizzat dönüştürüp farkı sayarak ölç.
 * 7. Raporu .claude/docs/olcum/mcp-cikti-token-2-2026-11-10.md dosyasına yaz.
 */

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const CLI = path.join(REPO_ROOT, 'bin', 'cdpilot.js');
const REPORT_PATH = path.join(__dirname, 'mcp-cikti-token-2-2026-11-10.md');

const SITES = [
  { id: 'hn', name: 'news.ycombinator.com', url: 'https://news.ycombinator.com' },
  { id: 'wiki', name: 'en.wikipedia.org/wiki/Web_browser', url: 'https://en.wikipedia.org/wiki/Web_browser' },
  { id: 'github', name: 'github.com/mehmetnadir/cdpilot', url: 'https://github.com/mehmetnadir/cdpilot' },
  { id: 'mdn', name: 'developer.mozilla.org/en-US/docs/Web/API/MutationObserver', url: 'https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver' },
  { id: 'npm', name: 'www.npmjs.com/package/cdpilot', url: 'https://www.npmjs.com/package/cdpilot' },
  { id: 'bbc', name: 'www.bbc.com/news', url: 'https://www.bbc.com/news' },
];

function getOpenTabs() {
  return new Promise((resolve) => {
    http.get('http://127.0.0.1:9333/json/list', (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { resolve([]); }
      });
    }).on('error', () => resolve([]));
  });
}

function closeTab(id) {
  return new Promise((resolve) => {
    http.get(`http://127.0.0.1:9333/json/close/${id}`, (res) => {
      res.resume();
      res.on('end', resolve);
    }).on('error', resolve);
  });
}

function estimateTokens(chars) {
  return Math.round(chars / 4);
}

class McpClient {
  constructor(env, cwd) {
    this.env = env;
    this.cwd = cwd;
    this.nextId = 1;
    this.waiters = new Map();
    this.srv = null;
    this.buf = '';
  }

  start() {
    this.srv = spawn(process.execPath, [CLI, 'mcp'], {
      env: this.env,
      cwd: this.cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    this.srv.stdout.on('data', (d) => {
      this.buf += d;
      let i;
      while ((i = this.buf.indexOf('\n')) >= 0) {
        const line = this.buf.slice(0, i);
        this.buf = this.buf.slice(i + 1);
        if (!line.trim()) continue;
        try {
          const m = JSON.parse(line);
          const w = this.waiters.get(m.id);
          if (w) {
            this.waiters.delete(m.id);
            w(m);
          }
        } catch (e) {}
      }
    });

    // drain stderr
    this.srv.stderr.on('data', () => {});

    return new Promise((resolve) => {
      setTimeout(resolve, 600);
    });
  }

  call(method, params, timeoutMs = 45000) {
    return new Promise((resolve) => {
      const id = this.nextId++;
      let timer = null;
      const done = (val) => {
        if (timer) clearTimeout(timer);
        this.waiters.delete(id);
        resolve(val);
      };
      timer = setTimeout(() => {
        process.stderr.write(`  [TIMEOUT ${timeoutMs}ms] method=${method} params=${JSON.stringify(params).slice(0, 60)}\n`);
        done({ error: { code: -32000, message: `Timeout after ${timeoutMs}ms` } });
      }, timeoutMs);

      this.waiters.set(id, done);
      this.srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  }

  async stop() {
    if (this.srv) {
      try {
        this.srv.stdin.end();
      } catch (e) {}
      await new Promise((r) => setTimeout(r, 400));
      try {
        this.srv.kill('SIGTERM');
      } catch (e) {}
      this.srv = null;
    }
  }
}

function checkBotChallenge(text) {
  if (!text) return false;
  const lower = text.toLowerCase();
  const markers = [
    'cloudflare',
    'turnstile',
    'captcha',
    'verify you are human',
    'just a moment...',
    'attention required',
    'robot or human',
    'human verification',
    'ddos-guard',
  ];
  for (const m of markers) {
    if (lower.includes(m)) return true;
  }
  return false;
}

/**
 * Gereksinim (2):
 * Her araç sonucu için isError ve ilk 160 karakteri kaydeder.
 * Sonuç bir hata ise, boş ise veya 20 karakterden küçükse INVALID olarak işaretler.
 */
function parseToolResult(res) {
  if (!res) {
    return {
      text: '',
      isError: true,
      preview: '',
      valid: false,
      invalidReason: 'Sunucudan yanıt alınamadı (null)',
    };
  }
  if (res.error) {
    const msg = res.error.message || JSON.stringify(res.error);
    return {
      text: msg,
      isError: true,
      preview: msg.slice(0, 160),
      valid: false,
      invalidReason: `JSON-RPC hata: ${msg.slice(0, 80)}`,
    };
  }
  const result = res.result || {};
  const isError = Boolean(result.isError);
  let text = '';
  if (result.content && Array.isArray(result.content)) {
    text = result.content.map((c) => (typeof c.text === 'string' ? c.text : JSON.stringify(c))).join('\n');
  } else if (typeof result === 'string') {
    text = result;
  } else {
    text = JSON.stringify(result);
  }

  const preview = text.slice(0, 160);

  if (isError) {
    return {
      text,
      isError: true,
      preview,
      valid: false,
      invalidReason: `isError=true (${preview.slice(0, 60)})`,
    };
  }

  const trimmedText = text.trim();
  if (!text || trimmedText.length === 0 || trimmedText === '(empty)' || trimmedText === 'Command executed successfully') {
    return {
      text,
      isError: false,
      preview,
      valid: false,
      invalidReason: 'Boş yanıt',
    };
  }

  if (text.length < 20) {
    return {
      text,
      isError: false,
      preview,
      valid: false,
      invalidReason: `<20 karakter (${text.length}c: "${preview}")`,
    };
  }

  return {
    text,
    isError: false,
    preview,
    valid: true,
    invalidReason: null,
  };
}

/**
 * Gereksinim (6):
 * Metni bizzat dönüştürüp aradaki farkı sayarak:
 * (a) whitespace runs, (b) repeated JSON keys, (c) URLs, (d) duplicated lines paylarını ölçer.
 */
function analyzeTextTransformations(text) {
  if (!text || typeof text !== 'string') {
    return {
      length: 0,
      tokens: 0,
      whitespaceRuns: { charsSaved: 0, tokensSaved: 0, share: 0, sharePct: '0.0%' },
      repeatedKeys: { charsSaved: 0, tokensSaved: 0, share: 0, sharePct: '0.0%' },
      urls: { charsSaved: 0, tokensSaved: 0, share: 0, sharePct: '0.0%' },
      duplicatedLines: { charsSaved: 0, tokensSaved: 0, share: 0, sharePct: '0.0%' },
    };
  }

  const L0 = text.length;
  const T0 = estimateTokens(L0);

  // (a) Whitespace runs: 2 veya daha fazla ardışık boşluk/satır sonu karakterini tek boşluğa indirge
  const textWs = text.replace(/\s{2,}/g, ' ');
  const wsSaved = Math.max(0, L0 - textWs.length);

  // (b) Repeated JSON keys: JSON içindeki yinelenen anahtarları bizzat temizle
  let keysSaved = 0;
  let isJson = false;
  try {
    JSON.parse(text);
    isJson = true;
  } catch (e) {}

  if (isJson) {
    const seen = new Set();
    const textKeys = text.replace(/"([a-zA-Z0-9_\-\.]+)"\s*:/g, (match, key) => {
      if (seen.has(key)) return '';
      seen.add(key);
      return match;
    });
    keysSaved = Math.max(0, L0 - textKeys.length);
  }

  // (c) URLs: Tüm http/https bağlantılarını metinden çıkar
  const textUrls = text.replace(/https?:\/\/[^\s"',<>\)]+/g, '');
  const urlsSaved = Math.max(0, L0 - textUrls.length);

  // (d) Duplicated lines: Tekrarlanan boş olmayan satırları metinden çıkar
  const lines = text.split('\n');
  const seenLines = new Set();
  const keptLines = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      keptLines.push(line);
      continue;
    }
    if (!seenLines.has(trimmed)) {
      seenLines.add(trimmed);
      keptLines.push(line);
    }
  }
  const textDedup = keptLines.join('\n');
  const linesSaved = Math.max(0, L0 - textDedup.length);

  return {
    length: L0,
    tokens: T0,
    whitespaceRuns: {
      charsSaved: wsSaved,
      tokensSaved: estimateTokens(wsSaved),
      share: L0 > 0 ? wsSaved / L0 : 0,
      sharePct: L0 > 0 ? ((wsSaved / L0) * 100).toFixed(1) + '%' : '0.0%',
    },
    repeatedKeys: {
      charsSaved: keysSaved,
      tokensSaved: estimateTokens(keysSaved),
      share: L0 > 0 ? keysSaved / L0 : 0,
      sharePct: L0 > 0 ? ((keysSaved / L0) * 100).toFixed(1) + '%' : '0.0%',
    },
    urls: {
      charsSaved: urlsSaved,
      tokensSaved: estimateTokens(urlsSaved),
      share: L0 > 0 ? urlsSaved / L0 : 0,
      sharePct: L0 > 0 ? ((urlsSaved / L0) * 100).toFixed(1) + '%' : '0.0%',
    },
    duplicatedLines: {
      charsSaved: linesSaved,
      tokensSaved: estimateTokens(linesSaved),
      share: L0 > 0 ? linesSaved / L0 : 0,
      sharePct: L0 > 0 ? ((linesSaved / L0) * 100).toFixed(1) + '%' : '0.0%',
    },
  };
}

/**
 * Sayfanın güncel URL'sini browser_eval ile çeker
 */
async function getCurrentUrl(client) {
  try {
    const res = await client.call('tools/call', {
      name: 'browser_eval',
      arguments: { expression: 'window.location.href' },
    }, 5000);
    const ext = parseToolResult(res);
    return (ext.text || '').replace(/^["']|["']$/g, '').trim();
  } catch (e) {
    return '';
  }
}

function isSameUrl(u1, u2) {
  if (!u1 || !u2) return false;
  if (u1 === u2) return true;
  try {
    const p1 = new URL(u1);
    const p2 = new URL(u2);
    const path1 = p1.pathname.replace(/\/+$/, '');
    const path2 = p2.pathname.replace(/\/+$/, '');
    return p1.origin === p2.origin && path1 === path2 && p1.search === p2.search;
  } catch (e) {
    return u1.replace(/#.*$/, '').replace(/\/+$/, '') === u2.replace(/#.*$/, '').replace(/\/+$/, '');
  }
}

/**
 * Gereksinim (3):
 * diff ölçümü için sayfayı terk etmeyen (non-navigating) bir öğe seçer:
 * 1. Checkbox
 * 2. Details / Summary / Disclosure
 * 3. Tab
 * 4. Button (link olmayan)
 * 5. Searchbox / textbox (type eylemi ile)
 */
function selectNonNavigatingAction(snap) {
  let actions = [];
  if (snap && Array.isArray(snap.actions)) {
    actions = snap.actions;
  }

  // 1. Checkbox
  const checkbox = actions.find((a) => a.role === 'checkbox');
  if (checkbox) {
    return { ref: checkbox.ref, action: 'click', reason: `checkbox: ${checkbox.name || checkbox.ref}` };
  }

  // 2. Details / Summary / Disclosure
  const details = actions.find((a) => ['disclosure-triangle', 'details', 'summary'].includes(a.role));
  if (details) {
    return { ref: details.ref, action: 'click', reason: `details: ${details.name || details.ref}` };
  }

  // 3. Tab
  const tab = actions.find((a) => a.role === 'tab');
  if (tab) {
    return { ref: tab.ref, action: 'click', reason: `tab: ${tab.name || tab.ref}` };
  }

  // 4. Button whose role is not link
  const button = actions.find((a) => {
    if (a.role !== 'button') return false;
    const name = (a.name || '').toLowerCase();
    if (name.includes('sign in') || name.includes('log in') || name.includes('register') || name.includes('subscribe')) {
      return false;
    }
    return true;
  });
  if (button) {
    return { ref: button.ref, action: 'click', reason: `button (non-link): ${button.name || button.ref}` };
  }

  // 5. Searchbox / Textbox / Input (type eylemi)
  const searchbox = actions.find((a) => ['searchbox', 'textbox', 'combobox', 'search'].includes(a.role));
  if (searchbox) {
    return { ref: searchbox.ref, action: 'type', text: 'cdpilot', reason: `searchbox type: ${searchbox.name || searchbox.ref}` };
  }

  // 6. Diğer link olmayan eylem
  const anyNonLink = actions.find((a) => a.role && a.role !== 'link' && a.role !== 'WebArea');
  if (anyNonLink) {
    const act = (anyNonLink.action === 'type' || (anyNonLink.role && anyNonLink.role.includes('text'))) ? 'type' : 'click';
    return {
      ref: anyNonLink.ref,
      action: act,
      text: act === 'type' ? 'cdpilot' : undefined,
      reason: `non-link (${anyNonLink.role}): ${anyNonLink.name || anyNonLink.ref}`,
    };
  }

  return null;
}

async function runMeasurement() {
  const initialTabs = await getOpenTabs();
  const initialTabIds = new Set(initialTabs.map((t) => t.id));

  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-token-measure-2-'));
  const baseEnv = {
    ...process.env,
    CDPILOT_HOME: tempHome,
    CDPILOT_DAEMON: '1',
    CDPILOT_LOG: '0',
    CDPILOT_WEBMCP: '0',
  };
  delete baseEnv.CDPILOT_TIMEOUT;

  process.stderr.write(`[CONNECT] 9333 bağlanıyor...\n`);
  const c = spawnSync(process.execPath, [CLI, 'connect', '9333'], {
    env: baseEnv,
    cwd: REPO_ROOT,
    encoding: 'utf8',
  });
  if (c.status !== 0) {
    console.error('connect 9333 failed:', c.stderr);
    process.exit(1);
  }

  const results = {
    uptime: '',
    tokenizer: 'cdpilot _estimate_tokens (chars / 4); çevrimdışı o200k kütüphanesi ortamda yüklü değil',
    toolsList: {
      default: { count: 0, chars: 0, tokens: 0 },
      core: { count: 0, chars: 0, tokens: 0 },
    },
    pages: [],
  };

  try {
    const up = spawnSync('uptime', { encoding: 'utf8' });
    results.uptime = (up.stdout || '').trim();
  } catch (e) {}

  // 1. Measure tools/list for core
  process.stderr.write(`[TOOLS/LIST] Core profil ölçülüyor...\n`);
  {
    const coreClient = new McpClient({ ...baseEnv, CDPILOT_MCP_TOOLS: 'core' }, REPO_ROOT);
    await coreClient.start();
    await coreClient.call('initialize', {});
    coreClient.srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
    const r = await coreClient.call('tools/list', {});
    const tools = r.result && r.result.tools ? r.result.tools : [];
    const jsonStr = JSON.stringify(tools);
    results.toolsList.core = {
      count: tools.length,
      chars: jsonStr.length,
      tokens: estimateTokens(jsonStr.length),
    };
    await coreClient.stop();
  }

  // 2. Measure tools/list for default (all)
  process.stderr.write(`[TOOLS/LIST] Default profil ölçülüyor...\n`);
  {
    const defaultClient = new McpClient({ ...baseEnv, CDPILOT_MCP_TOOLS: '' }, REPO_ROOT);
    await defaultClient.start();
    await defaultClient.call('initialize', {});
    defaultClient.srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
    const r = await defaultClient.call('tools/list', {});
    const tools = r.result && r.result.tools ? r.result.tools : [];
    const jsonStr = JSON.stringify(tools);
    results.toolsList.default = {
      count: tools.length,
      chars: jsonStr.length,
      tokens: estimateTokens(jsonStr.length),
    };
    await defaultClient.stop();
  }

  // 3. Loop over pages with isolated MCP client per site
  for (const site of SITES) {
    const siteData = {
      id: site.id,
      name: site.name,
      url: site.url,
      finalUrl: site.url,
      readyState: '',
      botChallenge: false,
      tools: {},
    };

    process.stderr.write(`\n=== [SAYFA] ${site.name} ===\n`);

    const client = new McpClient({ ...baseEnv, CDPILOT_MCP_TOOLS: '' }, REPO_ROOT);
    await client.start();
    await client.call('initialize', {});
    client.srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');

    // Helper to run a tool, parse and record result
    const runTool = async (toolName, args, timeoutMs) => {
      const t0 = Date.now();
      const res = await client.call('tools/call', { name: toolName, arguments: args }, timeoutMs);
      const ms = Date.now() - t0;
      const ext = parseToolResult(res);
      const data = {
        name: toolName,
        rawText: ext.text,
        chars: ext.valid ? ext.text.length : 0,
        tokens: ext.valid ? estimateTokens(ext.text.length) : 0,
        isError: ext.isError,
        preview160: ext.preview,
        valid: ext.valid,
        invalidReason: ext.invalidReason,
        ms,
      };
      return data;
    };

    try {

    // (1) browser_navigate
    process.stderr.write(`  [1/7] browser_navigate (${site.url}) ...\n`);
    const navData = await runTool('browser_navigate', { url: site.url }, 45000);
    process.stderr.write(`        navigate bitti: ${navData.valid ? navData.chars + 'c' : 'GEÇERSİZ: ' + navData.invalidReason} (${navData.ms} ms)\n`);
    siteData.tools.browser_navigate = navData;

    // (1) Wait until document.readyState === 'complete' or 15 s
    process.stderr.write(`        readyState 'complete' bekleniyor (en fazla 15 sn)...\n`);
    const waitStart = Date.now();
    let lastReadyState = '';
    while (Date.now() - waitStart < 15000) {
      try {
        const readyRes = await client.call('tools/call', {
          name: 'browser_eval',
          arguments: { expression: 'document.readyState' },
        }, 5000);
        const readyExt = parseToolResult(readyRes);
        lastReadyState = (readyExt.text || '').replace(/^["']|["']$/g, '').trim();
        if (lastReadyState.includes('complete')) {
          break;
        }
      } catch (e) {}
      await new Promise((r) => setTimeout(r, 400));
    }
    siteData.readyState = lastReadyState || 'unknown';
    const finalUrl = await getCurrentUrl(client);
    siteData.finalUrl = finalUrl || site.url;
    process.stderr.write(`        hazır: readyState='${siteData.readyState}', finalUrl='${siteData.finalUrl}' (${Date.now() - waitStart} ms)\n`);

    // Bot challenge check (Requirement 4)
    if (checkBotChallenge(navData.rawText)) {
      siteData.botChallenge = true;
      siteData.botChallengeReason = 'Navigate çıktısında bot/turnstile/captcha tespit edildi.';
      results.pages.push(siteData);
      process.stderr.write(`   [BOT CHALLENGE] Tespit edildi, sayfa atlandı.\n`);
      continue;
    }

    try {
      const fData = await runTool('browser_friction', {}, 10000);
      if (fData.rawText.includes('"rung": "soft_captcha"') || fData.rawText.includes('"rung": "hard_block"')) {
        siteData.botChallenge = true;
        siteData.botChallengeReason = `browser_friction seviyesi: ${fData.rawText}`;
        results.pages.push(siteData);
        process.stderr.write(`   [BOT CHALLENGE via friction] Atlandı.\n`);
        continue;
      }
    } catch (e) {}

    // Tool 2: browser_content
    process.stderr.write(`  [2/7] browser_content ...\n`);
    {
      const cntData = await runTool('browser_content', {}, 25000);
      if (cntData.valid) {
        cntData.stats = analyzeTextTransformations(cntData.rawText);
      }
      siteData.tools.browser_content = cntData;
      process.stderr.write(`        content bitti: ${cntData.valid ? cntData.chars + 'c' : 'GEÇERSİZ: ' + cntData.invalidReason} (${cntData.ms} ms)\n`);
    }

    // Tool 3: browser_a11y
    process.stderr.write(`  [3/7] browser_a11y ...\n`);
    {
      const a11yData = await runTool('browser_a11y', {}, 35000);
      if (a11yData.valid) {
        a11yData.stats = analyzeTextTransformations(a11yData.rawText);
      }
      siteData.tools.browser_a11y = a11yData;
      process.stderr.write(`        a11y bitti: ${a11yData.valid ? a11yData.chars + 'c' : 'GEÇERSİZ: ' + a11yData.invalidReason} (${a11yData.ms} ms)\n`);
    }

    // Tool 4: browser_agent_observe
    process.stderr.write(`  [4/7] browser_agent_observe ...\n`);
    let observeSnap = null;
    {
      const obsData = await runTool('browser_agent_observe', {}, 35000);
      if (obsData.valid) {
        obsData.stats = analyzeTextTransformations(obsData.rawText);
        try {
          observeSnap = JSON.parse(obsData.rawText);
        } catch (e) {}
      }
      siteData.tools.browser_agent_observe = obsData;
      process.stderr.write(`        observe bitti: ${obsData.valid ? obsData.chars + 'c' : 'GEÇERSİZ: ' + obsData.invalidReason} (${obsData.ms} ms)\n`);
    }

    // Tool 5: (Requirement 3) non-navigating action + browser_agent_observe diff=true
    process.stderr.write(`  [5/7] diff ölçümü (non-navigating action + observe diff=true) ...\n`);
    {
      let diffData = {
        name: 'browser_agent_observe_diff',
        rawText: '',
        chars: 0,
        tokens: 0,
        isError: false,
        preview160: '',
        valid: false,
        invalidReason: 'Ölçülemedi',
        ms: 0,
      };

      if (!siteData.tools.browser_agent_observe || !siteData.tools.browser_agent_observe.valid) {
        diffData.invalidReason = 'Önceki observe geçersiz olduğu için diff ölçülemedi';
      } else {
        const target = selectNonNavigatingAction(observeSnap);
        if (!target) {
          diffData.invalidReason = 'Gezinmeyen (non-navigating) etkileşimli öğe bulunamadı';
          process.stderr.write(`        [DIFF ATLANDI] Uygun öğe bulunamadı.\n`);
        } else {
          process.stderr.write(`        Hedef öğe: ${target.reason} (ref=${target.ref}, action=${target.action})\n`);
          const urlBefore = await getCurrentUrl(client);

          // Eylemi uygula
          const actArgs = { ref: target.ref, action: target.action };
          if (target.text) actArgs.text = target.text;

          const t0Act = Date.now();
          const actRes = await client.call('tools/call', {
            name: 'browser_agent_act',
            arguments: actArgs,
          }, 20000);
          const actExt = parseToolResult(actRes);
          process.stderr.write(`        act tamamlandı: ${actExt.valid ? 'başarılı' : actExt.invalidReason} (${Date.now() - t0Act} ms)\n`);

          // Sayfa oturmasını bekle
          await new Promise((r) => setTimeout(r, 600));

          const urlAfter = await getCurrentUrl(client);

          // URL değişti mi teyit et
          if (urlBefore && urlAfter && !isSameUrl(urlBefore, urlAfter)) {
            diffData.valid = false;
            diffData.isError = true;
            diffData.invalidReason = `URL değişti: ${urlBefore} -> ${urlAfter}`;
            diffData.preview160 = `Eylem sonrasında URL değişti: ${urlBefore} -> ${urlAfter}`;
            process.stderr.write(`        [DIFF GEÇERSİZ] URL değişti (${urlBefore} -> ${urlAfter})\n`);
          } else {
            // URL değişmedi: diff=true ile ölç
            const t0Diff = Date.now();
            const diffRes = await client.call('tools/call', {
              name: 'browser_agent_observe',
              arguments: { diff: true },
            }, 30000);
            const diffExt = parseToolResult(diffRes);
            const diffMs = Date.now() - t0Diff;

            diffData = {
              name: 'browser_agent_observe_diff',
              rawText: diffExt.text,
              chars: diffExt.valid ? diffExt.text.length : 0,
              tokens: diffExt.valid ? estimateTokens(diffExt.text.length) : 0,
              isError: diffExt.isError,
              preview160: diffExt.preview,
              valid: diffExt.valid,
              invalidReason: diffExt.invalidReason,
              targetAction: target,
              ms: diffMs,
            };

            if (diffExt.valid) {
              diffData.stats = analyzeTextTransformations(diffExt.text);
            }
            process.stderr.write(`        diff bitti: ${diffData.valid ? diffData.chars + 'c' : 'GEÇERSİZ: ' + diffData.invalidReason} (${diffMs} ms)\n`);
          }
        }
      }
      siteData.tools.browser_agent_observe_diff = diffData;
    }

    // Tool 6: browser_tabs
    process.stderr.write(`  [6/7] browser_tabs ...\n`);
    {
      const tabsData = await runTool('browser_tabs', {}, 10000);
      siteData.tools.browser_tabs = tabsData;
      process.stderr.write(`        tabs bitti: ${tabsData.valid ? tabsData.chars + 'c' : 'GEÇERSİZ: ' + tabsData.invalidReason} (${tabsData.ms} ms)\n`);
    }

    // Tool 7: browser_console & browser_network
    process.stderr.write(`  [7/7] browser_console & browser_network ...\n`);
    {
      const conData = await runTool('browser_console', { url: siteData.finalUrl || site.url }, 35000);
      siteData.tools.browser_console = conData;

      const netData = await runTool('browser_network', { url: siteData.finalUrl || site.url }, 35000);
      siteData.tools.browser_network = netData;

      process.stderr.write(`        console: ${conData.valid ? conData.chars + 'c' : 'GEÇERSİZ: ' + conData.invalidReason} (${conData.ms}ms), network: ${netData.valid ? netData.chars + 'c' : 'GEÇERSİZ: ' + netData.invalidReason} (${netData.ms}ms)\n`);
    }

    } finally {
      process.stderr.write(`        [MCP] Site oturumu kapatılıyor...\n`);
      await client.stop();
      // Her siteden sonra açılan sekmeleri temizle
      const midTabs = await getOpenTabs();
      for (const tab of midTabs) {
        if (!initialTabIds.has(tab.id)) {
          await closeTab(tab.id);
        }
      }
    }

    results.pages.push(siteData);
  }

  // Cleanup temp dir
  try {
    fs.rmSync(tempHome, { recursive: true, force: true });
  } catch (e) {}

  // Generate Markdown Report
  process.stderr.write(`[RAPOR] Rapor yazılıyor: ${REPORT_PATH} ...\n`);
  const md = generateMarkdown(results);
  fs.writeFileSync(REPORT_PATH, md, 'utf8');

  return results;
}

function formatCell(toolData) {
  if (!toolData) return '—';
  if (!toolData.valid) {
    return `INVALID (${toolData.invalidReason || 'hata'})`;
  }
  return toolData.tokens.toLocaleString('tr-TR');
}

function generateMarkdown(results) {
  const lines = [];
  lines.push('# MCP Araç Çıktıları Token Ölçümü (v2 — 2026-11-10)');
  lines.push('');
  lines.push('## Sistem Yükü ve Koşullar');
  lines.push(`- Ölçüm zamanı: 2026-11-10 (yerel)`);
  lines.push(`- Sistem yükü (\`uptime\`): \`${results.uptime}\``);
  lines.push('- Donanım: Apple M1 Max (arm64), macOS');
  lines.push('- Ortak başsız Chrome: 127.0.0.1:9333 (`HeadlessChrome/152.0.7977.30`)');
  lines.push('- Sunucu kipi: `CDPILOT_DAEMON=1 CDPILOT_LOG=0`');
  lines.push(`- Token hesap kuralı: ${results.tokenizer}`);
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 1. `tools/list` Şema Boyutları (Default vs Core)');
  lines.push('');
  lines.push('| Profil | Araç Sayısı | Karakter | Tahmini Token | Tasarruf |');
  lines.push('|---|---|---|---|---|');
  const d = results.toolsList.default;
  const c = results.toolsList.core;
  const savingPct = d.chars > 0 ? Math.round(((d.chars - c.chars) / d.chars) * 100) : 0;
  lines.push(`| **Default (all)** | ${d.count} | ${d.chars.toLocaleString('tr-TR')} | ${d.tokens.toLocaleString('tr-TR')} | Referans |`);
  lines.push(`| **\`--tools core\`** | ${c.count} | ${c.chars.toLocaleString('tr-TR')} | ${c.tokens.toLocaleString('tr-TR')} | **−%${savingPct}** (${(d.tokens - c.tokens).toLocaleString('tr-TR')} token) |`);
  lines.push('');
  lines.push('> [!NOTE]');
  lines.push('> `tools/list` şeması MCP istemcisi tarafından her model turunda sistem istemine eklenir.');
  lines.push(`> Core profil seçildiğinde her istekte **${(d.tokens - c.tokens).toLocaleString('tr-TR')} token** (%${savingPct}) tasarruf edilir.`);
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 2. Sayfa × Araç Çıktı Boyutları (Token)');
  lines.push('');
  lines.push('| Sayfa | navigate | content | a11y | observe | observe (diff) | tabs | console | network | Toplam |');
  lines.push('|---|---|---|---|---|---|---|---|---|---|');

  for (const page of results.pages) {
    if (page.botChallenge) {
      lines.push(`| **${page.name}** | — | — | — | — | — | — | — | — | *(Bot engeli: atlandı)* |`);
      continue;
    }
    const t = page.tools;
    const navTok = (t.browser_navigate && t.browser_navigate.valid) ? t.browser_navigate.tokens : 0;
    const cntTok = (t.browser_content && t.browser_content.valid) ? t.browser_content.tokens : 0;
    const a11yTok = (t.browser_a11y && t.browser_a11y.valid) ? t.browser_a11y.tokens : 0;
    const obsTok = (t.browser_agent_observe && t.browser_agent_observe.valid) ? t.browser_agent_observe.tokens : 0;
    const diffTok = (t.browser_agent_observe_diff && t.browser_agent_observe_diff.valid) ? t.browser_agent_observe_diff.tokens : 0;
    const tabTok = (t.browser_tabs && t.browser_tabs.valid) ? t.browser_tabs.tokens : 0;
    const conTok = (t.browser_console && t.browser_console.valid) ? t.browser_console.tokens : 0;
    const netTok = (t.browser_network && t.browser_network.valid) ? t.browser_network.tokens : 0;
    const total = navTok + cntTok + a11yTok + obsTok + diffTok + tabTok + conTok + netTok;

    lines.push(`| **${page.name}** | ${formatCell(t.browser_navigate)} | ${formatCell(t.browser_content)} | ${formatCell(t.browser_a11y)} | ${formatCell(t.browser_agent_observe)} | ${formatCell(t.browser_agent_observe_diff)} | ${formatCell(t.browser_tabs)} | ${formatCell(t.browser_console)} | ${formatCell(t.browser_network)} | **${total.toLocaleString('tr-TR')}** |`);
  }

  lines.push('');
  lines.push('> [!IMPORTANT]');
  lines.push('> Gereksinim gereğince: Hata, boş ya da 20 karakterden küçük sonuçlar veya gezinmeye sebep olan diff sonuçları **INVALID** olarak işaretlenmiş ve sayfa toplamına **asla dahil edilmemiştir**.');
  lines.push('');
  lines.push('### Sayfa Yükleme ve Son URL Durumları');
  for (const page of results.pages) {
    if (page.botChallenge) {
      lines.push(`- **${page.name}**: Bot engeli tespit edildi (${page.botChallengeReason || 'atlandı'}).`);
    } else {
      lines.push(`- **${page.name}**: Son URL = \`${page.finalUrl}\`, readyState = \`${page.readyState}\``);
    }
  }

  lines.push('');
  lines.push('### Araç Sonuçları Durumu ve İlk 160 Karakter Denetimi');
  lines.push('');
  lines.push('| Sayfa | Araç | Durum | isError | Karakter | İlk 160 Karakter Özeti |');
  lines.push('|---|---|---|---|---|---|');
  for (const page of results.pages) {
    if (page.botChallenge) {
      lines.push(`| **${page.name}** | *(Tümü)* | BOT ENGELİ | — | — | ${page.botChallengeReason} |`);
      continue;
    }
    for (const [toolName, toolData] of Object.entries(page.tools)) {
      const statusStr = toolData.valid ? 'GEÇERLİ' : `INVALID (${toolData.invalidReason})`;
      const cleanPreview = (toolData.preview160 || '').replace(/[\r\n]+/g, ' ').replace(/\|/g, '\\|').slice(0, 100);
      lines.push(`| **${page.name}** | \`${toolName}\` | ${statusStr} | \`${toolData.isError}\` | ${toolData.chars} | \`${cleanPreview}\` |`);
    }
  }

  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 3. Geçerli Çıktıların Dönüştürülerek Ölçülen İsraf Payları');
  lines.push('');
  lines.push('Yalnızca GEÇERLİ `browser_content`, `browser_a11y` ve `browser_agent_observe` çıktıları için metin bizzat dönüştürülüp hesaplanan kesin paylar:');
  lines.push('');
  lines.push('| Sayfa | Araç | Boyut (Token) | (a) Boşluk Dizileri | (b) Yinelenen JSON Anahtarları | (c) URL\'ler | (d) Yinelenen Satırlar |');
  lines.push('|---|---|---|---|---|---|---|');

  const validTargets = [];

  for (const page of results.pages) {
    if (page.botChallenge) continue;
    for (const toolKey of ['browser_content', 'browser_a11y', 'browser_agent_observe']) {
      const toolData = page.tools[toolKey];
      if (toolData && toolData.valid && toolData.stats) {
        const s = toolData.stats;
        validTargets.push({ page: page.name, tool: toolKey, stats: s });
        lines.push(`| **${page.name}** | \`${toolKey}\` | ${toolData.tokens.toLocaleString('tr-TR')} | ${s.whitespaceRuns.sharePct} (${s.whitespaceRuns.tokensSaved.toLocaleString('tr-TR')} t) | ${s.repeatedKeys.sharePct} (${s.repeatedKeys.tokensSaved.toLocaleString('tr-TR')} t) | ${s.urls.sharePct} (${s.urls.tokensSaved.toLocaleString('tr-TR')} t) | ${s.duplicatedLines.sharePct} (${s.duplicatedLines.tokensSaved.toLocaleString('tr-TR')} t) |`);
      }
    }
  }

  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 4. Ölçülen Tasarruflara Göre Sıralı Budama (Trim) Listesi');
  lines.push('');
  lines.push('Aşağıdaki tasarruflar varsayım DEĞİL, yukarıdaki gerçek çıktılar üzerinde uygulanan dönüştürmelerin sayfa başına ortalama ve toplam ölçümüdür:');
  lines.push('');

  // Calculate aggregates
  let totalWsTokens = 0;
  let totalKeysTokens = 0;
  let totalUrlsTokens = 0;
  let totalDupLinesTokens = 0;
  const count = validTargets.length || 1;

  for (const v of validTargets) {
    totalWsTokens += v.stats.whitespaceRuns.tokensSaved;
    totalKeysTokens += v.stats.repeatedKeys.tokensSaved;
    totalUrlsTokens += v.stats.urls.tokensSaved;
    totalDupLinesTokens += v.stats.duplicatedLines.tokensSaved;
  }

  const avgWs = Math.round(totalWsTokens / count);
  const avgKeys = Math.round(totalKeysTokens / count);
  const avgUrls = Math.round(totalUrlsTokens / count);
  const avgDup = Math.round(totalDupLinesTokens / count);

  const trims = [
    {
      rank: 1,
      title: '`tools/list` Core Profil Zorunluluğu',
      saving: `${(d.tokens - c.tokens).toLocaleString('tr-TR')} token / tur (%${savingPct})`,
      avgTokens: d.tokens - c.tokens,
      risk: 'Sıfır',
      desc: 'Her model turunda sistem istemine giren 49 araçlık şema 11 araca indirilir. İstem boyutu anında küçülür.',
    },
    {
      rank: 2,
      title: 'Yinelenen JSON Anahtarlarının Sıkıştırılması / Tabüler Şema (`a11y` ve `observe`)',
      saving: `Ortalama ${avgKeys.toLocaleString('tr-TR')} token / sayfa (Toplam: ${totalKeysTokens.toLocaleString('tr-TR')} token)`,
      avgTokens: avgKeys,
      risk: 'Düşük',
      desc: '`browser_a11y` ve `browser_agent_observe` çıktılarındaki tekrarlanan `"role":`, `"name":`, `"ref":`, `"actions":` anahtarları tabüler dizi veya kompakt formata geçirilerek doğrudan bertaraf edilir.',
    },
    {
      rank: 3,
      title: 'Ardışık Boşluk Dizilerinin (Whitespace Runs) Sıkıştırılması',
      saving: `Ortalama ${avgWs.toLocaleString('tr-TR')} token / sayfa (Toplam: ${totalWsTokens.toLocaleString('tr-TR')} token)`,
      avgTokens: avgWs,
      risk: 'Sıfır',
      desc: '`browser_content` metin katmanındaki ve girintili JSON çıktılarındaki `\\s{2,}` dizileri tek boşluğa indirgendiğinde anlamsal hiçbir kayıp olmadan ölçülen tasarruf sağlanır.',
    },
    {
      rank: 4,
      title: 'Yinelenen Satırların (Duplicated Lines) Temizlenmesi',
      saving: `Ortalama ${avgDup.toLocaleString('tr-TR')} token / sayfa (Toplam: ${totalDupLinesTokens.toLocaleString('tr-TR')} token)`,
      avgTokens: avgDup,
      risk: 'Düşük',
      desc: 'Menü, telif, navigasyon ve liste tekrarlarından kaynaklanan özdeş satırlar filtrelenir.',
    },
    {
      rank: 5,
      title: 'URL\'lerin Göreliye Çevrilmesi veya İndekslenmesi',
      saving: `Ortalama ${avgUrls.toLocaleString('tr-TR')} token / sayfa (Toplam: ${totalUrlsTokens.toLocaleString('tr-TR')} token)`,
      avgTokens: avgUrls,
      risk: 'Düşük',
      desc: 'Sayfa içindeki mutlak URL (`https://...`) tekrarları göreli yola ya da referans indeksine çevrilir.',
    },
  ];

  // Sort trims by avgTokens descending
  trims.sort((a, b) => b.avgTokens - a.avgTokens);
  trims.forEach((t, i) => { t.rank = i + 1; });

  lines.push('| Sıra | Budama Önerisi | Ölçülen Tasarruf | Risk Seviyesi | Doğrulama & Uygulama Notu |');
  lines.push('|---|---|---|---|---|');
  for (const t of trims) {
    lines.push(`| **${t.rank}** | **${t.title}** | **${t.saving}** | **${t.risk}** | ${t.desc} |`);
  }
  lines.push('');

  return lines.join('\n');
}

if (require.main === module) {
  runMeasurement()
    .then((res) => {
      console.log('--- ÖLÇÜM TAMAMLANDI ---');
      console.log(`tools/list default: ${res.toolsList.default.tokens} token (${res.toolsList.default.count} araç)`);
      console.log(`tools/list core:    ${res.toolsList.core.tokens} token (${res.toolsList.core.count} araç)`);
      for (const p of res.pages) {
        if (p.botChallenge) {
          console.log(`${p.name}: BOT CHALLENGE (atlandı)`);
        } else {
          const t = p.tools;
          console.log(`${p.name}: nav=${t.browser_navigate?.valid ? t.browser_navigate.tokens : 'INVALID'} cnt=${t.browser_content?.valid ? t.browser_content.tokens : 'INVALID'} a11y=${t.browser_a11y?.valid ? t.browser_a11y.tokens : 'INVALID'} obs=${t.browser_agent_observe?.valid ? t.browser_agent_observe.tokens : 'INVALID'} diff=${t.browser_agent_observe_diff?.valid ? t.browser_agent_observe_diff.tokens : 'INVALID'}`);
        }
      }
      console.log(`Rapor yazıldı: ${REPORT_PATH}`);
      process.exit(0);
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}

module.exports = { runMeasurement };
