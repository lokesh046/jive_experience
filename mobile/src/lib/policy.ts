export interface PolicyTier { hours_before: number; percent: number }
export interface Policy { tiers: PolicyTier[] }

const lead = (hours: number) => {
  if (hours <= 0) return "at any time before the event starts";
  if (hours % 24 === 0) {
    const d = hours / 24;
    return `at least ${d} ${d === 1 ? "day" : "days"} before the event`;
  }
  return `at least ${hours} ${hours === 1 ? "hour" : "hours"} before the event`;
};

/** The policy in plain English, one sentence per tier. */
export function describePolicy(policy: Policy | null | undefined): string[] {
  const tiers = [...(policy?.tiers ?? [])].sort((a, b) => b.hours_before - a.hours_before);
  if (tiers.length === 0) return [];
  const lines = tiers.map((t) => {
    const amount = t.percent === 100 ? "A full refund" : t.percent === 0 ? "No refund" : `A ${t.percent}% refund`;
    return `${amount} if you cancel ${lead(t.hours_before)}.`;
  });
  const last = tiers[tiers.length - 1];
  if (last.percent > 0 && last.hours_before > 0) lines.push("No refund after that.");
  return lines;
}

export const NO_REFUNDS: PolicyTier[] = [{ hours_before: 0, percent: 0 }];
export const PRESETS: { label: string; tiers: PolicyTier[] }[] = [
  { label: "Full refund up to 7 days before", tiers: [{ hours_before: 168, percent: 100 }] },
  { label: "100% up to 7 days, 50% up to 2 days", tiers: [{ hours_before: 168, percent: 100 }, { hours_before: 48, percent: 50 }] },
  { label: "No refunds", tiers: NO_REFUNDS },
];
