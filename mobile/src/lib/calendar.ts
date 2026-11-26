const DEFAULT_LENGTH_MS = 3 * 60 * 60 * 1000;
const utc = (d: Date) => d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

/** A Google Calendar "add event" link; it opens in the calendar app or the browser. */
export function googleCalendarUrl(e: { title: string; subtitle?: string | null; starts_at: string; ends_at?: string | null; where: string; url: string }): string {
  const start = new Date(e.starts_at);
  const end = e.ends_at && new Date(e.ends_at) > start ? new Date(e.ends_at) : new Date(start.getTime() + DEFAULT_LENGTH_MS);
  const q = new URLSearchParams({
    action: "TEMPLATE", text: e.title, dates: `${utc(start)}/${utc(end)}`,
    details: [e.subtitle, `Tickets and details: ${e.url}`].filter(Boolean).join("\n\n"), location: e.where,
  });
  return `https://calendar.google.com/calendar/render?${q}`;
}
