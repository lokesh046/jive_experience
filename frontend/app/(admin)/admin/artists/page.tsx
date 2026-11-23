"use client";
import { useState } from "react";
import { PhotoField } from "@/components/admin/PhotoField";
import { ApiError, api } from "@/lib/api-client";
import { useData } from "@/lib/use-data";
import type { ArtistAdmin } from "@/lib/types";

interface Form { id: string | null; name: string; note: string; photo: string; show: boolean }
const BLANK: Form = { id: null, name: "", note: "", photo: "", show: true };
const thumb = (u: string) => u.replace("/upload/", "/upload/f_auto,q_auto,c_fill,g_face,w_160,h_200/");

export default function Artists() {
  const list = useData<ArtistAdmin[]>("admin/artists");
  const [form, setForm] = useState<Form | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const rows = list.data ?? [];

  const fail = (e: unknown, fallback: string) => setMsg(e instanceof ApiError ? e.message : fallback);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true); setMsg(null);
    const body = { name: form.name.trim(), note: form.note.trim() || null, photo_url: form.photo || null, show_on_home: form.show };
    try {
      if (form.id) await api(`admin/artists/${form.id}`, { method: "PATCH", json: body });
      else await api("admin/artists", { method: "POST", json: body });
      setForm(null); list.reload();
    } catch (err) { fail(err, "Could not save the artist."); }
    finally { setBusy(false); }
  }
  async function toggle(a: ArtistAdmin) {
    setMsg(null);
    try { await api(`admin/artists/${a.id}`, { method: "PATCH", json: { show_on_home: !a.show_on_home } }); list.reload(); }
    catch (err) { fail(err, "Could not change the artist."); }
  }
  async function remove(a: ArtistAdmin) {
    if (!window.confirm(`Remove ${a.name}? This cannot be undone. Lineups that already include them keep their copy.`)) return;
    try { await api(`admin/artists/${a.id}`, { method: "DELETE" }); list.reload(); }
    catch (err) { fail(err, "Could not remove the artist."); }
  }
  async function move(i: number, d: number) {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const ids = rows.map((r) => r.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    setMsg(null);
    try { await api("admin/artists/order", { method: "PUT", json: { ids } }); list.reload(); }
    catch (err) { fail(err, "Could not change the order."); }
  }

  return (
    <>
      <div className="ad-head"><h1>Artists</h1>{!form && <button className="pill" type="button" onClick={() => { setForm(BLANK); setMsg(null); }}>Add artist</button>}</div>
      <p className="hint">The artists shown on the homepage, in this order. Hide someone to keep them here without showing them. If no artist is shown, the homepage uses performers from upcoming events.</p>
      {msg && !form && <p className="err" role="alert">{msg}</p>}

      {form && (
        <form onSubmit={save} className="ad-sec" style={{ borderTop: 0, marginTop: 20, paddingTop: 0 }}>
          <h2>{form.id ? "Edit artist" : "New artist"}</h2>
          <div className="ad-grid">
            <div className="f"><label htmlFor="an">Name</label><input id="an" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={120} /></div>
            <div className="f"><label htmlFor="ar">Short line</label><input id="ar" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} maxLength={200} placeholder="Solo cello and vocals" /></div>
            <PhotoField label="Photo" value={form.photo} onChange={(photo) => setForm((f) => (f ? { ...f, photo } : f))} hint="A portrait works best. The homepage shows it in black and white." />
            <div className="f wide chk"><label><input type="checkbox" checked={form.show} onChange={(e) => setForm({ ...form, show: e.target.checked })} /> Show on the homepage</label></div>
          </div>
          {msg && <p className="err" role="alert">{msg}</p>}
          <div className="ad-actions"><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : "Save artist"}</button><button className="link" type="button" onClick={() => { setForm(null); setMsg(null); }}>Cancel</button></div>
        </form>
      )}

      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 120, marginTop: 24 }} />}
      {list.data && rows.length === 0 && !form && <p className="empty">No artists yet. Add one to show them on the homepage.</p>}
      <ul className="ar-list">
        {rows.map((a, i) => (
          <li key={a.id} className={`ar-row${a.show_on_home ? "" : " off"}`}>
            <div className="ar-pic">
              {a.photo_url
                // eslint-disable-next-line @next/next/no-img-element
                ? <img src={thumb(a.photo_url)} alt="" width={72} height={90} />
                : <span aria-hidden="true">{a.name.charAt(0).toUpperCase()}</span>}
            </div>
            <div className="ar-main">
              <b>{a.name}{!a.show_on_home && <span className="tag">Hidden</span>}</b>
              {a.note && <p>{a.note}</p>}
              {!a.photo_url && <p className="hint">No photo: the homepage skips artists without one.</p>}
            </div>
            <div className="ar-ctl">
              <span className="mv">
                <button type="button" aria-label={`Move ${a.name} earlier`} disabled={i === 0} onClick={() => void move(i, -1)}>↑</button>
                <button type="button" aria-label={`Move ${a.name} later`} disabled={i === rows.length - 1} onClick={() => void move(i, 1)}>↓</button>
              </span>
              <button className="link" type="button" onClick={() => void toggle(a)}>{a.show_on_home ? "Hide" : "Show"}</button>
              <button className="link" type="button" onClick={() => { setForm({ id: a.id, name: a.name, note: a.note ?? "", photo: a.photo_url ?? "", show: a.show_on_home }); setMsg(null); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Edit</button>
              <button className="link" type="button" onClick={() => void remove(a)}>Remove</button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
