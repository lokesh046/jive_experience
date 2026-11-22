"use client";
import { PRESETS, describePolicy, type PolicyTier } from "@/lib/policy";

const MAX = 6;

/** Edit refund tiers: "if a customer cancels at least N before the event, they get P% back". */
export function PolicyEditor({
  tiers, onChange, disabled,
}: { tiers: PolicyTier[]; onChange: (t: PolicyTier[]) => void; disabled?: boolean }) {
  const set = (i: number, part: Partial<PolicyTier>) => onChange(tiers.map((t, k) => (k === i ? { ...t, ...part } : t)));
  const lines = describePolicy({ tiers });

  return (
    <div className="pol">
      <div className="pol-presets" role="group" aria-label="Quick starts">
        {PRESETS.map((p) => (
          <button key={p.label} type="button" className="chip" disabled={disabled} onClick={() => onChange(p.tiers.map((t) => ({ ...t })))}>{p.label}</button>
        ))}
      </div>
      <ol className="pol-rows">
        {tiers.map((t, i) => {
          const days = t.hours_before % 24 === 0;
          return (
            <li key={i}>
              <span>If cancelled at least</span>
              <input
                type="number" min={0} aria-label={`Tier ${i + 1}: lead time`} disabled={disabled}
                value={days ? t.hours_before / 24 : t.hours_before}
                onChange={(e) => set(i, { hours_before: Math.max(0, Math.round(Number(e.target.value) || 0)) * (days ? 24 : 1) })}
              />
              <select aria-label={`Tier ${i + 1}: unit`} disabled={disabled} value={days ? "d" : "h"} onChange={(e) => set(i, { hours_before: e.target.value === "d" ? Math.max(1, Math.round(t.hours_before / 24)) * 24 : t.hours_before })}>
                <option value="d">days</option><option value="h">hours</option>
              </select>
              <span>before, refund</span>
              <input
                type="number" min={0} max={100} aria-label={`Tier ${i + 1}: refund percent`} disabled={disabled}
                value={t.percent}
                onChange={(e) => set(i, { percent: Math.min(100, Math.max(0, Math.round(Number(e.target.value) || 0))) })}
              />
              <span>%</span>
              {!disabled && <button type="button" className="link" onClick={() => onChange(tiers.filter((_, k) => k !== i))}>Remove</button>}
            </li>
          );
        })}
      </ol>
      {!disabled && tiers.length < MAX && (
        <button type="button" className="link" onClick={() => onChange([...tiers, { hours_before: tiers.length ? Math.max(0, Math.min(...tiers.map((t) => t.hours_before)) - 24) : 168, percent: 0 }])}>Add a step</button>
      )}
      <div className="pol-preview" aria-live="polite">
        <b>What customers will read</b>
        {lines.length ? lines.map((l, i) => <p key={i}>{l}</p>) : <p>No steps: customers are told to contact you to cancel.</p>}
      </div>
    </div>
  );
}
