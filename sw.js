// Offline-Cache: Die App wird einmalig gespeichert und danach nur noch aus dem Cache geladen.
// Es werden keine Daten verschickt; der Speicher der Einträge liegt ausschließlich im Gerät.
// Updates nur auf Wunsch: Ein neues Update wird nur installiert, wenn in den Einstellungen
// „Nach Update suchen“ gedrückt wurde (Freigabe für 10 Minuten in IndexedDB).
const V = 103, C = 'alltagsplaner-v' + V;
const FILES = ['./', './index.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png'];
function freigabe() {
  return new Promise(res => {
    try {
      const r = indexedDB.open('alltagsplaner-update', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('kv');
      r.onsuccess = () => { try { const q = r.result.transaction('kv').objectStore('kv').get('ok'); q.onsuccess = () => res(!!q.result && Date.now() - q.result < 600000); q.onerror = () => res(false); } catch (e) { res(false); } };
      r.onerror = () => res(false);
    } catch (e) { res(false); }
  });
}
self.addEventListener('install', e => {
  e.waitUntil((async () => {
    // Läuft schon eine Version mit Update-Sperre (ab 103), braucht es die Freigabe des Nutzers
    // Der App Bescheid geben, dass es eine neue Version gibt (sie fragt dann, ob du sie willst)
    (await self.clients.matchAll({ includeUncontrolled: true })).forEach(c => c.postMessage({ neu: V }));
    const gesperrt = (await caches.keys()).some(k => { const m = /^alltagsplaner-v(\d+)$/.exec(k); return m && k !== C && +m[1] >= 103; });
    if (gesperrt && !(await freigabe())) throw new Error('Update nur auf Wunsch');
    const c = await caches.open(C);
    await c.addAll(FILES.map(f => new Request(f, { cache: 'reload' })));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== C).map(x => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('message', e => { if (e.data === 'version' && e.source) e.source.postMessage({ version: V }); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  // Einzige Ausnahme: Kursdienste, und nur wenn in den Einstellungen „Nur Finanzkurse“ gewählt ist (die App prüft das vor jeder Anfrage)
  if (u.origin === 'https://api.twelvedata.com' || u.origin === 'https://www.alphavantage.co') return;
  if (u.origin !== location.origin) { e.respondWith(new Response('', { status: 403 })); return; }
  // Alles kommt aus dem Speicher auf dem Gerät, nie aus dem Netz
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || caches.match('./index.html')));
});
