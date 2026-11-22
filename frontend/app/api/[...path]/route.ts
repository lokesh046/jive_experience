/**
 * Same-origin proxy to the FastAPI backend.
 *
 * Why it exists: the access and refresh tokens live in httpOnly cookies, so page
 * JavaScript (and any script injected into it) can never read them. The browser
 * calls /api/*, this handler adds the bearer token, and refreshes it when it has
 * expired. It also removes the need for CORS.
 */
import { revalidateTag } from "next/cache";
import { NextRequest, NextResponse } from "next/server";
import { API_V1 } from "@/lib/config";

const ACCESS = "jive_at";
const REFRESH = "jive_rt";
const REFRESH_DAYS = 30;
const IS_PROD = process.env.NODE_ENV === "production";

// Only these backend areas are reachable from the browser.
const ALLOWED = ["events", "auth", "users", "bookings", "tickets", "scanner", "admin"];

interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: unknown;
}

// One refresh per refresh token at a time. The backend rotates refresh tokens and
// treats reuse as theft, so two parallel requests must share a single refresh.
const inflight = new Map<string, Promise<TokenPair | null>>();

function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  let p = inflight.get(refreshToken);
  if (!p) {
    p = fetch(`${API_V1}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    })
      .then((r) => (r.ok ? (r.json() as Promise<TokenPair>) : null))
      .catch(() => null)
      .finally(() => setTimeout(() => inflight.delete(refreshToken), 10_000));
    inflight.set(refreshToken, p);
  }
  return p;
}

// The role is only used to decide which header links to show. It is not a
// credential: every admin and scanner request is still checked by the API.
const ROLE = "jive_role";
function setRole(res: NextResponse, role: unknown, maxAge: number) {
  if (typeof role === "string") res.cookies.set(ROLE, role, { httpOnly: false, sameSite: "lax", secure: IS_PROD, path: "/", maxAge });
}

function setSession(res: NextResponse, t: TokenPair) {
  const base = { httpOnly: true, sameSite: "lax" as const, secure: IS_PROD };
  res.cookies.set(ACCESS, t.access_token, { ...base, path: "/", maxAge: Math.max(60, t.expires_in) });
  res.cookies.set(REFRESH, t.refresh_token, { ...base, path: "/api", maxAge: REFRESH_DAYS * 86400 });
  setRole(res, (t.user as { role?: string } | null)?.role, REFRESH_DAYS * 86400);
}

function clearSession(res: NextResponse) {
  res.cookies.set(ACCESS, "", { path: "/", maxAge: 0 });
  res.cookies.set(REFRESH, "", { path: "/api", maxAge: 0 });
  res.cookies.set(ROLE, "", { path: "/", maxAge: 0 });
}

async function call(url: string, req: NextRequest, body: ArrayBuffer | undefined, token: string | undefined) {
  const headers = new Headers();
  const type = req.headers.get("content-type");
  if (type) headers.set("content-type", type);
  if (token) headers.set("authorization", `Bearer ${token}`);
  const ip = req.headers.get("x-forwarded-for");
  if (ip) headers.set("x-forwarded-for", ip);
  return fetch(url, { method: req.method, headers, body, cache: "no-store", redirect: "manual" });
}

function passthrough(upstream: Response, data: ArrayBuffer | null) {
  const headers = new Headers({ "cache-control": "no-store" });
  const type = upstream.headers.get("content-type");
  if (type) headers.set("content-type", type);
  return new NextResponse(upstream.status === 204 ? null : data, { status: upstream.status, headers });
}

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  if (!ALLOWED.includes(path[0]) || path.some((s) => s === ".." || s === ".")) {
    return NextResponse.json({ error: { code: "NOT_FOUND", message: "Not found." } }, { status: 404 });
  }

  const url = `${API_V1}/${joined}${req.nextUrl.search}`;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let body = hasBody ? await req.arrayBuffer() : undefined;
  let access = req.cookies.get(ACCESS)?.value;
  const refresh = req.cookies.get(REFRESH)?.value;

  // Sign-out: the backend wants the refresh token, which the browser cannot read.
  if (joined === "auth/logout" || joined === "auth/logout-all") {
    if (joined === "auth/logout") {
      body = new TextEncoder().encode(JSON.stringify({ refresh_token: refresh ?? "x".repeat(20) })).buffer as ArrayBuffer;
    }
    let upstream: Response | null = null;
    try {
      upstream = await call(url, req, body, access);
    } catch {}
    const res = new NextResponse(null, { status: 204, headers: { "cache-control": "no-store" } });
    clearSession(res);
    void upstream;
    return res;
  }

  let upstream: Response;
  let rotated: TokenPair | null = null;
  try {
    upstream = await call(url, req, body, access);
    // Expired access token: refresh once and retry once.
    if (upstream.status === 401 && refresh && joined !== "auth/google/callback") {
      rotated = await refreshTokens(refresh);
      if (rotated) {
        access = rotated.access_token;
        upstream = await call(url, req, body, access);
      }
    }
  } catch {
    return NextResponse.json(
      { error: { code: "UPSTREAM_UNAVAILABLE", message: "The service is not reachable right now. Please try again." } },
      { status: 502, headers: { "cache-control": "no-store" } },
    );
  }

  // Sign-in: keep the tokens in cookies and hand the page only the user.
  if (joined === "auth/google/callback" && upstream.ok) {
    const pair = (await upstream.json()) as TokenPair;
    const res = NextResponse.json({ user: pair.user }, { headers: { "cache-control": "no-store" } });
    setSession(res, pair);
    return res;
  }

  // An admin changed events, venues or ticket types: drop the cached public pages now,
  // so the change shows up straight away instead of after the cache lifetime.
  if (upstream.ok && hasBody && joined.startsWith("admin/") && /^admin\/(events|venues|ticket-categories)/.test(joined)) {
    revalidateTag("events", { expire: 0 });
  }
  const buf = upstream.status === 204 ? null : await upstream.arrayBuffer();
  const res = passthrough(upstream, buf);
  // Sessions that began before the role cookie existed get it from /auth/me.
  if (joined === "auth/me" && upstream.ok && buf) {
    try { setRole(res, (JSON.parse(new TextDecoder().decode(buf)) as { role?: string }).role, REFRESH_DAYS * 86400); } catch {}
  }
  if (rotated) setSession(res, rotated);
  // The refresh token itself was rejected: the session is over.
  if (upstream.status === 401 && refresh && !rotated) clearSession(res);
  return res;
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE };
