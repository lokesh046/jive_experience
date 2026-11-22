"use client";
import { useRef, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { fromIst, toIst } from "@/lib/admin";
import { photoProblem, uploadPhoto } from "@/lib/upload";
import type { EventAdmin } from "@/lib/types";

interface Row { key: string; name: string; role: string; photo: string; time: string }
const MAX = 20;
const thumb = (u: string) => u.replace("/upload/", "/upload/f_auto,q_auto,c_fill,g_face,w_160,h_200/");

/** Who is playing, in running order. Saved as one list, so what you see is what the event page shows. */
export function LineupEditor({ event, onSaved }: { event: EventAdmin; onSaved: () => void }) {
  const counter = useRef(0);
  const newKey = () => `r${counter.current++}`;
  // What the editor shows: the saved lineup, with the admin's unsaved edits on top.
  const saved: Row[] = event.performers.map((p) => ({ key: p.id, name: p.name, role: p.role ?? "", photo: p.photo_url ?? "", time: toIst(p.performs_at) }));
  const [edited, setEdited] = useState<Row[] | null>(null);
  const rows = edited ?? saved;
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [note, setNote] = useState<{ text: string; ok?: boolean } | null>(null);
  const editable = event.status !== "CANCELLED" && event.status !== "COMPLETED";

  const update = (next: Row[]) => { setEdited(next); setNote(null); };
  const patch = (key: string, part: Partial<Row>) => update(rows.map((r) => (r.key === key ? { ...r, ...part } : r)));
  const move = (i: number, d: number) => {
    const j = i + d;
    if (j < 0 || j >= rows.length) return;
    const next = [...rows]; [next[i], next[j]] = [next[j], next[i]];
    update(next);
  };

  async function pick(key: string, file: File | undefined) {
    if (!file) return;
    const bad = photoProblem(file);
    if (bad) return setNote({ text: bad });
    setUploading(key);
    try { patch(key, { photo: await uploadPhoto(file) }); }
    catch (e) { setNote({ text: e instanceof Error ? e.message : "The upload did not go through." }); }
    finally { setUploading(null); }
  }

  async function save() {
    if (rows.some((r) => !r.name.trim())) return setNote({ text: "Every performer needs a name." });
    setBusy(true); setNote(null);
    try {
      await api(`admin/events/${event.id}/lineup`, {
        method: "PUT",
        json: { performers: rows.map((r) => ({ name: r.name.trim(), role: r.role.trim() || null, photo_url: r.photo || null, performs_at: fromIst(r.time) })) },
      });
      setEdited(null);
      setNote({ text: "Lineup saved.", ok: true });
      onSaved();
    } catch (e) {
      setNote({ text: e instanceof ApiError ? e.message : "Something went wrong." });
    } finally { setBusy(false); }
  }

  return (
    <section className="section" aria-labelledby="lineup-h">
      <div className="ad-head" style={{ marginBottom: 8 }}>
        <h2 id="lineup-h" style={{ margin: 0 }}>Lineup</h2>
        {editable && rows.length < MAX && <button className="pill sm" type="button" onClick={() => update([...rows, { key: newKey(), name: "", role: "", photo: "", time: "" }])}>Add performer</button>}
      </div>
      <p className="hint" style={{ marginBottom: 20 }}>Shown on the event page in this order. Set times are India time.</p>
      {rows.length === 0 && <p className="empty">No performers yet. The event page shows no lineup until you add some.</p>}
      <ol className="lu-edit">
        {rows.map((r, i) => (
          <li key={r.key}>
            <div className="lu-pic">
              {r.photo
                // eslint-disable-next-line @next/next/no-img-element
                ? <img src={thumb(r.photo)} alt="" width={80} height={100} />
                : <span aria-hidden="true">{r.name.trim().charAt(0).toUpperCase() || "?"}</span>}
              {editable && (
                <label className="link">
                  {uploading === r.key ? "Uploading…" : r.photo ? "Change" : "Add photo"}
                  <input type="file" accept="image/jpeg,image/png,image/webp" hidden disabled={uploading !== null} onChange={(e) => { void pick(r.key, e.target.files?.[0]); e.target.value = ""; }} />
                </label>
              )}
            </div>
            <div className="lu-fields">
              <div className="f"><label htmlFor={`n-${r.key}`}>Name</label><input id={`n-${r.key}`} value={r.name} maxLength={120} onChange={(e) => patch(r.key, { name: e.target.value })} disabled={!editable} /></div>
              <div className="f"><label htmlFor={`t-${r.key}`}>Goes on (optional)</label><input id={`t-${r.key}`} type="datetime-local" value={r.time} onChange={(e) => patch(r.key, { time: e.target.value })} disabled={!editable} /></div>
              <div className="f wide"><label htmlFor={`r-${r.key}`}>Short line</label><input id={`r-${r.key}`} value={r.role} maxLength={200} placeholder="Solo cello and vocals" onChange={(e) => patch(r.key, { role: e.target.value })} disabled={!editable} /></div>
            </div>
            {editable && (
              <div className="lu-ctl">
                <button type="button" aria-label={`Move ${r.name || "performer"} earlier`} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                <button type="button" aria-label={`Move ${r.name || "performer"} later`} disabled={i === rows.length - 1} onClick={() => move(i, 1)}>↓</button>
                <button type="button" aria-label={`Remove ${r.name || "performer"}`} onClick={() => update(rows.filter((x) => x.key !== r.key))}>×</button>
              </div>
            )}
          </li>
        ))}
      </ol>
      {note && <p className={note.ok ? "ok" : "err"} role={note.ok ? "status" : "alert"} style={note.ok ? { marginLeft: 0 } : undefined}>{note.text}</p>}
      {editable && edited && <div className="ad-actions"><button className="pill" type="button" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save lineup"}</button></div>}
    </section>
  );
}
