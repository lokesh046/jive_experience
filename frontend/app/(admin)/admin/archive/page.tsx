"use client";
import { useState } from "react";
import { PhotoField } from "@/components/admin/PhotoField";
import { ApiError, api } from "@/lib/api-client";
import { useData } from "@/lib/use-data";
import type { ArchiveAdmin } from "@/lib/types";

interface Form { id: string | null; caption: string; photo: string; show: boolean }
const BLANK: Form = { id: null, caption: "", photo: "", show: true };
const thumb = (u: string) => u.replace("/upload/", "/upload/f_auto,q_auto,c_fill,w_200,h_250/");

export default function Archive() {
  const list = useData<ArchiveAdmin[]>("admin/archive");
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const rows = list.data ?? [];
  const shown = rows.filter((r) => r.show_on_home).length;

  const fail = (e: unknown, fallback: string) => setMsg(e instanceof ApiError ? e.message : fallback);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    if (!form.photo) return setMsg("Add a photo first.");
    setBusy(true); setMsg(null);
    const body = { caption: form.caption.trim() || null, photo_url: form.photo, show_on_home: form.show };
    try {
      if (form.id) await api(`admin/archive/${form.id}`, { method: "PATCH", json: body });
      else await api("admin/archive", { method: "POST", json: body });
      setForm(null); list.reload();
    } catch (err) { fail(err, "Could not save the photo."); }
    finally { setBusy(false); }
  }
  async function toggle(a: ArchiveAdmin) {
    setMsg(null);
    try { await api(`admin/archive/${a.id}`, { method: "PATCH", json: { show_on_home: !a.show_on_home } }); list.reload(); }
    catch (err) { fail(err, "Could not change the photo."); }
  }
  async function remove(a: ArchiveAdmin) {
    if (!window.confirm("Remove this photo? This cannot be undone.")) return;
    try { await api(`admin/archive/${a.id}`, { method: "DELETE" }); list.reload(); }
    catch (err) { fail(err, "Could not remove the photo."); }
  }
  async function move(i: number, d: number) {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const ids = rows.map((r) => r.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setMsg(null);
    try { await api("admin/archive/order", { method: "PUT", json: { ids } }); list.reload(); }
    catch (err) { fail(err, "Could not change the order."); }
  }

  return (
    <>
      <div className="ad-head"><h1>Archive</h1>{!form && <button className="pill" type="button" onClick={() => { setForm(BLANK); setMsg(null); }}>Add photo</button>}</div>
      <p className="hint">Photos of past nights, shown under &ldquo;From the archive&rdquo; on the homepage in this order. The homepage shows up to 6; three or six look best. If none are shown, it uses the sample photos.</p>
      {list.data && rows.length > 0 && <p className="hint" style={{ marginTop: 6 }}>{shown} shown on the homepage{shown > 6 ? ` (only the first 6 appear)` : ""}.</p>}
      {msg && !form && <p className="err" role="alert">{msg}</p>}

      {form && (
        <form onSubmit={save} className="ad-sec" style={{ borderTop: 0, marginTop: 20, paddingTop: 0 }}>
          <h2>{form.id ? "Edit photo" : "New photo"}</h2>
          <div className="ad-grid">
            <PhotoField label="Photo" value={form.photo} onChange={(photo) => setForm((f) => (f ? { ...f, photo } : f))} hint="Portrait photos fit best (4 by 5)." />
            <div className="f"><label htmlFor="ac">Caption</label><input id="ac" value={form.caption} onChange={(e) => setForm({ ...form, caption: e.target.value })} maxLength={200} placeholder="Bandra Vinyl Salon, March 2027" /></div>
            <div className="f wide chk"><label><input type="checkbox" checked={form.show} onChange={(e) => setForm({ ...form, show: e.target.checked })} /> Show on the homepage</label></div>
          </div>
          {msg && <p className="err" role="alert">{msg}</p>}
          <div className="ad-actions"><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : "Save photo"}</button><button className="link" type="button" onClick={() => { setForm(null); setMsg(null); }}>Cancel</button></div>
        </form>
      )}

      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && rows.length === 0 && !form && <p className="empty">No photos yet. Add one to replace the sample photos on the homepage.</p>}
      <ul className="ar-list">
        {rows.map((a, i) => (
          <li key={a.id} className={`ar-row${a.show_on_home ? "" : " off"}`}>
            <div className="ar-pic">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={thumb(a.photo_url)} alt="" width={72} height={90} />
            </div>
            <div className="ar-main">
              <b>{a.caption || "No caption"}{!a.show_on_home && <span className="tag">Hidden</span>}</b>
            </div>
            <div className="ar-ctl">
              <span className="mv">
                <button type="button" aria-label={`Move photo ${i + 1} earlier`} disabled={i === 0} onClick={() => void move(i, -1)}>↑</button>
                <button type="button" aria-label={`Move photo ${i + 1} later`} disabled={i === rows.length - 1} onClick={() => void move(i, 1)}>↓</button>
              </span>
              <button className="link" type="button" onClick={() => void toggle(a)}>{a.show_on_home ? "Hide" : "Show"}</button>
              <button className="link" type="button" onClick={() => { setForm({ id: a.id, caption: a.caption ?? "", photo: a.photo_url, show: a.show_on_home }); setMsg(null); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button>
              <button className="link" type="button" onClick={() => void remove(a)}>Remove</button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
