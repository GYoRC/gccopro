/**
 * @file Page script: registers the service worker and drives the notification
 * panel of the "Profil" page (#push-panel). No dependencies, no build step.
 */

/**
 * Convert a base64url string (the VAPID public key) to the bytes PushManager expects.
 * @param {string} value
 * @returns {Uint8Array}
 */
function base64UrlToBytes(value) {
  const base64 = (value + "=".repeat((4 - (value.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
}

/**
 * POST JSON to the app with the CSRF header.
 * @param {string} url
 * @param {string} csrf
 * @param {object} body
 * @returns {Promise<Response>}
 */
function postJson(url, csrf, body) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: JSON.stringify(body),
    credentials: "same-origin",
  });
}

/**
 * Wire the enable/disable buttons and keep the status line accurate.
 * @param {HTMLElement} panel
 * @param {ServiceWorkerRegistration} registration
 */
async function setUpPushPanel(panel, registration) {
  const status = panel.querySelector("#push-status");
  const enable = panel.querySelector("#push-enable");
  const disable = panel.querySelector("#push-disable");
  const { vapidKey, csrf, subscribeUrl, unsubscribeUrl } = panel.dataset;

  /** Refresh the status text and which button is visible. */
  async function refresh() {
    const sub = await registration.pushManager.getSubscription();
    enable.hidden = !!sub;
    disable.hidden = !sub;
    if (sub) {
      status.textContent = "Notifications activées sur cet appareil.";
    } else if (Notification.permission === "denied") {
      status.textContent = "Notifications bloquées : autorisez-les dans les réglages du navigateur pour ce site.";
      enable.hidden = true;
    } else {
      status.textContent = "Notifications désactivées sur cet appareil.";
    }
  }

  enable.addEventListener("click", async () => {
    enable.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        await refresh();
        return;
      }
      const sub = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: base64UrlToBytes(vapidKey),
      });
      const response = await postJson(subscribeUrl, csrf, sub.toJSON());
      if (!response.ok) throw new Error("HTTP " + response.status);
    } catch (err) {
      status.textContent = "Impossible d’activer les notifications (" + err.message + ").";
      enable.disabled = false;
      return;
    }
    enable.disabled = false;
    await refresh();
  });

  disable.addEventListener("click", async () => {
    const sub = await registration.pushManager.getSubscription();
    if (sub) {
      await postJson(unsubscribeUrl, csrf, { endpoint: sub.endpoint });
      await sub.unsubscribe();
    }
    await refresh();
  });

  await refresh();
}

/** Entry point: register the service worker, then set up the panel if present. */
async function main() {
  const panel = document.getElementById("push-panel");
  const status = panel && panel.querySelector("#push-status");

  if (!("serviceWorker" in navigator) || !window.isSecureContext) {
    if (status) status.textContent = "Ce navigateur ou cette adresse ne permet pas les notifications (connexion HTTPS requise).";
    return;
  }
  const registration = await navigator.serviceWorker.register("/sw.js");
  if (!panel) return;

  if (!("PushManager" in window) || !("Notification" in window)) {
    status.textContent = "Notifications non disponibles. Sur iPhone, ajoutez d’abord le site à l’écran d’accueil.";
    return;
  }
  if (!panel.dataset.vapidKey) {
    status.textContent = "Notifications non configurées sur le serveur.";
    return;
  }
  await navigator.serviceWorker.ready;
  await setUpPushPanel(panel, registration);
}

main().catch((err) => console.error(err));
