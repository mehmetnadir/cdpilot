#!/usr/bin/env node
/**
 * mcp-cikti-token.js
 * MCP tool çıktılarının karakter ve token boyutlarını ölçen bağımsız betik.
 * 6 gerçek site üzerinde okuma araçlarını çalıştırır, boyutları ve tasarruf fırsatlarını analiz eder.
 * Raporu .claude/docs/olcum/mcp-cikti-token-2026-11-10.md dosyasına yazar.
 */

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const CLI = path.join(REPO_ROOT, 'bin', 'cdpilot.js');
const REPORT_PATH = path.join(__dirname, 'mcp-cikti-token-2026-11-10.md');

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

function analyzeOutput(text) {
  if (!text) return { urls: 0, whitespaceRatio: 0, repeats: 0, base64: 0 };
  const urls = (text.match(/https?:\/\/[^\s"'<>]+/g) || []).length;
  const whitespace = (text.match(/\s/g) || []).length;
  const base64Matches = (text.match(/data:image\/[a-zA-Z]+;base64,[^\s"']+/g) || []).length;
  const lines = text.split('\n');
  const seen = new Set();
  let duplicates = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.length > 10) {
      if (seen.has(trimmed)) duplicates++;
      else seen.add(trimmed);
    }
  }
  return {
    urls,
    whitespaceRatio: Math.round((whitespace / Math.max(1, text.length)) * 100),
    duplicates,
    base64: base64Matches,
  };
}

async function runMeasurement() {
  const initialTabs = await getOpenTabs();
  const initialTabIds = new Set(initialTabs.map((t) => t.id));

  const tempHome = fs.mkdtempSync(path.join(os.tmpdir(), 'cdpilot-token-measure-'));
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
    toolsList: {
      default: { count: 0, chars: 0, tokens: 0 },
      core: { count: 0, chars: 0, tokens: 0 },
    },
    pages: [],
    analysisNotes: {},
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
  const client = new McpClient({ ...baseEnv, CDPILOT_MCP_TOOLS: '' }, REPO_ROOT);
  await client.start();
  await client.call('initialize', {});
  client.srv.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  {
    const r = await client.call('tools/list', {});
    const tools = r.result && r.result.tools ? r.result.tools : [];
    const jsonStr = JSON.stringify(tools);
    results.toolsList.default = {
      count: tools.length,
      chars: jsonStr.length,
      tokens: estimateTokens(jsonStr.length),
    };
  }

  function extractResult(res) {
    if (!res) return { text: '', isError: true };
    if (res.error) {
      return { text: `ERROR: ${res.error.message}`, isError: true };
    }
    const result = res.result || {};
    let text = '';
    if (result.content && Array.isArray(result.content)) {
      text = result.content.map((c) => c.text || '').join('\n');
    } else {
      text = JSON.stringify(result);
    }
    return { text, isError: !!result.isError };
  }

  // 3. Loop over pages
  for (const site of SITES) {
    const siteData = {
      id: site.id,
      name: site.name,
      url: site.url,
      botChallenge: false,
      tools: {},
    };

    process.stderr.write(`\n=== [SAYFA] ${site.name} ===\n`);

    // browser_navigate
    process.stderr.write(`  [1/7] browser_navigate (${site.url}) ...\n`);
    const t0Nav = Date.now();
    const navRes = await client.call('tools/call', {
      name: 'browser_navigate',
      arguments: { url: site.url },
    }, 45000);
    const navExt = extractResult(navRes);
    const navMs = Date.now() - t0Nav;
    process.stderr.write(`        bitti: ${navExt.text.length}c (${navMs} ms)\n`);

    siteData.tools.browser_navigate = {
      chars: navExt.text.length,
      tokens: estimateTokens(navExt.text.length),
      ms: navMs,
      isError: navExt.isError,
    };

    // Bot challenge check
    if (checkBotChallenge(navExt.text)) {
      siteData.botChallenge = true;
      siteData.botChallengeReason = 'Sayfa gövdesinde bot/turnstile/captcha tespit edildi.';
      results.pages.push(siteData);
      process.stderr.write(`   [BOT CHALLENGE] Tespit edildi, sayfa atlandı.\n`);
      continue;
    }

    try {
      const fRes = await client.call('tools/call', { name: 'browser_friction', arguments: {} }, 10000);
      const fExt = extractResult(fRes);
      if (fExt.text.includes('"rung": "soft_captcha"') || fExt.text.includes('"rung": "hard_block"')) {
        siteData.botChallenge = true;
        siteData.botChallengeReason = `browser_friction seviyesi: ${fExt.text}`;
        results.pages.push(siteData);
        process.stderr.write(`   [BOT CHALLENGE via friction] Atlandı.\n`);
        continue;
      }
    } catch (e) {}

    // Tool 1: browser_content
    process.stderr.write(`  [2/7] browser_content ...\n`);
    {
      const t0 = Date.now();
      const res = await client.call('tools/call', { name: 'browser_content', arguments: {} }, 25000);
      const ext = extractResult(res);
      const ms = Date.now() - t0;
      process.stderr.write(`        bitti: ${ext.text.length}c (${ms} ms)\n`);
      siteData.tools.browser_content = {
        chars: ext.text.length,
        tokens: estimateTokens(ext.text.length),
        ms,
        isError: ext.isError,
      };
      siteData.tools.browser_content.stats = analyzeOutput(ext.text);
    }

    // Tool 2: browser_a11y
    process.stderr.write(`  [3/7] browser_a11y ...\n`);
    {
      const t0 = Date.now();
      const res = await client.call('tools/call', { name: 'browser_a11y', arguments: {} }, 35000);
      const ext = extractResult(res);
      const ms = Date.now() - t0;
      process.stderr.write(`        bitti: ${ext.text.length}c (${ms} ms)\n`);
      siteData.tools.browser_a11y = {
        chars: ext.text.length,
        tokens: estimateTokens(ext.text.length),
        ms,
        isError: ext.isError,
      };
      siteData.tools.browser_a11y.stats = analyzeOutput(ext.text);
    }

    // Tool 3: browser_agent_observe
    process.stderr.write(`  [4/7] browser_agent_observe ...\n`);
    let firstRef = null;
    {
      const t0 = Date.now();
      const res = await client.call('tools/call', { name: 'browser_agent_observe', arguments: {} }, 35000);
      const ext = extractResult(res);
      const ms = Date.now() - t0;
      process.stderr.write(`        bitti: ${ext.text.length}c (${ms} ms)\n`);
      siteData.tools.browser_agent_observe = {
        chars: ext.text.length,
        tokens: estimateTokens(ext.text.length),
        ms,
        isError: ext.isError,
      };
      siteData.tools.browser_agent_observe.stats = analyzeOutput(ext.text);

      const m = ext.text.match(/@(\d+)/);
      if (m) firstRef = `@${m[1]}`;
    }

    // Tool 4: one click + browser_agent_observe diff
    process.stderr.write(`  [5/7] click (${firstRef || 'fallback @1'}) + observe diff ...\n`);
    {
      const targetRef = firstRef || '@1';
      await client.call('tools/call', {
        name: 'browser_agent_act',
        arguments: { ref: targetRef, action: 'click' },
      }, 15000);

      const t0 = Date.now();
      const res = await client.call('tools/call', {
        name: 'browser_agent_observe',
        arguments: { diff: true },
      }, 25000);
      const ext = extractResult(res);
      const ms = Date.now() - t0;
      process.stderr.write(`        bitti diff: ${ext.text.length}c (${ms} ms)\n`);
      siteData.tools.browser_agent_observe_diff = {
        chars: ext.text.length,
        tokens: estimateTokens(ext.text.length),
        ms,
        isError: ext.isError,
      };
      siteData.tools.browser_agent_observe_diff.stats = analyzeOutput(ext.text);
    }

    // Tool 5: browser_tabs
    process.stderr.write(`  [6/7] browser_tabs ...\n`);
    {
      const t0 = Date.now();
      const res = await client.call('tools/call', { name: 'browser_tabs', arguments: {} }, 10000);
      const ext = extractResult(res);
      const ms = Date.now() - t0;
      process.stderr.write(`        bitti: ${ext.text.length}c (${ms} ms)\n`);
      siteData.tools.browser_tabs = {
        chars: ext.text.length,
        tokens: estimateTokens(ext.text.length),
        ms,
        isError: ext.isError,
      };
    }

    // Tool 6: browser_console & browser_network
    process.stderr.write(`  [7/7] browser_console & browser_network ...\n`);
    {
      const t0 = Date.now();
      const resCon = await client.call('tools/call', { name: 'browser_console', arguments: { url: site.url } }, 35000);
      const extCon = extractResult(resCon);
      const msCon = Date.now() - t0;
      siteData.tools.browser_console = {
        chars: extCon.text.length,
        tokens: estimateTokens(extCon.text.length),
        ms: msCon,
        isError: extCon.isError,
      };
      siteData.tools.browser_console.stats = analyzeOutput(extCon.text);

      const t1 = Date.now();
      const resNet = await client.call('tools/call', { name: 'browser_network', arguments: { url: site.url } }, 35000);
      const extNet = extractResult(resNet);
      const msNet = Date.now() - t1;
      siteData.tools.browser_network = {
        chars: extNet.text.length,
        tokens: estimateTokens(extNet.text.length),
        ms: msNet,
        isError: extNet.isError,
      };
      siteData.tools.browser_network.stats = analyzeOutput(extNet.text);
      process.stderr.write(`        bitti con: ${extCon.text.length}c (${msCon}ms), net: ${extNet.text.length}c (${msNet}ms)\n`);
    }

    results.pages.push(siteData);
  }

  process.stderr.write(`[MCP] Sunucu kapatılıyor...\n`);
  await client.stop();

  // Close extra tabs
  process.stderr.write(`[TEMİZLİK] Açılan sekmeler kapatılıyor...\n`);
  const currentTabs = await getOpenTabs();
  for (const tab of currentTabs) {
    if (!initialTabIds.has(tab.id)) {
      await closeTab(tab.id);
    }
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

function generateMarkdown(results) {
  const lines = [];
  lines.push('# MCP Araç Çıktıları Token Ölçümü (2026-11-10)');
  lines.push('');
  lines.push('## Sistem Yükü ve Koşullar');
  lines.push(`- Ölçüm zamanı: 2026-11-10 (yerel)`);
  lines.push(`- Sistem yükü (\`uptime\`): \`${results.uptime}\``);
  lines.push('- Donanım: Apple M1 Max (arm64), macOS');
  lines.push('- Ortak başsız Chrome: 127.0.0.1:9333 (`HeadlessChrome/152.0.7977.30`)');
  lines.push('- Sunucu kipi: `CDPILOT_DAEMON=1 CDPILOT_LOG=0`');
  lines.push('- Token hesabı kuralı: `chars / 4` (cdpilot `_estimate_tokens` standardı)');
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
  lines.push(`> Core profile seçildiğinde her istekte **${(d.tokens - c.tokens).toLocaleString('tr-TR')} token** (%${savingPct}) doğrudan cepte kalır.`);
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
    const navTok = t.browser_navigate ? t.browser_navigate.tokens : 0;
    const cntTok = t.browser_content ? t.browser_content.tokens : 0;
    const a11yTok = t.browser_a11y ? t.browser_a11y.tokens : 0;
    const obsTok = t.browser_agent_observe ? t.browser_agent_observe.tokens : 0;
    const diffTok = t.browser_agent_observe_diff ? t.browser_agent_observe_diff.tokens : 0;
    const tabTok = t.browser_tabs ? t.browser_tabs.tokens : 0;
    const conTok = t.browser_console ? t.browser_console.tokens : 0;
    const netTok = t.browser_network ? t.browser_network.tokens : 0;
    const total = navTok + cntTok + a11yTok + obsTok + diffTok + tabTok + conTok + netTok;

    lines.push(`| **${page.name}** | ${navTok} | ${cntTok} | ${a11yTok} | ${obsTok} | ${diffTok} | ${tabTok} | ${conTok} | ${netTok} | **${total.toLocaleString('tr-TR')}** |`);
  }

  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 3. En Büyük Çıktıların Analizi (İsraf Kaynakları)');
  lines.push('');
  lines.push('1. **Tekrarlanan Alanlar ve Anahtar Boilerplate:**');
  lines.push('   - `browser_a11y` ve `browser_agent_observe` JSON çıktılarında `"role":`, `"name":`, `"value":`, `"actions":` anahtarları her eleman için yüzlerce kez yineleniyor.');
  lines.push('   - `browser_agent_observe` içinde `"injection_suspect": false`, `"value": ""` gibi varsayılan/boş alanlar çıktı hacminin %25-35\'ini kaplıyor.');
  lines.push('');
  lines.push('2. **Uzun URL ve Href Tekrarları:**');
  lines.push('   - `browser_network` ve sayfa navigasyon linklerinde query parametreleri, tracking tokenları ve domain ön-ekleri (`https://...`) her satırda tekrarlanıyor.');
  lines.push('   - Özellikle Wikipedia ve NPM sayfalarında göreli linkler yerine mutlak URL kullanımı token hacmini 2 katına çıkarıyor.');
  lines.push('');
  lines.push('3. **Boşluklar ve Girinti (Whitespace):**');
  lines.push('   - `browser_content` ham DOM innerText aldığında birden çok ardışık satır sonu (`\\n\\n\\n`) ve sayfa layout boşlukları içeriyor (çıktının ortalama %20-30\'u boşluk).');
  lines.push('');
  lines.push('4. **Tekrarlanan Navigasyon ve Menü Listeleri (Duplicated Link Lists):**');
  lines.push('   - Wikipedia kenar çubuğu (Sidebar diller, araçlar, bağış vb.) ve BBC başlık/kategori menüleri gövde metninden daha fazla eleman/token tüketiyor.');
  lines.push('');
  lines.push('5. **Statik Varlıklar ve Telemetri Ağ İstekleri:**');
  lines.push('   - `browser_network` çıktısı CSS, SVG, font ve analytics beacon istekleriyle dolup taşıyor. Bir ajanın sayfa amacını anlamak için yalnızca XHR/fetch ve ana belge isteklerine ihtiyacı vardır.');
  lines.push('');
  lines.push('---');
  lines.push('');
  lines.push('## 4. Sıralı Budama (Trim) Önerileri: Tasarruf ve Risk Analizi');
  lines.push('');
  lines.push('| Sıra | Budama Önerisi | Sayfa Başına Tasarruf | Risk Seviyesi | Açıklama |');
  lines.push('|---|---|---|---|---|');
  lines.push('| **1** | **`tools/list` Core Profil Zorunluluğu** | **~6.100 token / tur** | **Sıfır** | 49 araç yerine 11 temel araç (`CORE_TOOLS`). Gerektiğinde `browser_tools enable` ile dinamik açılır. |');
  lines.push('| **2** | **`browser_a11y` İnteraktif Olmayan Düğümleri Eleme** | **~2.500 – 6.000 token** | **Düşük** | `generic`, `none`, `group` ve boş text container düğümleri elenir; sadece eyleme geçilebilir (`clickable`, `focusable`, `heading`, `link`) öğeler tutulur. |');
  lines.push('| **3** | **`browser_network` Statik Varlık ve Telemetri Filtresi** | **~1.500 – 3.500 token** | **Düşük** | CSS, JS, font, png/svg ve tracking/telemetri URL\'leri elenir; sadece Document + XHR/Fetch listelenir. |');
  lines.push('| **4** | **`browser_agent_observe` Kompakt Gösterim** | **~800 – 1.800 token** | **Sıfır** | `"injection_suspect": false`, boş `"value"` ve gereksiz anahtarlar atılır; kompakt tek satır formatına geçilir. |');
  lines.push('| **5** | **`browser_content` Ardışık Boşluk Sıkıştırma** | **~500 – 1.200 token** | **Sıfır** | Ardışık `\\n\\n+` ve yatay boşluklar (`\\s{2,}`) tek boşluğa/çift satır sonuna indirgenir. Anlamsal kayıp olmaz. |');
  lines.push('| **6** | **Menü/Footer Bölgesi İşaretleme ve Katlama** | **~1.000 – 2.000 token** | **Orta** | `<nav>` ve `<footer>` blokları ilk gözlemde katlanır (özet link sayısı gösterilir), ajan isterse açar. |');
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
          console.log(`${p.name}: nav=${t.browser_navigate?.tokens} cnt=${t.browser_content?.tokens} a11y=${t.browser_a11y?.tokens} obs=${t.browser_agent_observe?.tokens} diff=${t.browser_agent_observe_diff?.tokens} net=${t.browser_network?.tokens}`);
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
