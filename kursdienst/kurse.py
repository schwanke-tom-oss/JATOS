#!/usr/bin/env python3
"""Kursdienst für die JATOS-App.

Holt alle paar Minuten die aktuellen Kurse einer festen Liste von Wertpapieren bei
Lang & Schwarz (ls-tc.de) und Krypto-Kurse bei Kraken und legt sie als kleine Dateien ab.
Die App lädt nur diese Dateien. So verlässt keine Angabe über ein einzelnes Depot das Gerät,
und niemand braucht einen eigenen Zugangsschlüssel.

Ausgabe (Zweig "kurse"):
  kurse.json    aktueller Kurs je ISIN in Euro, Zeitpunkt, Schlusskurs vom Vortag
  verlauf.json  Schlusskurse: täglich für die letzten Monate, wöchentlich für die Jahre davor
  ids.json      Zuordnung ISIN -> Nummer bei Lang & Schwarz (spart Suchanfragen)

Nur Python-Standardbibliothek, keine Zugangsdaten.
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo('Europe/Berlin')
HIER = os.path.dirname(os.path.abspath(__file__))
ALT = os.environ.get('KURS_ALT', 'alt')
AUS = os.environ.get('KURS_AUS', 'out')
DEBUG = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')
ALLES = os.environ.get('ALLES', '').lower() in ('1', 'true', 'yes')
LS = 'https://www.ls-tc.de'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
KRYPTO = {'BTC': 'XBTEUR', 'ETH': 'ETHEUR', 'XRP': 'XRPEUR', 'SOL': 'SOLEUR', 'ADA': 'ADAEUR', 'DOGE': 'XDGEUR', 'LTC': 'LTCEUR', 'DOT': 'DOTEUR', 'LINK': 'LINKEUR'}
PAUSE = 0.25
ZAHL = r'[+\-−–]?\d{1,3}(?:\.\d{3})*,\d+'


def log(*a):
    print(*a, flush=True)


def hol(url, versuche=3, timeout=25):
    letzter = None
    for i in range(versuche):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Language': 'de-DE,de;q=0.9'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:  # noqa: BLE001
            letzter = e
            time.sleep(1.5 * (i + 1))
    raise letzter


def lade(pfad, leer):
    try:
        with open(pfad, encoding='utf-8') as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return leer


def schreib(name, obj):
    with open(os.path.join(AUS, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'), sort_keys=True)


def lese_liste():
    out = []
    with open(os.path.join(HIER, 'liste.txt'), encoding='utf-8') as f:
        for z in f:
            k = z.split('#')[0].strip().upper()
            if k and k not in out:
                out.append(k)
    return out


def de(s):
    return float(s.replace('.', '').replace('−', '-').replace('–', '-').replace(',', '.'))


def iso(t):
    return t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def zeitpunkt(uhr, jetzt):
    """Die Seite zeigt nur die Uhrzeit (deutsche Zeit). Daraus den Zeitpunkt bauen."""
    teile = [int(x) for x in uhr.split(':')]
    t = jetzt.astimezone(BERLIN).replace(hour=teile[0], minute=teile[1], second=teile[2] if len(teile) > 2 else 0, microsecond=0)
    if t > jetzt + dt.timedelta(minutes=10):
        t -= dt.timedelta(days=1)
    return iso(t)


# ---------- Lang & Schwarz ----------
def ls_suche(isin):
    j = json.loads(hol(f'{LS}/_rpc/json/.lstc/instrument/search/main?q={urllib.parse.quote(isin)}&localeId=2'))
    for x in j if isinstance(j, list) else []:
        if (x.get('isin') or '').upper() == isin and x.get('instrumentId'):
            return {'id': x['instrumentId'], 'link': x.get('link') or '', 'name': (x.get('displayname') or '').strip()}
    return None


def ls_seite(link, jetzt, zeigen=False):
    """Aktueller Kurs von der Wertpapier-Seite: Kurs, Veränderung, Uhrzeit."""
    roh = hol(LS + link)
    felder = {}
    for m in re.finditer(r'<[^>]*\bfield="([A-Za-z_]+)"[^>]*>\s*([^<]*?)\s*<', roh):
        felder.setdefault(m.group(1), html.unescape(m.group(2)))
    text = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<script.*?</script>|<style.*?</style>|<[^>]+>', ' ', roh, flags=re.S)))
    m = re.search(rf'({ZAHL})\s*€\s*({ZAHL})\s*({ZAHL})\s*%\s*(\d\d:\d\d(?::\d\d)?)', text)
    if zeigen:
        log('   Felder:', json.dumps(felder, ensure_ascii=False)[:900])
        i = m.start() if m else text.find('ISIN')
        log('   Text  :', text[max(0, i - 200):i + 400])
    if m:
        p, diff = de(m.group(1)), de(m.group(2))
        if p > 0:
            return {'p': round(p, 4), 'vt': round(p - diff, 4), 't': zeitpunkt(m.group(4), jetzt)}
    # Ersatz: die Felder der Live-Anzeige
    try:
        p = de(felder.get('mid') or '')
        uhr = next((v for v in felder.values() if re.fullmatch(r'\d\d:\d\d:\d\d', v or '')), None)
        if p > 0 and uhr:
            vt = None
            for k in ('change', 'diff', 'abs'):
                if re.fullmatch(ZAHL, felder.get(k) or ''):
                    vt = round(p - de(felder[k]), 4)
                    break
            return {'p': round(p, 4), 'vt': vt, 't': zeitpunkt(uhr, jetzt)}
    except Exception:  # noqa: BLE001
        pass
    return None


def ls_chart(iid, reihe):
    j = json.loads(hol(f'{LS}/_rpc/json/instrument/chart/dataForInstrument?instrumentId={iid}&marketId=1&quotetype=mid&series={reihe}&localeId=2'))
    daten = (((j.get('series') or {}).get(reihe) or {}).get('data')) or []
    vortag = None
    for pl in ((j.get('info') or {}).get('plotlines')) or []:
        if pl.get('id') == 'previousDay' and pl.get('value'):
            vortag = float(pl['value'])
    return [(int(ms), float(v)) for ms, v in daten if v], vortag


def ls_intraday(iid, jetzt):
    """Ersatzweg, falls die Seite nicht lesbar ist: letzter Punkt der Tageskurve."""
    daten, vortag = ls_chart(iid, 'intraday')
    if not daten:
        return None
    ms, v = daten[-1]
    t = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    if jetzt - t > dt.timedelta(hours=20) or v <= 0:
        return None
    return {'p': round(v, 4), 'vt': round(vortag, 4) if vortag else None, 't': iso(t)}


def ls_verlauf(iid):
    daten, _ = ls_chart(iid, 'history')
    return sorted(((dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=ms)).date().isoformat(), round(v, 4)) for ms, v in daten if v > 0)


# ---------- Kraken (Krypto in Euro) ----------
def kraken(pfad):
    j = json.loads(hol('https://api.kraken.com/0/public/' + pfad))
    if j.get('error'):
        raise RuntimeError(str(j['error']))
    return j['result']


def kr_kurs(paar, jetzt):
    r = kraken('Ticker?pair=' + paar)
    d = next(iter(r.values()))
    p = float(d['c'][0])
    tage = kr_verlauf(paar, 1440)
    heute = jetzt.date().isoformat()
    vor = [v for d2, v in tage if d2 < heute]
    return {'p': round(p, 6 if p < 10 else 2), 'vt': vor[-1] if vor else None, 't': iso(jetzt), 'q': 'kr'}, tage


def kr_verlauf(paar, minuten):
    r = kraken(f'OHLC?pair={paar}&interval={minuten}')
    reihe = next(v for k, v in r.items() if k != 'last')
    return sorted((dt.datetime.fromtimestamp(int(x[0]), dt.timezone.utc).date().isoformat(), round(float(x[4]), 6 if float(x[4]) < 10 else 2)) for x in reihe if float(x[4]) > 0)


# ---------- Verlauf ausdünnen: letzte Monate täglich, davor ein Kurs pro Woche ----------
def ausduennen(reihe, heute):
    ab_tag = (heute - dt.timedelta(days=110)).isoformat()
    ab_woche = (heute - dt.timedelta(days=366 * 6)).isoformat()
    bis = heute.isoformat()
    wochen, tage = {}, []
    for d, v in sorted(reihe):
        if d >= bis or d < ab_woche:
            continue
        if d >= ab_tag:
            tage.append([d, v])
        else:
            j, kw, _ = dt.date.fromisoformat(d).isocalendar()
            wochen[(j, kw)] = [d, v]  # der letzte Handelstag der Woche gewinnt
    return [wochen[k] for k in sorted(wochen)] + tage


def main():
    jetzt = dt.datetime.now(dt.timezone.utc)
    lokal = jetzt.astimezone(BERLIN)
    heute = lokal.date()
    os.makedirs(AUS, exist_ok=True)
    liste = lese_liste()
    alt_k = (lade(os.path.join(ALT, 'kurse.json'), {}) or {}).get('k', {})
    alt_v = lade(os.path.join(ALT, 'verlauf.json'), {}) or {}
    ids = lade(os.path.join(ALT, 'ids.json'), {}) or {}
    wp = [x for x in liste if x not in KRYPTO]
    kr = [x for x in liste if x in KRYPTO]
    kurse = {k: v for k, v in alt_k.items() if k in liste}
    offen = lokal.weekday() < 5 and dt.time(7, 20) <= lokal.time() <= dt.time(23, 15)
    fehlt = [x for x in wp if x not in kurse]
    log(f'{lokal:%d.%m.%Y %H:%M} Uhr · {len(wp)} Wertpapiere, {len(kr)} Krypto · Börse {"offen" if offen else "zu"}')

    fehler, neu = [], 0
    # 1. Aktuelle Kurse der Wertpapiere
    if offen or ALLES or fehlt:
        ziel = wp if (offen or ALLES) else fehlt
        for n, isin in enumerate(ziel):
            try:
                e = ids.get(isin)
                if not e or not e.get('link'):
                    e = ls_suche(isin)
                    time.sleep(PAUSE)
                    if not e:
                        fehler.append(f'{isin}: bei Lang & Schwarz nicht gefunden')
                        continue
                    ids[isin] = e
                k = None
                try:
                    k = ls_seite(e['link'], jetzt, DEBUG and n < 3)
                except Exception as ex:  # noqa: BLE001
                    log(f'   {isin}: Seite nicht lesbar ({ex})')
                if not k:
                    k = ls_intraday(e['id'], jetzt)
                    if k:
                        log(f'   {isin}: Kurs aus der Tageskurve')
                if not k:
                    fehler.append(f'{isin}: kein Kurs lesbar')
                    continue
                k['q'] = 'ls'
                if k.get('vt') is None and isin in kurse:
                    k['vt'] = kurse[isin].get('vt')
                kurse[isin] = k
                neu += 1
                if DEBUG:
                    log(f'   {isin} {e.get("name", "")[:28]:28} {k["p"]:>12} € · Vortag {k.get("vt")} · {k["t"]}')
            except Exception as ex:  # noqa: BLE001
                fehler.append(f'{isin}: {type(ex).__name__} {ex}')
            time.sleep(PAUSE)

    # 2. Krypto (läuft rund um die Uhr)
    kr_tage = {}
    for sym in kr:
        try:
            kurse[sym], kr_tage[sym] = kr_kurs(KRYPTO[sym], jetzt)
            neu += 1
            if DEBUG:
                log(f'   {sym:6} {kurse[sym]["p"]:>12} € · Vortag {kurse[sym].get("vt")}')
        except Exception as ex:  # noqa: BLE001
            fehler.append(f'{sym}: {type(ex).__name__} {ex}')
        time.sleep(PAUSE)

    # 3. Verlauf: einmal am Tag komplett, sonst nur was fehlt
    v_k = {k: v for k, v in (alt_v.get('k') or {}).items() if k in liste}
    tag_neu = alt_v.get('tag') != heute.isoformat()
    versucht = alt_v.get('versucht') or ''
    darf = not versucht or (jetzt - dt.datetime.fromisoformat(versucht.replace('Z', '+00:00'))) > dt.timedelta(minutes=50)
    v_ziel = [x for x in liste if x not in v_k] if not (tag_neu and darf) and not ALLES else liste
    v_fehl = 0
    if v_ziel:
        log(f'Verlauf für {len(v_ziel)} Werte …')
        for isin in v_ziel:
            try:
                if isin in KRYPTO:
                    tage = kr_tage.get(isin) or kr_verlauf(KRYPTO[isin], 1440)
                    wochen = kr_verlauf(KRYPTO[isin], 10080)
                    erster = tage[0][0] if tage else '9999'
                    reihe = [x for x in wochen if x[0] < erster] + tage
                elif isin in ids:
                    reihe = ls_verlauf(ids[isin]['id'])
                else:
                    continue
                h = ausduennen(reihe, jetzt.date() if isin in KRYPTO else heute)
                if h:
                    v_k[isin] = h
                else:
                    v_fehl += 1
            except Exception as ex:  # noqa: BLE001
                v_fehl += 1
                fehler.append(f'{isin}: Verlauf {type(ex).__name__} {ex}')
            time.sleep(PAUSE)
    verlauf = {'v': 1, 'stand': iso(jetzt) if v_ziel else alt_v.get('stand', iso(jetzt)), 'k': v_k,
               'tag': heute.isoformat() if (v_ziel and v_fehl <= len(v_ziel) // 3) or not tag_neu else alt_v.get('tag', ''),
               'versucht': iso(jetzt) if v_ziel else versucht}

    schreib('kurse.json', {'v': 1, 'stand': iso(jetzt), 'k': kurse, 'n': len(kurse), 'fehler': len(fehler)})
    schreib('verlauf.json', verlauf)
    schreib('ids.json', ids)
    with open(os.path.join(AUS, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('Automatisch erzeugte Kursdateien für die JATOS-App. Nicht von Hand ändern, sie werden alle paar Minuten überschrieben.\n')
    log(f'{neu} Kurse neu, {len(kurse)} in der Datei, Verlauf für {len(v_k)} Werte, {len(fehler)} Fehler')
    for f in fehler[:60]:
        log('  !', f)
    if not kurse:
        sys.exit(1)


if __name__ == '__main__':
    main()
