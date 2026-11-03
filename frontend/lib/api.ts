export type Notebook = {
  id: string;
  name: string;
  document_count: number;
  updated_at: string;
};
export type Document = {
  source_type: string;
  latest_version: number;
  import_status?: string;
  import_error?: string;
  source_url?: string;
  generation: number;
  processing?: {page:number;pages:number;stage:string}|null;
  extraction?: {ocr_pages?:number[];characters?:number}|null;
  id: string;
  filename: string;
  size: number;
  pages: number | null;
  status: string;
  error: string | null;
};
export type Conversation = { id: string; title: string; updated_at: string };
export type Citation = {
  label: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  page: number | null;
  version?: number;
  source_type?: string;
  location?: {block_id?:string;label?:string};
  position?: string;
  ordinal: number;
  text: string;
};
export type Message = {
  id: string;
  role: string;
  content: string;
  status: string;
  error: string | null;
  citations: Citation[];
};
export type WritingCitation = Partial<Citation> & {
  label: number;
  kind: "document" | "note";
  filename: string;
  text: string;
  version: number;
  state: "active" | "deleted" | "changed";
  note_id?: string;
};
export type Writing = {
  id: string;
  notebook_id: string;
  title: string;
  content: string;
  kind: "note" | "summary" | "guide";
  version: number;
  edited: boolean;
  updated_at: string;
  document_id: string | null;
  citations: WritingCitation[];
  details: {
    structured?: { questions?: { text: string; refs: number[] }[] };
    inputs?: {
      documents: { id: string; filename: string; version: number }[];
      notes: { id: string; title: string; version: number }[];
      purpose: string;
      audience: string;
      length: string;
    };
  };
  job: {
    id: string;
    generation: number;
    status: string;
    attempts: number;
    error: string | null;
  } | null;
};
export type Page<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
};
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function request(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set("X-Requested-With", "narcissus");
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api" + path, {
    ...options,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.location.assign("/login?expired=1");
    throw new ApiError(
      response.status,
      data?.error?.message || "请求失败，请稍后重试",
    );
  }
  return response;
}
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await request(path, options);
  return response.status === 204 ? (undefined as T) : response.json();
}
export const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});
export function errorText(e: unknown) {
  if (e instanceof TypeError && /fetch|network|load failed/i.test(e.message))
    return "暂时无法连接服务，请检查网络后重新加载";
  return e instanceof Error ? e.message : "发生错误，请重试";
}

export async function stream(
  path: string,
  options: RequestInit,
  onEvent: (event: string, data: Record<string, unknown>) => void,
) {
  const response = await request(path, options);
  if (!response.body) throw new Error("回答连接失败，请重试");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    completed = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let at: number;
      while ((at = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, at);
        buffer = buffer.slice(at + 2);
        const kind = block
          .split("\n")
          .find((l) => l.startsWith("event:"))
          ?.slice(6)
          .trim();
        const data = block
          .split("\n")
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trim())
          .join("\n");
        if (kind && data) {
          onEvent(kind, JSON.parse(data));
          if (kind === "done") completed = true;
        }
      }
    }
    if (!completed) throw new Error("回答连接已中断，可重试继续");
  } finally {
    reader.releaseLock();
  }
}
