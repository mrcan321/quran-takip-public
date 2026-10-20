// Tilavet Takip — G2 gozluk ekran duzeni (saf fonksiyonlar; Even SDK'ya ve DOM'a dokunmaz).
// Testler: tests/g2/layout.test.mjs (node --test, test kapisinin g2 kumesi).
//
// G2 ekrani 576x288, firmware (LVGL) yazi tipi tek boy, satir yuksekligi 27 px. Firmware satiri kendisi de kirar;
// biz satirlari burada kirip "\n" ile birlestiriyoruz ki sayfa (ve "1/3") onceden bilinsin ve kutudan tasmasin.
// Genislik tablosu: @evenrealities/pretext 0.1.4 (MIT) firmware font olculerinden (getAdvW, (adv+8)>>4) uretildi;
// kerning yok sayildi → olcum gercekten ~%4 genis (kirma hep guvenli tarafta). 0 = fontta yok.

export const SCREEN_W = 576;
export const SCREEN_H = 288;
export const LINE_H = 27;
/** Metin kutusu en fazla 999 bayt (firmware) — pay birakildi. */
export const TEXT_MAX_BYTES = 990;
/** Satir kirma siniri (px): kutu 576 - ic bosluk - guvenlik payi. */
export const WRAP_W = 548;
/** Metin kutusu ic boslugu (px). Kutu yuksekligi >= satir * 27 + 2 * PADDING olmali, yoksa firmware kaydirma cubugu cizer. */
export const PADDING = 2;

const WIDTHS = [
  [0x20, [
    5,4,6,15,13,14,16,4,7,7,8,10,5,10,5,8,12,8,12,12,13,12,12,13,12,12,4,5,10,10,10,12,17,14,12,12,12,
    11,11,12,12,6,9,12,10,16,12,12,12,12,12,12,12,12,14,16,14,14,13,7,8,7,10,9,0,12,11,11,11,11,10,11,
    11,4,7,10,4,16,11,11,11,11,8,11,8,12,12,16,12,12,10,9,4,9,16
  ]],
  [0xa0, [
    5,4,12,14,11,12,4,12,0,18,8,12,12,7,13,0,7,10,8,8,0,0,16,5,0,6,8,12,15,15,16,12,14,14,14,14,14,14,
    19,12,11,11,11,11,6,6,8,8,13,12,12,12,12,12,12,10,13,12,12,12,12,14,12,11,12,12,12,12,12,12,16,11,
    11,11,11,11,6,6,8,8,12,11,11,11,11,11,11,10,12,12,12,12,12,12,11,12,14,12,14,12,14,12,12,11,0,0,12,
    11,12,11,12,14,13,13,11,11,12,12,11,11,11,11,11,11,12,12,12,11,12,11,12,11,12,12,16,12,8,8,8,8,12,
    12,6,6,6,4,11,7,12,12,12,10,12,10,6,10,5,10,7,10,7,12,8,12,11,12,11,12,11,12,12,11,12,11,12,12,12,
    11,18,16,12,8,12,8,12,8,12,11,12,12,12,11,12,11,12,8,12,8,12,8,12,12,12,12,0,0,12,12,12,12,12,12,16,
    16,14,12,14,13,10,13,10,13,10,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,11,0,0,0,0,0,0,0,0,0,0,0,0,0,14,
    12,0,0,0,0,0,0,0,0,0,0,0,0,0,14,13,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,12,0,8,
    0,11,0,12,0,12,0,12,0,12,0,12,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,12,11,12,8,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,7,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
  ]],
  [0x2010, [
    20,0,0,15,15,20,20,0,5,5,5,0,8,8,9,0,12,12,9,0,0,20,10,0,0,0,0,0,0,0,0,0,17,0,5,8,0,20,0,0,0,8,8,20,
    0,0,0,0,0,0,0,0,11,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
  ]],
];

/** Fontta olmayan sik karakterlerin karsiligi (once bu, sonra NFD ile tabandaki harf). */
const SUBST = {
  '`': "'", '‘': "'", '’': "'", 'ʼ': "'", 'ʾ': "'", 'ʿ': "'", '′': "'",
  '“': '"', '”': '"', '„': '"', '″': '"', '‑': '-', '‒': '-', '⁃': '-',
  '…': '...', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ', ' ': ' ',
  '​': '', '‌': '', '‍': '', '‎': '', '‏': '', '﻿': '', '­': '',
};
const UNKNOWN_W = 12;

/** Karakter genisligi (px); fontta yoksa 0. */
export function charWidth(cp) {
  for (const [start, w] of WIDTHS) {
    if (cp >= start && cp < start + w.length) return w[cp - start];
  }
  return 0;
}

/** Firmware fontunda cizilemeyen karakterleri degistir (yoksa yer tutucu kutu cizilir). Satir sonlari korunur. */
export function sanitize(text) {
  let out = '';
  for (const ch of String(text ?? '')) {
    if (ch === '\n') { out += ch; continue; }
    if (ch === '\t' || ch === '\r') { out += ' '; continue; }
    if (ch in SUBST) { out += SUBST[ch]; continue; }
    const cp = ch.codePointAt(0);
    if (charWidth(cp) > 0) { out += ch; continue; }
    const base = ch.normalize('NFD').replace(/[̀-ͯ]/g, '');
    if (base && [...base].every((c) => charWidth(c.codePointAt(0)) > 0)) { out += base; continue; }
    // emoji / Arapca / bilinmeyen: atla
  }
  return out.replace(/ {2,}/g, ' ');
}

/** Buyuk yazi (canvas, telefondaki font): sadece gorunmez / kontrol karakterleri temizlenir. */
export function sanitizeBig(text) {
  return String(text ?? '').replace(/[\u200b-\u200f\ufeff\u00ad]/g, '').replace(/[\t\r]/g, ' ').replace(/ {2,}/g, ' ');
}

export function textWidth(s) {
  let w = 0;
  for (const ch of s) { const cw = charWidth(ch.codePointAt(0)); w += cw || UNKNOWN_W; }
  return w;
}

export function utf8Bytes(s) {
  return new TextEncoder().encode(s).length;
}

/** Bosluklardan satir kir (cok uzun kelime harf harf bolunur); "\n" paragraf sonu. */
export function wrap(text, maxW = WRAP_W) {
  const lines = [];
  for (const para of sanitize(text).split('\n')) {
    const words = para.split(' ').filter((w) => w.length > 0);
    if (words.length === 0) { lines.push(''); continue; }
    const spaceW = textWidth(' ');
    let cur = '';
    let curW = 0;
    for (let word of words) {
      let ww = textWidth(word);
      if (cur && curW + spaceW + ww <= maxW) { cur += ' ' + word; curW += spaceW + ww; continue; }
      if (!cur && ww <= maxW) { cur = word; curW = ww; continue; }
      if (cur) { lines.push(cur); cur = ''; curW = 0; }
      while (ww > maxW) {
        let cut = '';
        let cw = 0;
        for (const ch of word) { const w = textWidth(ch); if (cw + w > maxW) break; cut += ch; cw += w; }
        lines.push(cut);
        word = word.slice(cut.length);
        ww = textWidth(word);
      }
      cur = word;
      curW = ww;
    }
    lines.push(cur);
  }
  return lines;
}

/** Tek satira sigdir (sigmazsa sonu "..."). */
export function fitLine(s, maxW = WRAP_W) {
  s = sanitize(s).replace(/\n/g, ' ');
  if (textWidth(s) <= maxW) return s;
  let out = '';
  for (const ch of s) { if (textWidth(out + ch + '...') > maxW) break; out += ch; }
  return out.trimEnd() + '...';
}

/** Satirlari birlestir; bayt sinirini asarsa sondan satir at. */
export function joinLines(lines) {
  let take = lines.length;
  let s = lines.slice(0, take).join('\n');
  while (take > 1 && utf8Bytes(s) > TEXT_MAX_BYTES) { take--; s = lines.slice(0, take).join('\n'); }
  return s.trim() ? s : ' ';
}

/**
 * Iki duzen: "text" (baslik + 9 satir meal) ve "arabic" (baslik + 576x112 Arapca goruntu bandi + 5 satir meal).
 * Goruntu kutusu en fazla 288x144 → bant iki karo. Olay yakalayan tek kutu govde metni (kaydirma = sayfa).
 */
export const LAYOUTS = {
  text: {
    header: { x: 0, y: 0, w: SCREEN_W, h: 31 },
    body: { x: 0, y: 32, w: SCREEN_W, h: 256 },
    bodyLines: 9,
    tiles: [],
  },
  arabic: {
    header: { x: 0, y: 0, w: SCREEN_W, h: 31 },
    body: { x: 0, y: 146, w: SCREEN_W, h: 142 },
    bodyLines: 5,
    tiles: [{ x: 0, y: 32, w: 288, h: 112 }, { x: 288, y: 32, w: 288, h: 112 }],
  },
  // buyuk yazi + baslik (Ayarlar → G2'DE SURE / AYET ADI): ustte gozlugun kendi yazisiyla "Bakara 2:255 · 1/3"
  // (aninda degisir, goruntu gondermez — ADAY da baslikta, kilit dogrulaninca karolar yeniden gitmez), altinda 576x256
  // buyuk yazi (4 x 288x128 karo)
  bigh: {
    header: { x: 0, y: 0, w: SCREEN_W, h: 31 },
    body: { x: 0, y: 32, w: SCREEN_W, h: SCREEN_H - 32 },
    bodyLines: 0,
    tiles: [
      { x: 0, y: 32, w: 288, h: 128 }, { x: 288, y: 32, w: 288, h: 128 },
      { x: 0, y: 160, w: 288, h: 128 }, { x: 288, y: 160, w: 288, h: 128 },
    ],
  },
  // buyuk yazi: tum ekran 4 goruntu karosu; metin kutusu sadece dokunmatik olaylari icin (bos, arkada)
  big: {
    header: null,
    body: { x: 0, y: 0, w: SCREEN_W, h: SCREEN_H },
    bodyLines: 0,
    tiles: [
      { x: 0, y: 0, w: 288, h: 144 }, { x: 288, y: 0, w: 288, h: 144 },
      { x: 0, y: 144, w: 288, h: 144 }, { x: 288, y: 144, w: 288, h: 144 },
    ],
  },
};
/** Arapca bandinda sayfa basina satir. */
export const ARABIC_LINES = 2;

/**
 * Buyuk yazi (varsayilan, kullanici: "sadece meal, mumkun oldukca buyuk"): firmware fontu tek boy (27 px satir), daha
 * buyugu icin meal telefonda cizilip 4 goruntu karosu (288x144, ekranin tamami) olarak gider. Punto: metni tek sayfaya
 * sigdiran en buyugu (maxPx..minPx); minPx'te de sigmazsa sayfalar. Blok dikeyde ortada.
 * minPx = Ayarlar → G2 YAZI BOYUTU (/state textPx, BIG_PX araliginda; APK #46'ya kadar sabit 34 — kullanici: "yazilar
 * istedigim buyuklukte degil"). Satir 1.16 em: Manrope'ta sapkali buyuk harf ~0.93 em, kuyruk ~0.22 em.
 */
export const BIG = { minPx: 48, maxPx: 120, step: 2, lineH: 1.16, marginX: 6, marginY: 4, w: SCREEN_W, h: SCREEN_H };
/** Ayardaki en kucuk punto araligi (GlassesState.MIN/MAX/DEFAULT_TEXT_PX ile ayni); cift sayi (adim 2). */
export const BIG_PX = { min: 30, max: 80, def: 48 };
export const BIG_TILES = LAYOUTS.big.tiles;

/**
 * /state textPx → fitBigText secenekleri (gecersizse varsayilan); h: yazi alani yuksekligi (baslikli duzende 256);
 * fixed: Ayarlar → G2 SABİT YAZI BOYUTU — her metin tam bu puntoda (kisa metin buyutulmez, uzun meal kucultulmez,
 * sayfalara bolunur; kullanici: "hepsinde font boyutu ayni olsun").
 */
export function bigOptions(textPx, h = SCREEN_H, fixed = false) {
  const n = Math.round(Number(textPx));
  const px = !Number.isFinite(n) || n <= 0 ? BIG.minPx : Math.min(BIG_PX.max, Math.max(BIG_PX.min, n - (n % 2)));
  if (fixed) return { ...BIG, minPx: px, maxPx: px, h };
  return px === BIG.minPx && h === BIG.h ? BIG : { ...BIG, minPx: px, h };
}

/** Buyuk yazi duzeninin yazi alani yuksekligi (karolarin kapladigi). */
export function bigAreaHeight(layoutName) {
  const t = LAYOUTS[layoutName].tiles;
  return t[t.length - 1].y + t[t.length - 1].h - t[0].y;
}

/**
 * Buyuk yazi yerlesimi: {px, lineH, perPage, pages: [[satir...]...]}. measure(metin, px) → piksel genislik
 * (eklentide canvas measureText; testte yaklasik). "\n" paragraf sonu. Satira sigmayan tek kelime tireyle bolunur.
 */
export function fitBigText(text, measure, opt = BIG) {
  const paras = String(text ?? '').trim().split('\n');
  const maxW = opt.w - 2 * opt.marginX;
  // satirlar; out.split: satira sigmayan kelime bolundu (tek sayfa aramasinda o punto atlanir, kelime bolmeyen
  // daha kucugu secilir — "Dinlen- iyor" olmasin; sadece en kucuk puntoda kelime bolunur)
  const wrapAt = (px) => {
    const out = [];
    out.split = false;
    for (const para of paras) {
      const words = para.split(' ').filter((w) => w.length > 0);
      let cur = '';
      for (let word of words) {
        const cand = cur ? cur + ' ' + word : word;
        if (measure(cand, px) <= maxW) { cur = cand; continue; }
        if (cur) { out.push(cur); cur = ''; }
        while (measure(word, px) > maxW) {
          let cut = '';
          for (const ch of word) { if (measure(cut + ch + '-', px) > maxW) break; cut += ch; }
          if (!cut) cut = [...word][0];
          out.push(cut + '-');
          out.split = true;
          word = word.slice(cut.length);
        }
        cur = word;
      }
      if (cur) out.push(cur);
    }
    if (!out.length) out.push('');
    return out;
  };
  const perPageAt = (px) => Math.max(1, Math.floor((opt.h - 2 * opt.marginY) / Math.round(px * opt.lineH)));
  for (let px = opt.maxPx; px >= opt.minPx; px -= opt.step) {
    const lines = wrapAt(px);
    const per = perPageAt(px);
    if (lines.length <= per && (!lines.split || px === opt.minPx)) {
      return { px, lineH: Math.round(px * opt.lineH), perPage: per, pages: [[...lines]] };
    }
  }
  const px = opt.minPx;
  const lines = wrapAt(px);
  const per = perPageAt(px);
  // satirlar sayfalara esit dagilir, farki en fazla 1 (4 satir / 3'luk sayfa → 2 + 2; son sayfada tek satir kalmasin)
  const nPages = Math.ceil(lines.length / per);
  const base = Math.floor(lines.length / nPages);
  const extra = lines.length % nPages;
  const pages = [];
  for (let k = 0, i = 0; k < nPages; k++) {
    const n = base + (k < extra ? 1 : 0);
    pages.push(lines.slice(i, i + n));
    i += n;
  }
  return { px, lineH: Math.round(px * opt.lineH), perPage: per, pages };
}

export const BRIGHT = { header: 3, body: 4, dim: 3 };

const APP = 'Tilavet Takip';

/** Basligi sigdir: once tam, sigmazsa rekat durusu ("· KIYAM") atilir, sonra rekat tamamen, en son kesilir. */
function headerLine(main, rakat, pageTag) {
  const tail = pageTag ? '  ' + pageTag : '';
  const cands = [];
  if (rakat) {
    cands.push(main + '  ·  ' + rakat + tail);
    const short = rakat.split(' · ')[0];
    if (short !== rakat) cands.push(main + '  ·  ' + short + tail);
  }
  cands.push(main + tail);
  for (const c of cands) { const s = sanitize(c); if (textWidth(s) <= WRAP_W) return s; }
  return fitLine(main, WRAP_W - textWidth(tail)) + tail;
}

/** Ekrandaki ayet etiketi "A'râf: 55" — once sure adi, sonra ayet (uygulamadaki MushafData.ayahTag ile ayni; kullanici:
 * "7:55 gibi gostermesin"). Sure adi yoksa "Sure 7: 55". */
export function ayahLabel(st) {
  return `${st.surahName || 'Sure ' + st.surah}: ${st.ayah}`;
}

export function ayahKey(st) {
  return st && st.surah ? st.surah + ':' + st.ayah : '';
}

/** Sayfa: imamin ilerlemesine gore; kullanici kaydirdiysa (manual) o sayfa, ilerleme yeni sayfaya gecene kadar. */
function pickPage(st, pages, manual) {
  const progress = Math.min(1, Math.max(0, Number(st.progress) || 0));
  const auto = Math.min(pages - 1, Math.floor(progress * pages));
  const m = manual;
  const page = m && m.key === ayahKey(st) && m.base === auto ? Math.min(pages - 1, Math.max(0, m.page)) : auto;
  return { page, auto };
}

/**
 * Gozluk ekrani: {layout, header, headerColor, body, bodyColor, page, pages, arabicPage, arabicPages, autoPage,
 * big, bigDim}.
 *  st: koprudeki durum (/state JSON) ya da null; ui: {connected, arabicLineCount, manual: {key, base, page},
 *  fitBig: (metin, textPx, alanYuksekligi, sabit) → fitBigText sonucu (buyuk yazi fontu hazirsa; yoksa normal metin duzeni)}.
 * Uzun mealde sayfa imamin ayetteki ilerlemesiyle (progress) secilir; kullanici kaydirdiysa (manual) o sayfa,
 * ta ki ilerleme yeni bir sayfaya gecene ya da ayet degisene kadar.
 * Buyuk yazi duzeninde (st.bigText, Arapca kapali) sadece metin cizilir: meal / zikir-ezan anlami / kisa durum.
 */
export function buildScreen(st, ui = {}) {
  const layoutName = !(ui.connected && st) ? 'text'
    : st.showArabic ? 'arabic' : st.bigText && ui.fitBig ? (st.bigHeader === false ? 'big' : 'bigh') : 'text';
  // Ses kesildi (/state blank, uygulamada TextHold): ayet metni kalkti → bos ekran, ustte rekat / durus (gozlugun kendi
  // yazisi; goruntu karolari tek seferde yeniden kurulumla silinir). Zikir / ezan karti varsa o gosterilir.
  if (ui.connected && st && st.blank && st.listening && !st.noteTitle) {
    return {
      layout: 'text', header: headerLine((st.rakat || APP) + (st.sim ? ' · SİM' : ''), '', ''), headerColor: BRIGHT.header,
      body: ' ', bodyColor: BRIGHT.body, page: 0, pages: 1, autoPage: 0, arabicPage: -1, arabicPages: 0, big: null,
      bigDim: false, bigFixed: false, blank: true,
    };
  }
  const L = LAYOUTS[layoutName];
  const out = {
    layout: layoutName, header: APP, headerColor: BRIGHT.header, body: ' ', bodyColor: BRIGHT.body,
    page: 0, pages: 1, autoPage: 0, arabicPage: -1, arabicPages: 0, big: null, bigDim: false, bigFixed: false,
  };
  if (layoutName === 'big' || layoutName === 'bigh') {
    const withHeader = layoutName === 'bigh';
    const fit = (t) => ui.fitBig(sanitizeBig(t), st.textPx, bigAreaHeight(layoutName), st.fixedSize === true);
    out.bigFixed = st.fixedSize === true;
    const rakat = st.rakat || '';
    out.header = ' ';
    let text;
    if (st.noteTitle) {
      text = [st.noteReading, st.noteTurkish].filter(Boolean).join('\n') || st.noteTitle;
      if (withHeader) out.header = headerLine(st.noteTitle, rakat, '');
    } else if (!st.listening) {
      text = 'Dinleme kapalı';
      if (withHeader) out.header = headerLine(APP, '', '');
    } else if (!st.surah) {
      text = st.status || 'Dinleniyor';
      if (withHeader) out.header = headerLine(APP + (st.sim ? ' · SİM' : ''), rakat, '');
    }
    if (text !== undefined) {
      out.big = fit(text);
      out.pages = out.big.pages.length;
      return out;
    }
    out.big = fit(st.meal || '(meal yok)');
    out.pages = out.big.pages.length;
    const { page, auto } = pickPage(st, out.pages, ui.manual);
    out.page = page;
    out.autoPage = auto;
    if (withHeader) {
      // ADAY baslikta (soluk baslik); buyuk yazi parlak kalir → kilit dogrulaninca karolar yeniden gonderilmez
      const main = ayahLabel(st) + (st.tentative ? ' · ADAY' : '');
      out.header = headerLine(main, rakat, out.pages > 1 ? `${page + 1}/${out.pages}` : '');
      out.headerColor = st.tentative ? BRIGHT.dim - 1 : BRIGHT.header;
    } else {
      out.bigDim = !!st.tentative;
    }
    return out;
  }
  const body = (text) => joinLines(wrap(text).slice(0, L.bodyLines));

  if (!ui.connected || !st) {
    out.header = APP + '  ·  G2';
    out.body = body("Telefondaki Tilavet Takip'e bağlanılamıyor.\n" +
      'Telefonda uygulamayı açın (güncellemeden sonra bir kez açmak gerekir); Ayarlar → G2 GÖZLÜK: AÇIK olmalı.\n' +
      'Uygulama açılınca kendiliğinden bağlanır...' +
      (ui.diag ? '\n(' + ui.diag + ')' : ''));
    return out;
  }
  const rakat = st.rakat || '';
  if (st.noteTitle) {
    out.header = headerLine(st.noteTitle, rakat, '');
    out.body = body([st.noteReading, st.noteTurkish].filter(Boolean).join('\n'));
    return out;
  }
  if (!st.listening) {
    out.header = headerLine(APP, '', '');
    out.body = body('Dinleme kapalı.\nTelefonda mikrofon düğmesine basın.' + (st.status ? '\nDurum: ' + st.status : ''));
    return out;
  }
  if (!st.surah) {
    out.header = headerLine(APP + (st.sim ? ' · SİM' : ''), rakat, '');
    out.body = body((st.status || 'Dinleniyor') + '\nİmam okumaya başlayınca ayet ve meali burada görünür.');
    return out;
  }

  // Okunan ayet
  const mealLines = wrap(st.meal || '(meal yok)');
  const mealPages = Math.max(1, Math.ceil(mealLines.length / L.bodyLines));
  const arabicLines = layoutName === 'arabic' ? Math.max(0, ui.arabicLineCount | 0) : 0;
  const arabicPages = arabicLines > 0 ? Math.ceil(arabicLines / ARABIC_LINES) : 0;
  const pages = Math.max(mealPages, arabicPages, 1);
  const { page, auto } = pickPage(st, pages, ui.manual);
  const mp = Math.floor((page * mealPages) / pages);

  const main = ayahLabel(st) + (st.tentative ? ' · ADAY' : '');
  out.header = headerLine(main, rakat, pages > 1 ? `${page + 1}/${pages}` : '');
  out.body = joinLines(mealLines.slice(mp * L.bodyLines, (mp + 1) * L.bodyLines));
  out.bodyColor = st.tentative ? BRIGHT.dim : BRIGHT.body;
  out.page = page;
  out.pages = pages;
  out.autoPage = auto;
  out.arabicPages = arabicPages;
  out.arabicPage = arabicPages > 0 ? Math.floor((page * arabicPages) / pages) : -1;
  return out;
}
