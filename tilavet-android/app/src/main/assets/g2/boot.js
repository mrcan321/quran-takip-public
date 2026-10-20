// Tilavet Takip — G2 eklentisi yukleyici (index.html'in tek betigi).
//
// .ehpk Even uygulamasinin yerel sunucusundan acilir; cizim kodu (app.js, layout.js, sdk.js) mumkunse telefondaki
// Tilavet Takip'in koprusunden fetch ile alinip blob adresinden calistirilir → eklenti duzeltmeleri APK ile gelir,
// .ehpk'yi yeniden yuklemek gerekmez. Sayfa kopruye GECMEZ: telefonda kopru adresine sayfa gecisi
// "ERR_CONNECTION_REFUSED" oldu (APK #46-47), fetch ise localhost'a tutuyor.
// Kopruye ulasilamazsa, kopru eski surumse ya da blob import calismazsa paketteki kopya (./app.js) calisir.

const PORT = 18765;
const SAME_ORIGIN = /^https?:$/.test(location.protocol) && /^(127\.0\.0\.1|localhost)$/.test(location.hostname) &&
  Number(location.port) === PORT;
const BASES = [`http://localhost:${PORT}`, `http://127.0.0.1:${PORT}`];
// g2-kod.json "boot" alani: yukleyiciyle koprudeki kodun anlasmasi (import satirlari degisirse artir)
const BOOT_PROTOCOL = 1;

async function getText(url, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { cache: 'no-store', signal: ctl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.text();
  } finally {
    clearTimeout(timer);
  }
}

/** Koprudeki kod → {url (app.js blob), surum}; olmazsa null. */
async function fromBridge() {
  if (SAME_ORIGIN || new URLSearchParams(location.search).has('test-fetch-engel')) return null;
  for (const base of BASES) {
    let info;
    try {
      info = JSON.parse(await getText(`${base}/g2-kod.json`, 3000));
    } catch (e) {
      continue;   // bu adres tutmadi (ya da kopru kapali / eski APK: dosya yok)
    }
    if (info.boot !== BOOT_PROTOCOL) return null;
    try {
      const [layout, sdk, app] = await Promise.all(['layout.js', 'sdk.js', 'app.js'].map((f) => getText(`${base}/${f}`, 8000)));
      const blob = (s) => URL.createObjectURL(new Blob([s], { type: 'text/javascript' }));
      const layoutUrl = blob(layout);
      const sdkUrl = blob(sdk);
      if (!app.includes("from './layout.js'")) return null;
      globalThis.TT_SDK_URL = sdkUrl;
      return { url: blob(app.replace("from './layout.js'", `from '${layoutUrl}'`)), surum: info.surum };
    } catch (e) {
      console.log('[tt-g2] kopru kodu alinamadi:', String(e && e.message || e));
      return null;
    }
  }
  return null;
}

// Paketin (.ehpk) surumu: CI paketlerken g2-paket.json yazar (APK'dan sunulan sayfada yok) — eklenti sayfasinda ve
// uygulamanin ayarlarinda gorunur (Even yeni build'i almis mi)
try {
  globalThis.TT_PAKET = SAME_ORIGIN ? '' : String(JSON.parse(await getText('./g2-paket.json', 2000)).surum || '');
} catch (e) {
  globalThis.TT_PAKET = '';
}

const k = await fromBridge();
if (k) {
  globalThis.TT_KOD = `kopru-${k.surum}`;
  try {
    await import(k.url);
    console.log('[tt-g2] kod kopruden (uygulamadan):', k.surum);
  } catch (e) {
    // blob import calismadiysa (ya da modul yuklenirken hata) paketteki kopya
    console.log('[tt-g2] kopru kodu calismadi, paketteki kod:', String(e && e.message || e));
    globalThis.TT_KOD = 'paket';
    globalThis.TT_SDK_URL = undefined;
    await import('./app.js');
  }
} else {
  globalThis.TT_KOD = SAME_ORIGIN ? 'dogrudan' : 'paket';
  await import('./app.js');
}
