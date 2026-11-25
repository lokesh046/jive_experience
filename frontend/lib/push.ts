import { api } from "./api-client";

export type PushState = "unsupported" | "unconfigured" | "denied" | "off" | "on";

const supported = () =>
  typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

/** base64url public key -> the bytes the browser wants. */
function keyBytes(key: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (key.length % 4)) % 4);
  const raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration() {
  return (await navigator.serviceWorker.getRegistration("/")) ?? (await navigator.serviceWorker.register("/sw.js", { scope: "/" }));
}

/** Is push on for *this* browser? Asked of the browser, not the server: a person can have other devices. */
export async function pushState(): Promise<PushState> {
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  const key = await api<{ configured: boolean }>("notifications/push/key").catch(() => ({ configured: false }));
  if (!key.configured) return "unconfigured";
  const reg = await navigator.serviceWorker.getRegistration("/");
  return (await reg?.pushManager.getSubscription()) ? "on" : "off";
}

export async function enablePush(): Promise<PushState> {
  if (!supported()) return "unsupported";
  const { configured, public_key } = await api<{ configured: boolean; public_key: string | null }>("notifications/push/key");
  if (!configured || !public_key) return "unconfigured";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "off";
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) }));
  await api("notifications/push/subscribe", { method: "POST", json: sub.toJSON() });
  return "on";
}

export async function disablePush(): Promise<PushState> {
  const reg = await navigator.serviceWorker.getRegistration("/");
  const sub = await reg?.pushManager.getSubscription();
  if (sub) {
    await api("notifications/push/unsubscribe", { method: "POST", json: { endpoint: sub.endpoint } }).catch(() => {});
    await sub.unsubscribe().catch(() => {});
  }
  return "off";
}

export const sendTestPush = () => api<{ sent: number }>("notifications/push/test", { method: "POST", json: {} });
