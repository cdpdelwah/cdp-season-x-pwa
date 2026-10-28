self.addEventListener("push", function (event) {
    let data = { title: "CDP Season X", body: "Matchday alert incoming!", tag: "cdp-alert" };
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
        badge: "/icon.png",
        tag: data.tag || ("cdp-" + Date.now()),
        renotify: true,
        vibrate: [200, 100, 200],
        data: { url: "/#scores" }
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

self.addEventListener("notificationclick", function (event) {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (clientList) {
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if ("focus" in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow("/#scores");
            }
        })
    );
});