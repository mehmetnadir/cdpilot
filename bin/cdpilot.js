#!/usr/bin/env node

/**
 * cdpilot — Zero-dependency browser automation CLI
 * Entry point: detects Python, finds browser, delegates to cdpilot.py
 */

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');

const SCRIPT = path.join(__dirname, '..', 'src', 'cdpilot.py');
const VERSION = require('../package.json').version;

// ── Browser Detection ──

function findBrowser() {
  // User override
  if (process.env.CHROME_BIN) {
    if (fs.existsSync(process.env.CHROME_BIN)) return process.env.CHROME_BIN;
  }

  const platform = os.platform();
  const candidates = [];

  if (platform === 'darwin') {
    candidates.push(
      '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
    );
  } else if (platform === 'linux') {
    candidates.push(
      'brave-browser',
      'brave',
      'google-chrome',
      'google-chrome-stable',
      'chromium-browser',
      'chromium',
    );
  } else if (platform === 'win32') {
    const programFiles = process.env['PROGRAMFILES'] || 'C:\\Program Files';
    const programFilesX86 = process.env['PROGRAMFILES(X86)'] || 'C:\\Program Files (x86)';
    const localAppData = process.env.LOCALAPPDATA || '';
    candidates.push(
      path.join(programFiles, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(programFilesX86, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(localAppData, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'),
      path.join(programFiles, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(programFilesX86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
      path.join(localAppData, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    );
  }

  for (const bin of candidates) {
    if (bin.startsWith('/') || bin.includes('\\')) {
      if (fs.existsSync(bin)) return bin;
    } else {
      try {
        execSync(`which ${bin} 2>/dev/null`, { stdio: 'pipe' });
        return bin;
      } catch {}
    }
  }
  return null;
}

// ── Python Detection ──

function findPython() {
  for (const cmd of ['python3', 'python']) {
    try {
      const ver = execSync(`${cmd} --version 2>&1`, { stdio: 'pipe' }).toString().trim();
      const match = ver.match(/(\d+)\.(\d+)/);
      if (match && parseInt(match[1]) >= 3 && parseInt(match[2]) >= 8) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

// ── Python websockets Detection ──

function findWebsockets() {
  for (const cmd of ['pip3', 'pip']) {
    try {
      const ver = execSync(`${cmd} show websockets 2>&1`, { stdio: 'pipe' }).toString().trim();
      const match = ver.match(/Name: websockets/);
      if (match) {
        return cmd;
      }
    } catch {}
  }
  return null;
}

// ── Setup Command ──

function runSetup() {
  const browser = findBrowser();
  const config = resolveProjectConfig();

  console.log('\n  cdpilot setup\n');
  console.log(`  Browser:    ${browser || '❌ Not found'}`);
  console.log(`  Profile:    ${config.profileDir}`);
  console.log(`  CDP Port:   ${config.port === '0' ? 'auto' : config.port}`);
  console.log(`  Project:    ${config.projectId || 'manual mode'}`);
  console.log(`  Python:     ${findPython() || '❌ Not found'}`);
  console.log(`  websockets: ${findWebsockets() || '❌ Not found'}`);

  if (!browser) {
    console.log('\n  ❌ No compatible browser found.');
    console.log('  Install Brave (recommended): https://brave.com/download/');
    console.log('  Or Google Chrome: https://www.google.com/chrome/\n');
    process.exit(1);
  }

  if (!findPython()) {
    console.log('\n  ❌ Python 3.8+ not found.');
    console.log('  Install: https://www.python.org/downloads/\n');
    process.exit(1);
  }

  if (!findWebsockets()) {
    console.log('\n  ❌ Python websockets not found.');
    console.log('  Install: pip install websockets\n');
    process.exit(1);
  }

  // Create profile directory
  if (!fs.existsSync(config.profileDir)) {
    fs.mkdirSync(config.profileDir, { recursive: true });
    console.log(`\n  ✓ Created profile: ${config.profileDir}`);
  } else {
    console.log(`\n  ✓ Profile exists: ${config.profileDir}`);
  }

  console.log('  ✓ Setup complete! Run: cdpilot launch\n');
}

// ── Pre-flight Check (runs on first launch) ──

function checkWebsockets(python) {
  try {
    execSync(`${python} -c "import websockets"`, { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

function preflight() {
  const markerFile = path.join(os.homedir(), '.cdpilot', '.preflight-done');

  // Skip if already passed (not first run) and all deps present
  const python = findPython();
  const browser = findBrowser();
  if (fs.existsSync(markerFile) && python && browser && checkWebsockets(python)) {
    return; // All good, skip silently
  }

  console.log(`\n  cdpilot v${VERSION} — Pre-flight Check`);
  console.log('  ' + '─'.repeat(35) + '\n');

  // 1. Python
  if (python) {
    const ver = execSync(`${python} --version 2>&1`, { stdio: 'pipe' }).toString().trim();
    console.log(`  ✓ ${ver}`);
  } else {
    console.log('  ✗ Python 3.8+ not found');
    console.log('    → Install: https://www.python.org/downloads/\n');
    process.exit(1);
  }

  // 2. websockets
  if (checkWebsockets(python)) {
    console.log('  ✓ websockets');
  } else {
    console.log('  ✗ websockets — installing...');
    try {
      execSync(`${python} -m pip install websockets --quiet --disable-pip-version-check`, { stdio: 'pipe' });
      if (checkWebsockets(python)) {
        console.log('  ✓ websockets (installed)');
      } else {
        console.log('  ✗ websockets install failed');
        console.log('    → Run manually: pip install websockets\n');
        process.exit(1);
      }
    } catch {
      console.log('  ✗ websockets auto-install failed');
      console.log('    → Run manually: pip install websockets\n');
      process.exit(1);
    }
  }

  // 3. Browser
  if (browser) {
    const name = path.basename(browser).replace(/\.exe$/i, '');
    console.log(`  ✓ ${name} (${browser})`);
  } else {
    console.log('  ✗ No compatible browser found');
    console.log('    → Install Brave (recommended): https://brave.com/download/');
    console.log('    → Or Chrome: https://www.google.com/chrome/\n');
    process.exit(1);
  }

  // Mark as done
  const dir = path.dirname(markerFile);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(markerFile, new Date().toISOString());

  console.log('\n  Ready!\n');
}

// ── Status Command ──

function runStatus() {
  const config = resolveProjectConfig();
  const port = config.port === '0' ? '9222' : config.port;
  const projLabel = config.projectId ? ` [${config.projectId}]` : '';
  console.log(`\n  cdpilot status (port ${port})${projLabel}\n`);

  try {
    const http = require('http');
    const req = http.get(`http://127.0.0.1:${port}/json/version`, { timeout: 2000 }, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          const info = JSON.parse(data);
          console.log(`  ✓ Connected`);
          console.log(`  Browser: ${info.Browser || 'Unknown'}`);
          console.log(`  Protocol: ${info['Protocol-Version'] || 'Unknown'}`);
          console.log(`  WebSocket: ${info.webSocketDebuggerUrl || 'N/A'}\n`);
        } catch {
          console.log('  ✓ CDP responding but version info unavailable\n');
        }
      });
    });
    req.on('error', () => {
      console.log('  ❌ No browser connected on this port.');
      console.log('  Run: cdpilot launch\n');
    });
    req.on('timeout', () => {
      req.destroy();
      console.log('  ❌ Connection timeout.');
      console.log('  Run: cdpilot launch\n');
    });
  } catch {
    console.log('  ❌ Could not check status.\n');
  }
}

// ── Version ──

function showVersion() {
  console.log(`cdpilot v${VERSION}`);
}

// ── Project-Based Multi-Instance ──

function getProjectId() {
  const cwd = process.cwd();
  const dirName = path.basename(cwd).replace(/[^a-zA-Z0-9-]/g, '').slice(0, 20);
  const crypto = require('crypto');
  const hash = crypto.createHash('md5').update(cwd).digest('hex').slice(0, 6);
  return dirName ? `${dirName}-${hash}` : hash;
}

function resolveProjectConfig() {
  const envPort = process.env.CDP_PORT;
  const envProfile = process.env.CDPILOT_PROFILE;

  // Full manual override
  if (envPort && envProfile) {
    return { port: envPort, profileDir: envProfile, projectId: null };
  }

  const projectId = getProjectId();
  const registryFile = path.join(os.homedir(), '.cdpilot', 'registry.json');
  const defaultProfile = path.join(os.homedir(), '.cdpilot', 'projects', projectId, 'profile');

  let registry = {};
  try {
    const data = JSON.parse(fs.readFileSync(registryFile, 'utf-8'));
    registry = data.projects || {};
  } catch {}

  const info = registry[projectId];
  if (info) {
    return {
      port: envPort || String(info.port || 9222),
      profileDir: envProfile || info.profile_dir || defaultProfile,
      projectId,
    };
  }

  // New project: let Python allocate port (pass 0 for auto)
  return {
    port: envPort || '0',
    profileDir: envProfile || defaultProfile,
    projectId,
  };
}

// ── Help ──

function showHelp() {
  console.log(`
  cdpilot v${VERSION} — Zero-dependency browser automation

  USAGE
    cdpilot <command> [args]

  SETUP
    setup              Auto-detect browser, create isolated profile
    launch             Start browser with CDP enabled
    status             Check browser connection
    stop               Stop browser

  NAVIGATION
    go <url>           Navigate to URL
    content            Get page text content
    html               Get page HTML
    shot [file]        Take screenshot
    pdf [file]         Save page as PDF

  INTERACTION
    click <sel>        Click element
    type <sel> <text>  Type into input
    fill <sel> <val>   Set input value (React-compatible)
    submit <form>      Submit form
    hover <sel>        Hover element
    keys <combo>       Keyboard shortcut

  DEBUGGING
    console [url]      Capture console logs
    network [url]      Monitor network requests
    debug [url]        Full diagnostic
    eval <js>          Execute JavaScript

  TABS
    tabs               List open tabs
    new-tab [url]      Open new tab
    close-tab [id]     Close tab

  PROJECTS
    projects           List all project browser instances
    project-stop <id>  Stop a specific project's browser
    stop-all           Stop all browser instances

  AI AGENT
    mcp                Start MCP server (stdin/stdout JSON-RPC)

  More: https://github.com/mehmetnadir/cdpilot#commands
`);
}

// ── Main ──

const args = process.argv.slice(2);
const cmd = args[0];

if (!cmd || cmd === 'help' || cmd === '--help' || cmd === '-h') {
  showHelp();
  process.exit(0);
}

if (cmd === '--version' || cmd === '-v') {
  showVersion();
  process.exit(0);
}

if (cmd === 'setup') {
  runSetup();
  process.exit(0);
}

if (cmd === 'status') {
  runStatus();
  // Don't exit immediately — let http callback complete
} else {
  // Pre-flight check on first run or 'launch' command
  if (cmd === 'launch') {
    preflight();
  }

  // Delegate to Python
  const python = findPython();
  if (!python) {
    console.error('Error: Python 3.8+ required. Install: https://www.python.org/downloads/');
    process.exit(1);
  }

  const browser = findBrowser();
  const config = resolveProjectConfig();

  const env = {
    ...process.env,
    CDPILOT_PROFILE: config.profileDir,
  };

  // Only pass CDP_PORT if explicitly set or resolved from registry (not 0)
  if (config.port !== '0') {
    env.CDP_PORT = config.port;
  }

  if (config.projectId) {
    env.CDPILOT_PROJECT_ID = config.projectId;
  }

  if (browser && !process.env.CHROME_BIN) {
    env.CHROME_BIN = browser;
  }

  const child = spawn(python, [SCRIPT, ...args], {
    stdio: 'inherit',
    env,
  });

  child.on('close', (code) => {
    process.exit(code || 0);
  });
}
