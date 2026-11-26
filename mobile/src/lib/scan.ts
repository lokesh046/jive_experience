import { timeOf } from "./format";
import type { AssignedEvent, ScanResult } from "./types";

export const HEADLINE: Record<ScanResult, string> = {
  SUCCESS: "Let them in",
  ALREADY_USED: "Already used",
  WRONG_EVENT: "Wrong event",
  CANCELLED: "Cancelled",
  REFUNDED: "Refunded",
  INVALID: "Not recognised",
  NOT_ASSIGNED: "Not your event",
  EXPIRED: "Event is over",
};

/** How a result looks: green to admit, amber for a second scan, red for a refusal, grey for the rest. */
export const RESULT_TONE: Record<ScanResult, "good" | "warn" | "bad" | "neutral"> = {
  SUCCESS: "good",
  ALREADY_USED: "warn",
  WRONG_EVENT: "bad",
  CANCELLED: "bad",
  REFUNDED: "bad",
  INVALID: "bad",
  NOT_ASSIGNED: "neutral",
  EXPIRED: "neutral",
};

const DOORS_BEFORE_MS = 60 * 60 * 1000;      // an event counts as "on" an hour before it starts
const DEFAULT_LENGTH_MS = 5 * 60 * 60 * 1000; // when no end time was set

export interface When { phase: "live" | "soon" | "later" | "ended"; label: string; range: string; day: string }

/** Where an event is in time, in words a person at the gate can use. */
export function whenIs(e: AssignedEvent, now: number): When {
  const zone = { timeZone: e.timezone };
  const start = new Date(e.starts_at).getTime();
  const end = e.ends_at ? new Date(e.ends_at).getTime() : start + DEFAULT_LENGTH_MS;
  const clock = (ms: number) => new Intl.DateTimeFormat("en-IN", { ...zone, hour: "numeric", minute: "2-digit", hour12: true }).format(new Date(ms)).toUpperCase();
  const day = new Intl.DateTimeFormat("en-IN", { ...zone, weekday: "short", day: "numeric", month: "short" }).format(new Date(start));
  const ymd = (ms: number) => new Intl.DateTimeFormat("en-CA", { ...zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(ms));
  const range = e.ends_at ? `${clock(start)} to ${clock(end)}` : `from ${clock(start)}`;
  if (now > end) return { phase: "ended", label: "Ended", range, day };
  if (now >= start - DOORS_BEFORE_MS) return { phase: "live", label: now >= start ? "Happening now" : "Doors open", range, day };
  const mins = Math.round((start - now) / 60000);
  if (ymd(start) === ymd(now)) {
    const h = Math.floor(mins / 60), m = mins % 60;
    return { phase: "soon", label: `Today, starts in ${h ? `${h} h ` : ""}${m} min`, range, day };
  }
  const tomorrow = ymd(now + 24 * 3600 * 1000) === ymd(start);
  return { phase: "later", label: tomorrow ? "Tomorrow" : day, range, day };
}

/** The API words its messages for logs, with ISO timestamps. At the gate they read as a clock time. */
export const readable = (msg: string) =>
  msg.replace(/\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})/g, (iso) => timeOf(iso));
