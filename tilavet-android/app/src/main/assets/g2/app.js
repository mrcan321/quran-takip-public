// Tilavet Takip — Even Realities G2 eklentisi (Even uygulamasinin WebView'inde calisir).
//
// Telefondaki Tilavet Takip uygulamasi okunan ayeti localhost:18765'te yayinlar (GlassesBridge, uzun yoklama);
// bu sayfa onu okur ve Even Hub SDK ile gozluge yazar. Uc duzen (layout.js):
//   - big (varsayilan, "G2 YAZI: BUYUK"): sadece meal, sigan en buyuk puntoda (Manrope, telefonda cizilip 4 goruntu
//     karosu — firmware fontu tek boy), ekranin ortasinda; zikir / ezan kartinda anlami, bosta kisa durum
//   - text ("NORMAL"): firmware yazisi, baslik (sure ayet · rekat) + 9 satir meal
//   - arabic ("G2'DE ARAPCA"): baslik + Arapca ayet goruntusu (KFGQPC; gozluk fontunda Arapca yok) + 5 satir meal
// Uzun mealde sayfa imam ilerledikce degisir; gozlukte dokunmatik kaydirma: onceki / sonraki sayfa.

import * as L from './layout.js';

const PORT = 18765;
// Gelistirici modunda sayfa dogrudan koprudan acilir (ayni kaynak); .ehpk paketinde koprunun tam adresi
const SAME_ORIGIN = /^https?:$/.test(location.protocol) && /^(127\.0\.0\.1|localhost)$/.test(location.hostname) &&
  Number(location.port) === PORT;
// .ehpk Even uygulamasinin kendi yerel sunucusundan acilir (http://127.0.0.1:<rastgele port>). Telefonda (APK #44-47
// log'lari): bu sayfadan 127.0.0.1:18765'e istek / goruntu / sayfa gecisi hic kopruye ulasmiyor (gecis
// "ERR_CONNECTION_REFUSED"), localhost:18765'e fetch ulasiyor → once localhost. Sayfa kopruye GECMEZ (APK #46-47'deki
// gecis hata sayfasinda kaliyordu); cizim kodunu APK'dan almak boot.js'in isi (fetch + blob import).
const BASES = SAME_ORIGIN ? [''] : [`http://localhost:${PORT}`, `http://127.0.0.1:${PORT}`];
let BASE = BASES[0];
const DIRECT_URL = `http://localhost:${PORT}/?kaynak=ehpk`;
// Test (tests/g2/sim_check.py --mode engel): .ehpk'de fetch'in engellenmesini taklit eder (sadece baska kaynaktayken)
const TEST_BLOCK_FETCH = !SAME_ORIGIN && new URLSearchParams(location.search).has('test-fetch-engel');
// /state surum parametresi: kopru eskisini ayirt eder (< 3: .ehpk'deki eski kod — 2 sayfa gecisi yapiyordu, 0 yazi
// boyutunu bilmiyor). kod: bu kodun nereden geldigi (boot.js: "kopru-N" APK'dan, "paket" .ehpk'nin kendi kopyasi)
const CLIENT_VERSION = 3;
const CODE_SOURCE = globalThis.TT_KOD || (SAME_ORIGIN ? 'dogrudan' : 'paket');
// .ehpk paketinin surumu (boot.js, g2-paket.json; "" = bilinmiyor / gelistirici modu)
const PACKAGE_VERSION = globalThis.TT_PAKET || '';
const POLL_WAIT_SEC = 20;
const FONT_RETRY_MS = 5000;
const RETRY_MS = 2000;

// Arapca bant: 576x112 (iki 288x112 karo), sayfada 2 satir. 32 px + ince kontur: harekeler 4 bit gri tonda da
// seciliyor (Chromium'da denendi; Even simulatorunun WebKitGTK'si harekeleri cizmiyor, telefondaki WebView Chromium)
const AR = { fontPx: 32, stroke: 0.8, gamma: 0.5, maxW: 556, right: 566, baselines: [42, 98], w: 576, h: 112 };
// Buyuk yazi: Manrope 700 (uygulamaya gomulu, OFL — koprudan /manrope.ttf); aday ayet sonuk gri; sayfa etiketi kucuk
// Karolar kenar yumusatmali (gama); soluk metin (aday, basliksiz duzen) 'dim' carpaniyla. APK #50'de iki ton denendi
// (veri ~%20 az) ama topluluk olcumune gore gonderim suresinin cogu cagri basina sabit (~104 ms, + ~4 ms/KB gray4;
// even-g2-notes performance.md) → hiz farki ihmal edilebilir, kenar kalitesi geri alindi (APK #51).
const BIG = { weight: 700, gamma: 0.7, dim: 0.6, color: '#ffffff', barW: 3, barDim: '#3a3a3a' };
const BIG_LAYOUTS = new Set(['big', 'bigh']);

const FONTS = { quran: { family: 'TTQuran', file: 'kfgqpc.ttf' }, sans: { family: 'TTSans', file: 'manrope.ttf' } };

const EV = { CLICK: 0, SCROLL_TOP: 1, SCROLL_BOTTOM: 2, DOUBLE_CLICK: 3, FG_ENTER: 4, FG_EXIT: 5, ABNORMAL_EXIT: 6, SYS_EXIT: 7 };
const EV_NAMES = {
  CLICK_EVENT: 0, SCROLL_TOP_EVENT: 1, SCROLL_BOTTOM_EVENT: 2, DOUBLE_CLICK_EVENT: 3, FOREGROUND_ENTER_EVENT: 4,
  FOREGROUND_EXIT_EVENT: 5, ABNORMAL_EXIT_EVENT: 6, SYSTEM_EXIT_EVENT: 7,
};

const S = {
  diag: { attempts: 0, fails: 0, lastError: '', base: BASE },   // telefondaki sayfada + gozlukte gosterilir
  bridge: null,
  st: null,             // son durum (/state)
  connected: false,
  manual: null,         // kullanici kaydirmasi: {key, base, page}
  arabic: { text: '', lines: [] },
  fonts: {},            // aile → true / false (yuklenemedi); yoksa henuz denenmedi
  fontLoads: {},
  fontFailAt: {},       // font yuklenemedigi an (FONT_RETRY_MS sonra yeniden)
  fitCache: new Map(),  // buyuk yazi yerlesimi: (en kucuk punto, metin) → fitBigText
  created: false,       // createStartUpPageContainer yapildi mi
  shown: null,          // gozlukteki ekran: {layout, header, headerColor, body, bodyColor, imageKey}
  tileSent: {},         // goruntu kutusu → son gonderilen baytlarin ozeti (degismeyen karo tekrar gitmez)
  screen: null,         // son hesaplanan ekran
  screenDesc: '',       // kopruye bildirilen gozluk duzeni (/state ekran)
  reportedDesc: '',     // en son ayrica bildirilen duzen (reportScreen)
  busy: false,
  dirty: false,
  active: true,         // eklenti gozlukte on planda
};

function log(...a) {
  console.log('[tt-g2]', ...a);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ kopru (telefondaki uygulama)

function errText(e) {
  if (!e) return '?';
  const s = (e.name && e.name !== 'Error' ? e.name + ': ' : '') + (e.message || String(e));
  return s.slice(0, 120);
}

let pollGen = 0;   // gecis olmayinca yeniden baslayan dongu eskisiyle ust uste calismasin

async function pollLoop() {
  const gen = ++pollGen;
  let since = -1;
  let bi = 0;
  for (;;) {
    // sayfa kopruye geciyor: yeni istek gecisle yarida kesilip hata gibi gorunmesin
    if (leaving || gen !== pollGen) return;
    BASE = BASES[bi];
    S.diag.base = BASE || location.origin;
    S.diag.attempts++;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), (POLL_WAIT_SEC + 10) * 1000);
    try {
      if (TEST_BLOCK_FETCH) throw new TypeError('test: fetch engelli');
      const r = await fetch(`${BASE}/state?since=${since}&wait=${POLL_WAIT_SEC}${clientQuery()}`,
        { cache: 'no-store', signal: ctl.signal });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const st = await r.json();
      clearTimeout(timer);
      if (gen !== pollGen) return;
      const changed = !S.connected || st.seq !== since;
      since = st.seq;
      if (!S.connected) log('kopru bagli:', S.diag.base, 'kod:', CODE_SOURCE, 'paket:', PACKAGE_VERSION || '-');
      S.connected = true;
      S.diag.fails = 0;
      S.diag.lastError = '';
      if (changed) onState(st);
    } catch (e) {
      clearTimeout(timer);
      S.diag.fails++;
      S.diag.lastError = errText(e);
      if (S.connected || S.diag.fails === 1) log('kopru baglantisi yok:', S.diag.base, S.diag.lastError);
      S.connected = false;
      since = -1;
      if (BASES.length > 1) bi = (bi + 1) % BASES.length;
      schedule();
      maybeDirect();
      await sleep(RETRY_MS);
    }
  }
}

/**
 * .ehpk'de kopruye fetch tutmazsa: goruntu istegiyle (CORS'a / fetch engeline takilmaz) kopruye erisilebiliyor mu bak;
 * erisilebiliyorsa sayfayi dogrudan kopruden ac (aynı kaynak, gelistirici modundaki gibi; Even koprusu her sayfaya eklenir).
 * Yoklama her hatada tekrarlanir: kopru kapaliyken (uygulama acik degil — APK guncellenince Android uygulamayi kapatir)
 * eklenti bekler, uygulama acilip kopru gelince kendiliginden gecer. Yoklamasiz ("kor") gecis sadece dugmeyle, ikinci
 * basista: kopru kapaliyken gecis WebView hata sayfasinda kalir, oradan geri donus yok (APK #46'da oldu).
 */
let probing = false;
// Gecis bir kez denenir: Even uygulamasi gecisi engellerse ya da dis tarayiciya yollarsa tekrar tekrar denenmesin
// (dugmeyle yine olur)
let directTried = false;
let leaving = false;
// Dugme: once yoklama; kopruye ulasilamazsa uyari, DIRECT_CONFIRM_MS icinde ikinci basis yine de gecer
let directWarnAt = 0;
const DIRECT_CONFIRM_MS = 30000;

/** Kopru goruntu yoklamasi → ok (true/false), en fazla 4 sn. */
function probeBridge(cb) {
  const img = new Image();
  let settled = false;
  const done = (ok) => {
    if (settled) return;
    settled = true;
    cb(ok);
  };
  img.onload = () => done(true);
  img.onerror = () => done(false);
  setTimeout(() => done(false), 4000);
  img.src = `http://localhost:${PORT}/ping.png?t=${Date.now()}`;
}

function maybeDirect() {
  // iki adres de denenmeden yoklama yok: fetch localhost'a tutuyorsa gecis gereksiz
  if (SAME_ORIGIN || S.connected || probing || directTried || S.diag.fails < BASES.length) return;
  probing = true;
  probeBridge((ok) => {
    probing = false;
    S.diag.probe = ok ? 'var' : 'yok';
    if (ok && !S.connected) goDirect('goruntu yoklamasi basarili, fetch engelli', 'goruntu');
  });
}

function directClick() {
  if (Date.now() - directWarnAt < DIRECT_CONFIRM_MS) {
    goDirect('dugme (yoklamasiz)', 'dugme-kor');
    return;
  }
  probeBridge((ok) => {
    if (ok) {
      goDirect('dugme', 'dugme');
      return;
    }
    directWarnAt = Date.now();
    S.diag.probe = 'yok';
    if (S.screen) drawPhonePreview(S.screen);
  });
}

/** Son care (fetch hic tutmuyor, kopru goruntu yoklamasina cevap veriyor): sayfayi kopruden ac. yol: koprunun
 * log'unda gorunur (goruntu yoklamasi / dugme). */
function goDirect(why, yol) {
  directTried = true;
  log('sayfa dogrudan kopruden aciliyor:', why);
  leaving = true;
  location.href = `${DIRECT_URL}&yol=${encodeURIComponent(yol)}`;
  // gecis olmazsa (Even uygulamasi engeller / dis tarayiciya yollar) bu sayfa calismaya devam etsin
  setTimeout(() => {
    leaving = false;
    pollLoop();
  }, 8000);
}

function onState(st) {
  if (L.ayahKey(st) !== L.ayahKey(S.st)) S.manual = null;
  S.st = st;
  if (st.showArabic && st.arabic !== S.arabic.text) prepareArabic(st.arabic);
  if (st.bigText && S.fonts[FONTS.sans.family] !== true) ensureFont(FONTS.sans).then(schedule);
  schedule();
}

// ------------------------------------------------------------------ fontlar (koprudan)

/** Font kopruden (bir kez). Yuklenemezse FONT_RETRY_MS sonra yeniden denenir: kopru kapaliyken acilan eklenti
 * (sayfa gecisi yok) kopru gelince buyuk yaziya gecebilsin — eskiden ilk hata sayfa boyunca kaliyordu (normal yazi). */
async function ensureFont(f) {
  if (S.fonts[f.family] === true) return true;
  if (S.fontLoads[f.family]) return S.fontLoads[f.family];
  if (S.fonts[f.family] === false && Date.now() - (S.fontFailAt[f.family] || 0) < FONT_RETRY_MS) return false;
  {
    S.fontLoads[f.family] = (async () => {
      try {
        // fetch ile (CSS url() Even WebView'inde koprunun adresine ulasamayabilir; fetch'in tuttugu bilinen yol)
        const r = await fetch(`${BASE}/${f.file}`, { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const face = new FontFace(f.family, await r.arrayBuffer());
        await face.load();
        document.fonts.add(face);
        S.fonts[f.family] = true;
      } catch (e) {
        log('font yuklenemedi:', f.file, String(e && e.message || e));
        S.fonts[f.family] = false;
        S.fontFailAt[f.family] = Date.now();
      }
      S.fontLoads[f.family] = null;
      return S.fonts[f.family];
    })();
  }
  return S.fontLoads[f.family];
}

function canvas2d(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return { c, ctx: c.getContext('2d') };
}

// ------------------------------------------------------------------ buyuk yazi

const measureCtx = canvas2d(8, 8).ctx;

function measureBig(s, px) {
  measureCtx.font = `${BIG.weight} ${px}px ${FONTS.sans.family}`;
  return measureCtx.measureText(s).width;
}

/** Metin → buyuk yazi yerlesimi (onbellekli; punto ayardan, /state textPx + fixedSize + onePage); font yoksa null →
 * normal duzen. */
function fitBig(text, textPx, areaH, fixed, onePage) {
  const opt = L.bigOptions(textPx, areaH, fixed, onePage);
  const key = opt.minPx + '-' + opt.maxPx + '/' + opt.h + '/' + (opt.pageMinPx || 0) + '\n' + text;
  let f = S.fitCache.get(key);
  if (!f) {
    f = L.fitBigText(text, measureBig, opt);
    if (S.fitCache.size > 64) S.fitCache.clear();
    S.fitCache.set(key, f);
  }
  return f;
}

/** Buyuk yazi sayfasi → 576 x alan canvas'i (baslikli duzende 256, degilse 288): satirlar soldan, blok dikeyde ortada;
 * birden cok sayfa varsa (basliksiz duzende) sag kenarda sayfa cubugu — baslikli duzende sayfa baslikta ("1/3"). */
function bigCanvas(screen) {
  const fit = screen.big;
  const lines = fit.pages[Math.min(screen.page, fit.pages.length - 1)] || [];
  const H = L.bigAreaHeight(screen.layout);
  const { c, ctx } = canvas2d(L.SCREEN_W, H);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, L.SCREEN_W, H);
  ctx.font = `${BIG.weight} ${fit.px}px ${FONTS.sans.family}`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  const m = ctx.measureText('ÇĞİÜŞÂgjpy');
  const asc = m.fontBoundingBoxAscent || fit.px * 0.95;
  const desc = m.fontBoundingBoxDescent || fit.px * 0.25;
  const blockH = lines.length * fit.lineH;
  // blok dikeyde ortada; sabit yazi boyutunda ustten (satirlar her ekranda ayni yerde; kisa metin sadece ust karolara
  // duser → alt karolar bos kalir, gonderilmez: 4 yerine 2 karo, gozlukte ~yari surede)
  const y0 = screen.bigFixed ? L.BIG.marginY : Math.max(L.BIG.marginY, Math.round((H - blockH) / 2));
  const inner = Math.round((fit.lineH - (asc + desc)) / 2 + asc);
  ctx.fillStyle = BIG.color;   // soluk metin karoya donusturulurken (bigTileLut) — telefondaki onizleme hep parlak
  lines.forEach((line, i) => ctx.fillText(line, L.BIG.marginX, y0 + i * fit.lineH + inner));
  if (screen.pages > 1 && screen.layout === 'big') {
    // Sayfa gostergesi (basliksiz duzen; baslikli duzende sayfa baslikta "1/3"): sag kenarda ince dikey cubuk, sayfa
    // basina bir parca (metin kenar boslugunun icinde, yaziya binmez — eski koseden "2/3" dolu sayfada yaziya biniyordu)
    const gap = 6;
    const segH = (H - gap * (screen.pages - 1)) / screen.pages;
    for (let i = 0; i < screen.pages; i++) {
      ctx.fillStyle = i === screen.page ? BIG.color : BIG.barDim;
      ctx.fillRect(L.SCREEN_W - BIG.barW, Math.round(i * (segH + gap)), BIG.barW, Math.round(segH));
    }
  }
  return c;
}

/** Buyuk yazi canvas'i → karo parlakligi: gama (kenar yumusatma korunur), soluk metinde 'dim' carpani. */
function bigTileLut(dim) {
  const lut = gammaLut(BIG.gamma);
  if (dim) for (let v = 0; v < 256; v++) lut[v] = Math.round(lut[v] * BIG.dim);
  return lut;
}

// ------------------------------------------------------------------ Arapca goruntu

async function prepareArabic(text) {
  S.arabic = { text, lines: [] };
  if (!text || !(await ensureFont(FONTS.quran))) { schedule(); return; }
  if (S.arabic.text !== text) return;   // bu arada yeni ayet geldi
  const { ctx } = canvas2d(AR.w, AR.h);
  ctx.font = `${AR.fontPx}px ${FONTS.quran.family}`;
  ctx.direction = 'rtl';
  const lines = [];
  let cur = '';
  for (const w of text.split(' ').filter(Boolean)) {
    const cand = cur ? cur + ' ' + w : w;
    if (!cur || ctx.measureText(cand).width <= AR.maxW) { cur = cand; continue; }
    lines.push(cur);
    cur = w;
  }
  if (cur) lines.push(cur);
  S.arabic.lines = lines;
  schedule();
}

/** Arapca bandin bir sayfasi → 576x112 canvas. page < 0: bos (siyah). */
function arabicCanvas(page) {
  const { c, ctx } = canvas2d(AR.w, AR.h);
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, AR.w, AR.h);
  if (page >= 0) {
    ctx.font = `${AR.fontPx}px ${FONTS.quran.family}`;
    ctx.direction = 'rtl';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = AR.stroke;
    S.arabic.lines.slice(page * L.ARABIC_LINES, (page + 1) * L.ARABIC_LINES).forEach((line, i) => {
      ctx.strokeText(line, AR.right, AR.baselines[i]);
      ctx.fillText(line, AR.right, AR.baselines[i]);
    });
  }
  return c;
}

/** Gama tablosu (Arapca goruntu: gri kenar yumusatma korunur). */
function gammaLut(gamma) {
  const lut = new Uint8Array(256);
  for (let v = 1; v < 256; v++) lut[v] = Math.min(255, Math.round(255 * Math.pow(v / 255, gamma)));
  return lut;
}

/** Canvas → karolar (Gray8, kutu boyutunda). (ox, oy): canvas'in ekrandaki sol ust kosesi; lut: parlaklik tablosu. */
function tilesFrom(c, tiles, ox, oy, lut) {
  const rgba = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
  return tiles.map((t) => {
    const g = new Uint8Array(t.w * t.h);
    for (let y = 0; y < t.h; y++) {
      const row = (t.y - oy + y) * c.width;
      for (let x = 0; x < t.w; x++) g[y * t.w + x] = lut[rgba[(row + t.x - ox + x) * 4]];
    }
    return g;
  });
}

/** Karo ozeti (FNV-1a) — degismeyen karo tekrar gonderilmez (BLE). */
function digest(bytes) {
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i++) h = Math.imul(h ^ bytes[i], 0x01000193);
  return (h >>> 0).toString(16) + ':' + bytes.length;
}

// ------------------------------------------------------------------ gozluk

const TILE_BASE = { arabic: 3, big: 10, bigh: 10 };

function pageDef(screen) {
  const Ld = L.LAYOUTS[screen.layout];
  const box = (b) => ({ xPosition: b.x, yPosition: b.y, width: b.w, height: b.h });
  const imageObject = Ld.tiles.map((t, i) => ({ containerID: TILE_BASE[screen.layout] + i,
    containerName: screen.layout + i, ...box(t) }));
  if (BIG_LAYOUTS.has(screen.layout)) {
    // bos metin kutusu sadece dokunmatik olaylari icin, goruntulerin arkasinda (zOrderIndex ya hepsinde ya hicbirinde);
    // baslikli duzende ustte baslik metni (gozlugun kendi yazisi, aninda degisir)
    const textObject = [{ containerID: 2, containerName: 'body', ...box(Ld.body), paddingLength: 0, content: ' ',
      isEventCapture: 1, zOrderIndex: 0 }];
    if (Ld.header) {
      textObject.push({ containerID: 1, containerName: 'hdr', ...box(Ld.header), paddingLength: L.PADDING,
        content: screen.header, textColor: screen.headerColor, isEventCapture: 0, zOrderIndex: 1 });
    }
    imageObject.forEach((im, i) => { im.zOrderIndex = textObject.length + i; });
    return { containerTotalNum: textObject.length + imageObject.length, textObject, imageObject };
  }
  const textObject = [
    { containerID: 1, containerName: 'hdr', ...box(Ld.header), paddingLength: L.PADDING, content: screen.header,
      textColor: screen.headerColor, isEventCapture: 0 },
    { containerID: 2, containerName: 'body', ...box(Ld.body), paddingLength: L.PADDING, content: screen.body,
      textColor: screen.bodyColor, isEventCapture: 1 },
  ];
  const def = { containerTotalNum: textObject.length + imageObject.length, textObject };
  if (imageObject.length) def.imageObject = imageObject;
  return def;
}

/** Goruntu icerigi anahtari (degisince karolar yeniden cizilir); '' = goruntu yok. */
function imageKey(screen) {
  if (screen.layout === 'arabic') {
    return screen.arabicPage < 0 ? 'bos' : `${S.arabic.text.length}:${L.ayahKey(S.st)}:${screen.arabicPage}`;
  }
  if (BIG_LAYOUTS.has(screen.layout)) {
    const fit = screen.big;
    return `${fit.px}|${screen.page}/${screen.pages}|${screen.bigDim}|${(fit.pages[screen.page] || []).join('\n')}`;
  }
  return '';
}

/** /state'e eklenen eklenti bilgisi: surum (kopru eski .ehpk kodunu ayirt eder) + gozluge son cizilen duzen. */
function clientQuery() {
  return `&surum=${CLIENT_VERSION}&kod=${encodeURIComponent(CODE_SOURCE)}` +
    (PACKAGE_VERSION ? '&paket=' + encodeURIComponent(PACKAGE_VERSION) : '') +
    (S.screenDesc ? '&ekran=' + encodeURIComponent(S.screenDesc) : '');
}

/** Gozluge ekran aktarim suresi (tani; koprunun log'unda "eklenti aktarim: 4 karo 820 ms"). */
function reportTransfer(tiles, ms) {
  S.diag.transfer = `${tiles} karo ${ms} ms`;
  log('aktarim:', S.diag.transfer);
  if (!S.connected) return;
  fetch(`${BASE}/state?since=-1&wait=0${clientQuery()}&aktarim=${tiles}x${ms}`, { cache: 'no-store' }).catch(() => {});
}

/** Duzen degisince hemen bildir (uzun yoklama 20 sn bekleyebilir); yanit kullanilmaz. */
function reportScreen() {
  if (!S.connected || S.screenDesc === S.reportedDesc) return;
  S.reportedDesc = S.screenDesc;
  fetch(`${BASE}/state?since=-1&wait=0${clientQuery()}`, { cache: 'no-store' }).catch(() => {});
}

/** Kopruye bildirilen gozluk duzeni (uygulamada Ayarlar → G2 GÖZLÜK satirinda gorunur): "buyuk 48px", "normal", "arapca". */
function screenDesc(screen) {
  if (screen.blank) return S.screenDesc || 'bos';   // ses kesildi (bos ekran): ayardaki duzen degismedi
  if (BIG_LAYOUTS.has(screen.layout)) {
    return `buyuk ${screen.big.px}px` + (screen.bigFixed ? ' sabit' : '') + (S.st && S.st.onePage ? ' tek' : '');
  }
  return screen.layout === 'arabic' ? 'arapca' : 'normal';
}

function schedule() {
  S.dirty = true;
  if (!S.busy) flush();
}

async function flush() {
  S.busy = true;
  try {
    while (S.dirty) {
      S.dirty = false;
      const screen = L.buildScreen(S.st, {
        connected: S.connected,
        arabicLineCount: S.arabic.text === (S.st && S.st.arabic) ? S.arabic.lines.length : 0,
        manual: S.manual,
        fitBig: S.fonts[FONTS.sans.family] === true ? fitBig : null,
        diag: S.connected ? '' : S.diag.lastError,
      });
      S.screen = screen;
      S.screenDesc = S.connected && S.st && S.bridge ? screenDesc(screen) : '';
      reportScreen();
      drawPhonePreview(screen);
      if (S.bridge && S.active) await apply(screen);
    }
  } catch (e) {
    log('gozluk yazma hatasi:', String(e && e.message || e));
    S.shown = null;   // sonraki turda tum ekran yeniden kurulur
  } finally {
    S.busy = false;
  }
}

async function apply(screen) {
  const b = S.bridge;
  const prev = S.shown;
  if (!prev || prev.layout !== screen.layout) {
    const def = pageDef(screen);
    if (!S.created) {
      const r = await b.createStartUpPageContainer(def);
      S.created = true;
      log('ilk ekran:', screen.layout, r);
      // sayfa kopruden yeniden acildiysa (dogrudan gecis) ilk ekran onceki sayfada kurulmus olabilir: yeniden kur
      if (r !== 0 && r !== 'success') log('ilk ekran yeniden kuruldu:', await b.rebuildPageContainer(def));
    } else {
      const ok = await b.rebuildPageContainer(def);
      log('ekran yeniden kuruldu:', screen.layout, ok);
    }
    S.shown = { layout: screen.layout, header: screen.header, headerColor: screen.headerColor, body: screen.body,
      bodyColor: screen.bodyColor, imageKey: null };
    S.tileSent = {};
  } else if (screen.layout !== 'big') {
    // baslik (metin ve baslikli buyuk yazi duzeni) — gozlugun kendi yazisi, aninda
    if (prev.header !== screen.header || prev.headerColor !== screen.headerColor) {
      await b.textContainerUpgrade({ containerID: 1, containerName: 'hdr', content: screen.header,
        textColor: screen.headerColor });
      prev.header = screen.header;
      prev.headerColor = screen.headerColor;
    }
    if (screen.layout !== 'bigh' && (prev.body !== screen.body || prev.bodyColor !== screen.bodyColor)) {
      await b.textContainerUpgrade({ containerID: 2, containerName: 'body', content: screen.body,
        textColor: screen.bodyColor });
      prev.body = screen.body;
      prev.bodyColor = screen.bodyColor;
    }
  }
  const key = imageKey(screen);
  if (key && S.shown.imageKey !== key) {
    const Ld = L.LAYOUTS[screen.layout];
    let tiles;
    if (BIG_LAYOUTS.has(screen.layout)) {
      const c = bigCanvas(screen);
      drawPhoneCanvas('pv-big', c);
      tiles = tilesFrom(c, Ld.tiles, 0, Ld.tiles[0].y, bigTileLut(screen.bigDim));
    } else {
      const c = arabicCanvas(screen.arabicPage);
      drawPhoneCanvas('pv-ar', c);
      tiles = tilesFrom(c, Ld.tiles, 0, Ld.tiles[0].y, gammaLut(AR.gamma));
    }
    const t0 = Date.now();
    let sent = 0;
    for (let i = 0; i < tiles.length; i++) {
      const id = TILE_BASE[screen.layout] + i;
      const d = digest(tiles[i]);
      if (S.tileSent[id] === d) continue;
      // bu arada yeni ekran geldiyse eskinin kalan karolarini gonderme: dogrudan yenisine gec (ara ayetler / hizli
      // degisimlerde gozluk eski ekrani bitirmeye ugrasmasin). imageKey yazilmaz → yeni ekran farkli karolari gonderir.
      if (sent > 0 && S.dirty) {
        log('eski ekran yarida birakildi:', sent, 'karo gonderilmisti');
        return;
      }
      const r = await b.updateImageRawData({ containerID: id, containerName: screen.layout + i, imageData: tiles[i] });
      if (r !== 'success' && r !== 0 && r !== true) log('goruntu gonderilemedi:', id, r);
      else S.tileSent[id] = d;
      sent++;
    }
    S.shown.imageKey = key;
    if (sent) reportTransfer(sent, Date.now() - t0);
  }
}

function eventType(ev) {
  const src = ev && (ev.textEvent || ev.sysEvent || ev.listEvent);
  if (!src || src.eventType === undefined || src.eventType === null) {
    // CLICK (0) bazen alan hic gonderilmeden gelir
    return src ? EV.CLICK : null;
  }
  const t = src.eventType;
  if (typeof t === 'number') return t;
  if (typeof t === 'string') return t in EV_NAMES ? EV_NAMES[t] : Number(t);
  return null;
}

function onGlassesEvent(ev) {
  const t = eventType(ev);
  if (t === null) return;
  const sc = S.screen;
  if (t === EV.SCROLL_TOP || t === EV.SCROLL_BOTTOM) {
    if (!sc || sc.pages <= 1 || !(S.st && S.st.surah)) return;
    const page = Math.min(sc.pages - 1, Math.max(0, sc.page + (t === EV.SCROLL_BOTTOM ? 1 : -1)));
    if (page === sc.page) return;
    S.manual = { key: L.ayahKey(S.st), base: sc.autoPage, page };
    schedule();
  } else if (t === EV.FG_EXIT) {
    S.active = false;
  } else if (t === EV.FG_ENTER) {
    S.active = true;
    S.shown = null;
    schedule();
  } else if (t === EV.SYS_EXIT || t === EV.ABNORMAL_EXIT) {
    S.active = false;
  }
}

async function connectGlasses() {
  let sdk;
  try {
    sdk = await import(globalThis.TT_SDK_URL || './sdk.js');   // boot.js kopruden yukleyince blob adresi
  } catch (e) {
    log('SDK yuklenemedi:', String(e && e.message || e));
    return;
  }
  try {
    S.bridge = await Promise.race([
      sdk.waitForEvenAppBridge(),
      sleep(8000).then(() => { throw new Error('Even uygulamasi yok (8 sn)'); }),
    ]);
  } catch (e) {
    log('gozluk koprusu yok:', String(e && e.message || e));
    setPhoneGlasses('Even uygulaması dışında açıldı — sadece önizleme');
    return;
  }
  setPhoneGlasses('gözlüğe yazılıyor');
  S.bridge.onEvenHubEvent(onGlassesEvent);
  log('gozluk hazir');
  schedule();
}

// ------------------------------------------------------------------ telefondaki sayfa (Even uygulamasinda acik kalir)

function $(id) {
  return document.getElementById(id);
}

function setPhoneGlasses(text) {
  const el = $('glasses');
  if (el) el.textContent = text;
}

function drawPhonePreview(screen) {
  const link = $('link');
  if (link) {
    link.textContent = S.connected ? 'Tilavet Takip bağlı'
      : "Tilavet Takip'e ulaşılamıyor — telefonda uygulamayı açın (Ayarlar → G2 GÖZLÜK: AÇIK). Uygulama güncellenince " +
        'bir kez açmak gerekir; açılınca eklenti kendiliğinden bağlanır.';
    link.className = S.connected ? 'ok' : 'wait';
  }
  const diag = $('diag');
  if (diag) {
    diag.textContent = (PACKAGE_VERSION ? `eklenti ${PACKAGE_VERSION} · ` : '') +
      `sayfa: ${location.origin || location.protocol} · köprü: ${S.diag.base} · deneme ${S.diag.attempts}` +
      (S.diag.lastError ? ` · son hata: ${S.diag.lastError}` : '') +
      (!SAME_ORIGIN && !S.connected && S.diag.probe ? ` · köprü yoklaması: ${S.diag.probe}` : '') +
      (BIG_LAYOUTS.has(screen.layout) ? ` · gözlükte ${screen.big.px} px` +
        (screen.pages > 1 ? `, sayfa ${screen.page + 1}/${screen.pages}` : '') : '') +
      (S.diag.transfer ? ` · son aktarım ${S.diag.transfer}` : '');
  }
  const direct = $('direct');
  if (direct) {
    direct.style.display = SAME_ORIGIN || S.connected ? 'none' : 'inline-block';
    direct.textContent = Date.now() - directWarnAt < DIRECT_CONFIRM_MS
      ? 'Köprü yanıt vermiyor — yine de bağlan' : 'Köprüye doğrudan bağlan';
  }
  const big = BIG_LAYOUTS.has(screen.layout);
  const show = (id, on) => { const el = $(id); if (el) el.style.display = on ? 'block' : 'none'; };
  show('pv-hdr', !big || screen.layout === 'bigh');
  show('pv-body', !big);
  show('pv-ar', screen.layout === 'arabic');
  show('pv-big', big);
  if (big) {
    if (!S.bridge) drawPhoneCanvas('pv-big', bigCanvas(screen));   // gozluk yokken de onizleme
    const hb = $('pv-hdr');
    if (hb && screen.layout === 'bigh') hb.textContent = screen.header;
    return;
  }
  const h = $('pv-hdr');
  const bd = $('pv-body');
  if (h) h.textContent = screen.header;
  if (bd) bd.textContent = screen.body;
}

function drawPhoneCanvas(id, canvas) {
  const pv = $(id);
  if (!pv) return;
  const ctx = pv.getContext('2d');
  ctx.clearRect(0, 0, pv.width, pv.height);
  ctx.drawImage(canvas, 0, 0);
}

// ------------------------------------------------------------------ baslat

{
  const direct = $('direct');
  if (direct) direct.addEventListener('click', directClick);
}

schedule();   // buyuk yazi fontu ilk durumla (onState) — kopru yokken istek atilmasin
pollLoop();
connectGlasses();
