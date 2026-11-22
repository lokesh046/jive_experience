"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="page">
      <div className="wrap narrow">
        <h1>Something went wrong</h1>
        <p style={{ margin: "16px 0 36px" }}>That did not load. Please try again.</p>
        <button className="pill" type="button" onClick={reset}>Try again</button>
      </div>
    </main>
  );
}
