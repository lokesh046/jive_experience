"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import { CATEGORIES, fromIst, label, rupees, toIst, toPaise, when } from "@/lib/admin";
import { LineupEditor } from "@/components/admin/LineupEditor";
import { GalleryField } from "@/components/admin/GalleryField";
import { PhotoField } from "@/components/admin/PhotoField";
import { useData } from "@/lib/use-data";
import type { AttendeeRow, Attendance, CategoryAdmin, EventAdmin, Page, ScanRow, StaffAssignment, UserAdmin, VenueFull } from "@/lib/types";

const blank = {
  title: "", slug: "", subtitle: "", description: "", category: "CONCERT", venue_id: "",
  starts_at: "", ends_at: "", sale_starts_at: "", sale_ends_at: "",
  banner_image_url: "", thumbnail_image_url: "", gallery: [] as string[], max_tickets_per_customer: "4",
  requires_attendee_name: false, terms_and_conditions: "", location_url: "", is_featured: false,
};
type Form = typeof blank;

const msgOf = (e: unknown, fallback = "Something went wrong.") => (e instanceof ApiError ? e.message : fallback);

export function EventEditor({ eventId }: { eventId?: string }) {
  const router = useRouter();
  const ev = useData<EventAdmin>(eventId ? `admin/events/${eventId}` : null);
  const venues = useData<Page<VenueFull>>("admin/venues?size=100");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; ok?: boolean } | null>(null);
  // What the form shows: the saved event, with the admin's unsaved edits on top.
  const [edits, setEdits] = useState<Partial<Form>>({});
  const e0 = ev.data;
  const base: Form = e0
    ? {
        title: e0.title, slug: e0.slug, subtitle: e0.subtitle ?? "", description: e0.description ?? "", category: e0.category, venue_id: e0.venue.id,
        starts_at: toIst(e0.starts_at), ends_at: toIst(e0.ends_at), sale_starts_at: toIst(e0.sale_starts_at), sale_ends_at: toIst(e0.sale_ends_at),
        banner_image_url: e0.banner_image_url ?? "", thumbnail_image_url: e0.thumbnail_image_url ?? "", gallery: e0.gallery_image_urls ?? [],
        max_tickets_per_customer: String(e0.max_tickets_per_customer), requires_attendee_name: e0.requires_attendee_name,
        terms_and_conditions: e0.terms_and_conditions ?? "", location_url: e0.location_url ?? "", is_featured: e0.is_featured,
      }
    : blank;
  const f: Form = { ...base, ...edits };

  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setEdits((x) => ({ ...x, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value }));
  const nul = (s: string) => (s.trim() === "" ? null : s.trim());

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setNote(null);
    const body = {
      title: f.title.trim(), subtitle: nul(f.subtitle), description: nul(f.description), category: f.category, venue_id: f.venue_id,
      starts_at: fromIst(f.starts_at), ends_at: fromIst(f.ends_at), sale_starts_at: fromIst(f.sale_starts_at), sale_ends_at: fromIst(f.sale_ends_at),
      banner_image_url: nul(f.banner_image_url), thumbnail_image_url: nul(f.thumbnail_image_url), gallery_image_urls: f.gallery,
      max_tickets_per_customer: Number(f.max_tickets_per_customer), requires_attendee_name: f.requires_attendee_name,
      terms_and_conditions: nul(f.terms_and_conditions), location_url: nul(f.location_url), is_featured: f.is_featured,
    };
    try {
      if (!eventId) {
        const created = await api<EventAdmin>("admin/events", { method: "POST", json: { ...body, slug: nul(f.slug) } });
        router.replace(`/admin/events/${created.id}`);
      } else {
        await api(`admin/events/${eventId}`, { method: "PATCH", json: body });
        setNote({ text: "Saved.", ok: true }); setEdits({}); ev.reload();
      }
    } catch (err) { setNote({ text: msgOf(err, "Could not save the event.") }); }
    finally { setBusy(false); }
  }

  const event = ev.data;
  const editable = !event || (event.status !== "CANCELLED" && event.status !== "COMPLETED");

  return (
    <>
      <p><Link className="link" href="/admin">← All events</Link></p>
      <div className="ad-head" style={{ marginTop: 16 }}>
        <h1>{eventId ? (event?.title ?? "Event") : "New event"}</h1>
        {event && <span className={`status${event.status === "PUBLISHED" ? " live" : ""}`}>{label(event.status)}</span>}
      </div>
      {ev.error && <p className="err" role="alert">{ev.error}</p>}

      {event && <StatusActions event={event} onChange={ev.reload} />}

      <form onSubmit={save}>
        <div className="ad-grid">
          <div className="f wide"><label htmlFor="t">Title</label><input id="t" value={f.title} onChange={set("title")} required maxLength={200} disabled={!editable} /></div>
          <div className="f wide"><label htmlFor="sub">Subtitle</label><input id="sub" value={f.subtitle} onChange={set("subtitle")} maxLength={300} disabled={!editable} /></div>
          {!eventId && <div className="f"><label htmlFor="sl">Web address (optional)</label><input id="sl" value={f.slug} onChange={set("slug")} placeholder="resonance-in-ruin" pattern="[a-z0-9]+(-[a-z0-9]+)*" /></div>}
          <div className="f"><label htmlFor="c">Category</label><select id="c" value={f.category} onChange={set("category")} disabled={!editable}>{CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}</select></div>
          <div className="f"><label htmlFor="v">Venue</label>
            <select id="v" value={f.venue_id} onChange={set("venue_id")} required disabled={!editable}>
              <option value="">Choose a venue</option>
              {venues.data?.items.map((v) => <option key={v.id} value={v.id}>{v.name}, {v.city}</option>)}
            </select>
            {venues.data && venues.data.items.length === 0 && <span className="hint">No venues yet. <Link className="link" href="/admin/venues">Add one</Link>.</span>}
          </div>
          <div className="f wide"><label htmlFor="loc">Location link</label><input id="loc" type="url" value={f.location_url} onChange={set("location_url")} placeholder="https://maps.app.goo.gl/… or https://www.google.com/maps/…" disabled={!editable} />
            <span className="hint">Paste the Google Maps share link for this event. The event page shows a map after the tickets and a button that opens this link. Leave empty to use the venue&apos;s own map link or its address.</span></div>
          <div className="f"><label htmlFor="st">Starts (India time)</label><input id="st" type="datetime-local" value={f.starts_at} onChange={set("starts_at")} required disabled={!editable} /></div>
          <div className="f"><label htmlFor="en">Ends (India time)</label><input id="en" type="datetime-local" value={f.ends_at} onChange={set("ends_at")} disabled={!editable} /></div>
          <div className="f"><label htmlFor="ss">Sales open</label><input id="ss" type="datetime-local" value={f.sale_starts_at} onChange={set("sale_starts_at")} disabled={!editable} /></div>
          <div className="f"><label htmlFor="se">Sales close</label><input id="se" type="datetime-local" value={f.sale_ends_at} onChange={set("sale_ends_at")} disabled={!editable} /></div>
          <div className="f"><label htmlFor="mx">Tickets per person</label><input id="mx" type="number" min={1} max={100} value={f.max_tickets_per_customer} onChange={set("max_tickets_per_customer")} required disabled={!editable} /></div>
          <div className="f chk" style={{ alignSelf: "end" }}><input id="an" type="checkbox" checked={f.requires_attendee_name} onChange={set("requires_attendee_name")} disabled={!editable} /><label htmlFor="an">Ask for each attendee&apos;s name</label></div>
          <PhotoField label="Banner photo" value={f.banner_image_url} onChange={(u) => setEdits((x) => ({ ...x, banner_image_url: u }))} disabled={!editable} hint="Shown at the top of the event page. Wide photos work best." />
          <PhotoField label="Card thumbnail" value={f.thumbnail_image_url} onChange={(u) => setEdits((x) => ({ ...x, thumbnail_image_url: u }))} disabled={!editable} hint="Shown on the homepage and events list. Leave empty to reuse the banner." />
          <GalleryField value={f.gallery} onChange={(g) => setEdits((x) => ({ ...x, gallery: g }))} disabled={!editable} />
          <div className="f wide"><label htmlFor="d">Description</label><textarea id="d" value={f.description} onChange={set("description")} style={{ minHeight: 160 }} disabled={!editable} /><span className="hint">Separate paragraphs with a blank line.</span></div>
          <div className="f wide"><label htmlFor="tc">Terms for this event</label><textarea id="tc" value={f.terms_and_conditions} onChange={set("terms_and_conditions")} disabled={!editable} style={{ minHeight: 160 }} /><span className="hint">One term per line. Each line shows as its own bullet under &quot;Good to know&quot;.</span></div>
          <div className="f chk"><input id="ft" type="checkbox" checked={f.is_featured} onChange={set("is_featured")} disabled={!editable} /><label htmlFor="ft">Show in the homepage banner</label><span className="hint" style={{ marginLeft: 12 }}>Uses this event&apos;s banner photo, title and date. If several are ticked, the soonest shows.</span></div>
        </div>
        {note && <p className={note.ok ? "ok" : "err"} role={note.ok ? "status" : "alert"} style={note.ok ? { marginLeft: 0, marginTop: 20 } : undefined}>{note.text}</p>}
        {editable && <div className="ad-actions"><button className="pill" type="submit" disabled={busy}>{busy ? "Saving…" : eventId ? "Save changes" : "Create event"}</button></div>}
      </form>

      {event && <Categories event={event} onChange={ev.reload} />}
      {event && <LineupEditor event={event} onSaved={ev.reload} />}
      {event && <Staff eventId={event.id} />}
      {event && <AttendanceBlock eventId={event.id} />}
    </>
  );
}

function StatusActions({ event, onChange }: { event: EventAdmin; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [refund, setRefund] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function run(path: string, json?: unknown) {
    setBusy(true); setErr(null);
    try { await api(`admin/events/${event.id}/${path}`, { method: "POST", json: json ?? {} }); setAsking(false); onChange(); }
    catch (e) { setErr(msgOf(e)); }
    finally { setBusy(false); }
  }
  const live = event.status === "PUBLISHED" || event.status === "SOLD_OUT";
  return (
    <div style={{ marginBottom: 32 }}>
      <div className="ad-actions" style={{ marginTop: 0 }}>
        {event.status === "DRAFT" && <button className="pill" type="button" disabled={busy} onClick={() => run("publish")}>Publish</button>}
        {live && <button className="pill ghost" type="button" disabled={busy} onClick={() => run("unpublish")}>Unpublish</button>}
        {event.status !== "CANCELLED" && event.status !== "COMPLETED" && !asking && <button className="pill danger" type="button" onClick={() => setAsking(true)}>Cancel event</button>}
        {event.status === "PUBLISHED" && <Link className="link" href={`/events/${event.slug}`} target="_blank">View public page</Link>}
      </div>
      {event.status === "CANCELLED" && <p className="notice"><span>Cancelled{event.cancellation_reason ? `: ${event.cancellation_reason}` : "."}</span></p>}
      {asking && (
        <div className="drawer" style={{ marginTop: 20 }}>
          <h3>Cancel this event?</h3>
          <p className="small" style={{ margin: "8px 0 20px" }}>Buyers are told it is cancelled. This cannot be undone.</p>
          <div className="f"><label htmlFor="cr">Reason (shown in records)</label><input id="cr" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></div>
          <div className="f chk" style={{ margin: "20px 0" }}><input id="cf" type="checkbox" checked={refund} onChange={(e) => setRefund(e.target.checked)} /><label htmlFor="cf">Refund every confirmed booking in full</label></div>
          <div className="ad-actions" style={{ marginTop: 0 }}>
            <button className="pill danger" type="button" disabled={busy || !reason.trim()} onClick={() => run("cancel", { reason: reason.trim(), refund_bookings: refund })}>Cancel event</button>
            <button className="link" type="button" onClick={() => setAsking(false)}>Keep it</button>
          </div>
        </div>
      )}
      {err && <p className="err" role="alert">{err}</p>}
    </div>
  );
}

function Categories({ event, onChange }: { event: EventAdmin; onChange: () => void }) {
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [c, setC] = useState({ name: "", description: "", price: "", capacity: "", max: "10", active: true });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function open(row: CategoryAdmin | null) {
    setErr(null); setEditing(row ? row.id : "new");
    setC(row ? { name: row.name, description: row.description ?? "", price: String(row.price_paise / 100), capacity: String(row.capacity), max: String(row.max_per_booking), active: row.is_active } : { name: "", description: "", price: "", capacity: "", max: "10", active: true });
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    const body = { name: c.name.trim(), description: c.description.trim() || null, price_paise: toPaise(c.price), capacity: Number(c.capacity), max_per_booking: Number(c.max), is_active: c.active };
    try {
      if (editing === "new") await api(`admin/events/${event.id}/ticket-categories`, { method: "POST", json: body });
      else await api(`admin/ticket-categories/${editing}`, { method: "PATCH", json: body });
      setEditing(null); onChange();
    } catch (x) { setErr(msgOf(x)); }
    finally { setBusy(false); }
  }
  async function remove(row: CategoryAdmin) {
    if (!confirm(`Delete "${row.name}"?`)) return;
    try { await api(`admin/ticket-categories/${row.id}`, { method: "DELETE" }); onChange(); } catch (x) { setErr(msgOf(x)); }
  }

  return (
    <section className="ad-sec" aria-labelledby="cat-h">
      <div className="ad-head" style={{ marginBottom: 8 }}><h2 id="cat-h" style={{ margin: 0 }}>Ticket categories</h2>{!editing && <button className="pill sm" type="button" onClick={() => open(null)}>Add category</button>}</div>
      <div className="tbl">
        <div className="tr th" style={{ gridTemplateColumns: "2fr 1fr 1fr 1fr auto" }}><span>Name</span><span className="num">Price</span><span className="num">Sold / capacity</span><span className="num">Held</span><span /></div>
        {event.ticket_categories.length === 0 && <p className="empty">No categories yet. Add at least one before publishing.</p>}
        {event.ticket_categories.map((row) => (
          <div className="tr" key={row.id} style={{ gridTemplateColumns: "2fr 1fr 1fr 1fr auto" }}>
            <span><span className="name">{row.name}</span>{!row.is_active && <span className="small"> · hidden</span>}</span>
            <span className="num">₹{rupees(row.price_paise)}</span>
            <span className="num">{row.sold_count} / {row.capacity}</span>
            <span className="num">{row.reserved_count}</span>
            <span style={{ display: "flex", gap: 16 }}><button className="link" type="button" onClick={() => open(row)}>Edit</button><button className="link" type="button" onClick={() => remove(row)}>Delete</button></span>
          </div>
        ))}
      </div>
      {editing && (
        <form onSubmit={save} className="drawer" style={{ marginTop: 20 }}>
          <div className="ad-grid">
            <div className="f"><label htmlFor="cn">Name</label><input id="cn" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} required maxLength={120} /></div>
            <div className="f"><label htmlFor="cp">Price (₹)</label><input id="cp" type="number" min={0} step="0.01" value={c.price} onChange={(e) => setC({ ...c, price: e.target.value })} required /></div>
            <div className="f"><label htmlFor="cc">Capacity</label><input id="cc" type="number" min={0} value={c.capacity} onChange={(e) => setC({ ...c, capacity: e.target.value })} required /></div>
            <div className="f"><label htmlFor="cm">Most per booking</label><input id="cm" type="number" min={1} value={c.max} onChange={(e) => setC({ ...c, max: e.target.value })} required /></div>
            <div className="f wide"><label htmlFor="cd">What this ticket includes</label><textarea id="cd" value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} placeholder={"Standing, full access to the main floor\nOne welcome drink\nFast-track entry"} style={{ minHeight: 110 }} /><span className="hint">One item per line. Each line shows with a tick on the event page.</span></div>
            <div className="f chk"><input id="ca" type="checkbox" checked={c.active} onChange={(e) => setC({ ...c, active: e.target.checked })} /><label htmlFor="ca">On sale</label></div>
          </div>
          {err && <p className="err" role="alert">{err}</p>}
          <div className="ad-actions"><button className="pill sm" type="submit" disabled={busy}>{busy ? "Saving…" : "Save category"}</button><button className="link" type="button" onClick={() => setEditing(null)}>Cancel</button></div>
        </form>
      )}
      {!editing && err && <p className="err" role="alert">{err}</p>}
    </section>
  );
}

function Staff({ eventId }: { eventId: string }) {
  const staff = useData<StaffAssignment[]>(`admin/events/${eventId}/staff`);
  const users = useData<Page<UserAdmin>>("users?role=EVENT_STAFF&size=100");
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const assigned = new Set(staff.data?.map((s) => s.user_id));
  const options = users.data?.items.filter((u) => u.status === "ACTIVE" && !assigned.has(u.id)) ?? [];

  async function add() {
    if (!pick) return;
    setErr(null);
    try { await api(`admin/events/${eventId}/staff`, { method: "POST", json: { user_id: pick } }); setPick(""); staff.reload(); } catch (x) { setErr(msgOf(x)); }
  }
  async function remove(userId: string) {
    setErr(null);
    try { await api(`admin/events/${eventId}/staff/${userId}`, { method: "DELETE" }); staff.reload(); } catch (x) { setErr(msgOf(x)); }
  }
  return (
    <section className="ad-sec" aria-labelledby="staff-h">
      <h2 id="staff-h">Gate staff</h2>
      <div className="tbl">
        {staff.data?.length === 0 && <p className="empty">No one is assigned. Staff can only scan events they are assigned to.</p>}
        {staff.data?.map((s) => (
          <div className="tr" key={s.id} style={{ gridTemplateColumns: "1fr auto" }}>
            <span><span className="name">{s.full_name ?? s.email}</span><br /><span className="small">{s.email}</span></span>
            <button className="link" type="button" onClick={() => remove(s.user_id)}>Remove</button>
          </div>
        ))}
      </div>
      <div className="ad-bar" style={{ marginTop: 24 }}>
        <div className="f" style={{ minWidth: 280 }}><label htmlFor="sp">Add staff member</label>
          <select id="sp" value={pick} onChange={(e) => setPick(e.target.value)}><option value="">Choose…</option>{options.map((u) => <option key={u.id} value={u.id}>{u.full_name ?? u.email} · {u.email}</option>)}</select></div>
        <button className="pill sm" type="button" disabled={!pick} onClick={add}>Assign</button>
      </div>
      <p className="hint">Not in the list? <Link className="link" href="/admin/team">Give them staff access</Link> first.</p>
      {err && <p className="err" role="alert">{err}</p>}
    </section>
  );
}

const STATUS_LABEL: Record<string, string> = { ISSUED: "Not yet in", CHECKED_IN: "Checked in", CANCELLED: "Cancelled", REFUNDED: "Refunded" };
const RESULT_LABEL: Record<string, string> = {
  SUCCESS: "Let in", ALREADY_USED: "Already used", WRONG_EVENT: "Wrong event", CANCELLED: "Cancelled ticket", REFUNDED: "Refunded ticket", INVALID: "Not a ticket",
};

function AttendanceBlock({ eventId }: { eventId: string }) {
  const { data } = useData<Attendance>(`admin/events/${eventId}/attendance`);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function download() {
    setBusy(true); setErr(null);
    try {
      const res = await fetch(`/api/admin/events/${eventId}/attendees.csv`, { cache: "no-store" });
      if (!res.ok) throw new Error();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await res.blob());
      a.download = `attendees-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch { setErr("The attendee list could not be downloaded. Please try again."); }
    finally { setBusy(false); }
  }

  if (!data) return null;
  return (
    <section className="ad-sec" aria-labelledby="att-h">
      <div className="ad-head" style={{ marginBottom: 20 }}>
        <h2 id="att-h" style={{ margin: 0 }}>Attendance</h2>
        {data.total > 0 && <button className="pill sm ghost" type="button" onClick={download} disabled={busy}>{busy ? "Preparing…" : "Download attendee list (CSV)"}</button>}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <div className="stat">
        <div><strong>{data.checked_in}</strong><span>Checked in</span></div>
        <div><strong>{data.issued}</strong><span>Not yet in</span></div>
        <div><strong>{data.cancelled + data.refunded}</strong><span>Cancelled or refunded</span></div>
        <div><strong>{data.total}</strong><span>Tickets in total</span></div>
      </div>
      {data.total > 0 && <AttendeeList eventId={eventId} />}
      <ScanLog eventId={eventId} />
    </section>
  );
}

/** Opened on demand, so an event page that nobody scrolls to costs no request. */
function AttendeeList({ eventId }: { eventId: string }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const path = open ? `admin/events/${eventId}/attendees?size=20&page=${page}${status ? `&status=${status}` : ""}${q ? `&search=${encodeURIComponent(q)}` : ""}` : null;
  const list = useData<Page<AttendeeRow>>(path);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;
  const cols = "1.2fr 1.3fr 1.6fr 1fr";
  return (
    <details className="ad-fold" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Who is coming</summary>
      <form className="ad-bar" style={{ flexDirection: "row", marginTop: 16 }} onSubmit={(e) => { e.preventDefault(); setQ(typed.trim()); setPage(1); }}>
        <div className="f"><label htmlFor="as">Search</label><input id="as" value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Name, email, booking or ticket" maxLength={80} /></div>
        <div className="f"><label htmlFor="ast">Status</label>
          <select id="ast" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All</option>{Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <button className="pill sm" type="submit">Search</button>
      </form>
      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 80, marginTop: 16 }} />}
      {list.data && (
        <div className="tbl" role="table" aria-label="Attendees">
          <div className="tr th" style={{ gridTemplateColumns: cols }}><span>Name</span><span>Ticket</span><span>Email</span><span>Status</span></div>
          {list.data.items.length === 0 && <p className="empty">No one matches.</p>}
          {list.data.items.map((a) => (
            <div className="tr" key={a.serial} style={{ gridTemplateColumns: cols }}>
              <span><span className="name">{a.attendee_name || a.customer_name || "—"}</span><br /><span className="small">{a.booking_reference}</span></span>
              <span>{a.ticket_type}<br /><span className="small">{a.serial}</span></span>
              <span style={{ overflowWrap: "anywhere" }}>{a.customer_email}</span>
              <span>{STATUS_LABEL[a.status] ?? a.status}{a.checked_in_at ? <><br /><span className="small">{when(a.checked_in_at)}</span></> : null}</span>
            </div>
          ))}
          {pages > 1 && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {pages} <button type="button" className="link" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></p>}
        </div>
      )}
    </details>
  );
}

function ScanLog({ eventId }: { eventId: string }) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const list = useData<Page<ScanRow>>(open ? `admin/events/${eventId}/scans?size=20&page=${page}` : null);
  const pages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.size)) : 1;
  const cols = "1.3fr 1.1fr 1.4fr 1.2fr";
  return (
    <details className="ad-fold" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Scan log</summary>
      <p className="hint" style={{ marginTop: 12 }}>Every scan at the gate, newest first. Refused scans are listed too: a run of &quot;Wrong event&quot; usually means someone is at the wrong gate.</p>
      {list.error && <p className="err" role="alert">{list.error}</p>}
      {list.loading && <div className="skeleton" style={{ height: 80, marginTop: 16 }} />}
      {list.data && (
        <div className="tbl" role="table" aria-label="Scan log">
          <div className="tr th" style={{ gridTemplateColumns: cols }}><span>When</span><span>Result</span><span>Ticket</span><span>Scanned by</span></div>
          {list.data.items.length === 0 && <p className="empty">Nothing has been scanned yet.</p>}
          {list.data.items.map((s, i) => (
            <div className="tr" key={`${s.scanned_at}-${i}`} style={{ gridTemplateColumns: cols }}>
              <span>{when(s.scanned_at)}</span>
              <span className={s.result === "SUCCESS" ? "scan-ok" : "scan-no"}>{RESULT_LABEL[s.result] ?? s.result}</span>
              <span>{s.serial ? <>{s.ticket_type}<br /><span className="small">{s.serial}</span></> : <span className="small">No matching ticket</span>}</span>
              <span style={{ overflowWrap: "anywhere" }}>{s.staff ?? "—"}{s.device_label ? <><br /><span className="small">{s.device_label}</span></> : null}</span>
            </div>
          ))}
          {pages > 1 && <p className="pager"><button type="button" className="link" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button> Page {page} of {pages} <button type="button" className="link" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</button></p>}
        </div>
      )}
    </details>
  );
}
