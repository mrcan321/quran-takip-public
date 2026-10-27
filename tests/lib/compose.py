"""Gercek kayitlarin TRJSON parcalarindan bilesik senaryolar (ASR'siz, metin duzeyinde):

- Zorlama S1-S5 (bkz. CLAUDE.md acik sorun 10): kamet + namaz, kamet + Fatiha'siz sure, hutbe + kamet + namaz,
  %15 gurultu enjeksiyonu, okuma ortasinda sahte tekbir.
- Teravih / uzun namaz bilesimleri: gercek cami kayitlarindan kesilen Fatiha, zamm, rukû/secde (semiallah dahil) ve
  tahiyyat/selam bolumleriyle 20 rekatlik teravih (her 4 rekatta tesbih + salavat arasi), hatimle teravih (Rahman iki
  rekata bolunmus: 2. rekat kalinan ayetten devam) ve 4 rekatli namaz (3-4. rekat sessiz, sadece semiallah duyulur).
  Beklenen rekat / namaz sayisi Kotlin RakatTracker'la olculur (gate.py).
"""
import random

from . import env

ev = env.ev
CUMA = "namaz_cuma_kamet_fatiha_enbiya_fatiha_insirah.wav"
NAMAZ_FILES = ("namaz_aksam_fatiha_zilzal_fatiha_kafirun.wav", "namaz_aksam2_fatiha_rad_fatiha_ibrahim.wav",
               CUMA, "namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav")
RAHMAN = "session_1777009737.wav"

# Turkiye'de teravihte her 4 rekatta okunan tesbih + salavat (Kuran degil; aday / kilit uretmemeli)
TERAVIH_TESBIH = [
    "سبحان ذي الملك والملكوت",
    "سبحان ذي العزة والعظمة والهيبة والقدرة",
    "والكبرياء والجبروت سبحان الملك الحي الذي لا ينام",
    "ولا يموت سبوح قدوس ربنا ورب الملائكة والروح",
    "اللهم صل على سيدنا محمد وعلى آل سيدنا محمد",
    "اللهم أجرنا من النار يا مجير يا مجير",
]
HALLU = ["شركة الهدى للخدمات التقنية", "المصدر كتاب", "موسوعة النابلسي للعلوم الإسلامية", "المصدر صور من حياة"]


# ---------------- parca araclari ----------------
def times(chunks):
    return [env.chunk_time(c, k) for k, c in enumerate(chunks)]


def shift(chunks, off):
    out = []
    for k, c in enumerate(chunks):
        c = list(c) + [None] * (6 - len(c))
        c[2] = round(env.chunk_time(c, k) + off, 2)
        if c[4] is not None:
            c[4] = round(c[4] + off, 2)
        out.append(c)
    return out


def concat(parts):
    """parts: [(chunks, timeline)] → (tek kayit, timeline); zamanlar kaydirilir."""
    allc, tl, off = [], [], 0.0
    for chunks, t in parts:
        sc = shift(chunks, off)
        allc += sc
        tl += [(st + off, su) for st, su in (t or [])]   # zaman cizelgesi henuz yazilmamis yeni kayit: bolumsuz
        off = sc[-1][2] if sc else off
    return allc, tl


def piece(chunks, t0, t1):
    """Bitis zamani (t0, t1] araligindaki parcalar; zamanlar t0'a gore."""
    out = []
    for k, c in enumerate(chunks):
        t = env.chunk_time(c, k)
        if t0 < t <= t1:
            c2 = list(c) + [None] * (6 - len(c))
            c2[2] = round(t - t0, 2)
            if c2[4] is not None:
                c2[4] = round(c2[4] - t0, 2)
            out.append(c2)
    return out


def text_chunks(texts, rms=0.05, step=5.0):
    return [[rms, t, round((i + 1) * step, 2), False, None, None] for i, t in enumerate(texts)]


def silence(n, step=5.0):
    return [[0.0, "", round((i + 1) * step, 2), False, None, None] for i in range(n)]


def sections(fn, chunks):
    """TIMELINE bolumleri → [(sure|None, parcalar)]"""
    tl = ev.timeline_for(fn)
    if not tl:
        return []
    end = times(chunks)[-1] if chunks else 0.0
    out = []
    for i, (st, su) in enumerate(tl):
        nxt = tl[i + 1][0] if i + 1 < len(tl) else end + 1
        out.append((su, piece(chunks, st, nxt)))
    return out


# ---------------- zorlama S1-S5 ----------------
def stress_scenarios(T, seeds=5):
    """T: {dosya: parcalar} (bir zincir) → [(senaryo, [(ad, parcalar, timeline)])]"""
    out = []
    cuma = T[CUMA]
    pre_n = next(k for k, c in enumerate(cuma) if env.chunk_time(c, k) > 80)
    kamet = cuma[:pre_n]
    fatiha_start = sorted(fn for fn in T if (tl := ev.timeline_for(fn)) and any(su == 1 for _, su in tl) and fn != CUMA)
    out.append(("S1 kamet + Fatiha ile baslayan kayit",
                 [(f"kamet+{fn}", *concat([(kamet, [(0, None)]), (T[fn], ev.timeline_for(fn))])) for fn in fatiha_start]))
    singles = [fn for fn in sorted(T) if isinstance(ev.EXPECTED.get(fn), int) and ev.EXPECTED[fn] != 1]
    out.append(("S2 kamet + Fatiha'siz tek sure",
                 [(f"kamet+{fn}", *concat([(kamet, [(0, None)]), (T[fn], ev.timeline_for(fn))])) for fn in singles]))
    hutbe = T[RAHMAN][:8]
    namazlar = [fn for fn in sorted(T) if fn.startswith(("namaz_", "sentetik_", "telefon_fatiha"))]
    out.append(("S3 hutbe + kamet + namaz",
                 [(f"hutbe+kamet+{fn}", *concat([(hutbe, [(0, 55)]), (kamet, [(0, None)]), (T[fn], ev.timeline_for(fn))]))
                  for fn in namazlar]))
    # Gurultu kelimeleri: transkriptlerdeki kelimeler (repo verisi). Korpus sozlugu kullanilmaz: yereldeki korpus kopyasi
    # CI'dakinden (alquran.cloud) birkac kelime farkli → sirali listede rastgele secim kayiyordu, S4 makineye gore degisti.
    vocab = sorted({w for ch in T.values() for c in ch for w in (c[1] or "").split()})
    tl_files = [fn for fn in sorted(T) if ev.timeline_for(fn) and ev.EXPECTED.get(fn) is not None]
    cases = []
    for seed in range(seeds):
        rnd = random.Random(seed)
        for fn in tl_files:
            ch = [list(c) for c in T[fn]]
            for c in ch:
                if rnd.random() < 0.15:
                    kind = rnd.random()
                    c[0] = max(c[0] or 0, 0.05)
                    if kind < 0.35:
                        c[1] = rnd.choice(HALLU)
                    elif kind < 0.85:
                        c[1] = " ".join(rnd.choice(vocab) for _ in range(rnd.randint(2, 5)))
                    else:
                        c[1] = ""
            cases.append((f"s{seed} {fn}", ch, ev.timeline_for(fn)))
    out.append(("S4 gurultu %15", cases))
    cases = []
    for seed in range(seeds):
        rnd = random.Random(100 + seed)
        for fn in tl_files:
            ch = [list(c) for c in T[fn]]
            tl = ev.timeline_for(fn)
            tt = times(ch)
            idx = [k for k in range(len(ch)) if k > 2 and ch[k][1] and any(su for s0, su in tl if s0 <= tt[k])]
            for k in rnd.sample(idx, min(2, len(idx))):
                ch[k][1] = "الله أكبر"
            cases.append((f"s{seed} {fn}", ch, tl))
    out.append(("S5 okuma ortasinda sahte tekbir", cases))
    return out


# ---------------- teravih / uzun namaz bilesimleri ----------------
def prayer_pieces(T):
    """Gercek namaz kayitlarindan: Fatiha, zamm, rukû/secde araligi, son (tahiyyat + selam) parcalari."""
    fatihas, zamms, gaps, ends = [], [], [], []
    for fn in NAMAZ_FILES:
        if fn not in T:
            continue
        secs = sections(fn, T[fn])
        quran = [i for i, (su, _) in enumerate(secs) if su is not None]
        for i, (su, ch) in enumerate(secs):
            if su == 1:
                fatihas.append((fn, ch))
            elif su is not None:
                zamms.append((su, fn, ch))
            elif quran and quran[0] < i < quran[-1]:
                gaps.append((fn, ch))          # iki rekat arasi: rukû + secde (+ semiallah)
            elif quran and i > quran[-1] and "cuma" in fn:
                # son bolum (sadece 2 rekatli namazlardan — aksamlarin sonunda sessiz 3. rekat var): selam + 2 parca
                # (dua kismi kirpilir — teravihte sonraki namaz hemen baslar)
                cut = next((k for k, c in enumerate(ch) if env.sm.namaz_signal(c[1] or "") == "selam"), None)
                ends.append((fn, ch if cut is None else ch[:cut + 3]))
    singles = []
    for fn in sorted(T):
        if not isinstance(ev.EXPECTED.get(fn), int) or ev.EXPECTED[fn] == 1 or fn.startswith("session_17770275"):
            continue
        ch = T[fn]
        if sum(1 for c in ch if c[1]) < 0.5 * len(ch):
            continue        # 1-2 parca okuyup susan kayitlar (session_1777005126/6567): zamm'in ortasinda dakikalik sessizlik
        last = max((k for k, c in enumerate(ch) if c[1]), default=-1)
        singles.append((ev.EXPECTED[fn], fn, ch[:last + 2]))     # sondaki sessizlik kirpilir (rukû hemen gelir)
    return fatihas, zamms + singles, gaps, ends


def teravih_compositions(T):
    """→ [(ad, parcalar, timeline, beklenen_rekat, beklenen_namaz)]"""
    fatihas, zamms, gaps, ends = prayer_pieces(T)
    if not (fatihas and zamms and gaps and ends):
        return []
    out = []
    zk = sorted(zamms, key=lambda z: (z[0], z[1]))

    # Teravih 20 rekat: 10 x 2 rekat, her 4 rekatta tesbih + salavat
    parts = []
    for n in range(10):
        f1, f2 = fatihas[(2 * n) % len(fatihas)], fatihas[(2 * n + 1) % len(fatihas)]
        z1, z2 = zk[(2 * n) % len(zk)], zk[(2 * n + 1) % len(zk)]
        g, e = gaps[n % len(gaps)], ends[n % len(ends)]
        parts += [(f1[1], [(0, 1)]), (z1[2], [(0, z1[0])]), (g[1], [(0, None)]),
                  (f2[1], [(0, 1)]), (z2[2], [(0, z2[0])]), (e[1], [(0, None)])]
        if n % 2 == 1 and n < 9:
            parts += [(silence(2) + text_chunks(TERAVIH_TESBIH) + silence(2), [(0, None)])]
    ch, tl = concat(parts)
    out.append(("teravih 20 rekat (kisa sureler + tesbih/salavat)", ch, tl, 20, 10))

    # Hatimle teravih: Rahman iki rekata bolunur, 2. rekat kalinan ayetten devam eder (55:14+)
    if RAHMAN in T:
        rch = T[RAHMAN]
        mid = env.chunk_time(rch[18], 18) if len(rch) > 20 else env.chunk_time(rch[-1], len(rch) - 1) / 2
        r1, r2 = piece(rch, 0, mid), piece(rch, mid, 1e9)
        f1, f2 = fatihas[0], fatihas[1 % len(fatihas)]
        ch, tl = concat([(f1[1], [(0, 1)]), (r1, [(0, 55)]), (gaps[0][1], [(0, None)]),
                         (f2[1], [(0, 1)]), (r2, [(0, 55)]), (ends[0][1], [(0, None)])])
        out.append(("hatimle teravih (Rahman 2 rekata bolunmus)", ch, tl, 2, 1))

    # 4 rekatli namaz: 3-4. rekat sessiz (sadece rukû/secde araligi = tekbir + semiallah duyulur)
    sem_gaps = [g for g in gaps if any(env.sm.namaz_signal(c[1] or "") == "ruku" for c in g[1])]
    if sem_gaps:
        g = sem_gaps[0][1]
        f1, f2 = fatihas[0], fatihas[1 % len(fatihas)]
        z1, z2 = zk[0], zk[1 % len(zk)]
        ch, tl = concat([(f1[1], [(0, 1)]), (z1[2], [(0, z1[0])]), (g, [(0, None)]),
                         (f2[1], [(0, 1)]), (z2[2], [(0, z2[0])]), (g, [(0, None)]),
                         (silence(12), [(0, None)]),       # oturus (tahiyyat) + 3. rekata kalkis
                         (silence(6), [(0, None)]), (g, [(0, None)]),   # 3. rekat: sessiz Fatiha, rukû/secde
                         (silence(6), [(0, None)]),                      # 4. rekat: sessiz Fatiha
                         (ends[0][1], [(0, None)])])       # son parca: 4. rekatin rukûsu (semiallah) + secde + selam
        out.append(("4 rekatli namaz (3-4. rekat sessiz)", ch, tl, 4, 1))
    return out
