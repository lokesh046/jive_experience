/** "Add to calendar": a Google Calendar link and a standard .ics file for Apple, Outlook and the rest. */

export interface CalendarEvent {
  id: string;
  slug: string;
  title: string;
  subtitle?: string | null;
  starts_at: string;
  ends_at?: string | null;
  /** Where it is, as one line. */
  where: string;
  /** The event page. */
  url: string;
}

const DEFAULT_LENGTH_MS = 3 * 60 * 60 * 1000; // when an event has no end time

const range = (e: CalendarEvent) => {
  const start = new Date(e.starts_at);
  const end = e.ends_at ? new Date(e.ends_at) : new Date(start.getTime() + DEFAULT_LENGTH_MS);
  return { start, end: end > start ? end : new Date(start.getTime() + DEFAULT_LENGTH_MS) };
};

/** 20261221T104700Z */
const utc = (d: Date) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

const note = (e: CalendarEvent) => [e.subtitle, `Tickets and details: ${e.url}`].filter(Boolean).join("\n\n");

export function googleCalendarUrl(e: CalendarEvent): string {
  const { start, end } = range(e);
  const q = new URLSearchParams({ action: "TEMPLATE", text: e.title, dates: `${utc(start)}/${utc(end)}`, details: note(e), location: e.where });
  return `https://calendar.google.com/calendar/render?${q}`;
}

/** RFC 5545 text escaping. */
const esc = (t: string) => t.replace(/\\/g, "\\\\").replace(/;/g, "\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

/** Lines longer than 75 bytes are folded onto continuation lines, never in the middle of a character. */
function fold(line: string): string[] {
  const enc = new TextEncoder();
  const out: string[] = [];
  let cur = "";
  let bytes = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (bytes + n > (out.length ? 74 : 75)) {
      out.push(cur);
      cur = "";
      bytes = 0;
    }
    cur += ch;
    bytes += n;
  }
  out.push(cur);
  return out.map((l, i) => (i ? ` ${l}` : l));
}

export function icsFor(e: CalendarEvent, now = new Date()): string {
  const { start, end } = range(e);
  const host = new URL(e.url).hostname;
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//JIVE//Events//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${e.id}@${host}`,
    `DTSTAMP:${utc(now)}`,
    `DTSTART:${utc(start)}`,
    `DTEND:${utc(end)}`,
    `SUMMARY:${esc(e.title)}`,
    `LOCATION:${esc(e.where)}`,
    `DESCRIPTION:${esc(note(e))}`,
    `URL:${e.url}`,
    "BEGIN:VALARM",
    "ACTION:DISPLAY",
    `DESCRIPTION:${esc(`${e.title} starts in 2 hours`)}`,
    "TRIGGER:-PT2H",
    "END:VALARM",
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  return lines.flatMap(fold).join("\r\n") + "\r\n";
}
