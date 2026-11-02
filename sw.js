self.addEventListener("push", function(event) {
    let data = { title: "CDP Command Center", body: "New live update", tag: "cdp-alert" };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: "/icon.png",
        badge: "/badge.png",
        tag: data.tag || "cdp-alert",
        renotify: true,
        vibrate: [200, 100, 200],
        data: { url: "/" }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
            .then(() => fetch(`/api/push_ack?status=displayed&tag=${encodeURIComponent(options.tag)}&title=${encodeURIComponent(data.title)}`).catch(() => {}))
            .catch((err) => fetch(`/api/push_ack?status=error&tag=${encodeURIComponent(options.tag)}&err=${encodeURIComponent(String(err))}`).catch(() => {}))
    );
});

self.addEventListener("notificationclick", function(event) {
    event.notification.close();
    event.waitUntil(clients.openWindow("/"));
});