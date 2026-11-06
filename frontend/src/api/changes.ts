export type ChangeCounts = { count: number; individual: number; bulk: number };

export type ChangeRow = {
  id: string; source: string; occurred_at: string; day: string; evidence_type: string; actor: string | null;
  title: string; detail: string; object_id: string | null; reference_url: string | null;
  resource_type: string | null; client_type: string | null; campaign: string | null;
  payload: Record<string, unknown>;
};

export type BulkChangeGroup = {
  day: string; source: string; actor: string | null; evidence_type: string; title: string; count: number;
  first: string; last: string;
  sample: null | { resource_type: string | null; client_type: string | null; detail: string; object_id: string | null };
};

export type ChangeCoverage = {
  source: string; days_requested: number; days_covered: number; days_unavailable: number; days_failed: number;
  last_fetched_at: string | null;
};

export type ChangeHistory = {
  date_from: string; date_to: string; timezone: string; bulk_min_size: number;
  totals: {
    changes: number; individual: number; bulk: number; bulk_groups: number;
    by_source: Array<ChangeCounts & { source: string }>;
    by_actor: Array<ChangeCounts & { actor: string | null; sources: string[] }>;
  };
  filtered: { individual: number; bulk: number; bulk_groups: number };
  bulk_groups: BulkChangeGroup[]; bulk_groups_truncated: boolean;
  changes: ChangeRow[]; offset: number; limit: number; has_more: boolean;
  coverage: ChangeCoverage[];
};

export type ChangeQuery = {
  date_from: string; date_to: string; source?: string; actor?: string; q?: string;
  include_bulk?: boolean; offset?: number; limit?: number;
};

// Filter value for changes without a recorded person (matches the server's NO_ACTOR).
export const NO_ACTOR = "__none__";
