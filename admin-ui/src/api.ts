export const API = "/api/admin";

export async function apiGet<T = any>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body?.error) message = body.error;
    } catch {
      // 保留状态码
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T = any>(
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data: any = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error(data?.error || `HTTP ${response.status}`);
    (error as any).status = response.status;
    (error as any).field = data?.field;
    throw error;
  }
  return data as T;
}

export type UploadedFile = {
  name: string;
  path: string;
  size: number;
};

export async function apiUpload(
  files: File[],
): Promise<{ files: UploadedFile[] }> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  const response = await fetch(`${API}/uploads`, {
    method: "POST",
    body: form,
  });
  let data: any = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const error = new Error(data?.error || `HTTP ${response.status}`);
    (error as any).status = response.status;
    (error as any).field = data?.field;
    throw error;
  }
  return data as { files: UploadedFile[] };
}

export type HealthItem = { code: string; message: string };

export type Health = {
  ok: boolean;
  red: HealthItem[];
  yellow: HealthItem[];
  db: { path: string; version: number; schema_version: number };
  provider: { fake: boolean; modes: Record<string, string>; notes: string[] };
  pipelines: Array<{
    kind: string;
    status: string;
    started_at: string;
    error: string | null;
  }>;
  index: { missing_embeddings: number; missing_fts: number };
  counts: Record<string, number>;
};

export type Task = {
  task_id: string;
  kind: "ingest" | "rebuild" | "evaluate";
  status:
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "cancelled"
    | "awaiting_review";
  params: Record<string, any>;
  progress: {
    phase?: string;
    current?: number | null;
    total?: number | null;
    message?: string;
  } | null;
  log_tail: string[];
  result: Record<string, any> | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export const TASK_TERMINAL = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "awaiting_review",
]);

export const EVAL_SUITES = [
  "probe",
  "asr",
  "questions",
  "scoring",
  "agent",
] as const;

export function taskStatusColor(status: string): any {
  if (status === "succeeded") return "success";
  if (status === "failed") return "error";
  if (status === "running") return "info";
  if (status === "awaiting_review") return "warning";
  return "default";
}

export function taskLabel(kind: string): string {
  if (kind === "ingest") return "知识摄取";
  if (kind === "rebuild") return "知识重建";
  if (kind === "evaluate") return "整体评测";
  return kind;
}

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 19);
}
