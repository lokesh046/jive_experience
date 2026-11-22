"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, takeNext } from "@/lib/api-client";

export default function GoogleCallback() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    // The code is single-use; React's dev double-invoke must not spend it twice.
    if (started.current) return;
    started.current = true;
    const q = new URLSearchParams(window.location.search);
    const code = q.get("code");
    const state = q.get("state");
    Promise.resolve()
      .then(() => {
        if (q.get("error") || !code || !state) throw new ApiError(400, "CANCELLED", "Sign-in was cancelled or did not complete.");
        return api<unknown>("auth/google/callback", { method: "POST", json: { code, state } });
      })
      .then(() => router.replace(takeNext()))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Sign-in did not complete. Please try again."));
  }, [router]);

  return (
    <main className="page">
      <div className="wrap narrow">
        {error ? (
          <>
            <h1>We could not sign you in</h1>
            <p style={{ margin: "16px 0 36px" }}>{error}</p>
            <a className="pill" href="/signin">Try again</a>
          </>
        ) : (
          <>
            <h1>Signing you in</h1>
            <p style={{ marginTop: 16 }} aria-live="polite">One moment.</p>
          </>
        )}
      </div>
    </main>
  );
}
