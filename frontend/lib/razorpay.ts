export interface RazorpayResponse { razorpay_payment_id: string; razorpay_order_id: string; razorpay_signature: string }
interface RazorpayInstance { open(): void; on(ev: string, cb: (r: unknown) => void): void }
declare global { interface Window { Razorpay?: new (o: Record<string, unknown>) => RazorpayInstance } }

/** Loads Razorpay's checkout script once, on demand. */
export function loadRazorpay(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.Razorpay) return resolve();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load the payment window."));
    document.head.appendChild(s);
  });
}
