export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "/api";

export type UploadResponse = {
  file_id: string;
  filename: string;
  size: number;
  upload_time: string;
};

export type TranslationRequest = {
  file_id: string;
  lang_in: string;
  lang_out: string;
  qps?: number;
  debug?: boolean;
  glossary_ids?: string[];
  model?: string;
  translate_images_experimental?: boolean; // 实验性：翻译图片
};

export type StartTranslationResponse = {
  task_id: string;
  status: string;
  owner_token?: string;
};

export type TaskItem = {
  task_id: string;
  status: string;
  filename: string;
  original_filename?: string;
  source_lang: string;
  target_lang: string;
  translate_images_experimental?: boolean;
  progress: number;
  stage: string;
  start_time: string | null;
  end_time: string | null;
  message: string | null;
  error: string | null;
  owner_ip?: string | null;
  created_at: string;
  updated_at: string;
  // 可选：队列位置（仅当 status=queued 且仍在等待队列中）
  queue_position?: number | null;
};

export type TasksResponse = {
  tasks: TaskItem[];
  total: number;
  page: number;
  page_size: number;
};

export type TaskStatusResponse = {
  task_id: string;
  status: string;
  progress: number;
  stage: string;
  message?: string;
  error?: string;
  start_time?: string;
  end_time?: string;
};

export async function uploadFile(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE_URL}/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function startTranslation(req: TranslationRequest): Promise<StartTranslationResponse> {
  const res = await fetch(`${API_BASE_URL}/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function listTasks(params?: { page?: number; page_size?: number; only_mine?: boolean }): Promise<TasksResponse> {
  const qs = new URLSearchParams();
  const page = params?.page ?? 1;
  const pageSize = params?.page_size ?? 15;
  const onlyMine = params?.only_mine ?? false;
  qs.set("page", String(page));
  qs.set("page_size", String(pageSize));
  if (onlyMine) qs.set("only_mine", "true");
  const url = `${API_BASE_URL}/tasks?${qs.toString()}`;
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function getTaskStatus(task_id: string): Promise<TaskStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/tasks/${task_id}/status`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function getClientIP(): Promise<{ ip: string }> {
  const res = await fetch(`${API_BASE_URL}/client-ip`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function deleteTasks(task_ids: string[], ownerToken?: string): Promise<{
  deleted: string[];
  cancelled: string[];
  not_found: string[];
  errors: Record<string, string>;
}> {
  const res = await fetch(`${API_BASE_URL}/tasks/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(ownerToken ? { "X-Owner-Token": ownerToken } : {}) },
    body: JSON.stringify({ task_ids }),
  });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}

export async function createDownloadToken(task_id: string, file_type: "mono"|"glossary", owner_token?: string): Promise<{token: string; expires_at: string}> {
  const url = `${API_BASE_URL}/tasks/${task_id}/download/token?file_type=${encodeURIComponent(file_type)}`;
  const headers: Record<string, string> = {};
  if (owner_token) headers["X-Owner-Token"] = owner_token;
  const res = await fetch(url, { method: "POST", headers });
  if (!res.ok) {
    throw new Error(await res.text());
  }
  return res.json();
}