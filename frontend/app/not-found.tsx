import Link from "next/link";

export default function NotFound() {
  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>We could not find that page</h1>
        <p style={{ margin: "16px 0 36px" }}>The link may be old, or the night may no longer be listed.</p>
        <Link className="pill" href="/#events">See what is on</Link>
      </div>
    </main>
  );
}
