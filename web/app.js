"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const number = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
  const integer = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
  const POLL_MS = 900;
  const state = {
    meta: null, appliedConfig: null, formBaseConfig: null, job: null, jobs: [], activeId: null,
    view: "draft", node: null, path: [], labels: [], selectedHand: "AA",
    draftDirty: false, formEdited: false, busy: false, loading: false,
    requestId: 0, nodeController: null, pollTimer: null, pollFailures: 0, pollInFlight: false,
    lastNodeRequest: null, announcementTimer: null, initialized: false,
    resumeJobId: null,
    treeSettingsDraft: null, treeEditorMode: "form", treePolicyDrafts: { preflop: {}, postflop: {} }, preflopPresetRequest: 0, archiveBusy: false,
    policyKey: null, policyWorking: null, policySource: null, policyTopologyDirty: false, policyDrafts: new Map(),
    analysisCache: new Map(), analysisLoading: null, analysisRenderedId: null,
  };
  let desktop = null;
  const actionTokens = { fold: "fold", check: "call", call: "call", raise: "raise", bet: "raise", allin: "shove", all_in: "shove", "all-in": "shove", shove: "shove" };
  const fieldIds = ["small-blind", "big-blind", "ante", "open-sizes", "reraise-sizes", "max-raises", "utility", "payouts", "iterations", "seed"];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function format(value) { return Number.isFinite(Number(value)) ? number.format(Number(value)) : "—"; }
  function formatInt(value) { return Number.isFinite(Number(value)) ? integer.format(Number(value)) : "—"; }
  function configSummary(config) {
    if (!config) return "等待场景";
    const model = { chips: "Chip EV", icm: "ICM", mtt_icm: "MTT ICM" }[config.utility] || config.utility;
    const bounty = config.bounty?.mode && config.bounty.mode !== "none" ? ` + ${config.bounty.mode.toUpperCase()}` : "";
    return `${config.players.length} 人桌 · ${model}${bounty} · ${config.players.map((player) => format(usesChipUnits(config) ? player.stack / config.big_blind : player.stack)).join(" / ")} BB`;
  }
  function isRunning(job) { return job && ["running", "cancelling"].includes(job.status); }
  function hasResult(job) { return !!job && (["completed", "cancelled"].includes(job.status) || !!job.summary || job.has_source_strategy === true); }
  function currentConfig() { return state.view === "result" && state.job ? state.job.config : state.appliedConfig; }
  function isResearch(config) { return config?.engine === state.meta?.research?.engine && !!config?.engine; }
  function isTournament(config) { return config?.engine === "hrc_tournament"; }
  function isCustomNative(config) { return config?.engine === "hrc_custom"; }
  function isImported(config) { return config?.engine === "hrc_imported"; }
  function usesChipUnits(config) { return isCustomNative(config) || isImported(config); }
  function isFixed(config) { return isResearch(config) || isTournament(config) || isImported(config); }
  function isNative(config) { return isFixed(config) || isCustomNative(config); }
  function sampleLimit() { return Number(state.meta?.training?.max_samples || state.meta?.custom_native?.max_samples || state.meta?.research?.max_samples || 60000000); }
  function hasTournamentInputs(config) { return isTournament(config) || (usesChipUnits(config) && $("utility").value !== "chips"); }
  function utilityUnit(config = currentConfig()) { return config?.utility === "chips" ? "BB" : "奖金单位"; }
  function presetValue(config) { return isImported(config) ? "imported-source" : isCustomNative(config) ? "custom-native" : isTournament(config) ? `tournament-${config.benchmark}` : isResearch(config) ? `research-${config.benchmark}` : "default"; }
  function hasHandPolicy(hand) {
    return !!hand && (Number(hand.visits) > 0 || hand.has_saved_policy === true)
      && Array.isArray(hand.frequencies) && hand.frequencies.length > 0
      && hand.frequencies.every((frequency) => Number.isFinite(frequency) && frequency >= 0);
  }
  function sourceHistory(job = state.job) { return job?.summary?.hrcz_import; }
  function rangeLabels() {
    return state.node?.street > 0 ? Array.from({ length: state.node.buckets || 0 }, (_, i) => `桶 ${i}`) : state.meta?.hand_labels || [];
  }
  function colorFor(action, index = 0) {
    const key = actionTokens[String(action.kind || "").toLowerCase()] || "raise";
    return `var(--color-${key})`;
  }
  function rawColorFor(action) {
    const key = actionTokens[String(action.kind || "").toLowerCase()] || "raise";
    return getComputedStyle(document.documentElement).getPropertyValue(`--color-${key}`).trim();
  }
  function actionLabel(action) {
    const kind = String(action.kind || "").toLowerCase();
    const amount = Number(action.amount);
    const suffix = Number.isFinite(amount) && amount > 0 ? ` ${format(amount)}` : "";
    if (kind === "fold") return "弃牌";
    if (kind === "check") return "过牌";
    if (kind === "call") return `跟注 ${format(action.cost ?? amount)}${String(action.label || "").includes("all-in") ? "（全下）" : ""}`;
    if (["shove", "allin", "all_in", "all-in"].includes(kind)) return `全下到${suffix}`;
    if (["raise", "bet"].includes(kind)) return `加注到${suffix}`;
    return action.label || "行动";
  }
  function announce(message) {
    clearTimeout(state.announcementTimer);
    $("announcement").textContent = message;
    state.announcementTimer = setTimeout(() => { $("announcement").textContent = ""; }, 4200);
  }
  function showConnection(message) {
    $("connection-message").textContent = message;
    $("connection-banner").hidden = false;
  }
  function clearConnection() { $("connection-banner").hidden = true; }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const externalSignal = options.signal;
    const forwardAbort = () => controller.abort();
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort();
      else externalSignal.addEventListener("abort", forwardAbort, { once: true });
    }
    let timeout = false;
    const timer = setTimeout(() => { timeout = true; controller.abort(); }, options.timeoutMs || 30000);
    try {
      const response = await fetch(path, {
        ...options, signal: controller.signal,
        headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      });
      let data;
      try { data = await response.json(); }
      catch { throw new Error("本地服务返回了无法读取的数据，请重新连接。"); }
      if (!response.ok) {
        const error = new Error(data.error || `请求未完成（${response.status}）。`);
        error.status = response.status;
        throw error;
      }
      return data;
    } catch (error) {
      if (timeout) throw new Error("本地服务响应超时。输入已保留，请检查服务后重试。");
      if (error.name === "TypeError") throw new Error("无法连接本地服务。请确认启动窗口仍在运行，再重新连接。");
      throw error;
    } finally {
      clearTimeout(timer);
      externalSignal?.removeEventListener("abort", forwardAbort);
    }
  }

  function clearErrors() {
    $("form-error").hidden = true;
    document.querySelectorAll(".field-error").forEach((item) => item.remove());
    document.querySelectorAll("[aria-invalid]").forEach((input) => {
      input.removeAttribute("aria-invalid");
      const help = input.dataset.originalDescription;
      if (help) input.setAttribute("aria-describedby", help);
      else input.removeAttribute("aria-describedby");
    });
  }
  function showFieldError(id, message) {
    const input = desktop?.handSetup?.errorTarget(id) || $(id);
    if (!input) return;
    for (let owner = input.parentElement; owner; owner = owner.parentElement) if (owner.tagName === "DETAILS") owner.open = true;
    input.dataset.originalDescription = input.dataset.originalDescription || input.getAttribute("aria-describedby") || "";
    const errorId = `${id}-error`;
    if ($(errorId)) { $(errorId).textContent += ` ${message}`; return; }
    const error = el("span", "field-error", message);
    error.id = errorId;
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", [input.dataset.originalDescription, errorId].filter(Boolean).join(" "));
    const owner = input.closest("td") || input.closest(".field") || input.closest(".player-field") || input.parentNode;
    owner.append(error);
  }
  function focusField(id) { (desktop?.handSetup?.errorTarget(id) || $(id))?.focus(); }
  function formError(message) {
    $("form-error").textContent = message;
    $("form-error").hidden = false;
  }
  function parseList(id, name, errors, allowEmpty = false) {
    const text = $(id).value.trim();
    if (!text && allowEmpty) return [];
    const tokens = text.split(/[,，\s]+/).filter(Boolean);
    const values = tokens.map(Number);
    if (!tokens.length || values.some((value) => !Number.isFinite(value) || value < 0)) errors.push([id, `${name}请填写非负数，用逗号分隔。`]);
    return values;
  }
  function readNumber(id, label, min, integral, max, errors) {
    const raw = $(id).value.trim();
    const result = Number(raw);
    if (!raw || !Number.isFinite(result) || result < min || result > max || (integral && !Number.isInteger(result))) {
      errors.push([id, `${label}需为${integral ? "整数" : "数字"}，范围 ${min}${Number.isFinite(max) ? `–${max}` : " 以上"}。`]);
    }
    return result;
  }
  function treePolicyName(settings, street) { return settings?.[street]?.id?.split(".").at(-1) || "simple"; }
  function usesGeneralPolicy(settings) { return ["preflop", "postflop"].some((street) => treePolicyName(settings, street) === "general"); }
  function treePolicyDefault(street, policy) {
    return state.meta?.custom_native?.tree_policy_defaults?.[street]?.[policy] || (policy === "simple" ? state.meta?.custom_native?.default_config?.tree_settings?.[street] : null);
  }
  function normalizeTreeSettings(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || raw.mode !== "ui") throw new Error("需要 mode=ui 的内置树规则对象。");
    const settings = clone(raw);
    for (const street of ["preflop", "postflop"]) {
      const block = settings[street], policy = treePolicyName(settings, street);
      if (!["simple", "general"].includes(policy) || block?.id !== `${street}.settings.${policy}` || !block.settings || typeof block.settings !== "object" || Array.isArray(block.settings)) throw new Error(`${street} 需为 Simple 或 General settings 对象。`);
      const defaults = treePolicyDefault(street, policy);
      if (!defaults) throw new Error(`当前服务未提供 ${street} ${policy} 规则，请更新服务后重试。`);
      block.settings = { ...clone(defaults.settings), ...block.settings };
    }
    return settings;
  }
  function parseTreeJson(errors, raw) {
    try {
      const settings = normalizeTreeSettings(raw === undefined ? JSON.parse($("tree-settings-json").value) : raw);
      const pre = settings.preflop.settings, post = settings.postflop.settings;
      for (const street of ["preflop", "postflop"]) {
        const defaults = treePolicyDefault(street, treePolicyName(settings, street)).settings;
        for (const key of Object.keys(settings[street].settings)) if (!Object.hasOwn(defaults, key)) throw new Error(`未知下注参数：${key}。`);
      }
      for (const street of ["preflop", "postflop"]) if (treePolicyName(settings, street) === "general") {
        const defaults = treePolicyDefault(street, "general").settings;
        for (const [key, item] of Object.entries(settings[street].settings)) {
          if (!Object.hasOwn(defaults, key)) throw new Error(`未知 General 参数：${key}。`);
          const expected = defaults[key];
          if (Array.isArray(expected)) {
            if (!Array.isArray(item)) throw new Error(`${key} 需为数组。`);
            if (key === "ALLOWED_FLATS_PER_RAISE" && item.some((n) => !Number.isInteger(n) || n < 0)) throw new Error(`${key} 需为非负整数数组。`);
            if (key === "POSTFLOP_FORCE_CHECKDOWN_AFTER" && item.some((n) => !Number.isInteger(n) || n < 0 || n > 3)) throw new Error(`${key} 每项需为 0–3 的整数。`);
          } else if (typeof expected === "boolean" ? typeof item !== "boolean" : typeof expected === "number" ? !Number.isFinite(item) : item !== null && typeof item !== "string") throw new Error(`${key} 的值类型不符合该规则。`);
        }
      }
      if (treePolicyName(settings, "preflop") === "simple") {
        if (!Array.isArray(pre.PREFLOP_SIZES) || !pre.PREFLOP_SIZES.length || pre.PREFLOP_SIZES.some((x) => typeof x !== "string")) throw new Error("PREFLOP_SIZES 需为非空字符串数组。");
        if (!Array.isArray(pre.ALLOWED_FLATS_PER_RAISE) || pre.ALLOWED_FLATS_PER_RAISE.some((x) => !Number.isInteger(x) || x < 0)) throw new Error("ALLOWED_FLATS_PER_RAISE 需为非负整数数组。");
        if (typeof pre.ALLOW_SB_COMPLETE !== "boolean" || !Number.isFinite(pre.PREFLOP_ALLIN_THRESHOLD) || pre.PREFLOP_ALLIN_THRESHOLD < 0) throw new Error("SB 补齐需为布尔值，全下阈值需为非负数。");
      }
      if (treePolicyName(settings, "postflop") === "simple") for (const [key, row] of Object.entries(post)) {
        if (!Array.isArray(row)) throw new Error(`${key} 需为数组。`);
        if (key === "POSTFLOP_FORCE_CHECKDOWN_AFTER") { if (row.some((x) => !Number.isInteger(x) || x < 0 || x > 3)) throw new Error(`${key} 每项需为 0–3 的整数。`); }
        else if (key === "POSTFLOP_ALLOW_DONK" || key === "POSTFLOP_ALLOW_DONK_PREV_AGGRESSION") { if (row.length !== 2 || row.some((x) => typeof x !== "boolean")) throw new Error(`${key} 需为两个布尔值。`); }
        else if (key === "POSTFLOP_ADD_ALLIN_SPR") { if (row.length !== 2 || row.some((x) => !Number.isFinite(x))) throw new Error(`${key} 需为两个有限数值。`); }
        else if (key === "POSTFLOP_MAX_BETS_PER_STREET") { if (row.length !== 2 || row.some((x) => !Number.isInteger(x) || x < -1)) throw new Error(`${key} 需为两个不小于 -1 的整数。`); }
        else if (row.length !== 2 || row.some((xs) => !Array.isArray(xs) || xs.some((x) => !Number.isFinite(x) || x < 0 || (key === "POSTFLOP_GEO" && x === 0)))) throw new Error(`${key} 需为两组非负数值数组，几何尺寸必须大于 0。`);
      }
      return settings;
    } catch (error) {
      errors.push(["tree-settings-json", error instanceof SyntaxError ? "JSON 语法无效，请检查引号、逗号与括号。" : error.message]); return null;
    }
  }
  function readTreeSettings(errors, numberValue) {
    if (state.treeEditorMode === "json" || usesGeneralPolicy(state.treeSettingsDraft)) return parseTreeJson(errors);
    const value = numberValue || ((id, label, min = 0, integral = false, max = Infinity) => readNumber(id, label, min, integral, max, errors));
    const settings = clone(state.treeSettingsDraft || state.meta.custom_native.default_config.tree_settings);
    const pre = settings.preflop.settings, post = settings.postflop.settings;
    const sizes = ["tree-open", "tree-3bet", "tree-4bet", "tree-5bet"].map((id) => $(id).value.trim());
    pre.PREFLOP_SIZES = [...sizes, ...(pre.PREFLOP_SIZES || []).slice(4)];
    pre.ALLOWED_FLATS_PER_RAISE = parseList("tree-flats", "平跟次数", errors, true);
    if (pre.ALLOWED_FLATS_PER_RAISE.some((n) => !Number.isInteger(n))) errors.push(["tree-flats", "平跟次数必须为非负整数。"]);
    pre.ALLOW_SB_COMPLETE = $("sb-complete").checked;
    pre.PREFLOP_ALLIN_THRESHOLD = value("allin-threshold", "全下替换阈值");
    if ($("postflop-enabled").checked) {
      post.POSTFLOP_GEO = [parseList("geo-hu", "单挑几何尺寸", errors, true), parseList("geo-multi", "多人几何尺寸", errors, true)];
      post.POSTFLOP_GEO.forEach((row, i) => { if (row.some((n) => n <= 0)) errors.push([i ? "geo-multi" : "geo-hu", "几何尺寸必须大于 0，或留空。"]); });
      post.POSTFLOP_ADD_ALLIN_SPR = [value("spr-hu", "单挑全下 SPR", -1e12), value("spr-multi", "多人全下 SPR", -1e12)];
      const streets = parseList("checkdown-streets", "最后下注街", errors, true);
      if (streets.length > 9 || streets.some((n) => !Number.isInteger(n) || n > 3)) errors.push(["checkdown-streets", "最多 9 项，每项填 0、1、2 或 3。"]);
      post.POSTFLOP_FORCE_CHECKDOWN_AFTER = streets;
    } else post.POSTFLOP_FORCE_CHECKDOWN_AFTER = Array(9).fill(0);
    return settings;
  }
  function fillTreeFields(settings) {
    settings = normalizeTreeSettings(settings);
    state.treeSettingsDraft = clone(settings);
    for (const street of ["preflop", "postflop"]) {
      const policy = treePolicyName(settings, street);
      state.treePolicyDrafts[street][policy] = clone(settings[street]);
      $(`${street}-policy`).value = policy;
    }
    if (usesGeneralPolicy(settings)) state.treeEditorMode = "json";
    $("tree-editor-mode").value = state.treeEditorMode;
    const pre = settings.preflop.settings, post = settings.postflop.settings;
    ["tree-open", "tree-3bet", "tree-4bet", "tree-5bet"].forEach((id, i) => { $(id).value = pre.PREFLOP_SIZES?.[i] ?? "all-in"; });
    $("tree-flats").value = (pre.ALLOWED_FLATS_PER_RAISE || []).join(", ");
    $("sb-complete").checked = !!pre.ALLOW_SB_COMPLETE;
    $("allin-threshold").value = pre.PREFLOP_ALLIN_THRESHOLD;
    $("geo-hu").value = (post.POSTFLOP_GEO?.[0] || []).join(", ");
    $("geo-multi").value = (post.POSTFLOP_GEO?.[1] || []).join(", ");
    $("spr-hu").value = post.POSTFLOP_ADD_ALLIN_SPR?.[0] ?? 5;
    $("spr-multi").value = post.POSTFLOP_ADD_ALLIN_SPR?.[1] ?? 5;
    $("checkdown-streets").value = (post.POSTFLOP_FORCE_CHECKDOWN_AFTER || []).join(", ");
    $("postflop-enabled").checked = (post.POSTFLOP_FORCE_CHECKDOWN_AFTER || []).some((street) => street > 0);
    $("tree-settings-json").value = JSON.stringify(settings, null, 2);
    syncPreflopPreset();
    renderTreeEditor();
  }
  function preflopPresets() { return state.meta?.custom_native?.preflop_presets || window.HrcPreflopCatalog || []; }
  function preflopKey(block) {
    if (!block?.settings) return "";
    const policy = block.id?.split(".").at(-1), defaults = treePolicyDefault("preflop", policy)?.settings || {};
    const values = { ...defaults, ...block.settings };
    return JSON.stringify([block.id, Object.keys(values).sort().map((key) => [key, values[key]])]);
  }
  function syncPreflopPreset(preflop = state.treeSettingsDraft?.preflop) {
    const select = $("preflop-preset"); if (!select) return;
    const rows = preflopPresets(), identity = rows.map((row) => row.id).join("|");
    if (select.dataset.catalog !== identity) {
      select.replaceChildren(new Option("Custom settings", ""));
      for (const [label, include] of [["Multiway / Tournament", (row) => /^\d/.test(row.label)], ["Heads-up", (row) => /^HU\s/i.test(row.label)], ["Other setups", (row) => !/^\d|^HU\s/i.test(row.label)]]) {
        const group = document.createElement("optgroup"); group.label = label;
        for (const row of rows.filter(include)) group.append(new Option(row.label, row.id));
        if (group.children.length) select.append(group);
      }
      select.dataset.catalog = identity;
    }
    const key = preflopKey(preflop);
    select.value = rows.find((row) => preflopKey(row.preflop) === key)?.id || "";
  }
  function applyPreflopBlock(block, label) {
    if (!isCustomNative(state.formBaseConfig) || $("scenario-fields").disabled) return false;
    const errors = [], current = readTreeSettings(errors);
    if (errors.length) {
      syncPreflopPreset(); errors.forEach(([id, message]) => showFieldError(id, message));
      formError("请先修正当前树参数，再选择预设；已有输入已保留。"); $(errors[0][0]).focus(); return false;
    }
    const next = parseTreeJson(errors, { ...current, preflop: clone(block) });
    if (errors.length) { syncPreflopPreset(); showFieldError("preflop-preset", errors[0][1]); formError("翻前预设无效，当前配置已保留。"); return false; }
    state.preflopPresetRequest += 1;
    clearErrors(); fillTreeFields(next); state.policyTopologyDirty = true; state.policySource = null;
    markEdited(); announce(`已应用 ${label} 翻前下注配置；更新决策树后生效。`); return true;
  }
  function parsePreflopFile(text) {
    if (new TextEncoder().encode(text).length > 128 * 1024) throw new Error("翻前预设不能超过 128 KiB。");
    text = text.replace(/^\uFEFF/, ""); const values = Object.create(null); let offset = 0;
    while (offset < text.length) {
      offset += /^(?:\s+|\/\/[^\n]*(?:\n|$)|\/\*[\s\S]*?\*\/)*/.exec(text.slice(offset))[0].length;
      if (offset === text.length) break;
      const match = /^([A-Z][A-Z0-9_]*)\s*=\s*/.exec(text.slice(offset));
      if (!match) throw new Error("仅支持“配置名 = JSON 值;”形式的翻前预设。");
      const key = match[1]; if (Object.hasOwn(values, key)) throw new Error(`预设参数重复：${key}`);
      offset += match[0].length; const begin = offset; let quoted = false, escaped = false;
      for (; offset < text.length; offset += 1) {
        const char = text[offset];
        if (quoted) { if (escaped) escaped = false; else if (char === "\\") escaped = true; else if (char === '"') quoted = false; }
        else if (char === '"') quoted = true; else if (char === ";") break;
      }
      if (offset >= text.length) throw new Error(`预设参数末尾缺少分号：${key}`);
      try { values[key] = JSON.parse(text.slice(begin, offset)); }
      catch { throw new Error(`预设参数不是有效的 JSON 值：${key}`); }
      offset += 1;
    }
    const id = values.CONFIGURATION_ID; delete values.CONFIGURATION_ID;
    if (!["preflop.settings.simple", "preflop.settings.general"].includes(id)) throw new Error("仅支持 Simple 或 Advanced 翻前配置。");
    return { id, settings: values };
  }
  function renderTreeEditor() {
    const general = usesGeneralPolicy(state.treeSettingsDraft);
    $("tree-general-help").hidden = !general;
    $("tree-basic-fields").disabled = general;
    $("tree-editor-mode").querySelector('option[value="form"]').disabled = general;
    $("tree-policy-label").textContent = general ? `翻前 ${treePolicyName(state.treeSettingsDraft, "preflop")} / 翻后 ${treePolicyName(state.treeSettingsDraft, "postflop")}` : "Simple 规则";
    $("tree-basic-fields").hidden = general || state.treeEditorMode === "json";
    $("tree-json-field").hidden = state.treeEditorMode !== "json";
    $("postflop-basic-fields").hidden = !$("postflop-enabled").checked;
    $("checkdown-warning").hidden = $("postflop-enabled").checked;
    const editor = $("tree-settings-json");
    if (!$("tree-json-field").hidden) { editor.style.height = "auto"; editor.style.height = `${Math.min(720, Math.max(280, editor.scrollHeight))}px`; }
  }
  function changeTreeEditor() {
    const next = $("tree-editor-mode").value;
    const errors = [];
    const settings = readTreeSettings(errors);
    if (errors.length) {
      $("tree-editor-mode").value = state.treeEditorMode;
      errors.forEach(([id, message]) => showFieldError(id, message));
      formError("请先修正树参数；已有输入保持不变。"); $(errors[0][0]).focus(); return;
    }
    state.treeEditorMode = next;
    fillTreeFields(settings); markEdited();
  }
  function changeTreePolicy(street) {
    const selected = $(`${street}-policy`).value;
    const errors = [], settings = readTreeSettings(errors);
    if (errors.length) {
      $(`${street}-policy`).value = treePolicyName(state.treeSettingsDraft, street);
      errors.forEach(([id, message]) => showFieldError(id, message));
      formError("请先修正当前树参数；切换没有覆盖已有输入。"); $(errors[0][0]).focus(); return;
    }
    for (const item of ["preflop", "postflop"]) state.treePolicyDrafts[item][treePolicyName(settings, item)] = clone(settings[item]);
    const replacement = state.treePolicyDrafts[street][selected] || treePolicyDefault(street, selected);
    if (!replacement) {
      $(`${street}-policy`).value = treePolicyName(settings, street); formError("当前服务未提供该规则的默认参数。"); return;
    }
    settings[street] = clone(replacement);
    clearErrors(); fillTreeFields(settings);
    state.policyTopologyDirty = true; state.policySource = null;
    markEdited();
    announce("树规则已切换；更新决策树后生效。当前草稿中另一套规则的设置已保留。");
  }
  function readNativeOptions(config, errors, value) {
    if (state.meta.training) {
      config.solver_mode = $("solver-mode").value;
      config.threads = value("training-threads", "计算线程数", 1, true, 32);
      config.track_ci = $("track-ci").checked;
      if (state.meta.training.street_formats) {
        const formats = [23, ...["flop", "turn", "river"].map((street) => Number($(`store-${street}`).value))];
        if (config.stores || formats.slice(1).some((n) => n !== 25)) config.stores = { version: 1, street_formats: formats };
      }
      for (const [key, id, label, min, max] of [["stop_after_seconds", "stop-after-seconds", "目标计算时间", .1, 86400], ["target_ci", "target-ci", "目标 CI", 1e-12, 1e12], ["hard_seconds", "hard-seconds", "最长运行时间", .1, 86400]]) {
        if ($(id).value.trim()) config[key] = value(id, label, min, false, max);
        else delete config[key];
      }
      if (config.target_ci !== undefined && !config.track_ci) errors.push(["track-ci", "设置 CI 停止目标需要启用策略漂移记录。"]);
    }
    if (state.meta.rake && isCustomNative(config)) {
      const mode = $("rake-mode").value;
      if (mode !== "none" || config.rake) {
        config.rake = mode === "none" ? { ...clone(config.rake || state.meta.rake.defaults), mode } : { mode, percentage: value("rake-percentage", "抽水比例", 0, false, 100), cap: value("rake-cap", "抽水上限", 0, false, 1e8) };
        if (mode !== "none" && config.utility !== "chips") errors.push(["rake-mode", "抽水仅支持 ChipEV，请关闭抽水或更改收益模型。"]);
        if (Math.abs(config.rake.cap * 10000 - Math.round(config.rake.cap * 10000)) > .00001) errors.push(["rake-cap", "抽水上限最多保留 4 位小数。"]);
      }
    }
    if (!state.meta.fgs) return;
    const defaults = state.meta.fgs.defaults;
    const fgs = { ...clone(defaults), ...clone(state.formBaseConfig.fgs || {}), enabled: $("fgs-enabled").checked };
    if (fgs.enabled) {
      if (config.utility !== "icm") errors.push(["fgs-enabled", "FGS 仅支持本桌 ICM；请更改收益模型或关闭 FGS。"]);
      for (const [key, min, max] of [["depth", 0, 10], ["depth3way", 0, 10], ["cache_capacity", 0, 100000], ["terminal_cache_capacity", 0, 1000000], ["max_states", 1, 1000000], ["max_sweeps", 1, 100000000]]) fgs[key] = value(`fgs-${key.replaceAll("_", "-")}`, `FGS ${key}`, min, true, max);
      fgs.max_seconds = value("fgs-max-seconds", "FGS 时间预算", .001, false, 86400);
      if ($("fgs-next-enabled").checked) {
        fgs.next_level_at = value("fgs-next-at", "盲注切换手数", 1, true, 10);
        fgs.next_level = { small_blind: value("fgs-next-sb", "下一小盲", 0, false, 1e12), big_blind: value("fgs-next-bb", "下一大盲", .0001, false, 1e12), ante: value("fgs-next-ante", "下一前注", 0, false, 1e12) };
        if (fgs.next_level.small_blind > fgs.next_level.big_blind) errors.push(["fgs-next-sb", "下一小盲不能大于下一大盲。"]);
      } else { fgs.next_level_at = null; fgs.next_level = null; }
    }
    if (fgs.enabled || config.fgs) config.fgs = fgs;
  }
  function fillNativeOptions(config) {
    $("solver-mode").value = config.solver_mode || "v4";
    $("training-threads").value = config.threads ?? 4;
    $("track-ci").checked = !!config.track_ci;
    ["flop", "turn", "river"].forEach((street, i) => { $(`store-${street}`).value = config.stores?.street_formats?.[i + 1] ?? 25; });
    const rake = { ...(state.meta.rake?.defaults || { mode: "none", percentage: 5, cap: 3 }), ...(config.rake || {}) };
    $("rake-mode").value = rake.mode; $("rake-percentage").value = rake.percentage; $("rake-cap").value = rake.cap;
    $("rake-fields").hidden = rake.mode === "none";
    for (const [key, id] of [["stop_after_seconds", "stop-after-seconds"], ["target_ci", "target-ci"], ["hard_seconds", "hard-seconds"]]) $(id).value = config[key] ?? "";
    const fgs = { ...(state.meta.fgs?.defaults || {}), ...(config.fgs || {}) };
    $("fgs-enabled").checked = !!fgs.enabled;
    for (const key of ["depth", "depth3way", "cache_capacity", "terminal_cache_capacity", "max_states", "max_sweeps", "max_seconds"]) $(`fgs-${key.replaceAll("_", "-")}`).value = fgs[key] ?? "";
    $("fgs-next-enabled").checked = fgs.next_level_at != null;
    $("fgs-next-at").value = fgs.next_level_at ?? 1;
    $("fgs-next-sb").value = fgs.next_level?.small_blind ?? config.small_blind;
    $("fgs-next-bb").value = fgs.next_level?.big_blind ?? config.big_blind;
    $("fgs-next-ante").value = fgs.next_level?.ante ?? config.ante;
    renderFgs();
  }
  function renderFgs() {
    $("fgs-fields").hidden = !$("fgs-enabled").checked;
    $("fgs-next-fields").hidden = !$("fgs-next-enabled").checked;
  }
  function readConfig(validationPage = null) {
    clearErrors();
    // An imported tree is an immutable source, not a recipe for our builder.
    if (isImported(state.formBaseConfig)) return clone(state.formBaseConfig);
    const errors = [];
    const value = (id, label, min = 0, integral = false, max = Infinity) => readNumber(id, label, min, integral, max, errors);
    if (isNative(state.formBaseConfig)) {
      const config = { ...clone(state.formBaseConfig),
        iterations: value("iterations", "采样次数", 100, true, sampleLimit()),
        seed: value("seed", "随机种子", 0, true, 4294967295) };
      if (isCustomNative(config)) {
        const chipValue = (id, label, min = 0) => {
          const result = value(id, label, min, false, 1e8);
          const scale = config.chip_scale || 10000;
          if (Number.isFinite(result) && Math.abs(result * scale - Math.round(result * scale)) > .00001) errors.push([id, `${label}需符合当前筹码精度（1/${scale}）。`]);
          return result;
        };
        config.players = collectPlayers().map((player, i) => {
          const name = player.name.trim();
          if (!name || name.length > 30) errors.push([`player-name-${i}`, "座位名称需为 1–30 个字符。"]);
          return { name, stack: chipValue(`player-stack-${i}`, "筹码", .0001), range: "all" };
        });
        config.small_blind = chipValue("small-blind", "小盲");
        config.big_blind = chipValue("big-blind", "大盲", .0001);
        config.ante = chipValue("ante", "前注");
        if (config.small_blind > config.big_blind) errors.push(["small-blind", "小盲不能大于大盲。"]);
        config.ante_type = $("ante-type").value;
        config.straddle = $("straddle").value;
        if (config.players.length < 3 && config.straddle !== "OFF") errors.push(["straddle", "Straddle 至少需要 3 个座位。"]);
        config.skip_small_blind = $("skip-small-blind").checked;
        config.moving_button = state.meta.custom_native.moving_button ? $("moving-button").checked : !!config.moving_button;
        config.max_active = value("max-active", "最多累计参与者", 2, true, 10);
        config.node_budget = value("node-budget", "节点上限", 10, true, 1000000);
        config.tree_settings = readTreeSettings(errors, value);
        config.utility = $("utility").value;
        if (config.utility === "chips") {
          config.other_stacks = [];
          config.payouts = [1];
          config.bounty = { mode: "none", amounts: config.players.map(() => 0), other_amounts: [], immediate_fraction: 1 };
        }
      }
      if (isTournament(config) || (isCustomNative(config) && config.utility !== "chips")) {
        config.utility = $("utility").value;
        config.payouts = parseList("payouts", "奖金序列", errors);
        config.other_stacks = config.utility === "mtt_icm" ? parseList("other-stacks", "外桌筹码", errors, true) : [];
        if (config.other_stacks.some((stack) => stack <= 0)) errors.push(["other-stacks", "每位外桌玩家的筹码必须大于 0。"]);
        if (config.other_stacks.length > 10000 || config.other_stacks.some((stack) => stack > 1e12)) errors.push(["other-stacks", `外桌最多 10000 人，每人筹码不超过 10¹² ${isCustomNative(config) ? "基准单位" : "BB"}。`]);
        if (config.payouts.some((prize, index) => index > 0 && prize > config.payouts[index - 1])) errors.push(["payouts", "奖金请按名次从高到低填写。"]);
        if (config.payouts.some((prize) => prize > 1e12)) errors.push(["payouts", "每个名次的奖金不超过 10¹²。"]);
        if (config.payouts.length > config.players.length + config.other_stacks.length) errors.push(["payouts", "奖金名次数不能超过本桌与外桌总人数。"]);
        const mode = $("bounty-mode").value;
        const amount = mode === "ko" ? value("ko-amount", "每人固定赏金", 0, false, 1e12) : 0;
        const amounts = config.players.map((player, i) => mode === "pko" ? value(`bounty-${i}`, `${player.name} 赏金`, 0, false, 1e12) : amount);
        const otherAmounts = mode === "pko" && config.utility === "mtt_icm" ? parseList("other-bounties", "外桌赏金", errors, true) : config.other_stacks.map(() => amount);
        if (otherAmounts.length !== config.other_stacks.length) errors.push(["other-bounties", "外桌赏金数量必须与外桌筹码人数一致。"]);
        if (otherAmounts.some((amount) => amount > 1e12)) errors.push(["other-bounties", "每位外桌玩家的赏金不超过 10¹²。"]);
        if (mode !== "none" && ![...amounts, ...otherAmounts].some((b) => b > 0)) errors.push(["bounty-mode", "启用赏金时，至少一位玩家的赏金须大于 0。"]);
        if (!config.payouts.some((p) => p > 0) && ![...amounts, ...otherAmounts].some((b) => b > 0)) errors.push(["payouts", "常规奖金或赏金中至少需要一项大于 0。"]);
        config.bounty = { mode, amounts, other_amounts: otherAmounts,
          immediate_fraction: mode === "pko" ? value("immediate-fraction", "即时支付比例", 0, false, 100) / 100 : 1 };
      }
      if (state.policyTopologyDirty && config.policies?.nodes?.length) errors.push(["preset", "树结构已改变。请先清除草稿的全部节点约束，再更新决策树。"]);
      readNativeOptions(config, errors, value);
      const relevant = validationPage === null ? errors : errors.filter(([id]) => desktop?.pageForField(id) === validationPage);
      if (relevant.length) {
        relevant.forEach(([id, message]) => showFieldError(id, message));
        formError("请修正标记的输入。"); focusField(relevant[0][0]); return null;
      }
      if (isCustomNative(config) && validationPage === null) fillTreeFields(config.tree_settings);
      return config;
    }
    const players = Array.from(document.querySelectorAll(".player-field")).map((_, index) => {
      const name = $(`player-name-${index}`).value.trim();
      const range = $(`player-range-${index}`).value.trim();
      if (!name) errors.push([`player-name-${index}`, "请填写座位名称。"]);
      if (!range) errors.push([`player-range-${index}`, "请填写起始范围，例如 all 或 TT+,AKs。"]);
      return { name, stack: value(`player-stack-${index}`, "筹码", 0.000001, false, 10000), range };
    });
    const config = {
      ...(state.formBaseConfig || {}), players,
      small_blind: value("small-blind", "小盲", 0.000001, false, 1000),
      big_blind: value("big-blind", "大盲", 0.000001, false, 1000),
      ante: value("ante", "前注", 0, false, 1000),
      open_sizes: parseList("open-sizes", "首加注尺寸", errors),
      reraise_multipliers: parseList("reraise-sizes", "再加注倍数", errors),
      max_raises: value("max-raises", "非全下加注深度", 0, true, 4),
      utility: $("utility").value,
      payouts: $("utility").value === "icm" ? parseList("payouts", "奖金序列", errors) : [],
      iterations: value("iterations", "训练轮数", 100, true, 20000),
      seed: value("seed", "随机种子", 0, true, 4294967295),
    };
    if (config.small_blind > config.big_blind) errors.push(["small-blind", "小盲不能大于大盲。"]);
    if (config.open_sizes.length > 4 || config.open_sizes.some((size) => size < 2 * config.big_blind || size > 20000)) errors.push(["open-sizes", "填写 1–4 个尺寸，至少为两倍大盲，且不超过 20000。"]);
    if (config.reraise_multipliers.length > 3 || config.reraise_multipliers.some((size) => size < 1.01 || size > 10)) errors.push(["reraise-sizes", "填写 1–3 个倍数，范围为 1.01–10。"]);
    if (config.utility === "chips") {
      const prizes = $("payouts").value.trim().split(/[,，\s]+/).filter(Boolean).map(Number).slice(0, players.length);
      const valid = prizes.length && prizes.some((prize) => prize > 0) && prizes.every((prize, index) => Number.isFinite(prize) && prize >= 0 && (!index || prize <= prizes[index - 1]));
      config.payouts = valid ? prizes : [1];
    }
    if (config.utility === "icm" && config.payouts.some((prize, index) => index > 0 && prize > config.payouts[index - 1])) errors.push(["payouts", "奖金请按名次从高到低填写。"]);
    if (config.utility === "icm" && (config.payouts.length > players.length || !config.payouts.some((prize) => prize > 0))) errors.push(["payouts", "奖金至少有一项大于 0，名次数不能超过座位数。"]);
    const relevant = validationPage === null ? errors : errors.filter(([id]) => desktop?.pageForField(id) === validationPage);
    if (relevant.length) {
      relevant.forEach(([id, message]) => showFieldError(id, message));
      formError("请修正标记的输入；当前结果不会被修改。");
      focusField(relevant[0][0]);
      return null;
    }
    return config;
  }
  function collectPlayers() {
    return Array.from(document.querySelectorAll(".player-field")).map((_, index) => ({
      name: $(`player-name-${index}`).value,
      stack: $(`player-stack-${index}`).value,
      range: $(`player-range-${index}`).value,
      bounty: $(`bounty-${index}`)?.value ?? "0",
    }));
  }
  function renderPlayerFields(players) {
    if (desktop?.handSetup) { desktop.handSetup.renderPlayers(players); return; }
    const custom = usesChipUnits(state.formBaseConfig);
    const fragment = document.createDocumentFragment();
    players.forEach((player, index) => {
      const card = el("div", "player-field");
      const top = el("div", "player-top");
      const nameLabel = el("label");
      nameLabel.htmlFor = `player-name-${index}`;
      nameLabel.append(el("span", "seat-marker", String(index + 1)));
      const name = el("input", "player-name");
      name.id = `player-name-${index}`;
      name.type = "text";
      name.maxLength = custom ? 30 : 18;
      name.value = player.name;
      name.setAttribute("aria-label", `座位 ${index + 1} 名称`);
      nameLabel.append(name);
      const stackLabel = el("label");
      stackLabel.htmlFor = `player-stack-${index}`;
      const stack = el("input");
      stack.id = `player-stack-${index}`;
      stack.type = "number";
      stack.min = custom ? "0.0001" : "0.000001";
      stack.max = custom ? "100000000" : "10000";
      stack.step = custom ? "0.0001" : "0.5";
      stack.inputMode = "decimal";
      stack.value = player.stack;
      stack.setAttribute("aria-label", `座位 ${index + 1} 筹码${custom ? "，与盲注同单位" : "，单位 BB"}`);
      stackLabel.append(stack);
      top.append(nameLabel, stackLabel);
      const rangeRow = el("div", "player-range");
      const rangeLabel = el("label", "", "范围");
      rangeLabel.htmlFor = `player-range-${index}`;
      const range = el("input");
      range.id = `player-range-${index}`;
      range.type = "text";
      range.value = player.range && typeof player.range === "object"
        ? Object.entries(player.range).map(([hand, weight]) => `${hand}:${weight}`).join(",")
        : player.range || "all";
      range.spellcheck = false;
      range.setAttribute("aria-label", `座位 ${index + 1} 起始范围`);
      rangeRow.append(rangeLabel, range);
      card.append(top, rangeRow);
      fragment.append(card);
    });
    $("player-fields").replaceChildren(fragment);
    $("seat-count").textContent = `${players.length} 人`;
    $("add-seat").disabled = players.length >= (custom ? 10 : 6);
    $("remove-seat").disabled = players.length <= 2;
  }
  function setConfig(config) {
    state.preflopPresetRequest += 1;
    state.formBaseConfig = clone(config);
    state.policyTopologyDirty = false;
    clearErrors();
    renderPlayerFields(config.players);
    const map = {
      "small-blind": config.small_blind, "big-blind": config.big_blind, ante: config.ante,
      "open-sizes": (config.open_sizes || []).join(", "), "reraise-sizes": (config.reraise_multipliers || []).join(", "),
      "max-raises": config.max_raises ?? 1, utility: config.utility,
      payouts: (config.payouts || []).join(", "), iterations: config.iterations, seed: config.seed,
    };
    Object.entries(map).forEach(([id, value]) => { $(id).value = value; });
    fillNativeOptions(config);
    $("other-stacks").value = (config.other_stacks || []).join(", ");
    $("bounty-mode").value = config.bounty?.mode || "none";
    $("ko-amount").value = config.bounty?.amounts?.[0] ?? 0;
    $("immediate-fraction").value = 100 * (config.bounty?.mode === "pko" ? config.bounty.immediate_fraction : 0.5);
    $("other-bounties").value = (config.bounty?.other_amounts || []).join(", ");
    $("ante-type").value = config.ante_type || "REGULAR";
    $("straddle").value = config.straddle || "OFF";
    $("skip-small-blind").checked = !!config.skip_small_blind;
    $("moving-button").checked = !!config.moving_button;
    renderBountyFields(config.players.map((player, i) => ({ ...player, bounty: config.bounty?.amounts?.[i] ?? 0 })));
    if (isCustomNative(config)) {
      $("ante-type").value = config.ante_type;
      $("straddle").value = config.straddle;
      $("skip-small-blind").checked = config.skip_small_blind;
      $("moving-button").checked = !!config.moving_button;
      state.treePolicyDrafts = { preflop: {}, postflop: {} };
      $("max-active").value = config.max_active;
      $("node-budget").value = config.node_budget;
      state.treeEditorMode = "form"; $("tree-editor-mode").value = "form";
      fillTreeFields(config.tree_settings);
    }
    $("preset").value = presetValue(config);
    renderTournamentFields();
    updateControls();
  }
  function renderBountyFields(players) {
    $("player-bounties").replaceChildren(...players.map((player, i) => {
      const field = el("div", "field");
      const label = el("label", "", player.name); label.htmlFor = `bounty-${i}`;
      const input = el("input"); input.id = `bounty-${i}`; input.type = "number";
      input.min = "0"; input.step = "any"; input.inputMode = "decimal";
      input.value = player.bounty ?? 0;
      field.append(label, input); return field;
    }));
    desktop?.handSetup?.refresh();
  }
  function refreshFormVisibility() {
    renderTournamentFields(); renderFgs();
    $("rake-fields").hidden = $("rake-mode").value === "none";
    if (isCustomNative(state.formBaseConfig)) renderTreeEditor();
    updateControls(); desktop?.handSetup?.refresh();
  }
  function renderTournamentFields() {
    const tournament = hasTournamentInputs(state.formBaseConfig);
    const mtt = $("utility").value === "mtt_icm";
    const mode = $("bounty-mode").value;
    $("tournament-fields").hidden = !tournament;
    $("payout-field").hidden = $("utility").value === "chips";
    $("other-stacks-field").hidden = !mtt;
    $("ko-amount-field").hidden = mode !== "ko";
    $("pko-fields").hidden = mode !== "pko";
    $("other-bounties-field").hidden = !mtt;
    if (tournament) {
      const external = mtt ? $("other-stacks").value.trim().split(/[,，\s]+/).filter(Boolean).length : 0;
      const seats = collectPlayers().length;
      const description = mode === "none" ? "无赏金" : mode === "ko" ? "固定赏金 · 全额即时支付" : `PKO · 即时支付 ${$("immediate-fraction").value || "—"}%`;
      $("tournament-input-summary").textContent = `本桌 ${seats} 人 + 外桌 ${external} 人，共 ${seats + external} 人 · ${description}。EV 使用奖金单位。`;
    }
  }
  function markEdited() {
    state.draftDirty = true;
    state.formEdited = true;
    if (!isNative(state.formBaseConfig)) $("preset").value = "default";
    renderTournamentFields();
    renderContext();
  }
  function updateControls() {
    const importedDraft = isImported(state.formBaseConfig);
    const importedResult = isImported(state.job?.config);
    $("scenario-fields").disabled = !state.meta || state.busy || importedDraft;
    $("start-solve").disabled = !state.meta || state.busy || !!state.activeId || importedDraft;
    $("start-solve").setAttribute("aria-busy", String(state.busy));
    $("apply-tree").disabled = !state.meta || state.busy || state.loading || importedDraft;
    $("export-config").disabled = !state.meta || state.busy;
    $("import-config").disabled = !state.meta || state.busy;
    $("show-model").disabled = !state.meta;
    $("view-result").disabled = !state.job || state.busy;
    $("view-draft").disabled = !state.meta || state.busy;
    $("job-history").disabled = state.busy;
    $("resume-job").disabled = !state.job?.can_resume || state.busy || !!state.activeId || Number(state.job?.summary?.iterations_completed || 0) >= sampleLimit();
    $("resume-job").setAttribute("aria-busy", String(state.busy));
    $("resume-target").disabled = state.busy || !!state.activeId;
    $("resume-threads").disabled = state.busy || !!state.activeId;
    $("resume-target").max = sampleLimit();
    $("resume-reset-controls").hidden = !state.meta?.training?.reset_regret && !state.meta?.training?.reset_average;
    $("reset-regret").disabled = state.busy || !!state.activeId || !state.meta?.training?.reset_regret;
    $("reset-average").disabled = state.busy || !!state.activeId || !state.meta?.training?.reset_average;
    $("resume-migration-controls").hidden = !state.meta?.training?.checkpoint_migration || importedResult;
    $("resume-use-draft").disabled = state.busy || !!state.activeId || importedResult;
    $("checkpoint-migration").disabled = state.busy || !!state.activeId || importedResult || !$("resume-use-draft").checked;
    const persistence = state.meta?.persistence;
    $("archive-panel").hidden = !persistence?.archive_import && !persistence?.archive_export && !persistence?.hrcz_import && !persistence?.hrcz_export;
    $("export-archive").hidden = !persistence?.archive_export;
    $("export-hrcz").hidden = !persistence?.hrcz_export;
    $("export-hrcz").disabled = !persistence?.hrcz_export || !state.job?.can_export_hrcz || state.busy || state.archiveBusy;
    $("import-archive").hidden = !persistence?.archive_import && !persistence?.hrcz_import;
    $("export-archive").disabled = !state.job?.can_export_archive || state.busy || state.archiveBusy;
    $("import-archive").disabled = !(persistence?.archive_import || persistence?.hrcz_import) || state.busy || state.archiveBusy || !!state.activeId;
    $("archive-resources").disabled = !state.job?.can_export_archive || state.busy || state.archiveBusy;
    $("archive-panel").setAttribute("aria-busy", String(state.archiveBusy));
    $("back-node").disabled = !state.path.length || state.loading;
    const fixed = isFixed(state.formBaseConfig);
    const tournament = isTournament(state.formBaseConfig);
    const custom = isCustomNative(state.formBaseConfig);
    const native = fixed || custom;
    fieldIds.filter((id) => !["iterations", "seed"].includes(id)).forEach((id) => { $(id).disabled = fixed && !(tournament && ["utility", "payouts"].includes(id)); });
    $("utility").querySelector('option[value="chips"]').disabled = tournament;
    $("utility").querySelector('option[value="mtt_icm"]').disabled = !(tournament || custom);
    $("player-fields").querySelectorAll("input").forEach((input) => { input.disabled = fixed || (custom && input.id.startsWith("player-range-")); });
    $("add-seat").disabled = fixed || collectPlayers().length >= (custom ? 10 : 6);
    $("remove-seat").disabled = fixed || collectPlayers().length <= 2;
    $("iterations").max = native ? sampleLimit() : 20000;
    $("training-controls").hidden = !native || !state.meta?.training;
    $("store-controls").hidden = !native || !state.meta?.training?.street_formats;
    $("fgs-section").hidden = !native || !state.meta?.fgs;
    $("rake-section").hidden = !custom || !state.meta?.rake;
    const policyVisible = !!state.meta?.training?.policies && isNative(currentConfig());
    const editablePolicy = policyVisible && !isImported(currentConfig()) && state.view === "draft" && !state.draftDirty && !state.busy && !state.loading && !!state.node && !state.node.terminal && state.node.actions.length >= 2;
    $("policy-panel").hidden = !policyVisible;
    $("policy-editor").disabled = !editablePolicy;
    $("policy-save").disabled = !editablePolicy;
    $("policy-remove").disabled = !editablePolicy;
    $("policy-lock-fill").disabled = !editablePolicy || !canLockBuckets();
    $("policy-copy-result").hidden = state.view !== "result";
    $("policy-copy-result").disabled = state.busy || state.loading || !state.job || importedResult;
    $("policy-clear-all").disabled = state.busy || importedDraft || !(state.formBaseConfig?.policies?.nodes?.length);
    $("policy-context").textContent = isImported(currentConfig()) ? "原版存档的树、模型和约束保持冻结；可查看已保存策略。只有服务确认支持时，才可在原树上续跑。" : state.view === "result" ? "当前结果只读。使用下方按钮，以该任务配置替换左侧草稿并创建新训练；原任务保持不变。" : state.draftDirty ? "请先更新决策树，再编辑当前节点约束。已有约束绑定原树；更改树结构需先清除约束。" : state.node?.terminal ? "终局没有可设置的行动约束。" : `当前 ${state.node?.actor_name || "—"} · 节点 ${state.node?.native_id ?? "—"}。应用约束会更新草稿，之后开始新的训练。`;
    $("research-note").hidden = !native;
    $("research-note").textContent = custom ? "独立生成内置规则行动树；起始范围暂为 all。翻后使用本机 1024 / 256 / 256 桶，动态抽象尚未接入。验证范围见模型说明。" : tournament ? "锦标赛研究使用所选预设的固定筹码、盲注与行动树；可编辑奖金、外桌与赏金。自由建树请选自定义原生模式。" : "筹码与行动树固定。翻后桶使用本机 HRC 数据，策略从零训练；可用训练控制由本地服务提供。";
    if (importedDraft) $("research-note").textContent = "原版 .hrcz 场景与行动树已冻结。保存的数据可直接查看与导出；是否支持续跑以本任务状态为准。新建场景请使用 File → New。";
    $("moving-button-field").hidden = !custom || !state.meta?.custom_native?.moving_button;
    $("tree-policy-fields").hidden = !custom || !state.meta?.custom_native?.tree_policy_defaults;
    $("native-blind-fields").hidden = !custom;
    $("native-tree-fields").hidden = !custom;
    $("legacy-tree-fields").hidden = custom || importedDraft;
    $("range-help").hidden = native;
    $("stack-unit-label").textContent = custom || importedDraft ? "筹码 / 基准单位" : "筹码 / BB";
    $("blind-unit-label").textContent = custom || importedDraft ? "与筹码同单位" : "单位 BB";
    $("input-unit-tag").textContent = custom || importedDraft ? "筹码" : "BB";
    $("tournament-unit-help").textContent = custom || importedDraft ? "奖金与赏金使用同一金额单位。外桌筹码与本桌筹码使用同一基准单位，结果按大盲换算为 BB。" : "奖金与赏金使用同一金额单位；筹码和外桌筹码仍以 BB 填写。本模式沿用固定行动树。";
    document.querySelector('label[for="other-stacks"] span').textContent = custom || importedDraft ? "筹码 / 人" : "BB / 人";
    document.querySelector('label[for="ante"]').textContent = importedDraft ? state.formBaseConfig.ante_type && state.formBaseConfig.ante_type !== "REGULAR" ? "BB前注总额" : "每人前注" : custom && $("ante-type").value !== "REGULAR" ? "BB前注总额" : "每人前注";
    ["small-blind", "big-blind", "ante"].forEach((id) => { $(id).max = custom ? "100000000" : "1000"; $(id).step = custom ? "0.0001" : "0.1"; });
    $("small-blind").min = custom ? "0" : "0.000001";
    $("big-blind").min = custom ? "0.0001" : "0.000001";
    $("reraise-sizes").placeholder = fixed ? "仅全下" : "3";
    $("raise-depth-help").textContent = fixed ? "对照树的再加注仅含全下；多人对照配置最多 4 位累计参与者。" : "所有增加下注的行动（含短全下）都计入深度。";
    desktop?.handSetup?.refresh();
    desktop?.updateCommands();
  }
  function renderContext() {
    $("view-draft").setAttribute("aria-pressed", String(state.view === "draft"));
    $("view-result").setAttribute("aria-pressed", String(state.view === "result"));
    $("context-summary").textContent = configSummary(currentConfig());
    const differentSnapshot = state.view === "result" && state.job && JSON.stringify(state.appliedConfig) !== JSON.stringify(state.job.config);
    $("dirty-notice").classList.toggle("is-dirty", state.draftDirty || !!differentSnapshot);
    if ((state.draftDirty || differentSnapshot) && state.view === "result") $("dirty-copy").textContent = "左侧场景与当前任务不同；此处使用该任务的配置。开始新任务才会使用左侧输入，续跑使用所选任务的检查点。";
    else if (state.draftDirty) $("dirty-copy").textContent = "输入已修改，决策树仍使用上次应用的场景。点击“更新决策树”应用新输入。";
    else if (state.view === "result") $("dirty-copy").textContent = `正在查看任务 ${state.job.id.slice(0, 8)} 的配置与${isRunning(state.job) ? "决策树；训练结束后加载频率" : "抽样策略"}。`;
    else $("dirty-copy").textContent = "场景预览只展示合法行动；点击“开始求解”训练各节点的手牌策略。";
    if (state.meta) renderMeta();
    renderTournamentAnalysis();
    updateControls();
    desktop?.render();
  }
  function resetNode() {
    state.node = null;
    state.path = [];
    state.labels = [];
    renderNode();
  }
  async function loadNode(path = state.path, labels = state.labels) {
    const config = currentConfig();
    if (!config) return;
    state.nodeController?.abort();
    const controller = new AbortController();
    state.nodeController = controller;
    const requestId = ++state.requestId;
    const view = state.view;
    const jobId = state.job?.id;
    state.lastNodeRequest = { path: [...path], labels: [...labels] };
    state.loading = true;
    $("node-error").hidden = true;
    $("retry-node").hidden = true;
    document.querySelector(".tree-panel").classList.add("is-loading");
    document.querySelector(".tree-panel").setAttribute("aria-busy", "true");
    $("node-status").textContent = "正在加载节点";
    $("node-actions").querySelectorAll("button").forEach((button) => { button.disabled = true; });
    updateControls();
    try {
      const node = view === "result" && jobId
        ? await api(`/api/jobs/${encodeURIComponent(jobId)}/node?path=${encodeURIComponent(JSON.stringify(path))}`, { signal: controller.signal })
        : await api("/api/tree", { method: "POST", body: JSON.stringify({ config, path }), signal: controller.signal });
      if (requestId !== state.requestId) return;
      if (view === "result" && jobId && state.checkpointJobId !== jobId) {
        const restored = await api(`/api/jobs/${encodeURIComponent(jobId)}`, { signal: controller.signal });
        if (requestId !== state.requestId) return;
        state.job = restored; state.checkpointJobId = jobId;
        upsertJob(restored); renderJob();
      }
      state.node = node;
      state.path = [...path];
      state.labels = [...labels];
      clearConnection();
      renderNode();
    } catch (error) {
      if (error.name === "AbortError" || requestId !== state.requestId) return;
      $("node-error").textContent = error.message;
      $("node-error").hidden = false;
      $("retry-node").hidden = false;
      $("retry-node").disabled = false;
      $("node-status").textContent = "节点加载失败";
    } finally {
      if (requestId === state.requestId) {
        state.loading = false;
        document.querySelector(".tree-panel").classList.remove("is-loading");
        document.querySelector(".tree-panel").setAttribute("aria-busy", "false");
        $("node-actions").querySelectorAll("button").forEach((button) => { button.disabled = false; });
        updateControls();
      }
    }
  }
  function renderBreadcrumbs() {
    const list = $("breadcrumbs");
    const labels = ["起始节点", ...state.labels];
    list.replaceChildren(...labels.map((text, index) => {
      const item = el("li");
      if (index === labels.length - 1) {
        item.textContent = text;
        item.setAttribute("aria-current", "page");
      } else {
        const button = el("button", "", text);
        button.type = "button";
        button.addEventListener("click", () => { if (!state.loading) loadNode(state.path.slice(0, index), state.labels.slice(0, index)); });
        item.append(button);
      }
      return item;
    }));
  }
  function renderSeats() {
    const config = currentConfig();
    const node = state.node;
    if (!config || !node) { $("table-seats").replaceChildren(); return; }
    const positionSets = {
      2: [[50, 13], [50, 88]],
      3: [[50, 12], [83, 80], [17, 80]],
      4: [[27, 12], [77, 12], [77, 86], [27, 86]],
      5: [[50, 10], [87, 36], [73, 86], [27, 86], [13, 36]],
      6: [[29, 12], [72, 12], [88, 50], [72, 86], [29, 86], [12, 50]],
      8: [[32, 10], [68, 10], [88, 35], [88, 65], [68, 90], [32, 90], [12, 65], [12, 35]],
      9: [[50, 10], [76, 19], [89, 43], [85, 70], [64, 88], [36, 88], [15, 70], [11, 43], [24, 19]],
    };
    const count = config.players.length;
    $("table-seats").closest(".table-view").classList.toggle("nine-seats", count >= 8);
    $("table-seats").replaceChildren(...config.players.map((player, index) => {
      const seat = el("div", "table-seat");
      seat.classList.toggle("is-actor", node.actor === index);
      seat.classList.toggle("is-folded", !!node.folded?.[index]);
      const angle = Math.PI / 2 + (index - (count - 2)) * Math.PI * 2 / count;
      const [left, top] = desktop?.enabled ? [50 + 39 * Math.cos(angle), 50 + 37 * Math.sin(angle)] : positionSets[count]?.[index] || [50 + 39 * Math.cos(angle), 50 + 40 * Math.sin(angle)];
      seat.style.left = `${left}%`;
      seat.style.top = `${top}%`;
      const header = el("div", "seat-top");
      const role = node.folded?.[index] ? "弃牌" : node.all_in?.[index] ? "全下" : node.actor === index ? "行动" : index === count - 1 ? "BB" : index === count - 2 ? "SB" : "";
      header.append(el("strong", "", player.name), el("span", "seat-role", role));
      const stack = el("div", "seat-stack", format(node.remaining?.[index]));
      stack.append(el("small", "", " BB"));
      if (desktop?.enabled && !node.folded?.[index]) {
        const cards = el("span", "hrc-hole-cards"); cards.setAttribute("aria-hidden", "true");
        cards.append(el("i"), el("i")); seat.append(cards);
      }
      seat.append(header, stack, el("span", "seat-contribution", `已投入 ${format(node.contributions?.[index])}`));
      if (desktop?.enabled) {
        const unit = usesChipUnits(config) ? config.big_blind : 1;
        stack.replaceChildren(document.createTextNode(`${Number(node.remaining?.[index] || 0).toFixed(2)}bb`));
        header.replaceChildren(el("strong", "", player.name));
        if (config.bounty?.mode && config.bounty.mode !== "none") {
          seat.append(el("span", "hrc-seat-bounty", `${format(config.bounty.amounts[index] * (config.bounty.mode === "pko" ? config.bounty.immediate_fraction : 1))}`));
        }
        if (index === count - 3 || count === 2 && index === 0) seat.append(el("span", "hrc-dealer", "D"));
        seat.dataset.stackUnit = String(unit);
      }
      seat.setAttribute("aria-label", `${player.name}，${role}，剩余 ${format(node.remaining?.[index])} BB，已投入 ${format(node.contributions?.[index])} BB`);
      return seat;
    }));
  }
  function renderNode() {
    const node = state.node;
    renderBreadcrumbs();
    renderSeats();
    const pot = $("pot-value");
    pot.replaceChildren(document.createTextNode(node ? `${format(node.pot)} ` : "— "), el("small", "", "BB"));
    $("actor-name").textContent = node ? node.terminal ? "行动结束" : node.actor_name || "—" : "—";
    $("actor-caption").textContent = node?.terminal ? "终止节点" : "当前行动者";
    $("range-actor").textContent = node && !node.terminal ? `${node.actor_name} · ${node.street > 0 ? `${node.buckets} 桶` : "169 类"}` : "—";
    const callAction = node?.actions?.find((action) => action.kind === "call");
    const toCall = node && node.actor !== null ? Number(callAction?.cost ?? Math.max(0, Number(node.current_bet) - Number(node.street_contributions?.[node.actor] || 0))) : 0;
    $("to-call").textContent = node ? node.terminal ? "进入结算" : `待跟 ${format(Math.min(toCall, node.remaining?.[node.actor] ?? toCall))} BB` : "等待场景";
    $("action-instruction").textContent = node?.terminal ? node.terminal_kind === "fold_award" ? "其余玩家已弃牌，底池归最后一位玩家；无需摊牌。" : "此路径已无下注行动；按抽样公共牌摊牌结算。" : `${node?.street_name || "翻前"} · 点击一个行动，进入下一级节点。`;
    $("node-status").textContent = node ? node.terminal ? "TERMINAL" : `DEPTH ${state.path.length.toString().padStart(2, "0")}` : "等待场景";
    $("node-summary").textContent = node ? (node.terminal ? "行动已结束，可返回上一级继续探索。" : `${node.street_name || "翻前"} · 当前下注 ${format(node.current_bet)} BB · ${(node.actions || []).length} 个可选行动`) + (node.dead_money > 0 ? ` · 公共前注 ${format(node.dead_money)} BB（已计入底池）` : "") : "请加载场景后探索行动。";
    $("node-actions").replaceChildren(...(node?.actions || []).map((action, index) => {
      const button = el("button", "action-button", actionLabel(action));
      button.type = "button";
      button.style.setProperty("--action-color", colorFor(action, index));
      button.addEventListener("click", () => {
        if (state.loading) return;
        loadNode([...state.path, action.id], [...state.labels, `${node.actor_name} ${actionLabel(action)}`]);
      });
      return button;
    }));
    document.title = `${node?.terminal ? "行动结束" : node?.actor_name ? `${node.actor_name} 行动` : "翻前研究台"} — Preflop Lab`;
    desktop?.render();
    renderRange();
    renderPolicy();
    updateControls();
  }
  function trainedHand(label) {
    const hand = state.node?.strategy?.hands?.[label];
    return hasHandPolicy(hand) ? hand : null;
  }
  function strategyActions() {
    const actions = state.node?.strategy?.actions;
    return Array.isArray(actions) && actions.every((action) => typeof action === "object") ? actions : state.node?.actions || [];
  }
  function referenceHand(label) {
    const hand = state.node?.strategy?.hands?.[label]?.reference;
    if (!hand || !Array.isArray(hand.frequencies) || hand.frequencies.length !== strategyActions().length || !hand.frequencies.length) return null;
    if (hand.frequencies.some((frequency) => !Number.isFinite(frequency) || frequency < 0)) return null;
    return hand;
  }
  function renderMatrix(target, labels, handFor, source) {
    const actions = strategyActions();
    const colors = actions.map(rawColorFor);
    let count = 0;
    target.replaceChildren(...labels.map((label, index) => {
      const hand = handFor(label);
      const button = el("button", "hand-cell");
      button.type = "button";
      button.dataset.hand = label;
      button.dataset.index = index;
      button.classList.toggle("untrained", !hand);
      button.classList.toggle("is-pair", label.length === 2);
      button.setAttribute("aria-pressed", String(label === state.selectedHand));
      button.tabIndex = label === state.selectedHand ? 0 : -1;
      const frequencies = hand ? actions.map((action, i) => `${actionLabel(action)} ${(hand.frequencies[i] * 100).toFixed(2)}%`).join("，") : "尚无策略数据";
      const description = `${source} ${label}，${frequencies}${hand?.visits != null ? `，${sourceHistory()?.history_unknown ? "导入后新增 " : ""}${formatInt(hand.visits)} 次访问` : hand?.has_saved_policy ? "，原档逐手采样历史未知" : ""}`;
      button.setAttribute("aria-label", description);
      button.title = description;
      if (hand) {
        count += 1;
        let offset = 0;
        const stops = hand.frequencies.map((frequency, actionIndex) => {
          const start = offset;
          offset += frequency * 100;
          return `${colors[actionIndex]} ${start}% ${offset}%`;
        });
        button.style.setProperty("--cell-background", `linear-gradient(to right, ${stops.join(", ")})`);
      }
      button.append(el("span", "hand-cell-label", label));
      button.addEventListener("click", () => selectHand(label));
      button.addEventListener("keydown", (event) => {
        if (event.isComposing) return;
        const shifts = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 13, ArrowUp: -13 };
        let next = index;
        if (Object.hasOwn(shifts, event.key)) next = Math.max(0, Math.min(labels.length - 1, index + shifts[event.key]));
        else if (event.key === "Home") next = event.ctrlKey ? 0 : Math.floor(index / 13) * 13;
        else if (event.key === "End") next = event.ctrlKey ? labels.length - 1 : Math.min(labels.length - 1, Math.floor(index / 13) * 13 + 12);
        else return;
        event.preventDefault();
        selectHand(labels[next]);
        target.children[next].focus();
      });
      return button;
    }));
    return count;
  }
  function renderStrategyTotals(target, labels, handFor) {
    const actions = strategyActions();
    const totals = actions.map(() => 0);
    let combinations = 0;
    labels.forEach((label) => {
      const hand = handFor(label);
      if (!hand) return;
      const weight = label.length === 2 ? 6 : label.endsWith("s") ? 4 : 12;
      combinations += weight;
      hand.frequencies.forEach((value, index) => { totals[index] += value * weight; });
    });
    target.replaceChildren(el("span", "totals-caption", `组合加权 · 覆盖 ${combinations} / 1326`), ...actions.map((action, i) => {
      const item = el("span", "strategy-total");
      const swatch = el("i", "legend-dot");
      swatch.style.setProperty("--action-color", colorFor(action));
      item.append(swatch, document.createTextNode(`${actionLabel(action)} `), el("strong", "mono", combinations ? `${(100 * totals[i] / combinations).toFixed(4)}%` : "—"));
      return item;
    }));
  }
  function renderRange() {
    const labels = rangeLabels();
    if (!labels.includes(state.selectedHand)) state.selectedHand = labels[0] || "AA";
    const postflop = state.node?.street > 0;
    const comparing = !desktop?.enabled && !postflop && !state.node?.terminal && labels.some((label) => referenceHand(label));
    $("range-panel").classList.toggle("is-comparing", comparing);
    $("strategy-matrices").classList.toggle("is-comparing", comparing);
    ["reference-panel", "ours-heading", "ours-totals", "comparison-help"].forEach((id) => { $(id).hidden = !comparing; });
    if (comparing) {
      renderMatrix($("reference-matrix"), labels, referenceHand, "HRC 原版");
      renderStrategyTotals($("reference-totals"), labels, referenceHand);
      renderStrategyTotals($("ours-totals"), labels, trainedHand);
      $("ours-samples").textContent = `种子 ${state.job.config.seed} · ${formatInt(state.job.summary?.iterations_completed)} 次采样`;
    } else {
      $("reference-matrix").replaceChildren();
      $("reference-totals").replaceChildren();
      $("ours-totals").replaceChildren();
    }
    $("range-matrix").classList.toggle("bucket-matrix", postflop);
    $("range-matrix").setAttribute("aria-label", postflop ? "翻后抽象桶" : "169 类起手牌");
    $("range-title").textContent = postflop ? "翻后抽象桶" : comparing ? "策略对照 · 13×13" : "起手牌范围";
    $("matrix-caption-label").textContent = postflop ? `桶需结合公共牌映射；显示${state.node?.strategy?.basis === "current_regret_policy" ? "当前遗憾" : "平均行动"}策略` : "上三角同花 · 下三角非同花";
    const actions = strategyActions();
    const legend = actions.map((action, index) => {
      const item = el("span");
      const swatch = el("i", "legend-dot");
      swatch.style.setProperty("--action-color", colorFor(action, index));
      item.append(swatch, document.createTextNode(actionLabel(action)));
      return item;
    });
    const neutral = el("span");
    neutral.append(el("i", "legend-dot untrained"), document.createTextNode("无策略数据"));
    $("range-legend").replaceChildren(...legend, neutral);
    const count = renderMatrix($("range-matrix"), labels, trainedHand, state.job?.has_source_strategy && state.view === "result" ? "已载入策略" : "我们的策略");
    $("sampled-count").textContent = `${count} / ${labels.length} 有策略数据`;
    $("node-visits").textContent = state.node?.strategy?.visits != null ? `${sourceHistory()?.history_unknown && state.view === "result" ? "导入后新增 " : ""}${formatInt(state.node.strategy.visits)}` : state.job?.has_source_strategy && state.view === "result" ? "原档历史未知" : "—";
    $("export-csv").disabled = !count;
    renderHand();
    desktop?.decorateRange();
  }
  function selectHand(label) {
    state.selectedHand = label;
    $("strategy-matrices").querySelectorAll(".hand-cell").forEach((button) => {
      const selected = button.dataset.hand === label;
      button.setAttribute("aria-pressed", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    renderHand();
    renderPolicyHand();
  }
  function renderHand() {
    const label = state.selectedHand;
    const hand = trainedHand(label);
    $("selected-hand").textContent = label;
    const postflop = state.node?.street > 0;
    $("hand-type").textContent = postflop ? "公共牌与手牌的抽象类别" : label.length === 2 ? "口袋对子 · 6 个组合" : label.endsWith("s") ? "同花手牌 · 4 个组合" : "非同花手牌 · 12 个组合";
    $("hand-visits").textContent = !hand ? "尚无策略数据" : hand.visits == null ? "原档有策略；逐手采样历史未知" : sourceHistory()?.history_unknown && state.view === "result" ? `导入后新增 ${formatInt(hand.visits)} 次更新；原档历史未知` : `${formatInt(hand.visits)} 次遗憾更新${hand.average_samples != null ? ` / ${formatInt(hand.average_samples)} 次平均策略采样` : ""}`;
    const terminal = state.node?.terminal;
    $("hand-description").textContent = terminal ? "终止节点没有后续行动，也没有待求解的行动频率。" : hand ? `在当前行动路径下，${state.node.actor_name} 的 ${label} ${state.node.strategy.basis === "current_regret_policy" ? "当前策略" : "平均行动策略"}${postflop ? "；桶不对应固定起手牌" : ""}。` : state.view === "draft" ? "当前为场景预览。运行求解后，可查看行动频率。" : isRunning(state.job) ? "求解正在运行；训练结束后加载真实采样频率。" : "此类别在当前节点尚无训练样本，不能推断其行动策略。";
    if (!hand) {
      const text = terminal ? "返回上一节点，继续研究行动选择。" : state.view === "draft" ? "尚无策略数据\n点击左侧“开始求解”。" : isRunning(state.job) ? "训练中，暂不显示策略。" : "可增加训练轮数，或调整起始范围后重新求解。";
      $("hand-frequencies").replaceChildren(el("div", "hand-empty", text));
      return;
    }
    $("hand-frequencies").replaceChildren(...strategyActions().map((action, index) => {
      const item = el("div", "frequency-item");
      item.style.setProperty("--action-color", colorFor(action, index));
      const row = el("div", "frequency-label");
      const percentage = Math.max(0, Math.min(100, Number(hand.frequencies[index] || 0) * 100));
      row.append(el("span", "", actionLabel(action)), el("strong", "", `${percentage.toFixed(1)}%`));
      const track = el("div", "frequency-track");
      track.setAttribute("aria-hidden", "true");
      const bar = el("span");
      bar.style.width = `${percentage}%`;
      track.append(bar);
      item.append(row, track);
      const reference = hand.reference;
      if (reference?.frequencies) item.append(el("small", "quiet", `原版 ${(reference.frequencies[index] * 100).toFixed(1)}% · 差 ${(percentage - reference.frequencies[index] * 100).toFixed(2)} 个百分点`));
      const values = hand.relative_ev || hand.relative_ev_bb;
      const referenceValues = reference?.relative_ev || reference?.relative_ev_bb;
      if (Number.isFinite(values?.[index])) item.append(el("small", "quiet", `相对首行动 EV ${values[index].toFixed(4)} ${utilityUnit()}${Number.isFinite(referenceValues?.[index]) ? ` · 原版 ${referenceValues[index].toFixed(4)} ${utilityUnit()}` : ""}`));
      return item;
    }));
  }

  function renderTournamentAnalysis() {
    const job = state.job;
    const visible = !!state.meta?.tournament_analysis && state.view === "result" && isNative(job?.config) && job?.config.utility !== "chips";
    $("tournament-analysis-panel").hidden = !visible;
    if (!visible) return;
    if (state.analysisRenderedId !== job.id) {
      state.analysisRenderedId = job.id;
      $("analysis-error").hidden = true;
      $("tournament-analysis-help").textContent = "按本任务配置计算行玩家对列玩家的有效筹码全下。不包含盲注、前注或死钱；即使本任务启用 FGS，此工具也使用静态权益。";
    }
    const data = state.analysisCache.get(job.id), busy = state.analysisLoading === job.id;
    $("analysis-refresh").disabled = busy; $("analysis-export").disabled = !data;
    $("tournament-analysis-panel").setAttribute("aria-busy", String(busy));
    $("analysis-status").textContent = busy ? `正在计算任务 ${job.id.slice(0, 8)} 的静态权益…` : data ? `任务 ${job.id.slice(0, 8)} · ${data.players.length} 位本桌玩家 · 金额权益模型` : "点击“计算本任务权益”读取此结果的配置。";
    const table = $("tournament-analysis-table"); table.replaceChildren(); $("analysis-baseline").textContent = "";
    if (!data) return;
    $("tournament-analysis-help").textContent = data.explanation;
    const key = $("analysis-kind").value;
    table.append(el("caption", "", key === "bubble_factors" ? "泡沫因子：行玩家对列玩家；对角线不适用。" : "风险溢价：行玩家对列玩家，单位为百分点；对角线不适用。"));
    const head = el("thead"), row = el("tr");
    row.append(el("th", "", "行 → 列")); data.players.forEach((name) => { const th = el("th", "", name); th.scope = "col"; row.append(th); }); head.append(row); table.append(head);
    const body = el("tbody");
    data.players.forEach((name, r) => {
      const tr = el("tr"), label = el("th", "", name); label.scope = "row"; tr.append(label);
      data.players.forEach((_, c) => {
        const value = data[key][r][c], pair = data.pairs.find((p) => p.row === r && p.column === c);
        const cell = el("td", "", Number.isFinite(value) ? value.toFixed(3) : key === "bubble_factors" && pair?.state === "infinite" ? "∞" : "—");
        cell.title = r === c ? "同一玩家，不适用" : `${name} 对 ${data.players[c]} · ${pair?.state === "undefined" ? "此权益状态无法定义比值" : key === "bubble_factors" ? "泡沫因子" : "风险溢价，百分点"}`;
        tr.append(cell);
      }); body.append(tr);
    }); table.append(body);
    $("analysis-baseline").textContent = `基准权益（奖金单位）：${data.players.map((name, i) => `${name} ${format(data.baseline_equities[i])}`).join(" · ")}。`;
  }
  async function loadTournamentAnalysis() {
    const job = state.job;
    if (!job || state.view !== "result" || state.analysisLoading === job.id) return;
    state.analysisLoading = job.id; $("analysis-error").hidden = true; renderTournamentAnalysis();
    try {
      const data = await api(`/api/jobs/${encodeURIComponent(job.id)}/tournament-analysis`, { timeoutMs: 120000 });
      state.analysisCache.set(job.id, data);
    } catch (error) { if (state.job?.id === job.id) { $("analysis-error").textContent = error.message; $("analysis-error").hidden = false; } }
    finally { if (state.analysisLoading === job.id) state.analysisLoading = null; renderTournamentAnalysis(); }
  }
  function policyError(message) { $("policy-error").textContent = message; $("policy-error").hidden = !message; }
  function policyLabels() { return state.node?.street === 0 ? state.node.policy_bucket_labels || [] : rangeLabels(); }
  function canLockBuckets() { return state.node?.street === 0 || [27, 31].includes(currentConfig()?.stores?.street_formats?.[state.node?.street]); }
  function blankPolicy(mode) {
    const node = state.node;
    if (mode === "locks") return { node_id: node.native_id, locks: node.actions.map(() => null) };
    if (mode === "frequency") return { node_id: node.native_id, frequency: { targets: node.actions.map(() => null), edges: node.actions.map(() => 0) } };
    return null;
  }
  function renderPolicy() {
    const node = state.node;
    if (!node || !state.meta?.training?.policies || !isNative(currentConfig())) return;
    const key = JSON.stringify([state.view, node.native_id, currentConfig()]);
    if (state.policyKey === key) return;
    state.policyKey = key;
    const saved = state.policyDrafts.get(key);
    state.policyWorking = clone(saved?.working || node.policy || null);
    state.policyMode = saved?.mode || (node.policy?.locks ? "locks" : node.policy?.frequency ? "frequency" : "none");
    $("policy-mode").value = state.policyMode;
    $("policy-summary").textContent = `节点 ${node.native_id} · ${saved ? "有未应用编辑" : node.policy?.locks ? "手牌行动锁" : node.policy?.frequency ? "整体频率目标" : "无约束"}`;
    $("policy-mode").querySelector('option[value="locks"]').disabled = !canLockBuckets();
    $("policy-lock-fill").textContent = `设置全部 ${policyLabels().length} ${node.street === 0 ? "手" : "桶"}`;
    const observed = node.strategy?.frequency;
    $("policy-observed").hidden = !observed;
    $("policy-observed").textContent = observed ? `训练累计权重整体频率：${node.actions.map((action, i) => `${actionLabel(action)} 实际 ${Number.isFinite(observed.aggregate?.[i]) ? (observed.aggregate[i] * 100).toFixed(3) + "%" : "—"} / 目标 ${Number.isFinite(observed.targets?.[i]) ? (observed.targets[i] * 100).toFixed(3) + "%" : "未约束"}`).join("；")}。与矩阵的均匀组合加权汇总口径不同。` : "";
    policyError(""); fillPolicyFields();
    if (saved?.mode === "json") $("policy-json").value = saved.json;
    if (saved?.mode === "frequency") saved.frequency.forEach(([target, edge], i) => { $(`policy-target-${i}`).value = target; $(`policy-edge-${i}`).value = edge; });
  }
  function rememberPolicyDraft() {
    if (!state.policyKey || !state.node) return;
    state.policyDrafts.set(state.policyKey, { mode: state.policyMode, working: clone(state.policyWorking), json: $("policy-json").value,
      frequency: state.policyMode === "frequency" ? state.node.actions.map((_, i) => [$(`policy-target-${i}`).value, $(`policy-edge-${i}`).value]) : [] });
    $("policy-summary").textContent = `节点 ${state.node.native_id} · 有未应用编辑`;
  }
  function fillPolicyFields() {
    const node = state.node; if (!node) return;
    const mode = state.policyMode;
    $("policy-frequency-fields").hidden = mode !== "frequency";
    $("policy-lock-fields").hidden = mode !== "locks";
    $("policy-json-field").hidden = mode !== "json";
    if (mode === "json") $("policy-json").value = JSON.stringify(state.policyWorking || blankPolicy("frequency"), null, 2);
    if (mode === "frequency") {
      const frequency = state.policyWorking?.frequency || blankPolicy("frequency").frequency;
      $("policy-frequency-rows").replaceChildren(...node.actions.map((action, i) => {
        const row = el("div", "field-grid policy-frequency-row");
        for (const [name, text, value] of [["target", `${actionLabel(action)}目标 %`, frequency.targets[i] == null ? "" : frequency.targets[i] * 100], ["edge", `EV 偏置 · ${utilityUnit()}`, frequency.edges?.[i] ?? 0]]) {
          const field = el("div", "field"), label = el("label", "", text), input = el("input");
          input.id = `policy-${name}-${i}`; input.type = "number"; input.step = "any"; input.value = value;
          if (name === "target") { input.min = 0; input.max = 100; input.placeholder = "不约束"; }
          label.htmlFor = input.id; field.append(label, input); row.append(field);
        }
        return row;
      }));
    }
    if (mode === "locks") {
      const previous = $("policy-lock-action").value;
      $("policy-lock-action").replaceChildren(...node.actions.map((action, i) => { const option = el("option", "", actionLabel(action)); option.value = i; option.disabled = !!node.special && i === 0; return option; }));
      $("policy-lock-action").value = previous && !(node.special && previous === "0") ? previous : node.special ? "1" : "0";
      if (!$("policy-lock-action").value) $("policy-lock-action").value = $("policy-lock-action").querySelector("option:not([disabled])")?.value || "0";
      $("policy-lock-hand").replaceChildren(...(node.street === 0 ? state.meta.hand_labels : policyLabels()).map((label) => { const option = el("option", "", label); option.value = label; return option; }));
      renderPolicyHand();
    }
  }
  function renderPolicyHand() {
    if (state.policyMode !== "locks" || !policyLabels().length) return;
    const action = Number($("policy-lock-action").value), label = state.selectedHand;
    $("policy-lock-hand").value = label;
    const bucket = policyLabels().indexOf(label);
    const values = state.policyWorking?.locks?.[action];
    $("policy-lock-value").value = values && bucket >= 0 ? values[bucket] * 100 : "";
    $("policy-lock-value").disabled = !values;
    $("policy-lock-update").disabled = !values;
    $("policy-lock-unlock").disabled = !values;
    const source = state.policySource;
    const canCopy = source?.node_id === state.node.native_id && source?.configKey === JSON.stringify(state.appliedConfig) && policyLabels().every((hand) => source.hands?.[hand]?.visits > 0 && Array.isArray(source.hands[hand].frequencies));
    $("policy-lock-source").disabled = !canCopy;
    const locked = state.policyWorking?.locks?.filter((row) => row != null).length || 0;
    $("policy-lock-status").textContent = `${locked} / ${state.node.actions.length} 个行动已有完整锁数组。${values ? `${label} 可单独修改，其他手牌保持现值。` : "先设置全部手牌或从原任务复制，再修改此牌。"}`;
  }
  function readPolicy(mode = state.policyMode) {
    if (mode === "none") return null;
    const node = state.node; let row;
    if (mode === "json") { try { row = JSON.parse($("policy-json").value); } catch { throw new Error("节点 JSON 语法无效；输入已保留。"); } }
    else if (mode === "frequency") {
      row = blankPolicy("frequency");
      node.actions.forEach((_, i) => {
        const raw = $(`policy-target-${i}`).value.trim(), edge = $(`policy-edge-${i}`).value.trim();
        row.frequency.targets[i] = raw ? Number(raw) / 100 : null;
        row.frequency.edges[i] = edge ? Number(edge) : 0;
      });
    } else row = clone(state.policyWorking || blankPolicy("locks"));
    if (!row || row.node_id !== node.native_id) throw new Error("JSON 必须使用当前节点的 node_id。");
    if (!!row.locks === !!row.frequency) throw new Error("每个节点只能设置 locks 或 frequency 其中一种约束。");
    const probability = (x) => typeof x === "number" && Number.isFinite(x) && x >= 0 && x <= 1;
    if (row.locks) {
      if (!canLockBuckets()) throw new Error("当前翻后记录方式不支持逐桶锁。请先选择平均策略记录并更新树，或改用整体频率目标。");
      if (row.locks.length !== node.actions.length || row.locks.some((values) => values !== null && (!Array.isArray(values) || values.length !== policyLabels().length || values.some((v) => !probability(v))))) throw new Error(`每个锁定行动必须有完整 ${policyLabels().length} 项、0–1 的概率数组。`);
      if (node.special && row.locks[0] !== null) throw new Error("可过牌节点的虚拟弃牌行动不能锁定。");
      for (let i = 0; i < policyLabels().length; i++) {
        const mass = row.locks.reduce((sum, values) => sum + (values?.[i] || 0), 0);
        if (mass > 1 + 1e-12 || (row.locks.every((values) => values !== null) && Math.abs(mass - 1) > 1e-12)) throw new Error(`${policyLabels()[i]} 的锁定频率不合法：总和不能超过 100%，全部行动锁定时须等于 100%。`);
      }
    } else {
      const targets = row.frequency.targets, edges = row.frequency.edges || node.actions.map(() => 0);
      if (!Array.isArray(targets) || targets.length !== node.actions.length || targets.some((x) => x !== null && !probability(x)) || targets.reduce((sum, x) => sum + (x || 0), 0) > 1 + 1e-12) throw new Error("频率目标按行动列出，总和不能超过 100%；未约束行动留空。");
      if (!Array.isArray(edges) || edges.length !== node.actions.length || edges.some((x) => typeof x !== "number" || !Number.isFinite(x) || Math.abs(x) > 1e12)) throw new Error("EV 偏置需按行动填写有限金额，绝对值不超过 10¹²。");
    }
    return row;
  }
  async function copyResultDraft() {
    if (!state.job || state.busy || state.loading) return;
    if (isImported(state.job.config)) { announce("原版存档参数已冻结；请使用 File → New 创建独立场景。"); return; }
    const config = clone(state.job.config), path = [...state.path], labels = [...state.labels];
    state.policySource = { node_id: state.node?.native_id, hands: clone(state.node?.strategy?.hands || {}), configKey: JSON.stringify(config) };
    state.appliedConfig = clone(config); setConfig(config); state.draftDirty = false; state.formEdited = true; state.view = "draft";
    state.policyKey = null; renderContext(); await loadNode(path, labels);
    announce("已用所选任务创建新草稿；原任务保持不变，修改约束后需开始新训练。");
  }
  async function applyPolicy(remove = false) {
    if (state.busy || state.loading || state.view !== "draft" || state.draftDirty || !state.node || isImported(currentConfig())) return;
    policyError(""); let row;
    try { row = remove ? null : readPolicy(); } catch (error) { policyError(error.message); return; }
    const config = readConfig(); if (!config) return;
    const nodeId = state.node.native_id, path = [...state.path], labels = [...state.labels];
    const rows = (config.policies?.nodes || []).filter((r) => r.node_id !== nodeId);
    if (row) rows.push(row);
    config.policies = { version: 1, nodes: rows };
    state.busy = true; updateControls();
    try {
      const node = await api("/api/tree", { method: "POST", body: JSON.stringify({ config, path }) });
      state.policyDrafts.delete(state.policyKey);
      state.nodeController?.abort(); state.requestId += 1;
      state.appliedConfig = clone(config); setConfig(config); state.formEdited = true; state.draftDirty = false;
      state.node = node; state.path = path; state.labels = labels; state.policyKey = null;
      renderContext(); renderNode(); announce(row ? "节点约束已应用到草稿；开始新训练后生效。" : "已移除此节点约束，其他节点保持不变。");
    } catch (error) { policyError(error.message); }
    finally { state.busy = false; updateControls(); }
  }
  async function applyTree() {
    if (state.busy || state.loading || isImported(state.formBaseConfig)) return false;
    const config = readConfig();
    if (!config) return false;
    state.busy = true; updateControls();
    try {
      const node = await api("/api/tree", { method: "POST", body: JSON.stringify({ config, path: [] }) });
      state.nodeController?.abort(); state.requestId += 1;
      state.appliedConfig = clone(config); state.view = "draft"; state.draftDirty = false;
      state.path = []; state.labels = []; state.node = node;
      renderContext(); renderNode();
      announce("决策树已更新，可以选择行动继续探索。"); return true;
    } catch (error) { formError(error.message); return false; }
    finally { state.busy = false; updateControls(); }
  }
  function upsertJob(job) {
    const index = state.jobs.findIndex((item) => item.id === job.id);
    if (index >= 0) state.jobs[index] = job;
    else state.jobs.unshift(job);
    state.jobs = state.jobs.slice(0, 100);
  }
  async function refreshJobs() {
    const response = await api("/api/jobs");
    state.jobs = response.jobs || [];
    const active = state.jobs.find(isRunning);
    state.activeId = active?.id || null;
    if (state.job) {
      const existing = state.jobs.find((job) => job.id === state.job.id);
      if (existing) state.job = existing;
      else {
        state.job = active || state.jobs[0] || null;
        state.path = [];
        state.labels = [];
        if (!state.job) state.view = "draft";
      }
    }
    renderHistory();
    updateControls();
    return response;
  }
  async function startSolve(configOverride = null) {
    if (state.busy || state.activeId || isImported(configOverride || state.formBaseConfig)) return false;
    const config = configOverride ? clone(configOverride) : readConfig();
    if (!config) return false;
    state.samplingError = null;
    state.busy = true;
    updateControls();
    try {
      const job = await api("/api/jobs", { method: "POST", body: JSON.stringify({ config }) });
      state.job = job;
      state.activeId = isRunning(job) ? job.id : null;
      state.appliedConfig = clone(job.config);
      state.draftDirty = false;
      state.formEdited = false;
      state.view = "result";
      upsertJob(job);
      resetNode();
      renderJob();
      renderContext();
      await loadNode([], []);
      announce(config.sampling_stage === "initialization" ? "正在初始化手牌；完成后点击 Run 开始正式计算。" : "计算任务已启动，完成后会自动加载策略。");
      schedulePoll();
      return true;
    } catch (error) {
      state.samplingError = error.message;
      formError(error.message);
      // A lost creation response may still have created a job. Reconcile before another start.
      try {
        await refreshJobs();
        const active = state.jobs.find(isRunning);
        if (active) {
          state.job = active;
          renderJob();
          schedulePoll();
        }
      } catch { showConnection("无法确认任务是否已启动，请重新连接后查看任务状态。"); }
      return false;
    } finally { state.busy = false; updateControls(); }
  }
  async function initializeHand() {
    const config = clone(state.appliedConfig);
    if (!isNative(config)) return true;
    if (!state.meta?.training?.sampling_dialog) { formError("当前服务不支持手牌初始化，请连接新版采样服务后重试。"); return false; }
    for (const key of ["target_ci", "stop_after_seconds", "hard_seconds"]) delete config[key];
    Object.assign(config, { iterations: Number(state.meta.training.initialization_samples || 10000000), stopping_mode: "samples", sampling_scope: "entire_tree", sampling_path: [], sampling_stage: "initialization", track_ci: false });
    return startSolve(config);
  }
  async function submitSampling(context, options) {
    state.samplingError = null;
    if (!state.meta?.training?.sampling_dialog || state.busy || state.activeId) { state.samplingError = "当前服务尚不可开始采样，或已有计算正在运行。"; return false; }
    if (context.jobId) {
      if (state.view !== "result" || state.job?.id !== context.jobId || !state.job.can_resume) { state.samplingError = "当前手牌已变更，请关闭窗口后重新打开 Run。"; return false; }
      return resumeJob(options, context.jobId);
    }
    if (state.view !== "draft" || state.draftDirty || JSON.stringify(state.appliedConfig) !== JSON.stringify(context.config)) { state.samplingError = "当前手牌已变更，请先更新决策树再打开 Run。"; return false; }
    const config = clone(context.config);
    for (const key of ["target_ci", "stop_after_seconds", "hard_seconds", "iterations"]) delete config[key];
    Object.assign(config, options); delete config.reset_regret; delete config.reset_average;
    if (config.hard_seconds == null) delete config.hard_seconds;
    return startSolve(config);
  }
  function schedulePoll() {
    clearTimeout(state.pollTimer);
    if (state.activeId) state.pollTimer = setTimeout(pollJob, POLL_MS);
  }
  async function pollJob() {
    const id = state.activeId;
    if (!id || state.pollInFlight) return;
    state.pollInFlight = true;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (id !== state.activeId) return;
      state.pollFailures = 0;
      upsertJob(job);
      if (state.job?.id === id) state.job = job;
      if (!isRunning(job)) {
        state.activeId = null;
        if (state.view === "result" && state.job?.id === id) await loadNode(state.path, state.labels);
        announce(job.status === "completed" ? job.config.sampling_stage === "initialization" ? "手牌已初始化，点击 Run 开始正式计算。" : job.summary?.precision_target_reached ? "已达到设定的 CI 目标。" : "计算已结束，请查看停止原因。" : job.status === "cancelled" ? "求解已停止，已有样本已保留。" : "求解未完成，请查看任务错误。");
      }
      clearConnection();
      renderJob();
      renderContext();
      schedulePoll();
    } catch (error) {
      if (id !== state.activeId) return;
      state.pollFailures += 1;
      showConnection(`${error.message} 当前任务状态待确认。`);
      if (state.pollFailures < 4) state.pollTimer = setTimeout(pollJob, Math.min(10000, POLL_MS * 2 ** state.pollFailures));
    } finally { state.pollInFlight = false; }
  }
  async function cancelJob() {
    if (!state.job || !isRunning(state.job) || state.job.status === "cancelling") return;
    const id = state.job.id;
    $("cancel-job").disabled = true;
    $("cancel-job").setAttribute("aria-busy", "true");
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" });
      upsertJob(job);
      if (state.job?.id === id) state.job = job;
      renderJob();
      schedulePoll();
      announce("已请求停止，正在等待当前计算结束。");
    } catch (error) {
      $("job-error").textContent = error.message;
      $("job-error").hidden = false;
      $("cancel-job").disabled = false;
    } finally { $("cancel-job").setAttribute("aria-busy", "false"); }
  }
  async function resumeJob(overrides = null, sourceId = null) {
    const source = state.job;
    if (!source?.can_resume || state.busy || state.activeId || (sourceId && source.id !== sourceId)) return false;
    state.samplingError = null;
    let options;
    if (overrides) options = clone(overrides);
    else {
    const input = $("resume-target");
    $("resume-target-error")?.remove();
    input.removeAttribute("aria-invalid"); input.setAttribute("aria-describedby", "resume-help");
    const target = Number(input.value.trim());
    const completed = Number(source.summary?.iterations_completed || 0);
    if (!input.value.trim() || !Number.isInteger(target) || target <= completed || target > sampleLimit()) {
      showFieldError("resume-target", `累计目标需大于已完成的 ${formatInt(completed)}，且不超过 ${formatInt(sampleLimit())}。`); input.focus(); return;
    }
    const threads = Number($("resume-threads").value.trim());
    if (!$("resume-threads").value.trim() || !Number.isInteger(threads) || threads < 1 || threads > 32) {
      showFieldError("resume-threads", "计算线程数需为 1–32 的整数。"); $("resume-threads").focus(); return;
    }
    $("resume-threads-error")?.remove(); $("resume-threads").removeAttribute("aria-invalid");
    $("resume-threads").setAttribute("aria-describedby", "resume-thread-help");
    options = { iterations: target, threads };
    }
    state.busy = true; updateControls();
    try {
      if (!overrides && !isImported(source.config) && $("resume-use-draft").checked && state.meta.training?.checkpoint_migration) {
        if (state.draftDirty) throw new Error("请先更新决策树，确认左侧配置和节点约束后再迁移检查点。");
        const config = readConfig(); if (!config) throw new Error("左侧草稿包含无效字段，迁移尚未开始。");
        options.config = { ...config, iterations: options.iterations };
        options.checkpoint_migration = $("checkpoint-migration").value;
      }
      if (!overrides && state.meta.training?.reset_regret) options.reset_regret = $("reset-regret").checked;
      if (!overrides && state.meta.training?.reset_average) options.reset_average = $("reset-average").checked;
      const job = await api(`/api/jobs/${encodeURIComponent(source.id)}/resume`, { method: "POST", body: JSON.stringify(options) });
      state.job = job; state.activeId = isRunning(job) ? job.id : null; state.view = "result";
      upsertJob(job); renderJob(); renderContext(); await loadNode(state.path, state.labels);
      announce("已从检查点创建续跑任务，原任务与左侧草稿均已保留。"); schedulePoll();
      return true;
    } catch (error) {
      state.samplingError = error.message;
      $("job-error").textContent = error.message; $("job-error").hidden = false;
      try {
        await refreshJobs();
        if (state.activeId) { const active = state.jobs.find((job) => job.id === state.activeId); if (active) state.job = active; renderJob(); schedulePoll(); }
      } catch { showConnection("无法确认续跑是否已启动，请重新连接后查看任务状态。"); }
      return false;
    } finally { state.busy = false; updateControls(); }
  }
  function renderHistory() {
    const select = $("job-history");
    const selectedId = state.job?.id;
    const names = { running: "运行中", cancelling: "停止中", completed: "已完成", cancelled: "已停止", failed: "失败" };
    select.replaceChildren(...state.jobs.map((job) => {
      const option = el("option", "", `${job.id.slice(0, 8)} · ${configSummary(job.config)} · ${names[job.status] || job.status}`);
      option.value = job.id;
      return option;
    }));
    if (selectedId) select.value = selectedId;
    $("job-history-wrap").hidden = state.jobs.length < 2;
  }
  function renderJob() {
    const job = state.job;
    const status = job?.status || "idle";
    const titles = { idle: "准备好探索这个局面", running: "正在训练行动策略", cancelling: "正在停止求解", completed: "本次抽样训练已完成", cancelled: "已停止，保留已有样本", failed: hasResult(job) ? "达到资源上限，已保留部分结果" : "本次求解未完成" };
    const statusLabels = { idle: "尚未求解", running: "运行中", cancelling: "停止中", completed: "已完成", cancelled: "部分结果", failed: "失败" };
    $("job-title").textContent = titles[status] || "求解任务";
    $("job-state").textContent = statusLabels[status] || status;
    $("job-state").className = `status-pill is-${status}`;
    $("job-detail").textContent = !job ? "先检查行动路径，再开始抽样训练。" : status === "running" ? `种子 ${job.config.seed} · ${configSummary(job.config)} · 完成后自动加载频率` : status === "cancelling" ? "等待当前计算结束；实际状态以服务返回为准。" : status === "completed" ? `种子 ${job.config.seed} · 轮数完成不代表达到均衡，请检查节点与手牌样本数。` : status === "cancelled" ? job.can_resume ? "部分样本可查看、导出或从检查点继续训练。" : "部分样本可以继续查看和导出；增加训练轮数需新建任务。" : "场景输入已保留，可以修改后重新开始。";
    const iteration = Number(isRunning(job) ? job?.progress?.iteration ?? job?.summary?.iterations_completed ?? 0 : job?.summary?.iterations_completed ?? job?.progress?.iteration ?? 0);
    const total = Number(isRunning(job) ? job?.progress?.total ?? job?.config?.iterations ?? job?.summary?.iterations_requested ?? 0 : job?.summary?.iterations_requested ?? job?.progress?.total ?? job?.config?.iterations ?? 0);
    const sampling = window.PreflopDesktop?.samplingProgress(job);
    const importedHistory = sourceHistory(job);
    if (job?.has_source_strategy && iteration === 0 && !isRunning(job)) {
      $("job-title").textContent = "原版存档策略已载入";
      $("job-state").textContent = "已载入";
      $("job-detail").textContent = job.can_resume ? "已保存策略可查看、导出或在原树上继续训练。" : "已保存策略可查看和导出；此存档暂不支持训练。";
    }
    $("job-progress").hidden = !!sampling?.hideProgress;
    $("job-progress").max = sampling?.max ?? Math.max(1, total);
    if (sampling?.indeterminate) $("job-progress").removeAttribute("value");
    else $("job-progress").value = sampling?.value ?? Math.min(iteration, Math.max(1, total));
    $("job-progress").setAttribute("aria-label", sampling?.mode === "ci" ? sampling.indeterminate ? "计算进行中，当前没有可用的 CI 进度估计" : "基于 CI 的启发式进度估计，不是均衡误差百分比" : "求解进度");
    $("progress-label").textContent = sampling?.label ?? `${importedHistory?.history_unknown ? "新增 " : ""}${formatInt(iteration)} / ${formatInt(total)}`;
    $("sampling-status-note").hidden = !job || !isNative(job.config);
    $("sampling-status-note").textContent = sampling?.detail || "";
    $("hrcz-source-note").hidden = !importedHistory;
    if (importedHistory) {
      const counter = importedHistory.source_saved_counter;
      const unsupported = (importedHistory.unsupported || []).map((item) => typeof item === "string" ? item : item.message || JSON.stringify(item)).join("；");
      $("hrcz-source-note").textContent = `原档更新计数 ${counter == null ? "未知" : String(counter)}（不是可还原的总采样数）；导入后累计新增 ${formatInt(iteration)} 个样本。原档逐手采样历史与原随机状态未知；首次续跑从种子 ${job.config.seed} 开始，保留原更新时钟的算法权重。${importedHistory.training_supported === false ? ` 当前只读${unsupported ? `：${unsupported}` : "。"}` : ""}`;
    }
    const seconds = Number(job?.elapsed_seconds || 0);
    $("elapsed").textContent = job ? seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s` : `${seconds.toFixed(1)}s` : "—";
    $("cancel-job").hidden = !isRunning(job);
    $("cancel-job").disabled = status === "cancelling";
    $("cancel-job").textContent = status === "cancelling" ? "正在停止…" : "停止求解";
    $("export-result").disabled = !hasResult(job);
    const evaluation = job?.summary?.evaluation;
    $("evaluation-note").hidden = !evaluation;
    $("evaluation-note").textContent = evaluation ? `自博弈评价：${formatInt(evaluation.samples)} 次采样；${formatInt(evaluation.untrained_fallback_decisions)} / ${formatInt(evaluation.decisions)} 次决策使用未训练时的均匀策略回退。该评价不是可利用度或均衡证明。` : "";
    const comparison = job?.summary?.comparison;
    if (comparison && isNative(job.config)) {
      $("evaluation-note").hidden = false;
      const evError = job.config.utility === "chips" ? comparison.relative_ev_mae_bb ?? comparison.relative_ev_mae : comparison.relative_ev_mae;
      $("evaluation-note").textContent = `根节点对照：组合加权频率平均误差 ${format(comparison.frequency_mae_pp)} 个百分点；相对 EV 平均误差 ${format(evError)} ${utilityUnit(job.config)}。覆盖 ${comparison.covered_combos} / 1326 组合。不同策略环境的 EV 差不是损失或可利用度；根节点误差不代表下游节点。`;
    }
    if (isRunning(job) && job.progress?.message) $("job-detail").textContent = job.progress.message;
    else if (isRunning(job) && job.progress?.samples_per_second) $("job-detail").textContent += ` · ${formatInt(job.progress.samples_per_second)} 样本/秒`;
    const stopReason = job?.summary?.stop_reason;
    const stopNames = { sample_target: "达到采样目标", time_target: "达到时间目标", ci_target: "达到策略漂移目标", sample_cap: "达到采样硬上限", hard_time: "达到最长运行时间", cancelled: "用户停止" };
    if (stopReason && !isRunning(job)) $("job-detail").textContent += ` · ${stopNames[stopReason] || stopReason}${job.summary.target_reached === false ? "，目标未达成" : ""}`;
    if (job?.config?.sampling_stage === "initialization") {
      $("job-title").textContent = isRunning(job) ? "正在初始化手牌" : job.status === "completed" && stopReason === "sample_target" ? "手牌已初始化" : "手牌初始化尚未完成";
      $("job-detail").textContent = job.status === "completed" && stopReason === "sample_target" ? "点击绿色 Run 开始正式计算（默认 CI Target 10）。初始化完成不代表已达到精度目标。" : `自动全树初始化 ${formatInt(total)} 次采样；完成后可使用 Run 进行正式计算。${!isRunning(job) ? ` ${stopNames[stopReason] || "未完成"}，已保留可用策略。` : ""}`;
    } else if (sampling?.mode === "ci" && !isRunning(job) && job && !(job.has_source_strategy && iteration === 0)) {
      $("job-title").textContent = job.summary?.precision_target_reached === true ? "已达到设定的 CI 目标" : "计算已停止，CI 目标未达成";
      $("job-detail").textContent = `${stopNames[stopReason] || "请查看任务状态"}。CI 描述近期策略漂移，不是均衡证明。`;
    }
    if (job && isNative(job.config)) $("job-detail").textContent += ` · ${job.summary?.training_threads ?? job.config.threads ?? 1} 线程`;
    const ci = isRunning(job) ? job?.progress?.ci || job?.summary?.ci : job?.summary?.ci || job?.progress?.ci;
    $("ci-note").hidden = !job?.config?.track_ci;
    $("ci-note").textContent = Number.isFinite(ci?.value) ? `策略漂移 CI ${ci.value.toFixed(5)}${sampling?.mode === "ci" ? ` / 目标 ${format(job.config.target_ci)}` : ""} · ${formatInt(ci.selected_nodes)} 个节点 · ${formatInt(ci.history?.length || 0)} 条记录。它描述近期策略变化，不是统计置信区间或可利用度。` : "已启用策略漂移记录；当前没有足够的时间窗口生成 CI。此处不以样本数量推算精度。";
    $("job-error").hidden = !job?.error;
    $("job-error").textContent = job?.error || "";
    $("resume-panel").hidden = !job?.can_resume;
    if (job?.can_resume && state.resumeJobId !== job.id) {
      state.resumeJobId = job.id;
      $("resume-target").value = Math.min(sampleLimit(), iteration + Math.max(100, iteration));
      $("resume-threads").value = job.config.threads ?? 4;
      $("resume-threads-error")?.remove(); $("resume-threads").removeAttribute("aria-invalid");
      $("resume-threads").setAttribute("aria-describedby", "resume-thread-help");
      $("reset-regret").checked = false; $("reset-average").checked = false;
      $("resume-use-draft").checked = false; $("checkpoint-migration").value = "reject";
      $("resume-target").min = iteration + 1;
      $("resume-target-error")?.remove(); $("resume-target").removeAttribute("aria-invalid");
      $("resume-target").setAttribute("aria-describedby", "resume-help");
    }
    $("resume-help").textContent = iteration >= sampleLimit() ? `本任务已达到当前 ${formatInt(sampleLimit())} 次上限。原始结果与检查点仍保留。` : `从任务 ${job?.id?.slice(0, 8) || "—"} 已完成的 ${formatInt(iteration)} 次继续；目标为累计次数。保留原结果并创建新任务。${$("resume-use-draft").checked ? "将使用左侧已应用配置，并按所选规则迁移检查点。" : "沿用所选任务的配置，不使用左侧草稿。"}`;
    if (importedHistory?.history_unknown && iteration < sampleLimit()) $("resume-help").textContent = `目标仅累计导入后的新增样本，当前 ${formatInt(iteration)} 次；原档更新计数不计入此目标。沿用原树与模型，新建续跑任务并保留原结果。首次续跑使用种子 ${job.config.seed}，不恢复原版未保存的随机状态。`;
    renderHistory();
    updateControls();
    desktop?.render();
  }
  async function switchView(view) {
    if (state.busy || state.view === view || (view === "result" && !state.job)) return;
    if (view === "draft" && isImported(state.appliedConfig)) { announce("原版存档保持只读场景；请使用 File → New 新建。"); return; }
    state.view = view;
    resetNode();
    renderContext();
    await loadNode([], []);
  }
  function download(filename, text, type) {
    const blob = new Blob([text], { type });
    const url = URL.createObjectURL(blob);
    const link = el("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function exportConfig() {
    const config = readConfig();
    if (!config) return;
    download("preflop-scenario.json", JSON.stringify(config, null, 2), "application/json;charset=utf-8");
    state.formEdited = false;
    announce("场景已导出为 JSON。");
  }
  async function importConfig(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > 512 * 1024) { formError("场景文件不能超过 512 KB。"); return; }
    state.busy = true;
    updateControls();
    try {
      const parsed = JSON.parse(await file.text());
      const config = parsed.config || parsed;
      if (isImported(config)) throw new Error("原版场景 JSON 不含完整原树与存储数据；请使用 Load Hand 导入 .hrcz 存档。");
      if (!config || !Array.isArray(config.players) || config.players.length < 2 || config.players.length > (isNative(config) ? 10 : 6)) throw new Error("简化模型支持 2–6 人；原生模型支持 2–10 人。");
      if (isCustomNative(config) && !state.meta.custom_native) throw new Error("当前服务尚未提供自定义原生四街树，请连接支持该模式的服务。");
      const normalized = { ...clone(isCustomNative(config) ? state.meta.custom_native.default_config : state.meta.default_config), ...config };
      const node = await api("/api/tree", { method: "POST", body: JSON.stringify({ config: normalized, path: [] }) });
      state.nodeController?.abort();
      state.requestId += 1;
      state.loading = false;
      document.querySelector(".tree-panel").classList.remove("is-loading");
      document.querySelector(".tree-panel").setAttribute("aria-busy", "false");
      state.appliedConfig = clone(normalized);
      setConfig(normalized);
      $("preset").value = presetValue(config);
      state.view = "draft";
      state.path = [];
      state.labels = [];
      state.node = node;
      state.draftDirty = false;
      state.formEdited = false;
      renderContext();
      renderNode();
      announce("场景已导入，决策树已更新。");
    } catch (error) { formError(error instanceof SyntaxError ? "文件不是有效 JSON，请选择导出的场景文件。" : error.message); }
    finally { state.busy = false; updateControls(); }
  }
  function exportCsv() {
    if (!state.node?.strategy) return;
    const quote = (value) => `"${String(value).replaceAll('"', '""')}"`;
    const actions = strategyActions();
    const rows = [["hand", sourceHistory()?.history_unknown ? "visits_after_import" : "visits", "has_saved_policy", ...actions.map(actionLabel)]];
    rangeLabels().forEach((label) => {
      const hand = trainedHand(label);
      rows.push([label, hand?.visits ?? "", hand?.has_saved_policy === true, ...actions.map((_, index) => hand ? hand.frequencies[index] : "")]);
    });
    download(`preflop-${state.node.actor_name || "node"}-range.csv`, "\uFEFF" + rows.map((row) => row.map(quote).join(",")).join("\r\n"), "text/csv;charset=utf-8");
    announce("当前节点策略已导出；空白访问数表示未知，空白频率表示无策略数据。");
  }
  async function exportResult() {
    if (!hasResult(state.job)) return;
    const job = state.job;
    $("export-result").disabled = true;
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(job.id)}/export`);
      download(`preflop-${job.id.slice(0, 8)}.json`, JSON.stringify(result, null, 2), "application/json;charset=utf-8");
      announce(isImported(job.config) ? "根节点与任务摘要已导出；完整原档数据请导出 .hrcz。" : isNative(job.config) ? "根节点与任务摘要已导出；所有节点保存在本机检查点。" : job.status === "completed" ? "完整求解结果已导出。" : "部分求解结果已导出。");
    } catch (error) { $("job-error").textContent = error.message; $("job-error").hidden = false; }
    finally { $("export-result").disabled = !hasResult(state.job); }
  }
  async function exportArchive() {
    if (!state.meta?.persistence?.archive_export || !state.job?.can_export_archive || state.archiveBusy) return;
    const job = state.job;
    const resources = $("archive-resources").checked ? "1" : "0";
    state.archiveBusy = true; $("archive-error").hidden = true; updateControls();
    $("archive-status").textContent = "正在检查所选任务的存档状态…";
    try {
      const current = await api(`/api/jobs/${encodeURIComponent(job.id)}`);
      if (!current.can_export_archive) throw new Error("此任务尚无可导出的完整检查点。");
      const link = el("a");
      link.href = `/api/jobs/${encodeURIComponent(job.id)}/archive?resources=${resources}`;
      link.download = `preflop-${job.id.slice(0, 8)}.plabz`;
      document.body.append(link); link.click(); link.remove();
      $("archive-status").textContent = `任务 ${job.id.slice(0, 8)} 的完整存档下载已发起；请在浏览器下载记录中确认完成。`;
      announce("完整存档下载已发起。");
    } catch (error) { $("archive-status").textContent = ""; $("archive-error").textContent = error.message; $("archive-error").hidden = false; }
    finally { state.archiveBusy = false; updateControls(); }
  }
  async function exportHrcz() {
    if (!state.meta?.persistence?.hrcz_export || !state.job?.can_export_hrcz || state.archiveBusy) return;
    const job = state.job;
    desktop?.showTab("bottom", "hrc-archive-pane");
    state.archiveBusy = true; $("archive-error").hidden = true; updateControls();
    $("archive-status").textContent = "正在检查所选任务的 .hrcz 导出状态…";
    try {
      const current = await api(`/api/jobs/${encodeURIComponent(job.id)}`);
      if (!current.can_export_hrcz) throw new Error("此任务当前无法导出 .hrcz 存档。");
      const link = el("a");
      link.href = `/api/jobs/${encodeURIComponent(job.id)}/hrcz`;
      link.download = `preflop-${job.id.slice(0, 8)}.hrcz`;
      document.body.append(link); link.click(); link.remove();
      $("archive-status").textContent = `任务 ${job.id.slice(0, 8)} 的 .hrcz 下载已发起；请在浏览器下载记录中确认完成。`;
      announce(".hrcz 存档下载已发起。");
    } catch (error) { $("archive-status").textContent = ""; $("archive-error").textContent = error.message; $("archive-error").hidden = false; }
    finally { state.archiveBusy = false; updateControls(); }
  }
  async function importArchive(event) {
    const file = event.target.files?.[0]; event.target.value = "";
    const persistence = state.meta?.persistence;
    if (!file || !(persistence?.archive_import || persistence?.hrcz_import) || state.archiveBusy || state.busy || state.activeId) return;
    desktop?.showTab("bottom", "hrc-archive-pane");
    $("archive-error").hidden = true;
    const maxBytes = persistence.max_import_bytes || 1024 * 1024 * 1024;
    const hrcz = /\.hrcz$/i.test(file.name);
    if (!file.size || file.size > maxBytes || !/\.(plabz|hrcz)$/i.test(file.name)) {
      $("archive-error").textContent = `请选择非空 .hrcz 或 .plabz 文件，最大 ${formatInt(maxBytes / 1024 / 1024)} MiB。`;
      $("archive-error").hidden = false; return;
    }
    if (hrcz ? !persistence.hrcz_import : !persistence.archive_import) {
      $("archive-error").textContent = `当前服务尚未提供 ${hrcz ? ".hrcz" : ".plabz"} 导入。`;
      $("archive-error").hidden = false; return;
    }
    state.busy = true; state.archiveBusy = true; updateControls();
    $("archive-status").textContent = `正在导入 ${file.name}（${format(file.size / 1024 / 1024)} MiB），校验文件并载入保存的数据…`;
    try {
      const job = await api("/api/import", { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file, timeoutMs: 300000 });
      if (desktop && !isImported(state.formBaseConfig)) desktop.savedDraft = {
        config: { ...clone(state.formBaseConfig), players: collectPlayers() }, applied: clone(state.appliedConfig), dirty: state.draftDirty, edited: state.formEdited,
        inputs: [...$("scenario-form").querySelectorAll("input[id],select[id],textarea[id]")].filter((field) => field.type !== "file").map((field) => ({ id: field.id, value: field.value, checked: field.type === "checkbox" ? field.checked : undefined })),
        draftState: Object.fromEntries(["treeSettingsDraft", "treeEditorMode", "treePolicyDrafts", "policyTopologyDirty", "policySource"].map((key) => [key, clone(state[key])])),
      };
      state.job = job;
      state.jobs = [job, ...state.jobs.filter((item) => item.id !== job.id)].slice(0, 100);
      state.view = "result";
      if (isImported(job.config)) {
        setConfig(job.config); state.appliedConfig = clone(job.config); state.draftDirty = false; state.formEdited = false;
      }
      resetNode(); renderContext(); renderJob();
      await loadNode([], []);
      $("archive-status").textContent = `已新增任务 ${job.id.slice(0, 8)}。${isImported(job.config) ? "当前显示冻结的原档参数；已有草稿可从 Hand 标签恢复。" : "原任务和左侧草稿保持不变。"}`;
      announce(job.can_resume ? "存档已导入，可查看策略或在原树上继续训练。" : "存档已导入，可查看与导出已保存的数据；当前不支持续跑。");
    } catch (error) {
      $("archive-status").textContent = "";
      $("archive-error").textContent = `${error.message} 若连接在恢复期间中断，请先重新连接并检查任务历史，再决定是否再次导入。`;
      $("archive-error").hidden = false;
    } finally { state.busy = false; state.archiveBusy = false; updateControls(); }
  }
  function applyPreset(kind) {
    if (!state.meta) return;
    if (kind === "custom-native" && state.meta.custom_native) {
      setConfig(clone(state.meta.custom_native.default_config)); markEdited();
      announce("自定义原生四街树已填入；可编辑筹码、盲注、树参数与收益模型。"); return;
    }
    const standalone = state.meta.custom_native?.scenario_presets?.find((row) => `setup-${row.id}` === kind);
    if (standalone) {
      setConfig(clone(standalone.config)); markEdited(); $("preset").value = kind;
      announce(`${standalone.title}已填入；可直接建树，无需导入存档。`); return;
    }
    const tournamentPreset = state.meta.tournament?.presets?.find((p) => `tournament-${p.id}` === kind);
    if (tournamentPreset) {
      setConfig(clone(tournamentPreset.config)); markEdited();
      announce("锦标赛预设已填入；可设置奖金、外桌筹码和赏金。"); return;
    }
    const researchPreset = state.meta.research?.presets.find((p) => `research-${p.id}` === kind);
    if (researchPreset) {
      setConfig(clone(researchPreset.config)); markEdited();
      announce("固定对照预设已填入；可以修改采样次数与种子。"); return;
    }
    const config = clone(state.meta.default_config);
    if (kind === "default") {
      // Switching back from a fixed research scenario restores editable defaults.
    } else if (kind === "heads-up") {
      config.players = [{ name: "BTN/SB", stack: 10, range: "all" }, { name: "BB", stack: 10, range: "all" }];
      config.utility = "chips";
      config.payouts = [1, 0];
      config.iterations = 1000;
    } else if (kind === "bubble") {
      config.players = [{ name: "BTN", stack: 15, range: "all" }, { name: "SB", stack: 10, range: "all" }, { name: "BB", stack: 5, range: "all" }];
      config.utility = "icm";
      config.payouts = [65, 35, 0];
      config.iterations = 1000;
    } else {
      config.players = ["UTG", "HJ", "CO", "BTN", "SB", "BB"].map((name) => ({ name, stack: 20, range: "all" }));
      config.utility = "chips";
      config.payouts = [50, 30, 20, 0, 0, 0];
      config.iterations = 300;
    }
    setConfig(config);
    markEdited();
    $("preset").value = kind;
    announce("预设已填入；点击“更新决策树”应用。");
  }
  function renderMeta() {
    const config = currentConfig();
    const model = (isImported(config) ? state.meta.imported?.model : isCustomNative(config) ? state.meta.custom_native?.model : isTournament(config) ? state.meta.tournament?.model : isResearch(config) ? state.meta.research.model : state.meta.model) || state.meta.model;
    $("model-title").textContent = model.title;
    $("model-continuation").textContent = model.continuation + ((isTournament(config) || usesChipUnits(config)) ? ` 当前结果单位：${utilityUnit(config)}；${config.utility === "mtt_icm" ? `含 ${(config.other_stacks || []).length} 位外桌玩家` : config.utility === "chips" ? "筹码收益" : "仅本桌 ICM"}；${!config.bounty?.mode || config.bounty.mode === "none" ? "无赏金" : `${config.bounty.mode.toUpperCase()} 赏金`}。` : "");
    $("model-limitations").replaceChildren(...(model.limitations || []).map((text) => el("li", "", text)));
    $("evidence-links").replaceChildren(...(state.meta.evidence || []).map((evidence) => {
      const row = el("div");
      try {
        const url = new URL(evidence.url);
        if (!["http:", "https:"].includes(url.protocol)) return row;
        const link = el("a", "", `${evidence.title} ↗`);
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        row.append(link, el("span", "evidence-note", evidence.note || ""));
      } catch { row.textContent = evidence.title; }
      return row;
    }));
  }
  async function connect() {
    $("retry-connect").disabled = true;
    try {
      const meta = await api("/api/meta");
      state.meta = meta;
      $("preset").querySelectorAll("option[data-custom-native]").forEach((option) => option.remove());
      if (meta.custom_native) {
        const option = el("option", "", "自定义原生四街树 · 2–10 人"); option.value = "custom-native"; option.dataset.customNative = "true";
        $("preset").append(option);
      }
      $("preset").querySelectorAll("optgroup[data-standalone]").forEach((group) => group.remove());
      if (meta.custom_native?.scenario_presets?.length) {
        const group = el("optgroup"); group.label = "内置手牌设置 · 可编辑"; group.dataset.standalone = "true";
        for (const row of meta.custom_native.scenario_presets) {
          const option = el("option", "", row.title); option.value = `setup-${row.id}`; group.append(option);
        }
        $("preset").append(group);
      }
      syncPreflopPreset();
      $("preset").querySelectorAll("option[data-research]").forEach((option) => option.remove());
      (meta.research?.presets || []).forEach((p) => {
        const option = el("option", "", p.title); option.value = `research-${p.id}`;
        option.dataset.research = "true"; option.disabled = !p.available; $("preset").append(option);
      });
      $("preset").querySelectorAll("optgroup[data-tournament]").forEach((group) => group.remove());
      if (meta.tournament?.presets?.length) {
        const group = el("optgroup"); group.label = "锦标赛研究 · 固定行动树"; group.dataset.tournament = "true";
        meta.tournament.presets.forEach((p) => {
          const option = el("option", "", p.title); option.value = `tournament-${p.id}`;
          option.disabled = p.available === false; group.append(option);
        });
        $("preset").append(group);
      }
      renderMeta();
      if (!state.initialized) {
        state.appliedConfig = clone(meta.default_config);
        setConfig(meta.default_config);
        renderRange();
      }
      await refreshJobs();
      if (!state.initialized) {
        const requestedJob = new URLSearchParams(window.location.search).get("job");
        state.job = state.jobs.find((job) => job.id === requestedJob) || state.jobs.find(isRunning) || state.jobs[0] || null;
        // A reload recovers available work, but never silently changes the editable scenario.
        if (state.job) {
          setConfig(state.job.config);
          state.appliedConfig = clone(state.job.config);
          state.view = "result";
        }
      }
      state.initialized = true;
      state.pollFailures = 0;
      clearConnection();
      renderContext();
      renderJob();
      await loadNode(state.path, state.labels);
      schedulePoll();
    } catch (error) { showConnection(error.message); }
    finally { $("retry-connect").disabled = false; updateControls(); }
  }

  $("scenario-form").addEventListener("submit", (event) => { event.preventDefault(); });
  $("scenario-form").addEventListener("input", (event) => {
    // The compound model selector writes utility + FGS together on change.
    // Refreshing it before that commit would restore the old canonical value.
    if (event.target.id === "hrc-equity-mode") return;
    if (["bb", "cash", "prize"].includes(event.target.dataset.setupColumn)) return;
    const changesTree = event.target.id.startsWith("player-stack-") || ["small-blind", "big-blind", "ante", "ante-type", "straddle", "skip-small-blind", "moving-button", "preflop-policy", "postflop-policy", "max-active", "tree-open", "tree-3bet", "tree-4bet", "tree-5bet", "tree-flats", "sb-complete", "allin-threshold", "postflop-enabled", "geo-hu", "geo-multi", "spr-hu", "spr-multi", "checkdown-streets", "tree-settings-json"].includes(event.target.id);
    if (changesTree && isCustomNative(state.formBaseConfig)) { state.policyTopologyDirty = true; state.policySource = null; }
    if (!["preset", "tree-editor-mode", "preflop-preset", "preflop-preset-file"].includes(event.target.id)) markEdited();
    if (event.target.id === "tree-settings-json") {
      try { syncPreflopPreset(JSON.parse(event.target.value)?.preflop || null); }
      catch (_) { syncPreflopPreset(null); }
      renderTreeEditor();
    }
    if (event.target.id.startsWith("player-name-")) {
      const index = event.target.id.slice("player-name-".length);
      const label = document.querySelector(`label[for="bounty-${index}"]`); if (label) label.textContent = event.target.value;
    }
  });
  $("scenario-form").addEventListener("change", (event) => {
    if (["utility", "bounty-mode"].includes(event.target.id)) markEdited();
    if (event.target.id === "postflop-enabled") {
      const streets = $("checkdown-streets").value.split(/[,，\s]+/).filter(Boolean).map(Number);
      if (event.target.checked && !streets.some((street) => street > 0)) $("checkdown-streets").value = state.meta.custom_native.default_config.tree_settings.postflop.settings.POSTFLOP_FORCE_CHECKDOWN_AFTER.join(", ");
      renderTreeEditor(); markEdited();
    }
    if (event.target.id === "tree-editor-mode") changeTreeEditor();
    if (event.target.id === "preflop-policy") changeTreePolicy("preflop");
    if (event.target.id === "postflop-policy") changeTreePolicy("postflop");
    if (event.target.id === "ante-type") updateControls();
    if (["fgs-enabled", "fgs-next-enabled"].includes(event.target.id)) { renderFgs(); markEdited(); }
    if (event.target.id === "rake-mode") { $("rake-fields").hidden = event.target.value === "none"; markEdited(); }
  });
  $("preset").addEventListener("change", (event) => applyPreset(event.target.value));
  $("preflop-preset").addEventListener("change", (event) => {
    state.preflopPresetRequest += 1;
    const row = preflopPresets().find((item) => item.id === event.target.value);
    if (row) applyPreflopBlock(row.preflop, row.label);
  });
  $("preflop-preset-import").addEventListener("click", () => $("preflop-preset-file").click());
  $("preflop-preset-file").addEventListener("change", async (event) => {
    const file = event.target.files?.[0]; if (!file) return;
    const request = ++state.preflopPresetRequest;
    const picker = $("preflop-preset"), button = $("preflop-preset-import");
    picker.disabled = true; button.disabled = true; picker.setAttribute("aria-busy", "true");
    try {
      if (!/\.preflop\.js$/i.test(file.name)) throw new Error("请选择 .preflop.js 下注配置文件。");
      if (file.size > 128 * 1024) throw new Error("翻前预设不能超过 128 KiB。");
      const text = await file.text();
      if (request !== state.preflopPresetRequest || $("scenario-fields").disabled) return;
      applyPreflopBlock(parsePreflopFile(text), file.name.replace(/\.preflop\.js$/i, ""));
    } catch (error) {
      if (request === state.preflopPresetRequest) {
        showFieldError("preflop-preset", error.message); formError("未能读取翻前预设，当前配置已保留。");
      }
    } finally {
      event.target.value = ""; picker.disabled = false; button.disabled = false; picker.removeAttribute("aria-busy");
    }
  });
  $("add-seat").addEventListener("click", () => {
    const players = collectPlayers();
    const custom = isCustomNative(state.formBaseConfig);
    if (players.length >= (custom ? 10 : 6)) return;
    players.unshift({ name: players.length === 2 ? "BTN" : custom ? `P${players.length + 1}` : ["", "", "", "CO", "HJ", "UTG"][players.length], stack: 20, range: "all", bounty: 0 });
    state.policyTopologyDirty = true; state.policySource = null;
    renderPlayerFields(players); renderBountyFields(players); markEdited();
  });
  $("remove-seat").addEventListener("click", () => {
    const players = collectPlayers();
    if (players.length <= 2) return;
    state.policyTopologyDirty = true; state.policySource = null;
    players.shift(); renderPlayerFields(players); renderBountyFields(players); markEdited();
  });
  $("apply-tree").addEventListener("click", applyTree);
  $("start-solve").addEventListener("click", () => desktop ? desktop.command("run") : startSolve());
  $("view-draft").addEventListener("click", () => switchView("draft"));
  $("view-result").addEventListener("click", () => switchView("result"));
  $("back-node").addEventListener("click", () => { if (!state.loading && state.path.length) loadNode(state.path.slice(0, -1), state.labels.slice(0, -1)); });
  $("retry-node").addEventListener("click", () => { const last = state.lastNodeRequest || { path: [], labels: [] }; loadNode(last.path, last.labels); });
  $("retry-connect").addEventListener("click", connect);
  $("cancel-job").addEventListener("click", cancelJob);
  $("resume-job").addEventListener("click", () => $("resume-use-draft").checked ? resumeJob() : desktop ? desktop.command("run") : resumeJob());
  $("resume-use-draft").addEventListener("change", renderJob);
  $("export-config").addEventListener("click", exportConfig);
  $("import-config").addEventListener("click", () => $("config-file").click());
  $("config-file").addEventListener("change", importConfig);
  $("export-csv").addEventListener("click", exportCsv);
  $("export-result").addEventListener("click", exportResult);
  $("export-archive").addEventListener("click", exportArchive);
  $("export-hrcz").addEventListener("click", exportHrcz);
  $("import-archive").addEventListener("click", () => $("archive-file").click());
  $("archive-file").addEventListener("change", importArchive);
  $("analysis-kind").addEventListener("change", renderTournamentAnalysis);
  $("analysis-refresh").addEventListener("click", loadTournamentAnalysis);
  $("analysis-export").addEventListener("click", () => {
    const job = state.job, data = state.analysisCache.get(job?.id); if (!data) return;
    download(`preflop-${job.id.slice(0, 8)}-equity-analysis.json`, JSON.stringify({ job_id: job.id, config: job.config, analysis: data }, null, 2), "application/json;charset=utf-8"); announce("本任务静态权益分析已导出。");
  });
  $("policy-copy-result").addEventListener("click", copyResultDraft);
  $("policy-save").addEventListener("click", () => applyPolicy(false));
  $("policy-remove").addEventListener("click", () => applyPolicy(true));
  $("policy-clear-all").addEventListener("click", () => {
    if (isImported(state.formBaseConfig)) return;
    state.formBaseConfig.policies = { version: 1, nodes: [] }; state.policyTopologyDirty = false;
    state.policyDrafts.clear(); markEdited(); announce("已清除草稿的节点约束；更新决策树后应用。原任务保持不变。");
  });
  $("policy-mode").addEventListener("change", () => {
    const next = $("policy-mode").value;
    try {
      const previous = readPolicy();
      state.policyWorking = next === "json" ? previous : next === "locks" && previous?.locks ? previous : next === "frequency" && previous?.frequency ? previous : blankPolicy(next);
      state.policyMode = next; policyError(""); fillPolicyFields(); rememberPolicyDraft();
    } catch (error) { $("policy-mode").value = state.policyMode; policyError(error.message); }
  });
  $("policy-editor").addEventListener("input", (event) => {
    if (event.target.id.startsWith("policy-target-") || event.target.id.startsWith("policy-edge-") || event.target.id === "policy-json") rememberPolicyDraft();
  });
  $("policy-lock-action").addEventListener("change", renderPolicyHand);
  $("policy-lock-hand").addEventListener("change", (event) => selectHand(event.target.value));
  for (const kind of ["fill", "update", "unlock", "source"]) $(`policy-lock-${kind}`).addEventListener("click", () => {
    try {
      const node = state.node, action = Number($("policy-lock-action").value);
      if (node.special && action === 0) throw new Error("可过牌节点的虚拟弃牌不能锁定。");
      state.policyWorking ||= blankPolicy("locks");
      if (kind === "unlock") state.policyWorking.locks[action] = null;
      else if (kind === "source") {
        if ($( "policy-lock-source").disabled) return;
        state.policyWorking.locks[action] = policyLabels().map((label) => state.policySource.hands[label].frequencies[action]);
      } else {
        const input = $(kind === "fill" ? "policy-lock-all" : "policy-lock-value"), value = Number(input.value);
        if (!input.value.trim() || !Number.isFinite(value) || value < 0 || value > 100) throw new Error("锁定频率需为 0–100%。");
        if (kind === "fill") state.policyWorking.locks[action] = policyLabels().map(() => value / 100);
        else state.policyWorking.locks[action][policyLabels().indexOf(state.selectedHand)] = value / 100;
      }
      policyError(""); renderPolicyHand(); rememberPolicyDraft();
    } catch (error) { policyError(error.message); }
  });
  $("show-model").addEventListener("click", () => {
    $("model-details").open = true;
    $("model-details").scrollIntoView({ behavior: "auto", block: "center" });
    $("model-details").querySelector("summary").focus({ preventScroll: true });
  });
  $("job-history").addEventListener("change", async (event) => {
    const job = state.jobs.find((item) => item.id === event.target.value);
    if (!job) return;
    state.job = job;
    state.view = "result";
    resetNode(); renderContext(); renderJob();
    await loadNode([], []);
  });
  window.addEventListener("beforeunload", (event) => {
    if (state.formEdited) { event.preventDefault(); event.returnValue = ""; }
  });
  window.addEventListener("online", () => { if (!$("connection-banner").hidden) connect(); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.activeId) { clearTimeout(state.pollTimer); pollJob(); }
  });
  if (window.PreflopDesktop) desktop = new window.PreflopDesktop({
    state, currentConfig, api, loadNode, renderRange, actionLabel,
    resetNode, renderContext, renderJob, switchView, applyPreset,
    startSolve, initializeHand, submitSampling, isNative, sampleLimit, cancelJob, exportArchive, exportHrcz, hasHandPolicy,
    applyTree, setConfig, collectPlayers,
    readConfig, refreshFormVisibility, formError,
  });
  connect();
})();
