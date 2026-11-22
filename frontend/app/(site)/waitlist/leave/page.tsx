import type { Metadata } from "next";
import { Leave } from "./Leave";

export const metadata: Metadata = { title: "Leave the waitlist", robots: { index: false, follow: false } };

export default function Page() {
  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Leave the waitlist</h1>
        <Leave />
      </div>
    </main>
  );
}
