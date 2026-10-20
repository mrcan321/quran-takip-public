// G2 eklentisinin ekran duzeni (assets/g2/layout.js) — node --test tests/g2/layout.test.mjs
// TILAVET_MEAL_BIN verilirse (test kapisi: <assets>/asr/meal.bin) tum mealler de denenir: her satir kutuya sigmali, her
// sayfa 999 bayt sinirinin altinda olmali; fontta karsiligi olmayan (atilan) karakterler G2_MEALS satirinda sayilir.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const L = await import(path.join(here, '../../tilavet-android/app/src/main/assets/g2/layout.js'));

const ST = {
  v: 1, seq: 1, listening: true, sim: false, status: 'Dinleniyor', surah: 108, ayah: 2, surahName: 'Kevser',
  surahAyahCount: 3, tentative: false, progress: 1, meal: 'Şu halde Rabbin için namaz kıl ve kurban kes.', arabic: '',
  showArabic: false, rakat: '1. REKÂT · KIYAM', noteTitle: '', noteReading: '', noteTurkish: '',
};
const LONG = Array.from({ length: 40 }, (_, i) => `Cümle ${i + 1}: Ey iman edenler, belirli bir süre için borçlandığınızda yazın.`).join(' ');

function lines(s) {
  return s.split('\n');
}

test('Turkce harfler fontta, Arapca / emoji yok', () => {
  for (const ch of 'ÂâÎîÛûÇçĞğİıÖöŞşÜü·—–') assert.ok(L.charWidth(ch.codePointAt(0)) > 0, ch);
  assert.equal(L.charWidth('ا'.codePointAt(0)), 0);
  assert.equal(L.sanitize('a`b’c“d”'), "a'b'c\"d\"");
  assert.equal(L.sanitize('اللّه x 😀 y'), ' x y');
  assert.equal(L.sanitize('ŭ'), 'u');
  assert.equal(L.sanitize('a​b'), 'ab');
});

test('satir kirma: her satir sinirda, kelime bolunmez, uzun kelime harf harf', () => {
  const ls = L.wrap(LONG);
  assert.ok(ls.length > 20);
  for (const l of ls) assert.ok(L.textWidth(l) <= L.WRAP_W, l);
  assert.equal(ls.join(' ').replace(/\s+/g, ' '), L.sanitize(LONG));
  const w = L.wrap('x'.repeat(200));
  assert.ok(w.length >= 3 && w.every((l) => L.textWidth(l) <= L.WRAP_W));
  assert.deepEqual(L.wrap('a\nb'), ['a', 'b']);
});

test('kutu yukseklikleri satirlara yetiyor (kaydirma cubugu yok)', () => {
  for (const [name, lay] of Object.entries(L.LAYOUTS)) {
    if (lay.header) assert.ok(lay.header.h >= L.LINE_H + 2 * L.PADDING, name + ' baslik');
    assert.ok(lay.body.h >= lay.bodyLines * L.LINE_H + 2 * L.PADDING, name + ' govde');
    assert.ok(lay.body.y + lay.body.h <= L.SCREEN_H, name + ' ekran disi');
    for (const t of lay.tiles) assert.ok(t.w <= 288 && t.h <= 144 && t.w >= 20 && t.h >= 20, 'karo boyutu');
  }
});

test('baglanti yok / bosta / dinleniyor / not', () => {
  let s = L.buildScreen(null, { connected: false });
  assert.match(s.body, /bağlanılamıyor/);
  assert.equal(s.layout, 'text');
  s = L.buildScreen({ ...ST, listening: false, surah: 0, status: 'Durduruldu' }, { connected: true });
  assert.match(s.body, /Dinleme kapalı/);
  assert.match(s.body, /Durduruldu/);
  s = L.buildScreen({ ...ST, surah: 0, status: 'Kamet · Fatiha bekleniyor' }, { connected: true });
  assert.match(s.body, /^Kamet/);
  assert.match(s.header, /REKÂT/);
  s = L.buildScreen({ ...ST, noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' },
    { connected: true });
  assert.match(s.header, /^TEKBİR/);
  assert.deepEqual(lines(s.body), ['Allâhu ekber', 'Allah en büyüktür']);
});

test('ayet: baslik, aday sonuk, kisa meal tek sayfa', () => {
  let s = L.buildScreen(ST, { connected: true });
  assert.equal(s.header, 'Kevser: 2 · 1. REKÂT · KIYAM');
  assert.equal(s.body, ST.meal);
  assert.equal(s.pages, 1);
  assert.equal(s.bodyColor, L.BRIGHT.body);
  s = L.buildScreen({ ...ST, tentative: true }, { connected: true });
  assert.match(s.header, /ADAY/);
  assert.equal(s.bodyColor, L.BRIGHT.dim);
});

test('uzun meal: ilerlemeye gore sayfa, kaydirma, ayet degisince sifirlanir', () => {
  const st = { ...ST, surah: 2, ayah: 282, surahName: 'Bakara', meal: LONG, progress: 0 };
  const s0 = L.buildScreen(st, { connected: true });
  assert.ok(s0.pages >= 3, String(s0.pages));
  assert.equal(s0.page, 0);
  assert.match(s0.header, new RegExp(`1/${s0.pages}$`));
  assert.ok(lines(s0.body).length <= L.LAYOUTS.text.bodyLines);
  const sEnd = L.buildScreen({ ...st, progress: 1 }, { connected: true });
  assert.equal(sEnd.page, s0.pages - 1);
  const sMid = L.buildScreen({ ...st, progress: 0.5 }, { connected: true });
  assert.equal(sMid.page, Math.floor(0.5 * s0.pages));
  // kullanici kaydirdi: ilerleme ayni sayfadayken elle secilen sayfa
  const manual = { key: '2:282', base: 0, page: 2 };
  assert.equal(L.buildScreen({ ...st, progress: 0.01 }, { connected: true, manual }).page, 2);
  // ilerleme yeni sayfaya gecti → elle secim biter
  assert.equal(L.buildScreen({ ...st, progress: 0.5 }, { connected: true, manual }).page, sMid.page);
  // baska ayet → elle secim gecersiz
  assert.equal(L.buildScreen({ ...st, ayah: 283, progress: 0 }, { connected: true, manual }).page, 0);
  // tum sayfalar birlikte tum meali kapsar
  const all = [];
  for (let p = 0; p < s0.pages; p++) {
    all.push(L.buildScreen(st, { connected: true, manual: { key: '2:282', base: 0, page: p } }).body);
  }
  assert.equal(all.join('\n').split('\n').join(' ').replace(/\s+/g, ' '), L.sanitize(LONG));
});

test('Arapca duzen: 5 satir meal, Arapca sayfalari ile senkron', () => {
  const st = { ...ST, surah: 2, ayah: 255, surahName: 'Bakara', meal: LONG, showArabic: true, progress: 0 };
  const s = L.buildScreen(st, { connected: true, arabicLineCount: 5 });
  assert.equal(s.layout, 'arabic');
  assert.ok(lines(s.body).length <= 5);
  assert.equal(s.arabicPages, 3);
  assert.equal(s.arabicPage, 0);
  const sEnd = L.buildScreen({ ...st, progress: 1 }, { connected: true, arabicLineCount: 5 });
  assert.equal(sEnd.arabicPage, 2);
  // not / bosta: bant bos
  assert.equal(L.buildScreen({ ...st, noteTitle: 'TEKBİR' }, { connected: true }).arabicPage, -1);
  // baglanti yoksa her zaman metin duzeni
  assert.equal(L.buildScreen(st, { connected: false }).layout, 'text');
});

// yaklasik Manrope 700 olcusu (eklentide canvas measureText): karakter basina ~0.6 em
const approxMeasure = (s, px) => [...s].length * px * 0.6;
const fitBig = (t, px, h, fixed) => L.fitBigText(t, approxMeasure, L.bigOptions(px, h, fixed));
// satira sigmali; tireyle bolunen kelime parcasi da ("kavuş-")
const fitsLine = (line, px, opt) => approxMeasure(line, px) <= opt.w - 2 * opt.marginX || [...line].length <= 2;

test('buyuk yazi: punto metne gore, kisa meal en buyuk, uzun meal en kucukte sayfali', () => {
  const short = L.fitBigText('Allah birdir.', approxMeasure);
  assert.equal(short.px, L.BIG.maxPx);
  assert.equal(short.pages.length, 1);
  const mid = L.fitBigText(ST.meal, approxMeasure);
  assert.ok(mid.px < L.BIG.maxPx && mid.px >= L.BIG.minPx && mid.pages.length === 1, JSON.stringify(mid));
  const long = L.fitBigText(LONG, approxMeasure);
  assert.equal(long.px, L.BIG.minPx);
  assert.ok(long.pages.length > 3);
  for (const f of [short, mid, long]) {
    for (const pg of f.pages) {
      assert.ok(pg.length <= f.perPage);
      assert.ok(pg.length * f.lineH <= L.BIG.h - 2 * L.BIG.marginY + 1, 'sayfa ekrana sigmali');
      for (const line of pg) assert.ok(fitsLine(line, f.px, L.BIG), line);
    }
  }
  assert.equal(long.pages.flat().join(' '), LONG);
  // paragraf: okunus + anlam ayri satirlarda
  assert.deepEqual(L.fitBigText('Allâhu ekber\nAllah en büyüktür', approxMeasure).pages[0].length >= 2, true);
});

test('buyuk yazi boyutu: ayardaki en kucuk punto (textPx), sinirlar, uzun kelime tireyle', () => {
  assert.equal(L.bigOptions(undefined), L.BIG);
  assert.equal(L.bigOptions('x'), L.BIG);
  assert.equal(L.bigOptions(L.BIG_PX.def), L.BIG);
  assert.equal(L.BIG.minPx, L.BIG_PX.def);
  assert.equal(L.bigOptions(10).minPx, L.BIG_PX.min);
  assert.equal(L.bigOptions(500).minPx, L.BIG_PX.max);
  assert.equal(L.bigOptions(57).minPx, 56);   // cift (adim 2)
  // en kucuk punto buyudukce uzun meal daha cok sayfa, satirlar hep sigiyor
  let prev = 0;
  for (let px = L.BIG_PX.min; px <= L.BIG_PX.max; px += 2) {
    const opt = L.bigOptions(px);
    const f = L.fitBigText(LONG, approxMeasure, opt);
    assert.equal(f.px, px);
    assert.ok(f.pages.length >= prev, `${px}: ${f.pages.length} < ${prev}`);
    prev = f.pages.length;
    for (const pg of f.pages) {
      assert.ok(pg.length * f.lineH <= opt.h - 2 * opt.marginY + 1);
      for (const line of pg) assert.ok(fitsLine(line, f.px, opt), `${px}: ${line}`);
    }
  }
  // sayfalar dengeli: en dolu ile en bos sayfa arasi en fazla 1 satir
  for (let px = L.BIG_PX.min; px <= L.BIG_PX.max; px += 2) {
    const n = L.fitBigText(LONG, approxMeasure, L.bigOptions(px)).pages.map((p) => p.length);
    assert.ok(Math.max(...n) - Math.min(...n) <= 1, `${px}: ${n}`);
  }
  // kisa metin her zaman ayardan buyuk
  assert.ok(L.fitBigText('Allah en büyüktür', approxMeasure, L.bigOptions(L.BIG_PX.max)).px > L.BIG_PX.max);
  // satira sigmayan kelime tireyle bolunur, harf kaybolmaz
  const word = 'kavuşturulacaklardır';
  const w = L.fitBigText(`${word} ${word}`, approxMeasure, L.bigOptions(L.BIG_PX.max));
  const ls = w.pages.flat();
  assert.ok(ls.some((l) => l.endsWith('-')), JSON.stringify(ls));
  assert.equal(ls.map((l) => l.endsWith('-') ? l.slice(0, -1) : l + ' ').join('').trim(), `${word} ${word}`);
  // duzen ayari kullanir
  const st = { ...ST, bigText: true, bigHeader: false, surah: 2, ayah: 282, meal: LONG, progress: 0 };
  const a = L.buildScreen({ ...st, textPx: 30 }, { connected: true, fitBig });
  const b = L.buildScreen({ ...st, textPx: 70 }, { connected: true, fitBig });
  assert.equal(a.big.px, 30);
  assert.equal(b.big.px, 70);
  assert.ok(b.pages > a.pages);
});

test('buyuk yazi duzeni: sadece meal, sayfa ilerlemeyle, aday sonuk, notlar ve bosta', () => {
  const st = { ...ST, bigText: true, bigHeader: false, surah: 2, ayah: 282, meal: LONG, progress: 0 };
  // font hazir degilse normal duzen
  assert.equal(L.buildScreen(st, { connected: true }).layout, 'text');
  const s0 = L.buildScreen(st, { connected: true, fitBig });
  assert.equal(s0.layout, 'big');
  assert.ok(s0.pages > 3);
  assert.equal(s0.page, 0);
  assert.equal(L.buildScreen({ ...st, progress: 1 }, { connected: true, fitBig }).page, s0.pages - 1);
  const manual = { key: '2:282', base: 0, page: 2 };
  assert.equal(L.buildScreen({ ...st, progress: 0.01 }, { connected: true, fitBig, manual }).page, 2);
  assert.equal(L.buildScreen({ ...st, tentative: true }, { connected: true, fitBig }).bigDim, true);
  // Arapca acikken her zaman Arapca duzeni
  assert.equal(L.buildScreen({ ...st, showArabic: true }, { connected: true, fitBig }).layout, 'arabic');
  // NORMAL secili
  assert.equal(L.buildScreen({ ...st, bigText: false }, { connected: true, fitBig }).layout, 'text');
  const note = L.buildScreen({ ...st, noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' },
    { connected: true, fitBig });
  assert.match(note.big.pages[0].join(' '), /Allah en büyüktür/);
  assert.equal(L.buildScreen({ ...st, listening: false }, { connected: true, fitBig }).big.pages[0].join(' '),
    'Dinleme kapalı');
  assert.equal(L.buildScreen({ ...st, surah: 0, status: 'Dinleniyor' }, { connected: true, fitBig }).big.pages[0].join(' '),
    'Dinleniyor');
});

test('buyuk yazi + baslik (varsayilan): sure / ayet / sayfa ustte, ADAY baslikta, yazi alani 256 px', () => {
  assert.equal(L.bigAreaHeight('big'), 288);
  assert.equal(L.bigAreaHeight('bigh'), 256);
  assert.equal(L.bigOptions(48, 256).h, 256);
  assert.equal(L.bigOptions(48, 256).minPx, 48);
  assert.equal(L.bigOptions(48, 288), L.BIG);
  // karolar baslik altini tam kapliyor, en fazla 288x144
  const t = L.LAYOUTS.bigh.tiles;
  assert.equal(t.length, 4);
  for (const k of t) assert.ok(k.w <= 288 && k.h <= 144 && k.y >= L.LAYOUTS.bigh.header.h);
  assert.equal(t.reduce((a, k) => a + k.w * k.h, 0), 576 * 256);
  const st = { ...ST, bigText: true, surah: 2, ayah: 282, surahName: 'Bakara', meal: LONG, progress: 0 };
  const s = L.buildScreen(st, { connected: true, fitBig });
  assert.equal(s.layout, 'bigh');
  assert.ok(s.pages > 3);
  assert.match(s.header, /^Bakara: 282/);
  assert.match(s.header, new RegExp(`1/${s.pages}$`));
  for (const pg of s.big.pages) assert.ok(pg.length * s.big.lineH <= 256 - 2 * L.BIG.marginY + 1, 'sayfa alana sigmali');
  // baslikli duzende ayni metin daha cok (ya da ayni) sayfa
  const nh = L.buildScreen({ ...st, bigHeader: false }, { connected: true, fitBig });
  assert.ok(s.pages >= nh.pages);
  // son sayfa
  assert.match(L.buildScreen({ ...st, progress: 1 }, { connected: true, fitBig }).header, new RegExp(`${s.pages}/${s.pages}$`));
  // aday: baslikta ADAY + soluk baslik; buyuk yazi parlak (kilit dogrulaninca karolar degismez)
  const a = L.buildScreen({ ...st, tentative: true }, { connected: true, fitBig });
  assert.match(a.header, /ADAY/);
  assert.ok(a.headerColor < s.headerColor);
  assert.equal(a.bigDim, false);
  assert.deepEqual(a.big.pages[a.page], s.big.pages[s.page]);
  // kisa meal tek sayfa: sayfa etiketi yok, rekat sigarsa baslikta
  const k = L.buildScreen({ ...ST, bigText: true, surahName: 'Kevser' }, { connected: true, fitBig });
  assert.equal(k.pages, 1);
  assert.match(k.header, /^Kevser: 2/);
  assert.doesNotMatch(k.header, /1\/1/);
  assert.match(k.header, /REKÂT/);
  // not: baslikta not basligi, buyuk yazida okunus + anlam
  const note = L.buildScreen({ ...st, noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' },
    { connected: true, fitBig });
  assert.match(note.header, /^TEKBİR/);
  assert.match(note.big.pages[0].join(' '), /Allah en büyüktür/);
  // bosta / dinleniyor
  assert.match(L.buildScreen({ ...st, listening: false }, { connected: true, fitBig }).header, /^Tilavet Takip/);
  const idle = L.buildScreen({ ...st, surah: 0, sim: true }, { connected: true, fitBig });
  assert.match(idle.header, /SİM/);
  assert.equal(idle.big.pages[0].join(' '), 'Dinleniyor');
  // baslik firmware genisligine sigiyor
  for (const x of [s, a, k, note, idle]) assert.ok(L.textWidth(x.header) <= L.WRAP_W, x.header);
});

test('sabit yazi boyutu: her metin ayardaki puntoda, uzun meal sayfalara, kapaliyken eski davranis', () => {
  for (const px of [L.BIG_PX.min, 48, 64, L.BIG_PX.max]) {
    for (const h of [288, 256]) {
      const opt = L.bigOptions(px, h, true);
      assert.equal(opt.minPx, px);
      assert.equal(opt.maxPx, px);
      for (const t of ['Allah en büyüktür', ST.meal, LONG]) {
        const f = L.fitBigText(t, approxMeasure, opt);
        assert.equal(f.px, px, `${px}/${h}: ${t.slice(0, 20)}`);
        for (const pg of f.pages) {
          assert.ok(pg.length * f.lineH <= h - 2 * opt.marginY + 1);
          for (const line of pg) assert.ok(fitsLine(line, px, opt), line);
        }
        assert.equal(f.pages.flat().map((l) => l.endsWith('-') ? l.slice(0, -1) : l + ' ').join('').trim(), t);
      }
    }
  }
  // duzen: kisa ve uzun metin ayni punto; kapaliyken kisa metin buyuk
  const st = { ...ST, bigText: true, fixedSize: true, textPx: 48 };
  const kisa = L.buildScreen(st, { connected: true, fitBig });
  const uzun = L.buildScreen({ ...st, surah: 2, ayah: 282, meal: LONG }, { connected: true, fitBig });
  const tekbir = L.buildScreen({ ...st, noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' },
    { connected: true, fitBig });
  assert.deepEqual([kisa.big.px, uzun.big.px, tekbir.big.px], [48, 48, 48]);
  assert.equal(kisa.bigFixed, true);
  assert.ok(uzun.pages > 1);
  const serbest = L.buildScreen({ ...st, fixedSize: false }, { connected: true, fitBig });
  assert.ok(serbest.big.px > 48);
  assert.equal(serbest.bigFixed, false);
});

test('ses kesildi (blank): bos ekran, ustte rekat; not karti onde; baglanti / dinleme yokken eski davranis', () => {
  for (const extra of [{ bigText: true }, { bigText: true, bigHeader: false }, { bigText: false }, { showArabic: true }]) {
    const st = { ...ST, ...extra, blank: true, rakat: '1. REKÂT · RÜKÛ / SECDE', arabic: 'إِنَّآ' };
    const s = L.buildScreen(st, { connected: true, fitBig, arabicLineCount: 2 });
    assert.equal(s.layout, 'text', JSON.stringify(extra));
    assert.equal(s.blank, true);
    assert.equal(s.body, ' ');
    assert.equal(s.header, '1. REKÂT · RÜKÛ / SECDE');
    assert.equal(s.big, null);
  }
  // rekat bilgisi yoksa uygulama adi, simulasyonda SİM
  assert.equal(L.buildScreen({ ...ST, blank: true, rakat: '' }, { connected: true }).header, 'Tilavet Takip');
  assert.match(L.buildScreen({ ...ST, blank: true, sim: true }, { connected: true }).header, /SİM$/);
  // zikir / ezan karti bos ekrandan once gelir
  const note = L.buildScreen({ ...ST, blank: true, noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' },
    { connected: true });
  assert.notEqual(note.blank, true);
  assert.match(note.header, /^TEKBİR/);
  // dinleme durduysa ya da baglanti yoksa bos ekran degil
  assert.notEqual(L.buildScreen({ ...ST, blank: true, listening: false }, { connected: true }).blank, true);
  assert.match(L.buildScreen({ ...ST, blank: true }, { connected: false }).body, /bağlanılamıyor/);
});

test('baslik sigmazsa rekat kisalir, sonra atilir', () => {
  const st = { ...ST, surahName: 'Ankebût Ankebût Ankebût', surah: 29, ayah: 45, rakat: '2. REKÂT SONRASI · SESSİZ',
    meal: LONG, tentative: true };
  const s = L.buildScreen(st, { connected: true });
  assert.ok(L.textWidth(s.header) <= L.WRAP_W, s.header);
  assert.match(s.header, /\d+\/\d+$/);
});

test('bayt siniri', () => {
  const heavy = 'ğüşıöç '.repeat(400);
  const s = L.buildScreen({ ...ST, meal: heavy }, { connected: true });
  assert.ok(L.utf8Bytes(s.body) <= L.TEXT_MAX_BYTES);
});

// ------------------------------------------------------------------ gercek mealler (meal.bin)

function readMealBin(p) {
  const b = fs.readFileSync(p);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const count = dv.getUint32(8, true);
  const surahCount = dv.getUint32(12, true);
  let off = 16;
  const meals = [];
  const dec = new TextDecoder();
  for (let i = 0; i < count; i++) {
    const s = dv.getUint16(off, true); const a = dv.getUint16(off + 2, true); const len = dv.getUint16(off + 4, true);
    off += 6;
    meals.push([s, a, dec.decode(b.subarray(off, off + len))]);
    off += len;
  }
  const names = [];
  for (let i = 0; i < surahCount; i++) {
    off += 2;
    const tl = b[off]; off += 1; names.push(dec.decode(b.subarray(off, off + tl))); off += tl;
    const al = b[off]; off += 1 + al + 2;
  }
  return { meals, names };
}

const MEAL_BIN = process.env.TILAVET_MEAL_BIN;
const median = (xs) => [...xs].sort((x, y) => x - y)[Math.floor(xs.length / 2)];
test('tum mealler: font, satir, bayt', { skip: !MEAL_BIN || !fs.existsSync(MEAL_BIN) }, () => {
  const { meals, names } = readMealBin(MEAL_BIN);
  assert.ok(meals.length > 6000, 'meal sayisi ' + meals.length);
  const dropped = new Map();
  let maxPages = 0;
  let bigMax = 0;
  let bigPaged = 0;
  const bigPx = [];
  const bigPages = [];
  const bigHPages = [];
  const bigFixedPages = [];
  for (const [s, a, meal] of meals) {
    // buyuk yazi (yaklasik olcu, varsayilan en kucuk punto): kac meal tek sayfaya sigmiyor, punto / sayfa dagilimi
    const bf = L.fitBigText(L.sanitizeBig(meal), approxMeasure);
    const bp = bf.pages.length;
    bigMax = Math.max(bigMax, bp);
    if (bp > 1) bigPaged++;
    bigPx.push(bf.px);
    bigPages.push(bp);
    // baslikli buyuk yazi (varsayilan): baslik firmware genisligine sigmali, sayfa 256 px alana
    const hs = L.buildScreen({ ...ST, bigText: true, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal, tentative: true,
      rakat: '2. REKÂT · KIYAM' }, { connected: true, fitBig });
    assert.ok(L.textWidth(hs.header) <= L.WRAP_W, `${s}:${a} buyuk baslik`);
    bigHPages.push(hs.pages);
    // sabit yazi boyutu (varsayilan 48 px, baslikli)
    const fx = L.buildScreen({ ...ST, bigText: true, fixedSize: true, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal },
      { connected: true, fitBig });
    assert.equal(fx.big.px, L.BIG_PX.def, `${s}:${a} sabit punto`);
    bigFixedPages.push(fx.pages);
    for (const ch of meal) {
      const cp = ch.codePointAt(0);
      if (ch !== ' ' && L.charWidth(cp) === 0 && L.sanitize(ch) === '') dropped.set(ch, (dropped.get(ch) || 0) + 1);
    }
    for (const arabic of [false, true]) {
      const st = { ...ST, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal, showArabic: arabic, rakat: '2. REKÂT · KIYAM' };
      const s0 = L.buildScreen(st, { connected: true, arabicLineCount: arabic ? 4 : 0 });
      maxPages = Math.max(maxPages, s0.pages);
      assert.ok(L.textWidth(s0.header) <= L.WRAP_W, `${s}:${a} baslik`);
      for (let p = 0; p < s0.pages; p++) {
        const sp = L.buildScreen(st, { connected: true, arabicLineCount: arabic ? 4 : 0, manual: { key: `${s}:${a}`, base: s0.autoPage, page: p } });
        const ls = lines(sp.body);
        assert.ok(ls.length <= L.LAYOUTS[sp.layout].bodyLines, `${s}:${a} satir`);
        assert.ok(L.utf8Bytes(sp.body) <= L.TEXT_MAX_BYTES, `${s}:${a} bayt`);
        for (const l of ls) assert.ok(L.textWidth(l) <= L.WRAP_W, `${s}:${a} genislik`);
      }
    }
  }
  for (const n of names) assert.equal(L.sanitize(n), n, 'sure adi fontta: ' + n);
  // atilan karakter testi bozmaz (gozlukte sadece o isaret gorunmez); test kapisi sayiyi baseline ile karsilastirir
  const nDropped = [...dropped.values()].reduce((x, y) => x + y, 0);
  console.log(`G2_MEALS ${JSON.stringify({ meals: meals.length, max_pages: maxPages, dropped_chars: nDropped,
    big_max_pages: bigMax, big_paged: bigPaged, big_px_median: median(bigPx), big_pages_median: median(bigPages),
    big_header_pages_median: median(bigHPages), big_header_max_pages: Math.max(...bigHPages),
    big_fixed_pages_median: median(bigFixedPages), big_fixed_max_pages: Math.max(...bigFixedPages),
    dropped: Object.fromEntries(dropped) })}`);
});
