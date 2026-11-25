/** Paise (integer) to a display string with Indian digit grouping. */
export function inr(paise: number): string {
  const rupees = paise / 100;
  return "₹" + rupees.toLocaleString("en-IN", { maximumFractionDigits: rupees % 1 ? 2 : 0 });
}

const tz = (zone: string) => ({ timeZone: zone });

export function longDate(iso: string, zone = "Asia/Kolkata"): string {
  return new Intl.DateTimeFormat("en-IN", { ...tz(zone), weekday: "short", day: "numeric", month: "long", year: "numeric" }).format(new Date(iso));
}

export function timeOf(iso: string, zone = "Asia/Kolkata"): string {
  return new Intl.DateTimeFormat("en-IN", { ...tz(zone), hour: "numeric", minute: "2-digit", hour12: true })
    .format(new Date(iso))
    .toUpperCase();
}

export function dayMonth(iso: string, zone = "Asia/Kolkata"): string {
  return new Intl.DateTimeFormat("en-IN", { ...tz(zone), day: "numeric", month: "short" }).format(new Date(iso));
}

export function isPast(iso: string): boolean {
  return new Date(iso).getTime() < Date.now();
}

/** "just now", "5 min ago", "3 h ago", "2 days ago", then a date. */
export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)} day${Math.floor(s / 86400) === 1 ? "" : "s"} ago`;
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" }).format(new Date(iso));
}
