import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { disablePush } from "./push";
import { api, clearTokens, loadTokens, refreshOnce, refreshToken, saveTokens, setSignedOutHandler } from "./api";
import type { AuthUser, TokenPair } from "./types";

type Status = "loading" | "signedOut" | "signedIn";
interface Ctx {
  status: Status;
  user: AuthUser | null;
  requestCode: (email: string) => Promise<void>;
  verifyCode: (email: string, code: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  const drop = useCallback(() => { setUser(null); setStatus("signedOut"); }, []);

  useEffect(() => {
    setSignedOutHandler(drop);
    (async () => {
      await loadTokens();
      // Who we are comes back with a fresh pair. A refused token signs out; no network does not.
      const r = await refreshOnce();
      if (typeof r === "object") { setUser(r.user); setStatus("signedIn"); return; }
      if (r === "rejected") await clearTokens();
      drop();
    })();
  }, [drop]);

  const requestCode = useCallback(async (email: string) => {
    await api("auth/email/request", { method: "POST", json: { email } });
  }, []);

  const verifyCode = useCallback(async (email: string, code: string) => {
    const pair = await api<TokenPair>("auth/email/verify", { method: "POST", json: { email, code } });
    await saveTokens(pair);
    setUser(pair.user);
    setStatus("signedIn");
  }, []);

  const signOut = useCallback(async () => {
    await disablePush();   // this phone stops getting this person's notifications
    const rt = await refreshToken();
    if (rt) { try { await api("auth/logout", { method: "POST", json: { refresh_token: rt } }); } catch {} }
    await clearTokens();
    drop();
  }, [drop]);

  const value = useMemo(() => ({ status, user, requestCode, verifyCode, signOut }), [status, user, requestCode, verifyCode, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
