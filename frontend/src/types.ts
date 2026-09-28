export type BatchState = "open" | "running" | "finished" | "purged";

export type DocumentState =
  | "created"
  | "uploaded"
  | "validating"
  | "queued"
  | "processing"
  | "verifying"
  | "review_required"
  | "completed"
  | "failed"
  | "rejected"
  | "cancelled";

export type BatchView = {
  batch_id: string;
  state: BatchState;
  mask_salary: boolean;
  document_count: number;
  version: number;
};

export type DocumentView = {
  document_id: string;
  batch_id: string;
  state: DocumentState;
  document_format: "pdf" | "docx" | null;
  size_bytes: number | null;
  attempt: number;
  error_code: string | null;
  review_reasons: string[];
  can_approve: boolean;
  has_output: boolean;
  finding_counts: Record<string, number> | null;
  residual_counts: Record<string, number>;
  residual_pages: Record<string, number[]>;
  hidden_removed: Record<string, number>;
  version: number;
};

export type BatchDetail = BatchView & {
  documents: DocumentView[];
};

export type ApiErrorBody = {
  code: string;
  batch_id?: string;
  document_id?: string;
  limit?: number;
};
