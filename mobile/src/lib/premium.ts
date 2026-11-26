/**
 * Whether a ticket type gets the premium look: named like a VIP tier, or the top-priced type when an
 * event has several. Mirrors the rule used in the confirmation email.
 */
export function isPremiumType(name: string, price: number, allPrices: number[]): boolean {
  if (/vip|premium|platinum|gold|black|elite|royal/i.test(name)) return true;
  return allPrices.length > 1 && price > 0 && price === Math.max(...allPrices);
}
