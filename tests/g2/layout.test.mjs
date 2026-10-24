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
  assert.deepEqual(lines(s.body), ['Allah en büyüktür']);   // gozlukte sadece Turkce anlami
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
const fitBig = (t, px, h, fixed, onePage, onePageMinPx) =>
  L.fitBigText(t, approxMeasure, L.bigOptions(px, h, fixed, onePage, onePageMinPx));
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
  // paragraf ("\n") ayri satirlarda
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
  // font hazir degilse normal duzen (ust bilgi kapali → basliksiz)
  assert.equal(L.buildScreen(st, { connected: true }).layout, 'textn');
  const s0 = L.buildScreen(st, { connected: true, fitBig });
  assert.equal(s0.layout, 'big');
  assert.ok(s0.pages > 3);
  assert.equal(s0.page, 0);
  assert.equal(L.buildScreen({ ...st, progress: 1 }, { connected: true, fitBig }).page, s0.pages - 1);
  const manual = { key: '2:282', base: 0, page: 2 };
  assert.equal(L.buildScreen({ ...st, progress: 0.01 }, { connected: true, fitBig, manual }).page, 2);
  assert.equal(L.buildScreen({ ...st, tentative: true }, { connected: true, fitBig }).bigDim, true);
  // Arapca acikken her zaman Arapca duzeni (ust bilgi kapali → basliksiz Arapca)
  assert.equal(L.buildScreen({ ...st, showArabic: true }, { connected: true, fitBig }).layout, 'arabicn');
  // NORMAL secili (bu durumda ust bilgi kapali → basliksiz normal duzen; acikken baslikli)
  assert.equal(L.buildScreen({ ...st, bigText: false }, { connected: true, fitBig }).layout, 'textn');
  assert.equal(L.buildScreen({ ...st, bigText: false, bigHeader: true }, { connected: true, fitBig }).layout, 'text');
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

test('tek ekrana sigdir: uzun meal tek sayfa (punto alt sinira kadar kuculur), kisa metin ayni', () => {
  const MID = LONG.slice(0, 900);
  for (const h of [288, 256]) {
    for (const px of [L.BIG_PX.min, 48, L.BIG_PX.max]) {
      // serbest: kisa metin eskisi gibi (en buyuk), uzun metin tek sayfa (alt sinir 12)
      const opt = L.bigOptions(px, h, false, true, 12);
      assert.equal(opt.minPx, 12);
      assert.equal(opt.fewestPages, true);
      assert.equal(L.fitBigText('Allah en büyüktür', approxMeasure, opt).px,
        L.fitBigText('Allah en büyüktür', approxMeasure, L.bigOptions(px, h)).px);
      const f = L.fitBigText(MID, approxMeasure, opt);
      assert.equal(f.pages.length, 1, `${px}/${h}`);
      assert.ok(f.px >= 12 && f.px < px, `${px}/${h}: ${f.px}`);
      assert.ok(f.pages[0].length * f.lineH <= h - 2 * opt.marginY + 1, 'sayfa alana sigmali');
      for (const line of f.pages[0]) assert.ok(fitsLine(line, f.px, opt), line);
      assert.equal(f.pages.flat().map((l) => l.endsWith('-') ? l.slice(0, -1) : l + ' ').join('').trim(), MID);
      // sabit + tek ekran: kisa metin ayardaki puntoda (buyutulmez), uzun metin kuculur
      const fo = L.bigOptions(px, h, true, true, 12);
      assert.equal(L.fitBigText('Allah en büyüktür', approxMeasure, fo).px, px);
      const ff = L.fitBigText(MID, approxMeasure, fo);
      assert.equal(ff.pages.length, 1);
      assert.ok(ff.px < px);
    }
  }
  // duzen: onePage /state alanindan; kapaliyken eski sayfalar
  const st = { ...ST, bigText: true, surah: 2, ayah: 282, surahName: 'Bakara', meal: MID, progress: 0.5 };
  const tek = L.buildScreen({ ...st, onePage: true, onePageMinPx: 12 }, { connected: true, fitBig });
  assert.equal(tek.pages, 1);
  assert.equal(tek.page, 0);
  assert.doesNotMatch(tek.header, /1\/1/);
  const eski = L.buildScreen(st, { connected: true, fitBig });
  assert.ok(eski.pages > 1);
  assert.ok(tek.big.px < eski.big.px);
});

test('tek ekran alt siniri (onePageMinPx): altinda kalacaksa sayfalar — en az sayfa, o sayfaya sigan en buyuk punto', () => {
  // sinirlar: 12-40, cift, ayardaki puntodan buyuk olamaz; gecersiz → varsayilan
  assert.equal(L.bigOptions(48, 256, false, true).minPx, L.ONE_PAGE_PX.def);
  assert.equal(L.bigOptions(48, 256, false, true, 'x').minPx, L.ONE_PAGE_PX.def);
  assert.equal(L.bigOptions(48, 256, false, true, 4).minPx, L.ONE_PAGE_PX.min);
  assert.equal(L.bigOptions(80, 256, false, true, 99).minPx, L.ONE_PAGE_PX.max);
  assert.equal(L.bigOptions(48, 256, false, true, 23).minPx, 22);
  assert.equal(L.bigOptions(30, 256, false, true, 40).minPx, 30);
  const MID = LONG.slice(0, 900);
  const at = (t, px, h) => L.fitBigText(t, approxMeasure, { ...L.BIG, minPx: px, maxPx: px, h });
  for (const h of [288, 256]) {
    for (const floor of [12, 20, 28, 40]) {
      for (const t of [MID, LONG, LONG.slice(0, 400)]) {
        const opt = L.bigOptions(48, h, false, true, floor);
        const f = L.fitBigText(t, approxMeasure, opt);
        assert.ok(f.px >= floor, `${floor}/${h}: ${f.px}`);
        const n = at(t, floor, h).pages.length;
        // alt sinirda tek sayfaya sigiyorsa tek sayfa; sigmiyorsa alt sinirdaki kadar sayfa (daha cok degil)
        assert.equal(f.pages.length, n, `${floor}/${h}`);
        if (n > 1) {
          // ayni sayfa sayisina sigan en buyuk punto: 2 px buyugu daha cok sayfa ister
          assert.ok(f.px === opt.maxPx || at(t, f.px + 2, h).pages.length > n, `${floor}/${h}: ${f.px}`);
          for (const pg of f.pages) {
            assert.ok(pg.length * f.lineH <= h - 2 * opt.marginY + 1);
            for (const line of pg) assert.ok(fitsLine(line, f.px, opt), line);
          }
          const sizes = f.pages.map((p) => p.length);
          assert.ok(Math.max(...sizes) - Math.min(...sizes) <= 1, `${floor}/${h}: ${sizes}`);
        }
        assert.equal(f.pages.flat().map((l) => l.endsWith('-') ? l.slice(0, -1) : l + ' ').join('').trim(), t);
      }
    }
  }
  // duzen: alt sinir 40'ta MID sayfali (ilerlemeyle sayfa + baslikta "1/2"), 12'de tek sayfa; sinir buyudukce sayfa artmaz azalmaz
  const st = { ...ST, bigText: true, surah: 2, ayah: 282, surahName: 'Bakara', meal: MID, progress: 0, onePage: true };
  const kucuk = L.buildScreen({ ...st, onePageMinPx: 12 }, { connected: true, fitBig });
  const buyuk = L.buildScreen({ ...st, onePageMinPx: 40 }, { connected: true, fitBig });
  assert.equal(kucuk.pages, 1);
  assert.ok(buyuk.pages > 1);
  assert.ok(buyuk.big.px >= 40);
  assert.match(buyuk.header, new RegExp(`1/${buyuk.pages}$`));
  assert.ok(buyuk.pages < L.buildScreen({ ...st, onePage: false }, { connected: true, fitBig }).pages);
  assert.equal(L.buildScreen({ ...st, onePageMinPx: 40, progress: 1 }, { connected: true, fitBig }).page, buyuk.pages - 1);
});

test('demo (Ayarlar → G2 DEMO): cerceve, numarali satirlar, demo 4 ekrani doldurur, her seyin onunde', () => {
  const demoBig = (lv, px) => L.demoLayout(lv, px, approxMeasure);
  const ui = { connected: true, fitBig, demoBig };
  // kapali / gecersiz deger → normal ekran
  for (const d of [0, 5, -1, 'x', undefined]) {
    assert.ok(!L.buildScreen({ ...ST, bigText: true, demo: d }, ui).layout.startsWith('demo'), String(d));
  }
  // her seyin onunde: dinleme kapali, not karti, bos ekran, durum gizli, basliksiz, Arapca acik
  for (const extra of [{}, { listening: false }, { noteTitle: 'TEKBİR', noteTurkish: 'Allah en büyüktür' },
    { blank: true }, { hideStatus: true, surah: 0 }, { bigHeader: false }, { showArabic: true }]) {
    const s = L.buildScreen({ ...ST, bigText: true, demo: 4, ...extra }, ui);
    assert.equal(s.layout, 'demob', JSON.stringify(extra));
    assert.equal(s.demoLevel, 4);
    assert.equal(s.pages, 1);
  }
  const maxW = L.SCREEN_W - L.DEMO.numW - L.DEMO.padR;
  for (const px of [30, 36, 48, 64, 80]) {
    const d = [1, 2, 3, 4].map((lv) => demoBig(lv, px));
    // G2 YAZI BOYUTU'nda; demo 4 satir kapasitesinin tamami, blok cercevenin icinde
    assert.ok(d.every((x) => x.px === px));
    assert.equal(d[3].lines.length, d[3].perPage, `${px} px`);
    assert.ok(d[3].y0 >= L.DEMO.frame && d[3].y0 + d[3].perPage * d[3].lineH <= L.SCREEN_H - L.DEMO.frame, `${px} px`);
    // satirlar sigar, artan doluluk
    for (const x of d) for (const line of x.lines) assert.ok(approxMeasure(line, px) <= maxW, `${px} px: ${line}`);
    assert.ok(d[1].lines.length <= d[2].lines.length && d[2].lines.length <= d[3].lines.length, `${px} px`);
  }
  // demo 1 kisa (48 px'te tek satir); boyut buyudukce demo 4'te satir azalir
  assert.equal(demoBig(1, 48).lines.length, 1);
  assert.ok(demoBig(4, 30).lines.length > demoBig(4, 80).lines.length);
  // ekran yerlesimi ayardaki punto ile (yazi boyutu degisince degisir)
  assert.equal(L.buildScreen({ ...ST, bigText: true, demo: 4, textPx: 64 }, ui).demo.px, 64);
  // gozlugun kendi yazisi (NORMAL ya da buyuk yazi fontu yuklenmedi): 1 / 3 / 6 / 10 numarali satir, cerceveli kutu
  const D = L.LAYOUTS.demo;
  assert.ok(D.bodyLines * L.LINE_H + 2 * (D.padding + D.border.width) <= D.body.h);
  assert.ok(D.border.width >= 1 && D.border.width <= 5 && D.border.color >= 0 && D.border.color <= 16);
  for (const [lv, n] of [[1, 1], [2, 3], [3, 6], [4, 10]]) {
    for (const [st, u] of [[{ ...ST, bigText: false, demo: lv }, ui], [{ ...ST, bigText: true, demo: lv }, { connected: true }]]) {
      const s = L.buildScreen(st, u);
      assert.equal(s.layout, 'demo');
      const ls = lines(s.body);
      assert.equal(ls.length, n, `demo ${lv}`);
      ls.forEach((l, i) => {
        assert.ok(l.startsWith(`${i + 1}  `), l);
        assert.ok(L.textWidth(l) <= L.SCREEN_W - 2 * (D.padding + D.border.width), l);
      });
      assert.ok(L.utf8Bytes(s.body) <= L.TEXT_MAX_BYTES);
    }
  }
  // baglanti yoksa tani ekrani (demo bilinmiyor)
  assert.match(L.buildScreen({ ...ST, demo: 3 }, { connected: false }).body, /bağlanılamıyor/);
});

test('mealde ayet adi (mealLabel): basta / sonda / kapali; satir artiracaksa sadece mealLabelGrow ile', () => {
  const ui = { connected: true };
  // gozlugun kendi yazisi: kisa meal, ayet adi sigar → eklenir
  const kev = { ...ST, bigText: false };
  const base = L.buildScreen(kev, ui);
  assert.ok(L.buildScreen({ ...kev, mealLabel: 'start' }, ui).body.startsWith('Kevser: 2 — Şu halde'));
  assert.ok(L.buildScreen({ ...kev, mealLabel: 'end' }, ui).body.endsWith('kurban kes. — Kevser: 2'));
  for (const v of ['off', undefined, 'x']) assert.equal(L.buildScreen({ ...kev, mealLabel: v }, ui).body, base.body);
  // satiri dolu meal: ayet adi yeni satir acacaksa eklenmez; mealLabelGrow ile eklenir
  const words = LONG.split(' ');
  let full = null;
  for (let n = 4; n < words.length && !full; n++) {
    const m = words.slice(0, n).join(' ');
    if (L.wrap(m + ' — Kevser: 2').length > L.wrap(m).length && L.wrap(m).length <= 8) full = m;
  }
  assert.ok(full, 'satiri dolu meal bulunamadi');
  const st = { ...kev, meal: full, mealLabel: 'end' };
  assert.equal(L.buildScreen(st, ui).body, L.buildScreen({ ...st, mealLabel: 'off' }, ui).body);
  assert.ok(L.buildScreen({ ...st, mealLabelGrow: true }, ui).body.endsWith('— Kevser: 2'));
  // buyuk yazi, sabit boyut: satir eklemiyorsa eklenir, ekliyorsa sadece mealLabelGrow ile
  const big = { ...ST, bigText: true, bigHeader: false, fixedSize: true, textPx: 48 };
  const bl = (s) => s.big.pages.flat();
  const bigLines = (m, extra) => bl(L.buildScreen({ ...big, meal: m, ...extra }, { connected: true, fitBig }));
  let bigFits = null, bigFull = null;
  for (let n = 1; n < words.length && !(bigFits && bigFull); n++) {
    const m = words.slice(0, n).join(' ');
    const a = bigLines(m).length;
    const b = bigLines(m, { mealLabel: 'end', mealLabelGrow: true }).length;
    if (b === a && !bigFits) bigFits = m;
    if (b > a && !bigFull) bigFull = m;
  }
  assert.ok(bigFits && bigFull, 'sabit boyutta sigan / sigmayan meal bulunamadi');
  assert.match(bigLines(bigFits, { mealLabel: 'start' }).join(' '), /^Kevser: 2 — /);
  assert.ok(bigLines(bigFits, { mealLabel: 'end' }).join(' ').endsWith('Kevser: 2'));
  assert.ok(!bigLines(bigFull, { mealLabel: 'end' }).join(' ').includes('Kevser: 2'));
  assert.ok(bigLines(bigFull, { mealLabel: 'end', mealLabelGrow: true }).join(' ').endsWith('Kevser: 2'));
  // degisken boyut: ayet adi yaziyi kucultecekse eklenmez (satir yerine punto kuculur), mealLabelGrow ile eklenir
  const vb = { ...big, fixedSize: false, meal: 'Allah birdir.', mealLabel: 'start' };
  const v0 = L.buildScreen({ ...vb, mealLabel: 'off' }, { connected: true, fitBig });
  const v1 = L.buildScreen(vb, { connected: true, fitBig });
  const v2 = L.buildScreen({ ...vb, mealLabelGrow: true }, { connected: true, fitBig });
  assert.equal(v1.big.px, v0.big.px);
  assert.ok(!bl(v1).join(' ').includes('Kevser'));
  assert.ok(bl(v2).join(' ').startsWith('Kevser: 2 —') && v2.big.px <= v0.big.px);
  // not karti / bos ekran: ayet adi yok
  assert.ok(!L.buildScreen({ ...kev, mealLabel: 'start', noteTitle: 'TEKBİR', noteTurkish: 'Allah en büyüktür' }, ui).body.includes('Kevser'));
});

test('zikir / ezan karti: sadece Turkce anlami (okunus yok), yoksa okunus', () => {
  const note = { noteTitle: 'TEKBİR', noteReading: 'Allâhu ekber', noteTurkish: 'Allah en büyüktür' };
  for (const extra of [{ bigText: true }, { bigText: true, bigHeader: false }, { bigText: false }]) {
    const s = L.buildScreen({ ...ST, ...extra, ...note }, { connected: true, fitBig });
    const text = s.big ? s.big.pages.flat().join(' ') : s.body;
    assert.equal(text, 'Allah en büyüktür', JSON.stringify(extra));
    assert.doesNotMatch(text, /Allâhu/);
  }
  assert.equal(L.noteText({ noteTitle: 'KAMET', noteReading: "Kad kâmeti's-salâh", noteTurkish: '' }), "Kad kâmeti's-salâh");
  assert.equal(L.noteText({ noteTitle: 'KAMET', noteReading: '', noteTurkish: '' }), 'KAMET');
});

test('bos ekranda ust bilgi (blankHeader) ve durum yazisi gizli (hideStatus): ekran bombos', () => {
  const blank = { ...ST, bigText: true, blank: true, rakat: '1. REKÂT · RÜKÛ / SECDE' };
  // alan yoksa (eski uygulama) ustte rekat; false → bos
  assert.equal(L.buildScreen(blank, { connected: true, fitBig }).header, '1. REKÂT · RÜKÛ / SECDE');
  assert.equal(L.buildScreen({ ...blank, blankHeader: true }, { connected: true, fitBig }).header, '1. REKÂT · RÜKÛ / SECDE');
  for (const extra of [{}, { bigHeader: false }, { bigText: false }, { showArabic: true }, { sim: true }]) {
    const s = L.buildScreen({ ...blank, ...extra, blankHeader: false }, { connected: true, fitBig, arabicLineCount: 2 });
    assert.equal(s.blank, true);
    assert.equal(s.header.trim(), '', JSON.stringify(extra));
    assert.equal(s.body.trim(), '');
    assert.equal(s.big, null);
  }
  // zikir karti bos ekrandan once
  assert.equal(L.buildScreen({ ...blank, blankHeader: false, noteTitle: 'TEKBİR', noteTurkish: 'Allah en büyüktür' },
    { connected: true, fitBig }).big.pages.flat().join(' '), 'Allah en büyüktür');
  // durum yazisi gizli: dinleme kapali / dinleniyor / kamet beklemesi → bos; ayet ve not kartlari gelir
  for (const extra of [{ bigText: true }, { bigText: true, bigHeader: false }, { bigText: false }]) {
    for (const st of [{ ...ST, listening: false, status: 'Hazır' }, { ...ST, surah: 0, status: 'Dinleniyor' },
      { ...ST, surah: 0, status: 'Kamet · Fatiha bekleniyor', sim: true }]) {
      const s = L.buildScreen({ ...st, ...extra, hideStatus: true }, { connected: true, fitBig });
      assert.equal(s.blank, true, JSON.stringify([extra, st.status]));
      assert.equal(s.header.trim() + s.body.trim(), '');
      assert.equal(s.big, null);
    }
    const ayet = L.buildScreen({ ...ST, ...extra, hideStatus: true }, { connected: true, fitBig });
    assert.notEqual(ayet.blank, true);
    const not = L.buildScreen({ ...ST, ...extra, listening: false, hideStatus: true, noteTitle: 'SELAM',
      noteTurkish: "Allah'ın selamı ve rahmeti üzerinize olsun" }, { connected: true, fitBig });
    assert.notEqual(not.blank, true);
  }
  // kapaliyken eski yazi; baglanti yoksa tani ekrani (ayar bilinmiyor)
  assert.equal(L.buildScreen({ ...ST, bigText: true, listening: false }, { connected: true, fitBig }).big.pages[0].join(' '),
    'Dinleme kapalı');
  assert.match(L.buildScreen({ ...ST, hideStatus: true }, { connected: false }).body, /bağlanılamıyor/);
});

test('ust bilgi kapali gozlugun kendi yazisinda / Arapcada da: basliksiz duzen, daha cok satir', () => {
  const st = { ...ST, surah: 2, ayah: 282, surahName: 'Bakara', meal: LONG, progress: 0, bigText: false };
  const t = L.buildScreen({ ...st, bigHeader: false }, { connected: true, fitBig });
  assert.equal(t.layout, 'textn');
  assert.equal(L.LAYOUTS.textn.header, null);
  assert.equal(t.header.trim(), '');
  assert.equal(lines(t.body).length, L.LAYOUTS.textn.bodyLines);
  assert.ok(L.LAYOUTS.textn.bodyLines > L.LAYOUTS.text.bodyLines);
  // baslik acikken eski duzen
  assert.equal(L.buildScreen(st, { connected: true, fitBig }).layout, 'text');
  // Arapca: bant en ustte, altinda daha cok satir; Arapca sayfalariyla senkron
  const a = L.buildScreen({ ...st, showArabic: true, bigHeader: false }, { connected: true, arabicLineCount: 4 });
  assert.equal(a.layout, 'arabicn');
  assert.equal(a.header.trim(), '');
  assert.equal(a.arabicPages, 2);
  assert.ok(lines(a.body).length <= L.LAYOUTS.arabicn.bodyLines);
  assert.ok(L.LAYOUTS.arabicn.bodyLines > L.LAYOUTS.arabic.bodyLines);
  for (const k of L.LAYOUTS.arabicn.tiles) assert.equal(k.y, 0);
  assert.equal(L.buildScreen({ ...st, showArabic: true }, { connected: true, arabicLineCount: 4 }).layout, 'arabic');
  // not, bosta, dinleniyor da basliksiz; aday sonuk
  for (const x of [{ noteTitle: 'TEKBİR', noteTurkish: 'Allah en büyüktür' }, { listening: false }, { surah: 0 },
    { tentative: true }]) {
    const s = L.buildScreen({ ...st, ...x, bigHeader: false }, { connected: true, fitBig });
    assert.equal(s.layout, 'textn', JSON.stringify(x));
    assert.equal(s.header.trim(), '');
    assert.ok(s.body.trim().length > 0);
  }
  assert.ok(L.buildScreen({ ...st, tentative: true, bigHeader: false }, { connected: true }).bodyColor < L.BRIGHT.body);
  // baglanti yokken tani ekrani baslikli (ayar bilinmiyor)
  assert.equal(L.buildScreen({ ...st, bigHeader: false }, { connected: false }).layout, 'text');
});

test('rekat bilgisi gizli (hideRakat): baslikta sadece "Sure: ayet", notta sadece baslik, bos ekran ust satiri bos', () => {
  const rk = { ...ST, surahName: 'Kevser', rakat: '1. REKÂT · KIYAM', hideRakat: true };
  for (const extra of [{ bigText: true }, { bigText: false }, { showArabic: true }]) {
    const s = L.buildScreen({ ...rk, ...extra }, { connected: true, fitBig, arabicLineCount: 2 });
    assert.equal(s.header, 'Kevser: 2', JSON.stringify(extra));
    const n = L.buildScreen({ ...rk, ...extra, noteTitle: 'TEKBİR', noteTurkish: 'Allah en büyüktür' },
      { connected: true, fitBig, arabicLineCount: 2 });
    assert.equal(n.header, 'TEKBİR');
    const d = L.buildScreen({ ...rk, ...extra, surah: 0 }, { connected: true, fitBig });
    assert.doesNotMatch(d.header, /REKÂT/);
  }
  // aday ve sayfa etiketi kalir
  const u = L.buildScreen({ ...rk, bigText: true, surah: 2, ayah: 282, surahName: 'Bakara', meal: LONG, tentative: true },
    { connected: true, fitBig });
  assert.match(u.header, /^Bakara: 282 · ADAY \d+\/\d+$/);
  // kapaliyken rekat baslikta
  assert.match(L.buildScreen({ ...rk, hideRakat: false, bigText: true }, { connected: true, fitBig }).header, /REKÂT/);
  // bos ekran: ust bilgi acik olsa da rekat yazmaz
  const b = L.buildScreen({ ...rk, blank: true, blankHeader: true }, { connected: true, fitBig });
  assert.equal(b.blank, true);
  assert.equal(b.header.trim(), '');
  assert.equal(L.buildScreen({ ...rk, hideRakat: false, blank: true, blankHeader: true }, { connected: true, fitBig }).header,
    '1. REKÂT · KIYAM');
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
  const onePx = [];
  let onePaged = 0;
  let oneDefPaged = 0;
  let oneDefMax = 1;
  for (const [s, a, meal] of meals) {
    // tek ekrana sigdir (baslikli, 48 px): alt sinir 12'de hepsi tek sayfa olmali (en kucuk punto); varsayilan alt sinirda
    // (20) kac meal sayfali, en cok kac sayfa
    const opst = { ...ST, bigText: true, onePage: true, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal };
    const op = L.buildScreen({ ...opst, onePageMinPx: 12 }, { connected: true, fitBig });
    if (op.pages > 1) onePaged++;
    else onePx.push(op.big.px);
    const od = L.buildScreen(opst, { connected: true, fitBig });
    if (od.pages > 1) { oneDefPaged++; oneDefMax = Math.max(oneDefMax, od.pages); }
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
    for (const [arabic, bigHeader] of [[false, true], [true, true], [false, false], [true, false]]) {
      const st = { ...ST, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal, showArabic: arabic, rakat: '2. REKÂT · KIYAM',
        bigHeader };
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
    onepage_paged: onePaged, onepage_px_min: Math.min(...onePx), onepage_px_median: median(onePx),
    onepage_below_20: onePx.filter((x) => x < 20).length, onepage_default_paged: oneDefPaged,
    onepage_default_max_pages: oneDefMax,
    dropped: Object.fromEntries(dropped) })}`);
});

// Secilebilir mealler (scripts/build_meals.py → <assets>/asr/meals/<id>.bin + index.tsv; Ayarlar → MEAL). Varsayilan meal
// (meal.bin) yukarida agir testten gecer; digerleri hafif dongu: gozluk fontu, normal duzende satir / bayt / genislik
// (baslikli ve basliksiz Arapcali), buyuk yazida sayfa sayisi.
const MEALS_DIR = process.env.TILAVET_MEALS_DIR;
test('secilebilir mealler: font, satir, bayt', { skip: !MEALS_DIR || !fs.existsSync(MEALS_DIR + '/index.tsv') }, () => {
  const index = fs.readFileSync(MEALS_DIR + '/index.tsv', 'utf8').split('\n').filter((l) => l && !l.startsWith('#'))
    .map((l) => { const [id, file, merged, name, desc] = l.split('\t'); return { id, file, merged: +merged, name, desc }; });
  assert.ok(index.length >= 1 && index[0].file === 'meal.bin', 'index: ilk meal varsayilan (meal.bin)');
  const ids = new Set();
  const per = {};
  const dropped = new Map();
  let maxPages = 0;
  let bigMax = 0;
  for (const ed of index) {
    assert.ok(ed.id && ed.name && !ids.has(ed.id), 'index girdisi ' + JSON.stringify(ed));
    ids.add(ed.id);
    if (ed.file === 'meal.bin') continue;
    const { meals, names } = readMealBin(MEALS_DIR + '/' + ed.file.replace(/^meals\//, ''));
    assert.equal(meals.length, 6236, `${ed.id} meal sayisi`);
    let edDropped = 0;
    let edMax = 0;
    let edBig = 0;
    for (const [s, a, meal] of meals) {
      assert.ok(meal.length > 0, `${ed.id} ${s}:${a} bos`);
      for (const ch of meal) {
        const cp = ch.codePointAt(0);
        if (ch !== ' ' && L.charWidth(cp) === 0 && L.sanitize(ch) === '') {
          dropped.set(ch, (dropped.get(ch) || 0) + 1);
          edDropped++;
        }
      }
      for (const [arabic, bigHeader] of [[false, true], [true, false]]) {
        const st = { ...ST, surah: s, ayah: a, surahName: names[s - 1] || 'X', meal, showArabic: arabic,
          rakat: '2. REKÂT · KIYAM', bigHeader };
        const s0 = L.buildScreen(st, { connected: true, arabicLineCount: arabic ? 4 : 0 });
        edMax = Math.max(edMax, s0.pages);
        for (let p = 0; p < s0.pages; p++) {
          const sp = L.buildScreen(st, { connected: true, arabicLineCount: arabic ? 4 : 0,
            manual: { key: `${s}:${a}`, base: s0.autoPage, page: p } });
          const ls = lines(sp.body);
          assert.ok(ls.length <= L.LAYOUTS[sp.layout].bodyLines, `${ed.id} ${s}:${a} satir`);
          assert.ok(L.utf8Bytes(sp.body) <= L.TEXT_MAX_BYTES, `${ed.id} ${s}:${a} bayt`);
          for (const l of ls) assert.ok(L.textWidth(l) <= L.WRAP_W, `${ed.id} ${s}:${a} genislik`);
        }
      }
      edBig = Math.max(edBig, L.fitBigText(L.sanitizeBig(meal), approxMeasure).pages.length);
    }
    for (const n of names) assert.equal(L.sanitize(n), n, `${ed.id} sure adi fontta: ` + n);
    per[ed.id] = { dropped: edDropped, max_pages: edMax, big_max_pages: edBig };
    maxPages = Math.max(maxPages, edMax);
    bigMax = Math.max(bigMax, edBig);
  }
  console.log(`G2_EDITIONS ${JSON.stringify({ editions: index.length, max_pages: maxPages, big_max_pages: bigMax,
    dropped_chars: [...dropped.values()].reduce((x, y) => x + y, 0), dropped: Object.fromEntries(dropped), per })}`);
});

// ------------------------------------------------------------------ buyuk yazi fontlari (Ayarlar → G2 YAZI TİPİ)

test('buyuk yazi fontu: secim, kalinlik, bilinmeyen deger', () => {
  assert.deepEqual(L.bigFontOf(null), L.BIG_FONT_DEFAULT);
  assert.deepEqual(L.bigFontOf({}), { id: 'manrope', weight: 700 });
  assert.deepEqual(L.bigFontOf({ bigFont: 'lexend', bigWeight: 300 }), { id: 'lexend', weight: 300 });
  assert.deepEqual(L.bigFontOf({ bigFont: 'yok', bigWeight: 800 }), { id: 'manrope', weight: 800 });
  assert.deepEqual(L.bigFontOf({ bigFont: 'toString', bigWeight: 0 }), { id: 'manrope', weight: 700 });
  assert.equal(L.bigFontOf({ bigFont: 'inter', bigWeight: 650 }).weight, 700);   // en yakin kalinlik
  assert.equal(L.bigFontOf({ bigFont: 'inter', bigWeight: 100 }).weight, 300);
  for (const [id, f] of Object.entries(L.BIG_FONTS)) {
    assert.match(f.file, /^g2font-[a-z]+\.ttf$/, id);
    assert.ok(fs.existsSync(path.join(FONT_DIR, f.file.replace('g2font-', ''))), `${id}: assets/g2fonts dosyasi`);
    const [lo, hi] = f.weights.split(' ').map(Number);
    for (const w of L.BIG_WEIGHTS) assert.ok(w >= lo && w <= hi, `${id}: ${w} kalinlik araligi ${f.weights}`);
  }
  // her fontun lisansi APK'da
  for (const id of Object.keys(L.BIG_FONTS)) assert.ok(fs.existsSync(path.join(FONT_DIR, `OFL-${id}.txt`)), `${id} OFL`);
});

const FONT_DIR = path.join(here, '../../tilavet-android/app/src/main/assets/g2fonts');

/** TTF cmap (biçim 4 ve 12) → kod noktasi kumesi. */
function ttfCodepoints(file) {
  const b = fs.readFileSync(file);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const nTables = dv.getUint16(4);
  let cmap = -1;
  for (let i = 0; i < nTables; i++) {
    const o = 12 + i * 16;
    if (b.toString('latin1', o, o + 4) === 'cmap') cmap = dv.getUint32(o + 8);
  }
  assert.ok(cmap >= 0, file + ': cmap yok');
  const cps = new Set();
  const n = dv.getUint16(cmap + 2);
  for (let i = 0; i < n; i++) {
    const off = cmap + dv.getUint32(cmap + 4 + i * 8 + 4);
    const fmt = dv.getUint16(off);
    if (fmt === 4) {
      const segX2 = dv.getUint16(off + 6);
      const ends = off + 14; const starts = ends + segX2 + 2; const deltas = starts + segX2; const ranges = deltas + segX2;
      for (let s = 0; s < segX2 / 2; s++) {
        const end = dv.getUint16(ends + 2 * s); const start = dv.getUint16(starts + 2 * s);
        const delta = dv.getInt16(deltas + 2 * s); const ro = dv.getUint16(ranges + 2 * s);
        for (let c = start; c <= end && c !== 0xffff; c++) {
          let g;
          if (ro === 0) g = (c + delta) & 0xffff;
          else {
            g = dv.getUint16(ranges + 2 * s + ro + 2 * (c - start));
            if (g) g = (g + delta) & 0xffff;
          }
          if (g) cps.add(c);
        }
      }
    } else if (fmt === 12) {
      const groups = dv.getUint32(off + 12);
      for (let gi = 0; gi < groups; gi++) {
        const go = off + 16 + gi * 12;
        const start = dv.getUint32(go); const end = dv.getUint32(go + 4); const g0 = dv.getUint32(go + 8);
        for (let c = start; c <= end; c++) if (g0 + (c - start)) cps.add(c);
      }
    }
  }
  return cps;
}

// Buyuk yazida bir karakter fontta yoksa tarayici baska fonttan cizer (satir icinde farkli harf) → her fontta, varsayilan
// mealin ve (varsa) secilebilir meallerin tum karakterleri + Turkce harfler + zikir / ezan kartlarinin metinleri olmali.
test('buyuk yazi fontlari: tum meal karakterleri fontta', () => {
  const chars = new Set('ÂÎÛâîûİıŞşĞğÇçÖöÜü·—–…');
  for (const t of ['Allah en büyüktür', 'Rabbimiz! Hamd sana mahsustur', 'Allah, kendisine hamd edeni işitti']) {
    for (const ch of t) chars.add(ch);
  }
  const bins = [];
  if (MEAL_BIN && fs.existsSync(MEAL_BIN)) bins.push(MEAL_BIN);
  if (MEALS_DIR && fs.existsSync(MEALS_DIR)) {
    for (const f of fs.readdirSync(MEALS_DIR)) if (f.endsWith('.bin')) bins.push(path.join(MEALS_DIR, f));
  }
  for (const p of bins) for (const [, , meal] of readMealBin(p).meals) for (const ch of meal) chars.add(ch);
  chars.delete(' ');
  chars.delete('\n');
  const missing = {};
  let total = 0;
  for (const [id, f] of Object.entries(L.BIG_FONTS)) {
    const cps = ttfCodepoints(path.join(FONT_DIR, f.file.replace('g2font-', '')));
    // gozlukte zaten cizilmeyen (sanitizeBig'in attigi) karakterler sayilmaz
    const miss = [...chars].filter((ch) => !cps.has(ch.codePointAt(0)) && L.sanitizeBig(ch) !== '');
    if (miss.length) missing[id] = miss.join('');
    total += miss.length;
  }
  console.log(`G2_FONTS ${JSON.stringify({ fonts: Object.keys(L.BIG_FONTS).length, chars: chars.size,
    meal_files: bins.length, dropped_chars: total, missing })}`);
  assert.equal(total, 0, 'fontta olmayan karakter: ' + JSON.stringify(missing));
});
