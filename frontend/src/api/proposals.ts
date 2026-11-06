export type ProposalStatus = "discussion" | "approved" | "sent" | "done" | "not_done" | "rejected";
export type ProposalPlatform = "google_ads" | "meta_ads" | "tiktok_ads" | "merchant_center" | "tracking" | "site" | "other";
export type ProposalExecutor = "agency" | "owner" | "site";

export type ProposalNote = {
  id: string; author: "owner" | "advestiq"; text: string; status: ProposalStatus | null; created_at: string;
};

export type ProposalSummary = {
  code: string; title: string; platform: ProposalPlatform; executor: ProposalExecutor; created_on: string;
  status: ProposalStatus; status_changed_at: string | null; advestiq_status: string;
  check_7_on: string | null; check_14_on: string | null; updated_at: string;
  notes_count: number; last_note_at: string | null;
};

export type Proposal = ProposalSummary & {
  what: string; why: string; expected: string; rollback: string;
  message_subject: string; message_body: string; created_at: string; notes: ProposalNote[];
};

export type ProposalList = { rows: ProposalSummary[]; counts: Record<ProposalStatus, number> };
export type ProposalFilter = { status?: ProposalStatus | "open" | "closed" | ""; platform?: ProposalPlatform | "" };
