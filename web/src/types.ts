export type QuoteAction = {
  kind: string;
  immediate_paise?: number;
  held_paise?: number;
  cooling_minutes?: number;
  trusted_contact_name?: string | null;
};

export type Probe = {
  probe_id: string;
  question: string;
  options: string[];
};

export type QuoteResponse = {
  decision_id: string;
  verdict: string;
  tier: number;
  headline: string;
  facts: string[];
  counterfactual: string;
  action: QuoteAction;
  probe: Probe | null;
  lead_time_started_at: string;
};

export type AccountView = {
  account_id?: string;
  handle?: string;
  display_name?: string;
  balance_paise: number;
  available_paise: number;
  active_holds: Array<{
    id?: string;
    reason_ref: string;
    held_paise: number;
    releases_at: string | null;
  }>;
};

export type CommitResponse = {
  outcome: "settled" | "held" | "challenged";
  reason_ref?: string;
  releases_at?: string;
  circuit_breaker?: string;
};

export type GraphNode = {
  id: string;
  handle: string;
  label: string;
  bank: string;
  tier: number;
  risk: number;
  age_days: number;
  is_held: boolean;
  is_guest?: boolean;
};

export type GraphLink = {
  source: string | GraphNode;
  target: string | GraphNode;
  amount_paise: number;
  ts: string;
  taint: number;
  decision_id: string | null;
};

export type DecisionItem = {
  decision_id: string;
  ts: string;
  sender: string;
  receiver: string;
  amount_paise: number;
  tier: number;
  fused_score: number;
  top_rule: string | null;
  verdict: string;
};

export type Metrics = {
  prevented_loss_paise: number;
  median_lead_time_ms: number;
  false_challenge_rate: number;
  comprehension_rate: number;
  multiparty_coverage: number;
  denominators: {
    legit_tx: number;
    probes_shown: number;
    seeded_structures: number;
  };
};

export type InvestigatePayload = {
  account: {
    id: string;
    handle: string;
    display_name: string;
    bank_code: string;
    created_at: string;
    balance_paise: number;
    available_paise: number;
    age_days: number;
    is_held: boolean;
  };
  sub_scores: { ringwatch: number; trailscore: number; contextflag: number };
  fused_score?: number;
  tier?: number;
  verdict?: string;
  contributions: Array<{
    scorer: string;
    weight: number | null;
    value: number;
    contribution: number;
  }>;
  rules_fired: Array<{ code: string | null; points: number | null; detail: string | null }>;
  event_timeline: Array<{ ts: string; type: string; summary: string }>;
  neighbours: Array<{
    id: string;
    handle: string;
    direction: string;
    amount_paise: number;
    ts: string;
  }>;
  pattern_match: { similarity: number; label: string } | null;
  available_actions: string[];
};

export type WsEvent = {
  type: string;
  ts: string;
  data: Record<string, unknown>;
};

export type DirectoryItem = {
  id: string;
  handle: string;
  display_name: string;
  is_demo_guest: boolean;
  balance_paise: number;
  watch_token: string | null;
  contact_name: string | null;
};

export type Health = {
  db_ok: boolean;
  rf_model_loaded: boolean;
  gnn_model_loaded: boolean;
  ws_clients: number;
  last_decision_at: string | null;
  ambient_running?: boolean;
};
