// Offline-Cache: Die App wird einmalig gespeichert und danach nur noch aus dem Cache geladen.
// Es werden keine Daten verschickt; der Speicher der Einträge liegt ausschließlich im Gerät.
const C = 'alltagsplaner-v102';
const FILES = ['./', './index.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(C).then(c => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  // Einzige Ausnahme: Kursdienste, und nur wenn in den Einstellungen „Nur Finanzkurse“ gewählt ist (die App prüft das vor jeder Anfrage)
  if (u.origin === 'https://api.twelvedata.com' || u.origin === 'https://www.alphavantage.co') return;
  if (u.origin !== location.origin) { e.respondWith(new Response('', { status: 403 })); return; }
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match('./index.html')));
});
