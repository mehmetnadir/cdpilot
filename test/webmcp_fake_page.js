#!/usr/bin/env node
// A fake page for test/webmcp_fake_cdp.py: stdin {expression, scenario};
// evaluates the expression cdpilot sent with Runtime.evaluate inside a vm
// context whose document.modelContext is a recording fake, and prints
// {value} or {exception}, plus {calls}: what the expression asked the
// WebMCP API for (getTools / executeTool with its input and options).
//
// Scenarios:
//   spec     executeTool(tool, inputObject, options): length 1, object input
//   legacy   Chrome 154 shape: executeTool(tool, inputJSONString, options),
//            length 2, inputSchema returned as a JSON string
//   hang     the tool never settles; it rejects when options.signal aborts
//   noapi    secure page without document.modelContext (flag off)
//   insecure isSecureContext false, no document.modelContext
//   refused  getTools() rejects with SecurityError on a non-origin-keyed page
'use strict';
const vm = require('vm');

const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const scenario = input.scenario;
const calls = [];

const topUrl = 'https://shop.test/index.html';
const form = { hasAttribute: (a) => a === 'toolautosubmit' };
const frameWin = { location: { href: 'https://shop.test/frame.html' },
  document: { querySelector: () => null } };
const win = { location: { href: topUrl } };
win.document = { querySelector: (sel) => (sel.includes('"subscribe_newsletter"') ? form : null) };

const schema = { type: 'object', properties: { sku: { type: 'string' }, qty: { type: 'integer' } },
  required: ['sku', 'qty'] };
const asSchema = (s) => (scenario === 'legacy' ? JSON.stringify(s) : s);
const tools = [
  { name: 'add_to_cart', title: 'Add to cart', description: 'Add a product',
    inputSchema: asSchema(schema), window: win, origin: 'https://shop.test',
    annotations: { readOnlyHint: false, consequentialHint: true, untrustedContentHint: false } },
  { name: 'frame_echo', title: '', description: 'Echo from a frame',
    inputSchema: asSchema({ type: 'object', properties: { text: { type: 'string' } } }),
    window: frameWin, origin: 'https://shop.test' },
  { name: 'subscribe_newsletter', title: 'Subscribe', description: 'Form tool',
    inputSchema: asSchema({ type: 'object', properties: { email: { type: 'string' } } }),
    window: win, origin: 'https://shop.test' },
];

function record(tool, inputValue, options) {
  calls.push({ fn: 'executeTool', name: tool && tool.name, frame: tool && tool.window === frameWin,
    inputType: typeof inputValue, input: inputValue, argc: null,
    hasOptions: !!options, signal: !!(options && options.signal instanceof AbortSignal) });
}

function settle(tool, parsed, options) {
  if (scenario === 'hang') {
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        calls.push({ fn: 'aborted', reason: String(options.signal.reason && options.signal.reason.name) });
        reject(options.signal.reason);
      });
    });
  }
  return Promise.resolve(JSON.stringify({ ok: true, tool: tool.name, got: parsed }));
}

const modelContext = {
  getTools(opts) {
    calls.push({ fn: 'getTools', argc: arguments.length });
    if (scenario === 'refused') {
      return Promise.reject(new DOMException('not origin-keyed', 'SecurityError'));
    }
    return Promise.resolve(tools);
  },
};
if (scenario === 'legacy') {
  modelContext.executeTool = function(tool, inputArguments, options) {
    record(tool, inputArguments, options);
    calls[calls.length - 1].argc = arguments.length;
    if (typeof inputArguments !== 'string') {
      return Promise.reject(new DOMException('Failed to parse input arguments', 'UnknownError'));
    }
    return settle(tool, JSON.parse(inputArguments), options);
  };
} else {
  modelContext.executeTool = function(tool, inputObject = undefined, options = {}) {
    record(tool, inputObject, options);
    calls[calls.length - 1].argc = arguments.length;
    if (typeof inputObject !== 'object' || inputObject === null) {
      return Promise.reject(new TypeError('inputObject is not an object'));
    }
    return settle(tool, inputObject, options);
  };
}

const secure = scenario !== 'insecure';
const hasApi = !['noapi', 'insecure'].includes(scenario);
if (hasApi) win.document.modelContext = modelContext;
// `window` is the page's global object.
Object.assign(win, {
  window: win, isSecureContext: secure, originAgentCluster: scenario !== 'refused',
  navigator: {}, CSS: { escape: (s) => String(s).replace(/"/g, '\\"') },
  DOMException, AbortController, AbortSignal, setTimeout, clearTimeout,
});
vm.createContext(win);
// Inside the context `window` is the context's global proxy, not `win` itself:
// top-document tools must point at that, as a real RegisteredTool.window does.
const pageGlobal = vm.runInContext('globalThis', win);
for (const t of tools) if (t.window === win) t.window = pageGlobal;

(async () => {
  let out;
  try {
    out = { value: await vm.runInContext(input.expression, win) };
  } catch (e) {
    out = { exception: String(e && e.stack || e) };
  }
  out.calls = calls;
  process.stdout.write(JSON.stringify(out));
})();
