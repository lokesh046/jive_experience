import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { disablePush } from "./push";
import { api, clearTokens, loadTokens, refreshToken, saveTokens, setSignedOutHandler } from "./api";
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
      const rt = await loadTokens();
      if (!rt) return drop();
      try {
        // The refresh call hands back a fresh pair and who we are in one go.
        const pair = await api<TokenPair>("auth/refresh", { method: "POST", json: { refresh_token: rt } });
        await saveTokens(pair);
        setUser(pair.user);
        setStatus("signedIn");
      } catch (e: any) {
        // Offline at launch must not sign the person out; only a refused token does.
        if (e?.status === 401 || e?.status === 403) { await clearTokens(); drop(); } else drop();
      }
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
