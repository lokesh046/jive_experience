import type { Metadata } from "next";
import Link from "next/link";
import { getDefaultPolicy } from "@/lib/catalogue";
import { CONTACT_EMAIL } from "@/lib/config";
import { describePolicy } from "@/lib/policy";

export const metadata: Metadata = {
  title: "Cancellation and refund policy",
  description: "When you can cancel a JIVE booking and how much you get back.",
  alternates: { canonical: "/cancellation-policy" },
};

export default async function Page() {
  const lines = describePolicy(await getDefaultPolicy());
  return (
    <main className="page">
      <div className="wrap narrow prose">
        <h1>Cancellation and refund policy</h1>
        <h2>If you cancel a booking</h2>
        {lines.length > 0 ? (
          <ul className="terms">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
        ) : (
          <p>Online cancellation is not set up yet. If your plans change, contact us and we will help.</p>
        )}
        <p>Some events have their own policy. It is shown on that event&apos;s page before you buy, and it is the one that applies to your booking.</p>
        <h2>How to cancel</h2>
        <p>Open <Link className="link" href="/tickets">My tickets</Link>, choose the booking and select <b>Cancel this booking</b>. You are shown exactly how much you will get back before you confirm. Cancelling a booking cancels every ticket in it.</p>
        <h2>If we cancel the event</h2>
        <p>If we cancel an event, every booking for it is refunded in full to the original payment method.</p>
        <h2>When the money arrives</h2>
        <p>Refunds go back to the payment method you used. Banks can take a few working days to show them.</p>
        {CONTACT_EMAIL && <p>Questions? Write to <a className="link" href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.</p>}
      </div>
    </main>
  );
}
