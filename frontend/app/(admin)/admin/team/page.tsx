"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { label, when } from "@/lib/admin";
import { useData } from "@/lib/use-data";
import type { Page, UserAdmin } from "@/lib/types";

const ROLES = ["", "ADMIN", "EVENT_STAFF", "CUSTOMER"];

export default function Team() {
  const [role, setRole] = useState("");
  const [page, setPage] = useState(1);
  const list = useData<Page<UserAdmin>>(`users?size=25&page=${page}${role ? `&role=${role}` : ""}`);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [grant, setGrant] = useState("EVENT_STAFF");
  const [msg, setMsg] = useState<{ text: string; ok?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      await api("users/staff", { method: "POST", json: { email: email.trim(), full_name: name.trim(), role: grant } });
      setMsg({ text: `Done. ${email.trim()} gets access the next time they sign in with Google.`, ok: true });
      setEmail(""); setName(""); list.reload();
    } catch (err) { setMsg({ text: err instanceof ApiError ? err.message : "Could not add that person." }); }
    finally { setBusy(false); }
  }
  async function setStatus(u: UserAdmin, status: "ACTIVE" | "SUSPENDED") {
    if (status === "SUSPENDED" && !confirm(`Suspend ${u.email}? They are signed out straight away.`)) return;
    try { await api(`users/${u.id}/status`, { method: "PATCH", json: { status } }); list.reload(); }
    catch (err) { setMsg({ text: err instanceof ApiError ? err.message : "Could not change that account." }); }
  }
  const cols = "2fr 1fr 1fr 1.3fr auto";

  return (
    <>
      <div className="ad-head"><h1>Team</h1></div>

      <form onSubmit={add} aria-labelledby="give">
        <h2 id="give" style={{ fontSize: 26, marginBottom: 8 }}>Give someone access</h2>
        <p className="small" style={{ marginBottom: 20 }}>They sign in with Google as usual; the role is theirs the next time they do. There are no passwords or invite links.</p>
        <div className="ad-bar" style={{ flexDirection: "row" }}>
          <div className="f" style={{ minWidth: 260 }}><label htmlFor="e">Google email</label><input id="e" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
          <div className="f"><label htmlFor="n">Name</label><input id="n" value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} /></div>
          <div className="f"><label htmlFor="g">Role</label><select id="g" value={grant} onChange={(e) => setGrant(e.target.value)}><option value="EVENT_STAFF">Gate staff</option><option value="ADMIN">Administrator</option></select></div>
          <button className="pill sm" type="submit" disabled={busy}>{busy ? "Adding…" : "Give access"}</button>
        </div>
        {msg && <p className={msg.ok ? "ok" : "err"} role={msg.ok ? "status" : "alert"} style={msg.ok ? { marginLeft: 0 } : undefined}>{msg.text}</p>}
      </form>

      <section className="ad-sec">
        <div className="ad-head" style={{ marginBottom: 0 }}>
          <h2 style={{ margin: 0 }}>Accounts</h2>
          <div className="f"><label htmlFor="rf">Show</label><select id="rf" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>{ROLES.map((r) => <option key={r} value={r}>{r ? label(r) : "Everyone"}</option>)}</select></div>
        </div>
        {list.error && <p className="err" role="alert">{list.error}</p>}
        {list.data && (
          <div className="tbl" role="table" aria-label="Accounts">
            <div className="tr th" style={{ gridTemplateColumns: cols }}><span>Account</span><span>Role</span><span>Status</span><span>Last sign-in</span><span /></div>
            {list.data.items.map((u) => (
              <div className="tr" key={u.id} style={{ gridTemplateColumns: cols }}>
                <span><span className="name">{u.full_name ?? u.email}</span><br /><span className="small">{u.email}</span></span>
                <span>{label(u.role)}</span><span className="status">{label(u.status)}</span><span className="small">{when(u.last_login_at)}</span>
                {u.status === "ACTIVE"
                  ? <button className="link" type="button" onClick={() => setStatus(u, "SUSPENDED")}>Suspend</button>
                  : <button className="link" type="button" onClick={() => setStatus(u, "ACTIVE")}>Reactivate</button>}
              </div>
            ))}
          </div>
        )}
        {list.data && pages > 1 && (
          <div className="ad-actions">
            <button className="pill sm ghost" type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="small">Page {page} of {pages}</span>
            <button className="pill sm ghost" type="button" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </section>
    </>
  );
}
