/**
 * @file Service worker: displays push notifications and opens the app when one is tapped.
 * Served from /sw.js (see views/pwa.py) so its scope is the whole site.
 */

/**
 * Show the notification described by the push payload ({title, body, url}).
 */
self.addEventListener("push", (event) => {
  let data = { title: "Notification", body: "", url: "/" };
  try {
    data = Object.assign(data, event.data ? event.data.json() : {});
  } catch (err) {
    data.body = event.data ? event.data.text() : "";
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      lang: "fr",
      data: { url: data.url },
    })
  );
});

/**
 * Focus an open GCCopro tab (navigating it to the notification's URL), or open one.
 */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      for (const tab of tabs) {
        if ("focus" in tab) {
          return tab.navigate(url).then((t) => (t || tab).focus());
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
