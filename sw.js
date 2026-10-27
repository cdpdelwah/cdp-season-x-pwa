const CACHE_VERSION = 'cdp-v1';

// Instantly install the new service worker
self.addEventListener('install', (event) => {
    self.skipWaiting(); 
});

// Wipe out any old caches so the app is forced to pull fresh code
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames.map((cache) => {
                    if (cache !== CACHE_VERSION) {
                        return caches.delete(cache);
                    }
                })
            );
        }).then(() => self.clients.claim()) 
    );
});

self.addEventListener("push", function (event) {
    let data = { title: "CDP Season X", body: "Matchday alert incoming!" };
    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: "https://via.placeholder.com/192/f59e0b/000000?text=CDP",
        badge: "https://via.placeholder.com/96/f59e0b/000000?text=CDP",
        vibrate: [200, 100, 200]
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});