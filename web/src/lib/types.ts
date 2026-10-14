// The JSON contract written by the Python pipeline (backend/mbf/signals/web.py).
// Dates are ISO strings in Pakistan time without an offset ("2026-10-14T00:00:00").

export type Mode = "live" | "backtest" | "preview";

export type Stats = {
  n: number;
  win_rate: number;
  mean_net: number;
  median_net: number;
  worst?: number;
  best?: number;
  stopped?: number;
};

export type Result = {
  status: "pending_entry" | "open" | "closed" | "skipped" | "no_data";
  outcome: "exit_ex_date" | "exit_late" | "stop" | "stop_gap" | "stop_locked" | null;
  outcome_text: string | null;
  entry_price: number | null;
  exit_price: number | null;
  exit_date: string | null;
  net: number | null;
  dividend: number | null;
  last_price: number | null;
};

export type SignalCard = {
  id: string;
  type: string;
  type_name: string;
  mode: Mode;
  symbol: string;
  name: string | null;
  sector: string | null;
  signal_date: string;
  entry_date: string;
  exit_date: string;
  nights: number;
  close_at_signal: number;
  max_entry_price: number;
  stop_price_approx: number;
  stop_pct: number;
  dividend_rs: number;
  dividend_pct_of_par: number;
  par: number;
  yield: number;
  yield_band: string | null;
  expected: { win_rate: number | null; mean_net: number | null; median_net: number | null; n: number | null };
  how: string;
  warnings: { warning: string; title: string }[];
  result?: Result;
  rank?: number;
  strongest?: boolean;
};

export type Upcoming = {
  symbol: string;
  name: string | null;
  dividend_rs: number;
  ex_date: string;
  last_close: number | null;
  signal_evening: string;
  entry_date: string;
  yield_now: number | null;
  liquid: boolean;
  qualifies_now: boolean;
};

export type Warning = {
  symbol: string;
  name: string | null;
  warning: string;
  title: string;
  detail: string;
  since: string;
};

export type Market = {
  kse100?: number;
  date?: string;
  chg_1d?: number;
  chg_5d?: number;
  chg_20d?: number;
  above_200d?: boolean | null;
  breadth50?: number | null;
  spark?: { date: string; close: number }[];
};

export type TrackRecord = {
  all: Stats;
  by_band: Record<string, Stats>;
  by_year?: Record<string, Stats>;
  since: string;
};

export type Today = {
  generated_at: string;
  asof: string;
  next_session: string;
  tonight: SignalCard[];
  active: SignalCard[];
  upcoming: Upcoming[];
  market: Market;
  warnings: Warning[];
  track_record: Record<string, TrackRecord>;
  disclaimer: string;
};

export type WeekBlock = {
  week: string;
  signals: SignalCard[];
  n: number;
  closed: number;
  wins: number;
  stops: number;
  skipped: number;
  mean_net: number | null;
};

export type HistoryIndex = {
  generated_at: string;
  years: number[];
  track_record: Record<string, TrackRecord>;
  curve: { week: string; cum_profit: number; trades: number }[];
  disclaimer: string;
};

export type HistoryYear = { year: number; weeks: WeekBlock[] };

export type Price = { date: string; open: number; high: number; low: number; close: number; volume: number };

export type SignalDetail = SignalCard & {
  why: string[];
  event: {
    announced_at: string;
    details: string | null;
    book_closure: [string | null, string | null];
    ex_date: string;
    ex_basis: string | null;
    source: string | null;
  };
  fundamentals: {
    as_of: string;
    eps_annual?: { period: string; eps: number }[];
    eps_quarterly?: { period: string; eps: number }[];
    net_margin_pct?: { period: string; value: number };
    eps_growth_pct?: { period: string; value: number };
  } | null;
  technicals: Record<string, number | null>;
  technicals_date: string;
  warnings_detail: { symbol: string; warning: string; title: string; detail: string; since: string }[];
  track_record: TrackRecord | null;
  this_stock_before: { id: string; signal_date: string; ex_date: string; yield: number; net: number | null; outcome: string | null }[];
  prices: Price[];
};
