"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api-client";
import type { AssignedEvent, Attendance, ScanResponse, ScanResult } from "@/lib/types";

const HEADLINE: Record<ScanResult, string> = {
  SUCCESS: "Let them in",
  ALREADY_USED: "Already used",
  WRONG_EVENT: "Wrong event",
  CANCELLED: "Cancelled",
  REFUNDED: "Refunded",
  INVALID: "Not recognised",
  NOT_ASSIGNED: "Not your event",
  EXPIRED: "Event is over",
};

const timeOf = (iso: string) => new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso)).toUpperCase();
const STORE = "jive_scan_event";

/** The API words its messages for logs, with ISO timestamps. At the gate they read as a clock time. */
const readable = (msg: string) =>
  msg.replace(/\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})/g, (iso) => timeOf(iso)).replace(/\.(?=\s|$)/, ".");

type Detector = { detect: (src: CanvasImageSource) => Promise<{ rawValue: string }[]> };

export function Scanner() {
  const [events, setEvents] = useState<AssignedEvent[] | null>(null);
  const [eventId, setEventId] = useState<string | null>(null);
  const [result, setResult] = useState<ScanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [camera, setCamera] = useState<"starting" | "on" | "off">("starting");
  const [attendance, setAttendance] = useState<Attendance | null>(null);
  const [manual, setManual] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const busy = useRef(false);
  const last = useRef({ code: "", at: 0 });

  useEffect(() => {
    api<AssignedEvent[]>("scanner/events")
      .then((list) => {
        setEvents(list);
        const saved = localStorage.getItem(STORE);
        setEventId(list.find((e) => e.event_id === saved)?.event_id ?? (list.length === 1 ? list[0].event_id : null));
      })
      .catch((e) => { setEvents([]); setError(e instanceof ApiError ? e.message : "Could not load your events."); });
  }, []);

  const loadAttendance = useCallback(async (id: string) => {
    try { setAttendance(await api<Attendance>(`scanner/events/${id}/attendance`)); } catch {}
  }, []);
  useEffect(() => {
    if (!eventId) return;
    const load = () => api<Attendance>(`scanner/events/${eventId}/attendance`).then(setAttendance).catch(() => {});
    load();
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [eventId]);

  const submit = useCallback(async (code: string) => {
    if (!eventId || busy.current) return;
    const now = Date.now();
    // The camera sees the same code many times a second: ignore repeats for a moment.
    if (code === last.current.code && now - last.current.at < 3000) return;
    last.current = { code, at: now };
    busy.current = true;
    try {
      const r = await api<ScanResponse>("scanner/scan", { method: "POST", json: { qr_token: code, event_id: eventId, device_label: `web ${navigator.platform}`.slice(0, 120) } });
      navigator.vibrate?.(r.ok ? 60 : [200, 100, 200]);
      setResult(r);
      void loadAttendance(eventId);
    } catch (e) {
      busy.current = false;
      setError(e instanceof ApiError ? e.message : "Could not reach the server. Check the connection and scan again.");
    }
  }, [eventId, loadAttendance]);

  const dismiss = useCallback(() => { setResult(null); setError(null); busy.current = false; }, []);

  // A valid entry moves on by itself so the queue keeps flowing; every refusal waits for a tap.
  useEffect(() => {
    if (result?.ok) { const t = setTimeout(dismiss, 1800); return () => clearTimeout(t); }
  }, [result, dismiss]);

  // Camera + decoding. BarcodeDetector where the browser has it, jsQR everywhere else.
  useEffect(() => {
    if (!eventId || result) return;
    let stopped = false;
    let stream: MediaStream | null = null;
    let raf = 0;
    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } }, audio: false });
        if (stopped) return stream.getTracks().forEach((t) => t.stop());
        const el = video.current!;
        el.srcObject = stream;
        await el.play();
        setCamera("on");

        const BD = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
        const native = BD ? new BD({ formats: ["qr_code"] }) : null;
        const jsQR = native ? null : (await import("jsqr")).default;
        const canvas = document.createElement("canvas");
        const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
        let t0 = 0;

        const tick = async (t: number) => {
          if (stopped) return;
          if (t - t0 > 130 && el.readyState >= 2 && !busy.current) {
            t0 = t;
            try {
              if (native) {
                const found = await native.detect(el);
                if (found[0]?.rawValue) void submit(found[0].rawValue);
              } else if (jsQR) {
                const w = Math.min(640, el.videoWidth), h = Math.round((w / el.videoWidth) * el.videoHeight);
                canvas.width = w; canvas.height = h;
                ctx.drawImage(el, 0, 0, w, h);
                const hit = jsQR(ctx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" });
                if (hit?.data) void submit(hit.data);
              }
            } catch {}
          }
          raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      } catch {
        if (!stopped) setCamera("off");
      }
    })();
    return () => { stopped = true; cancelAnimationFrame(raf); stream?.getTracks().forEach((t) => t.stop()); };
  }, [eventId, result, submit]);

  if (events === null) return <div className="sc-pad"><div className="skeleton" style={{ height: 48 }} /></div>;

  if (events.length === 0) {
    return (
      <div className="sc-pad">
        <h1 className="sc-h">No events to scan</h1>
        <p style={{ marginTop: 12 }}>{error ?? "You are not assigned to any event. Ask an administrator to add you."}</p>
      </div>
    );
  }

  if (!eventId) {
    return (
      <div className="sc-pad">
        <h1 className="sc-h">Choose an event</h1>
        <p style={{ margin: "12px 0 28px" }}>Only events you are assigned to are listed.</p>
        {events.map((e) => (
          <button key={e.event_id} type="button" className="sc-event" onClick={() => { localStorage.setItem(STORE, e.event_id); setEventId(e.event_id); }}>
            <b>{e.title}</b>
            <span>{e.venue_name}, {e.city} · {new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }).format(new Date(e.starts_at))}</span>
          </button>
        ))}
      </div>
    );
  }

  const event = events.find((e) => e.event_id === eventId)!;
  const expected = attendance ? attendance.total - attendance.cancelled - attendance.refunded : null;

  return (
    <div className="sc-app">
      <div className="sc-top">
        <div>
          <b>{event.title}</b>
          <small>{event.venue_name}</small>
        </div>
        <div className="sc-count" aria-live="polite">{attendance ? attendance.checked_in : "–"}<small>{expected !== null ? `of ${expected} in` : "in"}</small></div>
      </div>

      <div className="sc-view">
        <div className="sc-frame">
          <video ref={video} playsInline muted className="sc-video" aria-label="Camera" />
          <i /><i /><i /><i />
          {camera !== "on" && <div className="sc-hint">{camera === "off" ? "The camera is not available. Allow camera access, or type the code below." : "Starting the camera…"}</div>}
        </div>
      </div>

      <div className="sc-bottom">
        {error && !result && <p className="sc-err" role="alert">{error}<button type="button" className="link" onClick={dismiss}>Dismiss</button></p>}
        <details className="sc-manual">
          <summary>Type a code instead</summary>
          <form onSubmit={(e) => { e.preventDefault(); if (manual.trim()) { void submit(manual.trim()); setManual(""); } }}>
            <input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Ticket code" autoCapitalize="off" autoCorrect="off" spellCheck={false} aria-label="Ticket code" />
            <button className="pill sm" type="submit">Check</button>
          </form>
        </details>
        {events.length > 1 && <button type="button" className="pill ghost full" onClick={() => { localStorage.removeItem(STORE); setEventId(null); }}>Change event</button>}
      </div>

      {result && (
        <button type="button" className={`sc-res ${result.ok ? "ok" : "no"}`} onClick={dismiss} aria-live="assertive">
          <svg className="ico" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10.5" />
            {result.ok ? <path d="m7.5 12.5 3 3 6-7" /> : <path d="m8.5 8.5 7 7m0-7-7 7" />}
          </svg>
          <h2>{HEADLINE[result.result] ?? result.result}</h2>
          <p className="msg">{readable(result.message)}</p>
          <dl>
            {result.ticket_category && <div><dt>Category</dt><dd>{result.ticket_category}</dd></div>}
            {result.ticket_serial && <div><dt>Ticket</dt><dd>{result.ticket_serial}</dd></div>}
            {result.attendee_name && <div><dt>Name</dt><dd>{result.attendee_name}</dd></div>}
            {result.checked_in_at && <div><dt>{result.ok ? "Scanned" : "First scanned"}</dt><dd>{timeOf(result.checked_in_at)}</dd></div>}
          </dl>
          <span className="pill">{result.ok ? "Scan next" : "Dismiss"}</span>
        </button>
      )}
    </div>
  );
}
