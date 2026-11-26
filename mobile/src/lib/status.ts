import type { BookingStatus } from "./types";

export const STATUS_LABEL: Record<BookingStatus, string> = {
  PENDING: "Waiting for payment",
  CONFIRMED: "Confirmed",
  EXPIRED: "Not completed",
  CANCELLED: "Cancelled",
  REFUNDED: "Cancelled, refunded",
  PARTIALLY_REFUNDED: "Partly refunded",
};

export const statusTone = (s: BookingStatus): "good" | "warn" | "neutral" =>
  s === "CONFIRMED" || s === "PARTIALLY_REFUNDED" ? "good" : s === "PENDING" ? "warn" : "neutral";
