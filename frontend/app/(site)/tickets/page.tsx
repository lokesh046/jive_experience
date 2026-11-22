import type { Metadata } from "next";
import { MyTickets } from "./MyTickets";

export const metadata: Metadata = { title: "My tickets", robots: { index: false, follow: false } };

export default function Page() {
  return <MyTickets />;
}
