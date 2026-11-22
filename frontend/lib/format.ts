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
