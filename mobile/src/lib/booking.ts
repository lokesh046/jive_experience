import { randomUUID } from "expo-crypto";

export const BOOKING_MESSAGES: Record<string, string> = {
  PURCHASE_LIMIT_EXCEEDED: "That is over the limit for this event. Reduce the number of tickets and try again.",
  INSUFFICIENT_INVENTORY: "Those tickets have just sold out. Pick a different category or fewer tickets.",
  SALE_NOT_OPEN: "Sales for this event have not opened yet.",
  SALE_CLOSED: "Sales for this event have closed.",
  EVENT_STARTED: "This event has already started.",
  EVENT_NOT_SELLABLE: "Tickets for this event are not on sale.",
  CATEGORY_INACTIVE: "That ticket type is no longer available.",
  BELOW_MINIMUM: "That ticket type has a minimum number of tickets per booking.",
  ABOVE_MAXIMUM: "That is more than the maximum for this ticket type.",
};

/** Same selection gives the same key, so a double tap or a retry cannot make two bookings. */
let last: { sig: string; key: string } | null = null;
export function idempotencyKey(sig: string): string {
  if (last?.sig !== sig) last = { sig, key: randomUUID() };
  return last.key;
}
export const forgetKey = () => { last = null; };

/** The page Razorpay's checkout runs in, inside a WebView. Results come back as messages. */
export function razorpayHtml(options: Record<string, unknown>): string {
  const safe = JSON.stringify(options).replace(/</g, "\\u003c");
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{margin:0;background:#0a0a0a;color:#a3a3a3;font-family:-apple-system,Roboto,sans-serif;display:flex;align-items:center;justify-content:center;height:100%}</style></head><body><p id="m">Opening payment…</p>
<script src="https://checkout.razorpay.com/v1/checkout.js"></script>
<script>
function post(o){window.ReactNativeWebView.postMessage(JSON.stringify(o))}
try{
  var o=${safe};
  o.handler=function(r){post({type:"success",payload:r})};
  o.modal={ondismiss:function(){post({type:"dismissed"})},confirm_close:true};
  var rz=new Razorpay(o);
  rz.on("payment.failed",function(r){post({type:"failed",payload:r&&r.error})});
  rz.open();
}catch(e){post({type:"error",message:String(e)})}
</script></body></html>`;
}
