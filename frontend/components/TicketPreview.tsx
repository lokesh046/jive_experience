/** A ticket that fills in as the customer chooses. It is a preview: the real ticket and its QR code are issued after payment. */
export function TicketPreview({
  when, title, venue, ticket, admit, total, premium = false, year,
}: { when: string; title: string; venue: string; ticket: string | null; admit: number; total: string | null; premium?: boolean; year?: string }) {
  return (
    <figure className={`tkp${premium ? " prem" : ""}`} aria-label="Ticket preview">
      <div className="tkp-main">
        <p className="tkp-kick">{when}</p>
        <h3 className="tkp-title">{premium ? `JIVE presents · ${title}` : title}</h3>
        <p className="tkp-big" aria-hidden="true">{ticket ?? "VIP"}</p>
        <p className="tkp-venue">{venue}</p>
        <dl className="tkp-fields" aria-live="polite">
          <div><dt>Ticket</dt><dd key={ticket ?? "none"} className={ticket ? "fill" : "empty"}>{ticket ?? "Choose below"}</dd></div>
          <div><dt>Admit</dt><dd key={admit} className={admit ? "fill" : "empty"}>{admit || "—"}</dd></div>
          <div><dt>Total</dt><dd key={total ?? "none"} className={total ? "fill" : "empty"}>{total ?? "—"}</dd></div>
        </dl>
      </div>
      <div className="tkp-stub" aria-hidden="true">
        {premium && year && <span className="tkp-year">{year}</span>}
        <span className="tkp-admit">{admit > 1 ? `Admit ${admit}` : "Admit one"}</span>
        <span className="tkp-bars" />
        <span className="tkp-code">JIVE · after payment</span>
      </div>
    </figure>
  );
}
