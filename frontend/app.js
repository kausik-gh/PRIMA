let API_BASE = "";
const DEFAULT_API_PORT = "8088";
const DEMO_SIM_MODE = true;
const LIVE_POLL_MS = 5000;
const TX_POLL_MS = 1800;
const ACCOUNT_POLL_MS = 5000;
const ATTACK_POLL_MS = 3000;
const ACCOUNT_CREATE_MS = 12000;
const DETECTION_STATUS_MS = 2000;
const NORMAL_TX_DURATION_MS = 900;
const SUSPICIOUS_TX_DURATION_MS = 1125;
const ATTACK_TX_DURATION_MS = 260;
const ATTACK_SIREN_MS = 3000;
const ATTACK_TX_PHASE_MS = 4000;
const GRAPH_POSITION_SCALE = 1.45;
const GRAPH_LAYOUT_CENTER_X = 900 * GRAPH_POSITION_SCALE;
const GRAPH_LAYOUT_CENTER_Y = 575 * GRAPH_POSITION_SCALE;
const GRAPH_LAYOUT_RADIUS = 680;
const GRAPH_LAYOUT_DEPTH = 1420;
const GRAPH_CAMERA_FOV = 62;
const GRAPH_CAMERA_NEAR = 0.03;
const GRAPH_CAMERA_FAR = 18000;
const MAX_ACTIVE_TRAVELERS = 18;
const MAX_TX_PER_FRAME = 4;
const FEED_RENDER_MIN_INTERVAL_MS = 60;
const VISIBLE_TPS_WINDOW_MS = 1000;
const MAX_SEEN_TRANSACTION_SIGNATURES = 12000;
const FRAME_INTERVAL_MS = 33;
const UI_UPDATE_MIN_INTERVAL_MS = 60;
const PERF_DEBUG = false;
const NO_EDGE_ARROWS = { to: { enabled: false }, from: { enabled: false }, middle: { enabled: false } };
const LIVE_WARNING_THRESHOLD = 0.38;
const DEMO_RUNTIME_INTERVAL_MS = 140;
const DEMO_TPS_MIN = 3;
const DEMO_TPS_MAX = 7;
const DEMO_SUSPICIOUS_MIN_TOTAL = 3;
const DEMO_SUSPICIOUS_MIN_SIGNAL = 0.9;
const DEMO_STREAM_DECAY = 0.99;
const DEMO_SUSPICIOUS_SOFT_CAP = 20;
const DEMO_SUSPICIOUS_HARD_CAP = 20;
const DEMO_MIN_SUSPICIOUS = 5;
const PHASES = Object.freeze({
  IDLE: "idle",
  BUILD: "build",
  ATTACK_FLOW: "attack_flow",
  FRAUD_REVEAL: "fraud_reveal",
  POST_ATTACK: "post_attack",
});

const state = {
  live: null,
  dashboard: null,
  investigation: null,
  liveNetwork: null,
  attackNetwork: null,
  liveNodes: new vis.DataSet(),
  liveEdges: new vis.DataSet(),
  attackNodes: new vis.DataSet(),
  attackEdges: new vis.DataSet(),
  charts: {},
  seenTransactions: new Set(),
  txFeed: [],
  suspiciousFeed: [],
  transactionQueue: [],
  transactionQueueCursor: 0,
  localEdgeIndex: 0,
  latestAttackData: null,
  attackReplayTimer: null,
  banSelect: null,
  fraudNodeSet: new Set(),
  fraudEdgeSet: new Set(),
  currentFraudIds: new Set(),
  currentEarlyIds: new Set(),
  sirenMuted: false,
  sirenActive: false,
  audioContext: null,
  intervals: [],
  apiCandidates: [],
  simulationInFlight: false,
  detectionPollTimer: null,
  attackGraphFittedFor: null,
  currentInvestigationAccount: null,
  attackAnimationTimer: null,
  lastSirenAttackName: null,
  lastReplayAttackName: null,
  websocket: null,
  websocketConnected: false,
  pollingFallbackStarted: false,
  backgroundLoopsStarted: false,
  dashboardRefreshInFlight: false,
  lastDashboardRefreshJobId: null,
  lastDashboardErrorJobId: null,
  websocketReconnectTimer: null,
  uiSyncFrame: null,
  earlyExplainerTimer: null,
  liveGraphFitted: false,
  activeTravelers: [],
  travelerFrame: null,
  visualFrame: null,
  feedDirty: false,
  lastFeedRenderAt: 0,
  visibleTxTimestamps: [],
  visibleTps: 0,
  isReplaying: false,
  subgraphCreated: false,
  attackSequenceToken: 0,
  attackSequenceStage: "idle",
  pendingAttackNodes: new Set(),
  confirmedAttackNodes: new Set(),
  detectionFinalized: false,
  finalizedAttackName: null,
  activeAttackName: null,
  persistentAttackEdgeIds: new Set(),
  networkScaleFrame: null,
  lastLiveVisualAt: 0,
  nextLiveVisualDelay: 240,
  lastAccounts: [],
  liveSuspiciousSummary: null,
  resizeFrame: null,
  tableRenderCache: new WeakMap(),
  chartRenderHashes: {},
  seenTransactionOrder: [],
  pendingSnapshot: null,
  snapshotFrame: null,
  txWorker: null,
  txWorkerEnabled: false,
  lastVisualFrameAt: 0,
  lastUiRenderAt: 0,
  demoData: null,
  liveGraph3D: null,
  attackGraph3D: null,
  demoRuntimeTimer: null,
  demoRiskMap: new Map(),
  demoTxTimestamps: [],
  demoScenario: null,
  attackFlashTimer: null,
  phase: "idle",
  demoRunIndex: 0,
  demoAttackArmed: false,
  preAttackSuspiciousIds: [],
  preAttackSnapshot: [],
  accounts: {},
  suspiciousList: [],
  fraudList: [],
  bannedList: [],
  transactions: [],
  attackTransactions: [],
  accountStore: new Map(),
  selectedForBan: new Set(),
  stateValidationLock: false,
  dashboardHistory: {
    labels: [],
    thresholds: [],
    recalls: [],
    roleTotals: {
      "Ring Coordinator": 0,
      "Collector Mule": 0,
      "Distributor Mule": 0,
    },
  },
  lastHistorySignature: null,
  investigationHighlightId: null,
};

function randBetween(min, max) {
  return min + Math.random() * (max - min);
}

function upsertAccountStore(accountId, patch = {}) {
  const id = String(accountId || "");
  if (!id) return;
  const prev = state.accountStore.get(id) || {
    id,
    status: "normal",
    risk_score: 0,
    selected_for_ban: false,
  };
  state.accountStore.set(id, {
    ...prev,
    ...patch,
    id,
  });
}

function getStatusCounts() {
  const counts = { normal: 0, suspicious: 0, fraud: 0, banned: 0, active: 0, total: 0 };
  state.accountStore.forEach((account) => {
    counts.total += 1;
    const status = account?.status || "normal";
    if (status === "banned") {
      counts.banned += 1;
      return;
    }
    counts.active += 1;
    if (status === "fraud") counts.fraud += 1;
    else if (status === "early") counts.suspicious += 1;
    else counts.normal += 1;
  });
  return counts;
}

function getSuspiciousIdsFromStore() {
  return [...state.accountStore.values()]
    .filter((account) => account?.status === "early")
    .map((account) => String(account.id))
    .sort();
}

function getFraudIdsFromStore() {
  return [...state.accountStore.values()]
    .filter((account) => account?.status === "fraud")
    .map((account) => String(account.id))
    .sort();
}

function getBannedIdsFromStore() {
  return [...state.accountStore.values()]
    .filter((account) => account?.status === "banned")
    .map((account) => String(account.id))
    .sort();
}

function stableUnitFromId(input = "") {
  let hash = 2166136261;
  const text = String(input || "");
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 1000;
}

function syncFrontendDerivedLists() {
  const suspicious = [];
  const fraud = [];
  const banned = [];
  const accounts = {};

  state.accountStore.forEach((account, accountId) => {
    const normalizedId = String(accountId || account?.id || "");
    if (!normalizedId) {
      return;
    }
    const status = account?.status || "normal";
    const snapshot = {
      ...account,
      id: normalizedId,
      status,
    };
    accounts[normalizedId] = snapshot;
    if (status === "early") suspicious.push(normalizedId);
    else if (status === "fraud") fraud.push(normalizedId);
    else if (status === "banned") banned.push(normalizedId);
  });

  const mergedFraud = [...new Set([...fraud, ...[...state.fraudNodeSet].map(String)])].sort();
  const mergedBanned = [...new Set([...banned, ...((state.live?.banned_accounts || []).map(String))])].sort();
  const mergedSuspicious = suspicious
    .filter((accountId) => !mergedFraud.includes(accountId) && !mergedBanned.includes(accountId))
    .sort();
  state.accounts = accounts;
  state.suspiciousList = mergedSuspicious;
  state.fraudList = mergedFraud;
  state.bannedList = mergedBanned;
  state.currentEarlyIds = new Set(mergedSuspicious);
  state.currentFraudIds = new Set(mergedFraud);
  return { suspicious: mergedSuspicious, fraud: mergedFraud, banned: mergedBanned };
}

function buildFrontendTransactionStats(limit = 900) {
  const stats = new Map();
  const txWindow = (state.transactions || []).slice(-limit);
  txWindow.forEach((tx) => {
    if (!tx || tx.isAttack || tx.is_attack) {
      return;
    }
    const sender = String(tx.sender || tx.source || "");
    const receiver = String(tx.receiver || tx.target || "");
    const amount = Number(tx.amount || 0);
    const suspicious = Boolean(tx.suspicious);
    [sender, receiver].forEach((accountId) => {
      if (!accountId) return;
      const current = stats.get(accountId) || {
        count: 0,
        suspiciousCount: 0,
        totalAmount: 0,
      };
      current.count += 1;
      current.totalAmount += amount;
      if (suspicious) {
        current.suspiciousCount += 1;
      }
      stats.set(accountId, current);
    });
  });
  return stats;
}

function computeFrontendSuspiciousTargetCount() {
  const activeCount = (state.lastAccounts || []).filter((account) => account.is_active !== false).length
    || Math.max(0, state.accountStore.size - getBannedIdsFromStore().length);
  const txCount = Number(state.transactions?.length || 0);
  const baseTarget = Math.min(
    DEMO_SUSPICIOUS_SOFT_CAP,
    Math.max(DEMO_MIN_SUSPICIOUS, 5 + Math.floor(txCount / 180) * 3)
  );
  const cappedByUniverse = activeCount
    ? Math.min(baseTarget, Math.max(DEMO_MIN_SUSPICIOUS, Math.min(DEMO_SUSPICIOUS_SOFT_CAP, Math.round(activeCount * 0.08))))
    : baseTarget;
  const previous = Math.max(0, Number(state.suspiciousList?.length || 0));
  if (previous <= 0) {
    return Math.min(DEMO_SUSPICIOUS_SOFT_CAP, Math.max(DEMO_MIN_SUSPICIOUS, cappedByUniverse));
  }
  if (cappedByUniverse > previous) {
    return Math.min(cappedByUniverse, previous + 2);
  }
  if (cappedByUniverse < previous) {
    return Math.max(DEMO_MIN_SUSPICIOUS, previous - 1);
  }
  return previous;
}

function buildFrontendSuspiciousRanking(accounts = state.lastAccounts, bannedSet = new Set(), fraudSet = new Set()) {
  const stats = buildFrontendTransactionStats();
  const currentSuspicious = new Set(state.suspiciousList || []);
  return (accounts || [])
    .map((account) => String(account?.account_id || ""))
    .filter(Boolean)
    .filter((accountId) => !bannedSet.has(accountId) && !fraudSet.has(accountId))
    .map((accountId) => {
      const account = state.accountStore.get(accountId) || {};
      const stat = stats.get(accountId) || { count: 0, suspiciousCount: 0, totalAmount: 0 };
      const riskScore = Math.max(0, Math.min(1, Number(account.risk_score || 0)));
      const txScore = Math.min(1, Number(stat.count || 0) / 18);
      const suspiciousScore = Math.min(1, Number(stat.suspiciousCount || 0) / 8);
      const amountScore = Math.min(1, Number(stat.totalAmount || 0) / 90000);
      const continuityBoost = currentSuspicious.has(accountId) ? 0.18 : 0;
      const candidateBoost = state.demoScenario?.fraudCandidatePool?.includes(accountId) ? 0.08 : 0;
      const stableNoise = stableUnitFromId(`${accountId}|suspicious`) * 0.05;
      const score = (riskScore * 0.38)
        + (txScore * 0.2)
        + (suspiciousScore * 0.18)
        + (amountScore * 0.08)
        + continuityBoost
        + candidateBoost
        + stableNoise;
      return { accountId, score };
    })
    .sort((left, right) => right.score - left.score);
}

function enforceFrontendMasterState({ accounts = state.lastAccounts, live = state.live, forceMinimumSuspicious = false } = {}) {
  if (state.stateValidationLock) {
    return syncFrontendDerivedLists();
  }

  state.stateValidationLock = true;
  try {
    const accountList = Array.isArray(accounts) ? accounts : [];
    const livePayload = live || state.live || {};
    const bannedSet = new Set([
      ...(livePayload?.banned_accounts || []).map(String),
      ...getBannedIdsFromStore(),
      ...accountList
        .filter((account) => account?.is_active === false)
        .map((account) => String(account.account_id || "")),
    ]);
    const persistentFraudList = (state.detectionFinalized || isFraudRevealPhase(getEffectivePhase()))
      ? state.fraudList
      : [];
    const fraudSet = new Set([
      ...state.fraudNodeSet,
      ...state.confirmedAttackNodes,
      ...state.currentFraudIds,
      ...persistentFraudList,
    ].map(String).filter(Boolean));

    bannedSet.forEach((accountId) => fraudSet.delete(accountId));

    const desiredSuspiciousCount = computeFrontendSuspiciousTargetCount();
    const ranked = buildFrontendSuspiciousRanking(accountList, bannedSet, fraudSet);
    const suspiciousSet = new Set(
      ranked
        .slice(0, Math.max(forceMinimumSuspicious ? DEMO_MIN_SUSPICIOUS : 0, desiredSuspiciousCount))
        .map((item) => item.accountId)
    );

    if (forceMinimumSuspicious && suspiciousSet.size < DEMO_MIN_SUSPICIOUS) {
      ranked.forEach((item) => {
        if (suspiciousSet.size >= DEMO_MIN_SUSPICIOUS) return;
        suspiciousSet.add(String(item.accountId));
      });
      if (suspiciousSet.size < DEMO_MIN_SUSPICIOUS) {
        accountList.forEach((account) => {
          const accountId = String(account?.account_id || "");
          if (!accountId || bannedSet.has(accountId) || fraudSet.has(accountId) || suspiciousSet.has(accountId)) {
            return;
          }
          if (suspiciousSet.size < DEMO_MIN_SUSPICIOUS) {
            suspiciousSet.add(accountId);
          }
        });
      }
    }

    fraudSet.forEach((accountId) => suspiciousSet.delete(accountId));
    bannedSet.forEach((accountId) => suspiciousSet.delete(accountId));

    state.accountStore.forEach((account, accountId) => {
      const normalizedId = String(accountId || "");
      if (!normalizedId) return;
      const nextStatus = bannedSet.has(normalizedId)
        ? "banned"
        : fraudSet.has(normalizedId)
          ? "fraud"
          : suspiciousSet.has(normalizedId)
            ? "early"
            : "normal";
      state.accountStore.set(normalizedId, {
        ...account,
        id: normalizedId,
        status: nextStatus,
        selected_for_ban: nextStatus === "fraud" ? Boolean(account.selected_for_ban) : false,
      });
    });

    state.live = {
      ...(state.live || {}),
      ...(livePayload || {}),
      banned_accounts: [...bannedSet].sort(),
      fraud_accounts: [...fraudSet].sort(),
    };
    const derived = syncFrontendDerivedLists();
    if (state.demoScenario) {
      state.demoScenario.suspiciousIds = [...derived.suspicious];
      state.demoScenario.monitoringCount = Math.max(
        DEMO_MIN_SUSPICIOUS,
        Math.min(DEMO_SUSPICIOUS_SOFT_CAP, derived.suspicious.length || DEMO_MIN_SUSPICIOUS)
      );
      state.demoScenario.monitoringCountFloat = Number(state.demoScenario.monitoringCount);
      if (isFraudRevealPhase(getEffectivePhase())) {
        state.demoScenario.fraudIds = [...derived.fraud];
      }
    }
    return derived;
  } finally {
    state.stateValidationLock = false;
  }
}

function buildEmptyCrossCheck() {
  return {
    early_warned: 0,
    matched: 0,
    sleeper: 0,
    matched_accounts: [],
    sleeper_accounts: [],
    false_positive_accounts: [],
    message: "Cross-check becomes available after fraud reveal.",
  };
}

function isFraudRevealPhase(phase = state.phase) {
  return phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK;
}

function shouldRunCrossCheck() {
  return isFraudRevealPhase(getEffectivePhase()) && state.preAttackSnapshot.length > 0;
}

function capturePreAttackSnapshot() {
  const snapshot = getSuspiciousIdsFromStore();
  state.preAttackSnapshot = [...snapshot];
  state.preAttackSuspiciousIds = [...snapshot];
  return snapshot;
}

function computeCrossCheckFromState(fraudNodes = getFraudIdsFromStore()) {
  if (!shouldRunCrossCheck()) {
    return buildEmptyCrossCheck();
  }
  return computeDemoCrossCheck(state.preAttackSnapshot, fraudNodes);
}

function validateSystemState() {
  if (state.stateValidationLock) {
    return;
  }
  const counts = getStatusCounts();
  const yellowNodes = state.liveNodes.get().filter((node) => node.status === "early").length;
  if ((counts.suspicious <= 0 || yellowNodes <= 0) && (state.lastAccounts || []).some((account) => account.is_active !== false)) {
    enforceFrontendMasterState({
      accounts: state.lastAccounts,
      live: state.live,
      forceMinimumSuspicious: true,
    });
  }
  if (counts.suspicious !== yellowNodes) {
    console.error("[STATE_ERROR] suspicious_count mismatch", {
      statusCount: counts.suspicious,
      yellowNodes,
      phase: getEffectivePhase(),
    });
    enforceFrontendMasterState({
      accounts: state.lastAccounts,
      live: state.live,
      forceMinimumSuspicious: true,
    });
  }
  if (shouldRunCrossCheck()) {
    const fraudSet = new Set(getFraudIdsFromStore());
    const preAttack = new Set((state.preAttackSnapshot || []).map(String));
    const outsideSnapshot = [...fraudSet].filter((id) => !preAttack.has(id));
    if (outsideSnapshot.length) {
      console.error("[STATE_ERROR] fraud not subset of snapshot", {
        outsideSnapshot,
        phase: getEffectivePhase(),
      });
      state.preAttackSnapshot = [...new Set([...(state.preAttackSnapshot || []).map(String), ...outsideSnapshot])];
      state.preAttackSuspiciousIds = [...state.preAttackSnapshot];
    }
  } else if (state.demoScenario?.crossCheck) {
    console.error("[STATE_ERROR] cross-check ran before fraud reveal", {
      phase: getEffectivePhase(),
      crossCheck: state.demoScenario.crossCheck,
    });
    state.demoScenario.crossCheck = null;
  }
}

function setBanSelection(selectedIds = []) {
  const normalized = new Set((selectedIds || []).map(String));
  state.selectedForBan = normalized;
  state.accountStore.forEach((account, accountId) => {
    account.selected_for_ban = normalized.has(String(accountId));
  });
  const updates = [];
  normalized.forEach((id) => {
    const node = state.liveNodes.get(String(id));
    if (node && node.status === "fraud") {
      updates.push({ id: String(id), size: Math.max(Number(node.size || node.baseSize || 24), 46) });
    }
  });
  if (updates.length) {
    state.liveNodes.update(updates);
    state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
  }
  console.debug("[BAN_SELECTION]", { selected: [...normalized], count: normalized.size });
}

function buildDemoAccounts(total = 180) {
  const accounts = [];
  for (let i = 1; i <= total; i += 1) {
    const accountId = `A${String(i).padStart(4, "0")}`;
    accounts.push({
      account_id: accountId,
      channel: ["UPI", "NEFT", "IMPS", "ATM", "Mobile"][i % 5],
      is_active: true,
      is_fraud: 0,
      x: randBetween(40, 1760),
      y: randBetween(40, 1080),
      risk_score: randBetween(0.02, 0.18),
      early_status: "normal",
      risk_reasons: [],
      signal_breakdown: {},
      signal_count: 0,
    });
  }
  return accounts;
}

function pickDistinct(ids, n) {
  const pool = [...ids];
  const picked = [];
  while (pool.length && picked.length < n) {
    const idx = Math.floor(Math.random() * pool.length);
    picked.push(pool[idx]);
    pool.splice(idx, 1);
  }
  return picked;
}

function buildDemoSequence(kind, ids) {
  const safeIds = Array.isArray(ids) ? [...new Set(ids.map(String).filter(Boolean))] : [];
  if (safeIds.length < 2) {
    return [];
  }
  if (kind === "fan_out") {
    const [hub, ...leaf] = pickDistinct(safeIds, Math.min(6, safeIds.length));
    return leaf.map((to, i) => ({ source: hub, target: to, amount: 15000 + i * 2200, channel: "IMPS", timestamp: `${Date.now()}-${i}` }));
  }
  if (kind === "circular") {
    const ring = pickDistinct(safeIds, Math.min(6, safeIds.length));
    return ring.map((from, i) => ({ source: from, target: ring[(i + 1) % ring.length], amount: 12000 + i * 1500, channel: "UPI", timestamp: `${Date.now()}-${i}` }));
  }
  const [mule, ...feeders] = pickDistinct(safeIds, Math.min(6, safeIds.length));
  return feeders.map((from, i) => ({ source: from, target: mule, amount: 18000 + i * 2500, channel: "NEFT", timestamp: `${Date.now()}-${i}` }));
}

function buildDemoDashboard(accounts, attackName, fraudIds, earlyIds) {
  const table = fraudIds.map((id, i) => ({
    account_id: id,
    ml_score: Number((0.68 + i * 0.02).toFixed(4)),
    rule_score_norm: Number((0.61 + i * 0.02).toFixed(4)),
    final_score: Number((0.74 + i * 0.02).toFixed(4)),
    predicted_label: 1,
    gnn_score: Number((0.57 + i * 0.015).toFixed(4)),
    is_fraud: 1,
  }));
  return {
    available: true,
    is_detecting: false,
    detection_job: { status: "complete", attack_name: attackName, job_id: 1, error: null },
    attack_name: attackName,
    banned_accounts: [],
    gnn_available: true,
    rule_based: { high_count: Math.max(1, fraudIds.length - 2), medium_count: earlyIds.length, scored_count: accounts.length, table: [] },
    ml_detection: { fraud_flagged: fraudIds.length, precision: 0.91, recall: 0.88, threshold: 0.45, table },
    drift: { status: "warning", message: `${fraudIds.length} account(s) show behavioral drift.`, table: fraudIds.map((id) => ({ account_id: id, drift_score: 0.73, top_changes: "transaction_count, out_degree" })) },
    pattern_memory: { similarity: 0.63, patterns_stored: 6, message: "Variant of known pattern." },
    summary: { injected: fraudIds.length, detected: fraudIds.length, missed: 0 },
    early_cross_check: buildEmptyCrossCheck(),
    investigation_accounts: fraudIds,
    history: { threshold_history: [0.45, 0.46, 0.45, 0.44], fraud_history: [0.78, 0.82, 0.86, 0.9], role_totals: { "Ring Coordinator": 2, "Collector Mule": 3, "Distributor Mule": 3 } },
  };
}

function buildDemoBootstrapPayload() {
  const accounts = buildDemoAccounts(180);
  const live = {
    metrics: { tps: 0, tx_count: 0, fraud_count: 0, active_accounts: accounts.length, total_accounts: accounts.length, banned_count: 0, suspicious_count: 0 },
    threshold: 0.45,
    banned_accounts: [],
    fraud_accounts: [],
    early_warning: {
      status: "clear",
      message: "Monitoring live transaction stream.",
      count: 0,
      total_active: accounts.length,
      threshold: LIVE_WARNING_THRESHOLD,
      warning_pct: 8.0,
      distribution: accounts.map((a) => Number(a.risk_score || 0)).sort((a, b) => b - a).slice(0, 40),
      table: [],
    },
    detection_available: false,
    detection_job: { status: "idle", job_id: 0, attack_name: null, error: null },
  };
  const dashboard = {
    available: false,
    is_detecting: false,
    detection_job: { status: "idle", job_id: 0, attack_name: null, error: null },
  };
  return { status: "ok", live, dashboard, accounts, transactions: [], latest_attack: { attack_name: null, nodes: [], edges: [] } };
}

function stopDemoRuntime() {
  if (state.demoRuntimeTimer) {
    clearInterval(state.demoRuntimeTimer);
    state.demoRuntimeTimer = null;
  }
  state.demoScenario = null;
}

function demoUpdateEarlyWarning(accounts, messageOverride = "") {
  const warningThreshold = LIVE_WARNING_THRESHOLD;
  const earlyTable = accounts
    .filter((account) => account.is_active !== false && account.early_status === "early")
    .sort((a, b) => Number(b.risk_score || 0) - Number(a.risk_score || 0))
    .slice(0, 40)
    .map((account) => ({
      account_id: String(account.account_id),
      risk_score: Number(Number(account.risk_score || 0).toFixed(4)),
      status: "early",
      signal_count: Math.max(1, Number(account.signal_count || 0)),
      reasons: (account.risk_reasons || []).join(", ") || "Velocity spike",
    }));
  state.live.early_warning = {
    ...(state.live.early_warning || {}),
    status: earlyTable.length ? "warning" : "clear",
    message: messageOverride || (earlyTable.length
      ? `${earlyTable.length} suspicious account(s) are currently above the live adaptive threshold.`
      : "Risk is decaying below the live suspicious threshold."),
    count: earlyTable.length,
    total_active: Number(state.live?.metrics?.active_accounts || accounts.length),
    threshold: warningThreshold,
    warning_pct: 8.0,
    distribution: accounts
      .filter((account) => account.is_active !== false)
      .map((account) => Number(account.risk_score || 0))
      .sort((a, b) => b - a)
      .slice(0, 40),
    table: earlyTable,
  };
}

function demoPhaseAt(elapsedSec) {
  if (elapsedSec < 30) return PHASES.BUILD;
  if (elapsedSec < 34) return PHASES.ATTACK_FLOW;
  return PHASES.POST_ATTACK;
}

function buildDemoScenario(accounts) {
  const ids = accounts.map((account) => String(account.account_id)).sort();
  const attackKinds = ["fan_in", "fan_out", "circular"];
  const attackKind = attackKinds[state.demoRunIndex % attackKinds.length];
  state.demoRunIndex += 1;
  const fraudCandidatePool = pickDistinct(ids, Math.min(18, Math.max(10, Math.floor(ids.length * 0.14))));
  const noisePool = ids.filter((id) => !fraudCandidatePool.includes(id));
  const initialSuspiciousTarget = Math.min(12, ids.length);
  const initialCandidateCount = Math.min(fraudCandidatePool.length, Math.max(1, Math.round(initialSuspiciousTarget * 0.7)));
  const initialNoiseCount = Math.max(0, initialSuspiciousTarget - initialCandidateCount);
  const suspiciousIds = [
    ...fraudCandidatePool.slice(0, initialCandidateCount),
    ...noisePool.slice(0, initialNoiseCount),
  ];
  const fraudCount = Math.min(6, fraudCandidatePool.length);
  const fraudIds = fraudCandidatePool.slice(0, fraudCount);
  const attackNameMap = {
    fan_in: "Fan-In Pattern",
    fan_out: "Fan-Out Pattern",
    circular: "Circular Pattern",
  };
  return {
    startedAt: performance.now(),
    lastTickAt: performance.now(),
    lastTpsUpdateAt: performance.now(),
    tick: 0,
    txCounter: 0,
    txAccumulator: 0,
    txSecondAccumulator: 0,
    totalGeneratedTx: 0,
    currentTps: DEMO_TPS_MIN,
    targetTps: DEMO_TPS_MIN,
    phase: PHASES.BUILD,
    lastRenderedPhase: "",
    intelligenceShown: false,
    overlapPct: 100,
    attackKind,
    attackName: attackNameMap[attackKind] || "Attack Pattern",
    fraudCandidatePool,
    noisePool,
    suspiciousIds,
    fraudIds,
    attackTriggered: false,
    revealCompleted: false,
    revealDueAt: 0,
    pendingGraph: null,
    attackArmed: Boolean(state.demoAttackArmed),
    accountTxCounts: new Map(),
    accountSuspCounts: new Map(),
    scoreUpdateTick: 0,
    dynamicSuspiciousIds: [],
    dynamicSuspiciousScores: new Map(),
    monitoringCount: 0,
    monitoringCountFloat: 0,
    monitoringBase: 0,
    monitoringWavePhase: Math.random() * Math.PI * 2,
    crossCheck: null,
    forcedSeedDone: false,
    lastDebugAt: 0,
  };
}

function getAttackNameForKind(kind) {
  return {
    fan_in: "Fan-In Pattern",
    fan_out: "Fan-Out Pattern",
    circular: "Circular Pattern",
  }[kind] || "Attack Pattern";
}

function primeDemoAttackCycle(scenario, { advancePattern = true } = {}) {
  if (!scenario) {
    return null;
  }
  const activeUniverse = (state.lastAccounts || [])
    .filter((account) => account.is_active !== false)
    .map((account) => String(account.account_id))
    .sort();
  if (!activeUniverse.length) {
    return scenario;
  }

  if (advancePattern) {
    const attackKinds = ["fan_in", "fan_out", "circular"];
    scenario.attackKind = attackKinds[state.demoRunIndex % attackKinds.length];
    state.demoRunIndex += 1;
  }
  scenario.attackName = getAttackNameForKind(scenario.attackKind);
  scenario.fraudCandidatePool = pickDistinct(
    activeUniverse,
    Math.min(18, Math.max(10, Math.floor(activeUniverse.length * 0.14)))
  );
  scenario.noisePool = activeUniverse.filter((id) => !scenario.fraudCandidatePool.includes(id));

  const suspiciousTarget = Math.min(
    DEMO_SUSPICIOUS_SOFT_CAP,
    Math.max(DEMO_MIN_SUSPICIOUS + 4, Math.min(14, Math.round(activeUniverse.length * 0.08)))
  );
  const candidateCount = Math.min(
    scenario.fraudCandidatePool.length,
    Math.max(6, Math.round(suspiciousTarget * 0.68))
  );
  const noiseCount = Math.max(0, suspiciousTarget - candidateCount);
  scenario.suspiciousIds = [
    ...scenario.fraudCandidatePool.slice(0, candidateCount),
    ...scenario.noisePool.slice(0, noiseCount),
  ].slice(0, DEMO_SUSPICIOUS_SOFT_CAP);

  scenario.fraudIds = [];
  scenario.attackTriggered = false;
  scenario.revealCompleted = false;
  scenario.revealDueAt = 0;
  scenario.pendingGraph = null;
  scenario.phase = PHASES.BUILD;
  scenario.intelligenceShown = false;
  scenario.crossCheck = null;
  scenario.dynamicSuspiciousIds = [];
  scenario.dynamicSuspiciousScores = new Map();
  scenario.accountTxCounts = new Map();
  scenario.accountSuspCounts = new Map();
  scenario.scoreUpdateTick = 0;
  scenario.startedAt = performance.now();
  scenario.lastTickAt = performance.now();
  scenario.monitoringCount = Math.max(DEMO_MIN_SUSPICIOUS, Math.min(suspiciousTarget, scenario.suspiciousIds.length));
  scenario.monitoringCountFloat = Number(scenario.monitoringCount);
  scenario.monitoringBase = scenario.monitoringCount;
  scenario.monitoringWavePhase = Math.random() * Math.PI * 2;
  scenario.forcedSeedDone = false;
  return scenario;
}

function inferAttackKindFromGraph(data) {
  const attackName = String(data?.attack_name || "").toLowerCase();
  if (attackName.includes("fan-in")) return "fan_in";
  if (attackName.includes("fan-out")) return "fan_out";
  if (attackName.includes("circular")) return "circular";
  return "fan_out";
}

function buildAttackPatternLayout(data) {
  const edges = data?.edges || [];
  const nodeIds = [...new Set((data?.nodes || []).map((node) => String(node.id)).concat(
    edges.flatMap((edge) => [String(edge.source || edge.from || ""), String(edge.target || edge.to || "")])
  ).filter(Boolean))];
  const kind = inferAttackKindFromGraph(data);
  const layout = new Map();
  if (!nodeIds.length) {
    return { kind, layout };
  }

  const computeRingRadius = (count, minRadius, spacing = 108) => {
    if (count <= 1) {
      return minRadius;
    }
    const geometryRadius = spacing / (2 * Math.sin(Math.PI / count));
    const overflowBoost = count > 10 ? (count - 10) * 16 : 0;
    return Math.max(minRadius, geometryRadius + overflowBoost);
  };

  const buildCircularOrder = () => {
    const nextBySource = new Map();
    edges.forEach((edge) => {
      const source = String(edge.source || edge.from || "");
      const target = String(edge.target || edge.to || "");
      if (source && target && !nextBySource.has(source)) {
        nextBySource.set(source, target);
      }
    });
    const start = String(edges[0]?.source || edges[0]?.from || nodeIds[0] || "");
    if (!start) {
      return [...nodeIds];
    }
    const ordered = [];
    const visited = new Set();
    let current = start;
    while (current && !visited.has(current) && ordered.length < nodeIds.length) {
      ordered.push(current);
      visited.add(current);
      current = nextBySource.get(current);
    }
    nodeIds.forEach((nodeId) => {
      if (!visited.has(nodeId)) {
        ordered.push(nodeId);
      }
    });
    return ordered;
  };

  if (kind === "circular") {
    const orderedRing = buildCircularOrder();
    const radius = computeRingRadius(orderedRing.length, 210, 118);
    orderedRing.forEach((nodeId, index) => {
      const theta = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(orderedRing.length, 1));
      layout.set(nodeId, {
        x: Math.cos(theta) * radius,
        y: 0,
        z: Math.sin(theta) * radius,
      });
    });
    return { kind, layout };
  }

  const outDegree = new Map();
  const inDegree = new Map();
  edges.forEach((edge) => {
    const source = String(edge.source || edge.from || "");
    const target = String(edge.target || edge.to || "");
    if (!source || !target) return;
    outDegree.set(source, Number(outDegree.get(source) || 0) + 1);
    inDegree.set(target, Number(inDegree.get(target) || 0) + 1);
  });

  const hub = kind === "fan_in"
    ? [...inDegree.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
    : [...outDegree.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const leaves = nodeIds.filter((nodeId) => nodeId !== hub);

  if (kind === "fan_out") {
    const hubId = String(hub || nodeIds[0]);
    const orderedLeaves = leaves.length
      ? [...leaves].sort((left, right) => {
          const leftIndex = edges.findIndex((edge) => String(edge.target || edge.to || "") === left);
          const rightIndex = edges.findIndex((edge) => String(edge.target || edge.to || "") === right);
          return leftIndex - rightIndex;
        })
      : [];
    const radius = computeRingRadius(orderedLeaves.length || 1, 180, 116);
    layout.set(hubId, { x: 0, y: 0, z: 0 });
    orderedLeaves.forEach((nodeId, index) => {
      const theta = (-Math.PI / 2) + ((Math.PI * 2 * index) / Math.max(orderedLeaves.length, 1));
      layout.set(nodeId, {
        x: Math.cos(theta) * radius,
        y: 0,
        z: Math.sin(theta) * radius,
      });
    });
    return { kind, layout };
  }

  const hubX = kind === "fan_in" ? 210 : -210;
  const leafX = kind === "fan_in" ? -260 : 260;
  layout.set(String(hub || nodeIds[0]), { x: hubX, y: 0, z: 0 });
  leaves.forEach((nodeId, index) => {
    const ratio = leaves.length <= 1 ? 0.5 : index / (leaves.length - 1);
    const arc = (-0.92 + ratio * 1.84) * Math.PI * 0.5;
    layout.set(nodeId, {
      x: leafX + Math.cos(arc) * 120,
      y: Math.sin(arc) * 330,
      z: 0,
    });
  });
  return { kind, layout };
}

function clearCustomNodeLayouts() {
  const updates = [];
  state.liveNodes.get().forEach((node) => {
    if (node.layoutPosition) {
      updates.push({ id: String(node.id), layoutPosition: null });
    }
  });
  if (updates.length) {
    state.liveNodes.update(updates);
    updates.forEach((update) => {
      const account = state.accountStore.get(String(update.id));
      if (account) {
        state.accountStore.set(String(update.id), { ...account, layoutPosition: null });
      }
    });
    state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
  }
}

function applyAttackClusterLayout(data, status = "early") {
  const { layout } = buildAttackPatternLayout(data);
  if (!layout.size) {
    return [];
  }
  const nodeMap = new Map((data?.nodes || []).map((node) => [String(node.id), node]));
  const updates = [];
  layout.forEach((layoutPosition, nodeId) => {
    const existing = state.liveNodes.get(String(nodeId));
    if (!existing || existing.status === "banned") {
      return;
    }
    const nextStatus = existing.status === "fraud" ? "fraud" : status;
    const next = accountStyle(
      nodeId,
      nextStatus,
      {
        ...getNodeVisualPayload(existing, nodeMap.get(String(nodeId))),
        layoutPosition,
      }
    );
    if (existing.label) {
      next.label = existing.label;
    }
    updates.push(next);
    upsertAccountStore(nodeId, { layoutPosition });
  });
  if (updates.length) {
    state.liveNodes.update(updates);
    state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
  }
  return updates.map((node) => String(node.id));
}

function frameAttackCluster(nodeIds = [], durationMs = 760) {
  const ids = (nodeIds || []).map(String).filter(Boolean);
  if (!ids.length) {
    return;
  }
  pulseNetworkFrame(els.liveNetworkFrame);
  state.liveGraph3D?.focusNodesSmooth?.(ids, durationMs);
}

function frameReplayCluster(nodeIds = [], durationMs = 640) {
  const ids = (nodeIds || []).map(String).filter(Boolean);
  if (!ids.length) {
    return;
  }
  pulseNetworkFrame(els.attackNetworkFrame);
  state.attackGraph3D?.focusNodesSmooth?.(ids, durationMs);
}

function ensureDemoSuspiciousMinimum(scenario, elapsedSec = 0, forceSeed = false) {
  if (!scenario) return;
  const banned = new Set((state.live?.banned_accounts || []).map(String));
  const activeIds = new Set(
    (state.lastAccounts || [])
      .filter((account) => account.is_active !== false)
      .map((account) => String(account.account_id))
  );
  const candidatePool = (scenario.fraudCandidatePool || [])
    .map(String)
    .filter((id) => activeIds.has(id) && !banned.has(id));
  const noisePool = (scenario.noisePool || [])
    .map(String)
    .filter((id) => activeIds.has(id) && !banned.has(id) && !candidatePool.includes(id));
  const current = [...new Set((scenario.suspiciousIds || []).map(String))]
    .filter((id) => activeIds.has(id) && !banned.has(id));
  let merged = [...current];

  if (!scenario.forcedSeedDone && elapsedSec >= 5 && merged.length === 0) {
    const forcedCount = Math.min(5, Math.max(3, candidatePool.length || 3));
    merged = [...candidatePool.slice(0, forcedCount)];
    if (merged.length < forcedCount) {
      merged = [...merged, ...noisePool.slice(0, forcedCount - merged.length)];
    }
    scenario.forcedSeedDone = true;
  }

  if (merged.length < DEMO_MIN_SUSPICIOUS) {
    const needed = DEMO_MIN_SUSPICIOUS - merged.length;
    const fromCandidates = candidatePool.filter((id) => !merged.includes(id)).slice(0, needed);
    merged = [...merged, ...fromCandidates];
    if (merged.length < DEMO_MIN_SUSPICIOUS) {
      const fromNoise = noisePool
        .filter((id) => !merged.includes(id))
        .slice(0, DEMO_MIN_SUSPICIOUS - merged.length);
      merged = [...merged, ...fromNoise];
    }
  }

  if (forceSeed && merged.length < DEMO_MIN_SUSPICIOUS) {
    const fallbackUniverse = [...activeIds].filter((id) => !merged.includes(id));
    merged = [...merged, ...fallbackUniverse.slice(0, DEMO_MIN_SUSPICIOUS - merged.length)];
  }

  scenario.suspiciousIds = merged.slice(0, DEMO_SUSPICIOUS_SOFT_CAP);
  scenario.monitoringCount = Math.max(Number(scenario.monitoringCount || 0), Math.min(scenario.suspiciousIds.length, DEMO_SUSPICIOUS_SOFT_CAP));
}

function updateDemoSuspiciousMix(scenario, elapsedSec = 0) {
  if (!scenario) return;
  const banned = new Set((state.live?.banned_accounts || []).map(String));
  const activeIds = new Set(
    (state.lastAccounts || [])
      .filter((account) => account.is_active !== false)
      .map((account) => String(account.account_id))
  );
  const candidates = (scenario.fraudCandidatePool || [])
    .map(String)
    .filter((id) => activeIds.has(id) && !banned.has(id));
  const noise = (scenario.noisePool || [])
    .map(String)
    .filter((id) => activeIds.has(id) && !banned.has(id));
  const target = Math.max(0, Math.min(DEMO_SUSPICIOUS_SOFT_CAP, Number(scenario.monitoringCount || 0)));
  if (target <= 0) {
    scenario.suspiciousIds = [];
    return;
  }
  const candidateTake = Math.min(candidates.length, Math.max(1, Math.round(target * 0.72)));
  const noiseTake = Math.max(0, Math.min(noise.length, target - candidateTake));
  const candidateOffset = candidates.length ? (Math.floor(elapsedSec / 7) + scenario.tick) % candidates.length : 0;
  const noiseOffset = noise.length ? (Math.floor(elapsedSec / 11) + scenario.tick) % noise.length : 0;
  const orderedCandidates = candidates.length
    ? [...candidates.slice(candidateOffset), ...candidates.slice(0, candidateOffset)]
    : [];
  const orderedNoise = noise.length
    ? [...noise.slice(noiseOffset), ...noise.slice(0, noiseOffset)]
    : [];
  scenario.suspiciousIds = [
    ...orderedCandidates.slice(0, candidateTake),
    ...orderedNoise.slice(0, noiseTake),
  ];
}

function computeDemoCrossCheck(preAttackSuspicious = [], fraudNodes = []) {
  const suspicious = [...new Set((preAttackSuspicious || []).map(String))];
  const fraud = new Set((fraudNodes || []).map(String));
  const matched = suspicious.filter((id) => fraud.has(id));
  const sleeper = suspicious.filter((id) => !fraud.has(id));
  const allMatched = matched.length > 0 && matched.length === fraud.size;
  return {
    early_warned: suspicious.length,
    matched: matched.length,
    sleeper: sleeper.length,
    matched_accounts: matched,
    sleeper_accounts: sleeper,
    false_positive_accounts: sleeper,
    message: allMatched
      ? "All fraudulent accounts were detected before the attack"
      : matched.length > 0
        ? "Some fraudulent accounts were detected earlier"
        : "No fraudulent accounts were detected before the attack",
  };
}

function updateDemoCommandMessage(message, alarm = false) {
  els.attackAlertStrip.textContent = message;
  els.attackAlertStrip.classList.toggle("alarm", Boolean(alarm));
}

function getDemoPhaseConfig(phase) {
  const configs = {
    [PHASES.BUILD]: {
      message: "Phase: Build. Suspicious accounts are building gradually while transactions keep flowing.",
      tpsBase: 4.4,
      tpsSwing: 0.42,
    },
    [PHASES.ATTACK_FLOW]: {
      message: "Phase: Attack Flow. Attack transactions are executing, but fraud is not revealed yet.",
      tpsBase: 6.1,
      tpsSwing: 0.46,
    },
    [PHASES.FRAUD_REVEAL]: {
      message: "Phase: Fraud Reveal. Confirmed fraud is now locked into the graph and dashboard.",
      tpsBase: 4.3,
      tpsSwing: 0.24,
    },
    [PHASES.POST_ATTACK]: {
      message: "Phase: Post-attack. Fraud is locked in, but normal and suspicious money flow continues.",
      tpsBase: 3.8,
      tpsSwing: 0.28,
    },
  };
  return configs[phase] || configs[PHASES.BUILD];
}

function getSmoothDemoTps(scenario, elapsedSec) {
  const phaseConfig = getDemoPhaseConfig(scenario.phase);
  const waveA = Math.sin(elapsedSec * 0.34);
  const waveB = Math.sin(elapsedSec * 0.12 + 1.4) * 0.55;
  const target = phaseConfig.tpsBase + (waveA + waveB) * phaseConfig.tpsSwing;
  scenario.targetTps = THREE.MathUtils.clamp(target, DEMO_TPS_MIN, DEMO_TPS_MAX);
  scenario.currentTps = THREE.MathUtils.lerp(
    Number.isFinite(scenario.currentTps) ? scenario.currentTps : DEMO_TPS_MIN,
    scenario.targetTps,
    0.16
  );
  scenario.currentTps = THREE.MathUtils.clamp(scenario.currentTps, DEMO_TPS_MIN, DEMO_TPS_MAX);
  return scenario.currentTps;
}

function getVisibleSuspiciousIdsForPhase(scenario, phase, elapsedSec) {
  const suspiciousIds = scenario.suspiciousIds || [];
  const fraudIds = scenario.fraudIds || [];
  const dynamicIds = Array.isArray(scenario.dynamicSuspiciousIds) ? scenario.dynamicSuspiciousIds : [];
  if (!scenario.attackArmed) {
    const count = Math.max(0, Math.min(DEMO_SUSPICIOUS_SOFT_CAP, Number(scenario.monitoringCount || 0), suspiciousIds.length));
    return suspiciousIds.slice(0, count);
  }
  if (dynamicIds.length) {
    return dynamicIds
      .filter((id) => !fraudIds.includes(id))
      .slice(0, DEMO_SUSPICIOUS_HARD_CAP);
  }
  if (phase === PHASES.BUILD) {
    const progress = Math.max(0, Math.min(1, elapsedSec / 30));
    const count = Math.max(1, Math.min(suspiciousIds.length, Math.ceil(progress * suspiciousIds.length)));
    return suspiciousIds.slice(0, count);
  }
  if (phase === PHASES.ATTACK_FLOW) {
    return scenario.revealCompleted
      ? suspiciousIds.filter((id) => !fraudIds.includes(id))
      : suspiciousIds;
  }
  if (phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK) {
    const retained = suspiciousIds.filter((id) => !fraudIds.includes(id));
    return retained.length ? retained : suspiciousIds.slice(0, Math.min(3, suspiciousIds.length));
  }
  return suspiciousIds.filter((id) => !fraudIds.includes(id)).slice(0, DEMO_SUSPICIOUS_HARD_CAP);
}

function buildDemoAttackEdges(fraudIds, scenario, waveNumber) {
  if (!fraudIds.length) {
    return [];
  }
  const channels = ["UPI", "IMPS", "NEFT", "RTGS"];
  const edges = [];
  for (let i = 0; i < fraudIds.length; i += 1) {
    const from = fraudIds[i];
    const to = fraudIds[(i + 1) % fraudIds.length];
    edges.push({
      id: `demo-attack-${waveNumber}-${i}`,
      source: from,
      target: to,
      amount: 42000 + (waveNumber * 12000) + (i * 3600),
      channel: channels[(scenario.tick + i) % channels.length],
      timestamp: new Date().toISOString(),
    });
  }
  return edges;
}

function syncDemoDashboard(attackName = null) {
  const fraudIds = [...state.currentFraudIds].filter((id) => {
    const account = state.lastAccounts.find((item) => String(item.account_id) === String(id));
    return account?.is_active !== false;
  });
  const earlyIds = getSuspiciousIdsFromStore();
  const bannedAccounts = state.live?.banned_accounts || [];
  const dashboard = buildDemoDashboard(state.lastAccounts || [], attackName || state.finalizedAttackName || "Monitoring", fraudIds, earlyIds);
  dashboard.banned_accounts = [...bannedAccounts];
  dashboard.ml_detection.threshold = Number(state.liveSuspiciousSummary?.threshold || LIVE_WARNING_THRESHOLD);
  dashboard.summary.injected = fraudIds.length;
  dashboard.summary.detected = fraudIds.length;
  dashboard.summary.missed = 0;
  dashboard.early_cross_check = shouldRunCrossCheck()
    ? (state.demoScenario?.crossCheck || computeCrossCheckFromState(fraudIds))
    : buildEmptyCrossCheck();
  if (state.demoScenario?.intelligenceShown && shouldRunCrossCheck()) {
    dashboard.pattern_memory.message = `Early warning correctly predicted fraud before attack. Overlap ${state.demoScenario.overlapPct}%.`;
  }
  if (shouldRunCrossCheck() && state.demoScenario?.crossCheck?.message) {
    dashboard.pattern_memory.message = state.demoScenario.crossCheck.message;
  }
  renderDashboard(dashboard);
}

function applyDemoAttack() {
  const scenario = state.demoScenario;
  if (!scenario || scenario.attackTriggered) {
    return;
  }
  const activeFraudIds = scenario.fraudIds.filter((id) => !state.live?.banned_accounts?.includes(id));
  const capturedPreAttackSuspicious = capturePreAttackSnapshot();
  const attackEdges = buildDemoSequence(scenario.attackKind, activeFraudIds);
  const attackGraph = {
    attack_name: scenario.attackName,
    nodes: activeFraudIds.map((id) => {
      const account = state.lastAccounts.find((item) => String(item.account_id) === id);
      return {
        id,
        channel: account?.channel || "UPI",
        sus_score: Number(account?.risk_score || 0.88),
        reasons: ["Predicted suspicious before confirmed fraud"],
        x: account?.x,
        y: account?.y,
      };
    }),
    edges: attackEdges,
  };
  scenario.attackTriggered = true;
  scenario.crossCheck = null;
  scenario.pendingGraph = attackGraph;
  scenario.revealDueAt = performance.now() + ATTACK_TX_PHASE_MS;
  scenario.phase = PHASES.ATTACK_FLOW;
  state.pendingAttackNodes = new Set(activeFraudIds);
  state.activeAttackName = scenario.attackName;
  state.attackSequenceStage = "attack_tx";
  state.phase = PHASES.ATTACK_FLOW;
  state.subgraphCreated = false;
  state.latestAttackData = { attack_name: null, nodes: [], edges: [] };
  updateText("metric-attack-pattern", "Attack Flow");
  updateText("attack-replay-meta", `Attack transactions running: ${scenario.attackName}. Fraud reveal starts after this sequence.`);
  updateDemoCommandMessage(`Attack transactions in progress: ${scenario.attackName}. White-dot flows show suspicious movement before fraud reveal.`, false);
  const focusedIds = applyAttackClusterLayout(attackGraph, "early");
  frameAttackCluster(focusedIds.length ? focusedIds : activeFraudIds, 820);
  syncDemoDashboard(scenario.attackName);
}

function finalizeDemoAttackReveal() {
  const scenario = state.demoScenario;
  if (!scenario || !scenario.attackTriggered || scenario.revealCompleted || !scenario.pendingGraph) {
    return;
  }

  const activeFraudIds = scenario.fraudIds.filter((id) => !state.live?.banned_accounts?.includes(id));
  const snapshot = buildAttackSubgraphSnapshot(scenario.pendingGraph);
  state.attackTransactions = (scenario.pendingGraph.edges || []).map((edge) =>
    normalizeTransaction({
      sender: edge.source,
      receiver: edge.target,
      amount: edge.amount,
      channel: edge.channel,
      timestamp: edge.timestamp || new Date().toISOString(),
      isAttack: true,
    })
  );
  state.latestAttackData = snapshot;
  flashAttack(ATTACK_SIREN_MS);
  playSiren(ATTACK_SIREN_MS).catch(() => {});
  revealAttackCluster(scenario.pendingGraph);
  const focusedIds = applyAttackClusterLayout(scenario.pendingGraph, "fraud");
  freezeAttackSubgraph(snapshot);
  scenario.revealCompleted = true;
  scenario.phase = PHASES.FRAUD_REVEAL;
  state.detectionFinalized = true;
  state.finalizedAttackName = scenario.attackName;
  state.activeAttackName = scenario.attackName;
  state.phase = PHASES.FRAUD_REVEAL;
  state.attackSequenceStage = "revealed";
  state.subgraphCreated = true;
  state.live.fraud_accounts = [...new Set([...(state.live.fraud_accounts || []), ...activeFraudIds])];
  enforceFrontendMasterState({
    accounts: state.lastAccounts,
    live: state.live,
    forceMinimumSuspicious: true,
  });
  const crossCheck = computeCrossCheckFromState(state.live.fraud_accounts);
  scenario.crossCheck = crossCheck;
  state.live.metrics.fraud_count = state.live.fraud_accounts.length;
  state.live.metrics.tx_count = Number(state.live.metrics.tx_count || 0) + (scenario.pendingGraph.edges?.length || 0);
  updateText("metric-attack-pattern", scenario.attackName);
  updateText("attack-replay-meta", `Attack Detected: ${scenario.attackName}`);
  updateDemoCommandMessage(`Fraud reveal confirmed: ${scenario.attackName}. ${crossCheck.message}`, true);
  frameAttackCluster(focusedIds.length ? focusedIds : activeFraudIds, 900);
  frameReplayCluster(snapshot.nodes.map((node) => String(node.id)), 700);
  showToast(crossCheck.message, crossCheck.matched === activeFraudIds.length ? "success" : "info");
  const highlighted = crossCheck.matched_accounts || [];
  if (highlighted.length) {
    const boostedNodes = [];
    highlighted.forEach((id) => {
      const node = state.liveNodes.get(String(id));
      if (!node || node.status === "banned") return;
      boostedNodes.push({ id: String(id), size: Math.max(Number(node.size || 24), 44) });
    });
    if (boostedNodes.length) {
      state.liveNodes.update(boostedNodes);
      state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
      window.setTimeout(() => {
        const restore = boostedNodes
          .map((entry) => state.liveNodes.get(entry.id))
          .filter(Boolean)
          .map((node) => ({ id: node.id, size: Number(node.baseSize || node.size || 24) }));
        if (restore.length) {
          state.liveNodes.update(restore);
          state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
        }
      }, 1400);
    }
  }
  recordFraudTransactions(scenario.pendingGraph.edges || []);
  syncDemoDashboard(scenario.attackName);
}

async function applyBanAccounts(selected = [], options = {}) {
  const {
    resetAttack = true,
    message = `Banned ${selected.length} account(s).`,
    alarm = false,
    clearLatestAttack = true,
    showToastMessage = false,
  } = options;
  const normalizedSelected = [...new Set(
    []
      .concat(selected || [])
      .flatMap((value) => String(value || "").split(","))
      .map((value) => value.trim())
      .filter(Boolean)
  )];
  if (!normalizedSelected.length) {
    return;
  }
  stopAttackAnimation();
  clearPersistentAttackEdges();
  removeConnectedEdges(normalizedSelected);
  markNodesBanned(normalizedSelected);
  state.fraudEdgeSet.clear();
  normalizedSelected.forEach((accountId) => {
    const normalizedId = String(accountId);
    state.fraudNodeSet.delete(normalizedId);
    state.confirmedAttackNodes.delete(normalizedId);
    state.currentFraudIds.delete(normalizedId);
    state.currentEarlyIds.delete(normalizedId);
  });
  state.preAttackSnapshot = (state.preAttackSnapshot || []).filter(
    (accountId) => !normalizedSelected.includes(String(accountId))
  );
  state.preAttackSuspiciousIds = [...state.preAttackSnapshot];
  state.attackTransactions = (state.attackTransactions || []).filter((tx) => {
    const sender = String(tx.sender || tx.source || "");
    const receiver = String(tx.receiver || tx.target || "");
    return !normalizedSelected.includes(sender) && !normalizedSelected.includes(receiver);
  });
  state.suspiciousFeed = state.suspiciousFeed.filter((row) => {
    const title = String(row.title || "");
    return !normalizedSelected.some((accountId) => title.includes(String(accountId)));
  });
  if (Array.isArray(state.lastAccounts) && state.lastAccounts.length) {
    state.lastAccounts = state.lastAccounts.map((account) =>
      normalizedSelected.includes(String(account.account_id))
        ? { ...account, is_active: false, is_fraud: 0, status: "banned", early_status: "banned", risk_score: 0.02, risk_reasons: ["Account blocked after confirmed fraud"], signal_count: 0 }
        : account
    );
  }
  if (state.demoScenario) {
    const bannedSet = new Set(normalizedSelected.map(String));
    state.demoScenario.fraudCandidatePool = (state.demoScenario.fraudCandidatePool || []).filter((id) => !bannedSet.has(String(id)));
    state.demoScenario.noisePool = (state.demoScenario.noisePool || []).filter((id) => !bannedSet.has(String(id)));
    const activeUniverse = (state.lastAccounts || [])
      .filter((account) => account.is_active !== false)
      .map((account) => String(account.account_id))
      .filter((id) => !bannedSet.has(id));
    const existingCandidate = new Set((state.demoScenario.fraudCandidatePool || []).map(String));
    const refill = activeUniverse.filter((id) => !existingCandidate.has(id));
    while ((state.demoScenario.fraudCandidatePool || []).length < Math.min(18, Math.max(10, Math.floor(activeUniverse.length * 0.14))) && refill.length) {
      state.demoScenario.fraudCandidatePool.push(refill.shift());
    }
    state.demoScenario.noisePool = activeUniverse.filter((id) => !(state.demoScenario.fraudCandidatePool || []).includes(id));
    state.demoScenario.suspiciousIds = (state.demoScenario.suspiciousIds || []).filter((id) => !bannedSet.has(String(id)));
    state.demoScenario.dynamicSuspiciousIds = (state.demoScenario.dynamicSuspiciousIds || []).filter((id) => !bannedSet.has(String(id)));
    state.demoScenario.monitoringCount = Math.max(0, (state.demoScenario.suspiciousIds || []).length);
    state.demoScenario.monitoringCountFloat = state.demoScenario.monitoringCount;
  }
  if (state.live) {
    const bannedAccounts = new Set([...(state.live.banned_accounts || []), ...normalizedSelected.map(String)]);
    state.live = {
      ...state.live,
      banned_accounts: [...bannedAccounts],
      fraud_accounts: (state.live.fraud_accounts || []).filter(
        (accountId) => !normalizedSelected.includes(String(accountId))
      ),
    };
    enforceFrontendMasterState({
      accounts: state.lastAccounts,
      live: state.live,
      forceMinimumSuspicious: true,
    });
    rebuildSuspiciousSummaryFromLiveNodes(state.live);
    syncLiveMetricsFromGraph();
    renderLiveMetrics(state.live, state.dashboard);
    renderEarlyWarning(state.live);
  }
  setBanSelection([]);
  updateBanSelectOptions();
  if (state.demoScenario && shouldRunCrossCheck()) {
    state.demoScenario.crossCheck = computeCrossCheckFromState(getFraudIdsFromStore());
  }
  if (clearLatestAttack) {
    clearAttackReplayState({ resetLatest: true });
  }
  if (resetAttack) {
    state.activeAttackName = null;
    state.pendingAttackNodes = new Set();
    state.detectionFinalized = false;
    state.finalizedAttackName = null;
    state.attackSequenceStage = "idle";
    state.demoAttackArmed = false;
    if (state.demoScenario) {
      state.demoScenario.attackArmed = false;
      state.demoScenario.attackTriggered = false;
      state.demoScenario.revealCompleted = false;
      state.demoScenario.intelligenceShown = false;
      state.demoScenario.pendingGraph = null;
      state.demoScenario.revealDueAt = 0;
      state.demoScenario.startedAt = performance.now();
      state.demoScenario.lastTickAt = performance.now();
      state.demoScenario.suspiciousIds = pickDistinct(
        (state.lastAccounts || [])
          .filter((account) => account.is_active !== false)
          .map((account) => String(account.account_id))
          .sort(),
        Math.min(12, (state.lastAccounts || []).length)
      );
      const activeUniverse = (state.lastAccounts || [])
        .filter((account) => account.is_active !== false)
        .map((account) => String(account.account_id))
        .sort();
      state.demoScenario.fraudCandidatePool = pickDistinct(
        activeUniverse,
        Math.min(18, Math.max(10, Math.floor(activeUniverse.length * 0.14)))
      );
      state.demoScenario.noisePool = activeUniverse.filter((id) => !state.demoScenario.fraudCandidatePool.includes(id));
      state.demoScenario.fraudIds = [];
      state.demoScenario.accountTxCounts = new Map();
      state.demoScenario.accountSuspCounts = new Map();
      state.demoScenario.scoreUpdateTick = 0;
      state.demoScenario.dynamicSuspiciousIds = [];
      state.demoScenario.dynamicSuspiciousScores = new Map();
      state.demoScenario.crossCheck = null;
      state.demoScenario.monitoringCount = Math.min(8, Math.max(0, Math.round(Number(state.demoScenario.monitoringCount || 0) * 0.45)));
      state.demoScenario.monitoringCountFloat = state.demoScenario.monitoringCount;
      state.demoScenario.monitoringBase = state.demoScenario.monitoringCount;
      state.demoScenario.monitoringWavePhase = Math.random() * Math.PI * 2;
    }
    updateText("metric-attack-pattern", "Monitoring");
  }
  validateSystemState();
  if (DEMO_SIM_MODE && state.dashboard?.available) {
    syncDemoDashboard(state.activeAttackName || state.finalizedAttackName || "Monitoring");
  }
  updateDemoCommandMessage(message, alarm);
  console.debug("[BAN_EXECUTED]", { selected: normalizedSelected, bannedCount: state.live?.banned_accounts?.length || 0 });
  if (showToastMessage) {
    showToast(message, "success");
  }
}

function maybeAdvanceDemoTimeline(elapsedSec) {
  const scenario = state.demoScenario;
  if (!scenario) {
    return;
  }
  if (!scenario.attackArmed) {
    scenario.phase = PHASES.BUILD;
    state.phase = PHASES.BUILD;
    const maxCount = Math.min(DEMO_SUSPICIOUS_SOFT_CAP, (scenario.suspiciousIds || []).length);
    const trendCap = Math.max(0, maxCount - Number(scenario.monitoringBase || 0));
    const trend = Number(scenario.monitoringBase || 0) + Math.min(trendCap, elapsedSec * 0.17);
    const wavePrimary = Math.sin(elapsedSec * 0.45 + Number(scenario.monitoringWavePhase || 0)) * 2.2;
    const waveSecondary = Math.sin(elapsedSec * 0.17 + 1.35) * 1.15;
    const target = THREE.MathUtils.clamp(trend + wavePrimary + waveSecondary, 0, maxCount);
    scenario.monitoringCountFloat = THREE.MathUtils.lerp(
      Number.isFinite(Number(scenario.monitoringCountFloat)) ? Number(scenario.monitoringCountFloat) : 0,
      target,
      0.12
    );
    scenario.monitoringCount = Math.max(0, Math.min(maxCount, Math.round(scenario.monitoringCountFloat)));
    updateDemoSuspiciousMix(scenario, elapsedSec);
    ensureDemoSuspiciousMinimum(scenario, elapsedSec, false);
    return;
  }
  const now = performance.now();
  const phase = demoPhaseAt(elapsedSec);
  if (phase !== scenario.phase && !(scenario.revealCompleted && phase === PHASES.POST_ATTACK && scenario.phase === PHASES.FRAUD_REVEAL)) {
    scenario.phase = phase;
    const phaseConfig = getDemoPhaseConfig(phase);
    updateDemoCommandMessage(phaseConfig.message, phase === PHASES.ATTACK_FLOW || phase === PHASES.FRAUD_REVEAL);
  }
  if (phase === PHASES.ATTACK_FLOW && !scenario.attackTriggered) {
    applyDemoAttack();
  }
  if (scenario.attackTriggered && !scenario.revealCompleted && now >= Number(scenario.revealDueAt || 0)) {
    finalizeDemoAttackReveal();
  }
  if (phase === PHASES.POST_ATTACK && !scenario.intelligenceShown && scenario.revealCompleted) {
    scenario.intelligenceShown = true;
    const suspiciousUniverse = new Set(scenario.suspiciousIds || []);
    const fraudUniverse = new Set(scenario.fraudIds || []);
    const overlap = [...fraudUniverse].filter((id) => suspiciousUniverse.has(id)).length;
    scenario.overlapPct = fraudUniverse.size ? Math.round((overlap / fraudUniverse.size) * 100) : 0;
    const intelligenceMessage = `Early Warning System correctly predicted mule accounts before attack. Overlap: ${scenario.overlapPct}% (${overlap}/${fraudUniverse.size}).`;
    updateDemoCommandMessage("SUSPICIOUS ACCOUNTS SUCCESSFULLY IDENTIFIED BEFORE FRAUD ATTACK", true);
    els.patternMessage.textContent = intelligenceMessage;
    updateText("attack-replay-meta", intelligenceMessage);
  }

  state.phase = scenario.phase;
}

function applyDemoAccountStatuses(elapsedSec) {
  const scenario = state.demoScenario;
  if (!scenario) {
    return;
  }
  const phase = scenario.phase || state.phase || demoPhaseAt(elapsedSec);
  const suspiciousIds = phase === PHASES.BUILD || phase === PHASES.ATTACK_FLOW || phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK
    ? new Set(getVisibleSuspiciousIdsForPhase(scenario, phase, elapsedSec))
    : new Set();
  const fraudIds = new Set([
    ...(state.live?.fraud_accounts || []),
    ...state.fraudList,
    ...state.fraudNodeSet,
  ].map(String));
  const bannedIds = new Set(state.live?.banned_accounts || []);
  state.lastAccounts.forEach((account, index) => {
    const id = String(account.account_id);
    const baselineRisk = 0.04 + ((index % 11) * 0.008);
    if (bannedIds.has(id) || account.is_active === false) {
      account.is_active = false;
      account.is_fraud = 0;
      account.early_status = "banned";
      account.risk_score = 0.02;
      account.risk_reasons = ["Blocked by admin response"];
      account.signal_count = 0;
      state.demoRiskMap.set(id, 0.02);
      return;
    }
    if (fraudIds.has(id)) {
      const fraudRisk = 0.88 + ((index % 4) * 0.025);
      account.is_fraud = 1;
      account.early_status = "fraud";
      account.risk_score = Number(Math.min(0.98, fraudRisk).toFixed(4));
      account.risk_reasons = ["Predicted suspicious before confirmed fraud", "Attack-path transaction observed"];
      account.signal_count = 4;
      state.demoRiskMap.set(id, account.risk_score);
      return;
    }
    if (suspiciousIds.has(id)) {
      const suspiciousRank = [...suspiciousIds].indexOf(id);
      const dynamicScore = Number(scenario.dynamicSuspiciousScores?.get(id) || 0);
      const baseRisk = 0.42 + Math.max(0, suspiciousRank) * 0.012;
      const dynamicLift = Math.min(0.24, dynamicScore * 0.32);
      const pulse = (Math.sin((scenario.tick + index) * 0.24) + 1) * 0.016;
      const suspiciousRisk = baseRisk + dynamicLift + pulse;
      account.is_fraud = 0;
      account.early_status = "early";
      account.risk_score = Number(Math.min(0.72, suspiciousRisk).toFixed(4));
      account.risk_reasons = ["High transaction velocity", "Connected to suspicious flow"];
      account.signal_count = Math.max(2, Math.min(6, 2 + Math.round(dynamicScore * 5)));
      state.demoRiskMap.set(id, account.risk_score);
      return;
    }
    const previousRisk = Number(state.demoRiskMap.get(id) || baselineRisk);
    const cooledRisk = Math.max(baselineRisk, previousRisk * 0.958);
    account.is_fraud = 0;
    account.early_status = "normal";
    account.risk_score = Number(cooledRisk.toFixed(4));
    account.risk_reasons = [];
    account.signal_count = 0;
    state.demoRiskMap.set(id, account.risk_score);
  });
  state.live.fraud_accounts = [...fraudIds];
  state.live.metrics.suspicious_count = suspiciousIds.size;
  demoUpdateEarlyWarning(
    state.lastAccounts,
    phase === PHASES.BUILD
      ? "Monitoring live transaction stream."
      : phase === PHASES.ATTACK_FLOW
        ? "Suspicious accounts were identified before fraud activation."
        : getDemoPhaseConfig(phase).message
  );
}

function buildDemoTransactionBatch(elapsedSec, txCount) {
  const scenario = state.demoScenario;
  if (!scenario) {
    return [];
  }
  const phase = scenario.phase || state.phase || demoPhaseAt(elapsedSec);
  const activeIds = state.lastAccounts
    .filter((account) => account.is_active !== false)
    .map((account) => String(account.account_id))
    .sort();
  if (activeIds.length < 2) {
    return [];
  }
  if (state.phase === PHASES.IDLE) {
    return [];
  }
  const focusIds = phase === PHASES.BUILD || phase === PHASES.ATTACK_FLOW || phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK
    ? getVisibleSuspiciousIdsForPhase(scenario, phase, elapsedSec)
    : [];
  const txs = [];
  for (let i = 0; i < txCount; i += 1) {
    const useFocus = focusIds.length > 0 && (i % 2 === 0 || phase === PHASES.ATTACK_FLOW || phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK);
    const senderPool = useFocus ? focusIds : activeIds;
    const sender = senderPool[(scenario.tick + i) % senderPool.length];
    const receiverPool = phase === PHASES.ATTACK_FLOW && !scenario.revealCompleted && focusIds.length > 1
      ? focusIds
      : activeIds;
    const receiver = receiverPool[(scenario.tick + i + 5 + waveOffsetForPhase(phase)) % receiverPool.length];
    if (!sender || !receiver || sender === receiver) {
      continue;
    }
    const amountBase = phase === PHASES.BUILD ? 9400 : phase === PHASES.ATTACK_FLOW ? 28000 : 9400;
    const amount = amountBase + (((scenario.tick + i) % 7) * 1750);
    const channel = ["UPI", "IMPS", "NEFT", "ATM", "Mobile"][(scenario.tick + i) % 5];
    const baseSuspiciousChance =
      phase === PHASES.ATTACK_FLOW
        ? 0.42
        : phase === PHASES.BUILD
          ? 0.18
          : phase === PHASES.POST_ATTACK || phase === PHASES.FRAUD_REVEAL
            ? 0.16
            : 0.08;
    const involvesFraudNode = scenario.revealCompleted && (state.currentFraudIds.has(sender) || state.currentFraudIds.has(receiver));
    const amountBoost = amount >= 22000 ? 0.16 : amount >= 14000 ? 0.08 : 0;
    const channelBoost = channel === "UPI" || channel === "IMPS" ? 0.04 : 0;
    const suspiciousChance = Math.min(0.94, baseSuspiciousChance + amountBoost + channelBoost + (involvesFraudNode ? 0.28 : 0));
    const suspicious = Math.random() < suspiciousChance;
    txs.push({
      transaction_id: `DTX-${scenario.tick}-${scenario.txCounter += 1}`,
      sender,
      receiver,
      amount,
      channel,
      timestamp: new Date().toISOString(),
      is_attack: phase === PHASES.ATTACK_FLOW && !scenario.revealCompleted,
      suspicious,
    });
  }
  return txs;
}

function bumpTxCounter(map, key, delta) {
  const current = Number(map.get(key) || 0) + delta;
  if (current <= 0) {
    map.delete(key);
  } else {
    map.set(key, current);
  }
}

function updateDemoSuspiciousFromWindow(scenario, generated) {
  if (!scenario) return;
  scenario.scoreUpdateTick = Number(scenario.scoreUpdateTick || 0) + 1;
  if ((scenario.scoreUpdateTick % 7) === 0) {
    const applyDecay = (map) => {
      map.forEach((value, accountId) => {
        const next = Number(value || 0) * DEMO_STREAM_DECAY;
        if (next < 0.05) map.delete(accountId);
        else map.set(accountId, next);
      });
    };
    applyDecay(scenario.accountTxCounts);
    applyDecay(scenario.accountSuspCounts);
  }
  const fraudIds = new Set(state.live?.fraud_accounts || []);
  const liveTps = Math.max(DEMO_TPS_MIN, Number(state.live?.metrics?.tps || state.visibleTps || DEMO_TPS_MIN));
  const streamIntensity = THREE.MathUtils.clamp(liveTps / DEMO_TPS_MAX, 0.45, 1);
  generated.forEach((tx) => {
    const sender = String(tx.sender || "");
    const receiver = String(tx.receiver || "");
    if (!sender || !receiver || sender === receiver) return;
    const weightedSuspicious = Boolean(tx.suspicious) || fraudIds.has(sender) || fraudIds.has(receiver);
    bumpTxCounter(scenario.accountTxCounts, sender, 1 * streamIntensity);
    bumpTxCounter(scenario.accountTxCounts, receiver, 1 * streamIntensity);
    if (weightedSuspicious) {
      const suspiciousWeight = (fraudIds.has(sender) || fraudIds.has(receiver)) ? 1.8 : 1.25;
      bumpTxCounter(scenario.accountSuspCounts, sender, suspiciousWeight * streamIntensity);
      bumpTxCounter(scenario.accountSuspCounts, receiver, suspiciousWeight * streamIntensity);
    }
  });

  const banned = new Set(state.live?.banned_accounts || []);
  const suspiciousCandidates = [];
  const fallbackCandidates = [];
  scenario.accountTxCounts.forEach((totalTx, accountId) => {
    if (banned.has(accountId) || totalTx < DEMO_SUSPICIOUS_MIN_TOTAL) return;
    const suspiciousTx = Number(scenario.accountSuspCounts.get(accountId) || 0);
    const ratio = suspiciousTx / Math.max(totalTx, 1);
    const score = (ratio * 0.76) + (Math.min(1, suspiciousTx / 10) * 0.24);
    if (suspiciousTx >= DEMO_SUSPICIOUS_MIN_SIGNAL && ratio >= 0.2) {
      suspiciousCandidates.push({ accountId, score });
    }
    if (suspiciousTx > 0.3 || ratio > 0.11) {
      fallbackCandidates.push({ accountId, score: (ratio * 0.62) + (Math.min(1, suspiciousTx / 8) * 0.38) });
    }
  });
  suspiciousCandidates.sort((a, b) => b.score - a.score);
  fallbackCandidates.sort((a, b) => b.score - a.score);
  const primary = suspiciousCandidates.slice(0, DEMO_SUSPICIOUS_HARD_CAP).map((item) => item.accountId);
  const fallback = fallbackCandidates.slice(0, Math.min(8, DEMO_SUSPICIOUS_SOFT_CAP)).map((item) => item.accountId);
  const scoreMap = new Map();
  suspiciousCandidates.slice(0, 48).forEach((item) => scoreMap.set(String(item.accountId), Number(item.score || 0)));
  fallbackCandidates.slice(0, 24).forEach((item) => {
    const key = String(item.accountId);
    if (!scoreMap.has(key)) {
      scoreMap.set(key, Number(item.score || 0));
    }
  });
  scenario.dynamicSuspiciousScores = scoreMap;
  const candidateSet = new Set((scenario.fraudCandidatePool || []).map(String));
  const dynamicCombined = primary.length
    ? primary
    : fallback.length
      ? fallback
      : (scenario.suspiciousIds || []).slice(0, Math.min(6, (scenario.suspiciousIds || []).length));
  const candidateFirst = dynamicCombined.filter((id) => candidateSet.has(String(id)));
  const noiseOnly = dynamicCombined.filter((id) => !candidateSet.has(String(id)));
  scenario.dynamicSuspiciousIds = [
    ...candidateFirst.slice(0, DEMO_SUSPICIOUS_HARD_CAP),
    ...noiseOnly.slice(0, Math.max(0, Math.min(5, DEMO_SUSPICIOUS_HARD_CAP - candidateFirst.length))),
  ].slice(0, DEMO_SUSPICIOUS_HARD_CAP);
}

function waveOffsetForPhase(phase) {
  if (phase === PHASES.BUILD) return 2;
  if (phase === PHASES.ATTACK_FLOW) return 5;
  if (phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK) return 7;
  return 1;
}

function runDemoRuntimeTick() {
  if (!DEMO_SIM_MODE || !Array.isArray(state.lastAccounts) || !state.lastAccounts.length || !state.live || !state.demoScenario) {
    return;
  }
  const scenario = state.demoScenario;
  const now = performance.now();
  const deltaSec = Math.max(0.05, (now - scenario.lastTickAt) / 1000);
  scenario.lastTickAt = now;
  scenario.tick += 1;
  const elapsedSec = (now - scenario.startedAt) / 1000;
  maybeAdvanceDemoTimeline(elapsedSec);
  ensureDemoSuspiciousMinimum(scenario, elapsedSec, false);
  applyDemoAccountStatuses(elapsedSec);
  const smoothTps = getSmoothDemoTps(scenario, elapsedSec);
  scenario.txSecondAccumulator += deltaSec;
  const generated = [];
  while (scenario.txSecondAccumulator >= 1) {
    scenario.txSecondAccumulator -= 1;
    const txForSecond = Math.max(DEMO_TPS_MIN, Math.min(DEMO_TPS_MAX, Math.round(smoothTps)));
    const batch = buildDemoTransactionBatch(elapsedSec, txForSecond);
    if (batch.length) {
      generated.push(...batch);
    }
  }
  if (generated.length) {
    queueTransactions(generated);
    scenario.totalGeneratedTx += generated.length;
    generated.forEach(() => state.demoTxTimestamps.push(now));
    updateDemoSuspiciousFromWindow(scenario, generated);
  }
  const cutoff = now - 1000;
  while (state.demoTxTimestamps.length && state.demoTxTimestamps[0] < cutoff) {
    state.demoTxTimestamps.shift();
  }
  const activeCount = state.lastAccounts.filter((account) => account.is_active !== false).length;
  const bannedCount = state.lastAccounts.length - activeCount;
  state.live.metrics.tx_count = Number(scenario.totalGeneratedTx || 0);
  if (now - scenario.lastTpsUpdateAt >= 1000) {
    state.live.metrics.tps = Number(smoothTps.toFixed(2));
    scenario.lastTpsUpdateAt = now;
  }
  state.live.metrics.active_accounts = activeCount;
  state.live.metrics.total_accounts = state.lastAccounts.length;
  state.live.metrics.banned_count = bannedCount;
  state.live.metrics.fraud_count = (state.live.fraud_accounts || []).length;
  updateLiveNetwork(state.lastAccounts, state.live);
  if (state.dashboard?.available) {
    syncDemoDashboard();
  }
  if (!scenario.lastDebugAt || now - scenario.lastDebugAt >= 1000) {
    scenario.lastDebugAt = now;
    const suspiciousNow = Number(state.live?.metrics?.suspicious_count || 0);
    console.debug("[SUSPICIOUS_DEBUG]", {
      suspicious_count: suspiciousNow,
      candidate_pool_size: (scenario.fraudCandidatePool || []).length,
      phase: scenario.phase,
    });
    if (elapsedSec > 5 && suspiciousNow === 0) {
      console.error("[SUSPICIOUS_ERROR] suspicious_count is 0 after warm-up");
    }
  }
}

function startDemoRuntime(armAttack = false) {
  if (!DEMO_SIM_MODE) return;
  stopDemoRuntime();
  resetAttackState();
  clearAllTravelerOverlays();
  if (state.liveEdges.length) {
    const edgeIds = state.liveEdges.getIds();
    state.liveEdges.remove(edgeIds);
    edgeIds.forEach((edgeId) => removeGraphEdge("live", edgeId));
  }
  state.activeTravelers = [];
  state.transactionQueue = [];
  state.transactionQueueCursor = 0;
  state.visibleTxTimestamps = [];
  state.visibleTps = 0;
  state.demoTxTimestamps = [];
  state.demoRiskMap = new Map();
  (state.lastAccounts || []).forEach((account, index) => {
    const baselineRisk = Number((0.03 + (index % 9) * 0.01).toFixed(4));
    account.is_active = true;
    account.is_fraud = 0;
    account.early_status = "normal";
    account.risk_score = baselineRisk;
    account.risk_reasons = [];
    account.signal_count = 0;
    state.demoRiskMap.set(String(account.account_id), baselineRisk);
  });
  state.demoScenario = buildDemoScenario(state.lastAccounts || []);
  state.demoScenario.attackArmed = Boolean(armAttack);
  state.demoScenario.txSecondAccumulator = 1;
  state.live.fraud_accounts = [];
  state.live.banned_accounts = [];
  state.phase = PHASES.BUILD;
  state.detectionFinalized = false;
  state.fraudNodeSet = new Set();
  state.currentFraudIds = new Set();
  state.currentEarlyIds = new Set();
  state.accounts = {};
  state.suspiciousList = [];
  state.fraudList = [];
  state.bannedList = [];
  state.live.metrics.tx_count = 0;
  state.live.metrics.fraud_count = 0;
  state.live.metrics.banned_count = 0;
  state.live.metrics.suspicious_count = 0;
  state.live.metrics.active_accounts = (state.lastAccounts || []).length;
  state.live.metrics.total_accounts = (state.lastAccounts || []).length;
  state.live.metrics.tps = DEMO_TPS_MIN;
  els.patternMessage.textContent = "";
  updateText("attack-replay-meta", armAttack
    ? "Build phase active. Suspicious activity is building before attack confirmation."
    : "Monitoring mode active. Transactions are running; click Simulate Attack to arm warning/attack phases.");
  updateDemoCommandMessage(armAttack
    ? "Phase: Build. Transactions are running continuously while suspicious accounts build gradually."
    : "Monitoring mode: transactions and suspicious scoring are live. Click Simulate Attack to arm the attack timeline.", false);
  updateText("metric-attack-pattern", "Baseline");
  updateLiveNetwork(state.lastAccounts, state.live);
  state.demoRuntimeTimer = setInterval(runDemoRuntimeTick, DEMO_RUNTIME_INTERVAL_MS);
  ensureVisualLoop();
}

const els = {
  loader: document.getElementById("global-loader"),
  loaderText: document.getElementById("loader-text"),
  toastStack: document.getElementById("toast-stack"),
  apiStatusDot: document.getElementById("api-status-dot"),
  apiStatusText: document.getElementById("api-status-text"),
  postDetection: document.getElementById("post-detection"),
  txFeed: document.getElementById("tx-feed"),
  suspiciousFeed: document.getElementById("suspicious-feed"),
  earlyWarningTable: document.getElementById("early-warning-table"),
  driftTable: document.getElementById("drift-table"),
  ruleTable: document.getElementById("rule-table"),
  mlTable: document.getElementById("ml-table"),
  shapTable: document.getElementById("shap-table"),
  crossCheckList: document.getElementById("cross-check-list"),
  banSelect: document.getElementById("ban-select"),
  banSelectAllBtn: document.getElementById("ban-select-all-btn"),
  investigationSelect: document.getElementById("investigation-select"),
  attackReplayMeta: document.getElementById("attack-replay-meta"),
  attackAlertStrip: document.getElementById("attack-alert-strip"),
  attackPattern: document.getElementById("metric-attack-pattern"),
  banChip: document.getElementById("ban-chip"),
  driftChip: document.getElementById("drift-chip"),
  gnnChip: document.getElementById("gnn-chip"),
  investigationAlert: document.getElementById("investigation-alert"),
  bannedAccountsList: document.getElementById("banned-accounts-list"),
  patternMessage: document.getElementById("pattern-message"),
  detectionPattern: document.getElementById("detection-pattern"),
  shapExplanations: document.getElementById("shap-explanations"),
  muteSirenBtn: document.getElementById("mute-siren-btn"),
  postDetectionLoader: document.getElementById("post-detection-loader"),
  simulateAttackBtn: document.getElementById("simulate-attack-btn"),
  simulateAttackBtnSecondary: document.getElementById("simulate-attack-btn-secondary"),
  earlyWarningDetails: document.getElementById("early-warning-details"),
  earlyWarningExplainer: document.getElementById("early-warning-explainer"),
  earlyWarningExplainerIntro: document.getElementById("early-warning-explainer-intro"),
  liveNetworkShell: document.getElementById("live-network"),
  liveNetworkFrame: document.getElementById("live-network-frame"),
  liveNetworkOverlay: document.getElementById("live-network-overlay"),
  attackNetworkShell: document.getElementById("attack-network"),
  attackNetworkFrame: document.getElementById("attack-network-frame"),
  attackNetworkOverlay: document.getElementById("attack-network-overlay"),
  mainGraphStage: document.querySelector(".full-bleed-stage--main"),
  replayGraphStage: document.querySelector(".full-bleed-stage--replay"),
};

class ThreeGraphAdapter {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = null;
    this.scene.fog = new THREE.FogExp2(0x06150f, 0.00016);
    this.camera = new THREE.PerspectiveCamera(GRAPH_CAMERA_FOV, 1, GRAPH_CAMERA_NEAR, GRAPH_CAMERA_FAR);
    this.camera.position.set(0, 180, 1650);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(container.clientWidth || 1, container.clientHeight || 1);
    this.renderer.outputEncoding = THREE.sRGBEncoding;
    this.renderer.setClearColor(0x020d08, 0);
    this.renderer.sortObjects = true;
    this.renderer.domElement.style.background = "transparent";
    this.renderer.domElement.style.touchAction = "none";
    this.renderer.domElement.style.cursor = "grab";
    container.innerHTML = "";
    container.appendChild(this.renderer.domElement);
    this.networkRoot = new THREE.Group();
    this.scene.add(this.networkRoot);
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.enableRotate = true;
    this.controls.enableZoom = true;
    this.controls.enablePan = true;
    this.controls.screenSpacePanning = true;
    this.controls.rotateSpeed = 0.88;
    this.controls.zoomSpeed = 1.18;
    this.controls.panSpeed = 1.3;
    this.controls.minDistance = 90;
    this.controls.maxDistance = 12000;
    this.controls.autoRotate = false;
    this.controls.autoRotateSpeed = 0;
    this.controls.target.set(0, 0, 0);
    this.handlers = new Map();
    this.nodeMap = new Map();
    this.edgeMap = new Map();
    this.txDots = [];
    this.currentScale = 1;
    this.layoutPositions = new Map();
    this.layoutSignature = "";
    this.hasFramedOnce = false;
    this.focusAnimationFrame = null;
    this.nodeCoreGeometry = new THREE.SphereGeometry(4.8, 24, 24);
    this.txGlowGeometry = new THREE.SphereGeometry(2.5, 10, 10);
    this.txCoreGeometry = new THREE.SphereGeometry(1.02, 10, 10);
    this.defaultViewDirection = new THREE.Vector3(0.34, -0.18, 1).normalize();
    this._tmpVec = new THREE.Vector3();
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2(2, 2);
    this.hovered = null;
    this._initLights();
    this._initBackground();
    this._bindEvents();
    this._animate();
  }

  _hashUnit(seed) {
    let hash = 2166136261;
    const source = String(seed);
    for (let i = 0; i < source.length; i += 1) {
      hash ^= source.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
  }

  _sphericalVector(theta, phi, radius) {
    return new THREE.Vector3(
      Math.sin(phi) * Math.cos(theta) * radius,
      Math.cos(phi) * radius,
      Math.sin(phi) * Math.sin(theta) * radius
    );
  }

  _layoutSignatureFor(nodes) {
    return nodes
      .map((node) => String(node.id))
      .sort()
      .join("|");
  }

  _rebuildUniverseLayout(nodes) {
    const signature = this._layoutSignatureFor(nodes);
    if (signature === this.layoutSignature) {
      return;
    }

    this.layoutSignature = signature;
    this.layoutPositions = new Map();
    const ids = nodes.map((node) => String(node.id)).sort();
    const total = Math.max(ids.length, 1);
    const placed = [];
    const shellCount = Math.max(4, Math.ceil(Math.cbrt(total)) + 2);
    const minSeparation = total > 220 ? 64 : total > 140 ? 76 : 88;

    ids.forEach((id, index) => {
      const shellIndex = Math.min(shellCount - 1, Math.floor((index / total) * shellCount));
      const baseRadius = 220 + shellIndex * 168;
      let chosen = null;
      let bestCandidate = null;
      let bestDistance = -1;

      for (let attempt = 0; attempt < 18; attempt += 1) {
        const theta = this._hashUnit(`${id}|${attempt}|theta`) * Math.PI * 2;
        const phi = Math.acos(THREE.MathUtils.clamp(this._hashUnit(`${id}|${attempt}|phi`) * 2 - 1, -1, 1));
        const radius = baseRadius + (this._hashUnit(`${id}|${attempt}|radius`) - 0.5) * 52;
        const candidate = this._sphericalVector(theta, phi, radius);
        let nearest = Infinity;
        for (let i = 0; i < placed.length; i += 1) {
          nearest = Math.min(nearest, candidate.distanceTo(placed[i]));
        }
        if (!placed.length || nearest >= minSeparation) {
          chosen = candidate;
          break;
        }
        if (nearest > bestDistance) {
          bestDistance = nearest;
          bestCandidate = candidate;
        }
      }

      const resolved = chosen || bestCandidate || new THREE.Vector3();
      placed.push(resolved.clone());
      this.layoutPositions.set(id, resolved);
    });
  }

  _resolveNodePosition(node) {
    const cached = this.layoutPositions.get(String(node.id));
    return cached ? cached.clone() : new THREE.Vector3();
  }

  _layoutSpreadFactor() {
    return 1;
  }

  _initLights() {
    this.scene.add(new THREE.AmbientLight(0x0d1a2f, 1.22));
    const cyan = new THREE.PointLight(0x00ffff, 2.05, 2600);
    cyan.position.set(220, 220, 260);
    const blue = new THREE.PointLight(0x0044ff, 1.5, 2600);
    blue.position.set(-260, -120, 340);
    const teal = new THREE.PointLight(0x00ffcc, 0.9, 2200);
    teal.position.set(0, 320, -380);
    this.scene.add(cyan);
    this.scene.add(blue);
    this.scene.add(teal);
  }

  _initBackground() {
    const shell = new THREE.Mesh(
      new THREE.SphereGeometry(5400, 36, 36),
      new THREE.MeshBasicMaterial({
        color: 0x07111b,
        transparent: true,
        opacity: 0.38,
        side: THREE.BackSide,
        depthWrite: false,
      })
    );
    this.scene.add(shell);
    const stars = new THREE.BufferGeometry();
    const n = 1800;
    const p = new Float32Array(n * 3);
    const c = new Float32Array(n * 3);
    for (let i = 0; i < n; i += 1) {
      const radius = 1300 + Math.random() * 3600;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      p[i * 3] = Math.sin(phi) * Math.cos(theta) * radius;
      p[i * 3 + 1] = Math.cos(phi) * radius * 0.68;
      p[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * radius;
      const pick = Math.random();
      if (pick < 0.5) {
        c[i * 3] = 0;
        c[i * 3 + 1] = 0.8;
        c[i * 3 + 2] = 0.8;
      } else if (pick < 0.82) {
        c[i * 3] = 0;
        c[i * 3 + 1] = 0.28;
        c[i * 3 + 2] = 1;
      } else {
        c[i * 3] = 1;
        c[i * 3 + 1] = 0;
        c[i * 3 + 2] = 0.66;
      }
    }
    stars.setAttribute("position", new THREE.BufferAttribute(p, 3));
    stars.setAttribute("color", new THREE.BufferAttribute(c, 3));
    this.dust = new THREE.Points(
      stars,
      new THREE.PointsMaterial({ size: 1.05, vertexColors: true, transparent: true, opacity: 0.24, depthWrite: false })
    );
    this.scene.add(this.dust);
    this.groundPlane = new THREE.Mesh(
      new THREE.PlaneGeometry(4600, 4600, 1, 1),
      new THREE.MeshBasicMaterial({
        color: 0x06271b,
        transparent: true,
        opacity: 0.12,
        side: THREE.DoubleSide,
        depthWrite: false,
      })
    );
    this.groundPlane.rotation.x = -Math.PI / 2;
    this.groundPlane.position.y = -740;
    this.scene.add(this.groundPlane);
    this.groundGrid = new THREE.GridHelper(4400, 70, 0x0f5a3d, 0x0a3525);
    this.groundGrid.position.y = -738;
    this.groundGrid.material.opacity = 0.2;
    this.groundGrid.material.transparent = true;
    this.scene.add(this.groundGrid);
  }

  _bindEvents() {
    this.renderer.domElement.addEventListener("pointerdown", () => {
      this.renderer.domElement.style.cursor = "grabbing";
    }, { passive: true });
    this.renderer.domElement.addEventListener("pointerup", () => {
      this.renderer.domElement.style.cursor = "grab";
    }, { passive: true });
    this.renderer.domElement.addEventListener("mousemove", (event) => {
      const rect = this.renderer.domElement.getBoundingClientRect();
      this.mouse.x = ((event.clientX - rect.left) / Math.max(rect.width, 1)) * 2 - 1;
      this.mouse.y = -((event.clientY - rect.top) / Math.max(rect.height, 1)) * 2 + 1;
    }, { passive: true });
    this.renderer.domElement.addEventListener("mouseleave", () => {
      this.mouse.set(2, 2);
      this.hovered = null;
      this.renderer.domElement.style.cursor = "grab";
    }, { passive: true });
    this.renderer.domElement.addEventListener("click", () => {
      if (this.hovered) this._emit("click", { nodes: [this.hovered.userData.id] });
    });
    this.controls.addEventListener("change", () => {
      this._emit("zoom", {});
      this._emit("dragEnd", {});
    });
    window.addEventListener("resize", () => this.resize(), { passive: true });
  }

  _makeLabel(text) {
    const canvas = document.createElement("canvas");
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext("2d");
    const texture = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
    sprite.scale.set(44, 10, 1);
    sprite.position.set(0, 28, 0);
    sprite.userData = { canvas, ctx, texture, text: "" };
    this._updateLabel(sprite, text);
    return sprite;
  }

  _updateLabel(sprite, text) {
    if (!sprite?.userData) return;
    const nextText = String(text || "");
    if (sprite.userData.text === nextText) return;
    sprite.userData.text = nextText;
    const { canvas, ctx, texture } = sprite.userData;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (nextText) {
      ctx.font = "600 26px JetBrains Mono";
      ctx.fillStyle = "#d8fff6";
      ctx.textAlign = "center";
      ctx.fillText(nextText, canvas.width / 2, 42);
    }
    texture.needsUpdate = true;
    sprite.visible = Boolean(nextText);
  }

  _statusVisuals(status) {
    if (status === "fraud") {
      return {
        core: 0xff5d7d,
        emissive: 0xff2755,
        emissiveIntensity: 2.75,
      };
    }
    if (status === "early") {
      return {
        core: 0xffc34d,
        emissive: 0xffa000,
        emissiveIntensity: 2.4,
      };
    }
    if (status === "new") {
      return {
        core: 0x00ff88,
        emissive: 0x00d48f,
        emissiveIntensity: 2.35,
      };
    }
    return {
      core: 0x1a6fff,
      emissive: 0x0044ff,
      emissiveIntensity: 2.2,
    };
  }

  _edgeMaterialStyle(edge) {
    const rawColor = typeof edge?.color === "string"
      ? edge.color
      : edge?.color?.color || "#66ffcc";
    const normalizedColor = String(rawColor).replace(/rgba\(([^,]+),([^,]+),([^,]+),([^)]+)\)/i, "rgb($1,$2,$3)");
    const alphaMatch = String(rawColor).match(/rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)/i);
    const defaultOpacity = edge?.persistent ? 0.34 : edge?.temporary ? 0.12 : 0.08;
    const opacity = alphaMatch ? Number(alphaMatch[1]) : edge?.opacity ?? defaultOpacity;
    return {
      color: new THREE.Color(normalizedColor),
      opacity: THREE.MathUtils.clamp(Number(opacity || defaultOpacity), 0.06, 0.92),
    };
  }

  _resolveHitGroup(object) {
    let current = object;
    while (current && !current.userData?.id) {
      current = current.parent;
    }
    return current && current.userData?.id ? current : null;
  }

  upsertNode(node) {
    const id = String(node.id);
    let mesh = this.nodeMap.get(id);
    if (!mesh) {
      const group = new THREE.Group();
      const core = new THREE.Mesh(
        this.nodeCoreGeometry,
        new THREE.MeshStandardMaterial({
          color: 0x1a6fff,
          emissive: 0x0044ff,
          emissiveIntensity: 2.2,
          metalness: 0.22,
          roughness: 0.24,
          transparent: true,
          opacity: 1,
        })
      );
      const glow = new THREE.Mesh(
        new THREE.SphereGeometry(8.8, 16, 16),
        new THREE.MeshBasicMaterial({
          color: 0x00ffcc,
          transparent: true,
          opacity: 0.16,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        })
      );
      const halo = new THREE.Mesh(
        new THREE.TorusGeometry(10.8, 0.18, 10, 56),
        new THREE.MeshBasicMaterial({
          color: 0x00ffcc,
          transparent: true,
          opacity: 0.18,
          depthWrite: false,
        })
      );
      halo.rotation.x = Math.PI / 2;
      const label = this._makeLabel("");
      group.add(core);
      group.add(glow);
      group.add(halo);
      group.add(label);
      core.renderOrder = 4;
      group.userData = {
        id,
        core,
        glow,
        halo,
        label,
        basePosition: new THREE.Vector3(),
        displayLabel: "",
        hoverLabel: id,
        baseNodeScale: 1,
        baseEmissiveIntensity: 2.2,
        glowOpacity: 0.16,
        nodeOpacity: 1,
        driftX: (this._hashUnit(`${id}|dx`) - 0.5) * 32,
        driftY: (this._hashUnit(`${id}|dy`) - 0.5) * 24,
        driftZ: (this._hashUnit(`${id}|dz`) - 0.5) * 32,
        driftSpeed: 0.24 + this._hashUnit(`${id}|ds`) * 0.42,
        driftPhase: this._hashUnit(`${id}|dp`) * Math.PI * 2,
      };
      this.networkRoot.add(group);
      this.nodeMap.set(id, group);
      mesh = group;
    }
    const visuals = this._statusVisuals(node.status || "normal");
    const sourceX = Number(node.x);
    const sourceY = Number(node.y);
    mesh.userData.core.material.color.setHex(visuals.core);
    mesh.userData.core.material.emissive.setHex(visuals.emissive);
    mesh.userData.sourcePosition = {
      x: Number.isFinite(sourceX) ? sourceX : GRAPH_LAYOUT_CENTER_X,
      y: Number.isFinite(sourceY) ? sourceY : GRAPH_LAYOUT_CENTER_Y,
      z: Number.isFinite(Number(node.z)) ? Number(node.z) : 0,
    };
    const explicitLayout = node?.layoutPosition;
    if (
      explicitLayout &&
      Number.isFinite(Number(explicitLayout.x)) &&
      Number.isFinite(Number(explicitLayout.y))
    ) {
      mesh.userData.basePosition.set(
        Number(explicitLayout.x),
        Number(explicitLayout.y),
        Number(explicitLayout.z || 0)
      );
    } else {
      mesh.userData.basePosition.copy(this._resolveNodePosition(node));
    }
    mesh.position.copy(mesh.userData.basePosition);
    const baseSize = Number(node.baseSize || node.size || 24);
    mesh.userData.baseNodeScale = THREE.MathUtils.clamp((baseSize / 24) * 0.88, 0.72, 1.2);
    mesh.userData.baseEmissiveIntensity = visuals.emissiveIntensity;
    mesh.userData.glowOpacity = (node.status === "fraud" ? 0.26 : node.status === "early" ? 0.22 : 0.14);
    mesh.userData.nodeOpacity = THREE.MathUtils.clamp(Number(node.opacity ?? 1), 0.12, 1);
    mesh.userData.displayLabel = "";
    mesh.userData.hoverLabel = String(node.hoverLabel || id);
    this._updateLabel(mesh.userData.label, "");
    mesh.userData.core.material.emissiveIntensity = visuals.emissiveIntensity;
    mesh.userData.core.material.opacity = mesh.userData.nodeOpacity;
    mesh.userData.glow.material.color.setHex(visuals.core);
    mesh.userData.glow.material.opacity = mesh.userData.glowOpacity * mesh.userData.nodeOpacity;
    mesh.userData.halo.material.color.setHex(visuals.core);
    mesh.userData.halo.material.opacity = 0.18 * mesh.userData.nodeOpacity;
    mesh.visible = node.status !== "banned";
  }

  removeNode(id) {
    const key = String(id);
    const mesh = this.nodeMap.get(key);
    if (!mesh) return;
    this.networkRoot.remove(mesh);
    this.nodeMap.delete(key);
  }

  _edgeKey(edge) {
    return String(edge.id ?? `${edge.from}->${edge.to}`);
  }

  upsertEdge(edge) {
    const key = this._edgeKey(edge);
    const from = this.nodeMap.get(String(edge.from));
    const to = this.nodeMap.get(String(edge.to));
    if (!from || !to) return;
    const style = this._edgeMaterialStyle(edge);
    let line = this.edgeMap.get(key);
    if (!line) {
      const geo = new THREE.BufferGeometry().setFromPoints([from.position.clone(), to.position.clone()]);
      const mat = new THREE.LineBasicMaterial({ color: style.color, transparent: true, opacity: style.opacity, depthWrite: false });
      line = new THREE.Line(geo, mat);
      line.userData = { from: String(edge.from), to: String(edge.to), id: key, baseOpacity: style.opacity, hidden: Boolean(edge.hidden) };
      this.networkRoot.add(line);
      this.edgeMap.set(key, line);
    } else {
      line.userData.from = String(edge.from);
      line.userData.to = String(edge.to);
      line.userData.baseOpacity = style.opacity;
      line.userData.hidden = Boolean(edge.hidden);
      line.material.color.copy(style.color);
      line.material.opacity = style.opacity;
    }
    line.visible = !edge.hidden;
  }

  removeEdge(id) {
    const key = String(id);
    const line = this.edgeMap.get(key);
    if (!line) return;
    this.networkRoot.remove(line);
    this.edgeMap.delete(key);
  }

  syncFromDataSets(nodesDs, edgesDs) {
    const nodes = nodesDs.get();
    const edges = edgesDs.get();
    this._rebuildUniverseLayout(nodes);
    const activeIds = new Set(nodes.map((n) => String(n.id)));
    const activeEdges = new Set(edges.map((e) => this._edgeKey(e)));
    nodes.forEach((node) => this.upsertNode(node));
    edges.forEach((edge) => this.upsertEdge(edge));
    [...this.nodeMap.keys()].forEach((id) => { if (!activeIds.has(id)) this.removeNode(id); });
    [...this.edgeMap.keys()].forEach((id) => { if (!activeEdges.has(id)) this.removeEdge(id); });
    if (!this.hasFramedOnce && this.nodeMap.size > 0) {
      this.hasFramedOnce = true;
    }
  }

  animateTransaction(fromId, toId, colorHex = 0xffffff, duration = 820, lineColorHex = 0x38bdf8, lineOpacity = 0.14) {
    const from = this.nodeMap.get(String(fromId));
    const to = this.nodeMap.get(String(toId));
    if (!from || !to) return Promise.resolve(false);
    const tempLine = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([from.position.clone(), to.position.clone()]),
      new THREE.LineBasicMaterial({ color: lineColorHex, transparent: true, opacity: lineOpacity, depthWrite: false })
    );
    this.networkRoot.add(tempLine);
    const dot = new THREE.Group();
    const dotGlow = new THREE.Mesh(
      this.txGlowGeometry,
      new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.18, blending: THREE.AdditiveBlending, depthWrite: false })
    );
    const dotCore = new THREE.Mesh(
      this.txCoreGeometry,
      new THREE.MeshBasicMaterial({ color: colorHex })
    );
    dot.add(dotGlow);
    dot.add(dotCore);
    dot.userData = {
      fromId: String(fromId),
      toId: String(toId),
      startedAt: performance.now(),
      duration: Math.max(280, Number(duration || 820)),
      baseOpacity: lineOpacity,
      tempLine,
    };
    this.networkRoot.add(dot);
    this.txDots.push(dot);
    return Promise.resolve(true);
  }

  _removeTxVisual(dot) {
    if (!dot) return;
    const tempLine = dot.userData?.tempLine;
    if (tempLine) {
      if (tempLine.parent) {
        tempLine.parent.remove(tempLine);
      } else {
        this.networkRoot.remove(tempLine);
      }
      tempLine.geometry?.dispose?.();
      tempLine.material?.dispose?.();
    }
    if (dot.parent) {
      dot.parent.remove(dot);
    } else {
      this.networkRoot.remove(dot);
    }
  }

  getPositions(ids = []) {
    const out = {};
    ids.forEach((id) => {
      const node = this.nodeMap.get(String(id));
      if (node) out[String(id)] = { x: node.position.x, y: node.position.y, z: node.position.z };
    });
    return out;
  }

  getSourcePositions(ids = []) {
    const out = {};
    ids.forEach((id) => {
      const node = this.nodeMap.get(String(id));
      if (!node) return;
      const source = node.userData?.sourcePosition || {};
      out[String(id)] = {
        x: Number(source.x || 0),
        y: Number(source.y || 0),
        z: Number(source.z || 0),
      };
    });
    return out;
  }

  canvasToDOM(point) {
    const vector = new THREE.Vector3(point.x, point.y, point.z || 0).project(this.camera);
    const rect = this.renderer.domElement.getBoundingClientRect();
    return {
      x: ((vector.x + 1) * 0.5) * rect.width,
      y: ((-vector.y + 1) * 0.5) * rect.height,
    };
  }

  getScale() {
    return this.currentScale;
  }

  setOptions() {}

  fit(payload = {}) {
    return payload;
  }

  _computeBoundsForIds(ids = []) {
    const points = ids
      .map((id) => this.nodeMap.get(String(id))?.position?.clone())
      .filter(Boolean);
    if (!points.length) return null;
    const bounds = new THREE.Box3();
    points.forEach((point) => bounds.expandByPoint(point));
    return bounds;
  }

  _distanceForBounds(bounds) {
    const size = bounds.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() * 0.23, 180);
    const fitHeightDistance = radius / Math.tan(THREE.MathUtils.degToRad(this.camera.fov * 0.5));
    const fitWidthDistance = fitHeightDistance / Math.max(this.camera.aspect, 0.62);
    return THREE.MathUtils.clamp(Math.max(fitHeightDistance, fitWidthDistance) * 1.08, this.controls.minDistance, this.controls.maxDistance);
  }

  focusNodesSmooth(ids = [], durationMs = 1000) {
    const resolvedIds = Array.isArray(ids) && ids.length ? ids.map(String) : [...this.nodeMap.keys()];
    const bounds = this._computeBoundsForIds(resolvedIds);
    if (!bounds) return;
    const center = bounds.getCenter(new THREE.Vector3());
    const distance = this._distanceForBounds(bounds);
    const direction = this.camera.position.clone().sub(this.controls.target);
    if (direction.lengthSq() < 1e-6) direction.copy(this.defaultViewDirection);
    else direction.normalize();
    const targetCameraPos = center.clone().add(direction.multiplyScalar(distance));
    const startTarget = this.controls.target.clone();
    const startCamera = this.camera.position.clone();
    const startAt = performance.now();
    if (this.focusAnimationFrame) {
      cancelAnimationFrame(this.focusAnimationFrame);
      this.focusAnimationFrame = null;
    }
    const step = () => {
      const elapsed = performance.now() - startAt;
      const t = THREE.MathUtils.clamp(elapsed / Math.max(1, durationMs), 0, 1);
      const eased = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      this.controls.target.lerpVectors(startTarget, center, eased);
      this.camera.position.lerpVectors(startCamera, targetCameraPos, eased);
      this.controls.update();
      if (t < 1) {
        this.focusAnimationFrame = requestAnimationFrame(step);
      } else {
        this.focusAnimationFrame = null;
      }
    };
    this.focusAnimationFrame = requestAnimationFrame(step);
  }

  frameAllNodesSmooth(durationMs = 1000) {
    this.focusNodesSmooth([...this.nodeMap.keys()], durationMs);
  }

  on(name, handler) {
    if (!this.handlers.has(name)) this.handlers.set(name, []);
    this.handlers.get(name).push(handler);
  }

  _emit(name, payload) {
    const list = this.handlers.get(name) || [];
    list.forEach((handler) => {
      try { handler(payload); } catch (_) {}
    });
  }

  resize() {
    const w = Math.max(this.container.clientWidth, 1);
    const h = Math.max(this.container.clientHeight, 1);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _animate() {
    const step = () => {
      requestAnimationFrame(step);
      this.controls.update();
      const now = performance.now() * 0.001;
      this.currentScale = Math.max(0.4, Math.min(1.8, 760 / Math.max(this.camera.position.distanceTo(this.controls.target), 1)));
      const spread = this._layoutSpreadFactor();
      this.raycaster.setFromCamera(this.mouse, this.camera);
      const hits = this.raycaster.intersectObjects([...this.nodeMap.values()], true);
      this.hovered = hits.length ? this._resolveHitGroup(hits[0].object) : null;
      let pulseIndex = 0;
      this.nodeMap.forEach((node) => {
        const basePosition = node.userData?.basePosition || node.position;
        const driftOsc = now * node.userData.driftSpeed + node.userData.driftPhase;
        const desiredPosition = this._tmpVec
          .copy(basePosition)
          .multiplyScalar(spread)
          .add(new THREE.Vector3(
            Math.sin(driftOsc) * node.userData.driftX,
            Math.cos(driftOsc * 0.92) * node.userData.driftY,
            Math.sin(driftOsc * 0.77) * node.userData.driftZ
          ));
        node.position.lerp(desiredPosition, 0.14);
        const wave = Math.sin(now * 2.1 + pulseIndex * 0.7);
        pulseIndex += 1;
        const pulse = 1 + wave * 0.032;
        const distance = Math.max(120, this.camera.position.distanceTo(node.position));
        const hovered = this.hovered?.userData?.id === node.userData.id;
        const visibilityBoost = THREE.MathUtils.clamp(820 / distance, 0.96, 1.08);
        const depthScale = THREE.MathUtils.clamp(1280 / distance, 0.72, 1.22);
        node.scale.setScalar(node.userData.baseNodeScale * pulse * visibilityBoost * depthScale);
        node.userData.core.material.opacity = node.userData.nodeOpacity;
        node.userData.core.material.emissiveIntensity =
          (node.userData.baseEmissiveIntensity + Math.sin(now * 3.1 + pulseIndex) * 0.1 + (hovered ? 0.16 : 0)) *
          THREE.MathUtils.clamp(1220 / distance, 0.62, 1.28);
        if (node.userData.glow) {
          node.userData.glow.material.opacity =
            node.userData.glowOpacity *
            node.userData.nodeOpacity *
            THREE.MathUtils.clamp(1120 / distance, 0.3, 1.1) *
            (0.88 + Math.sin(now * 2.2 + pulseIndex) * 0.12);
        }
        if (node.userData.halo) {
          node.userData.halo.material.opacity =
            0.08 * node.userData.nodeOpacity * THREE.MathUtils.clamp(1180 / distance, 0.25, 1.15);
          node.userData.halo.rotation.z += 0.0025;
        }
        const desiredLabel = hovered ? (node.userData.hoverLabel || node.userData.displayLabel) : "";
        this._updateLabel(node.userData.label, desiredLabel);
        node.userData.label.material.opacity = desiredLabel
          ? THREE.MathUtils.clamp(1.1 - (distance / 2100), 0.16, 0.94) * node.userData.nodeOpacity
          : 0;
      });
      for (let i = this.txDots.length - 1; i >= 0; i -= 1) {
        const dot = this.txDots[i];
        const from = this.nodeMap.get(dot.userData.fromId);
        const to = this.nodeMap.get(dot.userData.toId);
        if (!from || !to) {
          this._removeTxVisual(dot);
          this.txDots.splice(i, 1);
          continue;
        }
        const progress = Math.min(1, (performance.now() - dot.userData.startedAt) / dot.userData.duration);
        if (progress >= 1) {
          this._removeTxVisual(dot);
          this.txDots.splice(i, 1);
          continue;
        }
        dot.position.lerpVectors(from.position, to.position, progress);
        if (dot.userData.tempLine) {
          dot.userData.tempLine.geometry.setFromPoints([from.position, to.position]);
          dot.userData.tempLine.material.opacity = dot.userData.baseOpacity * (1 - progress * 0.72);
        }
      }
      this.edgeMap.forEach((line) => {
        const from = this.nodeMap.get(line.userData.from);
        const to = this.nodeMap.get(line.userData.to);
        if (!from || !to) return;
        line.geometry.setFromPoints([from.position, to.position]);
        line.material.opacity = line.userData.baseOpacity;
        line.visible = !line.userData.hidden && from.visible && to.visible;
      });
      this.renderer.render(this.scene, this.camera);
    };
    step();
  }
}

function setLoader(visible, text = "Loading...") {
  els.loaderText.textContent = text;
  els.loader.classList.toggle("hidden", !visible);
}

function setSimulationButtonsDisabled(disabled) {
  if (els.simulateAttackBtn) {
    els.simulateAttackBtn.disabled = disabled;
  }
  if (els.simulateAttackBtnSecondary) {
    els.simulateAttackBtnSecondary.disabled = disabled;
  }
}

function setReplayButtonDisabled(disabled) {
  const replayBtn = document.getElementById("replay-attack-btn");
  if (replayBtn) {
    replayBtn.disabled = disabled;
  }
}

function setApiStatus(isLive) {
  els.apiStatusDot.classList.toggle("live", isLive);
  els.apiStatusDot.classList.toggle("offline", !isLive);
  els.apiStatusText.textContent = isLive
    ? `API Live${API_BASE ? ` • ${API_BASE}` : ""}`
    : "API Offline";
}

function setCollapsibleState(button, panel, isOpen, animate = true) {
  if (!button || !panel) return;

  button.setAttribute("aria-expanded", String(isOpen));
  panel.classList.toggle("is-open", isOpen);

  const meta = button.querySelector(".collapse-toggle__meta");
  if (meta) {
    meta.textContent = isOpen ? "Hide" : "Show";
  }

  if (!animate) {
    panel.style.transition = "none";
  }

  panel.style.maxHeight = isOpen ? `${panel.scrollHeight}px` : "0px";

  if (!animate) {
    requestAnimationFrame(() => {
      panel.style.transition = "";
    });
  }
}

function syncOpenCollapsibles() {
  document.querySelectorAll("[data-collapsible-trigger]").forEach((button) => {
    if (button.getAttribute("aria-expanded") !== "true") {
      return;
    }

    const panel = document.getElementById(button.dataset.collapsibleTrigger);
    if (panel) {
      panel.style.maxHeight = `${panel.scrollHeight}px`;
    }
  });
}

function scheduleUiSync() {
  if (state.uiSyncFrame) {
    cancelAnimationFrame(state.uiSyncFrame);
  }

  state.uiSyncFrame = requestAnimationFrame(() => {
    state.uiSyncFrame = null;
    syncOpenCollapsibles();
  });
}

function initCollapsibles() {
  document.querySelectorAll("[data-collapsible-trigger]").forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }

    const panel = document.getElementById(button.dataset.collapsibleTrigger);
    if (!panel) {
      return;
    }

    button.dataset.bound = "true";
    const initialOpen = button.getAttribute("aria-expanded") === "true";
    setCollapsibleState(button, panel, initialOpen, false);

    button.addEventListener("click", () => {
      const isOpen = button.getAttribute("aria-expanded") === "true";
      setCollapsibleState(button, panel, !isOpen);
      scheduleUiSync();
    });
  });
}

function stopEarlyExplainerAnimation() {
  if (state.earlyExplainerTimer) {
    clearTimeout(state.earlyExplainerTimer);
    state.earlyExplainerTimer = null;
  }
}

function animateEarlyExplainer() {
  if (!els.earlyWarningExplainer) {
    return;
  }
  stopEarlyExplainerAnimation();
  const steps = Array.from(
    els.earlyWarningExplainer.querySelectorAll(".explain-step")
  );
  steps.forEach((step) => step.classList.remove("is-visible"));

  const reveal = (index) => {
    if (index >= steps.length) {
      state.earlyExplainerTimer = null;
      return;
    }
    steps[index].classList.add("is-visible");
    state.earlyExplainerTimer = setTimeout(() => reveal(index + 1), 170);
  };

  reveal(0);
}

function renderEarlyWarningExplainer(explainer) {
  if (!els.earlyWarningExplainer) {
    return;
  }
  const payload = explainer || {};
  const steps = payload.steps || [];
  if (els.earlyWarningExplainerIntro) {
    els.earlyWarningExplainerIntro.textContent =
      payload.sample_account && payload.sample_account !== "--"
        ? `Live sample ${payload.sample_account} is being scored continuously. Nodes turn yellow above ${(Number(payload.threshold || 0.46) * 100).toFixed(1)}% risk and cool back toward blue through decay.`
        : "The learning engine watches every transaction, builds risk from live signals, and slowly decays risk back toward blue when behavior normalizes.";
  }

  els.earlyWarningExplainer.innerHTML = steps
    .map(
      (step, index) => `
        <article class="explain-step">
          <div class="explain-step__head">
            <span class="explain-step__badge">${index + 1}</span>
            <div class="explain-step__title">${escapeHtml(step.title || `Step ${index + 1}`)}</div>
          </div>
          <div class="explain-step__caption">${escapeHtml(step.caption || "")}</div>
          <div class="explain-step__items">
            ${(step.items || [])
              .map(
                (item) =>
                  `<span class="token-pill token-pill--warning">${escapeHtml(String(item))}</span>`
              )
              .join("")}
          </div>
        </article>
      `
    )
    .join("");

  if (els.earlyWarningDetails?.open) {
    animateEarlyExplainer();
  }
}

function initEarlyWarningDisclosure() {
  if (!els.earlyWarningDetails || els.earlyWarningDetails.dataset.bound === "true") {
    return;
  }
  els.earlyWarningDetails.dataset.bound = "true";
  els.earlyWarningDetails.addEventListener("toggle", () => {
    if (els.earlyWarningDetails.open) {
      animateEarlyExplainer();
    } else {
      stopEarlyExplainerAnimation();
    }
    scheduleUiSync();
  });
}

function buildApiCandidates() {
  const candidates = [];
  const pushCandidate = (value) => {
    if (!value) return;
    const normalized = value.endsWith("/") ? value.slice(0, -1) : value;
    if (!candidates.includes(normalized)) {
      candidates.push(normalized);
    }
  };

  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    pushCandidate(window.location.origin);
    if (window.location.port !== DEFAULT_API_PORT) {
      pushCandidate(`${window.location.protocol}//${window.location.hostname}:${DEFAULT_API_PORT}`);
    }
  }
  pushCandidate(`http://127.0.0.1:${DEFAULT_API_PORT}`);
  pushCandidate(`http://localhost:${DEFAULT_API_PORT}`);

  return candidates;
}

async function resolveApiBase() {
  state.apiCandidates = buildApiCandidates();

  for (const candidate of state.apiCandidates) {
    try {
      const response = await fetch(`${candidate}/metrics`, { method: "GET" });
      if (!response.ok) continue;
      API_BASE = candidate;
      return candidate;
    } catch (error) {
      continue;
    }
  }

  throw new Error(
    `Unable to reach the FastAPI server. Start uvicorn backend.api:app --reload --port ${DEFAULT_API_PORT}.`
  );
}

async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(payload || `Request failed for ${path}`);
  }
  return response.json();
}

function websocketUrl(path) {
  return `${API_BASE.replace(/^http/i, "ws")}${path}`;
}

function handleSnapshotMessage(payload) {
  if (!payload) return;
  if (payload.live) {
    state.live = payload.live;
  }
  if (payload.accounts) {
    updateLiveNetwork(payload.accounts, payload.live || state.live || {
      banned_accounts: [],
      fraud_accounts: [],
      early_warning: { table: [] },
    });
  } else if (payload.live) {
    rebuildSuspiciousSummaryFromLiveNodes(payload.live);
    renderLiveMetrics(payload.live, state.dashboard);
    renderEarlyWarning(payload.live);
  }
  if (payload.transactions) {
    queueTransactions(payload.transactions);
    pruneLiveEdges();
  }
  if (payload.latest_attack) {
    updateAttackNetwork(payload.latest_attack);
  }
  handleDetectionMeta(
    payload.dashboard || {
      available: Boolean(payload.live?.detection_available),
      is_detecting: payload.live?.detection_job?.status === "running",
      detection_job: payload.live?.detection_job || {},
    }
  ).catch(() => {});
  setApiStatus(true);
}

function scheduleSnapshotProcessing(payload) {
  state.pendingSnapshot = payload;
  if (state.snapshotFrame) {
    return;
  }
  state.snapshotFrame = requestAnimationFrame(() => {
    state.snapshotFrame = null;
    const nextPayload = state.pendingSnapshot;
    state.pendingSnapshot = null;
    if (nextPayload) {
      handleSnapshotMessage(nextPayload);
    }
  });
}

async function handleDetectionMeta(meta) {
  if (!meta) return;

  const detectionJob = meta.detection_job || {};
  const jobId = Number(detectionJob.job_id || 0);
  const status =
    detectionJob.status ||
    (meta.is_detecting ? "running" : meta.available ? "complete" : "idle");

  if (status === "running") {
    const activeJobId = Number(state.dashboard?.detection_job?.job_id || 0);
    if (!state.dashboard?.is_detecting || activeJobId !== jobId) {
      renderDashboard({
        available: false,
        is_detecting: true,
        detection_job: detectionJob,
      });
    } else {
      setPostDetectionLoading(true);
    }
    return;
  }

  if (status === "queued") {
    return;
  }

  if (status === "complete") {
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    if (state.latestAttackData?.attack_name) {
      applyFinalAttackState(state.latestAttackData);
    }
    if (
      jobId &&
      state.lastDashboardRefreshJobId !== jobId &&
      !state.dashboardRefreshInFlight
    ) {
      await refreshDashboard(jobId);
      showToast("ML detection complete.", "success");
    }
    return;
  }

  if (status === "error") {
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    if (state.lastDashboardErrorJobId !== jobId) {
      state.lastDashboardErrorJobId = jobId;
      showToast(`Detection failed: ${detectionJob.error || "Unknown error"}`, "error");
    }
    return;
  }

  if (!meta.available && !meta.is_detecting && !state.dashboard) {
    renderDashboard({
      available: false,
      is_detecting: false,
      detection_job: detectionJob,
    });
  }
}

async function startDetectionForCurrentAttack() {
  if (DEMO_SIM_MODE) {
    const attackName = state.latestAttackData?.attack_name || "Simulated Attack";
    const fraudIds = [...state.pendingAttackNodes].slice(0, 6);
    const earlyIds = [...state.currentEarlyIds].slice(0, 10);
    const accounts = Array.isArray(state.lastAccounts) ? state.lastAccounts : [];
    fraudIds.forEach((id) => {
      const node = state.liveNodes.get(id);
      if (node) {
        state.liveNodes.update({ id, status: "fraud", color: accountStyle(id, "fraud", node).color });
      }
    });
    state.live = {
      ...(state.live || {}),
      detection_available: true,
      fraud_accounts: fraudIds,
      metrics: {
        ...(state.live?.metrics || {}),
        fraud_count: fraudIds.length,
      },
      detection_job: { status: "complete", attack_name: attackName, job_id: 1, error: null },
    };
    renderDashboard(buildDemoDashboard(accounts, attackName, fraudIds, earlyIds));
    renderLiveMetrics(state.live, state.dashboard);
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    showToast("Simulated detection complete.", "success");
    return;
  }
  if (!state.latestAttackData?.attack_name) {
    return;
  }

  const payload = await apiFetch("/ui/start_detection", { method: "POST" });
  await handleDetectionMeta({
    available: false,
    is_detecting: payload.status === "running",
    detection_job: payload.job || {},
  });
  if (!state.websocketConnected && payload.status === "running") {
    startDetectionPolling();
  }
}

function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  els.toastStack.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3200);
}

function safeNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "--";
  }
  return Number(value).toFixed(digits);
}

function round4(value) {
  return Number(Number(value || 0).toFixed(4));
}

function updateText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function setPostDetectionLoading(isLoading) {
  els.postDetectionLoader.classList.toggle("hidden", !isLoading);
}

function resetInvestigationPanel(message = "Detection is still running.") {
  clearInvestigationHighlight();
  updateText("investigation-account", "--");
  updateText("investigation-score", "0%");
  updateText("investigation-confidence", "--");
  updateText("investigation-ml", "--");
  updateText("investigation-rule", "--");
  updateText("investigation-gnn", "--");
  updateText("investigation-role", "No role assigned.");
  els.investigationAlert.textContent = message;
  els.investigationAlert.className = "investigation-alert";
  els.investigationSelect.innerHTML = '<option value="">Loading detection results...</option>';
  els.shapExplanations.innerHTML = "";
  renderTable(
    els.shapTable,
    [],
    [
      { key: "category", label: "Category" },
      { key: "contribution", label: "Contribution (%)" },
    ],
    "Investigation details will appear when detection completes."
  );
  updateBarChart("roleChart", document.getElementById("role-chart"), [], [], "#38bdf8", {
    label: "Role Strength",
    title: "Fraud Role Classification",
    xTitle: "Role Type",
    yTitle: "Strength (%)",
  });
  updateBarChart("shapChart", document.getElementById("shap-chart"), [], [], "#38bdf8", {
    label: "Contribution",
    indexAxis: "y",
    title: "SHAP Risk Breakdown",
    xTitle: "Contribution (%)",
    yTitle: "Risk Category",
  });
  state.currentInvestigationAccount = null;
  scheduleUiSync();
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value || 0)));
}

function parseTxTime(value) {
  const parsed = new Date(value || 0).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}

function getAccountRecord(accountId) {
  return (state.lastAccounts || []).find((account) => String(account.account_id) === String(accountId)) || null;
}

function getDeviceFingerprint(account) {
  if (!account) return "device-unknown";
  if (account.device_id) return String(account.device_id);
  const numeric = Number(String(account.account_id || "").replace(/\D/g, "")) || 0;
  return `device-${numeric % 23}`;
}

function getAccountTransactions(accountId) {
  const id = String(accountId);
  return (state.transactions || []).filter((tx) => String(tx.sender || tx.source || "") === id || String(tx.receiver || tx.target || "") === id);
}

function getRoleColor(role) {
  if (role === "Ring Coordinator") return "#ff5d7d";
  if (role === "Collector Mule") return "#ffbe5c";
  if (role === "Distributor Mule") return "#38bdf8";
  return "#94a3b8";
}

function buildInvestigationMetrics(accountId) {
  const account = getAccountRecord(accountId);
  const relatedTx = getAccountTransactions(accountId)
    .slice()
    .sort((left, right) => parseTxTime(left.timestamp) - parseTxTime(right.timestamp));
  const incomingTx = relatedTx.filter((tx) => String(tx.receiver || tx.target || "") === String(accountId));
  const outgoingTx = relatedTx.filter((tx) => String(tx.sender || tx.source || "") === String(accountId));
  const incomingAmount = incomingTx.reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
  const outgoingAmount = outgoingTx.reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
  const allChannels = new Set(relatedTx.map((tx) => String(tx.channel || "Unknown")));
  const uniqueIncoming = new Set(incomingTx.map((tx) => String(tx.sender || tx.source || ""))).size;
  const uniqueOutgoing = new Set(outgoingTx.map((tx) => String(tx.receiver || tx.target || ""))).size;
  const neighbors = new Set([
    ...incomingTx.map((tx) => String(tx.sender || tx.source || "")),
    ...outgoingTx.map((tx) => String(tx.receiver || tx.target || "")),
  ]);
  neighbors.delete(String(accountId));
  let shortGapCount = 0;
  for (let index = 1; index < relatedTx.length; index += 1) {
    if (parseTxTime(relatedTx[index].timestamp) - parseTxTime(relatedTx[index - 1].timestamp) <= 90000) {
      shortGapCount += 1;
    }
  }
  const attackIncidentCount = relatedTx.filter((tx) => tx.isAttack === true || tx.is_attack === true).length;
  const deviceFingerprint = getDeviceFingerprint(account);
  const deviceClusterSize = (state.lastAccounts || []).filter(
    (candidate) =>
      candidate.is_active !== false &&
      getDeviceFingerprint(candidate) === deviceFingerprint
  ).length;
  const linkedFraudNeighbors = [...neighbors].filter((neighborId) => state.fraudNodeSet.has(String(neighborId))).length;
  const linkedSuspiciousNeighbors = [...neighbors].filter((neighborId) => state.currentEarlyIds.has(String(neighborId))).length;
  const retentionRatio = outgoingAmount > 0
    ? clamp01(incomingAmount > 0 ? outgoingAmount / Math.max(incomingAmount, 1) : 1)
    : 0;
  const passThroughRatio = incomingTx.length > 0
    ? clamp01(outgoingTx.length / Math.max(incomingTx.length, 1))
    : 0;

  return {
    account,
    relatedTx,
    incomingTx,
    outgoingTx,
    transactionCount: relatedTx.length,
    shortGapCount,
    incomingAmount,
    outgoingAmount,
    inDegree: uniqueIncoming,
    outDegree: uniqueOutgoing,
    neighborCount: neighbors.size,
    linkedFraudNeighbors,
    linkedSuspiciousNeighbors,
    uniqueChannels: allChannels.size,
    deviceClusterSize,
    retentionRatio,
    passThroughRatio,
    attackIncidentCount,
    liveRiskScore: Number(account?.risk_score || state.accountStore.get(String(accountId))?.risk_score || 0),
  };
}

function buildRoleStrengths(metrics) {
  const ring = clamp01((metrics.neighborCount / 8) * 0.42 + (Math.min(metrics.inDegree, metrics.outDegree) / 5) * 0.34 + (metrics.linkedFraudNeighbors / 4) * 0.24);
  const collector = clamp01((metrics.inDegree / 6) * 0.52 + (metrics.incomingAmount / 180000) * 0.24 + ((1 - clamp01(metrics.outDegree / Math.max(metrics.inDegree || 1, 1))) * 0.24));
  const distributor = clamp01((metrics.outDegree / 6) * 0.52 + (metrics.outgoingAmount / 180000) * 0.24 + (metrics.passThroughRatio * 0.24));
  return {
    "Ring Coordinator": ring,
    "Collector Mule": collector,
    "Distributor Mule": distributor,
  };
}

function buildRiskCategoryContributions(metrics) {
  const velocityRisk = clamp01((metrics.transactionCount / 24) * 0.62 + (metrics.shortGapCount / 10) * 0.38);
  const sharedDeviceRisk = clamp01((metrics.deviceClusterSize - 1) / 5);
  const ringParticipationRisk = clamp01((metrics.neighborCount / 8) * 0.48 + ((metrics.inDegree + metrics.outDegree) / 10) * 0.28 + (metrics.linkedFraudNeighbors / 4) * 0.24);
  const channelRisk = clamp01((metrics.uniqueChannels - 1) / 4);
  const retentionRisk = clamp01(metrics.retentionRatio * 0.58 + metrics.passThroughRatio * 0.42);

  const raw = [
    { category: "Velocity Risk", value: velocityRisk, details: `${metrics.transactionCount} transactions, ${metrics.shortGapCount} rapid gaps` },
    { category: "Shared Device Risk", value: sharedDeviceRisk, details: `${metrics.deviceClusterSize} account(s) share device pattern` },
    { category: "Ring Participation Risk", value: ringParticipationRisk, details: `${metrics.neighborCount} connected neighbors` },
    { category: "Channel Risk", value: channelRisk, details: `${metrics.uniqueChannels} payment channel(s)` },
    { category: "Retention Risk", value: retentionRisk, details: `${safeNumber(metrics.retentionRatio * 100, 1)}% retention ratio` },
  ];
  const total = raw.reduce((sum, item) => sum + item.value, 0) || 1;
  return raw
    .map((item) => ({
      category: item.category,
      contribution: Number(((item.value / total) * 100).toFixed(1)),
      rawValue: Number(item.value.toFixed(4)),
      details: item.details,
    }))
    .sort((left, right) => right.contribution - left.contribution);
}

function buildDynamicExplanation(accountId, metrics, shapCategories, role) {
  const topDrivers = shapCategories.slice(0, 3);
  const lead = topDrivers.map((item) => item.category.replace(" Risk", "").toLowerCase());
  const driverText = lead.length > 1
    ? `${lead.slice(0, -1).join(", ")} and ${lead.slice(-1)}`
    : (lead[0] || "transaction behavior");
  const lines = [
    `This account is flagged due to ${driverText}.`,
    `${role} behavior is visible through ${metrics.inDegree} incoming and ${metrics.outDegree} outgoing counterparties.`,
  ];
  if (metrics.deviceClusterSize > 1) {
    lines.push(`It shares a device signature with ${metrics.deviceClusterSize} accounts, increasing mule-network risk.`);
  }
  if (metrics.uniqueChannels > 1) {
    lines.push(`Funds moved across ${metrics.uniqueChannels} channels, which raises layering and evasion concerns.`);
  } else {
    lines.push(`Funds are concentrated through ${metrics.uniqueChannels || 1} dominant channel, which helps isolate the money path.`);
  }
  return {
    summary: lines.join(" "),
    bullets: topDrivers.map((item) => `${item.category}: ${item.details}. Contribution ${safeNumber(item.contribution, 1)}%.`),
  };
}

function buildInvestigationPayload(accountId) {
  const id = String(accountId);
  const metrics = buildInvestigationMetrics(id);
  const shapCategories = buildRiskCategoryContributions(metrics);
  const roleStrengths = buildRoleStrengths(metrics);
  const roleEntries = Object.entries(roleStrengths).sort((left, right) => right[1] - left[1]);
  const role = roleEntries[0]?.[0] || "Unclassified";

  const row = (state.dashboard?.ml_detection?.table || []).find((entry) => String(entry.account_id) === id) || {};
  const localMl = clamp01(
    shapCategories.find((item) => item.category === "Velocity Risk")?.rawValue * 0.34 +
    shapCategories.find((item) => item.category === "Ring Participation Risk")?.rawValue * 0.28 +
    shapCategories.find((item) => item.category === "Retention Risk")?.rawValue * 0.18 +
    shapCategories.find((item) => item.category === "Shared Device Risk")?.rawValue * 0.12 +
    shapCategories.find((item) => item.category === "Channel Risk")?.rawValue * 0.08
  );
  const localRule = clamp01(
    (metrics.transactionCount / 18) * 0.28 +
    (metrics.shortGapCount / 8) * 0.2 +
    (metrics.uniqueChannels / 4) * 0.12 +
    (metrics.linkedFraudNeighbors / 3) * 0.22 +
    (metrics.deviceClusterSize / 6) * 0.18
  );
  const localGnn = clamp01(
    roleStrengths["Ring Coordinator"] * 0.44 +
    roleStrengths["Collector Mule"] * 0.18 +
    roleStrengths["Distributor Mule"] * 0.18 +
    (metrics.linkedFraudNeighbors / 4) * 0.2
  );

  const mlScore = Number(row.ml_score ?? localMl);
  const ruleScore = Number(row.rule_score_norm ?? localRule);
  const gnnScore = Number(row.gnn_score ?? localGnn);
  const finalScore = clamp01(Number(row.final_score ?? (mlScore * 0.45 + ruleScore * 0.25 + gnnScore * 0.3)));
  const fraudScore = Number((finalScore * 100).toFixed(2));
  const confidence = fraudScore > 70 ? "High Confidence" : fraudScore >= 50 ? "Medium Confidence" : "Low Confidence";
  const severity = fraudScore > 70 ? "high" : fraudScore >= 50 ? "medium" : "low";
  const explanation = buildDynamicExplanation(id, metrics, shapCategories, role);

  return {
    account_id: id,
    fraud_score: fraudScore,
    confidence,
    severity,
    ml_score: Number(mlScore.toFixed(4)),
    rule_score_norm: Number(ruleScore.toFixed(4)),
    gnn_score: Number(gnnScore.toFixed(4)),
    role,
    role_counts: {
      labels: roleEntries.map(([label]) => label),
      values: roleEntries.map(([, value]) => Number((value * 100).toFixed(1))),
    },
    shap: {
      available: true,
      categories: shapCategories,
      explanations: explanation.bullets,
      summary: explanation.summary,
    },
    metrics,
  };
}

function clearInvestigationHighlight() {
  state.investigationHighlightId = null;
  if (!state.liveNodes.length) {
    return;
  }
  state.liveNodes.update(
    state.liveNodes.get().map((node) => ({
      id: node.id,
      size: Number(node.baseSize || node.size || 24),
      opacity: 1,
    }))
  );
  state.liveEdges.update(
    state.liveEdges.get().map((edge) => ({
      id: edge.id,
      width: edge.persistent ? Math.max(Number(edge.width || 2.2), 2.2) : 1.2,
      opacity: edge.persistent ? 0.78 : 0.22,
    }))
  );
  state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
}

function applyInvestigationHighlight(accountId) {
  const selectedId = String(accountId || "");
  clearInvestigationHighlight();
  state.investigationHighlightId = selectedId || null;
  if (!selectedId || !state.liveNodes.length) {
    return;
  }

  const connectedEdges = state.liveEdges.get().filter((edge) => String(edge.from) === selectedId || String(edge.to) === selectedId);
  const neighborIds = new Set(
    connectedEdges.flatMap((edge) => [String(edge.from), String(edge.to)]).filter((id) => id !== selectedId)
  );
  const focusIds = [selectedId, ...neighborIds];

  const nodeUpdates = state.liveNodes.get().map((node) => {
    const baseSize = Number(node.baseSize || node.size || 24);
    if (String(node.id) === selectedId) {
      return { id: node.id, size: Math.max(baseSize, 42), opacity: 1 };
    }
    if (neighborIds.has(String(node.id))) {
      return { id: node.id, size: Math.max(baseSize, 28), opacity: 0.92 };
    }
    return { id: node.id, size: Math.max(10, baseSize * 0.72), opacity: 0.2 };
  });
  const edgeUpdates = state.liveEdges.get().map((edge) => {
    const connected = String(edge.from) === selectedId || String(edge.to) === selectedId;
    return {
      id: edge.id,
      width: connected ? Math.max(Number(edge.width || 1.2), 2.6) : 0.8,
      opacity: connected ? 0.82 : 0.08,
    };
  });

  state.liveNodes.update(nodeUpdates);
  state.liveEdges.update(edgeUpdates);
  state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
  state.liveNetwork?.fit({
    nodes: focusIds,
    animation: { duration: 720, easingFunction: "easeInOutQuad" },
  });
  pulseNetworkFrame(els.liveNetworkFrame);
}

function recordDashboardHistory(dashboard, crossCheck, fraudAccounts) {
  const attackName = String(dashboard?.attack_name || "");
  if (!attackName || !dashboard?.available || !isFraudRevealPhase()) {
    return;
  }
  const roleTotals = { "Ring Coordinator": 0, "Collector Mule": 0, "Distributor Mule": 0 };
  fraudAccounts.forEach((accountId) => {
    const payload = buildInvestigationPayload(accountId);
    roleTotals[payload.role] = (roleTotals[payload.role] || 0) + 1;
  });
  const recallValue = Number.isFinite(Number(dashboard?.ml_detection?.recall))
    ? Number(dashboard.ml_detection.recall)
    : ((crossCheck.matched || 0) / Math.max(1, (crossCheck.matched || 0) + (crossCheck.sleeper || 0)));
  const thresholdValue = Number(dashboard?.ml_detection?.threshold ?? state.live?.early_warning?.threshold ?? 0);
  const cycleKey = dashboard?.detection_job?.attack_time || dashboard?.detection_job?.job_id || state.attackSequenceToken || attackName;
  const signature = `${cycleKey}|${attackName}|${fraudAccounts.join(",")}|${safeNumber(thresholdValue, 4)}|${safeNumber(recallValue, 4)}`;
  if (signature === state.lastHistorySignature) {
    return;
  }
  state.lastHistorySignature = signature;
  const nextRunIndex = state.dashboardHistory.labels.length + 1;
  state.dashboardHistory.labels.push(`Run ${nextRunIndex}`);
  state.dashboardHistory.thresholds.push(Number(thresholdValue.toFixed(3)));
  state.dashboardHistory.recalls.push(Number(recallValue.toFixed(3)));
  state.dashboardHistory.roleTotals = roleTotals;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => {
    const replacements = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return replacements[char] || char;
  });
}

function formatCellValue(value) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "--";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return String(value);
    }
  }
  return String(value);
}

function renderTagList(container, items, emptyMessage, tone = "neutral") {
  if (!items || !items.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    scheduleUiSync();
    return;
  }

  container.innerHTML = items
    .map(
      (item) =>
        `<span class="token-pill token-pill--${tone}">${escapeHtml(String(item))}</span>`
    )
    .join("");
  scheduleUiSync();
}

function renderStructuredGroups(container, groups) {
  container.innerHTML = groups
    .map((group) => {
      const items = group.items || [];
      const body = items.length
        ? items
            .map(
              (item) =>
                `<span class="token-pill token-pill--${group.tone || "neutral"}">${escapeHtml(String(item))}</span>`
            )
            .join("")
        : `<div class="empty-state">None</div>`;

      return `
        <section class="structured-item">
          <div class="structured-item__head">
            <strong>${escapeHtml(group.label)}</strong>
            <span class="structured-item__count">${items.length} account${items.length === 1 ? "" : "s"}</span>
          </div>
          <div class="token-stream">${body}</div>
        </section>
      `;
    })
    .join("");
  scheduleUiSync();
}

function renderTable(container, rows, columns, emptyMessage) {
  const safeRows = Array.isArray(rows) ? rows : [];
  const safeColumns = Array.isArray(columns) ? columns : [];
  const sampleCount = Math.min(8, safeRows.length);
  let sample = "";
  for (let i = 0; i < sampleCount; i += 1) {
    const row = safeRows[i] || {};
    for (let j = 0; j < safeColumns.length; j += 1) {
      const key = safeColumns[j].key;
      sample += `|${String(row[key] ?? "")}`;
    }
  }
  const tableHash = `${safeRows.length}|${safeColumns.map((c) => c.key).join(",")}|${sample}|${emptyMessage || ""}`;
  if (state.tableRenderCache.get(container) === tableHash) {
    return;
  }

  if (!safeRows.length) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(emptyMessage)}</div>`;
    state.tableRenderCache.set(container, tableHash);
    scheduleUiSync();
    return;
  }

  const headers = safeColumns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  const body = safeRows
    .map((row) => {
      const cells = safeColumns
        .map((column) => {
          const content = escapeHtml(formatCellValue(row[column.key]));
          return `<td data-label="${escapeHtml(column.label)}">${content}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  container.innerHTML = `
    <table class="data-table">
      <thead><tr>${headers}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
  state.tableRenderCache.set(container, tableHash);
  scheduleUiSync();
}

function createChart(ctx, config) {
  if (!ctx) return null;
  return new Chart(ctx, config);
}

function updateBarChart(key, ctx, labels, values, color, options = {}) {
  const nextHash = JSON.stringify({
    labels,
    values,
    color,
    type: options.type || "bar",
    label: options.label || "",
    indexAxis: options.indexAxis || "x",
    title: options.title || "",
    xTitle: options.xTitle || "",
    yTitle: options.yTitle || "",
  });
  if (!state.charts[key]) {
    state.chartRenderHashes[key] = nextHash;
    state.charts[key] = createChart(ctx, {
      type: options.type || "bar",
      data: {
        labels,
        datasets: [
          {
            label: options.label || "",
            data: values,
            backgroundColor: color,
            borderColor: color,
            borderWidth: 1,
            borderRadius: 8,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        indexAxis: options.indexAxis || "x",
        plugins: {
          legend: { display: false },
          title: {
            display: Boolean(options.title),
            text: options.title || "",
            color: "#edf7f1",
            padding: { bottom: 12 },
            font: { size: 15, weight: "600" },
          },
        },
        scales: {
          x: {
            title: {
              display: Boolean(options.xTitle),
              text: options.xTitle || "",
              color: "#93a4c5",
              font: { size: 12, weight: "600" },
            },
            ticks: { color: "#93a4c5" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            beginAtZero: true,
            title: {
              display: Boolean(options.yTitle),
              text: options.yTitle || "",
              color: "#93a4c5",
              font: { size: 12, weight: "600" },
            },
            ticks: { color: "#93a4c5" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
        },
      },
    });
    return;
  }

  if (state.chartRenderHashes[key] === nextHash) {
    return;
  }
  state.chartRenderHashes[key] = nextHash;
  state.charts[key].data.labels = labels;
  state.charts[key].data.datasets[0].data = values;
  state.charts[key].data.datasets[0].backgroundColor = color;
  state.charts[key].data.datasets[0].borderColor = color;
  state.charts[key].options.indexAxis = options.indexAxis || "x";
  state.charts[key].options.plugins.title.display = Boolean(options.title);
  state.charts[key].options.plugins.title.text = options.title || "";
  state.charts[key].options.scales.x.title.display = Boolean(options.xTitle);
  state.charts[key].options.scales.x.title.text = options.xTitle || "";
  state.charts[key].options.scales.y.title.display = Boolean(options.yTitle);
  state.charts[key].options.scales.y.title.text = options.yTitle || "";
  state.charts[key].update("none");
}

function updateLineChart(key, ctx, labels, values, color, label, options = {}) {
  const nextHash = JSON.stringify({
    labels,
    values,
    color,
    label,
    title: options.title || "",
    xTitle: options.xTitle || "",
    yTitle: options.yTitle || "",
  });
  if (!state.charts[key]) {
    state.chartRenderHashes[key] = nextHash;
    state.charts[key] = createChart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label,
            data: values,
            borderColor: color,
            backgroundColor: color,
            tension: 0.35,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          title: {
            display: Boolean(options.title),
            text: options.title || "",
            color: "#edf7f1",
            padding: { bottom: 12 },
            font: { size: 15, weight: "600" },
          },
        },
        scales: {
          x: {
            title: {
              display: Boolean(options.xTitle),
              text: options.xTitle || "",
              color: "#93a4c5",
              font: { size: 12, weight: "600" },
            },
            ticks: { color: "#93a4c5" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            title: {
              display: Boolean(options.yTitle),
              text: options.yTitle || "",
              color: "#93a4c5",
              font: { size: 12, weight: "600" },
            },
            ticks: { color: "#93a4c5" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
        },
      },
    });
    return;
  }

  if (state.chartRenderHashes[key] === nextHash) {
    return;
  }
  state.chartRenderHashes[key] = nextHash;
  state.charts[key].data.labels = labels;
  state.charts[key].data.datasets[0].data = values;
  state.charts[key].data.datasets[0].label = label;
  state.charts[key].options.plugins.title.display = Boolean(options.title);
  state.charts[key].options.plugins.title.text = options.title || "";
  state.charts[key].options.scales.x.title.display = Boolean(options.xTitle);
  state.charts[key].options.scales.x.title.text = options.xTitle || "";
  state.charts[key].options.scales.y.title.display = Boolean(options.yTitle);
  state.charts[key].options.scales.y.title.text = options.yTitle || "";
  state.charts[key].update("none");
}

function updateRiskDistributionChart(ctx, scores, threshold) {
  const labels = scores.map((_, index) => `${index + 1}`);
  const thresholdSeries = scores.map(() => threshold);
  const nextHash = JSON.stringify({ labels, scores, thresholdSeries });

  if (!state.charts.suspicionChart) {
    state.chartRenderHashes.suspicionChart = nextHash;
    state.charts.suspicionChart = createChart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Risk score",
            data: scores,
            borderColor: "#ffbe5c",
            backgroundColor: "rgba(255, 190, 92, 0.16)",
            fill: true,
            tension: 0.22,
            pointRadius: 2,
            pointHoverRadius: 4,
          },
          {
            label: "Adaptive threshold",
            data: thresholdSeries,
            borderColor: "#38bdf8",
            borderDash: [6, 6],
            pointRadius: 0,
            fill: false,
            tension: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: true, labels: { color: "#dbe7ff" } },
          title: {
            display: true,
            text: "Risk Distribution",
            color: "#edf7f1",
          },
        },
        scales: {
          x: {
            title: {
              display: true,
              text: "Accounts ranked by suspicious score",
              color: "#93a4c5",
            },
            ticks: { color: "#93a4c5", maxTicksLimit: 8 },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
          y: {
            min: 0,
            max: 1,
            title: {
              display: true,
              text: "Risk score",
              color: "#93a4c5",
            },
            ticks: { color: "#93a4c5" },
            grid: { color: "rgba(255,255,255,0.06)" },
          },
        },
      },
    });
    return;
  }

  if (state.chartRenderHashes.suspicionChart === nextHash) {
    return;
  }
  state.chartRenderHashes.suspicionChart = nextHash;
  state.charts.suspicionChart.data.labels = labels;
  state.charts.suspicionChart.data.datasets[0].data = scores;
  state.charts.suspicionChart.data.datasets[1].data = thresholdSeries;
  state.charts.suspicionChart.update("none");
}

function wait(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function buildTransactionSignature(tx) {
  if (tx.transaction_id) {
    return String(tx.transaction_id);
  }
  const source = String(tx.sender || tx.source || "");
  const target = String(tx.receiver || tx.target || "");
  const amount = Number(tx.amount || 0).toFixed(2);
  const timestamp = String(tx.timestamp || "");
  return `${source}-${target}-${amount}-${timestamp}`;
}

function rememberSeenTransaction(tx) {
  const signature = buildTransactionSignature(tx);
  if (state.seenTransactions.has(signature)) {
    return signature;
  }
  state.seenTransactions.add(signature);
  state.seenTransactionOrder.push(signature);
  while (state.seenTransactionOrder.length > MAX_SEEN_TRANSACTION_SIGNATURES) {
    const removed = state.seenTransactionOrder.shift();
    if (removed) {
      state.seenTransactions.delete(removed);
    }
  }
  return signature;
}

function normalizeTransaction(tx = {}) {
  const sender = String(tx.sender ?? tx.source ?? "");
  const receiver = String(tx.receiver ?? tx.target ?? "");
  const timestamp = tx.timestamp || new Date().toISOString();
  const isAttack = tx?.isAttack === true || tx?.is_attack === true;
  return {
    ...tx,
    sender,
    receiver,
    source: sender,
    target: receiver,
    timestamp,
    isAttack,
    is_attack: isAttack,
  };
}

function rememberTransactionHistory(tx) {
  state.transactions.push(tx);
  if (state.transactions.length > 4000) {
    state.transactions = state.transactions.slice(-4000);
  }
}

function queuePreparedTransactions(prepared = []) {
  if (!Array.isArray(prepared) || !prepared.length) {
    return;
  }
  for (let i = 0; i < prepared.length; i += 1) {
    const tx = normalizeTransaction(prepared[i]);
    rememberTransactionHistory(tx);
    state.transactionQueue.push(tx);
  }
  ensureVisualLoop();
}

function initTransactionWorker() {
  if (state.txWorker) {
    return;
  }
  try {
    const worker = new Worker("/tx-worker.js");
    worker.onmessage = (event) => {
      const payload = event.data || {};
      if (payload.type === "prepared") {
        queuePreparedTransactions(payload.transactions || []);
      }
    };
    worker.onerror = () => {
      state.txWorkerEnabled = false;
      state.txWorker = null;
    };
    state.txWorker = worker;
    state.txWorkerEnabled = true;
  } catch (error) {
    state.txWorkerEnabled = false;
    state.txWorker = null;
  }
}

function markTransactionsSeen(transactions = []) {
  transactions.forEach((tx) => {
    const normalizedTx = normalizeTransaction(tx);
    rememberSeenTransaction(normalizedTx);
    rememberTransactionHistory(normalizedTx);
  });
}

function scaleGraphCoordinate(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num * GRAPH_POSITION_SCALE : undefined;
}

function unscaleGraphCoordinate(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num / GRAPH_POSITION_SCALE : undefined;
}

function getNetworkForKind(kind) {
  return kind === "attack" ? state.attackNetwork : state.liveNetwork;
}

function getOverlayForKind(kind) {
  return kind === "attack" ? els.attackNetworkOverlay : els.liveNetworkOverlay;
}

function getEdgeDataSet(kind) {
  return kind === "attack" ? state.attackEdges : state.liveEdges;
}

function getNodeDataSet(kind) {
  return kind === "attack" ? state.attackNodes : state.liveNodes;
}

function getGraphAdapter(kind) {
  return kind === "attack" ? state.attackGraph3D : state.liveGraph3D;
}

function upsertGraphEdge(kind, edge) {
  const adapter = getGraphAdapter(kind);
  if (adapter && edge) {
    adapter.upsertEdge(edge);
  }
}

function removeGraphEdge(kind, edgeId) {
  const adapter = getGraphAdapter(kind);
  if (adapter && edgeId) {
    adapter.removeEdge(edgeId);
  }
}

function getOverlayMetrics(canvas, force = false) {
  if (!canvas) {
    return null;
  }

  const dpr = window.devicePixelRatio || 1;
  const clientWidth = Math.max(1, canvas.clientWidth || 1);
  const clientHeight = Math.max(1, canvas.clientHeight || 1);
  const cached = canvas.__overlayMetrics;

  if (
    !force &&
    cached &&
    cached.clientWidth === clientWidth &&
    cached.clientHeight === clientHeight &&
    cached.dpr === dpr
  ) {
    return cached;
  }

  const rect = canvas.getBoundingClientRect();
  const metrics = {
    rectWidth: rect.width,
    rectHeight: rect.height,
    clientWidth,
    clientHeight,
    dpr,
    width: Math.max(1, Math.round(rect.width * dpr)),
    height: Math.max(1, Math.round(rect.height * dpr)),
  };
  canvas.__overlayMetrics = metrics;
  return metrics;
}

function resizeOverlayCanvas(canvas) {
  if (!canvas) {
    return null;
  }
  const metrics = getOverlayMetrics(canvas);
  if (!metrics) {
    return null;
  }
  const { width, height, dpr, rectWidth, rectHeight } = metrics;

  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rectWidth, rectHeight);
  return { ctx, rect: { width: rectWidth, height: rectHeight } };
}

function clearOverlayCanvas(canvas) {
  if (!canvas) {
    return;
  }
  const metrics = getOverlayMetrics(canvas);
  const ctx = canvas.getContext("2d");
  if (!ctx || !metrics) {
    return;
  }
  const { dpr, rectWidth, rectHeight } = metrics;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rectWidth, rectHeight);
}

function clearAllTravelerOverlays() {
  clearOverlayCanvas(els.liveNetworkOverlay);
  clearOverlayCanvas(els.attackNetworkOverlay);
}

function getNodeDomPoints(network, nodeIds) {
  if (!network || !Array.isArray(nodeIds) || !nodeIds.length) {
    return new Map();
  }

  const uniqueIds = [...new Set(nodeIds.map((nodeId) => String(nodeId)).filter(Boolean))];
  if (!uniqueIds.length) {
    return new Map();
  }

  const positions = network.getPositions(uniqueIds);
  const domPoints = new Map();
  uniqueIds.forEach((nodeId) => {
    const point = positions?.[nodeId];
    if (!point) {
      return;
    }
    domPoints.set(nodeId, network.canvasToDOM(point));
  });
  return domPoints;
}

function drawTravelerTail(ctx, start, end, color, width = 1.15) {
  ctx.save();
  const gradient = ctx.createLinearGradient(start.x, start.y, end.x, end.y);
  gradient.addColorStop(0, "rgba(255, 255, 255, 0)");
  gradient.addColorStop(0.38, color);
  gradient.addColorStop(1, "rgba(255, 255, 255, 0.42)");
  ctx.strokeStyle = gradient;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();
  ctx.restore();
}

function drawTravelerDot(ctx, x, y, radius = 2.25, glowColor = "rgba(255, 255, 255, 0.16)") {
  ctx.save();
  const glow = ctx.createRadialGradient(x, y, 0, x, y, radius * 2.8);
  glow.addColorStop(0, "rgba(255, 255, 255, 0.92)");
  glow.addColorStop(0.3, glowColor);
  glow.addColorStop(0.56, "rgba(255, 255, 255, 0.14)");
  glow.addColorStop(1, "rgba(255, 255, 255, 0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(x, y, radius * 2.8, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#ffffff";
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function removeEdgeIfPresent(kind, edgeId) {
  if (!edgeId) {
    return;
  }
  const dataset = getEdgeDataSet(kind);
  if (dataset.get(edgeId)) {
    dataset.remove(edgeId);
  }
  removeGraphEdge(kind, edgeId);
}

function removeConnectedEdges(accountIds) {
  const ids = new Set((accountIds || []).map((accountId) => String(accountId)));
  if (!ids.size) {
    return;
  }

  const liveRemovals = state.liveEdges
    .get()
    .filter((edge) => ids.has(String(edge.from)) || ids.has(String(edge.to)))
    .map((edge) => edge.id);
  if (liveRemovals.length) {
    state.liveEdges.remove(liveRemovals);
    liveRemovals.forEach((edgeId) => removeGraphEdge("live", edgeId));
    liveRemovals.forEach((edgeId) => {
      state.persistentAttackEdgeIds.delete(edgeId);
      state.fraudEdgeSet.delete(String(edgeId));
    });
  }

  const attackRemovals = state.attackEdges
    .get()
    .filter((edge) => ids.has(String(edge.from)) || ids.has(String(edge.to)))
    .map((edge) => edge.id);
  if (attackRemovals.length) {
    state.attackEdges.remove(attackRemovals);
    attackRemovals.forEach((edgeId) => removeGraphEdge("attack", edgeId));
  }
}

function markNodesBanned(accountIds) {
  const ids = (accountIds || []).map((accountId) => String(accountId));
  if (!ids.length) {
    return;
  }

  const liveUpdates = [];
  ids.forEach((accountId) => {
    const existing = state.liveNodes.get(accountId);
    if (!existing) {
      return;
    }
    const next = accountStyle(accountId, "banned", getNodeVisualPayload(existing, existing));
    if (existing.label) {
      next.label = existing.label;
    }
    liveUpdates.push(next);
  });

  if (liveUpdates.length) {
    state.liveNodes.update(liveUpdates);
  }
  ids.forEach((accountId) => {
    upsertAccountStore(accountId, {
      status: "banned",
      risk_score: 0,
      selected_for_ban: false,
    });
    state.selectedForBan.delete(accountId);
    state.currentEarlyIds.delete(accountId);
  });
}

function runTravelerFrame(now) {
  state.travelerFrame = null;
  if (PERF_DEBUG) {
    console.time("traveler-frame");
  }
  const prepared = new Map();
  const pointsByKind = new Map();
  const nodeIdsByKind = new Map();
  const pending = [];
  const completed = [];

  const getPrepared = (kind) => {
    if (!prepared.has(kind)) {
      prepared.set(kind, resizeOverlayCanvas(getOverlayForKind(kind)));
    }
    return prepared.get(kind);
  };

  state.activeTravelers.forEach((traveler) => {
    if (!nodeIdsByKind.has(traveler.kind)) {
      nodeIdsByKind.set(traveler.kind, []);
    }
    nodeIdsByKind.get(traveler.kind).push(traveler.from, traveler.to);
  });

  nodeIdsByKind.forEach((nodeIds, kind) => {
    const network = getNetworkForKind(kind);
    pointsByKind.set(kind, getNodeDomPoints(network, nodeIds));
  });

  state.activeTravelers.forEach((traveler) => {
    const network = getNetworkForKind(traveler.kind);
    const preparedCanvas = getPrepared(traveler.kind);
    if (!network || !preparedCanvas) {
      completed.push(traveler);
      return;
    }

    const domPoints = pointsByKind.get(traveler.kind) || new Map();
    const start = domPoints.get(String(traveler.from));
    const end = domPoints.get(String(traveler.to));
    if (!start || !end) {
      completed.push(traveler);
      return;
    }

    const progress = Math.min(1, (now - traveler.startedAt) / traveler.duration);
    const eased = progress < 0.5
      ? 4 * progress * progress * progress
      : 1 - Math.pow(-2 * progress + 2, 3) / 2;
    const prevProgress = Math.max(0, progress - 0.12);
    const prevEased = prevProgress < 0.5
      ? 4 * prevProgress * prevProgress * prevProgress
      : 1 - Math.pow(-2 * prevProgress + 2, 3) / 2;
    const x = start.x + (end.x - start.x) * eased;
    const y = start.y + (end.y - start.y) * eased;
    const prevX = start.x + (end.x - start.x) * prevEased;
    const prevY = start.y + (end.y - start.y) * prevEased;
    drawTravelerTail(
      preparedCanvas.ctx,
      { x: prevX, y: prevY },
      { x, y },
      traveler.trailColor || "rgba(56, 189, 248, 0.24)",
      traveler.trailWidth || Math.max(1.1, (traveler.radius || 3.4) * 0.55)
    );
    drawTravelerDot(preparedCanvas.ctx, x, y, traveler.radius || 5.5, traveler.glowColor);

    if (progress >= 1) {
      completed.push(traveler);
    } else {
      pending.push(traveler);
    }
  });

  state.activeTravelers = pending;
  completed.forEach((traveler) => {
    traveler.onComplete?.();
  });

  if (state.activeTravelers.length) {
    state.travelerFrame = requestAnimationFrame(runTravelerFrame);
  } else {
    clearAllTravelerOverlays();
  }
  if (PERF_DEBUG) {
    console.timeEnd("traveler-frame");
  }
}

function queueTraveler(traveler) {
  if (state.activeTravelers.length >= MAX_ACTIVE_TRAVELERS) {
    const dropped = state.activeTravelers.shift();
    if (dropped) {
      removeEdgeIfPresent(dropped.kind, dropped.edgeId);
      dropped.onAbort?.();
    }
  }

  state.activeTravelers.push({
    radius: 2.1,
    ...traveler,
    startedAt: performance.now(),
  });

  if (!state.travelerFrame) {
    state.travelerFrame = requestAnimationFrame(runTravelerFrame);
  }
}

function debounceOnAnimationFrame(callback) {
  let frameId = null;
  return (...args) => {
    if (frameId) {
      cancelAnimationFrame(frameId);
    }
    frameId = requestAnimationFrame(() => {
      frameId = null;
      callback(...args);
    });
  };
}

function pulseNetworkFrame(frame) {
  if (!frame) {
    return;
  }
  const previousTimer = Number(frame.dataset.spotlightTimer || 0);
  if (previousTimer) {
    window.clearTimeout(previousTimer);
  }
  frame.classList.add("is-spotlight");
  frame.dataset.spotlightTimer = String(
    window.setTimeout(() => {
      frame.classList.remove("is-spotlight");
      delete frame.dataset.spotlightTimer;
    }, 1600)
  );
}

function applyNetworkZoomScaling() {
  ["live", "attack"].forEach((kind) => {
    const network = getNetworkForKind(kind);
    const nodes = getNodeDataSet(kind);
    const edges = getEdgeDataSet(kind);
    if (!network || !nodes.length) {
      return;
    }

    const scale = network.getScale();
    const multiplier = Math.max(0.82, Math.min(1.18, 0.82 + scale * 0.18));
    const showLabels = scale >= 0.9;
    const hideNonPersistentEdges = scale < 0.65;
    const updates = [];
    const edgeUpdates = [];
    nodes.forEach((node) => {
      const baseSize = Number(node.baseSize || node.size || 18);
      const nextSize = Number((baseSize * multiplier).toFixed(2));
      const nextLabel = showLabels ? (node.hoverLabel || "") : "";
      if (
        Math.abs(Number(node.size || 0) - nextSize) > 0.24 ||
        String(node.label || "") !== nextLabel
      ) {
        updates.push({ id: node.id, size: nextSize, label: nextLabel });
      }
    });

    if (updates.length) {
      nodes.update(updates);
    }

    if (edges && edges.length) {
      edges.forEach((edge) => {
        if (edge.persistent || edge.temporary) {
          return;
        }
        const nextHidden = hideNonPersistentEdges;
        if (Boolean(edge.hidden) !== nextHidden) {
          edgeUpdates.push({ id: edge.id, hidden: nextHidden });
        }
      });
      if (edgeUpdates.length) {
        edges.update(edgeUpdates);
      }
    }
  });
}

function scheduleNetworkZoomScaling() {
  if (state.networkScaleFrame) {
    cancelAnimationFrame(state.networkScaleFrame);
  }
  state.networkScaleFrame = requestAnimationFrame(() => {
    state.networkScaleFrame = null;
    applyNetworkZoomScaling();
  });
}

function networkOptions(compact = false) {
  return {
    autoResize: true,
    physics: false,
    layout: {
      improvedLayout: false,
      randomSeed: 24,
    },
    interaction: {
      hover: true,
      tooltipDelay: 120,
      navigationButtons: true,
      zoomView: true,
      dragView: true,
      hoverConnectedEdges: false,
      hideEdgesOnDrag: true,
    },
    edges: {
      smooth: false,
      color: { inherit: false, color: "rgba(56, 189, 248, 0.44)" },
      arrows: NO_EDGE_ARROWS,
      font: {
        color: "#dbe7ff",
        face: "JetBrains Mono",
        size: compact ? 11 : 0,
        strokeWidth: 0,
      },
      width: compact ? 1.65 : 1.2,
    },
    nodes: {
      shape: "dot",
      font: {
        face: "JetBrains Mono",
        color: "#eff6ff",
        size: compact ? 12 : 12,
      },
      borderWidth: 2,
      shadow: {
        enabled: true,
        size: compact ? 18 : 14,
        color: "rgba(14, 165, 233, 0.18)",
      },
    },
  };
}

function accountStyle(accountId, status, account = {}) {
  const labels = {
    normal: "#0ea5e9",
    early: "#ffbe5c",
    fraud: "#ff5d7d",
    banned: "#748399",
  };
  const shortId = String(accountId).slice(-4);
  const riskScore =
    account.riskScore !== null && account.riskScore !== undefined
      ? `Risk: ${(Number(account.riskScore || 0) * 100).toFixed(1)}%`
      : "";
  const reasons = Array.isArray(account.reasons) && account.reasons.length
    ? `Reasons: ${account.reasons.join(", ")}`
    : "";
  const baseSize =
    status === "fraud"
      ? 38
      : status === "early"
        ? 28 + Math.min(10, Math.round((Number(account.riskScore || 0) || 0) * 12))
        : 24;
  return {
    id: String(accountId),
    label: "",
    hoverLabel: `A-${shortId}`,
    title: `
      <div style="font-family: 'JetBrains Mono', monospace;">
        <strong>${accountId}</strong><br>
        Status: ${status}<br>
        Channel: ${account.channel || "--"}<br>
        ${riskScore}<br>
        ${reasons}
      </div>
    `,
    size: baseSize,
    baseSize,
    x: scaleGraphCoordinate(account.x),
    y: scaleGraphCoordinate(account.y),
    color: {
      background: labels[status],
      border: status === "fraud" ? "#ffd0d9" : "#d5e5ff",
      highlight: { background: labels[status], border: "#ffffff" },
      hover: { background: labels[status], border: "#ffffff" },
    },
    status,
    channel: account.channel || "--",
    riskScore: Number(account.riskScore || 0),
    reasons: Array.isArray(account.reasons) ? account.reasons : [],
    layoutPosition: account.layoutPosition || null,
  };
}

function pushFeed(feed, row, limit = 22) {
  feed.unshift(row);
  if (feed.length > limit) feed.length = limit;
}

function stopAttackAnimation() {
  state.attackSequenceToken += 1;
  state.attackSequenceStage = "idle";
  state.pendingAttackNodes = new Set();
  state.activeAttackName = null;
  state.isReplaying = false;
  if (state.attackAnimationTimer) {
    clearInterval(state.attackAnimationTimer);
    state.attackAnimationTimer = null;
  }
  if (state.attackReplayTimer) {
    clearInterval(state.attackReplayTimer);
    state.attackReplayTimer = null;
  }
  if (state.travelerFrame) {
    cancelAnimationFrame(state.travelerFrame);
    state.travelerFrame = null;
  }
  const transientEdgeIds = state.activeTravelers.map((traveler) => traveler.edgeId).filter(Boolean);
  if (transientEdgeIds.length) {
    state.liveEdges.remove(transientEdgeIds.filter((edgeId) => state.liveEdges.get(edgeId)));
  }
  state.activeTravelers = [];
  state.liveGraph3D?.txDots?.splice(0)?.forEach((dot) => state.liveGraph3D?._removeTxVisual?.(dot));
  state.attackGraph3D?.txDots?.splice(0)?.forEach((dot) => state.attackGraph3D?._removeTxVisual?.(dot));
  clearAllTravelerOverlays();
}

function clearAttackReplayState({ resetLatest = true, message = "Waiting for attack..." } = {}) {
  if (state.attackReplayTimer) {
    clearInterval(state.attackReplayTimer);
    state.attackReplayTimer = null;
  }
  state.isReplaying = false;
  state.subgraphCreated = false;
  state.attackNodes.clear();
  state.attackEdges.clear();
  state.attackGraph3D?.syncFromDataSets(state.attackNodes, state.attackEdges);
  state.attackGraphFittedFor = null;
  state.lastReplayAttackName = null;
  if (resetLatest) {
    state.latestAttackData = { attack_name: null, nodes: [], edges: [] };
  }
  state.attackTransactions = [];
  state.suspiciousFeed = [];
  state.feedDirty = true;
  flushFeedRender(performance.now(), true);
  updateText("attack-replay-meta", message);
  setReplayButtonDisabled(true);
}

function resetAttackState() {
  stopAttackAnimation();
  clearPersistentAttackEdges();
  clearCustomNodeLayouts();
  state.pendingAttackNodes = new Set();
  state.confirmedAttackNodes = new Set();
  syncFraudState();
  state.currentFraudIds = new Set();
  state.detectionFinalized = false;
  state.finalizedAttackName = null;
  state.activeAttackName = null;
  state.preAttackSnapshot = [];
  state.preAttackSuspiciousIds = [];
  clearAttackReplayState({ resetLatest: true, message: "Waiting for attack..." });
  els.attackAlertStrip.textContent = "Waiting for attack...";
  els.attackAlertStrip.classList.remove("alarm");
  updateText("metric-attack-pattern", "Idle");
  state.phase = DEMO_SIM_MODE && state.demoScenario ? PHASES.BUILD : PHASES.IDLE;
  if (state.demoScenario) {
    state.demoScenario.crossCheck = null;
    state.demoScenario.pendingGraph = null;
    state.demoScenario.attackTriggered = false;
    state.demoScenario.revealCompleted = false;
    state.demoScenario.intelligenceShown = false;
  }
  enforceFrontendMasterState({
    accounts: state.lastAccounts,
    live: state.live,
    forceMinimumSuspicious: true,
  });
  updateBanSelectOptions();
}

function shouldAcceptAttackPayload(data) {
  const incomingName = data?.attack_name || null;
  if (!incomingName) {
    return true;
  }

  if (
    state.activeAttackName &&
    state.attackSequenceStage !== "idle" &&
    incomingName !== state.activeAttackName
  ) {
    return false;
  }

  if (
    !state.activeAttackName &&
    state.detectionFinalized &&
    state.finalizedAttackName &&
    incomingName !== state.finalizedAttackName
  ) {
    return false;
  }

  return true;
}

function getValidatedAttackGraphData(data) {
  const edges = (data?.edges || [])
    .map((edge, index) => ({
      id: edge.id || `attack-${data?.attack_name || "cluster"}-${index}`,
      source: String(edge.source),
      target: String(edge.target),
      amount: Number(edge.amount || 0),
      channel: edge.channel || "TXN",
      timestamp: edge.timestamp || "",
    }))
    .filter((edge) => edge.source && edge.target && edge.source !== edge.target);

  const connectedNodeIds = new Set();
  edges.forEach((edge) => {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  });

  const nodeMap = new Map(
    (data?.nodes || []).map((node) => [String(node.id), { ...node, id: String(node.id) }])
  );

  const nodes = [...connectedNodeIds]
    .map((nodeId) => nodeMap.get(nodeId))
    .filter(Boolean);

  return {
    attack_name: data?.attack_name || null,
    nodes,
    edges: edges.filter(
      (edge) => connectedNodeIds.has(edge.source) && connectedNodeIds.has(edge.target)
    ),
    nodeIds: connectedNodeIds,
    edgeIds: new Set(edges.map((edge) => String(edge.id))),
  };
}

function buildAttackSubgraphSnapshot(data) {
  const validated = getValidatedAttackGraphData(data);
  const fraudIds = new Set(
    [...state.fraudNodeSet].filter((nodeId) => validated.nodeIds.has(String(nodeId)))
  );
  const finalFraudIds = fraudIds.size ? fraudIds : new Set(validated.nodeIds);
  const livePositions =
    state.liveNetwork?.getSourcePositions?.([...finalFraudIds]) ||
    state.liveNetwork?.getPositions?.([...finalFraudIds]) ||
    {};
  const nodeSourceMap = new Map(validated.nodes.map((node) => [String(node.id), node]));

  const nodes = [...finalFraudIds]
    .map((nodeId) => {
      const existing = state.liveNodes.get(String(nodeId));
      const sourceNode = nodeSourceMap.get(String(nodeId)) || {};
      if (!existing && !sourceNode.id) {
        return null;
      }
      const livePosition = livePositions[String(nodeId)] || livePositions[nodeId] || {};
      const next = accountStyle(
        nodeId,
        "fraud",
        {
          ...getNodeVisualPayload(existing, sourceNode),
          x: Number.isFinite(Number(livePosition.x))
            ? unscaleGraphCoordinate(livePosition.x)
            : getNodeVisualPayload(existing, sourceNode).x,
          y: Number.isFinite(Number(livePosition.y))
            ? unscaleGraphCoordinate(livePosition.y)
            : getNodeVisualPayload(existing, sourceNode).y,
        }
      );
      next.label = existing?.hoverLabel || next.hoverLabel || String(nodeId);
      return next;
    })
    .filter(Boolean);

  const nodeIds = new Set(nodes.map((node) => String(node.id)));
  const edges = validated.edges
    .filter(
      (edge) => nodeIds.has(String(edge.source)) && nodeIds.has(String(edge.target))
    )
    .map((edge, index) => ({
      id: `attack-static-${validated.attack_name || "cluster"}-${index}`,
      from: String(edge.source),
      to: String(edge.target),
      color: { color: "#ff5d7d" },
      width: 2.6,
      smooth: false,
      arrows: "to",
      label: `${Number(edge.amount || 0).toFixed(0)} ${edge.channel || ""}`.trim(),
      font: {
        color: "#ffe6ec",
        face: "JetBrains Mono",
        size: 11,
        strokeWidth: 0,
      },
      amount: Number(edge.amount || 0),
      channel: edge.channel || "TXN",
      source: String(edge.source),
      target: String(edge.target),
      timestamp: edge.timestamp || "",
    }));

  return {
    attack_name: validated.attack_name,
    nodes,
    edges,
    nodeIds,
  };
}

function freezeAttackSubgraph(snapshot) {
  state.attackNodes.clear();
  state.attackEdges.clear();
  if (snapshot?.nodes?.length) {
    state.attackNodes.add(snapshot.nodes);
  }
  if (snapshot?.edges?.length) {
    state.attackEdges.add(snapshot.edges);
  }
  state.subgraphCreated = Boolean(snapshot?.nodes?.length);
  state.attackGraphFittedFor = snapshot?.attack_name || null;
  state.attackNetwork.setOptions({ physics: false });
  state.attackGraph3D?.syncFromDataSets(state.attackNodes, state.attackEdges);
  scheduleNetworkZoomScaling();
}

function syncFraudState(nodeIds = [], edgeIds = []) {
  state.fraudNodeSet = new Set((nodeIds || []).map((nodeId) => String(nodeId)));
  state.fraudEdgeSet = new Set((edgeIds || []).map((edgeId) => String(edgeId)));
  state.confirmedAttackNodes = new Set(state.fraudNodeSet);
  state.currentFraudIds = new Set(state.fraudNodeSet);
  syncFrontendDerivedLists();
}

function getActiveFraudAccounts(dashboard = state.dashboard) {
  const banned = new Set([
    ...(dashboard?.banned_accounts || []).map((accountId) => String(accountId)),
    ...state.bannedList,
  ]);
  return [...new Set(state.fraudList || [])]
    .filter((accountId) => !banned.has(String(accountId)))
    .sort();
}

function updateBanSelectOptions(dashboard = state.dashboard) {
  if (!state.banSelect) {
    return;
  }
  const fraudAccounts = getActiveFraudAccounts(dashboard);
  const selected = [...state.selectedForBan].filter((id) => fraudAccounts.includes(String(id)));
  state.banSelect.clearOptions();
  state.banSelect.addOptions(fraudAccounts.map((accountId) => ({ value: accountId, text: accountId })));
  state.banSelect.setValue(selected, true);
  state.banSelect.refreshOptions(false);
  if (state.banSelect.control_input) {
    state.banSelect.control_input.disabled = fraudAccounts.length === 0;
  }
  if (els.banSelectAllBtn) {
    els.banSelectAllBtn.disabled = fraudAccounts.length === 0;
  }
  setBanSelection(selected);
}

function rebuildSuspiciousSummaryFromLiveNodes(live = state.live || {}) {
  if (!state.suspiciousList.length && state.lastAccounts.length) {
    enforceFrontendMasterState({
      accounts: state.lastAccounts,
      live,
      forceMinimumSuspicious: true,
    });
  }

  const activeAccounts = (state.lastAccounts || [])
    .filter((account) => account.is_active !== false)
    .map((account) => {
      const accountId = String(account.account_id);
      const stored = state.accountStore.get(accountId) || {};
      return {
        account_id: accountId,
        status: stored.status || account.early_status || account.status || "normal",
        risk_score: round4(Number(stored.risk_score ?? account.risk_score ?? 0)),
        signal_count: Number(account.signal_count || 0),
        reasons: Array.isArray(account.risk_reasons) && account.risk_reasons.length
          ? account.risk_reasons.join(", ")
          : "Learning normal behavior",
      };
    });

  const table = activeAccounts
    .filter((account) => account.status === "early")
    .sort((left, right) => Number(right.risk_score || 0) - Number(left.risk_score || 0))
    .slice(0, 40)
    .map((account) => ({
      account_id: account.account_id,
      risk_score: account.risk_score,
      status: "suspicious",
      signal_count: Math.max(1, Number(account.signal_count || 0)),
      reasons: account.reasons,
    }));

  const activeRiskScores = activeAccounts
    .filter((account) => account.status !== "banned" && account.status !== "fraud")
    .map((account) => Number(account.risk_score || 0))
    .sort((left, right) => left - right);
  const percentileIndex = activeRiskScores.length
    ? Math.min(activeRiskScores.length - 1, Math.max(0, Math.floor(activeRiskScores.length * 0.9)))
    : 0;
  const rawThreshold = activeRiskScores.length ? activeRiskScores[percentileIndex] : LIVE_WARNING_THRESHOLD;
  const previousThreshold = Number(
    state.liveSuspiciousSummary?.threshold ??
      live?.early_warning?.threshold ??
      live?.threshold ??
      LIVE_WARNING_THRESHOLD
  );
  const threshold = Number(
    Math.max(0.4, Math.min(0.75, (previousThreshold * 0.8) + (rawThreshold * 0.2))).toFixed(4)
  );
  const distribution = activeAccounts
    .map((account) => round4(Number(account.risk_score || 0)))
    .sort((left, right) => right - left)
    .slice(0, 40);
  const count = table.length;
  const fallbackMessage = count
    ? `${count} suspicious account(s) are currently above the live adaptive threshold.`
    : "Monitoring live transaction stream.";

  state.liveSuspiciousSummary = {
    count,
    total_active: Number(live?.metrics?.active_accounts ?? activeAccounts.length),
    threshold,
    distribution,
    table,
    message: count
      ? `${count} suspicious account(s) are currently above the live adaptive threshold.`
      : fallbackMessage,
  };
  state.live = {
    ...(state.live || {}),
    ...(live || {}),
    early_warning: {
      ...((state.live || {}).early_warning || {}),
      ...((live || {}).early_warning || {}),
      count,
      threshold,
      distribution,
      table,
      message: state.liveSuspiciousSummary.message,
      total_active: state.liveSuspiciousSummary.total_active,
    },
  };
  state.currentEarlyIds = new Set(table.map((row) => String(row.account_id)));
  state.suspiciousList = [...state.currentEarlyIds].sort();
  return state.liveSuspiciousSummary;
}

function resetAttackContext({ clearReplay = true, resetBanner = false } = {}) {
  resetAttackState();

  if (state.lastAccounts.length) {
    updateLiveNetwork(state.lastAccounts, {
      ...(state.live || {}),
      fraud_accounts: [],
    });
  } else {
    rebuildSuspiciousSummaryFromLiveNodes({
      ...(state.live || {}),
      fraud_accounts: [],
    });
    renderLiveMetrics(state.live || { metrics: {} }, state.dashboard);
    renderEarlyWarning(state.live || { early_warning: {} });
  }

  if (resetBanner) {
    els.attackAlertStrip.textContent = "No simulated attack yet. Live monitoring is active.";
    els.attackAlertStrip.classList.remove("alarm");
    updateText("metric-attack-pattern", "Idle");
  }
}

function renderFeed(container, rows, emptyMessage) {
  if (!rows.length) {
    const emptyMarkup = `<div class="empty-state">${emptyMessage}</div>`;
    if (container.__feedMarkup !== emptyMarkup) {
      container.innerHTML = emptyMarkup;
      container.__feedMarkup = emptyMarkup;
    }
    return;
  }
  const markup = rows
    .map(
      (row) => `
        <div class="feed-row ${row.alert ? "alert" : ""} ${row.tone ? `feed-row--${row.tone}` : ""}">
          <strong>${escapeHtml(row.title)}</strong>
          <span>${escapeHtml(row.meta)}</span>
        </div>
      `
    )
    .join("");
  if (container.__feedMarkup !== markup) {
    container.innerHTML = markup;
    container.__feedMarkup = markup;
  }
}

function getEffectivePhase() {
  if (state.phase && state.phase !== "idle") {
    return state.phase;
  }
  if (state.detectionFinalized || state.attackSequenceStage === "revealed") {
    return PHASES.FRAUD_REVEAL;
  }
  if (
    state.attackSequenceStage &&
    state.attackSequenceStage !== "idle" &&
    state.attackSequenceStage !== "revealed"
  ) {
    return PHASES.ATTACK_FLOW;
  }
  if (state.currentEarlyIds.size) {
    return PHASES.BUILD;
  }
  return PHASES.IDLE;
}

function getAccountRuntimeStatus(accountId) {
  const id = String(accountId || "");
  if (!id) {
    return "normal";
  }
  const stored = state.accountStore.get(id)?.status;
  if (stored) {
    return stored;
  }
  const liveNode = state.liveNodes.get(id)?.status;
  if (liveNode) {
    return liveNode;
  }
  return "normal";
}

function isAttackTransaction(tx, sender, receiver) {
  if (tx?.is_attack === true) {
    return true;
  }
  const edges = state.latestAttackData?.edges || [];
  for (let index = 0; index < edges.length; index += 1) {
    const edge = edges[index] || {};
    const from = String(edge.source ?? edge.from ?? "");
    const to = String(edge.target ?? edge.to ?? "");
    if (from === sender && to === receiver) {
      return true;
    }
  }
  return false;
}

function getTransactionColor(tx, phase = getEffectivePhase()) {
  const sender = String(tx?.sender || tx?.source || "");
  const receiver = String(tx?.receiver || tx?.target || "");
  const senderStatus = getAccountRuntimeStatus(sender);
  const receiverStatus = getAccountRuntimeStatus(receiver);
  const attackTx = isAttackTransaction(tx, sender, receiver);
  const involvesEarly =
    senderStatus === "early" ||
    receiverStatus === "early" ||
    state.currentEarlyIds.has(sender) ||
    state.currentEarlyIds.has(receiver);
  const involvesFraud =
    senderStatus === "fraud" ||
    receiverStatus === "fraud" ||
    state.currentFraudIds.has(sender) ||
    state.currentFraudIds.has(receiver);
  const fraudPhase = phase === PHASES.FRAUD_REVEAL || phase === PHASES.POST_ATTACK;

  if (fraudPhase && attackTx) {
    return {
      tone: "fraud",
      liveTone: involvesEarly || involvesFraud ? "warning" : "normal",
      graphColor: "rgba(255, 93, 125, 0.72)",
      width: 2.1,
      duration: ATTACK_TX_DURATION_MS,
      fraudFeed: true,
      liveAlert: true,
    };
  }

  if (involvesEarly || involvesFraud || attackTx) {
    return {
      tone: "warning",
      liveTone: "warning",
      graphColor: "rgba(255, 190, 92, 0.56)",
      width: 1.55,
      duration: SUSPICIOUS_TX_DURATION_MS,
      fraudFeed: false,
      liveAlert: true,
    };
  }

  return {
    tone: "normal",
    liveTone: "normal",
    graphColor: "rgba(56, 189, 248, 0.52)",
    width: 1.2,
    duration: NORMAL_TX_DURATION_MS,
    fraudFeed: false,
    liveAlert: false,
  };
}

function createBanSelect() {
  state.banSelect = new TomSelect(els.banSelect, {
    plugins: ["remove_button"],
    maxItems: null,
    persist: false,
    create: false,
    sortField: { field: "text", direction: "asc" },
  });
  state.banSelect.on("change", () => {
    const selected = []
      .concat(state.banSelect.getValue())
      .flatMap((value) => String(value || "").split(","))
      .map((value) => value.trim())
      .filter(Boolean);
    setBanSelection(selected);
  });
}

function ensureAudioContext() {
  if (!window.AudioContext && !window.webkitAudioContext) {
    return null;
  }
  if (!state.audioContext) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    state.audioContext = new AudioCtx();
  }
  return state.audioContext;
}

function playSiren(durationMs = ATTACK_SIREN_MS) {
  if (state.sirenMuted || state.sirenActive) {
    return wait(durationMs);
  }
  const ctx = ensureAudioContext();
  if (!ctx) {
    return wait(durationMs);
  }
  if (ctx.state === "suspended") {
    ctx.resume().catch(() => {});
  }

  state.sirenActive = true;
  const duration = durationMs / 1000;
  const oscillator = ctx.createOscillator();
  const gain = ctx.createGain();
  oscillator.type = "sawtooth";
  oscillator.connect(gain);
  gain.connect(ctx.destination);
  gain.gain.setValueAtTime(0.0001, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.08, ctx.currentTime + 0.08);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
  oscillator.frequency.setValueAtTime(640, ctx.currentTime);
  oscillator.frequency.linearRampToValueAtTime(980, ctx.currentTime + 0.35);
  oscillator.frequency.linearRampToValueAtTime(560, ctx.currentTime + 0.8);
  oscillator.frequency.linearRampToValueAtTime(1020, ctx.currentTime + 1.2);
  oscillator.frequency.linearRampToValueAtTime(600, ctx.currentTime + duration);
  oscillator.start();
  oscillator.stop(ctx.currentTime + duration);
  return new Promise((resolve) => {
    oscillator.onended = () => {
      state.sirenActive = false;
      resolve();
    };
  });
}

function flashAttack(durationMs = ATTACK_SIREN_MS) {
  document.body.classList.add("is-attack-flash");
  if (state.attackFlashTimer) {
    clearTimeout(state.attackFlashTimer);
  }
  state.attackFlashTimer = window.setTimeout(() => {
    document.body.classList.remove("is-attack-flash");
    state.attackFlashTimer = null;
  }, durationMs);
}

function getNodeVisualPayload(existing, node = {}) {
  return {
    channel: node.channel ?? existing?.channel ?? "--",
    riskScore:
      node.sus_score ??
      node.riskScore ??
      existing?.riskScore ??
      0,
    reasons: Array.isArray(node.reasons)
      ? node.reasons
      : Array.isArray(existing?.reasons)
        ? existing.reasons
        : [],
    x: Number.isFinite(Number(node.x)) ? Number(node.x) : unscaleGraphCoordinate(existing?.x),
    y: Number.isFinite(Number(node.y)) ? Number(node.y) : unscaleGraphCoordinate(existing?.y),
    layoutPosition: node.layoutPosition ?? existing?.layoutPosition ?? null,
  };
}

function updateNodeStatus(kind, accountId, status, nodeInfo = {}) {
  const dataset = getNodeDataSet(kind);
  const existing = dataset.get(String(accountId));
  if (!existing) {
    return;
  }
  if (
    kind === "live" &&
    existing.status === "fraud" &&
    state.fraudNodeSet.has(String(accountId)) &&
    status !== "banned"
  ) {
    status = "fraud";
  }

  const next = accountStyle(accountId, status, getNodeVisualPayload(existing, nodeInfo));
  if (existing.label) {
    next.label = existing.label;
  }
  dataset.update(next);
}

function promoteLiveNodeToEarly(accountId, nodeInfo = {}) {
  const existing = state.liveNodes.get(String(accountId));
  if (!existing || existing.status === "banned" || existing.status === "fraud") {
    return;
  }
  updateNodeStatus("live", accountId, "early", nodeInfo);
}

function applyFinalAttackState(data) {
  if (!data?.attack_name || !data?.edges?.length) {
    return;
  }
  if (state.finalizedAttackName === data.attack_name && state.detectionFinalized) {
    return;
  }

  const validated = revealAttackCluster(data);
  if (!validated?.nodeIds?.size) {
    syncFraudState();
    els.attackAlertStrip.textContent = `Detection completed for ${data.attack_name}, but no validated fraud cluster was confirmed.`;
    els.attackAlertStrip.classList.remove("alarm");
    clearAttackReplayState({ resetLatest: true, message: "Waiting for attack..." });
    return;
  }
  console.log("Fraud reveal triggered", data.attack_name);

  const snapshot = buildAttackSubgraphSnapshot(validated);
  state.attackTransactions = validated.edges.map((edge) =>
    normalizeTransaction({
      sender: edge.source,
      receiver: edge.target,
      amount: edge.amount,
      channel: edge.channel,
      timestamp: edge.timestamp || new Date().toISOString(),
      isAttack: true,
    })
  );
  state.latestAttackData = snapshot;
  freezeAttackSubgraph(snapshot);
  state.detectionFinalized = true;
  state.finalizedAttackName = validated.attack_name;
  state.attackSequenceStage = "revealed";
  state.subgraphCreated = true;
  enforceFrontendMasterState({
    accounts: state.lastAccounts,
    live: state.live,
    forceMinimumSuspicious: true,
  });
  rebuildSuspiciousSummaryFromLiveNodes(state.live || {});
  syncLiveMetricsFromGraph();
  renderLiveMetrics(state.live || { metrics: {} }, state.dashboard);
  renderEarlyWarning(state.live || { early_warning: {} });
  flashAttack(ATTACK_SIREN_MS);
  playSiren(ATTACK_SIREN_MS).catch(() => {});
  updateText("attack-replay-meta", `Attack Detected: ${validated.attack_name}`);
  setReplayButtonDisabled(!snapshot.edges.length);
  els.attackAlertStrip.textContent = `Attack Detected: ${validated.attack_name}`;
  els.attackAlertStrip.classList.add("alarm");
}

function shouldAnimateLiveTransaction(suspicious, tx) {
  if (tx?.is_attack === true) {
    return false;
  }

  if (state.activeTravelers.length >= MAX_ACTIVE_TRAVELERS - 4) {
    return false;
  }
  return true;
}

function clearPersistentAttackEdges() {
  if (!state.persistentAttackEdgeIds.size) {
    return;
  }
  const removableIds = [...state.persistentAttackEdgeIds].filter((edgeId) => state.liveEdges.get(edgeId));
  if (removableIds.length) {
    state.liveEdges.remove(removableIds);
    removableIds.forEach((edgeId) => removeGraphEdge("live", edgeId));
  }
  state.persistentAttackEdgeIds.clear();
}

async function scrollMainGraphIntoView() {
  els.mainGraphStage?.scrollIntoView({ behavior: "smooth", block: "center" });
  pulseNetworkFrame(els.liveNetworkFrame);
  await wait(540);
}

function clusterCenter(network, nodeIds) {
  if (!network || !nodeIds.length) {
    return null;
  }
  const positions = network.getPositions(nodeIds);
  const points = nodeIds
    .map((nodeId) => positions[String(nodeId)] || positions[nodeId])
    .filter(Boolean);

  if (!points.length) {
    return null;
  }

  const sums = points.reduce(
    (acc, point) => {
      acc.x += Number(point.x || 0);
      acc.y += Number(point.y || 0);
      return acc;
    },
    { x: 0, y: 0 }
  );

  return {
    x: sums.x / points.length,
    y: sums.y / points.length,
  };
}

function recordTransactionFeeds({ source, target, amount, channel, tone = "normal", fraud = false }) {
  const normalizedAmount = Number(amount || 0).toFixed(2);
  pushFeed(state.txFeed, {
    title: `${source} -> ${target}`,
    meta: `${channel || "TXN"} | Amount: ${normalizedAmount}`,
    tone,
  });

  if (fraud) {
    pushFeed(state.suspiciousFeed, {
      title: `${source} -> ${target}`,
      meta: `${channel || "TXN"} | Amount: ${normalizedAmount}`,
      tone: "fraud",
    });
  }
  state.feedDirty = true;
  ensureVisualLoop();
}

function recordFraudTransactions(edges = []) {
  if (!Array.isArray(edges) || !edges.length) {
    return;
  }
  edges.forEach((edge) => {
    recordTransactionFeeds({
      source: String(edge.source || edge.from || ""),
      target: String(edge.target || edge.to || ""),
      amount: edge.amount,
      channel: edge.channel,
      tone: "warning",
      fraud: true,
    });
  });
}

function getQueuedTransactionCount() {
  return state.transactionQueue.length - state.transactionQueueCursor;
}

function compactTransactionQueue() {
  if (state.transactionQueueCursor <= 0) {
    return;
  }
  if (
    state.transactionQueueCursor >= state.transactionQueue.length ||
    state.transactionQueueCursor >= 64
  ) {
    state.transactionQueue = state.transactionQueue.slice(state.transactionQueueCursor);
    state.transactionQueueCursor = 0;
  }
}

function dequeueTransaction() {
  if (state.transactionQueueCursor >= state.transactionQueue.length) {
    return null;
  }
  const tx = state.transactionQueue[state.transactionQueueCursor];
  state.transactionQueueCursor += 1;
  compactTransactionQueue();
  return tx;
}

function queueTransaction(tx) {
  const normalizedTx = normalizeTransaction(tx);
  const txId = buildTransactionSignature(normalizedTx);
  if (state.seenTransactions.has(txId)) {
    return;
  }
  rememberSeenTransaction(normalizedTx);
  rememberTransactionHistory(normalizedTx);
  state.transactionQueue.push(normalizedTx);
  ensureVisualLoop();
}

function queueTransactions(transactions = []) {
  if (!Array.isArray(transactions) || !transactions.length) {
    return;
  }
  if (!DEMO_SIM_MODE && state.txWorkerEnabled && state.txWorker) {
    state.txWorker.postMessage({
      type: "ingest",
      transactions,
      fraudIds: [...state.currentFraudIds],
      earlyIds: [...state.currentEarlyIds],
      attackSequenceStage: state.attackSequenceStage,
      activeAttackName: state.activeAttackName,
      maxSeen: MAX_SEEN_TRANSACTION_SIGNATURES,
    });
    return;
  }
  transactions.forEach(queueTransaction);
}

function noteVisibleTransaction(now = performance.now()) {
  state.visibleTxTimestamps.push(now);
}

function renderVisibleTps(now = performance.now()) {
  const cutoff = now - VISIBLE_TPS_WINDOW_MS;
  while (state.visibleTxTimestamps.length && state.visibleTxTimestamps[0] < cutoff) {
    state.visibleTxTimestamps.shift();
  }
  const nextTps = state.visibleTxTimestamps.length;
  const changed = nextTps !== state.visibleTps;
  if (changed) {
    state.visibleTps = nextTps;
  }
  return changed;
}

function flushFeedRender(now = performance.now(), force = false) {
  if (!state.feedDirty && !force) {
    return;
  }
  if (!force && now - state.lastFeedRenderAt < FEED_RENDER_MIN_INTERVAL_MS) {
    return;
  }
  renderFeed(els.txFeed, state.txFeed, "No transactions yet.");
  renderFeed(els.suspiciousFeed, state.suspiciousFeed, "No fraud transactions yet.");
  state.feedDirty = false;
  state.lastFeedRenderAt = now;
}

function processLiveTransaction(tx) {
  const sender = String(tx.sender || "");
  const receiver = String(tx.receiver || "");
  const shouldSkipAttackTxVisual =
    tx.is_attack === true &&
    state.attackSequenceStage !== "idle" &&
    state.activeAttackName;
  const visual = getTransactionColor(tx);

  recordTransactionFeeds({
    source: sender,
    target: receiver,
    amount: tx.amount,
    channel: tx.channel,
    tone: visual.liveTone,
    fraud: visual.fraudFeed,
  });

  if (shouldSkipAttackTxVisual) {
    return;
  }

  if (!shouldAnimateLiveTransaction(visual.liveTone === "warning", tx)) {
    return;
  }

  animateTemporaryEdge({
    kind: "live",
    from: sender,
    to: receiver,
    color: visual.graphColor,
    width: visual.width,
    title: buildEdgeTitle(sender, receiver, tx.amount, tx.channel),
    duration: visual.duration,
  })
    .then((didRender) => {
      if (didRender) {
        noteVisibleTransaction();
        ensureVisualLoop();
      }
    })
    .catch(() => {});
}

function drainTransactionQueueFrame() {
  let processed = 0;
  while (processed < MAX_TX_PER_FRAME) {
    const tx = dequeueTransaction();
    if (!tx) {
      break;
    }
    processLiveTransaction(tx);
    processed += 1;
  }
}

function runVisualFrame(now) {
  state.visualFrame = null;
  if (state.lastVisualFrameAt && now - state.lastVisualFrameAt < FRAME_INTERVAL_MS) {
    ensureVisualLoop();
    return;
  }
  state.lastVisualFrameAt = now;
  if (PERF_DEBUG) {
    console.time("visual-frame");
  }
  drainTransactionQueueFrame();
  flushFeedRender(now);
  const tpsChanged = renderVisibleTps(now);
  pruneLiveEdges();
  if (tpsChanged && state.live && shouldRenderUiNow()) {
    renderLiveMetrics(state.live, state.dashboard);
  }
  if (PERF_DEBUG) {
    console.timeEnd("visual-frame");
  }

  if (getQueuedTransactionCount() > 0 || state.feedDirty) {
    ensureVisualLoop();
  }
}

function ensureVisualLoop() {
  if (!state.visualFrame) {
    state.visualFrame = requestAnimationFrame(runVisualFrame);
  }
}

function buildEdgeTitle(source, target, amount, channel) {
  return `${source} -> ${target}<br>${Number(amount || 0).toFixed(2)} ${channel || ""}`.trim();
}

function animateTemporaryEdge({
  kind = "live",
  from,
  to,
  color,
  width,
  title,
  label = "",
  duration,
}) {
  const adapter = kind === "attack" ? state.attackGraph3D : state.liveGraph3D;
  if (!adapter || !from || !to || String(from) === String(to)) {
    return Promise.resolve(false);
  }
  const edgeId = `${kind}-tx-${String(from)}-${String(to)}-${Date.now()}-${state.localEdgeIndex += 1}`;
  const colorToken = String(color || "").toLowerCase();
  const isWarningEdge = colorToken.includes("255, 190, 92") || colorToken.includes("ffbe5c");
  const isFraudEdge = colorToken.includes("255, 93, 125") || colorToken.includes("ff5d7d");
  const lineColor = isFraudEdge
    ? "rgba(255, 93, 125, 0.86)"
    : isWarningEdge
      ? "rgba(255, 190, 92, 0.86)"
      : "rgba(56, 189, 248, 0.74)";
  const lineColorHex = isFraudEdge ? 0xff5d7d : isWarningEdge ? 0xffbe5c : 0x38bdf8;
  const txDuration = Math.max(320, Number(duration || 820));
  if (typeof adapter.animateTransaction === "function") {
    return adapter.animateTransaction(
      String(from),
      String(to),
      0xffffff,
      txDuration,
      lineColorHex,
      isFraudEdge ? 0.34 : isWarningEdge ? 0.26 : 0.2
    );
  }

  const edge = {
    id: edgeId,
    from: String(from),
    to: String(to),
    title,
    label,
    color: { color: lineColor },
    width: Math.max(1.4, Number(width || 1.6)),
    smooth: false,
    arrows: NO_EDGE_ARROWS,
    createdAt: Date.now(),
    life: txDuration + 180,
    temporary: true,
  };
  const dataset = getEdgeDataSet(kind);
  dataset.update(edge);
  upsertGraphEdge(kind, edge);
  queueTraveler({
    kind,
    from: String(from),
    to: String(to),
    edgeId,
    duration: txDuration,
    radius: isFraudEdge ? 3 : isWarningEdge ? 2.9 : 2.55,
    trailColor: isFraudEdge
      ? "rgba(255, 93, 125, 0.34)"
      : isWarningEdge
        ? "rgba(255, 190, 92, 0.3)"
        : "rgba(56, 189, 248, 0.22)",
    glowColor: isFraudEdge
      ? "rgba(255, 144, 165, 0.3)"
      : isWarningEdge
        ? "rgba(255, 214, 120, 0.28)"
        : "rgba(103, 226, 255, 0.2)",
    trailWidth: isFraudEdge ? 1.8 : isWarningEdge ? 1.7 : 1.35,
    onComplete: () => removeEdgeIfPresent(kind, edgeId),
    onAbort: () => removeEdgeIfPresent(kind, edgeId),
  });
  return Promise.resolve(true);
}

function revealAttackCluster(data) {
  const validated = getValidatedAttackGraphData(data);
  if (!validated.nodeIds.size) {
    syncFraudState();
    return validated;
  }

  const nodeMap = new Map(validated.nodes.map((node) => [String(node.id), node]));
  const edgeUpdates = [];
  const nodeUpdates = [];

  validated.edges.forEach((edge, index) => {
    const from = String(edge.source);
    const to = String(edge.target);
    if (!state.liveNodes.get(from) || !state.liveNodes.get(to)) {
      return;
    }

    const edgeId = `attack-persist-${validated.attack_name}-${index}`;
    edgeUpdates.push({
      id: edgeId,
      from,
      to,
      title: buildEdgeTitle(from, to, edge.amount, edge.channel),
      color: { color: "rgba(255, 93, 125, 0.68)" },
      width: 2.35,
      smooth: false,
      createdAt: Date.now(),
      life: Number.POSITIVE_INFINITY,
      persistent: true,
      arrows: NO_EDGE_ARROWS,
    });
    state.persistentAttackEdgeIds.add(edgeId);
  });

  validated.nodeIds.forEach((accountId) => {
    const existing = state.liveNodes.get(String(accountId));
    if (!existing || existing.status === "banned") {
      return;
    }
    const next = accountStyle(accountId, "fraud", getNodeVisualPayload(existing, nodeMap.get(accountId)));
    if (existing.label) {
      next.label = existing.label;
    }
    nodeUpdates.push(next);
  });

  if (edgeUpdates.length) {
    state.liveEdges.update(edgeUpdates);
    edgeUpdates.forEach((edge) => upsertGraphEdge("live", edge));
  }
  if (nodeUpdates.length) {
    state.liveNodes.update(nodeUpdates);
  }

  syncFraudState([...validated.nodeIds], [...state.persistentAttackEdgeIds]);
  return validated;
}

async function runAttackSequence(data) {
  if (!data?.attack_name || !data.edges?.length) {
    return;
  }
  console.log("Transactions running", data.attack_name);

  clearAttackReplayState({ resetLatest: false, message: "Waiting for attack confirmation..." });

  const token = state.attackSequenceToken;
  state.activeAttackName = data.attack_name;
  state.attackSequenceStage = "animating";
  state.pendingAttackNodes = new Set((data.nodes || []).map((node) => String(node.id)));
  state.latestAttackData = data;
  state.lastReplayAttackName = null;
  state.subgraphCreated = false;
  updateText("attack-replay-meta", "Waiting for attack confirmation...");
  setReplayButtonDisabled(true);

  data.edges.forEach((edge) => {
    rememberSeenTransaction({
      source: edge.source,
      target: edge.target,
      amount: edge.amount,
      timestamp: edge.timestamp,
    });
  });

  els.attackAlertStrip.textContent = `Attack injected: ${data.attack_name}. Streaming suspicious transactions into the live graph...`;
  els.attackAlertStrip.classList.add("alarm");

  await scrollMainGraphIntoView();
  if (token !== state.attackSequenceToken) {
    return;
  }

  const nodeMap = new Map((data.nodes || []).map((node) => [String(node.id), node]));
  for (const edge of data.edges) {
    if (token !== state.attackSequenceToken) {
      return;
    }

    const from = String(edge.source);
    const to = String(edge.target);
    recordTransactionFeeds({
      source: from,
      target: to,
      amount: edge.amount,
      channel: edge.channel,
      tone: "warning",
      fraud: false,
    });
    promoteLiveNodeToEarly(from, nodeMap.get(from));
    promoteLiveNodeToEarly(to, nodeMap.get(to));
    await animateTemporaryEdge({
      kind: "live",
      from,
      to,
      color: "rgba(255, 190, 92, 0.42)",
      width: 1.45,
      title: buildEdgeTitle(from, to, edge.amount, edge.channel),
      duration: ATTACK_TX_DURATION_MS,
    });
    await wait(1000 / (3 + Math.random() * 2));
  }

  if (token !== state.attackSequenceToken) {
    return;
  }

  state.attackSequenceStage = "siren";
  els.attackAlertStrip.textContent = `Attack pattern isolated. Finalizing the full sequence for ${data.attack_name}...`;
  pulseNetworkFrame(els.liveNetworkFrame);
  await wait(220);

  if (token !== state.attackSequenceToken) {
    return;
  }

  state.attackSequenceStage = "detecting";
  els.attackAlertStrip.textContent = `Attack sequence complete: ${data.attack_name}. Starting final detection now.`;
  await startDetectionForCurrentAttack();
  if (token !== state.attackSequenceToken) {
    return;
  }
  applyFinalAttackState(data);
}

function initNetworks() {
  state.liveGraph3D = new ThreeGraphAdapter(els.liveNetworkShell);
  state.attackGraph3D = new ThreeGraphAdapter(els.attackNetworkShell);
  state.liveNetwork = state.liveGraph3D;
  state.attackNetwork = state.attackGraph3D;

  state.liveNetwork.on("click", async (params) => {
    if (!params.nodes.length || !state.dashboard?.available) return;
    const accountId = params.nodes[0];
    const investigationAccounts = state.dashboard.investigation_accounts || [];
    if (investigationAccounts.includes(accountId)) {
      els.investigationSelect.value = accountId;
      await loadInvestigation(accountId);
      document.getElementById("post-detection").scrollIntoView({ behavior: "smooth" });
    }
  });

  state.liveNetwork.on("zoom", scheduleNetworkZoomScaling);
  state.liveNetwork.on("dragEnd", () => {
    pulseNetworkFrame(els.liveNetworkFrame);
  });

  state.attackNetwork.on("click", async (params) => {
    if (!params.nodes.length || !state.dashboard?.available) return;
    const accountId = params.nodes[0];
    const investigationAccounts = state.dashboard.investigation_accounts || [];
    if (investigationAccounts.includes(accountId)) {
      els.investigationSelect.value = accountId;
      await loadInvestigation(accountId);
    }
  });

  state.attackNetwork.on("zoom", scheduleNetworkZoomScaling);
  state.attackNetwork.on("dragEnd", () => {
    pulseNetworkFrame(els.attackNetworkFrame);
  });
}

function renderLiveMetrics(live, dashboard) {
  const metrics = live.metrics || {};
  const counts = getStatusCounts();
  const suspiciousCount = counts.suspicious;
  const visibleTps = Number(state.visibleTps ?? 0);
  const backendTps = Number(metrics.tps ?? 0);
  const mergedTps = Math.max(visibleTps, backendTps);
  const activeAccounts = Number.isFinite(Number(counts.active))
    ? counts.active
    : (metrics.active_accounts ?? "--");
  const fraudCount = Number.isFinite(Number(counts.fraud))
    ? counts.fraud
    : (metrics.fraud_count ?? 0);
  const bannedCount = Number.isFinite(Number(counts.banned))
    ? counts.banned
    : (metrics.banned_count ?? 0);
  updateText("metric-active-accounts", activeAccounts);
  updateText("metric-tps", safeNumber(mergedTps, 2));
  updateText("metric-suspicious", suspiciousCount);
  updateText("metric-suspicious-control", suspiciousCount);
  updateText("metric-total-transactions", metrics.tx_count ?? 0);
  updateText("metric-fraud", fraudCount);
  updateText("metric-banned", bannedCount);
}

function syncLiveMetricsFromGraph() {
  if (!state.live || !state.live.metrics) {
    return;
  }
  syncFrontendDerivedLists();
  const nodes = [...state.accountStore.values()];
  let suspicious = 0;
  let fraud = 0;
  let banned = 0;
  nodes.forEach((node) => {
    if (node.status === "early") suspicious += 1;
    else if (node.status === "fraud") fraud += 1;
    else if (node.status === "banned") banned += 1;
  });
  state.live.metrics.suspicious_count = suspicious;
  state.live.metrics.fraud_count = fraud;
  state.live.metrics.banned_count = banned;
  state.live.metrics.total_accounts = nodes.length;
  state.live.metrics.active_accounts = Math.max(0, nodes.length - banned);
}

function renderEarlyWarning(live) {
  const early = state.liveSuspiciousSummary || live.early_warning || {};
  updateText("early-warning-count", `${early.count || 0} suspicious`);
  updateText("early-warning-metric", early.count || 0);
  updateText("live-threshold", safeNumber(early.threshold, 3));
  updateText("early-warning-message", early.message || "Waiting for account activity.");
  renderTable(
    els.earlyWarningTable,
    early.table || [],
    [
      { key: "account_id", label: "Account ID" },
      { key: "risk_score", label: "Risk Score" },
      { key: "status", label: "Status" },
      { key: "signal_count", label: "Signals" },
      { key: "reasons", label: "Reasons" },
    ],
    "No suspicious accounts at the moment."
  );

  const scores = early.distribution || [];
  updateRiskDistributionChart(
    document.getElementById("suspicion-chart"),
    scores,
    Number(early.threshold || 0)
  );
}

function shouldRenderUiNow(force = false) {
  const now = performance.now();
  if (force || !state.lastUiRenderAt || now - state.lastUiRenderAt >= UI_UPDATE_MIN_INTERVAL_MS) {
    state.lastUiRenderAt = now;
    return true;
  }
  return false;
}

function updateLiveNetwork(accounts, live) {
  state.lastAccounts = Array.isArray(accounts) ? accounts : [];
  state.live = {
    ...(state.live || {}),
    ...(live || {}),
  };

  const seenAccountIds = new Set();
  const bannedIdsToCleanup = new Set();

  (accounts || []).forEach((account) => {
    const accountId = String(account?.account_id || "");
    if (!accountId) {
      return;
    }
    seenAccountIds.add(accountId);
    const previousStatus = state.accountStore.get(accountId)?.status || "normal";
    upsertAccountStore(accountId, {
      channel: account.channel,
      x: typeof account.x === "number" ? account.x : Number(account.x),
      y: typeof account.y === "number" ? account.y : Number(account.y),
      risk_score: Number(account.risk_score || state.accountStore.get(accountId)?.risk_score || 0),
      risk_reasons: Array.isArray(account.risk_reasons) ? account.risk_reasons : [],
      signal_count: Number(account.signal_count || 0),
      is_active: account.is_active !== false,
      backend_status: account.early_status || account.status || "normal",
      selected_for_ban: state.selectedForBan.has(accountId),
    });
    if (previousStatus !== "banned" && account.is_active === false) {
      bannedIdsToCleanup.add(accountId);
    }
  });

  state.accountStore.forEach((_, accountId) => {
    const normalizedId = String(accountId || "");
    if (normalizedId && !seenAccountIds.has(normalizedId)) {
      state.accountStore.delete(normalizedId);
      state.selectedForBan.delete(normalizedId);
      if (state.liveNodes.get(normalizedId)) {
        state.liveNodes.remove(normalizedId);
      }
    }
  });

  enforceFrontendMasterState({
    accounts: state.lastAccounts,
    live: state.live,
    forceMinimumSuspicious: true,
  });

  (accounts || []).forEach((account) => {
    const accountId = String(account.account_id);
    const existing = state.liveNodes.get(accountId);
    const stored = state.accountStore.get(accountId) || {};
    const status = stored.status || "normal";
    if (status === "banned" && existing?.status !== "banned") {
      bannedIdsToCleanup.add(accountId);
    }

    const riskScore = Number(stored.risk_score ?? account.risk_score ?? 0);
    const reasons = Array.isArray(stored.risk_reasons) && stored.risk_reasons.length
      ? stored.risk_reasons
      : Array.isArray(account.risk_reasons)
        ? account.risk_reasons
        : [];

    const node = accountStyle(accountId, status, {
      channel: stored.channel ?? account.channel,
      riskScore,
      reasons,
      x: Number.isFinite(Number(stored.x)) ? Number(stored.x) : (typeof account.x === "number" ? account.x : Number(account.x)),
      y: Number.isFinite(Number(stored.y)) ? Number(stored.y) : (typeof account.y === "number" ? account.y : Number(account.y)),
      layoutPosition: stored.layoutPosition ?? account.layoutPosition ?? null,
    });

    if (
      existing &&
      existing.status === node.status &&
      Math.abs(Number(existing.riskScore || 0) - Number(node.riskScore || 0)) < 0.015 &&
      JSON.stringify(existing.reasons || []) === JSON.stringify(node.reasons || [])
    ) {
      return;
    }

    if (existing) {
      state.liveNodes.update(node);
    } else {
      state.liveNodes.add(node);
    }
  });

  state.liveNodes.forEach((node) => {
    const accountId = String(node.id);
    if (!seenAccountIds.has(accountId)) {
      state.liveNodes.remove(accountId);
      state.accountStore.delete(accountId);
      state.selectedForBan.delete(accountId);
    }
  });

  if (bannedIdsToCleanup.size) {
    removeConnectedEdges([...bannedIdsToCleanup]);
  }

  syncFrontendDerivedLists();
  state.liveGraph3D?.syncFromDataSets(state.liveNodes, state.liveEdges);
  rebuildSuspiciousSummaryFromLiveNodes(state.live);
  syncLiveMetricsFromGraph();
  validateSystemState();
  if (shouldRenderUiNow()) {
    renderLiveMetrics(state.live, state.dashboard);
    renderEarlyWarning(state.live);
  }
  if (!state.liveGraphFitted && state.liveNodes.length) {
    state.liveNetwork.fit({ animation: { duration: 500, easingFunction: "easeInOutQuad" } });
    state.liveGraphFitted = true;
  }
  if (state.currentInvestigationAccount) {
    applyInvestigationHighlight(state.currentInvestigationAccount);
  }
  scheduleNetworkZoomScaling();
}

function pruneLiveEdges() {
  const now = Date.now();
  const stale = state.liveEdges
    .get()
    .filter((edge) => !edge.persistent && Number.isFinite(edge.life) && now - edge.createdAt > edge.life)
    .map((edge) => edge.id);
  if (stale.length) {
    state.liveEdges.remove(stale);
    stale.forEach((edgeId) => removeGraphEdge("live", edgeId));
  }
}

function addLiveTransaction(tx) {
  queueTransaction(tx);
}

function updateAttackNetwork(data, options = {}) {
  if (!shouldAcceptAttackPayload(data)) {
    return;
  }
  const incomingName = data?.attack_name || null;
  if (
    incomingName &&
    state.activeAttackName === incomingName &&
    !state.detectionFinalized &&
    state.attackSequenceStage !== "revealed"
  ) {
    updateText("attack-replay-meta", "Waiting for attack confirmation...");
    setReplayButtonDisabled(true);
    return;
  }
  const snapshot = data?.nodes?.length ? buildAttackSubgraphSnapshot(data) : null;
  if (!snapshot || !snapshot.nodes.length) {
    if (options.forceClear || state.attackSequenceStage === "idle") {
      clearAttackReplayState({ resetLatest: true, message: "Waiting for attack..." });
    }
    return;
  }

  state.latestAttackData = snapshot;
  freezeAttackSubgraph(snapshot);
  updateText("attack-replay-meta", `Attack Detected: ${snapshot.attack_name}`);
  setReplayButtonDisabled(!snapshot.edges.length);
}

function animateAttackInLiveGraph(data) {
  runAttackSequence(data).catch((error) => {
    showToast(`Attack animation failed: ${error.message}`, "error");
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
  });
}

function renderDashboard(dashboard) {
  state.dashboard = dashboard;
  if (
    dashboard?.available &&
    !dashboard?.is_detecting &&
    state.latestAttackData?.attack_name &&
    state.finalizedAttackName !== state.latestAttackData.attack_name
  ) {
    applyFinalAttackState(state.latestAttackData);
  }
  const shouldShowPostDetection = Boolean(dashboard?.available || dashboard?.is_detecting);
  els.postDetection.classList.toggle("hidden", !shouldShowPostDetection);
  setPostDetectionLoading(Boolean(dashboard?.is_detecting));
  if (!shouldShowPostDetection) {
    state.currentInvestigationAccount = null;
    return;
  }
  if (!dashboard?.available) {
    resetInvestigationPanel("Detection is still running.");
    return;
  }

  const fraudAccounts = getActiveFraudAccounts(dashboard);
  els.banChip.textContent = fraudAccounts.length
    ? `${fraudAccounts.length} detected`
    : "No fraud accounts";
  els.driftChip.textContent = dashboard.drift?.status || "idle";
  els.gnnChip.textContent = dashboard.gnn_available ? "GNN Active" : "GNN Inactive";
  if (dashboard.is_detecting && state.attackSequenceStage === "idle") {
    els.attackAlertStrip.textContent = `Attack injected: ${dashboard.detection_job?.attack_name || "Attack"} . Graph updated. ML detection is still processing...`;
    els.attackAlertStrip.classList.add("alarm");
  }
  const crossCheck = shouldRunCrossCheck()
    ? computeCrossCheckFromState(fraudAccounts)
    : buildEmptyCrossCheck();
  recordDashboardHistory(dashboard, crossCheck, fraudAccounts);

  updateText("rule-high", dashboard.rule_based.high_count || 0);
  updateText("rule-medium", dashboard.rule_based.medium_count || 0);
  updateText("rule-scored", dashboard.rule_based.scored_count || 0);
  updateText("ml-flagged", fraudAccounts.length);
  updateText("ml-precision", safeNumber(dashboard.ml_detection.precision, 3));
  updateText("ml-recall", safeNumber(dashboard.ml_detection.recall, 3));
  updateText("adaptive-threshold", safeNumber(dashboard.ml_detection.threshold, 3));
  updateText("adaptive-precision", safeNumber(dashboard.ml_detection.precision, 3));
  updateText("adaptive-recall", safeNumber(dashboard.ml_detection.recall, 3));
  updateText("pattern-similarity", `${safeNumber((dashboard.pattern_memory.similarity || 0) * 100, 2)}%`);
  updateText("pattern-stored", dashboard.pattern_memory.patterns_stored || 0);
  updateText("summary-injected", dashboard.summary.injected || 0);
  updateText("summary-detected", fraudAccounts.length);
  updateText(
    "summary-missed",
    Math.max(0, Number(dashboard.summary.injected || 0) - fraudAccounts.length)
  );
  updateText("cross-early", crossCheck.early_warned || 0);
  updateText("cross-matched", crossCheck.matched || 0);
  updateText("cross-sleeper", crossCheck.sleeper || 0);
  updateText("detection-pattern", `Detected Pattern: ${dashboard.attack_name || "Unknown"}`);
  updateText("pattern-message", dashboard.pattern_memory.message || "");
  updateText("metric-attack-pattern", dashboard.attack_name || "Idle");
  if (!dashboard.is_detecting && state.attackSequenceStage === "idle") {
    els.attackAlertStrip.textContent = dashboard.attack_name
      ? `Attack injected: ${dashboard.attack_name}. Detection complete and results are live below.`
      : "No simulated attack yet. Live monitoring is active.";
    els.attackAlertStrip.classList.toggle("alarm", Boolean(dashboard.attack_name));
  }

  renderTable(
    els.driftTable,
    dashboard.drift.table || [],
    [
      { key: "account_id", label: "Account ID" },
      { key: "drift_score", label: "Drift Score" },
      { key: "top_changes", label: "Top Changes" },
    ],
    dashboard.drift.message || "No drift data."
  );
  updateText("drift-message", dashboard.drift.message || "");

  renderTable(
    els.ruleTable,
    dashboard.rule_based.table || [],
    [
      { key: "account_id", label: "Account ID" },
      { key: "risk_score", label: "Risk Score" },
      { key: "verdict", label: "Verdict" },
      { key: "reasons_str", label: "Reasons" },
    ],
    "Rule-based scoring will appear after a detection run."
  );

  renderTable(
    els.mlTable,
    dashboard.ml_detection.table || [],
    [
      { key: "account_id", label: "Account ID" },
      { key: "ml_score", label: "ML Score" },
      { key: "rule_score_norm", label: "Rule Score" },
      { key: "final_score", label: "Final Score" },
      { key: "predicted_label", label: "Label" },
      { key: "gnn_score", label: "GNN Score" },
      { key: "is_fraud", label: "GT Fraud" },
    ],
    "ML detection results will appear after a simulation."
  );

  const matched = crossCheck.matched_accounts || [];
  const sleepers = crossCheck.sleeper_accounts || [];
  const falsePositives = crossCheck.false_positive_accounts || [];
  renderStructuredGroups(els.crossCheckList, [
    { label: "Matched Accounts", items: matched, tone: "success" },
    { label: "Sleeper Accounts", items: sleepers, tone: "warning" },
    { label: "False Positives", items: falsePositives, tone: "danger" },
  ]);

  const historyLabels = state.dashboardHistory.labels.length
    ? state.dashboardHistory.labels
    : (dashboard.history?.threshold_history || []).map((_, index) => `Run ${index + 1}`);
  const thresholdHistory = state.dashboardHistory.thresholds.length
    ? state.dashboardHistory.thresholds
    : (dashboard.history?.threshold_history || []);
  const recallHistory = state.dashboardHistory.recalls.length
    ? state.dashboardHistory.recalls
    : (dashboard.history?.fraud_history || []);
  updateLineChart(
    "thresholdHistory",
    document.getElementById("threshold-chart"),
    historyLabels,
    thresholdHistory,
    "#38bdf8",
    "Adaptive Threshold",
    {
      title: "Adaptive Threshold Over Time",
      xTitle: "Run Number",
      yTitle: "Threshold Value",
    }
  );
  updateLineChart(
    "fraudHistory",
    document.getElementById("fraud-history-chart"),
    historyLabels,
    recallHistory,
    "#ff5d7d",
    "Model Recall",
    {
      title: "Model Performance (Recall)",
      xTitle: "Run Number",
      yTitle: "Recall Score",
    }
  );
  const roleTotals = state.dashboardHistory.labels.length
    ? state.dashboardHistory.roleTotals
    : (dashboard.history?.role_totals || {});
  updateBarChart(
    "roleHistory",
    document.getElementById("role-history-chart"),
    Object.keys(roleTotals),
    Object.values(roleTotals),
    ["#ff5d7d", "#f97316", "#ffbe5c", "#38bdf8", "#818cf8", "#94a3b8"],
    {
      label: "Role Distribution",
      title: "Fraud Role Distribution",
      xTitle: "Role Type",
      yTitle: "Number of Accounts",
    }
  );

  updateBanSelectOptions(dashboard);
  renderTagList(
    els.bannedAccountsList,
    dashboard.banned_accounts || [],
    "No banned accounts yet.",
    "danger"
  );

  const investigationAccounts = (dashboard.investigation_accounts || []).filter((accountId) =>
    fraudAccounts.includes(String(accountId))
  );
  const resolvedAccounts = investigationAccounts.length ? investigationAccounts : fraudAccounts;
  els.investigationSelect.innerHTML = resolvedAccounts.length
    ? resolvedAccounts
        .map((accountId) => `<option value="${escapeHtml(accountId)}">${escapeHtml(accountId)}</option>`)
        .join("")
    : '<option value="">No fraud accounts detected</option>';

  if (resolvedAccounts.length) {
    const selected = dashboard.selected_account && resolvedAccounts.includes(dashboard.selected_account)
      ? dashboard.selected_account
      : resolvedAccounts[0];
    els.investigationSelect.value = selected;
    if (state.currentInvestigationAccount !== selected) {
      loadInvestigation(selected);
    }
  } else {
    resetInvestigationPanel("No fraud accounts detected.");
  }
  scheduleUiSync();
}

async function loadInvestigation(accountId) {
  if (!accountId) return;
  const payload = buildInvestigationPayload(accountId);
  state.investigation = payload;
  state.currentInvestigationAccount = payload.account_id;

  updateText("investigation-account", payload.account_id);
  updateText("investigation-score", `${safeNumber(payload.fraud_score, 2)}%`);
  updateText("investigation-confidence", payload.confidence);
  updateText("investigation-ml", safeNumber(payload.ml_score, 4));
  updateText("investigation-rule", safeNumber(payload.rule_score_norm, 4));
  updateText("investigation-gnn", payload.gnn_score === null ? "--" : safeNumber(payload.gnn_score, 4));
  updateText("investigation-role", payload.role || "Unclassified");

  els.investigationAlert.textContent =
    payload.severity === "high"
      ? "High confidence fraud account."
      : payload.severity === "medium"
        ? "Medium risk account with strong fraud indicators."
        : "Lower confidence fraud alert.";
  els.investigationAlert.className = `investigation-alert ${payload.severity}`;

  updateBarChart(
    "roleChart",
    document.getElementById("role-chart"),
    payload.role_counts.labels || [],
    payload.role_counts.values || [],
    (payload.role_counts.labels || []).map((label) => getRoleColor(label)),
    {
      label: "Role Strength",
      title: "Fraud Role Classification",
      xTitle: "Role Type",
      yTitle: "Strength (%)",
    }
  );

  updateBarChart(
    "shapChart",
    document.getElementById("shap-chart"),
    (payload.shap.categories || []).map((item) => item.category),
    (payload.shap.categories || []).map((item) => item.contribution),
    ["#ff5d7d", "#f97316", "#ffbe5c", "#38bdf8", "#818cf8"],
    {
      label: "Contribution",
      indexAxis: "y",
      title: "SHAP Risk Breakdown",
      xTitle: "Contribution (%)",
      yTitle: "Risk Category",
    }
  );

  renderTable(
    els.shapTable,
    payload.shap.categories || [],
    [
      { key: "category", label: "Category" },
      { key: "contribution", label: "Contribution (%)" },
      { key: "details", label: "Signal" },
    ],
    payload.shap.available ? "No SHAP categories found." : "SHAP explainer unavailable."
  );

  els.shapExplanations.innerHTML = [
    payload.shap.summary || "No explanation available.",
    ...(payload.shap.explanations || []),
  ]
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  applyInvestigationHighlight(payload.account_id);
  scheduleUiSync();
}

async function pollLiveState() {
  if (DEMO_SIM_MODE) {
    return;
  }
  const live = await apiFetch("/ui/live_state");
  state.live = live;
  setApiStatus(true);
  if (state.lastAccounts.length) {
    updateLiveNetwork(state.lastAccounts, live);
  } else {
    rebuildSuspiciousSummaryFromLiveNodes(live);
    renderLiveMetrics(live, state.dashboard);
    renderEarlyWarning(live);
  }
  await handleDetectionMeta({
    available: Boolean(live.detection_available),
    is_detecting: live.detection_job?.status === "running",
    detection_job: live.detection_job || {},
  });
  if (shouldRenderUiNow(true)) {
    renderLiveMetrics(live, state.dashboard);
  }
}

async function pollAccounts() {
  if (DEMO_SIM_MODE) {
    return;
  }
  const accounts = await apiFetch("/accounts");
  updateLiveNetwork(accounts, state.live || { banned_accounts: [], fraud_accounts: [], early_warning: { table: [] } });
}

async function pollTransactions() {
  if (DEMO_SIM_MODE) {
    return;
  }
  const transactions = await apiFetch("/transactions");
  queueTransactions(transactions);
  pruneLiveEdges();
}

async function pollLatestAttack() {
  if (DEMO_SIM_MODE) {
    return;
  }
  const attackData = await apiFetch("/latest_attack");
  updateAttackNetwork(attackData);
}

async function refreshDashboard(expectedJobId = null) {
  if (DEMO_SIM_MODE) {
    return;
  }
  if (state.dashboardRefreshInFlight) {
    return;
  }

  state.dashboardRefreshInFlight = true;
  try {
    const dashboard = await apiFetch("/ui/dashboard_state");
    renderDashboard(dashboard);
    renderLiveMetrics(state.live || { metrics: {}, threshold: 0 }, dashboard);
    if (expectedJobId !== null) {
      state.lastDashboardRefreshJobId = expectedJobId;
    }
  } finally {
    state.dashboardRefreshInFlight = false;
  }
}

function hydrateBootstrapState(payload, options = {}) {
  const { armAttack = false } = options;
  stopDemoRuntime();
  state.live = payload.live;
  stopAttackAnimation();
  state.txFeed = [];
  state.suspiciousFeed = [];
  state.transactionQueue = [];
  state.transactionQueueCursor = 0;
  state.seenTransactions.clear();
  state.seenTransactionOrder = [];
  state.chartRenderHashes = {};
  state.tableRenderCache = new WeakMap();
  state.liveEdges.clear();
  state.liveNodes.clear();
  state.attackEdges.clear();
  state.attackNodes.clear();
  state.accountStore.clear();
  syncFraudState();
  state.currentFraudIds = new Set();
  state.currentEarlyIds = new Set();
  state.confirmedAttackNodes = new Set();
  state.detectionFinalized = false;
  state.finalizedAttackName = null;
  state.currentInvestigationAccount = null;
  state.lastSirenAttackName = null;
  state.lastReplayAttackName = null;
  state.attackGraphFittedFor = null;
  state.liveGraphFitted = false;
  state.lastDashboardRefreshJobId = null;
  state.lastDashboardErrorJobId = null;
  state.activeTravelers = [];
  state.attackSequenceStage = "idle";
  state.pendingAttackNodes = new Set();
  state.activeAttackName = null;
  state.persistentAttackEdgeIds = new Set();
  state.lastAccounts = [];
  state.liveSuspiciousSummary = null;
  state.feedDirty = false;
  state.lastFeedRenderAt = 0;
  state.visibleTxTimestamps = [];
  state.visibleTps = 0;
  state.lastVisualFrameAt = 0;
  state.phase = PHASES.IDLE;
  state.preAttackSnapshot = [];
  state.preAttackSuspiciousIds = [];
  state.accounts = {};
  state.suspiciousList = [];
  state.fraudList = [];
  state.bannedList = [];
  state.transactions = [];
  state.attackTransactions = [];
  state.dashboardHistory = {
    labels: [],
    thresholds: [],
    recalls: [],
    roleTotals: {
      "Ring Coordinator": 0,
      "Collector Mule": 0,
      "Distributor Mule": 0,
    },
  };
  state.lastHistorySignature = null;
  state.investigationHighlightId = null;
  if (state.txWorkerEnabled && state.txWorker) {
    state.txWorker.postMessage({ type: "reset" });
  }
  if (state.visualFrame) {
    cancelAnimationFrame(state.visualFrame);
    state.visualFrame = null;
  }
  clearAllTravelerOverlays();

  renderLiveMetrics(payload.live, payload.dashboard);
  renderEarlyWarning(payload.live);
  renderDashboard(payload.dashboard);
  renderFeed(els.txFeed, [], "No transactions yet.");
  renderFeed(els.suspiciousFeed, [], "No fraud transactions yet.");

  if (payload.accounts) {
    updateLiveNetwork(payload.accounts, payload.live || {
      banned_accounts: [],
      fraud_accounts: [],
      early_warning: { table: [] },
    });
  }
  markTransactionsSeen(payload.transactions || []);
  updateAttackNetwork(payload.latest_attack || { attack_name: null, nodes: [], edges: [] }, { forceClear: true });
  if (DEMO_SIM_MODE) {
    startDemoRuntime(Boolean(armAttack));
  }
}

function stopDetectionPolling() {
  if (state.detectionPollTimer) {
    clearInterval(state.detectionPollTimer);
    state.detectionPollTimer = null;
  }
}

function startDetectionPolling() {
  stopDetectionPolling();
  state.detectionPollTimer = setInterval(async () => {
    try {
      const payload = await apiFetch("/ui/detection_status");
      renderDashboard(payload.dashboard);
      if (payload.status === "complete") {
        stopDetectionPolling();
        state.simulationInFlight = false;
        setSimulationButtonsDisabled(false);
        await pollLiveState();
        await pollAccounts();
        showToast("ML detection complete.", "success");
      } else if (payload.status === "error") {
        stopDetectionPolling();
        state.simulationInFlight = false;
        setSimulationButtonsDisabled(false);
        showToast(`Detection failed: ${payload.job?.error || "Unknown error"}`, "error");
      }
    } catch (error) {
      // Detection polling can fail transiently while the main API is still healthy.
    }
  }, DETECTION_STATUS_MS);
}

async function runSimulation() {
  if (state.simulationInFlight) {
    return;
  }
  if (DEMO_SIM_MODE) {
    const scenario = state.demoScenario;
    if (!scenario || !Array.isArray(scenario.suspiciousIds) || !scenario.suspiciousIds.length) {
      showToast("Attack scenario is not ready yet. Wait for stream warm-up.", "info");
      return;
    }
    resetAttackState();
    primeDemoAttackCycle(scenario, { advancePattern: true });
    ensureDemoSuspiciousMinimum(
      scenario,
      Math.max(0, (performance.now() - Number(scenario.startedAt || performance.now())) / 1000),
      true
    );
    const activeScenarioIds = scenario.suspiciousIds.filter((id) => {
      const account = (state.lastAccounts || []).find((item) => String(item.account_id) === String(id));
      return account?.is_active !== false && !state.live?.banned_accounts?.includes(String(id));
    });
    const candidatePool = (scenario.fraudCandidatePool || []).filter((id) => {
      const account = (state.lastAccounts || []).find((item) => String(item.account_id) === String(id));
      return account?.is_active !== false && !state.live?.banned_accounts?.includes(String(id));
    });
    const preAttackVisible = activeScenarioIds.length ? activeScenarioIds : scenario.suspiciousIds;
    const fraudFromVisibleCandidates = preAttackVisible.filter((id) => candidatePool.includes(id));
    const fallbackFraud = candidatePool.filter((id) => !fraudFromVisibleCandidates.includes(id));
    let selectedFraud = [...fraudFromVisibleCandidates, ...fallbackFraud].slice(0, Math.min(6, candidatePool.length));
    if (selectedFraud.length && !selectedFraud.every((id) => preAttackVisible.includes(id))) {
      const expansion = selectedFraud.filter((id) => !preAttackVisible.includes(id));
      scenario.suspiciousIds = [...new Set([...(scenario.suspiciousIds || []), ...expansion])].slice(0, DEMO_SUSPICIOUS_SOFT_CAP);
    }
    selectedFraud = selectedFraud.filter((id) => scenario.suspiciousIds.includes(id));
    if (selectedFraud.length < 3) {
      showToast("Not enough active fraud candidates yet. Let monitoring run a bit longer.", "info");
      return;
    }
    const activeNoisePool = (scenario.noisePool || []).filter((id) => {
      const account = (state.lastAccounts || []).find((item) => String(item.account_id) === String(id));
      return account?.is_active !== false && !state.live?.banned_accounts?.includes(String(id));
    });
    const activeCandidateNonFraud = candidatePool.filter((id) => !selectedFraud.includes(String(id)));
    const baseSuspiciousPool = [...new Set([...(scenario.suspiciousIds || []), ...preAttackVisible])];
    const nonFraudBase = baseSuspiciousPool.filter((id) => !selectedFraud.includes(String(id)));
    const targetSuspiciousTotal = Math.min(
      DEMO_SUSPICIOUS_SOFT_CAP,
      Math.max(baseSuspiciousPool.length, selectedFraud.length + 4, DEMO_MIN_SUSPICIOUS)
    );
    const refillPool = [
      ...activeNoisePool.filter((id) => !nonFraudBase.includes(String(id))),
      ...activeCandidateNonFraud.filter((id) => !nonFraudBase.includes(String(id))),
    ];
    const retainedNonFraud = [...nonFraudBase];
    while (
      selectedFraud.length + retainedNonFraud.length < targetSuspiciousTotal &&
      refillPool.length
    ) {
      retainedNonFraud.push(refillPool.shift());
    }
    scenario.suspiciousIds = [
      ...selectedFraud,
      ...retainedNonFraud,
    ].slice(0, DEMO_SUSPICIOUS_SOFT_CAP);
    scenario.monitoringCount = Math.max(
      selectedFraud.length,
      retainedNonFraud.length,
      Math.min(targetSuspiciousTotal, scenario.suspiciousIds.length)
    );
    scenario.monitoringCountFloat = Number(scenario.monitoringCount);
    scenario.fraudIds = selectedFraud;
    console.debug("[FRAUD_SELECTION]", {
      fraud_source: "candidate_pool_intersection_with_suspicious",
      selected_fraud: selectedFraud,
      suspicious_pool_size: scenario.suspiciousIds.length,
    });
    state.demoAttackArmed = true;
    scenario.attackArmed = true;
    scenario.attackTriggered = false;
    scenario.revealCompleted = false;
    scenario.intelligenceShown = false;
    scenario.pendingGraph = null;
    scenario.revealDueAt = 0;
    state.phase = PHASES.BUILD;
    await scrollMainGraphIntoView();
    frameAttackCluster(scenario.suspiciousIds, 760);
    scenario.startedAt = performance.now() - 30000;
    scenario.lastTickAt = performance.now();
    scenario.phase = PHASES.ATTACK_FLOW;
    state.phase = PHASES.ATTACK_FLOW;
    showToast("Attack transaction phase started.", "success");
    return;
  }

  state.simulationInFlight = true;
  setSimulationButtonsDisabled(true);
  els.attackAlertStrip.textContent = "Injecting attack into the live backend stream...";
  els.attackAlertStrip.classList.add("alarm");
  try {
    const payload = await apiFetch("/ui/trigger_attack", { method: "POST" });
    if (payload.status !== "attack triggered") {
      state.simulationInFlight = false;
      setSimulationButtonsDisabled(false);
      showToast(payload.reason || "Attack could not be triggered.", "info");
      return;
    }
    state.currentInvestigationAccount = null;
    resetAttackState();
    renderDashboard({
      available: false,
      is_detecting: false,
      detection_job: payload.job || {
        status: "queued",
        attack_name: payload.attack_name,
        attack_time: payload.attack_time,
      },
    });
    els.attackAlertStrip.textContent = `Attack injected: ${payload.attack_name}. Rendering the full transaction sequence before starting detection.`;
    els.attackAlertStrip.classList.add("alarm");
    showToast(`Attack injected: ${payload.attack_name}`, "success");
    if (payload.attack_graph) {
      animateAttackInLiveGraph(payload.attack_graph);
    }
    handleDetectionMeta({
      available: false,
      is_detecting: false,
      detection_job: payload.job || {},
    }).catch(() => {});
    if (!state.websocketConnected) {
      pollAccounts().catch(() => {});
      pollTransactions().catch(() => {});
      pollLiveState().catch(() => {});
      pollLatestAttack().catch(() => {});
    }
  } catch (error) {
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    showToast(`Simulation failed: ${error.message}`, "error");
  }
}

async function resetSession() {
  if (DEMO_SIM_MODE) {
    stopDetectionPolling();
    stopAttackAnimation();
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    state.demoAttackArmed = false;
    hydrateBootstrapState(buildDemoBootstrapPayload(), { armAttack: false });
    showToast("Session reset complete.", "success");
    return;
  }
  setLoader(true, "Resetting live engine and dashboard state...");
  try {
    stopDetectionPolling();
    stopAttackAnimation();
    state.simulationInFlight = false;
    setSimulationButtonsDisabled(false);
    const payload = await apiFetch("/ui/bootstrap", { method: "POST" });
    hydrateBootstrapState(payload);
    if (!state.websocketConnected) {
      pollLiveState().catch(() => {});
    }
    showToast("Session reset complete.", "success");
  } catch (error) {
    showToast(`Reset failed: ${error.message}`, "error");
  } finally {
    setLoader(false);
  }
}

async function replayAttackFlow(force = false) {
  const replayBtn = document.getElementById("replay-attack-btn");
  const attackData = state.latestAttackData;
  if (!attackData || !attackData.edges || !attackData.edges.length) {
    return;
  }
  if (state.isReplaying) {
    return;
  }
  if (!force && state.lastReplayAttackName === attackData.attack_name) {
    return;
  }

  clearAttackReplayState({ resetLatest: false, message: `Replaying ${attackData.attack_name}...` });
  state.isReplaying = true;
  state.subgraphCreated = false;
  state.attackNodes.add(attackData.nodes.map((node) => ({ ...node })));
  state.attackEdges.clear();
  state.attackGraph3D?.syncFromDataSets(state.attackNodes, state.attackEdges);
  replayBtn.disabled = true;
  pulseNetworkFrame(els.attackNetworkFrame);
  updateText("attack-replay-meta", `Replaying ${attackData.attack_name}...`);

  for (const edge of attackData.edges) {
    updateText(
      "attack-replay-meta",
      `${attackData.attack_name}: ${edge.source} -> ${edge.target}  ${Number(edge.amount || 0).toFixed(0)}`
    );
    await animateTemporaryEdge({
      kind: "attack",
      from: String(edge.source),
      to: String(edge.target),
      color: "rgba(255, 93, 125, 0.88)",
      width: 2.4,
      label: `${Number(edge.amount || 0).toFixed(0)} ${edge.channel || ""}`.trim(),
      title: buildEdgeTitle(edge.source, edge.target, edge.amount, edge.channel),
      duration: 780,
    });
    await wait(120);
  }

  freezeAttackSubgraph(attackData);
  state.isReplaying = false;
  state.subgraphCreated = true;
  state.lastReplayAttackName = attackData.attack_name;
  replayBtn.disabled = false;
  updateText("attack-replay-meta", `Attack Detected: ${attackData.attack_name}`);
}

async function createNewAccount() {
  if (state.simulationInFlight || state.dashboard?.is_detecting) {
    return;
  }
  if (DEMO_SIM_MODE) {
    return;
  }
  try {
    await apiFetch("/create_account", { method: "POST", body: JSON.stringify({}) });
    if (!state.websocketConnected) {
      await pollAccounts();
      await pollLiveState();
    }
  } catch (error) {
    // Background account creation should not mark the entire API offline.
  }
}

function bindEvents() {
  const handleWindowResize = debounceOnAnimationFrame(() => {
    [els.liveNetworkOverlay, els.attackNetworkOverlay].forEach((canvas) => {
      if (canvas) {
        delete canvas.__overlayMetrics;
      }
    });
    clearAllTravelerOverlays();
    scheduleUiSync();
    scheduleNetworkZoomScaling();
  });

  initCollapsibles();
  initEarlyWarningDisclosure();
  document.getElementById("simulate-attack-btn")?.addEventListener("click", runSimulation);
  document.getElementById("simulate-attack-btn-secondary")?.addEventListener("click", runSimulation);
  document.getElementById("reset-session-btn")?.addEventListener("click", resetSession);
  document.getElementById("replay-attack-btn")?.addEventListener("click", () => replayAttackFlow(true));
  els.banSelectAllBtn?.addEventListener("click", () => {
    const fraudAccounts = getActiveFraudAccounts();
    if (!fraudAccounts.length) {
      showToast("No validated fraud accounts are available to select.", "info");
      return;
    }
    state.banSelect.setValue(fraudAccounts, false);
    setBanSelection(fraudAccounts);
  });
  document.getElementById("ban-selected-btn")?.addEventListener("click", async () => {
    const selected = [...new Set(
      []
        .concat(state.banSelect.getValue())
        .flatMap((value) => String(value || "").split(","))
        .map((value) => value.trim())
        .filter(Boolean)
    )];
    if (!selected.length) {
      const fallbackFraud = getActiveFraudAccounts();
      if (fallbackFraud.length) {
        selected.push(...fallbackFraud);
      }
    }
    if (!selected.length) {
      showToast("Select one or more detected accounts first.", "info");
      return;
    }
    try {
      if (!DEMO_SIM_MODE) {
        await apiFetch("/ban_accounts", {
          method: "POST",
          body: JSON.stringify(selected),
        });
      }
      await applyBanAccounts(selected, {
        message: `Banned ${selected.length} account(s).`,
        alarm: false,
        resetAttack: !DEMO_SIM_MODE,
        clearLatestAttack: !DEMO_SIM_MODE,
        showToastMessage: true,
      });
      if (!DEMO_SIM_MODE) {
        await pollLiveState();
        await refreshDashboard();
        await pollAccounts();
      }
    } catch (error) {
      showToast(`Ban failed: ${error.message}`, "error");
    }
  });

  els.investigationSelect?.addEventListener("change", (event) => {
    if (event.target.value) {
      loadInvestigation(event.target.value).catch((error) => {
        showToast(`Investigation failed: ${error.message}`, "error");
      });
    }
  });

  els.muteSirenBtn?.addEventListener("click", () => {
    state.sirenMuted = !state.sirenMuted;
    if (els.muteSirenBtn) {
      els.muteSirenBtn.textContent = state.sirenMuted ? "Unmute Siren" : "Mute Siren";
    }
  });

  window.addEventListener(
    "resize",
    handleWindowResize,
    { passive: true }
  );
}

function startPolling() {
  if (state.pollingFallbackStarted) {
    return;
  }
  state.pollingFallbackStarted = true;
  const wrap = (fn) => async () => {
    try {
      await fn();
      setApiStatus(true);
    } catch (error) {
      setApiStatus(false);
    }
  };

  state.intervals.push(setInterval(wrap(pollLiveState), LIVE_POLL_MS));
  state.intervals.push(setInterval(wrap(pollTransactions), TX_POLL_MS));
  state.intervals.push(setInterval(wrap(pollAccounts), ACCOUNT_POLL_MS));
  state.intervals.push(setInterval(wrap(pollLatestAttack), ATTACK_POLL_MS));
}

function stopPolling() {
  state.intervals.forEach((intervalId) => clearInterval(intervalId));
  state.intervals = [];
  state.pollingFallbackStarted = false;
}

function startBackgroundLoops() {
  if (state.backgroundLoopsStarted) {
    return;
  }
  state.backgroundLoopsStarted = true;

  const wrap = (fn) => async () => {
    try {
      await fn();
    } catch (error) {
      // Ignore background loop noise for global API health.
    }
  };

  window.setInterval(wrap(createNewAccount), ACCOUNT_CREATE_MS);
  window.setInterval(pruneLiveEdges, 1200);
}

function scheduleWebSocketReconnect() {
  if (state.websocketReconnectTimer) {
    return;
  }
  state.websocketReconnectTimer = window.setTimeout(() => {
    state.websocketReconnectTimer = null;
    connectWebSocket();
  }, 1500);
}

function connectWebSocket() {
  if (state.websocket) {
    try {
      state.websocket.close();
    } catch (error) {
      // ignore close races
    }
  }

  const socket = new WebSocket(websocketUrl("/ws/live"));
  state.websocket = socket;

  socket.onopen = () => {
    state.websocketConnected = true;
    stopPolling();
    setApiStatus(true);
  };

  socket.onmessage = (event) => {
    try {
      scheduleSnapshotProcessing(JSON.parse(event.data));
    } catch (error) {
      // ignore malformed frames
    }
  };

  socket.onerror = () => {
    // Let polling fallback decide health; websocket errors can be transient.
  };

  socket.onclose = () => {
    if (state.websocket === socket) {
      state.websocket = null;
    }
    state.websocketConnected = false;
    if (!state.pollingFallbackStarted) {
      startPolling();
      pollLiveState().catch(() => {});
      pollAccounts().catch(() => {});
      pollTransactions().catch(() => {});
      pollLatestAttack().catch(() => {});
    }
    scheduleWebSocketReconnect();
  };
}

async function bootstrap() {
  setLoader(true, "Bootstrapping fraud intelligence...");

  try {
    if (!DEMO_SIM_MODE) {
      await resolveApiBase();
    }
    if (!DEMO_SIM_MODE) {
      initTransactionWorker();
    }
    initNetworks();
    createBanSelect();
    bindEvents();
    setSimulationButtonsDisabled(false);
    startBackgroundLoops();
    setLoader(false);
    const payload = DEMO_SIM_MODE
      ? buildDemoBootstrapPayload()
      : await apiFetch("/ui/bootstrap", { method: "POST" });
    hydrateBootstrapState(payload);
    if (!DEMO_SIM_MODE) {
      connectWebSocket();
    }
    setApiStatus(true);
  } catch (error) {
    setApiStatus(false);
    showToast(`Bootstrap failed: ${error.message}`, "error");
  } finally {
    setLoader(false);
  }
}

bootstrap();
