---
version: alpha
name: Preflop Lab HRC Workbench
description: A local research implementation using the observed HRC desktop layout and interaction structure requested by the user.
colors:
  navy: "#F3F3F3"
  ink: "#111111"
  muted: "#707070"
  background: "#F3F3F3"
  surface: "#FFFFFF"
  border: "#D6D6D6"
  primary: "#2675C8"
  call: "#97E4A0"
  raise: "#84EE86"
  shove: "#FFAAAA"
  fold: "#FFFFFF"
  success: "#257E36"
  danger: "#A32B2B"
typography:
  body:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: "1.35"
  display:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
    fontSize: "12px"
    lineHeight: "1.35"
  mono:
    fontFamily: '"Segoe UI", "Microsoft YaHei", sans-serif'
  range:
    fontFamily: '"Times New Roman", Times, serif'
    fontSize: "32px"
    lineHeight: "1.02"
rounded:
  DEFAULT: "0px"
  panel: "0px"
  cell: "0px"
spacing:
  unit: "4px"
  panel: "8px"
  gap: "4px"
components:
  toolbar:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.ink}"
  note:
    textColor: "{colors.muted}"
  button:
    backgroundColor: "{colors.background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.DEFAULT}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  panel:
    backgroundColor: "{colors.background}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  header:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
  workspace:
    backgroundColor: "{colors.background}"
    textColor: "{colors.ink}"
  field-label:
    textColor: "{colors.ink}"
  divider:
    backgroundColor: "{colors.border}"
  action-call:
    backgroundColor: "{colors.call}"
    textColor: "{colors.ink}"
  action-raise:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.ink}"
  action-shove:
    backgroundColor: "{colors.shove}"
    textColor: "{colors.ink}"
  action-fold:
    backgroundColor: "{colors.fold}"
    textColor: "{colors.ink}"
  success-status:
    textColor: "{colors.success}"
  error:
    textColor: "{colors.danger}"
---

# HRC desktop workbench reference

## Current design authority

The user's explicit instruction is to follow the installed HRC application's layout, positions, logic and displayed values, without introducing an independent visual design. This supersedes the earlier navy research dashboard and its card layout. The product remains an independent local implementation; copying the window arrangement does not establish numerical equivalence or make it the original HRC program.

The directly inspected visual references are analysis/hrc-desktop/screens/ui-reference-pko.png, ui-reference-main.png and ui-reference-settings.png. The first shows a loaded PKO hand, the second Home, and the third the collapsed Hand Settings property categories. These screenshots, rather than general taste preferences, determine the layout. No remote fonts, CDN or original logo assets are required.

Runtime CSS variables in web/app.css remain the canonical token owner (Model B). The colors, typography, zero radii and compact spacing above map to the matching --color-*, --font-*, --radius-* and --space-* properties. The historical `navy` key is retained for compatibility and now maps to light gray; no dark navigation shell remains. Numeric cells use tabular Segoe UI; the range matrix uses Times New Roman. Range font sizes shrink with the matrix container so both the hand label and EV line fit each of thirteen rows.

## Window layout

The viewport has a 23px File / Hand / Tools / Window / Help menu, a 25px icon toolbar, the remaining dock workspace and a 21px status bar. The desktop layout has no hero, branding banner, independent inspector card, shadow, rounded card or decorative animation. White and very light gray surfaces use one-pixel separators.

The left column starts at 390px, with a draggable 5px vertical separator. Its upper 65% contains document tabs and Strategy Table / Hand Settings tabs; the lower 35% is Table. The right upper 80% is Range, and the remaining 20% contains Progress / Outline / Hand Details / Constraints / Analysis / Archives. Each column has a draggable horizontal separator. Ratios are CSS properties --hrc-left-width, --hrc-left-top and --hrc-right-top. The root JavaScript adapter owns pointer and keyboard resizing. On a narrow viewport the actual two-column desktop workspace scrolls horizontally; it does not become a newly designed mobile card interface.

Strategy Table is a compact four-column table: Action, Amt [BB], Player, Range. Non-fold actions on the successive fold path form the initial view. Expansion opens actual child branches, while row selection changes the displayed action and range. A light-blue selected row, small green node marker and native-size expansion button follow the reference. The final Range column truncates long range text visually and preserves a complete tooltip.

Hand Settings uses the same controls and IDs grouped into Hand Data, Equity Model, Treeconfig and Engine. The basic hand editor follows the observed Basic Hand Data page: Stacks and Blinds on the left, Prizes on the right, Calculation Mode below. Its compact cells replace the earlier vertical seat and bounty cards. The actual canonical inputs remain in the single scenario form; the BB and immediate-bounty columns are unit editors, not separate scenario fields. Treeconfig and Engine retain their existing editors. Simple and General parameter preservation, validation and stored-state semantics remain authoritative.

Table is a gray oval with white outlined player labels, red card backs, yellow active-player label, optional head-bounty values and a dealer marker. SB is at the bottom, BB toward the lower left, and BU toward the lower right, following the inspected reference. The root adapter supplies the actual seat ordering, cards, amounts and selected-action caption. No calculated outcome is fabricated for decoration.

## Range display

The Range toolbar exposes source and action selection and three small color modes: combined, frequency and EV. One 13×13 matrix is visible at a time. The original reference uses the same visible surface through a source switch; there are no side-by-side comparison cards. The existing range-matrix and reference-matrix IDs remain available for rendering compatibility.

Each cell has a Times New Roman hand label and a second EV or frequency line. The root adapter owns the selected action, source, data validity, gradient and monetary conversion. CSS consumes --cell-background; meaningful positive action frequency receives the observed dark cell border, with fine gray borders otherwise. The selected hand and keyboard focus remain discernible. Untrained cells are neutral and labeled; absent EV is not synthesized. A thin bottom bar shows selected-action frequency against the remainder. Full hand frequencies, units, samples and model caveats are available in Hand Details instead of a separate side card.

The root adapter applies the HRC display unit for supported monetary models while preserving raw monetary values in underlying results. UI similarity must never convert a monetary EV into BB or reinterpret strategy drift as statistical confidence. Source matching remains strict; unavailable original references cannot be selected.

## Interaction contract

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Native select in web/index.html and app.js | DESIGN.md | OS popup | Browser source and action selection |
| Form | app.js readConfig/setConfig/showFieldError with hrc-hand-setup.js | API-CONTRACT.md and observed HRC Hand Setup | Property groups and modal wizard reuse one form | Chip/BB and bounty conversion, prize rows, validation, cancellation |
| Scrollbar | Global web/app.css | DESIGN.md | Independent dock scrolling | Browser narrow viewport |
| Toast | app.js announce and statusbar | DESIGN.md | Polite status and persistent inline errors | Browser live region |
| Table Selection | hrc-workbench.js Strategy Table | DESIGN.md | Lazy fold continuations and explicit expansion | Browser BTN selection and branch expansion |

The HTML keeps all 238 previous IDs. The root owns web/app.js and web/hrc-workbench.js; the shell owns web/index.html and web/app.css. The adapter is loaded before app.js. Existing calculation state, validation, networking, cancellation, partial results and checkpoint identity remain authoritative.

Tabs use `data-hrc-tab="left|bottom"` and `data-hrc-target="pane-id"`; active buttons set aria-selected and inactive panes set hidden. Left panes are hrc-strategy-pane / hrc-settings-pane. Bottom panes are hrc-progress-pane, hrc-outline-pane, hrc-hand-details-pane, hrc-constraints-pane, hrc-analysis-pane and hrc-archive-pane. Dynamic Home and document tabs are rendered by the adapter.

Menus use data-hrc-menu-toggle with file/hand/tools/window/help and aria-controls pointing to hrc-menu-*; panels use matching data-hrc-menu-panel. Commands are new, settings, save, open, run, stop, home, analysis, constraints, archive and about. Menu keyboard handling, outside click and actions belong to the adapter. Native hrc-about-dialog and hrc-new-dialog containers are reserved, with hrc-new-content for the new-hand workflow.

Range selects are hrc-range-source and hrc-range-action. Modes use data-hrc-range-mode=frequency|ev|combined; combined is initially selected. hrc-range-caption and hrc-range-total display actual selected-action information. The table and outline roots are hrc-strategy-body and hrc-outline-tree. Splitter IDs are hrc-vertical-splitter, hrc-left-splitter and hrc-right-splitter.

Former breadcrumbs, action buttons and view controls are retained in a hidden compatibility container because the strategy table and document tabs replace their visible role. Node errors and retry stay in the visible Table pane when active. Connection failures remain visible above the workspace. Draft/result separation text and transient announcements use the status bar. The adapter must reveal the appropriate tab or dialog before focusing validation errors; hiding an editor must not silently discard its fields.

## Preserved capabilities and verification

FGS, policies/locks, storage formats, stop targets, resets/migration, static BF/RP analysis, archives, import/export and resume remain in their respective settings groups or bottom panes. Existing jobs and checkpoints are untouched by shell reconstruction. No new kernel work is part of this UI task.

Static reconstruction checked that all 238 prior IDs survive and that the new HTML IDs are unique. The structural CSS no longer includes the earlier dashboard rules. Actual screenshots, tab/menu behavior, row selection, source switching, resizing, settings validation and save/restore actions require the root thread's browser pass. These checks establish the visible workbench and interaction coverage, not a claim of complete HRC feature or numerical parity. Remaining visual differences should be documented from that pass rather than assumed away.

## Basic hand data input contract

The reference is analysis/hrc-desktop/screens/inputs-hand-setup.png, observed directly from the installed HRC. Follow its compact native table layout and field order. New Hand and the existing Hand Settings pane reuse the same editor and actual inputs. Native selects retain the platform popup and keyboard behavior; no new authored listbox or icon system is introduced.

Stacks are entered before forced bets, in preflop action order. The BB column derives from the current stack divided by the current big blind. Editing BB converts to the canonical stack in the scene's existing unit; editing a blind never rescales stacks. Round native scene amounts only to their supported internal chip precision. Fixed benchmark inputs retain their documented BB unit. Loaded HRC scenes retain their source units and read-only restrictions.

PKO shows full head bounty and immediately paid bounty in adjacent columns: KO-P$ = KO-T$ × Instant / 100. At zero immediate percentage, the immediate-payment column is read-only zero. KO uses the shared fixed bounty input. Off leaves the inactive bounty columns blank. Prize percentages, Places Paid and regular prize pool are derived read-only observations; bounties are excluded from the regular pool. A blank or `..` prize cell inherits the preceding prize jump, and a final explicit zero ends the paid places. Preserve prizes beyond the first ten rows and explicit outside-player details. Unknown or unsupported source fields are not replaced with defaults.

The wizard validates the active step before Next, retains values on Back, and closes on Finish only after successful tree construction and acceptance of the initialization job. Recoverable errors remain inside the dialog with an associated field and a correction path. While Finish is pending, duplicate commits and cancellation races are blocked. Cancel restores the prior raw field values, conditional sections, selected hand, strategy source, path and uncommitted policy edits. Cancel never modifies an existing saved calculation or starts training.

The form and dialog use their established scrolling surfaces. Compact table borders, spacing, fonts and focus states consume the existing runtime tokens. The narrow Hand Settings sidebar stacks Stacks and Blinds above Prizes; the larger New Hand dialog preserves their side-by-side arrangement. Tables and model options scroll within their existing pane; labels, values, error messages and footer actions stay reachable. Enter/arrow keys move within an editable column without intercepting IME composition. Multirow paste accepts one numeric column at a time and rejects extra columns without altering input.

Thread count is a native numeric field in the existing Engine settings, using the shared field validation and density. Resume owns its own thread field outside the frozen source-scenario fieldset. Both accept integers 1–32 and default to four in new UI controls; API compatibility defaults to one. Resume submits thread count as a run option without changing topology or policies. The finished/progress detail displays the actual thread count. Parallel results may vary with scheduling; the settings note explains this without introducing a new confirmation or layout.

## Nash Calculation sampling contract

The user's original-program screenshots and `analysis/hrc-desktop/screens/ci40-observed-nash-dialog.png` govern the compact sampling property table. The green toolbar command is Run Nash Calculation (Alt+R), opening the existing native-dialog owner, `hrc-sampling-dialog`. Its rows follow HRC: CFR Algorithm, Scope, Run Sampling, CI Target (or Samples), Reset Regret and Reset Strategies. Defaults are HRC 4.0, Full Tree, Until CI value is reached, 10.0 and both resets off. Checking Reset Regret also checks and disables Reset Strategies; unchecking Regret leaves Strategies checked but editable. The formal request independently enforces that regret reset implies average-strategy reset. Native selects and numeric inputs use the established SWT-style field treatment. Threads and safety limits are a collapsed extension; the API-compatible time target remains available without changing the observed defaults.

The sampling form is owned by `PreflopDesktop.samplingOptions` / `submitSampling`, with app.js owning mutations. It is a separate run-options form, not a second copy of the hand configuration. A formal resume sends flat run overrides to the selected saved hand, including imported source hands. It never submits the left-hand draft or implicitly migrates stores. Opening the dialog freezes the hand identity and current decision prefix. Selected Subtree means the decision before the selected action, including all available actions; display its path, actor and node ID. Only initialized, nonterminal preflop decisions are selectable. The server must advertise the capability, and unsupported scope must produce an explicit unavailable state rather than falling back to Full Tree.

CI mode enables tracking and treats iterations only as a cumulative safety cap; a blank cap uses the service maximum. In the HRC dialog, fixed Samples means additional samples for this invocation, defaulting to 50,000,000. The adapter adds the saved hand's completed count before submitting the API's cumulative `iterations` target: 10m already completed plus 50m entered sends 60m. Input bounds use the remaining capacity and preserve the API minimum cumulative target of 100. The API mode switch clears incompatible old completion targets. Inline validation keeps the dialog open and focuses the invalid control; server failures retain every entered value. Pending submission blocks duplicate OK, Cancel and Escape; successful acceptance closes and returns to Progress. Cancel changes no hand configuration or run state. Original imported update clocks remain distinct from new cumulative samples.

New Hand Finish starts full-tree fixed-sample initialization using `meta.training.initialization_samples` (10,000,000 fallback), with CI tracking off and no inherited time or CI stop. The wizard states this before submission. Progress identifies initialization separately, and its successful completion says “手牌已初始化，点击 Run 开始正式计算”. The subsequent Run returns to CI 10, not the initialization sample mode. A stopped initialization never claims to have reached a precision goal.

CI progress never uses the sample-count fraction. Before a valid CI value and positive server `ci.progress` are available, the indicator is indeterminate. Finite server CI progress in 0–1 and `eta_seconds` are explicitly labeled heuristic estimates; missing ETA remains unknown. Stopped CI tasks do not retain an animated indeterminate bar. Current CI, target, actual sampling scope, sample safety cap, stopping reason and precision-goal status stay distinct. CI describes recent strategy drift, not a confidence interval, error percentage or equilibrium certificate.

Production adapter checks are in `scripts/check-ui-sampling.cjs`; they exercise request validation, source identity, lifecycle stage and progress semantics without launching a solver. Browser verification belongs to the shared root session and must verify the actual dialog, cancellation, current-node scope and request payload against the new capability-advertising service.

## Built-in betting presets

Keep the existing HRC desktop layout and Hand Setup ownership. The Treeconfig page owns the native `Preflop Preset` select and its adjacent file-open button. The canonical catalog is `preflop_lab/data/preflop_presets.json`; `scripts/bundle-preflop-presets.py` embeds the same data in `web/hrc-hand-setup.js` for services without the new metadata field. Never edit that generated catalog block directly. The 27 unique configurations retain provenance for all 33 supplied files. A BB depth label changes betting rules only; it never changes seat stacks, blind levels, payouts, outside tables or postflop settings. Existing JSON editing remains available. Failed or stale imports preserve the draft and expose the existing inline error state. The file parser accepts declarative JSON assignments only and never evaluates JavaScript.

Standalone hand scenarios remain under the existing Model Options preset selector. The eight-player 58/57 bubble setup contains the exact before-blind chip amounts, 50 outside stacks and 57 payouts supplied by the user. Its chip_scale=100 preserves HRC internal chip granularity while showing BB=3000; legacy scenes retain chip_scale=10000. New Hand and Run keep the initialization and formal sampling lifecycle described above. Matching inputs and topology must never be labeled proof of converged strategy equivalence.
