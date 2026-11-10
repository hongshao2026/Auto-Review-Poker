// Numeric and event regressions against the actual shared UI adapter.
// This does not launch HRC, a browser, a server, or a solver.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const context = vm.createContext({ window: {} });
vm.runInContext(fs.readFileSync(path.join(root, 'web/hrc-hand-setup.js'), 'utf8'), context);
const setup = Object.create(context.window.HrcHandSetup.prototype);
const fields = new Map();
setup.$ = id => fields.get(id);
setup.dispatch = field => { setup.lastDispatched = field; };
setup.refresh = () => { setup.refreshCount = (setup.refreshCount || 0) + 1; };
setup.host = {
  state: { formBaseConfig: { engine: 'hrc_custom' } },
  collectPlayers: () => [{}, {}],
  formError: message => { setup.lastError = message; },
};
for (const [id, value] of [
  ['scenario-fields', ''], ['big-blind', '100'], ['player-stack-0', '1500'],
  ['immediate-fraction', '50'], ['bounty-0', '10'], ['utility', 'chips'],
  ['fgs-enabled', ''], ['payouts', ''],
]) fields.set(id, { id, value, disabled: false, checked: false });
const input = (column, value) => ({ id: 'derived-editor', value, dataset: { setupColumn: column, setupRow: '0' }, disabled: false });
const results = [];
function check(name, fn) { fn(); results.push({ name, passed: true }); }
function prizes(raw) {
  setup.prizeRows = { querySelectorAll: () => raw.map(value => ({ value })) };
  setup.writePrizes(); return fields.get('payouts').value;
}
check('original prize jump map expands only through terminal zero', () => {
  assert.equal(prizes(['100', '60', '', '', '30', '', '', '0']), '100, 60, 60, 60, 30, 30, 30');
});
check('deleting a middle jump inherits the previous amount', () => {
  assert.equal(prizes(['100', '..', '', '', '30', '', '', '0']), '100, 100, 100, 100, 30, 30, 30');
});
check('additional terminal zero does not fabricate paid places', () => {
  assert.equal(prizes(['100', '60', '', '', '30', '', '', '0', '', '0']), '100, 60, 60, 60, 30, 30, 30');
});
check('deleting terminal zero ends at preceding explicit jump', () => {
  assert.equal(prizes(['100', '60', '', '', '30', '', '', '..']), '100, 60, 60, 60, 30');
});
check('pure bounty retains canonical zero prize', () => assert.equal(prizes(['0', '', '']), '0'));
check('missing first prize remains invalid rather than silently inheriting', () => assert.equal(prizes(['', '30', '20']), ''));
check('ten visual rows do not create trailing zero payouts', () => assert.equal(prizes(['50', '30', '20', '', '', '', '', '', '', '']), '50, 30, 20'));
check('more than ten paid places survive an early-row edit', () => {
  const raw = Array.from({ length: 14 }, (_, index) => String(140 - 10 * index));
  raw[0] = '150'; assert.equal(prizes([...raw, '0']), raw.join(', '));
});
check('BB edit writes chips without changing the blind', () => {
  setup.input({ target: input('bb', '20') });
  assert.equal(fields.get('player-stack-0').value, '2000'); assert.equal(fields.get('big-blind').value, '100');
});
check('custom BB conversion rounds to four decimal input units', () => {
  fields.get('big-blind').value = '0.3333'; setup.input({ target: input('bb', '1.234567') });
  assert.equal(fields.get('player-stack-0').value, '0.4115');
});
check('empty derived BB preserves invalid input instead of inventing zero', () => {
  setup.input({ target: input('bb', '') }); assert.equal(fields.get('player-stack-0').value, '');
});
check('legacy input units are not silently quantized as custom chips', () => {
  setup.host.state.formBaseConfig.engine = undefined;
  setup.input({ target: input('bb', '1.234567') }); assert.equal(Number(fields.get('player-stack-0').value), 1.234567 * .3333);
  setup.host.state.formBaseConfig.engine = 'hrc_custom';
});
check('PKO cash column inverts the immediate fraction', () => {
  setup.input({ target: input('cash', '7') }); assert.equal(fields.get('bounty-0').value, '14');
});
check('zero immediate fraction cannot divide or modify the full bounty', () => {
  fields.get('immediate-fraction').value = '0'; setup.input({ target: input('cash', '9') });
  assert.equal(fields.get('bounty-0').value, '14');
});
check('disabled original-source form rejects derived writes', () => {
  const before = fields.get('player-stack-0').value; fields.get('scenario-fields').disabled = true;
  setup.input({ target: input('bb', '123') }); assert.equal(fields.get('player-stack-0').value, before);
  fields.get('scenario-fields').disabled = false;
});
check('compound equity input does not refresh before canonical commit', () => {
  const before = setup.refreshCount; setup.input({ target: { id: 'hrc-equity-mode' } });
  assert.equal(setup.refreshCount, before);
});
check('FGS choice maps to canonical ICM plus enabled FGS', () => {
  setup.change({ target: { id: 'hrc-equity-mode', value: 'fgs', disabled: false } });
  assert.equal(fields.get('utility').value, 'icm'); assert.equal(fields.get('fgs-enabled').checked, true);
});
check('MTT choice clears FGS without changing the utility enum', () => {
  setup.change({ target: { id: 'hrc-equity-mode', value: 'mtt_icm', disabled: false } });
  assert.equal(fields.get('utility').value, 'mtt_icm'); assert.equal(fields.get('fgs-enabled').checked, false);
});
check('multi-column TSV is rejected without losing later columns or modifying inputs', () => {
  const before = fields.get('player-stack-0').value;
  setup.paste({ target: input('chips', ''), clipboardData: { getData: () => '100\t200\n300\t400' }, preventDefault() {} });
  assert.match(setup.lastError, /多列/); assert.equal(fields.get('player-stack-0').value, before);
});
check('IME composition does not navigate cells', () => setup.keydown({ isComposing: true }));
check('missing numeric values stay unknown', () => { assert.equal(setup.number(null), null); assert.equal(setup.number(''), null); assert.equal(setup.number('0'), 0); });
const report = {
  passed: true, cases: results.length,
  scope: 'Actual HrcHandSetup methods in an isolated JS context with field stubs. No browser layout, persistence codec or solver claims.',
  evidence: 'research/HRC-HAND-SETUP.md; installed HRC input screenshots in analysis/hrc-desktop/screens.',
  results,
};
fs.writeFileSync(path.join(root, 'reports/hrc-hand-setup-adapter-validation.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify({ passed: report.passed, cases: report.cases, report: 'reports/hrc-hand-setup-adapter-validation.json' }));
