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
  // Ayarlar → G2 ÜST BİLGİ: KAPALI gozlugun kendi yazisinda da (kullanici: "G2'nin kendi fontunu secince ust bilgiyi
  // gizleme ayari kayboluyor; o zaman da gizleyebilmek istiyorum"): baslik yok, meal ekranin ustunden (10 satir; Arapcada
  // bant en ustte, altinda 6 satir)
  textn: {
    header: null,
    body: { x: 0, y: 0, w: SCREEN_W, h: SCREEN_H },
    bodyLines: 10,
    tiles: [],
  },
  arabicn: {
    header: null,
    body: { x: 0, y: 114, w: SCREEN_W, h: SCREEN_H - 114 },
    bodyLines: 6,
    tiles: [{ x: 0, y: 0, w: 288, h: 112 }, { x: 288, y: 0, w: 288, h: 112 }],
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
  // Demo (Ayarlar → G2 DEMO, /state demo): gozlugun kendi yazisi, tum ekran tek kutu, kutu cercevesi ekranin dort
  // kenarinda (SDK metin kutusu kenarligi: kalinlik 0-5, gri ton 0-16 — even-g2-notes display.md), satirlar numarali
  demo: {
    header: null,
    body: { x: 0, y: 0, w: SCREEN_W, h: SCREEN_H },
    bodyLines: 10,
    tiles: [],
    padding: 6,
    border: { width: 2, color: 13, radius: 0 },
  },
  // Demo, buyuk yazi: tum ekran 4 karo (cerceve + numarali satirlar telefonda cizilir, secilen yazi tipi / kalinlik / boyut)
  demob: {
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
 * Ayarlar → G2 AYETİ TEK EKRANA SIĞDIR (/state onePage; kullanici: "ayet 2-3 sayfada gosterilince tum ayeti okumak zor"):
 * punto alt sinira kadar kuculur — alt sinir Ayarlar → G2 TEK EKRAN EN KÜÇÜK YAZI (/state onePageMinPx; kullanici: "alt
 * sinir punto ayarini kullaniciya birak, altinda kalacaksa yine sayfalama yaptir"; GlassesState.MIN/MAX/DEFAULT_ONE_PAGE_PX
 * ile ayni). Tum meallerde (Ali Bulac) olculdu: en uzunu Bakara 2:282 (1129 karakter) baslikli duzende ~12 px, 2:102 / 4:12
 * ~14 px; baslikli duzende 431 meal 24 px'in, 99'u 20 px'in, 11'i 16 px'in altina iniyor (12 px'te hepsi tek sayfa).
 */
export const ONE_PAGE_PX = { min: 12, max: 40, def: 20 };

/**
 * Buyuk yazinin yazi tipi + kalinligi (Ayarlar → G2 YAZI TİPİ / G2 YAZI KALINLIĞI; /state bigFont, bigWeight; sadece
 * gozluk). Kullanici: "bilimsel olarak rahat okunabilirligi arastirilmis 3 font daha, kalin ince secenekleri olsun".
 * Hepsi degisken (wght eksenli) OFL fontlar, degistirilmeden (assets/g2fonts, kopruden /g2font-<id>.ttf); hepsinde 7
 * mealin tum karakterleri ve Turkce harfler var (fontTools ile olculdu). B612 (Airbus kokpit ekrani) ğ ı İ ş icermiyor,
 * Andika'nin ince kalinligi yok → alinmadi.
 *   manrope   Manrope (APK #44'ten beri, varsayilan; 200-800)
 *   atkinson  Atkinson Hyperlegible Next (Braille Institute, az gorenlerle test edilerek; benzer harfler ayrik: I l 1,
 *             O 0; 200-800)
 *   lexend    Lexend (Shaver-Troup'un okuma akiciligi arastirmasi: genis harf araligi; 100-900)
 *   inter     Inter (ekran icin; buyuk x-yuksekligi — kucuk puntoda okunurluk; 100-900)
 * Satir yuksekligi hepsinde 1.16 em yetiyor (sapkali buyuk harf + kuyruk: Manrope 1.24 em, digerleri 1.04-1.19).
 */
export const BIG_FONTS = {
  manrope: { name: 'Manrope', file: 'g2font-manrope.ttf', family: 'TTBigManrope', weights: '200 800' },
  atkinson: { name: 'Atkinson', file: 'g2font-atkinson.ttf', family: 'TTBigAtkinson', weights: '200 800' },
  lexend: { name: 'Lexend', file: 'g2font-lexend.ttf', family: 'TTBigLexend', weights: '100 900' },
  inter: { name: 'Inter', file: 'g2font-inter.ttf', family: 'TTBigInter', weights: '100 900' },
};
/** İNCE / NORMAL / KALIN / ÇOK KALIN (GlassesState.WEIGHTS ile ayni); varsayilan KALIN = eski Manrope 700. */
export const BIG_WEIGHTS = [300, 500, 700, 800];
export const BIG_FONT_DEFAULT = { id: 'manrope', weight: 700 };

/** /state → {id, weight} (bilinmeyen font → Manrope, listede olmayan kalinlik → en yakini). */
export function bigFontOf(st) {
  const id = st && Object.prototype.hasOwnProperty.call(BIG_FONTS, st.bigFont) ? st.bigFont : BIG_FONT_DEFAULT.id;
  const w = Number(st && st.bigWeight);
  const weight = Number.isFinite(w) && w > 0
    ? BIG_WEIGHTS.reduce((a, b) => (Math.abs(b - w) < Math.abs(a - w) ? b : a))
    : BIG_FONT_DEFAULT.weight;
  return { id, weight };
}

/**
 * /state textPx → fitBigText secenekleri (gecersizse varsayilan); h: yazi alani yuksekligi (baslikli duzende 256);
 * fixed: Ayarlar → G2 SABİT YAZI BOYUTU — her metin tam bu puntoda (kisa metin buyutulmez, uzun meal kucultulmez,
 * sayfalara bolunur; kullanici: "hepsinde font boyutu ayni olsun").
 * onePage: Ayarlar → G2 AYETİ TEK EKRANA SIĞDIR — sigmayan metin sayfalanmaz, punto alt sinira (onePageMinPx, en fazla
 * ayardaki punto) kadar kuculur (sabit boyut da aciksa kisa metin ayardaki puntoda kalir, sadece sigmayan kuculur); alt
 * sinirda da sigmazsa sayfalar: en az sayfa (alt sinirdaki sayfa sayisi) ve o sayfa sayisina sigan en buyuk punto
 * (fewestPages).
 */
export function bigOptions(textPx, h = SCREEN_H, fixed = false, onePage = false, onePageMinPx = ONE_PAGE_PX.def) {
  const even = (v, lo, hi, def) => {
    const k = Math.round(Number(v));
    return !Number.isFinite(k) || k <= 0 ? def : Math.min(hi, Math.max(lo, k - (k % 2)));
  };
  const px = even(textPx, BIG_PX.min, BIG_PX.max, BIG.minPx);
  if (onePage) {
    const floor = Math.min(px, even(onePageMinPx, ONE_PAGE_PX.min, ONE_PAGE_PX.max, ONE_PAGE_PX.def));
    return { ...BIG, minPx: floor, maxPx: fixed ? px : BIG.maxPx, fewestPages: true, h };
  }
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
 * Tek sayfaya sigan punto yoksa minPx'te sayfalar; opt.fewestPages ise minPx'teki sayfa sayisina sigan en buyuk puntoda
 * (tek ekran modu: alt sinirda 3 sayfa tutuyorsa 3 sayfanin yettigi en buyuk punto).
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
  let px = opt.minPx;
  if (opt.fewestPages) {
    const pagesAt = (q) => Math.ceil(wrapAt(q).length / perPageAt(q));
    const n = pagesAt(px);
    for (let q = opt.maxPx; q > px; q -= opt.step) {
      if (pagesAt(q) <= n) { px = q; break; }
    }
  }
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

/**
 * Demo (Ayarlar → G2 DEMO 1-4, /state demo; kullanici: "gozlugu denettirecegim kisiler icin demo yazisi; demo1'de az
 * kelime, demo4'te tum ekrani kaplayacak kadar; en ust ve en alt satiri goruyor mu anlamam lazim; cerceve yap ki dort
 * kenari da gorebiliyor mu anlayalim; yazi tipi / boyutu degisince yazi da degissin"). Ekranin dort kenarinda cerceve,
 * satirlar numarali (en ust / en alt satirin numarasi sorulur). Buyuk yazida (G2 YAZI: BÜYÜK) secilen yazi tipi,
 * kalinlik ve G2 YAZI BOYUTU'nda (sabit — demo 4 o puntoda ekrani tam doldurur, boyut degisince satir sayisi degisir);
 * normal yazida gozlugun kendi yazisiyla 1 / 3 / 6 / 10 satir. Demo baslik ayarlarina bakmaz (tum ekran).
 */
export const DEMO_SHORT = 'Allah birdir.';
export const DEMO_TEXT = "Rahmân ve Rahîm olan Allah'ın adıyla. Hamd, âlemlerin Rabbi Allah'a mahsustur. O, Rahmân'dır, " +
  'Rahîm\'dir. Din gününün sahibidir. Yalnız sana ibadet eder, yalnız senden yardım dileriz. Bizi doğru yola ilet; ' +
  'nimet verdiklerinin yoluna, gazaba uğrayanların ve sapıtanların yoluna değil. De ki: O Allah birdir. Allah ' +
  "sameddir; her şey O'na muhtaçtır. O doğurmamış ve doğurulmamıştır. Hiçbir şey O'na denk değildir. Pijamalı hasta " +
  'yağız şoföre çabucak güvendi.';
/** Demo 2 / 3 ekranin (satir kapasitesinin) bu kadari; demo 4 tam ekran. */
export const DEMO_FILL = [0, 0, 1 / 3, 2 / 3, 1];
/**
 * Demo buyuk yazi geometrisi (576x288 goruntu): frame cerceve kalinligi (ekranin en dis pikselleri), numW satir
 * numarasi sutunu (yazi bunun sagindan baslar), padR sag bosluk, padY ust / alt bosluk; numara puntosu yazinin
 * numScale'i (numMin..numMax px — gozlukte okunsun, sutuna sigsin: 30 px'te en fazla 7 satir, tek hane).
 */
export const DEMO = { frame: 2, numW: 34, padR: 10, padY: 6, numScale: 0.45, numMin: 16, numMax: 26 };

/** Demo satir numarasi puntosu (yazi puntosuna gore). */
export function demoNumPx(px) {
  return Math.min(DEMO.numMax, Math.max(DEMO.numMin, Math.round(px * DEMO.numScale)));
}

/** /state demo → 1-4 (0 = kapali). */
export function demoLevel(st) {
  const n = Math.round(Number(st && st.demo));
  return Number.isFinite(n) && n >= 1 && n <= 4 ? n : 0;
}

/** Demo metni sonsuz kelime akisi (DEMO_TEXT tekrar eder). */
function demoWords(i) {
  const w = DEMO_TEXT.split(' ');
  return w[i % w.length];
}

/**
 * Demo, buyuk yazi: {px, lineH, perPage, y0, lines}. measure(metin, px) → piksel (eklentide canvas, testte yaklasik).
 * Punto = G2 YAZI BOYUTU (bigOptions sabit); demo 1 kisa cumle, demo 2-4 satir kapasitesinin 1/3, 2/3'u ve tamami (her
 * satir dolu, kelime bolunmez). Blok ust bosluk esit dagilacak sekilde (demo 4 dikeyde ortada; digerleri ayni yerden).
 */
export function demoLayout(level, textPx, measure) {
  const px = bigOptions(textPx, SCREEN_H, true).minPx;
  const lineH = Math.round(px * BIG.lineH);
  const maxW = SCREEN_W - DEMO.numW - DEMO.padR;
  const perPage = Math.max(1, Math.floor((SCREEN_H - 2 * DEMO.padY) / lineH));
  const y0 = Math.round((SCREEN_H - perPage * lineH) / 2);
  const lines = [];
  if (level <= 1) {
    let cur = '';
    for (const word of DEMO_SHORT.split(' ')) {
      const cand = cur ? cur + ' ' + word : word;
      if (!cur || measure(cand, px) <= maxW) { cur = cand; continue; }
      lines.push(cur);
      cur = word;
    }
    if (cur) lines.push(cur);
    return { px, lineH, perPage, y0, lines: lines.slice(0, perPage) };
  }
  const target = level >= 4 ? perPage : Math.max(1, Math.round(perPage * DEMO_FILL[level]));
  let cur = '';
  for (let i = 0; lines.length < target && i < 5000; i++) {
    const word = demoWords(i);
    const cand = cur ? cur + ' ' + word : word;
    if (!cur || measure(cand, px) <= maxW) { cur = cand; continue; }
    lines.push(cur);
    cur = word;
  }
  return { px, lineH, perPage, y0, lines };
}

/** Demo, gozlugun kendi yazisi: 1 / 3 / 6 / 10 numarali satir ("1  Hamd ..."), cerceveli kutuya sigar. */
export function demoTextLines(level) {
  const L = LAYOUTS.demo;
  const n = level >= 4 ? L.bodyLines : [0, 1, 3, 6][level];
  // ic genislik: kutu - 2 * (ic bosluk + kenarlik) - guvenlik payi (genislik tablosu ~%4 genis olcuyor)
  const inner = SCREEN_W - 2 * (L.padding + L.border.width) - 20;
  if (level <= 1) return ['1  ' + fitLine(DEMO_SHORT, inner - textWidth('1  '))];
  const out = [];
  let cur = '';
  const prefix = (k) => `${k}  `;
  for (let i = 0; out.length < n && i < 5000; i++) {
    const word = sanitize(demoWords(i));
    const maxW = inner - textWidth(prefix(out.length + 1));
    const cand = cur ? cur + ' ' + word : word;
    if (!cur || textWidth(cand) <= maxW) { cur = cand; continue; }
    out.push(prefix(out.length + 1) + cur);
    cur = word;
  }
  return out;
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

/**
 * Zikir karti / ezan penceresi gozlukte: sadece Turkce anlami (kullanici: "Allahu ekber Allah en buyuktur olmasin, direkt
 * Allah en buyuktur yazsin" — tekbir, kamet, ezan, selam, namaz sonu duasi). Anlam yoksa okunus, o da yoksa baslik.
 */
export function noteText(st) {
  return st.noteTurkish || st.noteReading || st.noteTitle || ' ';
}

/**
 * Ayarlar → G2 MEALDE AYET ADI (/state mealLabel: "off" | "start" | "end"; kullanici: "meali verirken hangi ayete ait
 * oldugunu goster: ya metinden once (Bakara:33 ...) ya metnin sonunda (... - Bakara:33) ya da hic"). Etiket uygulamadaki
 * gibi "Bakara: 33" (ayahLabel). Kapali / bilinmeyen deger → null.
 */
export function mealWithLabel(st, meal) {
  if (st.mealLabel === 'start') return `${ayahLabel(st)} — ${meal}`;
  if (st.mealLabel === 'end') return `${meal} — ${ayahLabel(st)}`;
  return null;
}

/** Buyuk yazi yerlesimi ayet adiyla "buyudu mu": daha cok sayfa, daha cok satir ya da daha kucuk punto. */
function bigGrows(base, withLabel) {
  const lines = (f) => f.pages.reduce((n, p) => n + p.length, 0);
  return withLabel.pages.length > base.pages.length || lines(withLabel) > lines(base) || withLabel.px < base.px;
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
 * Bos ekran (blank: true): ses kesildi (ustte rekat — Ayarlar → G2 BOŞ EKRANDA ÜST BİLGİ) ya da durum yazisi gizli.
 * Ayarlar → G2 ÜST BİLGİ (/state bigHeader; adi tarihsel, butun duzenler): KAPALI → baslik yok (big / textn / arabicn).
 * Ayarlar → G2 REKÂT BİLGİSİNİ GİZLE (/state hideRakat): baslikta rekat / durus yok — sadece "Sure: ayet" (kullanici:
 * "hide yaparsa sadece sure adi: ayet no cikacak").
 */
export function buildScreen(st, ui = {}) {
  // Demo (Ayarlar → G2 DEMO 1-4): her seyin onunde (dinleme, not karti, bos ekran); buyuk yazi fontu hazirsa
  // (ui.demoBig: (seviye, textPx) → demoLayout) secilen yazi tipiyle goruntu, degilse gozlugun kendi yazisi
  const demo = ui.connected && st ? demoLevel(st) : 0;
  if (demo) {
    const base = {
      header: ' ', headerColor: BRIGHT.header, body: ' ', bodyColor: BRIGHT.body, page: 0, pages: 1, autoPage: 0,
      arabicPage: -1, arabicPages: 0, big: null, bigDim: false, bigFixed: true, demo: null, demoLevel: demo,
    };
    if (st.bigText && ui.demoBig) return { ...base, layout: 'demob', demo: ui.demoBig(demo, st.textPx) };
    return { ...base, layout: 'demo', body: joinLines(demoTextLines(demo)) };
  }
  const noHeader = !!st && st.bigHeader === false;
  const layoutName = !(ui.connected && st) ? 'text'
    : st.showArabic ? (noHeader ? 'arabicn' : 'arabic')
      : st.bigText && ui.fitBig ? (noHeader ? 'big' : 'bigh') : (noHeader ? 'textn' : 'text');
  const rakatOf = (s) => (s.hideRakat === true ? '' : s.rakat || '');
  const empty = (header) => ({
    layout: 'text', header, headerColor: BRIGHT.header, body: ' ', bodyColor: BRIGHT.body, page: 0, pages: 1,
    autoPage: 0, arabicPage: -1, arabicPages: 0, big: null, bigDim: false, bigFixed: false, blank: true,
  });
  // Ses kesildi (/state blank, uygulamada TextHold): ayet metni kalkti → bos ekran, ustte rekat / durus (gozlugun kendi
  // yazisi; goruntu karolari tek seferde yeniden kurulumla silinir). Zikir / ezan karti varsa o gosterilir.
  // blankHeader false (Ayarlar → G2 BOŞ EKRANDA ÜST BİLGİ: KAPALI; kullanici: "ekran bos kaldiginda ust bilgi durmasin"):
  // ekran bombos. Alan yoksa (eski uygulama) ustte rekat.
  if (ui.connected && st && st.blank && st.listening && !st.noteTitle) {
    // rekat gizliyse bos ekranin ust satirinda gosterilecek bir sey yok
    const top = st.hideRakat === true ? '' : (st.rakat || APP) + (st.sim ? ' · SİM' : '');
    return empty(st.blankHeader === false || !top ? ' ' : headerLine(top, '', ''));
  }
  // Durum yazisi gizli (Ayarlar → G2 DURUM YAZISINI GİZLE, /state hideStatus; kullanici: "Dinleme kapali yazisi
  // cikmasin, ekran bombos olsun"): dinleme kapaliyken ve dinlenirken ayet bulunana kadar ("Dinleniyor", "Kamet · Fatiha
  // bekleniyor") ekran bos. Zikir / ezan karti yine gosterilir; baglanti yoksa tani ekrani (ayar bilinmiyor).
  if (ui.connected && st && st.hideStatus === true && !st.noteTitle && (!st.listening || !st.surah)) return empty(' ');
  const L = LAYOUTS[layoutName];
  const out = {
    layout: layoutName, header: APP, headerColor: BRIGHT.header, body: ' ', bodyColor: BRIGHT.body,
    page: 0, pages: 1, autoPage: 0, arabicPage: -1, arabicPages: 0, big: null, bigDim: false, bigFixed: false,
  };
  if (layoutName === 'big' || layoutName === 'bigh') {
    const withHeader = layoutName === 'bigh';
    const fit = (t) => ui.fitBig(sanitizeBig(t), st.textPx, bigAreaHeight(layoutName), st.fixedSize === true,
      st.onePage === true, st.onePageMinPx);
    out.bigFixed = st.fixedSize === true;
    const rakat = rakatOf(st);
    out.header = ' ';
    let text;
    if (st.noteTitle) {
      text = noteText(st);
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
    // Ayarlar → G2 MEALDE AYET ADI: ayet adi mealin basinda / sonunda. SATIR ARTSA DA EKLE kapaliyken (mealLabelGrow)
    // ayet adi satir / sayfa ekleyecekse ya da yaziyi kucultecekse (degisken boyutta satir yerine punto kuculur) eklenmez
    const meal = st.meal || '(meal yok)';
    const labeled = mealWithLabel(st, meal);
    const mealFit = (lay) => {
      const fitIn = (t) => ui.fitBig(sanitizeBig(t), st.textPx, bigAreaHeight(lay), st.fixedSize === true,
        st.onePage === true, st.onePageMinPx);
      const base = fitIn(meal);
      if (labeled) {
        const withLabel = fitIn(labeled);
        if (st.mealLabelGrow === true || !bigGrows(base, withLabel)) return { big: withLabel, labeled: true };
      }
      return { big: base, labeled: false };
    };
    let m = mealFit(layoutName);
    // Ayarlar → YAZI KÜÇÜLECEKSE ÜST BİLGİYİ GİZLE (/state headerAutoHide): ust bilgi yuzunden (alan 288 → 256 px) yazi
    // kuculecekse ya da meal bir sayfa daha bolunecekse o ekranda ust bilgi yok, ekranin tamami meal (duzen big; aday
    // sonuk yazi, sayfa cubugu). Kullanici: "yazilar ekrana sigmayacagi icin font kucultulecekse ust bilgiyi gosterme".
    if (withHeader && st.headerAutoHide === true) {
      const full = mealFit('big');
      if (m.big.px < full.big.px || m.big.pages.length > full.big.pages.length) {
        m = full;
        out.layout = 'big';
        out.headerAutoHidden = true;
      }
    }
    out.big = m.big;
    if (m.labeled) out.mealLabeled = true;
    out.pages = out.big.pages.length;
    const { page, auto } = pickPage(st, out.pages, ui.manual);
    out.page = page;
    out.autoPage = auto;
    if (out.layout === 'bigh') {
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
  // basliksiz duzende (textn / arabicn) baslik metni kullanilmaz
  const done = () => { if (!L.header) out.header = ' '; return out; };

  if (!ui.connected || !st) {
    out.header = APP + '  ·  G2';
    out.body = body("Telefondaki Tilavet Takip'e bağlanılamıyor.\n" +
      'Telefonda uygulamayı açın (güncellemeden sonra bir kez açmak gerekir); Ayarlar → G2 GÖZLÜK: AÇIK olmalı.\n' +
      'Uygulama açılınca kendiliğinden bağlanır...' +
      (ui.diag ? '\n(' + ui.diag + ')' : ''));
    return out;
  }
  const rakat = rakatOf(st);
  if (st.noteTitle) {
    out.header = headerLine(st.noteTitle, rakat, '');
    out.body = body(noteText(st));
    return done();
  }
  if (!st.listening) {
    out.header = headerLine(APP, '', '');
    out.body = body('Dinleme kapalı.\nTelefonda mikrofon düğmesine basın.' + (st.status ? '\nDurum: ' + st.status : ''));
    return done();
  }
  if (!st.surah) {
    out.header = headerLine(APP + (st.sim ? ' · SİM' : ''), rakat, '');
    out.body = body((st.status || 'Dinleniyor') + '\nİmam okumaya başlayınca ayet ve meali burada görünür.');
    return done();
  }

  // Okunan ayet (Ayarlar → G2 MEALDE AYET ADI: satir ekleyecekse sadece SATIR ARTSA DA EKLE aciksa)
  let mealLines = wrap(st.meal || '(meal yok)');
  const labeled = mealWithLabel(st, st.meal || '(meal yok)');
  if (labeled) {
    const withLabel = wrap(labeled);
    if (st.mealLabelGrow === true || withLabel.length <= mealLines.length) {
      mealLines = withLabel;
      out.mealLabeled = true;
    }
  }
  const mealPages = Math.max(1, Math.ceil(mealLines.length / L.bodyLines));
  const arabicLines = L.tiles.length ? Math.max(0, ui.arabicLineCount | 0) : 0;
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
  return done();
}
