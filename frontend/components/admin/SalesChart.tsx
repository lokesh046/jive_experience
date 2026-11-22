import { inr } from "@/lib/format";
import type { SalesDay } from "@/lib/types";

const compact = (paise: number) =>
  "₹" + new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(paise / 100);

/** A round number at or above `value`, so the top of the chart reads cleanly. */
function niceMax(value: number): number {
  if (value <= 0) return 100_00;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= value) return step * power;
  return 10 * power;
}

const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));

/** Sales per day as bars. Drawn as SVG so it costs no chart library; the data is also available as a table. */
export function SalesChart({ days }: { days: SalesDay[] }) {
  const W = 880, H = 260, L = 56, R = 8, T = 12, B = 30;
  const top = niceMax(Math.max(0, ...days.map((d) => d.gross_paise)));
  const plot = { w: W - L - R, h: H - T - B };
  const slot = plot.w / Math.max(days.length, 1);
  const bar = Math.max(2, Math.min(28, slot * 0.7));
  const y = (v: number) => T + plot.h - (v / top) * plot.h;
  const ticks = [0, 0.5, 1].map((f) => f * top);
  const labelAt = new Set([0, Math.floor((days.length - 1) / 2), days.length - 1]);
  const total = days.reduce((s, d) => s + d.gross_paise, 0);

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily sales for the last ${days.length} days, ${inr(total)} in total`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#222" />
            <text x={L - 10} y={y(t) + 4} textAnchor="end" fill="#8a8a8a" fontSize="14">{t === 0 ? "₹0" : compact(t)}</text>
          </g>
        ))}
        {days.map((d, i) => {
          const h = (d.gross_paise / top) * plot.h;
          const x = L + i * slot + (slot - bar) / 2;
          return (
            <g key={d.day}>
              <rect x={x} y={d.gross_paise ? y(d.gross_paise) : T + plot.h - 1} width={bar} height={d.gross_paise ? Math.max(h, 2) : 1} rx={2} fill={d.gross_paise ? "#fff" : "#333"}>
                <title>{`${dayLabel(d.day)}: ${inr(d.gross_paise)}, ${d.tickets} ${d.tickets === 1 ? "ticket" : "tickets"}`}</title>
              </rect>
              {labelAt.has(i) && <text x={x + bar / 2} y={H - 8} textAnchor={i === 0 ? "start" : i === days.length - 1 ? "end" : "middle"} fill="#8a8a8a" fontSize="14">{dayLabel(d.day)}</text>}
            </g>
          );
        })}
      </svg>
      <details className="chart-data">
        <summary>Show the numbers</summary>
        <table>
          <thead><tr><th scope="col">Day</th><th scope="col">Tickets</th><th scope="col">Sales</th></tr></thead>
          <tbody>{days.filter((d) => d.tickets || d.gross_paise).map((d) => <tr key={d.day}><th scope="row">{dayLabel(d.day)}</th><td>{d.tickets}</td><td>{inr(d.gross_paise)}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}
