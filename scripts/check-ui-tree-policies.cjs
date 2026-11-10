// Focused state regression tests using the actual buildless UI helper functions.
// No browser, server, training, HRC executable or strategy file is used.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const metadata = JSON.parse(fs.readFileSync(path.join(root, 'analysis/hrc-custom-ui/tree-policy-metadata.json'), 'utf8'));
const elements = new Map();
class Field {
  constructor() { this.value = ''; this.checked = false; this.hidden = false; this.disabled = false; this.style = {}; this.scrollHeight = 300; this.children = new Map(); }
  set value(value) { this._value = String(value); }
  get value() { return this._value; }
  querySelector(selector) { if (!this.children.has(selector)) this.children.set(selector, new Field()); return this.children.get(selector); }
  focus() { this.focused = true; }
}
const $ = (id) => { if (!elements.has(id)) elements.set(id, new Field()); return elements.get(id); };
const state = { meta: { custom_native: metadata }, treePolicyDrafts: { preflop: {}, postflop: {} }, treeEditorMode: 'form', policyTopologyDirty: false };
const messages = [];
const context = vm.createContext({ $, state, console, clone: (x) => JSON.parse(JSON.stringify(x)),
  clearErrors: () => {}, markEdited: () => { state.dirty = true; }, announce: (s) => messages.push(s),
  formError: (s) => messages.push(s), showFieldError: (id, s) => messages.push(`${id}: ${s}`) });
vm.runInContext(source.slice(source.indexOf('  function parseList('), source.indexOf('  function readNativeOptions(')), context);
const run = (code) => vm.runInContext(code, context);
const results = [];
function check(name, callback) { callback(); results.push({ name, passed: true }); }
run('fillTreeFields(state.meta.custom_native.default_config.tree_settings)');
check('simple form input survives general round trip; no cross-policy keys', () => {
  $('tree-open').value = '2.7bb, all-in';
  $('preflop-policy').value = 'general'; run('changeTreePolicy("preflop")');
  let settings = JSON.parse($('tree-settings-json').value);
  assert.equal(settings.preflop.id, 'preflop.settings.general');
  assert.equal(settings.preflop.settings.PREFLOP_SIZES, undefined);
  assert.equal(settings.postflop.id, 'postflop.settings.simple');
  assert.equal($('tree-basic-fields').disabled, true);
  assert.equal($('tree-basic-fields').hidden, true);
  assert.equal(state.treeEditorMode, 'json');
  settings.preflop.settings.SIZES_OPEN_BU = '9bb';
  $('tree-settings-json').value = JSON.stringify(settings);
  $('preflop-policy').value = 'simple'; run('changeTreePolicy("preflop")');
  settings = JSON.parse($('tree-settings-json').value);
  assert.equal(settings.preflop.settings.PREFLOP_SIZES[0], '2.7bb, all-in');
  assert.equal(settings.preflop.settings.SIZES_OPEN_BU, undefined);
  $('tree-editor-mode').value = 'form'; run('changeTreeEditor()');
  assert.equal($('tree-basic-fields').hidden, false);
  assert.equal($('tree-basic-fields').disabled, false);
  $('preflop-policy').value = 'general'; run('changeTreePolicy("preflop")');
  assert.equal(JSON.parse($('tree-settings-json').value).preflop.settings.SIZES_OPEN_BU, '9bb');
});
check('both streets retain their own General JSON values', () => {
  $('postflop-policy').value = 'general'; run('changeTreePolicy("postflop")');
  let settings = JSON.parse($('tree-settings-json').value);
  settings.postflop.settings.POSTFLOP_FLOP_BET = ['42%', '55%'];
  $('tree-settings-json').value = JSON.stringify(settings);
  $('postflop-policy').value = 'simple'; run('changeTreePolicy("postflop")');
  assert.equal(JSON.parse($('tree-settings-json').value).postflop.settings.POSTFLOP_FLOP_BET, undefined);
  $('postflop-policy').value = 'general'; run('changeTreePolicy("postflop")');
  settings = JSON.parse($('tree-settings-json').value);
  assert.deepEqual(settings.postflop.settings.POSTFLOP_FLOP_BET, ['42%', '55%']);
  assert.equal(settings.preflop.settings.SIZES_OPEN_BU, '9bb');
  assert.equal(settings.postflop.settings.POSTFLOP_GEO, undefined);
});
check('malformed JSON blocks switch without changing text or stored configuration', () => {
  const draft = JSON.stringify(state.treeSettingsDraft);
  $('tree-settings-json').value = '{"bad":';
  $('postflop-policy').value = 'simple'; run('changeTreePolicy("postflop")');
  assert.equal($('tree-settings-json').value, '{"bad":');
  assert.equal($('postflop-policy').value, 'general');
  assert.equal(JSON.stringify(state.treeSettingsDraft), draft);
  assert.equal($('tree-settings-json').focused, true);
});
check('General malformed field types become inline parse errors', () => {
  let settings = JSON.parse(JSON.stringify(state.treeSettingsDraft));
  settings.preflop.settings.ALLOWED_FLATS_PER_RAISE = 'not an array';
  $('tree-settings-json').value = JSON.stringify(settings);
  const result = run('(() => { const errors = []; return { value: parseTreeJson(errors), errors }; })()');
  assert.equal(result.value, null); assert.match(result.errors[0][1], /ALLOWED_FLATS/);
});
check('sparse General JSON merges only matching defaults', () => {
  $('tree-settings-json').value = JSON.stringify({ mode: 'ui', preflop: { id: 'preflop.settings.general', settings: { SIZES_OPEN_BU: '4bb' } }, postflop: { id: 'postflop.settings.simple', settings: {} } });
  const settings = run('parseTreeJson([])');
  assert.equal(settings.preflop.settings.SIZES_OPEN_BU, '4bb');
  assert.equal(settings.preflop.settings.PREFLOP_SIZES, undefined);
  assert.equal(settings.postflop.settings.POSTFLOP_FLOP_BET, undefined);
  assert.equal(Object.keys(settings.preflop.settings).length, Object.keys(metadata.tree_policy_defaults.preflop.general.settings).length);
});
check('General cannot be rendered through the Simple form', () => {
  $('tree-editor-mode').value = 'form'; run('changeTreeEditor()');
  assert.equal(state.treeEditorMode, 'json');
  assert.equal($('tree-editor-mode').value, 'json');
  assert.equal($('tree-editor-mode').querySelector('option[value="form"]').disabled, true);
});
check('old metadata continues Simple without exposing fake General defaults', () => {
  delete state.meta.custom_native.tree_policy_defaults;
  const result = run('(() => { const errors = []; return { value: parseTreeJson(errors), errors }; })()');
  assert.equal(result.value, null); assert.match(result.errors[0][1], /未提供/);
  run('fillTreeFields(state.meta.custom_native.default_config.tree_settings)');
  assert.equal(state.treeSettingsDraft.preflop.id, 'preflop.settings.simple');
});
const report = { passed: true, cases: results.length, scope: 'Actual UI helpers in isolated JS context with field mocks; protects settings preservation and validation, not a browser or training test.', results };
fs.writeFileSync(path.join(root, 'reports/ui-tree-policy-state-validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
