/**
 * example.cdpt.js — minimal fixture for cdpilot test runner smoke tests.
 * These tests do not require a browser (no goto/click calls).
 */

test('noop test passes', async (t) => {
  // no-op: verifies runner loads and executes tests
});

test('math check', async (t) => {
  if (1 + 1 !== 2) throw new Error('math broken');
});

test('async noop', async (t) => {
  await new Promise((r) => setTimeout(r, 5));
});
