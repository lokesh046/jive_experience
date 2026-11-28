import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { clearOffline, loadUser, saveUser } from "./offline";
import { disablePush } from "./push";
import { API_V1 } from "./config";
import { api, clearTokens, loadTokens, refreshOnce, refreshToken, saveTokens, setSignedOutHandler } from "./api";
import type { AuthUser, TokenPair } from "./types";

type Status = "loading" | "signedOut" | "signedIn";
interface Ctx {
  status: Status;
  user: AuthUser | null;
  requestCode: (email: string) => Promise<void>;
  verifyCode: (email: string, code: string) => Promise<void>;
  /** Resolves false when the person closed the Google window. */
  googleSignIn: () => Promise<boolean>;
  /** Replace the signed-in person's details after they change them (their name, for instance). */
  updateUser: (u: AuthUser) => void;
  signOut: () => Promise<void>;
}

WebBrowser.maybeCompleteAuthSession();

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
      if (typeof r === "object") { setUser(r.user); setStatus("signedIn"); void saveUser(r.user); return; }
      if (r === "offline") {
        // No signal at launch is not a reason to sign out: open with who was signed in, and the saved tickets.
        const saved = await loadUser();
        if (saved) { setUser(saved); setStatus("signedIn"); return; }
      }
      if (r === "rejected") { await clearTokens(); await clearOffline(); }
      drop();
    })();
  }, [drop]);

  const requestCode = useCallback(async (email: string) => {
    await api("auth/email/request", { method: "POST", json: { email } });
  }, []);

  const verifyCode = useCallback(async (email: string, code: string) => {
    const pair = await api<TokenPair>("auth/email/verify", { method: "POST", json: { email, code } });
    await saveTokens(pair);
    void saveUser(pair.user);
    setUser(pair.user);
    setStatus("signedIn");
  }, []);

  const googleSignIn = useCallback(async () => {
    // Google comes back to the API, which hands the code on to this app's own link.
    const appLink = Linking.createURL("auth/google");
    const back = `${API_V1}/auth/google/mobile-return`;
    const start = await api<{ authorization_url: string; state: string }>(
      `auth/google/authorize?redirect_uri=${encodeURIComponent(back)}&app_redirect=${encodeURIComponent(appLink)}`,
    );
    const res = await WebBrowser.openAuthSessionAsync(start.authorization_url, appLink);
    if (res.type !== "success") return false;
    const q = Linking.parse(res.url).queryParams ?? {};
    if (q.error || typeof q.code !== "string" || typeof q.state !== "string") throw new Error("Google did not sign you in. Please try again.");
    const pair = await api<TokenPair>("auth/google/callback", { method: "POST", json: { code: q.code, state: q.state } });
    await saveTokens(pair);
    void saveUser(pair.user);
    setUser(pair.user);
    setStatus("signedIn");
    return true;
  }, []);

  const updateUser = useCallback((u: AuthUser) => { setUser(u); void saveUser(u); }, []);

  const signOut = useCallback(async () => {
    await disablePush();   // this phone stops getting this person's notifications
    const rt = await refreshToken();
    if (rt) { try { await api("auth/logout", { method: "POST", json: { refresh_token: rt } }); } catch {} }
    await clearTokens();
    await clearOffline();   // saved tickets belong to the person who just left
    drop();
  }, [drop]);

  const value = useMemo(() => ({ status, user, requestCode, verifyCode, googleSignIn, updateUser, signOut }), [status, user, requestCode, verifyCode, googleSignIn, updateUser, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
