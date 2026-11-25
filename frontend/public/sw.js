/* JIVE service worker: shows push notifications and opens the right page when one is clicked.
   It does nothing else: no caching, no offline mode. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = {}; }
  const title = typeof data.title === "string" && data.title ? data.title : "JIVE";
  const url = typeof data.url === "string" && data.url.startsWith("/") && !data.url.startsWith("//") ? data.url : "/notifications";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: typeof data.body === "string" ? data.body : "",
      tag: typeof data.tag === "string" ? data.tag : undefined,
      data: { url },
      requireInteraction: data.severity === "critical",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data && event.notification.data.url ? event.notification.data.url : "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if ("focus" in w) { w.navigate(target).catch(() => {}); return w.focus(); }
      }
      return self.clients.openWindow(target);
    }),
  );
});
