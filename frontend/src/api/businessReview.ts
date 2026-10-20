export type Delta = { current: number | null; previous: number | null; delta: number | null; percent: number | null };
export type ReviewRow = { key: string; name: string; sku?: string; source?: string; state: string; metrics: Record<string, Delta> };
export type ReviewEvidence = {
  id?: string; source: string; occurred_at: string; title: string; detail: string;
  evidence_type: string; actor?: string; object_id?: string; reference_url?: string;
  payload?: Record<string, unknown>;
};
export type Coverage = {
  source: string; rows: number; days_with_rows: number; days_requested: number;
  verified_sync_days: number; first: string | null; last: string | null; status: string;
};
export type ReviewParameters = {
  date_from: string; date_to: string; baseline_from: string; baseline_to: string; with_costs: boolean;
};
export type ReviewPeriod = {
  date_from: string; date_to: string; days: number; metrics: Record<string, number | null>; coverage: Coverage[];
  costs: null | { products: number; fully_costed_products: number; covered_net_sales: number;
    covered_cogs: number; covered_gross_profit: number; basis: string };
};
export type BusinessReview = {
  generated_at: string; current: ReviewPeriod; baseline: ReviewPeriod; metrics: Record<string, Delta>;
  comparisons: Record<string, ReviewRow[]>; sources: Array<{ key: string; name: string; cost: Delta; value: Delta; roas: Delta }>;
  findings: Array<{ severity: string; title: string; detail: string }>;
  events: ReviewEvidence[]; events_truncated: boolean; limitations: string[];
};
export type ReviewJobs = { counts: Record<string, number>; rows: Array<{
  id: string; provider: string; kind: string; date_from: string; date_to: string; status: string;
  records: number; attempts: number; error: string | null;
}> };
