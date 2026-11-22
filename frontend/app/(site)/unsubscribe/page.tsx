import type { Metadata } from "next";
import { Unsubscribe } from "./Unsubscribe";

export const metadata: Metadata = { title: "Unsubscribe", robots: { index: false, follow: false } };

export default function Page() {
  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Unsubscribe</h1>
        <Unsubscribe />
      </div>
    </main>
  );
}
