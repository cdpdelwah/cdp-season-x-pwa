function resolveUrlFromTag(tag, explicitUrl) {
    if (explicitUrl && explicitUrl !== "/") return explicitUrl;
    const t = String(tag || "").trim().toLowerCase();
    if (t.startsWith("bh-gwlock-")) {
        const parts = t.split("-");
        for (const p of parts) {
            if (/^\d+$/.test(p)) return `/#hector_gw_${p}`;
        }
        return "/#hector_active";
    }
    if (t.startsWith("bh-acc-") || t.startsWith("bh-resp-")) return "/#hector_active";
    if (t.startsWith("bh-")) return "/#hector";
    if (t.startsWith("tr-")) return "/#trade_offers";
    if (t.startsWith("trade-")) return "/#trade";
    if (t.startsWith("wres-")) return "/#players_waivers";
    if (t.startsWith("waiver-")) return "/#players";
    if (t.startsWith("lineup-1h")) return "/#squad";
    if (t.startsWith("ev-") || t.startsWith("gw-locked-") || t.startsWith("lineup-passed")) return "/#scores";
    return "/#home";
}

self.addEventListener("install", (event) => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    let data = { title: "CDP App", body: "New update available", tag: "cdp-alert", url: "/#home" };
    try {
        if (event.data) {
            data = Object.assign(data, event.data.json());
        }
    } catch (e) {
        if (event.data) {
            data.body = event.data.text();
        }
    }

    const targetUrl = resolveUrlFromTag(data.tag, data.url);
    const options = {
        body: data.body,
        icon: "/icon.png",
        badge: "/badge.png",
        tag: data.tag || "cdp-alert",
        renotify: true,
        data: { url: targetUrl }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options).then(() => {
            return fetch(`/api/push_ack?status=displayed&tag=${encodeURIComponent(options.tag)}&title=${encodeURIComponent(data.title)}`).catch(() => {});
        }).catch((err) => {
            return fetch(`/api/push_ack?status=error&tag=${encodeURIComponent(options.tag)}&err=${encodeURIComponent(String(err))}`).catch(() => {});
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const nData = event.notification.data || {};
    const targetUrl = resolveUrlFromTag(event.notification.tag, nData.url);

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if (client.url.includes(self.location.origin) && "focus" in client) {
                    client.postMessage({ type: "CDP_NAVIGATE", url: targetUrl });
                    return client.focus();
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
        })
    );
});