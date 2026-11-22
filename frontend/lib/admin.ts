/** Admin helpers: money in rupees <-> paise, dates in India time <-> ISO. */

export const rupees = (paise: number) => (paise / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 });
export const toPaise = (v: string) => Math.round(parseFloat(v.replace(/,/g, "")) * 100);

/** "2027-03-22T21:00" (typed as India time) -> ISO with offset. */
export const fromIst = (local: string) => (local ? `${local}:00+05:30` : null);

/** ISO -> "2027-03-22T21:00" in India time, for a datetime-local input. */
export function toIst(iso: string | null): string {
  if (!iso) return "";
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date(iso)).map((x) => [x.type, x.value]),
  );
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

export const when = (iso: string | null) =>
  iso ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(iso)) : "—";

export const CATEGORIES = [
  "CONCERT", "MUSIC_FESTIVAL", "DJ_EVENT", "CULTURAL", "CELEBRITY", "CORPORATE", "EXHIBITION", "PRODUCT_LAUNCH", "BRAND_ACTIVATION", "PRIVATE_CELEBRATION", "DESTINATION", "OTHER",
];
export const label = (s: string) => s.charAt(0) + s.slice(1).toLowerCase().replace(/_/g, " ");
