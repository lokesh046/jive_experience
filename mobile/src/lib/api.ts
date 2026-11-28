import * as SecureStore from "expo-secure-store";
import { API_V1 } from "./config";
import type { TokenPair } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

const ACCESS = "jive_at";
const REFRESH = "jive_rt";

let access: string | null = null;
let onSignedOut: () => void = () => {};
export const setSignedOutHandler = (fn: () => void) => { onSignedOut = fn; };

export async function loadTokens(): Promise<string | null> {
  access = await SecureStore.getItemAsync(ACCESS);
  return await SecureStore.getItemAsync(REFRESH);
}

export async function saveTokens(t: Pick<TokenPair, "access_token" | "refresh_token">) {
  access = t.access_token;
  await SecureStore.setItemAsync(ACCESS, t.access_token);
  await SecureStore.setItemAsync(REFRESH, t.refresh_token);
}

export async function clearTokens() {
  access = null;
  await SecureStore.deleteItemAsync(ACCESS);
  await SecureStore.deleteItemAsync(REFRESH);
}

export const refreshToken = () => SecureStore.getItemAsync(REFRESH);

export type Refreshed = TokenPair | "rejected" | "offline" | "none";

// One refresh at a time, however many callers ask together. The server treats a refresh token
// used twice as stolen and ends the session, so two requests must never carry the same one.
let refreshing: Promise<Refreshed> | null = null;
export function refreshOnce(): Promise<Refreshed> {
  refreshing ??= (async (): Promise<Refreshed> => {
    try {
      const rt = await SecureStore.getItemAsync(REFRESH);
      if (!rt) return "none";
      const res = await fetch(`${API_V1}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (res.status === 401 || res.status === 403) return "rejected";
      if (!res.ok) return "offline";
      const pair = (await res.json()) as TokenPair;
      await saveTokens(pair);
      return pair;
    } catch {
      return "offline";
    } finally {
      setTimeout(() => { refreshing = null; }, 0);
    }
  })();
  return refreshing;
}

type Init = Omit<RequestInit, "body"> & { json?: unknown; file?: { blob: Blob; contentType: string } };

async function send(path: string, init: Init) {
  const { json, file, headers, ...rest } = init;
  return fetch(`${API_V1}/${path.replace(/^\//, "")}`, {
    ...rest,
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(file ? { "Content-Type": file.contentType } : {}),
      ...(access ? { Authorization: `Bearer ${access}` } : {}),
      ...headers,
    },
    body: file ? file.blob : json !== undefined ? JSON.stringify(json) : undefined,
  });
}

export async function api<T>(path: string, init: Init = {}): Promise<T> {
  let res: Response;
  try {
    res = await send(path, init);
    if (res.status === 401 && access && !path.startsWith("auth/")) {
      const r = await refreshOnce();
      if (typeof r === "object") res = await send(path, init);
      else {
        await clearTokens();
        onSignedOut();
      }
    }
  } catch {
    throw new ApiError(0, "NETWORK", "Can't reach JIVE. Check your connection and try again.");
  }
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch {}
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "ERROR", err?.message ?? "Something went wrong. Please try again.");
  }
  return data as T;
}
