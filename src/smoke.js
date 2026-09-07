// Load index.html's script the way a browser would, and fail loudly if it throws.
//
// This exists because a page was published whose script died on the first line that
// touched the data: a `var` declared 45 lines below its first use, which hoisting turns
// into `undefined` rather than a ReferenceError, so the assignment threw and took the
// whole script with it. The static header still rendered, so the page looked plausible
// in a screenshot and was completely empty underneath.
//
// Deliberately not a browser and not a DOM library -- there is no pip here and there is
// no npm either. It is a shim just rich enough to run the page's setup and prove three
// things: the script parses, it runs to completion, and it renders rows into the list.
//
//     node src/smoke.js            # after src/build_site.py
//
// If the page grows features this shim cannot fake, widen the shim; do not delete the
// check. Publishing a blank page is the failure worth spending code to prevent.

const fs = require('fs');
const path = require('path');

const file = process.argv[2] || path.join(__dirname, '..', 'index.html');
const html = fs.readFileSync(file, 'utf8');

// The payload is cut out by position, not by pattern. A record's text contains the
// literal string "<script", so a regex looking for script tags finds one *inside* the
// JSON and matches from there -- which is how the first version of this file reported a
// syntax error in a dataset about spatial packages.
const OPEN = '<script id="DATA" type="application/json">';
const start = html.indexOf(OPEN);
if (start < 0) { console.error('FAIL: no DATA payload in the page'); process.exit(1); }
const bodyStart = start + OPEN.length;
// build_site.py escapes every "</" inside the blob, so the next literal </script> is the
// payload's own closing tag and cannot be part of the data.
const end = html.indexOf('</script>', bodyStart);
const payload = html.slice(bodyStart, end);
const rest = html.slice(0, start) + html.slice(end + '</script>'.length);

const scripts = [...rest.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);

if (!scripts.length) { console.error('FAIL: no script block in the page'); process.exit(1); }

// --- the smallest DOM that lets the page's own code run -------------------------
function makeEl(tag = 'div') {
  const el = {
    tagName: tag, children: [], dataset: {}, style: {}, classList: {
      add() {}, remove() {}, toggle() {}, contains() { return false; },
    },
    _html: '',
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    set textContent(v) { this._text = String(v); },
    get textContent() { return this._text || ''; },
    appendChild(c) { this.children.push(c); return c; },
    addEventListener() {}, removeEventListener() {},
    setAttribute() {}, getAttribute() { return null; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    focus() {}, blur() {}, scrollTo() {}, remove() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 0, height: 0 }; },
  };
  return el;
}

const byId = {};
const dataEl = makeEl('script');
dataEl.textContent = payload;
byId['DATA'] = dataEl;

const document = {
  getElementById(id) { return byId[id] || (byId[id] = makeEl()); },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  createElement: makeEl,
  addEventListener() {},
  body: makeEl('body'),
  documentElement: makeEl('html'),
  location: { hash: '', search: '' },
};

const sandbox = {
  document,
  console,
  window: null,
  location: { hash: '', search: '', href: 'https://example.invalid/' },
  history: { replaceState() {}, pushState() {} },
  localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
  requestAnimationFrame: (fn) => fn(),
  setTimeout: (fn) => { try { fn(); } catch (e) { /* deferred work is not under test */ } return 0; },
  clearTimeout() {},
  navigator: { clipboard: { writeText: () => Promise.resolve() }, userAgent: 'smoke' },
  addEventListener() {},
  JSON, Math, Date, RegExp, String, Number, Object, Array, Boolean, Error, isNaN, parseInt, parseFloat,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

const vm = require('vm');
vm.createContext(sandbox);

let failed = false;
for (const [i, code] of scripts.entries()) {
  try {
    vm.runInContext(code, sandbox, { filename: `page-script-${i}.js`, timeout: 20000 });
  } catch (e) {
    console.error(`FAIL: script block ${i} threw: ${e && e.message}`);
    if (e && e.stack) console.error(e.stack.split('\n').slice(0, 4).join('\n'));
    failed = true;
  }
}
if (failed) process.exit(1);

// --- did it actually render anything? -------------------------------------------
// A script that runs to completion but paints nothing is the same bug wearing a hat.
const list = byId['list'];
const rendered = (list && list.innerHTML) || '';
const cards = (rendered.match(/class="card"/g) || []).length;
const stats = ((byId['stats'] || {}).innerHTML || '').length;

if (cards === 0) {
  console.error('FAIL: the script ran but rendered no cards into #list');
  process.exit(1);
}
console.log(`ok: ${scripts.length} script block(s) ran, ${cards} cards rendered, ` +
            `stats ${stats > 0 ? 'populated' : 'EMPTY'}`);
if (stats === 0) { console.error('FAIL: #stats was left empty'); process.exit(1); }
