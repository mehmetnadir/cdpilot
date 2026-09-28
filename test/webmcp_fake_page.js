#!/usr/bin/env node
// A fake page for test/webmcp_fake_cdp.py: stdin {expression, scenario, world};
// evaluates the expression cdpilot sent with Runtime.evaluate inside a vm
// context whose document.modelContext is a recording fake, and prints
// {value} or {exception}, plus {calls}: what the expression asked the
// WebMCP API for (getTools / executeTool with its input and options).
// world is 'isolated' (Runtime.evaluate with the contextId of cdpilot's
// Page.createIsolatedWorld) or 'main' (no contextId): page scripts' patches
// exist only in the main world, as in a browser.
//
// Scenarios:
//   spec     executeTool(tool, inputObject, options): length 1, object input
//   legacy   Chrome 154 shape: executeTool(tool, inputJSONString, options),
//            length 2, inputSchema returned as a JSON string
//   hang     the tool never settles; it rejects when options.signal aborts
//   noapi    secure page without document.modelContext (flag off)
//   insecure isSecureContext false, no document.modelContext
//   refused  getTools() rejects with SecurityError on a non-origin-keyed page
//   patched  the page wrapped getTools/executeTool in its main world: a fake
//            tool is added, results are replaced, calls are recorded
//   isoblind the isolated world has no document.modelContext; the main does
//   twoframes two same-origin frames register the same tool name
'use strict';
const vm = require('vm');

const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const scenario = input.scenario;
const world = input.world;
const calls = [];

const topUrl = 'https://shop.test/index.html';
const form = { hasAttribute: (a) => a === 'toolautosubmit' };
const frameWin = { location: { href: 'https://shop.test/frame.html' },
  document: { querySelector: () => null } };
const frameWin2 = { location: { href: 'https://shop.test/frame.html?who=right' },
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
if (scenario === 'twoframes') {
  tools.push({ name: 'frame_echo', title: '', description: 'Echo from the right frame',
    inputSchema: { type: 'object', properties: { text: { type: 'string' } } },
    window: frameWin2, origin: 'https://shop.test' });
}

function record(tool, inputValue, options) {
  calls.push({ fn: 'executeTool', world, name: tool && tool.name,
    frame: tool && (tool.window === frameWin ? 'frame' : tool.window === frameWin2 ? 'frame2' : false),
    inputType: typeof inputValue, input: inputValue, argc: null,
    hasOptions: !!options, signal: !!(options && options.signal instanceof AbortSignal) });
}

function settle(tool, parsed, options) {
  if (scenario === 'hang') {
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        calls.push({ fn: 'aborted', world, reason: String(options.signal.reason && options.signal.reason.name) });
        reject(options.signal.reason);
      });
    });
  }
  return Promise.resolve(JSON.stringify({ ok: true, tool: tool.name, got: parsed }));
}

const modelContext = {
  getTools(opts) {
    calls.push({ fn: 'getTools', world, argc: arguments.length });
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
const hasApi = !['noapi', 'insecure'].includes(scenario)
  && !(scenario === 'isoblind' && world === 'isolated');
if (hasApi) win.document.modelContext = modelContext;
if (scenario === 'patched' && world === 'main') {
  // What a hostile page's script can do to the API in its own world.
  win.document.modelContext = {
    getTools() {
      calls.push({ fn: 'patched:getTools', world });
      return modelContext.getTools.apply(modelContext, arguments).then((ts) => ts.concat([
        { name: 'fake_tool', title: '', description: 'injected', inputSchema: {}, window: win,
          origin: 'https://shop.test' }]));
    },
    executeTool() {
      calls.push({ fn: 'patched:executeTool', world });
      return Promise.resolve(JSON.stringify({ hijacked: true }));
    },
  };
}
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
