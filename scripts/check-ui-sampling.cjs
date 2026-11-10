// Exercise production sampling adapters without starting a server or solver.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const sandbox = vm.createContext({ window: {} });
vm.runInContext(fs.readFileSync(path.join(root, 'web/hrc-workbench.js'), 'utf8'), sandbox);
const Desktop = sandbox.window.PreflopDesktop;
const plain = value => JSON.parse(JSON.stringify(value));
const results = [];
const context = { supported: true, canResume: true, completed: 10000000, maxSamples: 1000000000,
  scopes: ['entire_tree', 'selected_subtree'], modes: ['ci', 'samples', 'time'],
  subtreeAllowed: true, path: [0, 0, 0, 0, 0] };
const values = { algorithm: 'v4', scope: 'entire_tree', mode: 'ci', target: '10',
  samples: '50000000', seconds: '60', threads: '4', cap: '', hardSeconds: '', resetRegret: false, resetAverage: false };
function check(name, fn) { fn(); results.push({ name, passed: true }); }
function options(patch = {}, contextPatch = {}) { return plain(Desktop.samplingOptions({ ...values, ...patch }, { ...context, ...contextPatch })); }
check('formal CI request uses current hand overrides without a poker config', () => {
  const p = options();
  assert.equal(p.sampling_stage, 'calculation'); assert.equal(p.target_ci, 10); assert.equal(p.track_ci, true);
  assert.equal(p.stopping_mode, 'ci'); assert.equal(p.solver_mode, 'v4');
  assert.equal('iterations' in p, false); assert.equal('config' in p, false); assert.equal('stop_after_seconds' in p, false);
  assert.deepEqual(p.sampling_path, []); assert.equal(p.reset_regret, false); assert.equal(p.reset_average, false);
});
check('selected subtree sends the decision prefix, never appends selected action', () => {
  assert.deepEqual(options({ scope: 'selected_subtree' }).sampling_path, [0, 0, 0, 0, 0]);
});
check('scope description resolves cached parent actions without invented Action numbers', () => {
  const desktop = Object.create(Desktop.prototype);
  desktop.host = { actionLabel: action => action.kind };
  desktop.branches = new Map([['[]', { rows: [
    { path: [], actor_name: 'P1', action: { id: '0', kind: 'Fold' } },
    { path: ['0'], actor_name: 'P2', action: { id: '0', kind: 'Fold' } },
  ] }]]);
  assert.deepEqual(plain(desktop.decisionPathLabels(['0', '0'])), ['P1 Fold', 'P2 Fold']);
  assert.deepEqual(plain(desktop.decisionPathLabels(['1'])), []);
});
check('postflop or uninitialized subtree is rejected instead of falling back to full tree', () => {
  assert.throws(() => options({ scope: 'selected_subtree' }, { subtreeAllowed: false }), /翻前决策点/);
});
check('old service does not silently downgrade sampling scope', () => {
  assert.throws(() => options({}, { supported: false }), /不支持/);
  assert.throws(() => options({ scope: 'selected_subtree' }, { scopes: ['entire_tree'] }), /不支持/);
});
check('CI target has observed HRC lower bound 0.01', () => {
  assert.equal(options({ target: '.01' }).target_ci, .01);
  for (const target of ['', '0', '-1', '0.009', 'Infinity', 'NaN']) assert.throws(() => options({ target }));
});
check('explicit smaller CI sample safety cap is retained', () => assert.equal(options({ cap: '10001000' }).iterations, 10001000));
check('fixed samples adds fifty million to ten million already completed', () => {
  assert.equal(options({ mode: 'samples', samples: '50000000' }).iterations, 60000000);
});
check('additional samples are positive integers bounded by remaining capacity', () => {
  for (const samples of ['', '0', '-1', '1.5', '990000001']) assert.throws(() => options({ mode: 'samples', samples }));
  assert.equal(options({ mode: 'samples', samples: '1' }).iterations, 10000001);
  assert.equal(options({ mode: 'samples', samples: '990000000' }).iterations, 1000000000);
  assert.throws(() => options({ mode: 'samples' }, { completed: 1000000000 }));
});
check('an uninitialized hand respects the API minimum cumulative target of one hundred', () => {
  assert.throws(() => options({ mode: 'samples', samples: '99' }, { completed: 0 }));
  assert.equal(options({ mode: 'samples', samples: '100' }, { completed: 0 }).iterations, 100);
});
check('sample mode does not accidentally retain CI or time target', () => {
  const p = options({ mode: 'samples' });
  assert.equal(p.iterations, 60000000); assert.equal('target_ci' in p, false); assert.equal('stop_after_seconds' in p, false);
});
check('time mode has a duration target and a separate optional hard limit', () => {
  const p = options({ mode: 'time', hardSeconds: '90' });
  assert.equal(p.stop_after_seconds, 60); assert.equal(p.hard_seconds, 90); assert.equal('target_ci' in p, false);
});
check('blank hard limit explicitly removes an inherited resume limit', () => assert.equal(options().hard_seconds, null));
check('reset controls are meaningful only for a saved hand', () => {
  assert.equal(options({ resetRegret: true }).reset_regret, true);
  assert.equal(options({ resetRegret: true, resetAverage: true }, { canResume: false }).reset_average, false);
});
check('formal Reset Regret always also resets average strategies in the request', () => {
  assert.equal(options({ resetRegret: true, resetAverage: false }).reset_average, true);
  assert.equal(options({ resetRegret: false, resetAverage: true }).reset_regret, false);
  assert.equal(options({ resetRegret: false, resetAverage: true }).reset_average, true);
});
check('formal dialog checks and disables Reset Strategies while Reset Regret is selected', () => {
  const desktop = Object.create(Desktop.prototype), fields = new Map();
  desktop.samplingContext = { ...context, labels: [], path: [], node: {} };
  desktop.element = id => { if (!fields.has(id)) fields.set(id, { value: '', checked: false, disabled: false }); return fields.get(id); };
  desktop.element('sampling-until').value = 'ci';
  desktop.element('sampling-reset-regret').checked = true;
  desktop.refreshSampling();
  assert.equal(desktop.element('sampling-reset-average').checked, true);
  assert.equal(desktop.element('sampling-reset-average').disabled, true);
  desktop.element('sampling-reset-regret').checked = false;
  desktop.refreshSampling();
  assert.equal(desktop.element('sampling-reset-average').checked, true);
  assert.equal(desktop.element('sampling-reset-average').disabled, false);
});
check('thread and cap validation reject fractions and exhausted budget', () => {
  for (const threads of ['', '0', '33', '1.5']) assert.throws(() => options({ threads }));
  assert.throws(() => options({}, { completed: 1000000000 }));
});
const running = { status: 'running', config: { stopping_mode: 'ci', target_ci: 10, iterations: 1000000000 },
  summary: { iterations_completed: 10000000, ci: { value: 30 } }, progress: { iteration: 20000000, ci: { value: 20 } } };
check('live CI uses latest progress and never derives precision from sample percentage', () => {
  const p = Desktop.samplingProgress(running);
  assert.equal(p.indeterminate, true); assert.match(p.label, /20 \/ 10/); assert.match(p.detail, /20,000,000/); assert.match(p.detail, /无法估计/);
});
check('unknown CI remains indeterminate with explicit empty value', () => {
  const p = Desktop.samplingProgress({ ...running, summary: null, progress: { iteration: 100000 } });
  assert.equal(p.indeterminate, true); assert.match(p.label, /CI —/);
});
check('only server CI progress and ETA can produce an explicitly heuristic estimate', () => {
  const p = Desktop.samplingProgress({ ...running, progress: { iteration: 20000000, ci: { value: 20, progress: .25, eta_seconds: 120 } } });
  assert.equal(p.indeterminate, false); assert.equal(p.max, 1); assert.equal(p.value, .25);
  assert.match(p.detail, /25%（启发式）/); assert.match(p.detail, /120 秒（启发式）/);
});
check('zero first-snapshot CI progress is still indeterminate', () => {
  const p = Desktop.samplingProgress({ ...running, progress: { iteration: 20000000, ci: { value: 20, progress: 0, eta_seconds: null } } });
  assert.equal(p.indeterminate, true); assert.match(p.detail, /无法估计/);
});
check('stopped CI does not retain an animated indeterminate bar', () => {
  const p = Desktop.samplingProgress({ ...running, status: 'completed' }); assert.equal(p.hideProgress, true); assert.equal(p.indeterminate, false);
});
check('initialization has determinate samples and an explicit stage label', () => {
  const p = Desktop.samplingProgress({ status: 'running', config: { sampling_stage: 'initialization', stopping_mode: 'samples', iterations: 10000000 }, progress: { iteration: 2000 } });
  assert.equal(p.indeterminate, false); assert.equal(p.max, 10000000); assert.equal(p.value, 2000); assert.match(p.detail, /初始化/);
});
check('imported source count is never labeled original total iterations', () => {
  const p = Desktop.samplingProgress({ ...running, summary: { hrcz_import: { history_unknown: true } } }); assert.match(p.detail, /导入后新增/);
});

// Execute the actual app-level dispatch functions with isolated state/API spies.
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const dispatchSource = app.slice(app.indexOf('  async function initializeHand()'), app.indexOf('  function schedulePoll()'));
const appState = { meta: { training: { sampling_dialog: true, initialization_samples: 10000000 } }, view: 'draft',
  appliedConfig: { engine: 'hrc_custom', players: [{ name: 'SB', stack: 15 }], target_ci: 2, stop_after_seconds: 30, hard_seconds: 10, iterations: 60000000, opaqueSourceMetadata: { keep: true } } };
let dispatched;
const dispatchSandbox = vm.createContext({ state: appState, clone: plain, isNative: () => true,
  formError: text => { dispatched = { error: text }; },
  startSolve: async config => { dispatched = { config }; return true; },
  resumeJob: async (options, id) => { dispatched = { options, id }; return true; } });
vm.runInContext(dispatchSource, dispatchSandbox);
(async () => {
  await dispatchSandbox.initializeHand();
  check('New Hand initializes ten million global samples with no CI/time target', () => {
    assert.equal(dispatched.config.iterations, 10000000); assert.equal(dispatched.config.sampling_stage, 'initialization');
    assert.equal(dispatched.config.track_ci, false); assert.equal(dispatched.config.sampling_scope, 'entire_tree');
    for (const key of ['target_ci', 'stop_after_seconds', 'hard_seconds']) assert.equal(key in dispatched.config, false);
    assert.equal(appState.appliedConfig.iterations, 60000000);
  });
  const freshContext = { config: plain(appState.appliedConfig), jobId: null };
  await dispatchSandbox.submitSampling(freshContext, options());
  check('new formal run clears stale mode targets while retaining current hand metadata', () => {
    assert.equal(dispatched.config.target_ci, 10); assert.equal('iterations' in dispatched.config, false);
    assert.equal('stop_after_seconds' in dispatched.config, false); assert.equal('hard_seconds' in dispatched.config, false);
    assert.equal('reset_regret' in dispatched.config, false); assert.equal(dispatched.config.opaqueSourceMetadata.keep, true);
  });
  appState.view = 'result'; appState.job = { id: 'saved-source', can_resume: true };
  appState.formBaseConfig = { unrelatedDraft: true };
  await dispatchSandbox.submitSampling({ jobId: 'saved-source' }, options({ scope: 'selected_subtree' }));
  check('resume applies flat controls to selected saved hand without submitting left draft', () => {
    assert.equal(dispatched.id, 'saved-source'); assert.equal('config' in dispatched.options, false);
    assert.deepEqual(plain(dispatched.options.sampling_path), [0, 0, 0, 0, 0]);
  });
  const result = await dispatchSandbox.submitSampling({ jobId: 'different-hand' }, options());
  check('a stale dialog never resumes a different hand', () => { assert.equal(result, false); assert.match(appState.samplingError, /已变更/); });
  appState.view = 'draft'; appState.draftDirty = true;
  const dirty = await dispatchSandbox.submitSampling(freshContext, options());
  check('unapplied edited draft cannot replace current hand through Run', () => assert.equal(dirty, false));
  const report = { passed: results.length, failed: 0, scope: 'Production UI adapter methods; no solver/browser/server execution.', checks: results };
  fs.writeFileSync(path.join(root, 'reports/hrc-sampling-ui-adapter-validation.json'), JSON.stringify(report, null, 2) + '\n');
  console.log(`${results.length}/${results.length} sampling adapter checks passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
