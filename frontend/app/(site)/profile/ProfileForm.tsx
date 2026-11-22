"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Avatar } from "@/components/Avatar";
import { ApiError, api, rememberNext } from "@/lib/api-client";
import type { UserProfile } from "@/lib/types";

const MAX_BYTES = 2 * 1024 * 1024;
const PHONE_ERRORS: Record<string, string> = {
  PHONE_TAKEN: "That number is already used by another account.",
  PHONE_COUNTRY_NOT_ALLOWED: "We can only accept numbers from supported countries.",
};
const memberSince = (iso: string) => new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(new Date(iso));

export function ProfileForm() {
  const router = useRouter();
  const [me, setMe] = useState<UserProfile | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState<"" | "photo" | "name" | "phone">("");
  const [msg, setMsg] = useState<{ where: "photo" | "name" | "phone"; text: string; ok?: boolean } | null>(null);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    api<UserProfile>("users/me")
      .then((u) => { if (live) { setMe(u); setName(u.full_name ?? ""); setPhone(u.phone_e164 ?? "+91"); } })
      .catch((e) => { if (e instanceof ApiError && e.status === 401) { rememberNext("/profile"); router.replace("/signin"); } });
    return () => { live = false; };
  }, [router]);

  const fail = (where: "photo" | "name" | "phone", e: unknown, map: Record<string, string> = {}) =>
    setMsg({ where, text: e instanceof ApiError ? (map[e.code] ?? e.message) : "Something went wrong. Please try again." });

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(f.type)) return setMsg({ where: "photo", text: "Use a JPEG, PNG or WebP image." });
    if (f.size > MAX_BYTES) return setMsg({ where: "photo", text: "That image is larger than 2 MB." });
    setBusy("photo"); setMsg(null);
    try { setMe(await api<UserProfile>("users/me/avatar", { method: "PUT", body: f, headers: { "Content-Type": f.type } })); setMsg({ where: "photo", text: "Photo updated.", ok: true }); router.refresh(); }
    catch (err) { fail("photo", err); }
    finally { setBusy(""); }
  }

  async function removePhoto() {
    setBusy("photo"); setMsg(null);
    try { setMe(await api<UserProfile>("users/me/avatar", { method: "DELETE" })); setMsg({ where: "photo", text: "Photo removed.", ok: true }); }
    catch (err) { fail("photo", err); }
    finally { setBusy(""); }
  }

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    setBusy("name"); setMsg(null);
    try { const u = await api<UserProfile>("users/me", { method: "PATCH", json: { full_name: name.trim() } }); setMe(u); setName(u.full_name ?? ""); setMsg({ where: "name", text: "Saved.", ok: true }); }
    catch (err) { fail("name", err); }
    finally { setBusy(""); }
  }

  async function savePhone(e: React.FormEvent) {
    e.preventDefault();
    setBusy("phone"); setMsg(null);
    try { await api("auth/phone", { method: "PUT", json: { phone_e164: phone.replace(/[\s-]/g, "") } }); setMe((m) => (m ? { ...m, phone_e164: phone.replace(/[\s-]/g, "") } : m)); setMsg({ where: "phone", text: "Saved.", ok: true }); }
    catch (err) { fail("phone", err, PHONE_ERRORS); }
    finally { setBusy(""); }
  }

  if (!me) return <main className="page"><div className="wrap narrow"><div className="skeleton" style={{ height: 112, width: 112, borderRadius: "50%" }} /></div></main>;

  const note = (where: "photo" | "name" | "phone") =>
    msg?.where === where && <p className={msg.ok ? "ok" : "err"} role={msg.ok ? "status" : "alert"}>{msg.text}</p>;

  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Profile</h1>

        <section className="section" aria-labelledby="photo">
          <h2 id="photo">Photo</h2>
          <div className="pic-row">
            <Avatar url={me.avatar_url} />
            <div>
              <div className="actions">
                <button className="pill sm" type="button" onClick={() => file.current?.click()} disabled={busy === "photo"}>
                  {busy === "photo" ? "Uploading…" : me.avatar_url ? "Change photo" : "Add photo"}
                </button>
                {me.avatar_url && <button className="link" type="button" onClick={removePhoto} disabled={busy === "photo"}>Remove</button>}
                <input ref={file} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={pick} />
              </div>
              <p className="hint">JPEG, PNG or WebP, up to 2 MB. It is cropped to a square.</p>
              {note("photo")}
            </div>
          </div>
        </section>

        <section className="section" aria-labelledby="name-h">
          <h2 id="name-h">Name</h2>
          <form onSubmit={saveName}>
            <div className="f"><label htmlFor="name">Full name</label><input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required /></div>
            <div><button className="pill sm" type="submit" disabled={busy === "name" || !name.trim() || name.trim() === (me.full_name ?? "")}>{busy === "name" ? "Saving…" : "Save name"}</button>{note("name")}</div>
          </form>
        </section>

        <section className="section" aria-labelledby="phone-h">
          <h2 id="phone-h">Phone</h2>
          <form onSubmit={savePhone}>
            <div className="f"><label htmlFor="phone">Mobile number</label><input id="phone" type="tel" inputMode="tel" autoComplete="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 98765 43210" required /></div>
            <p className="hint" style={{ marginTop: -12 }}>Used to reach you about your bookings. Include the country code.</p>
            <div><button className="pill sm" type="submit" disabled={busy === "phone" || phone.replace(/[\s-]/g, "") === (me.phone_e164 ?? "")}>{busy === "phone" ? "Saving…" : "Save number"}</button>{note("phone")}</div>
          </form>
        </section>

        <section className="section" aria-labelledby="acct">
          <h2 id="acct">Account</h2>
          <div className="rows">
            <div><span className="name">Email</span><span>{me.email}</span></div>
            <div><span className="name">Member since</span><span>{memberSince(me.created_at)}</span></div>
          </div>
          <p className="hint">Your email comes from your Google account, so it cannot be changed here.</p>
        </section>
      </div>
    </main>
  );
}
