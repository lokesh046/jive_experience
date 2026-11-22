/** Browser-side API access. Goes through this app's own /api proxy, never straight to the backend. */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api/${path.replace(/^\//, "")}`, {
    ...rest,
    headers: { ...(json !== undefined ? { "Content-Type": "application/json" } : {}), ...headers },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "ERROR", err?.message ?? "Something went wrong. Please try again.");
  }
  return data as T;
}

/** Remember where to go after signing in. */
export function rememberNext(path: string) {
  try {
    sessionStorage.setItem("jive_next", path);
  } catch {}
}
export function takeNext(fallback = "/tickets"): string {
  try {
    const v = sessionStorage.getItem("jive_next");
    sessionStorage.removeItem("jive_next");
    if (v && v.startsWith("/") && !v.startsWith("//")) return v;
  } catch {}
  return fallback;
}
