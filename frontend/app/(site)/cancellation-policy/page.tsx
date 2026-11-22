import type { Metadata } from "next";

export const metadata: Metadata = { title: "Cancellation and refund policy" };

// The wording of this page is a business and legal decision that is still open.
export default function Page() {
  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Cancellation and refund policy</h1>
        <p style={{ marginTop: 24 }}>This page is being finalised and will be published before tickets go on sale.</p>
      </div>
    </main>
  );
}
