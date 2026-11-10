"use strict";

// Desktop interaction adapter. Calculation state and networking remain owned
// by app.js; this module arranges and inspects those same real calculations.
window.PreflopDesktop = class PreflopDesktop {
  constructor(host) {
    this.host = host;
    this.enabled = !!document.getElementById("hrc-strategy-body");
    this.contextKey = null;
    this.branches = new Map();
    this.expanded = new Set();
    this.loading = new Set();
    this.selectedAction = null;
    this.mode = "combined";
    this.source = "ours";
    this.home = false;
    this.generation = 0;
    if (!this.enabled) return;
    this.setupProperties();
    if (window.HrcHandSetup) this.handSetup = new window.HrcHandSetup(host, this.propertyGroups);
    this.setupHome();
    this.setupDialogs();
    document.addEventListener("click", (event) => this.click(event));
    document.addEventListener("keydown", (event) => this.keydown(event));
    document.getElementById("hrc-range-action")?.addEventListener("change", (event) => {
      this.selectedAction = event.target.value;
      this.host.renderRange(); this.paintTreeSelection();
    });
    document.getElementById("hrc-range-source")?.addEventListener("change", (event) => {
      this.source = event.target.value;
      this.host.renderRange();
    });
    this.setupSplitters();
    document.querySelectorAll('[data-hrc-menu-toggle],[data-hrc-tab],[data-hrc-range-mode]').forEach((button) => { button.disabled = false; });
    for (const group of ["left", "bottom"]) {
      const selected = document.querySelector(`[data-hrc-tab="${group}"][aria-selected="true"]`);
      if (selected) this.showTab(group, selected.dataset.hrcTarget);
    }
  }
  element(id) { return document.getElementById(id); }
  setupDialogs() {
    const dialog = this.element("hrc-new-dialog"); if (!dialog) return;
    const footer = this.make("div", "hrc-dialog-footer hrc-wizard-footer");
    for (const [id, text] of [["back", "< Back"], ["next", "Next >"], ["finish", "Finish"], ["cancel", "Cancel"]]) {
      const button = this.make("button", "button", text); button.type = "button"; button.dataset.wizardAction = id;
      button.addEventListener("click", async () => {
        if (id === "cancel") dialog.close();
        else if (id === "back") this.showWizardPage(this.wizardPage - 1);
        else if (id === "next") { if (this.host.readConfig(this.wizardPage)) this.showWizardPage(this.wizardPage + 1); }
        else {
          button.disabled = true;
          this.wizardSubmitting = true;
          footer.querySelectorAll("button").forEach((control) => { control.disabled = true; });
          const closeButton = dialog.querySelector('.hrc-dialog-title button'); if (closeButton) closeButton.disabled = true;
          try {
            const applied = await this.host.applyTree();
            if (applied === true && await this.host.initializeHand()) { this.wizardCommitted = true; dialog.close(); this.showTab("left", "hrc-strategy-pane"); this.showTab("bottom", "hrc-progress-pane"); }
            else {
              const error = this.element("scenario-form").querySelector('[aria-invalid="true"]');
              if (error) {
                this.showWizardPage(this.pageForField(error.id));
                error.focus();
              }
            }
          } finally {
            this.wizardSubmitting = false;
            footer.querySelectorAll("button").forEach((control) => { control.disabled = false; });
            if (closeButton) closeButton.disabled = false;
            if (dialog.open) this.showWizardPage(this.wizardPage);
          }
        }
      }); footer.append(button);
    }
    dialog.append(footer);
    dialog.addEventListener("cancel", (event) => { if (this.wizardSubmitting) event.preventDefault(); });
    dialog.addEventListener("submit", (event) => { if (this.wizardSubmitting) event.preventDefault(); });
    footer.querySelector('[data-wizard-action="cancel"]').addEventListener("click", (event) => { if (this.wizardSubmitting) event.stopImmediatePropagation(); }, true);
    dialog.addEventListener("close", async () => {
      const form = this.element("scenario-form");
      if (this.formPlaceholder?.parentNode) this.formPlaceholder.replaceWith(form);
      form.classList.remove("hrc-wizard-form");
      if (this.element("hrc-initialization-note")) this.element("hrc-initialization-note").hidden = true;
      for (const group of Object.values(this.propertyGroups || {})) { group.hidden = group.dataset.hrcEmpty === "true"; group.open = false; }
      const actions = form.querySelector(".scenario-actions"); if (actions) actions.hidden = false;
      if (!this.wizardCommitted && this.wizardBefore) {
        const before = this.wizardBefore, state = this.host.state;
        this.host.setConfig(before.config);
        state.formBaseConfig = before.baseConfig;
        for (const input of before.inputs) {
          const field = this.element(input.id); if (!field) continue;
          field.value = input.value; if (input.checked !== undefined) field.checked = input.checked;
        }
        state.appliedConfig = before.applied; state.view = before.view;
        state.draftDirty = before.dirty; state.formEdited = before.edited;
        for (const [key, value] of Object.entries(before.draftState)) state[key] = value;
        state.selectedHand = before.selectedHand;
        this.host.refreshFormVisibility();
        this.host.renderContext();
        await this.host.loadNode(before.path, before.labels);
        this.selectedAction = before.action; this.source = before.source;
        this.branches = before.branches; this.expanded = before.expanded;
        state.selectedHand = before.selectedHand;
        this.renderTree(); this.host.renderRange();
      }
      this.wizardBefore = null;
    });
    const sampling = this.element("hrc-sampling-dialog");
    sampling.querySelectorAll('[data-sampling-close]').forEach((button) => {
      button.addEventListener("click", () => { if (!this.samplingSubmitting) sampling.close(); }); button.disabled = false;
    });
    sampling.addEventListener("cancel", (event) => { if (this.samplingSubmitting) event.preventDefault(); });
    sampling.addEventListener("close", () => { this.samplingContext = null; this.samplingTrigger?.focus(); });
    this.element("hrc-sampling-form").addEventListener("submit", (event) => { event.preventDefault(); this.submitSampling(); });
    for (const id of ["sampling-until", "sampling-scope", "sampling-reset-regret"]) this.element(id).addEventListener("change", () => this.refreshSampling());
  }
  openSampling() {
    const dialog = this.element("hrc-sampling-dialog"), state = this.host.state;
    if (!dialog || dialog.open || state.busy || state.activeId) return;
    const job = state.view === "result" ? state.job : null;
    const config = this.host.currentConfig();
    const training = state.meta?.training;
    const supported = training?.sampling_dialog && this.host.isNative(config);
    const path = state.path.map((edge) => /^\d+$/.test(String(edge)) ? Number(edge) : NaN);
    this.samplingContext = {
      jobId: job?.id || null, config: structuredClone(config),
      completed: Number(job?.summary?.iterations_completed || 0),
      maxSamples: this.host.sampleLimit(),
      path, labels: this.decisionPathLabels(state.path), node: structuredClone(state.node),
      supported: !!supported, canResume: !!job?.can_resume,
      scopes: training?.sampling_scopes || [], modes: training?.stopping_modes || [],
      subtreeAllowed: !!job?.can_resume && !state.node?.terminal && state.node?.street === 0 && path.every(Number.isInteger),
    };
    const initialized = config?.sampling_stage === "initialization";
    this.element("sampling-algorithm").value = initialized ? "v4" : config?.solver_mode || "v4";
    this.element("sampling-scope").value = "entire_tree";
    this.element("sampling-scope").querySelector('[value="selected_subtree"]').disabled = !this.samplingContext.subtreeAllowed || !this.samplingContext.scopes.includes("selected_subtree");
    this.element("sampling-until").value = !initialized && config?.stopping_mode ? config.stopping_mode : "ci";
    this.element("sampling-target").value = !initialized && config?.target_ci ? config.target_ci : Number(training?.default_ci ?? 10).toFixed(1);
    this.element("sampling-samples").value = Math.min(50000000, Math.max(0, this.host.sampleLimit() - this.samplingContext.completed));
    this.element("sampling-time").value = !initialized && config?.stop_after_seconds ? config.stop_after_seconds : 60;
    this.element("sampling-threads").value = config?.threads ?? 4;
    this.element("sampling-cap").value = "";
    this.element("sampling-hard-seconds").value = config?.hard_seconds ?? "";
    this.element("sampling-reset-regret").checked = false;
    this.element("sampling-reset-average").checked = false;
    this.element("sampling-error").hidden = true;
    this.element("sampling-advanced").open = false;
    dialog.querySelectorAll('[aria-invalid="true"]').forEach((field) => field.removeAttribute("aria-invalid"));
    const unavailable = !supported ? "当前服务或计算模型不支持此采样窗口；请连接支持 Sampling 的服务。" : job && !job.can_resume ? "当前手牌只支持查看，无法继续计算。" : !job && state.draftDirty ? "请先更新决策树或完成 New Hand，Run 不会使用尚未应用的草稿。" : "";
    this.samplingContext.unavailable = unavailable;
    this.element("sampling-fields").disabled = !!unavailable;
    this.element("sampling-ok").disabled = !!unavailable;
    if (unavailable) { this.element("sampling-error").textContent = unavailable; this.element("sampling-error").hidden = false; }
    this.refreshSampling();
    this.samplingTrigger = document.activeElement;
    dialog.showModal(); this.element(unavailable ? "sampling-cancel" : "sampling-algorithm").focus();
  }
  refreshSampling() {
    const context = this.samplingContext; if (!context) return;
    const mode = this.element("sampling-until").value;
    this.element("sampling-ci-row").hidden = mode !== "ci";
    this.element("sampling-samples-row").hidden = mode !== "samples";
    this.element("sampling-time-row").hidden = mode !== "time";
    this.element("sampling-cap-row").hidden = mode === "samples";
    this.element("sampling-samples").min = Math.max(1, 100 - context.completed);
    this.element("sampling-samples").max = Math.max(0, context.maxSamples - context.completed);
    this.element("sampling-cap").min = context.completed + 1;
    this.element("sampling-cap").max = context.maxSamples;
    this.element("sampling-cap").placeholder = Number(context.maxSamples).toLocaleString();
    const selected = this.element("sampling-scope").value === "selected_subtree";
    const path = !context.path.length ? "Root" : context.labels.length === context.path.length ? context.labels.join(" → ") : `前序 ${context.path.length} 步已固定`;
    this.element("sampling-selection").hidden = !selected;
    this.element("sampling-selection").textContent = `决策路径：${path} · ${context.node?.actor_name || "—"} · 节点 ${context.node?.native_id ?? "—"}。包含该决策点全部行动；到达此节点的范围保持冻结。`;
    this.element("sampling-budget-note").textContent = mode === "samples" ? `Samples 为本次新增次数，当前已完成 ${context.completed.toLocaleString()} 次；提交时自动相加为累计目标。导入原档只计入导入后新增样本。` : mode === "time" ? "时间为本次运行目标；样本上限和最长时间仅作为安全停止条件。" : "CI 衡量近期策略变化，不是误差百分比或置信区间。样本数量仅作安全上限，不代表精度进度。";
    const resetRegret = this.element("sampling-reset-regret"), resetAverage = this.element("sampling-reset-average");
    resetRegret.disabled = !context.canResume;
    if (context.canResume && resetRegret.checked) resetAverage.checked = true;
    resetAverage.disabled = !context.canResume || resetRegret.checked;
  }
  decisionPathLabels(path) {
    const rows = [...this.branches.values()].flatMap((branch) => branch.rows || []);
    const labels = [];
    for (let i = 0; i < path.length; i += 1) {
      const row = rows.find((item) => item.path.length === i && item.path.every((edge, index) => String(edge) === String(path[index])) && String(item.action.id) === String(path[i]));
      if (!row) return [];
      labels.push(`${row.actor_name} ${this.host.actionLabel(row.action)}`);
    }
    return labels;
  }
  static samplingOptions(values, context) {
    const fail = (field, message) => { const error = new Error(message); error.field = field; throw error; };
    if (!context.supported || context.unavailable) fail("sampling-algorithm", context.unavailable || "当前服务不支持此采样操作。");
    if (!["v3", "v4"].includes(values.algorithm)) fail("sampling-algorithm", "请选择 HRC 3.0 或 HRC 4.0。");
    if (!context.modes.includes(values.mode)) fail("sampling-until", "当前服务不支持所选停止条件。");
    if (!context.scopes.includes(values.scope)) fail("sampling-scope", "当前服务不支持所选采样范围。");
    if (values.scope === "selected_subtree" && !context.subtreeAllowed) fail("sampling-scope", "Selected Subtree 需要已初始化手牌的翻前决策点。");
    const number = (field, raw, min, max, integer = false) => {
      const value = Number(raw);
      if (String(raw).trim() === "" || !Number.isFinite(value) || value < min || value > max || (integer && !Number.isInteger(value))) fail(field, `请输入 ${min.toLocaleString()}–${max.toLocaleString()} 范围内的${integer ? "整数" : "数值"}。`);
      return value;
    };
    const options = {
      solver_mode: values.algorithm, sampling_stage: "calculation", stopping_mode: values.mode,
      sampling_scope: values.scope, sampling_path: values.scope === "selected_subtree" ? [...context.path] : [],
      threads: number("sampling-threads", values.threads, 1, 32, true),
      reset_regret: context.canResume && !!values.resetRegret, reset_average: context.canResume && (!!values.resetRegret || !!values.resetAverage),
    };
    if (values.mode === "ci") { options.target_ci = number("sampling-target", values.target, .01, 1e12); options.track_ci = true; }
    if (values.mode === "time") options.stop_after_seconds = number("sampling-time", values.seconds, .1, 86400);
    if (values.mode === "samples") {
      if (context.completed >= context.maxSamples) fail("sampling-samples", "已达到本服务的样本上限，无法追加采样。");
      options.iterations = context.completed + number("sampling-samples", values.samples, Math.max(1, 100 - context.completed), context.maxSamples - context.completed, true);
    }
    else if (String(values.cap).trim()) options.iterations = number("sampling-cap", values.cap, Math.max(100, context.completed + 1), context.maxSamples, true);
    else if (context.completed >= context.maxSamples) fail("sampling-cap", "已达到本服务的样本上限，无法继续采样。");
    if (String(values.hardSeconds).trim()) options.hard_seconds = number("sampling-hard-seconds", values.hardSeconds, .1, 86400);
    else options.hard_seconds = null;
    return options;
  }
  static samplingProgress(job) {
    if (!job) return null;
    const config = job.config || {}, running = ["running", "cancelling"].includes(job.status);
    const mode = config.stopping_mode || (config.target_ci ? "ci" : config.stop_after_seconds ? "time" : "samples");
    const count = Number(running ? job.progress?.iteration ?? job.summary?.iterations_completed ?? 0 : job.summary?.iterations_completed ?? job.progress?.iteration ?? 0);
    const cap = Number(running ? job.progress?.total ?? config.iterations ?? job.summary?.iterations_requested ?? 0 : job.summary?.iterations_requested ?? job.progress?.total ?? config.iterations ?? 0);
    const ci = running ? job.progress?.ci || job.summary?.ci : job.summary?.ci || job.progress?.ci;
    const format = (value) => Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
    const prefix = job.summary?.hrcz_import?.history_unknown ? "导入后新增 " : "累计 ";
    const selection = job.summary?.sampling_selection || job.summary?.selection;
    const path = selection?.sampling_path ?? config.sampling_path ?? [];
    const scope = (selection?.sampling_scope ?? config.sampling_scope) === "selected_subtree" ? `Selected Subtree · 路径 ${path.length ? path.join(" / ") : "Root"}（所选决策点全部行动）` : "Full Tree";
    const ciProgress = Number.isFinite(ci?.value) && Number.isFinite(ci?.progress) && ci.progress > 0 ? Math.min(1, ci.progress) : null;
    const eta = Number.isFinite(ci?.eta_seconds) && ci.eta_seconds >= 0 ? `${format(ci.eta_seconds)} 秒（启发式）` : "—（无法估计）";
    if (mode === "ci") return {
      mode, indeterminate: running && ciProgress == null, hideProgress: !running, max: 1, value: ciProgress ?? 0,
      label: `CI ${Number.isFinite(ci?.value) ? format(ci.value) : "—"} / ${format(config.target_ci ?? 10)}`,
      detail: `${scope} · ${prefix}${format(count)} 次 · 安全上限 ${format(cap)} 次${running ? `${ciProgress == null ? "" : ` · CI 估计进度 ${format(ciProgress * 100)}%（启发式）`} · 预计剩余 ${eta}` : ""}`,
    };
    if (mode === "time") return {
      mode, indeterminate: false, hideProgress: false, max: Number(config.stop_after_seconds), value: Math.min(Number(job.elapsed_seconds || 0), Number(config.stop_after_seconds)),
      label: `${format(job.elapsed_seconds || 0)} / ${format(config.stop_after_seconds)} 秒`, detail: `${scope} · ${prefix}${format(count)} 次 · 安全上限 ${format(cap)} 次`,
    };
    return { mode, indeterminate: false, hideProgress: false, max: Math.max(1, cap), value: Math.min(count, Math.max(1, cap)), label: `${prefix}${format(count)} / ${format(cap)}`, detail: `${config.sampling_stage === "initialization" ? "手牌初始化 · " : ""}${scope}` };
  }
  async submitSampling() {
    if (this.samplingSubmitting || !this.samplingContext) return;
    const dialog = this.element("hrc-sampling-dialog"), form = this.element("hrc-sampling-form");
    const errorNode = this.element("sampling-error"); errorNode.hidden = true;
    form.querySelectorAll('[aria-invalid="true"]').forEach((field) => field.removeAttribute("aria-invalid"));
    const read = (id) => this.element(`sampling-${id}`).value;
    try {
      const options = window.PreflopDesktop.samplingOptions({
        algorithm: read("algorithm"), scope: read("scope"), mode: read("until"), target: read("target"),
        samples: read("samples"), seconds: read("time"), threads: read("threads"), cap: read("cap"), hardSeconds: read("hard-seconds"),
        resetRegret: this.element("sampling-reset-regret").checked, resetAverage: this.element("sampling-reset-average").checked,
      }, this.samplingContext);
      this.samplingSubmitting = true; form.setAttribute("aria-busy", "true");
      this.element("sampling-fields").disabled = true;
      dialog.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      const accepted = await this.host.submitSampling(this.samplingContext, options);
      if (!accepted) throw new Error(this.host.state.samplingError || "未能开始计算，请检查当前手牌后重试。");
      dialog.close();
    } catch (error) {
      errorNode.textContent = error.message; errorNode.hidden = false;
      if (error.field) {
        const field = this.element(error.field); field.setAttribute("aria-invalid", "true");
        if (field.closest("details")) field.closest("details").open = true;
        field.focus();
      }
    } finally {
      this.samplingSubmitting = false; form.setAttribute("aria-busy", "false");
      this.element("sampling-fields").disabled = !!this.samplingContext?.unavailable;
      dialog.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      this.element("sampling-ok").disabled = !!this.samplingContext?.unavailable;
      this.refreshSampling();
    }
  }
  openWizard() {
    const dialog = this.element("hrc-new-dialog"), form = this.element("scenario-form");
    if (!dialog || dialog.open) return;
    const state = this.host.state;
    this.wizardBefore = {
      baseConfig: structuredClone(state.formBaseConfig),
      config: { ...JSON.parse(JSON.stringify(state.formBaseConfig)), players: this.host.collectPlayers() },
      applied: JSON.parse(JSON.stringify(state.appliedConfig)), view: state.view,
      dirty: state.draftDirty, edited: state.formEdited, path: [...state.path], labels: [...state.labels],
      selectedHand: state.selectedHand,
      draftState: Object.fromEntries(["treeSettingsDraft", "treeEditorMode", "treePolicyDrafts", "policyTopologyDirty", "policySource", "policyKey", "policyWorking", "policyDrafts", "policyMode"].map((key) => [key, structuredClone(state[key])])),
      action: this.selectedAction, source: this.source, branches: new Map(this.branches), expanded: new Set(this.expanded),
      inputs: [...form.querySelectorAll("input[id],select[id],textarea[id]")].filter((field) => field.type !== "file").map((field) => ({ id: field.id, value: field.value, checked: field.type === "checkbox" ? field.checked : undefined })),
    };
    this.wizardCommitted = false;
    if (state.meta.custom_native) this.host.applyPreset("custom-native");
    this.formPlaceholder = document.createComment("scenario form location"); form.before(this.formPlaceholder);
    this.element("hrc-new-content").append(form); form.classList.add("hrc-wizard-form");
    if (!this.element("hrc-initialization-note")) {
      const note = this.make("p", "form-note", "Finish 将创建手牌并自动进行全树初始化；完成后点击绿色 Run 开始正式 CI 计算。");
      note.id = "hrc-initialization-note"; this.propertyGroups.Engine?.append(note);
    }
    this.element("hrc-initialization-note").textContent = `Finish 将创建手牌并自动初始化 ${Number(state.meta.training?.initialization_samples || 10000000).toLocaleString()} 个全树样本。初始化不是正式 CI 目标；完成后点击绿色 Run。`;
    this.element("hrc-initialization-note").hidden = false;
    const actions = form.querySelector(".scenario-actions"); if (actions) actions.hidden = true;
    this.showWizardPage(0); dialog.showModal();
    this.element("player-stack-0")?.focus();
  }
  showWizardPage(index) {
    this.wizardPage = Math.max(0, Math.min(2, index));
    const titles = ["Hand Setup", "Tree Configuration", "Calculation Settings"];
    this.element("hrc-new-title").textContent = titles[this.wizardPage];
    this.element("hrc-new-dialog").dataset.page = String(this.wizardPage);
    for (const [name, group] of Object.entries(this.propertyGroups || {})) {
      group.hidden = group.dataset.hrcEmpty === "true" || (this.wizardPage === 0 ? !["Hand Data", "Equity Model"].includes(name) : name !== (this.wizardPage === 1 ? "Treeconfig" : "Engine"));
      group.open = !group.hidden;
    }
    const dialog = this.element("hrc-new-dialog");
    dialog.querySelector('[data-wizard-action="back"]').disabled = this.wizardPage === 0;
    dialog.querySelector('[data-wizard-action="next"]').disabled = this.wizardPage === 2;
    dialog.querySelector('[data-wizard-action="finish"]').disabled = this.wizardPage !== 2;
    this.element("hrc-new-content").scrollTop = 0;
  }
  pageForField(id) {
    const field = this.handSetup?.errorTarget(id) || this.element(id);
    const group = field?.closest(".hrc-property-group");
    return group === this.propertyGroups.Treeconfig ? 1 : group === this.propertyGroups.Engine ? 2 : 0;
  }
  setupHome() {
    if (this.element("hrc-home-pane")) return;
    const home = this.make("section", "hrc-tab-pane hrc-home-pane");
    home.id = "hrc-home-pane"; home.hidden = true;
    home.setAttribute("aria-label", "Home");
    home.append(this.make("h3", "", "Open Calculation"));
    for (const [label, command, description] of [
      ["New Monte Carlo Hand", "new", "Create a new calculation."],
      ["Load Hand", "open", "Open an .hrcz or .plabz calculation."],
      ["View Hand", "archive", "Browse saved calculation results."],
    ]) {
      const button = this.make("button", "hrc-home-link", label); button.type = "button"; button.dataset.hrcCommand = command;
      home.append(button, this.make("p", "", description));
    }
    this.element("hrc-strategy-pane")?.parentElement.append(home);
  }
  setupProperties() {
    const fieldset = this.element("scenario-fields"); if (!fieldset) return;
    const sections = [...fieldset.querySelectorAll(":scope > .form-section")];
    const groups = {};
    for (const title of ["Hand Data", "Equity Model", "Treeconfig", "Engine"]) {
      const details = document.createElement("details"); details.className = "hrc-property-group";
      const summary = document.createElement("summary"); summary.textContent = title; details.append(summary);
      groups[title] = details;
    }
    const heading = this.make("div", "hrc-property-heading");
    heading.append(this.make("span", "", "Setting"), this.make("span", "", "Value"));
    fieldset.prepend(heading, ...Object.values(groups));
    const preset = this.element("preset")?.closest(".field"); if (preset) groups["Hand Data"].append(preset);
    for (const section of sections) {
      const title = section.querySelector("h2")?.textContent || "";
      if (["座位与筹码", "盲注结构"].includes(title)) groups["Hand Data"].append(section);
      else if (["决策树", "原生四街树"].includes(title)) groups.Treeconfig.append(section);
      else if (["现金局抽水", "未来局模拟 FGS"].includes(title)) groups["Equity Model"].append(section);
      else {
        const utility = this.element("utility")?.closest(".field");
        if (utility && section.contains(utility)) {
          groups["Equity Model"].append(utility, this.element("payout-field"), this.element("tournament-fields"));
          const grid = this.element("iterations")?.closest(".field-grid");
          if (grid) groups.Engine.append(grid);
          if (this.element("training-controls")) groups.Engine.append(this.element("training-controls"));
          section.remove();
        } else groups.Engine.append(section);
      }
    }
    const note = this.element("research-note"); if (note) groups.Engine.append(note);
    const actions = fieldset.querySelector(".scenario-actions"); if (actions) groups.Engine.append(actions);
    this.propertyGroups = groups;
  }
  make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  key() {
    const state = this.host.state;
    return state.view === "result" && state.job
      ? `job:${state.job.id}:${state.job.status}`
      : `draft:${JSON.stringify(this.host.currentConfig())}`;
  }
  render() {
    if (!this.enabled) return;
    this.renderDocuments();
    const nextKey = this.key();
    if (nextKey !== this.contextKey) {
      this.contextKey = nextKey;
      this.generation += 1;
      this.branches.clear(); this.expanded.clear(); this.loading.clear();
      this.selectedAction = null;
      this.loadBranch([]);
    }
    this.renderActions();
    this.paintTreeSelection();
    this.updateCommands();
    const outline = this.element("hrc-outline-tree");
    if (outline) {
      const config = this.host.currentConfig();
      outline.textContent = config ? `Hand Data\n${config.players.map((player) => `${player.name}: ${player.stack}`).join(" / ")}\n\nEquity Model\n${config.utility}${config.bounty?.mode && config.bounty.mode !== "none" ? ` / ${config.bounty.mode.toUpperCase()}` : ""}\n\nEngine\n${config.solver_mode || "v4"} · ${Number(config.iterations).toLocaleString()} samples` : "No calculation loaded.";
    }
  }
  updateCommands() {
    if (!this.enabled) return;
    const state = this.host.state;
    const busy = state.busy || state.loading || state.archiveBusy;
    const running = ["running", "cancelling"].includes(state.job?.status);
    const imported = this.host.currentConfig()?.engine === "hrc_imported";
    const persistence = state.meta?.persistence;
    const canSave = (persistence?.hrcz_export && state.job?.can_export_hrcz) || (persistence?.archive_export && state.job?.can_export_archive);
    if (running && !this.samplingSubmitting && this.element("hrc-sampling-dialog")?.open) this.element("hrc-sampling-dialog").close();
    document.querySelectorAll('[data-hrc-command]').forEach((button) => {
      const command = button.dataset.hrcCommand;
      button.disabled = command === "run" ? !state.meta || busy || running || !!state.activeId || (imported && !(state.view === "result" && state.job?.can_resume))
        : command === "stop" ? !running
        : command === "save" ? busy || !canSave
        : command === "open" ? busy || !!state.activeId || !(persistence?.hrcz_import || persistence?.archive_import)
        : !state.meta || busy;
    });
  }
  async loadBranch(path) {
    const key = JSON.stringify(path);
    if (this.branches.has(key) || this.loading.has(key)) return;
    this.loading.add(key);
    const generation = this.generation;
    this.renderTree();
    try {
      const state = this.host.state;
      const payload = state.view === "result" && state.job
        ? { job_id: state.job.id, path }
        : { config: this.host.currentConfig(), path };
      let data;
      try {
        data = await this.host.api("/api/strategy-table", { method: "POST", body: JSON.stringify(payload) });
      } catch (error) {
        // Older running local servers still support the same node API. This
        // bounded fallback keeps the new shell usable without restarting them.
        if (error.status && error.status !== 404) throw error;
        data = await this.legacyBranch(path, state.view, state.job?.id, payload.config);
      }
      if (generation !== this.generation) return;
      this.branches.set(key, data);
      this.renderTree();
    } catch (error) {
      if (generation !== this.generation) return;
      this.branches.set(key, { rows: [], error: error.message });
      this.renderTree();
    } finally {
      if (generation === this.generation) { this.loading.delete(key); this.renderTree(); }
    }
  }
  async legacyBranch(path, view, jobId, config) {
    const read = (cursor) => view === "result" && jobId
      ? this.host.api(`/api/jobs/${encodeURIComponent(jobId)}/node?path=${encodeURIComponent(JSON.stringify(cursor))}`)
      : this.host.api("/api/tree", { method: "POST", body: JSON.stringify({ config, path: cursor }) });
    const rows = [];
    let cursor = [...path], street = null;
    for (let seat = 0; seat < 10; seat += 1) {
      const node = await read(cursor);
      if (node.terminal || (street !== null && (node.street || 0) !== street)) break;
      street = node.street || 0;
      for (const [index, action] of node.actions.entries()) {
        if (action.kind === "fold") continue;
        let sum = 0, mass = 0;
        const labels = [];
        for (const [handLabel, hand] of Object.entries(node.strategy?.hands || {})) {
          if (!this.host.hasHandPolicy(hand) || !Number.isFinite(hand.frequencies?.[index])) continue;
          const weight = street > 0 ? 1 : handLabel.length === 2 ? 6 : handLabel.endsWith("s") ? 4 : 12;
          mass += weight; sum += weight * hand.frequencies[index];
          if (hand.frequencies[index] >= .005) labels.push(handLabel);
        }
        rows.push({ key: [...cursor, action.id].join("/"), path: [...cursor], child_path: [...cursor, action.id],
          action, actor_name: node.actor_name, actor: node.actor, street, expandable: true,
          frequency: mass ? sum / mass : null, covered_combinations: mass, range_text: labels.join(", ") });
      }
      const fold = node.actions.find((action) => action.kind === "fold");
      if (!fold || node.special) break;
      cursor = [...cursor, fold.id];
    }
    return { rows };
  }
  renderTree() {
    const body = this.element("hrc-strategy-body");
    if (!body) return;
    const fragment = document.createDocumentFragment();
    const append = (path, depth) => {
      const branch = this.branches.get(JSON.stringify(path));
      if (!branch) {
        const row = this.make("tr", "hrc-tree-message"), cell = this.make("td", "", "Loading…");
        cell.colSpan = 4; row.append(cell); fragment.append(row); return;
      }
      if (branch.error || !branch.rows.length) {
        const row = this.make("tr", "hrc-tree-message"), cell = this.make("td", "", branch.error || "No further actions.");
        cell.colSpan = 4; row.append(cell); fragment.append(row); return;
      }
      for (const item of branch.rows) {
        const row = this.make("tr", "hrc-strategy-row");
        row.dataset.path = JSON.stringify(item.path);
        row.dataset.action = item.action.id;
        row.dataset.key = item.key;
        const action = this.make("td", "hrc-action-column");
        action.style.paddingLeft = `${depth * 15 + 3}px`;
        const toggle = this.make("button", "hrc-tree-expander", item.expandable ? this.expanded.has(item.key) ? "▾" : "▸" : "");
        toggle.type = "button"; toggle.disabled = !item.expandable;
        toggle.setAttribute("aria-label", `${this.expanded.has(item.key) ? "Collapse" : "Expand"} ${item.actor_name} ${this.host.actionLabel(item.action)}`);
        toggle.setAttribute("aria-expanded", String(this.expanded.has(item.key)));
        toggle.addEventListener("click", (event) => {
          event.stopPropagation();
          if (this.expanded.has(item.key)) this.expanded.delete(item.key);
          else { this.expanded.add(item.key); this.loadBranch(item.child_path); }
          this.renderTree();
        });
        const select = this.make("button", "hrc-tree-select"); select.type = "button";
        const symbol = { call: "C", check: "X", fold: "F", raise: "R", allin: "R", all_in: "R", shove: "R" }[item.action.kind] || "R";
        select.append(this.make("span", "hrc-node-dot", "●"), document.createTextNode(` ${symbol}`));
        select.setAttribute("aria-label", `${item.actor_name} ${this.host.actionLabel(item.action)}`);
        const activate = async () => {
          this.home = false;
          this.selectedAction = item.action.id;
          await this.host.loadNode(item.path, item.path.map((_, i) => `Action ${i + 1}`));
          this.selectedAction = item.action.id;
          this.host.renderRange(); this.paintTreeSelection();
        };
        select.addEventListener("click", activate);
        select.addEventListener("keydown", (event) => {
          if (["ArrowUp", "ArrowDown"].includes(event.key)) {
            const buttons = [...body.querySelectorAll(".hrc-tree-select")];
            const next = buttons[Math.max(0, Math.min(buttons.length - 1, buttons.indexOf(select) + (event.key === "ArrowUp" ? -1 : 1)))];
            event.preventDefault(); next?.focus(); next?.click();
          } else if (event.key === "ArrowRight" && item.expandable && !this.expanded.has(item.key)) { event.preventDefault(); toggle.click(); }
          else if (event.key === "ArrowLeft" && this.expanded.has(item.key)) { event.preventDefault(); toggle.click(); }
        });
        row.addEventListener("dblclick", () => { if (item.expandable) toggle.click(); });
        action.append(toggle, select);
        const amount = this.make("td", "hrc-number", item.action.kind === "check" ? "—" : Number(item.action.amount || 0).toFixed(2));
        const player = this.make("td", "", item.actor_name);
        const range = this.make("td", "hrc-range-column", item.frequency === null ? "—" : `${(100 * item.frequency).toFixed(1)}%, ${item.range_text || ""}`);
        range.title = item.frequency === null ? "No trained policy at this node." : `${item.range_text}\nObserved combinations: ${item.covered_combinations}/1326`;
        for (const cell of [amount, player, range]) cell.addEventListener("click", activate);
        row.append(action, amount, player, range); fragment.append(row);
        if (this.expanded.has(item.key)) append(item.child_path, depth + 1);
      }
    };
    append([], 0); body.replaceChildren(fragment); this.paintTreeSelection();
  }
  paintTreeSelection() {
    const state = this.host.state;
    const path = JSON.stringify(state.path);
    this.element("hrc-strategy-body")?.querySelectorAll("tr[data-action]").forEach((row) => {
      const selected = row.dataset.path === path && row.dataset.action === this.selectedAction;
      row.classList.toggle("is-selected", selected);
      row.setAttribute("aria-selected", String(selected));
    });
  }
  renderActions() {
    const state = this.host.state;
    const actions = state.node?.actions || [];
    if (!actions.some((action) => action.id === this.selectedAction)) {
      this.selectedAction = (actions.find((action) => ["raise", "allin", "all_in", "shove"].includes(action.kind)) || actions.find((action) => action.kind !== "fold") || actions[0])?.id;
    }
    const selector = this.element("hrc-range-action");
    if (selector) {
      selector.replaceChildren(...actions.map((action) => {
        const option = this.make("option", "", this.host.actionLabel(action)); option.value = action.id; return option;
      })); selector.value = this.selectedAction || ""; selector.disabled = !actions.length;
    }
  }
  selectedIndex() {
    const actions = this.host.state.node?.actions || [];
    return Math.max(0, actions.findIndex((action) => action.id === this.selectedAction));
  }
  evScale() {
    const config = this.host.currentConfig();
    if (!config || config.utility === "chips") return 1;
    const prize = (config.payouts || []).reduce((sum, value) => sum + Number(value), 0);
    const heads = config.bounty?.mode && config.bounty.mode !== "none"
      ? [...(config.bounty.amounts || []), ...(config.bounty.other_amounts || [])].reduce((sum, value) => sum + Number(value), 0) : 0;
    return prize + heads > 0 ? 100 / (prize + heads) : 1;
  }
  decorateRange() {
    if (!this.enabled) return;
    this.renderActions();
    const state = this.host.state, node = state.node;
    const actions = node?.actions || [], index = this.selectedIndex(), action = actions[index];
    const useReference = this.source === "reference";
    let covered = 0, weighted = 0, hasReference = false;
    const scale = this.evScale();
    this.element("hrc-range-pane")?.setAttribute("data-source", "ours");
    this.element("hrc-range-pane")?.setAttribute("data-mode", this.mode);
    const target = this.element("range-matrix");
    for (const cell of target?.children || []) {
      const label = cell.dataset.hand;
      const original = node?.strategy?.hands?.[label];
      if (original?.reference?.frequencies) hasReference = true;
      const hand = useReference ? original?.reference : original;
      const valid = Array.isArray(hand?.frequencies) && hand.frequencies.length === actions.length
        && hand.frequencies.every((frequency) => Number.isFinite(frequency) && frequency >= 0)
        && (useReference || this.host.hasHandPolicy(original));
      const frequency = valid ? hand.frequencies[index] : null;
      const values = hand?.relative_ev || hand?.relative_ev_bb;
      const rawValue = values?.[index], value = valid && Number.isFinite(rawValue) ? rawValue * scale : null;
      cell.classList.toggle("hrc-no-policy", !valid);
      cell.classList.toggle("hrc-positive-frequency", valid && frequency >= .005);
      cell.style.setProperty("--hrc-frequency", `${valid ? Math.max(0, Math.min(100, frequency * 100)) : 0}%`);
      cell.style.setProperty("--hrc-ev-background", value === null ? "#ffffff" : value >= 0 ? "#edffed" : "#ffe0e0");
      cell.style.setProperty("--cell-background", this.mode === "ev" ? "var(--hrc-ev-background)" : "linear-gradient(to right,#80ff80 var(--hrc-frequency),var(--hrc-ev-background) var(--hrc-frequency))");
      const text = this.mode === "frequency" ? valid ? `${(frequency * 100).toFixed(1)}%` : "—" : value === null ? "—" : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;
      let detail = cell.querySelector(".hrc-cell-value");
      if (!detail) { detail = this.make("span", "hrc-cell-value"); cell.append(detail); }
      detail.textContent = text;
      const unit = this.host.currentConfig()?.utility === "chips" ? "BB" : "% of prize pool";
      cell.title = `${label} · ${action ? this.host.actionLabel(action) : "—"}\n${valid ? `${(frequency * 100).toFixed(2)}%` : "No saved or trained policy"}${value === null ? "" : `\nEV ${value.toFixed(4)} ${unit}`}${!useReference && original?.has_saved_policy && original.visits == null ? "\nSaved policy; hand sampling history unknown" : ""}`;
      cell.setAttribute("aria-label", cell.title.replaceAll("\n", ", "));
      if (valid) {
        const weight = node?.street > 0 ? 1 : label.length === 2 ? 6 : label.endsWith("s") ? 4 : 12;
        covered += weight; weighted += frequency * weight;
      }
    }
    const source = this.element("hrc-range-source");
    if (source) {
      const ours = source.querySelector('[value="ours"]');
      if (ours) ours.textContent = state.view === "result" && state.job?.has_source_strategy ? "Loaded .hrcz / continued" : "Our calculation";
      const reference = source.querySelector('[value="reference"]'); if (reference) reference.disabled = !hasReference;
      if (!hasReference && useReference) { this.source = "ours"; source.value = "ours"; this.decorateRange(); return; }
    }
    const aggregate = covered ? weighted / covered : null;
    const amount = action ? action.kind === "check" ? "checks" : action.kind === "fold" ? "folds" : action.kind === "call" ? `calls ${Number(action.cost || 0).toFixed(2)}bb` : `raises ${Number(action.amount || 0).toFixed(2)}bb` : "";
    const caption = this.element("hrc-range-caption");
    if (caption) caption.textContent = node && action ? `${node.actor_name} ${amount}: ${aggregate === null ? "—" : `${(aggregate * 100).toFixed(1)}%`}${useReference ? " · HRC reference" : ""}` : "Select an action in the Strategy Table.";
    const tableCaption = this.element("hrc-table-caption");
    if (tableCaption) tableCaption.textContent = node ? `*** ${["PREFLOP", "FLOP", "TURN", "RIVER"][node.street || 0]}\n***\n${node.actor_name || "Showdown"}${action ? ` ${amount}` : ""}` : "";
    const bar = this.element("hrc-range-total");
    if (bar) {
      bar.replaceChildren();
      if (aggregate !== null) {
        const remainder = this.make("span", "hrc-total-remainder", (100 * (1 - aggregate)).toFixed(1));
        const selected = this.make("span", "hrc-total-selected", (100 * aggregate).toFixed(1));
        remainder.style.flex = String(1 - aggregate); selected.style.flex = String(aggregate);
        bar.append(remainder, selected);
      }
    }
  }
  renderDocuments() {
    const tabs = this.element("hrc-document-tabs"); if (!tabs) return;
    const state = this.host.state;
    const jobs = state.jobs.slice(0, 10);
    if (state.job && !jobs.some((job) => job.id === state.job.id)) jobs.unshift(state.job);
    const signature = `${state.job?.id || ""}/${state.view}/${jobs.map((job) => job.id).join()}/${this.home}`;
    if (signature === this.documentSignature) return;
    this.documentSignature = signature;
    tabs.replaceChildren(...jobs.map((job) => {
      const name = job.config.benchmark || `${job.config.players.length}max-${job.config.utility}${job.config.bounty?.mode !== "none" ? `-${job.config.bounty?.mode || ""}` : ""}`;
      const button = this.make("button", "hrc-document-tab", name); button.type = "button";
      button.title = `${name} · ${job.id}`; button.setAttribute("aria-pressed", String(!this.home && state.view === "result" && state.job?.id === job.id));
      button.addEventListener("click", async () => {
        this.home = false; this.showTab("left", "hrc-strategy-pane");
        if (state.view === "draft") this.savedDraft = { config: this.host.readConfig(), applied: structuredClone(state.appliedConfig) };
        state.job = job; state.view = "result";
        this.host.setConfig(job.config); state.appliedConfig = structuredClone(job.config); state.draftDirty = false; state.formEdited = false;
        this.host.resetNode(); this.host.renderContext(); this.host.renderJob();
        await this.host.loadNode([], []);
      }); return button;
    }));
    const draft = this.make("button", "hrc-document-tab", "Hand"); draft.type = "button";
    draft.setAttribute("aria-pressed", String(!this.home && state.view === "draft"));
    draft.addEventListener("click", () => {
      this.home = false;
      if (this.savedDraft?.config) {
        this.host.setConfig(this.savedDraft.config); state.appliedConfig = this.savedDraft.applied;
        for (const input of this.savedDraft.inputs || []) {
          const field = this.element(input.id); if (!field) continue;
          field.value = input.value; if (input.checked !== undefined) field.checked = input.checked;
        }
        for (const [key, value] of Object.entries(this.savedDraft.draftState || {})) state[key] = value;
        state.draftDirty = this.savedDraft.dirty ?? state.draftDirty;
        state.formEdited = this.savedDraft.edited ?? state.formEdited;
      }
      this.host.switchView("draft"); this.showTab("left", "hrc-strategy-pane");
    }); tabs.append(draft);
    const home = this.make("button", "hrc-document-tab", "⌂ Home"); home.type = "button";
    home.setAttribute("aria-pressed", String(this.home)); home.addEventListener("click", () => this.command("home")); tabs.append(home);
    tabs.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  showTab(group, target) {
    const buttons = document.querySelectorAll(`[data-hrc-tab="${group}"]`);
    buttons.forEach((button) => {
      const selected = button.dataset.hrcTarget === target;
      button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1;
      const pane = this.element(button.dataset.hrcTarget); if (pane) pane.hidden = !selected;
    });
    if (group === "left") {
      const home = this.element("hrc-home-pane"); if (home) home.hidden = target !== "hrc-home-pane";
    }
  }
  closeMenus() {
    document.querySelectorAll("[data-hrc-menu-panel]").forEach((panel) => { panel.hidden = true; });
    document.querySelectorAll("[data-hrc-menu-toggle]").forEach((button) => button.setAttribute("aria-expanded", "false"));
  }
  click(event) {
    const menu = event.target.closest("[data-hrc-menu-toggle]");
    if (menu) {
      const open = menu.getAttribute("aria-expanded") !== "true"; this.closeMenus();
      this.menuTrigger = menu;
      const panel = this.element(menu.getAttribute("aria-controls")); if (panel) panel.hidden = !open;
      menu.setAttribute("aria-expanded", String(open));
      if (open) panel?.querySelector("button:not(:disabled)")?.focus(); return;
    }
    const command = event.target.closest("[data-hrc-command]");
    if (command) { this.closeMenus(); this.command(command.dataset.hrcCommand); return; }
    const tab = event.target.closest("[data-hrc-tab]");
    if (tab) { this.showTab(tab.dataset.hrcTab, tab.dataset.hrcTarget); return; }
    const mode = event.target.closest("[data-hrc-range-mode]");
    if (mode) {
      this.mode = mode.dataset.hrcRangeMode;
      document.querySelectorAll("[data-hrc-range-mode]").forEach((button) => button.setAttribute("aria-pressed", String(button === mode)));
      this.host.renderRange(); return;
    }
    if (!event.target.closest("[data-hrc-menu-panel]")) this.closeMenus();
  }
  command(name) {
    // Keyboard shortcuts share capability guards with the visible commands.
    const state = this.host.state;
    if (["new", "open", "save", "run"].includes(name) && (state.busy || state.loading || state.archiveBusy)) return;
    if (name === "run" && (state.activeId || (this.host.currentConfig()?.engine === "hrc_imported" && !(state.view === "result" && state.job?.can_resume)))) return;
    if (name === "open" && state.activeId) return;
    if (["new", "settings"].includes(name)) {
      this.home = false;
      if (name === "new") { this.openWizard(); return; }
      this.showTab("left", "hrc-settings-pane");
      if (name === "new" && this.propertyGroups) { this.propertyGroups["Hand Data"].open = true; this.element("preset")?.focus(); }
    } else if (name === "run") {
      this.showTab("bottom", "hrc-progress-pane");
      this.openSampling();
    }
    else if (name === "stop") this.host.cancelJob();
    else if (name === "open") this.element("archive-file")?.click();
    else if (name === "save") {
      if (state.meta?.persistence?.hrcz_export && state.job?.can_export_hrcz) this.host.exportHrcz();
      else this.host.exportArchive();
    }
    else if (name === "analysis") this.showTab("bottom", "hrc-analysis-pane");
    else if (name === "constraints") this.showTab("bottom", "hrc-constraints-pane");
    else if (name === "archive") this.showTab("bottom", "hrc-archive-pane");
    else if (name === "about") { this.element("model-details").open = true; this.element("hrc-about-dialog")?.showModal(); }
    else if (name === "home") {
      this.home = true; this.showTab("left", "hrc-home-pane"); this.renderDocuments();
    }
  }
  keydown(event) {
    if (event.isComposing) return;
    if (event.altKey && event.key.toLowerCase() === "r" && !document.querySelector("dialog[open]")) { event.preventDefault(); this.command("run"); return; }
    if (event.key === "Escape" && document.querySelector('[data-hrc-menu-toggle][aria-expanded="true"]')) {
      this.closeMenus(); this.menuTrigger?.focus(); event.preventDefault(); return;
    }
    const target = event.target;
    if (target.matches('[role="menuitem"]') && ["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      const items = [...target.closest('[role="menu"]').querySelectorAll('button:not(:disabled)')];
      const index = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (items.indexOf(target) + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
      event.preventDefault(); items[index]?.focus(); return;
    }
    if (target.matches("input,textarea,select,[contenteditable]")) return;
    if ((event.ctrlKey || event.metaKey) && ["n", "s", "o", "l"].includes(event.key.toLowerCase())) {
      event.preventDefault(); this.command({ n: "new", s: "save", o: "open", l: "open" }[event.key.toLowerCase()]); return;
    }
    const tab = target.closest("[data-hrc-tab]");
    if (tab && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
      const siblings = [...document.querySelectorAll(`[data-hrc-tab="${tab.dataset.hrcTab}"]`)];
      const next = siblings[(siblings.indexOf(tab) + (event.key === "ArrowLeft" ? -1 : 1) + siblings.length) % siblings.length];
      event.preventDefault(); next.click(); next.focus();
    }
  }
  setupSplitters() {
    const root = this.element("hrc-workbench") || document.querySelector(".workspace");
    const definitions = [
      ["hrc-vertical-splitter", "--hrc-left-width", "x", 260, 650, 390],
      ["hrc-left-splitter", "--hrc-left-top", "y", 30, 85, 65],
      ["hrc-right-splitter", "--hrc-right-top", "y", 45, 88, 80],
    ];
    for (const [id, property, axis, min, max, initial] of definitions) {
      const divider = this.element(id); if (!divider || !root) continue;
      let value = initial;
      const update = (next) => {
        value = Math.min(max, Math.max(min, next)); root.style.setProperty(property, `${value}${axis === "x" ? "px" : "%"}`);
        divider.setAttribute("aria-valuenow", String(Math.round(value)));
      };
      divider.setAttribute("aria-valuemin", String(min)); divider.setAttribute("aria-valuemax", String(max)); update(value);
      divider.addEventListener("pointerdown", (event) => {
        event.preventDefault(); divider.setPointerCapture(event.pointerId);
        const start = axis === "x" ? event.clientX : event.clientY, before = value;
        const rect = divider.parentElement.getBoundingClientRect();
        const move = (next) => update(before + ((axis === "x" ? next.clientX : next.clientY) - start) * (axis === "x" ? 1 : 100 / rect.height));
        const end = () => { divider.removeEventListener("pointermove", move); divider.removeEventListener("pointerup", end); divider.removeEventListener("pointercancel", end); };
        divider.addEventListener("pointermove", move); divider.addEventListener("pointerup", end); divider.addEventListener("pointercancel", end);
      });
      divider.addEventListener("keydown", (event) => {
        if (event.key === (axis === "x" ? "ArrowLeft" : "ArrowUp")) { event.preventDefault(); update(value - (axis === "x" ? 15 : 3)); }
        if (event.key === (axis === "x" ? "ArrowRight" : "ArrowDown")) { event.preventDefault(); update(value + (axis === "x" ? 15 : 3)); }
      });
    }
  }
};
