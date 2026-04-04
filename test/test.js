#!/usr/bin/env node

/**
 * cdpilot — basic test suite
 * Tests CLI entry point, browser detection, and command routing
 */

const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');
const assert = require('assert');

const CLI = path.join(__dirname, '..', 'bin', 'cdpilot.js');
let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`    ${err.message}`);
  }
}

function run(args = '') {
  return execSync(`node ${CLI} ${args} 2>&1`, {
    timeout: 10000,
    encoding: 'utf-8',
    env: { ...process.env, CDP_PORT: '19222' }, // avoid conflict with real browser
  });
}

console.log('\n  cdpilot tests\n');

// ── CLI basics ──

test('--version prints version', () => {
  const out = run('--version');
  assert(out.includes('0.2.0'), 'Should print version');
});

test('-v prints version', () => {
  const out = run('-v');
  assert(out.includes('0.2.0'), 'Should print version');
});

test('help shows usage', () => {
  const out = run('help');
  assert(out.includes('cdpilot'), 'Should show cdpilot name');
  assert(out.includes('USAGE'), 'Should show USAGE section');
});

test('--help shows usage', () => {
  const out = run('--help');
  assert(out.includes('NAVIGATION'), 'Should show NAVIGATION section');
});

test('no args shows help', () => {
  const out = run('');
  assert(out.includes('SETUP'), 'Should show SETUP section');
});

// ── Setup ──

test('setup detects browser', () => {
  const out = run('setup');
  assert(out.includes('Browser:'), 'Should show browser detection');
  assert(out.includes('Profile:'), 'Should show profile path');
});

test('setup detects python', () => {
  const out = run('setup');
  assert(out.includes('Python:'), 'Should show Python detection');
});

// ── File structure ──

test('cdpilot.py exists', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  assert(fs.existsSync(pyPath), 'src/cdpilot.py should exist');
});

test('package.json has bin field', () => {
  const pkg = require('../package.json');
  assert(pkg.bin && pkg.bin.cdpilot, 'Should have bin.cdpilot');
});

test('package.json has correct name', () => {
  const pkg = require('../package.json');
  assert.strictEqual(pkg.name, 'cdpilot');
});

// ── Python script basics ──

test('python script has version', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  if (fs.existsSync(pyPath)) {
    const content = fs.readFileSync(pyPath, 'utf-8');
    assert(content.includes('__version__'), 'Should have __version__');
  }
});

test('python script has shebang', () => {
  const pyPath = path.join(__dirname, '..', 'src', 'cdpilot.py');
  if (fs.existsSync(pyPath)) {
    const content = fs.readFileSync(pyPath, 'utf-8');
    assert(content.startsWith('#!/usr/bin/env python3'), 'Should have python3 shebang');
  }
});

// ── Summary ──

console.log(`\n  ${passed} passed, ${failed} failed\n`);
process.exit(failed > 0 ? 1 : 0);
