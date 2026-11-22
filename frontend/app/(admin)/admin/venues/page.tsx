"use client";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { GalleryField } from "@/components/admin/GalleryField";
import { useData } from "@/lib/use-data";
import type { Page, VenueFull } from "@/lib/types";

const EMPTY = { name: "", address_line1: "", city: "", state: "", postal_code: "", directions: "", map_url: "", description: "", benefits: "" };

export default function Venues() {
  const { data, error, reload } = useData<Page<VenueFull>>("admin/venues?size=100");
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [photos, setPhotos] = useState<string[]>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  function open(v: VenueFull | null) {
    setMsg(null);
    setEditing(v ? v.id : "new");
    setForm(v ? { name: v.name, address_line1: v.address_line1, city: v.city, state: v.state ?? "", postal_code: v.postal_code ?? "", directions: v.directions ?? "", map_url: v.map_url ?? "", description: v.description ?? "", benefits: (v.benefits ?? []).join("\n") } : EMPTY);
    setPhotos(v?.image_urls ?? []);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const { benefits, ...text } = form;
    const body = {
      ...Object.fromEntries(Object.entries(text).map(([k, v]) => [k, v.trim() === "" ? (k === "name" || k === "address_line1" || k === "city" ? v.trim() : null) : v.trim()])),
      benefits: benefits.split(/\r?\n/).map((l) => l.trim()).filter(Boolean),
      image_urls: photos,
    };
    try {
      if (editing === "new") await api("admin/venues", { method: "POST", json: body });
      else await api(`admin/venues/${editing}`, { method: "PATCH", json: body });
      setEditing(null); reload();
    } catch (err) { setMsg(err instanceof ApiError ? err.message : "Could not save the venue."); }
    finally { setBusy(false); }
  }

  return (
    <>
      <div className="ad-head"><h1>Venues</h1>{!editing && <button className="pill" type="button" onClick={() => open(null)}>New venue</button>}</div>
      {error && <p className="err" role="alert">{error}</p>}

      {editing && (
        <form onSubmit={save} className="ad-sec" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
          <h2>{editing === "new" ? "New venue" : "Edit venue"}</h2>
          <div className="ad-grid">
            <div className="f"><label htmlFor="vn">Name</label><input id="vn" value={form.name} onChange={set("name")} required maxLength={200} /></div>
            <div className="f"><label htmlFor="vc">City</label><input id="vc" value={form.city} onChange={set("city")} required maxLength={100} /></div>
            <div className="f wide"><label htmlFor="va">Address</label><input id="va" value={form.address_line1} onChange={set("address_line1")} required maxLength={200} /></div>
            <div className="f"><label htmlFor="vs">State</label><input id="vs" value={form.state} onChange={set("state")} maxLength={100} /></div>
            <div className="f"><label htmlFor="vp">Postal code</label><input id="vp" value={form.postal_code} onChange={set("postal_code")} maxLength={20} /></div>
            <div className="f wide"><label htmlFor="vm">Map link</label><input id="vm" type="url" value={form.map_url} onChange={set("map_url")} placeholder="https://maps.google.com/…" /></div>
            <div className="f wide"><label htmlFor="vd">Directions</label><textarea id="vd" value={form.directions} onChange={set("directions")} /></div>
            <div className="f wide"><label htmlFor="vx">About the venue</label><textarea id="vx" value={form.description} onChange={set("description")} maxLength={4000} style={{ minHeight: 140 }} placeholder="A restored mill hall with brick walls and a small stage…" /><span className="hint">Shown on the event page under &quot;The venue&quot;. Separate paragraphs with a blank line.</span></div>
            <GalleryField label="Venue photos" value={photos} onChange={setPhotos} max={8} hint="Photos of the place itself. They show on the event page in this order." />
            <div className="f wide"><label htmlFor="vb">What the venue offers</label><textarea id="vb" value={form.benefits} onChange={set("benefits")} style={{ minHeight: 140 }} placeholder={"Free parking\nStep-free access\nFull bar and kitchen"} /><span className="hint">One benefit per line, up to 12. Each shows with a tick on the event page.</span></div>
          </div>
          {msg && <p className="err" role="alert">{msg}</p>}
          <div className="ad-actions"><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : "Save venue"}</button><button className="link" type="button" onClick={() => setEditing(null)}>Cancel</button></div>
        </form>
      )}

      {data && (
        <div className="tbl" role="table" aria-label="Venues">
          <div className="tr th" style={{ gridTemplateColumns: "2fr 1.5fr auto" }}><span>Venue</span><span>City</span><span /></div>
          {data.items.length === 0 && <p className="empty">No venues yet. Add one before creating an event.</p>}
          {data.items.map((v) => (
            <div className="tr" key={v.id} style={{ gridTemplateColumns: "2fr 1.5fr auto" }}>
              <span><span className="name">{v.name}</span><br /><span className="small">{v.address_line1}</span></span>
              <span>{v.city}{v.state ? `, ${v.state}` : ""}</span>
              <button className="link" type="button" onClick={() => open(v)}>Edit</button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
