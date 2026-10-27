#!/usr/bin/env python3
"""
StateMachine test fixture uretici.

Kotlin port'unu Python state machine ile karsilastirmak icin:
- Birkac realistic transkripsiyon senaryosu
- Her senaryo sira sira chunk olarak isleniyor
- Her chunk icin Python'in dondurdu state, status, verses kaydediliyor
- Kotlin port'u ayni inputlarla ayni outputlari uretmeli

Calistirma:
  python scripts/build_state_machine_fixture.py
"""

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import QuranCorpus, align_transcription, normalize_arabic

# server/app.py'den process_chunk + helpers'i ithal etmek karmasik (Flask ile karisik).
# Bu yuzden state machine mantigini buraya YAPISTIRIYORUM (bagimsiz hale geliyor).

import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

# ============================================================
# Konfigurasyon — app.py ile birebir
# ============================================================
MIN_RMS_ENERGY = 0.005
MIN_WORD_COUNT_COLD = 3
MIN_WORD_COUNT_HOT = 2
# eval: 4 → 3 ile yavas okunan chunk'lar (tertil: 5 sn'de 3 kelime) kilit verir, yanlis kilit yok
MIN_WORD_COUNT_FIRST_LOCK = 3
MIN_CONFIDENCE = 50
MIN_CONFIDENCE_FIRST_LOCK = 90
PREFERRED_AYAH_WINDOW_BASE = 2
PREFERRED_AYAH_WINDOW_MAX = 6
PREFERRED_AYAH_WINDOW_ARA = 3
ABANDON_LOCK_AFTER_LOST = 6
PENDING_VERIFY_AYAH_WINDOW = 4
PREFERRED_BONUS = 30
ARA_AFTER_LOST_CHUNKS = 12
MAX_GAP_FILL = 3
FATIHA_WORD_RANGE = (0, 30)
# Fatiha icinde geri gidilmez: pencere son eslesmenin bu kadar kelime gerisinden baslar. "الرحمن الرحيم" hem
# 1:1'de (besmele) hem 1:3'te — 1:2'den sonra 1:1'e eslesip ekran geri zipliyordu (telefon testi, APK #15)
FATIHA_BACK_WORDS = 3
SURAH_END_THRESHOLD = 2
# Fatiha'nin bu ayetinden sonra (6-7) pencere disi guclu eslesme = zamm suresine gecis (hemen)
FATIHA_END_AYAH = 6
# Kilitliyken pencere skoru bunun altindaysa tum Kuran'da da ara (sure gecisi / pencere cop eslesmesi)
JUMP_SEARCH_BELOW = 80
# Pencere disindaki eslesme pencereden en az bu kadar iyi olmali
JUMP_MARGIN = 15
# Namazda sesli okunan ilk sey Fatiha: BEKLEME'de Fatiha basina (1:1-3) bu kadar guclu eslesme
# (skor ve kelime) dogrulama beklemeden kilit verir (~5 sn erken)
FATIHA_FAST_LOCK_MIN_SCORE = 90
FATIHA_FAST_LOCK_MIN_WORDS = 4
# Kilit kaybolduktan sonra (rukû/secde/sessiz rekat) yeniden kilit ilk kilit gibi dogrulamali; istisnalar:
# rekat basi Fatiha (herhangi bir ayet, skor >= FATIHA_FAST_LOCK_MIN_SCORE, >= MIN_WORD_COUNT_FIRST_LOCK kelime)
# ve kalinan yerden devam (ayni sure, son ayetin -RESUME_BACK..+PREFERRED_AYAH_WINDOW_ARA arasi)
RESUME_BACK = 2
# Dogal gecis noktasinda (Fatiha sonu / sure sonu) yavas okumada parcaya 2 kelime sigiyor ("لإيلاف قريش",
# "أعطيناك الكوثر"); sure atlamasi 3 kelime istedigi icin gecis bir parca gecikiyordu (Kureys 13 sn, hibrit).
# 2 kelimelik parca da atlayabilir: ifade Kuran'da TEK yerde gecmeli (normalize, birebir), skor >=
# JUMP_SHORT_MIN_SCORE ve hedef dogal gecis olmali. Cok yerde gecen ifade ("ولقد ارسلنا", "الرحمن الرحيم") 3 kelimeyi bekler.
JUMP_SHORT_WORDS = 2
JUMP_SHORT_MIN_SCORE = 90
# Dogal gecis (Fatiha sonu → zamm, sure sonu → sure basi) dogrulamasiz gecer, ama skor bunun altindaysa sadece aday.
# Cuma namazi (02.10): Fatiha sonrasi "لا يسمعون عصيس" (21:102, ASR bozuk) → 7:100 (74.5) dogal gecis sayilip
# yanlis kilit + 30 sn yapiskan pencere. Eval'deki 28 dogal gecisin hepsi dogru, en dusugu 79.3 (Kevser sonu →
# "قل أعوذ برب الفحص" 113:1) → esik ikisinin arasinda.
NATURAL_MIN_SCORE = 77
# Sure basi (cuma #2, 09.10): Fatiha sonrasi zamm basi ASR'de bozuk geliyor — "ألهاكم التجاد" (الهاكم التكاثر 102:1),
# "والعص إن الإنسان لعام" (والعصر ان الانسان لفي خسر 103:1-2). Hizalama dogru yere 85 / 92 veriyor ama
# score_transcription Kuran sozlugunde olmayan kelimeler icin ceza kesiyor (60 / 65) → gecis reddedildi, sure 2. / 3.
# ayetinde kilitlendi (7 / 11.5 sn gec, surenin basi ekranda hic gorunmedi). Gecis noktasinda (at_transition_point)
# hizalama bir surenin ACILISINDAN basliyorsa (1. ayetin besmele disi ilk OPENING_START_SLACK+1 kelimesi) ham hizalama
# skoru (fuzzy, sozluk cezasiz) >= OPENING_MIN_FUZZY yeter → dogal gecis. Imam zamm'i cogunlukla sure basindan okur;
# aday kumesi 114 sure acilisi oldugu icin ceza olmadan da secici.
OPENING_MIN_FUZZY = 75
OPENING_START_SLACK = 1
# Iki surenin acilisi ayni ifadeyse ("قل أعوذ برب" 113:1 / 114:1) dogal gecis tahmin etmez: eslesme bir sure acilisi,
# baska suredeki ikinci yer de bir sure acilisi ve ham hizalama farki bundan azsa gecis adayi olur, sonraki parca karar
# verir (cuma #3: 2. rekatta Nas'in ilk parcasi Felak'a dogal gecis sayilip kilitlendi). Her yakin ikinci yere
# genellemek denendi (fark < 2: 97 dogal gecisin 3 yanlisini yakaliyordu) ama ayni metnin iki yerde gectigi dogru
# gecisleri de bekletiyordu (2:255 / 3:2, 14:1 / 38:29); hibritte Ayetel Kursi'nin devami kisa parcalarla dogrulanamadi,
# "لا تدري" 65:1'e kilitlendi.
OPENING_TIE_MARGIN = 2.0
# Fatiha sonundaki dogal geciste en iyi eslesme ayet ortasindan basliyorsa ve ayet basindan baslayan ikinci yer en fazla
# bu kadar geride ise ikincisi alinir: imam zamm'a ayet basindan baslar (yatsi 19.10, sabit parca: "الذين اتخذوا دينهم"
# 6:70 ortasina gecti, okunan 7:51 basi; 2 parca yanlis kilit)
AYAH_START_TIE_MARGIN = 2.0
# Hatimle teravih: Fatiha'dan sonra imam onceki rekatin kaldigi yerden devam eder. Fatiha sonundaki gecis aramasinda
# devam penceresi (son zamm konumu .. +CONTINUE_AHEAD ayet, sure biterse sonraki surenin basina tasar) tum Kuran
# eslesmesinden en fazla CONTINUE_MARGIN kotu ve >= NATURAL_MIN_SCORE ise devam secilir (dogal gecis). Son zamm konumu
# selam / kamette silinmez. Normal namazda da ise yariyor: 2. rekatta cogunlukla mushaf sirasiyla sonraki sure okunur
# (cuma #3: Felak → Nas, "قل أعوذ برب" 113:1 / 114:1 esitligi 114:1 lehine, Nas 12.3 → 3.2 sn).
CONTINUE_AHEAD = 6
CONTINUE_MARGIN = 2.0
# Devam onceligi: devam penceresi >= ilk kilit esigi ve tum Kuran'daki en iyi yerden en fazla CONTINUE_PRIOR_MARGIN kotu ise,
# en iyi yer bir sure acilisi degilse devam secilir. Yatsi 21.10: 1. rekat Enbiya 21:23'te bitti, 2. rekat "أَمِ اتَّخَذُوا مِن
# دُونِهِ" (21:24) ASR'de "أم اتطعتم من دونه" → Yunus 10:38'e ("استطعتم من دون الله") 77.3 dogal gecis, devam penceresi
# 21:24 72.2 (sozluk cezasi) → 2 parca ekranda yanlis sure.
CONTINUE_PRIOR_MARGIN = 6.0
# Fatiha sonunda sure acilisi onceligi: dogal gecis acilis olmayan bir yere oturduysa, ilk kelimesi parcanin ilk 2
# kelimesinden biri olan surelerin acilisi (1-2. ayet) ayrica hizalanir; tum Kuran'daki en iyi yerden en fazla bu kadar
# kotuyse acilis alinir. Aksam 22.10: "قل يا أيها الرحم" 7:158 / 62:6 / 109:1 esit 78.6 → 7:158'e gecti, Kafirun 5 sn gecikti.
OPENING_PREFER_MARGIN = 1.0
# Taze gecisin yeniden kontrolu: Fatiha sonunda acilis / devam olmayan yere dogal gecisten sonraki FRESH_JUMP_CHUNKS
# parcada pencere eslesmesi MIN_CONFIDENCE altindaysa parca (2 kelime de) tum Kuran'da aranir; en iyi yer baska bir
# surenin 1-2. ayetinde, >= FRESH_JUMP_MIN_SCORE, pencereden >= JUMP_MARGIN iyi ve gecis parcasinin metni o surenin
# acilisina >= ilk kilit esigi oturuyorsa (sirali) gecilir. Aksam 22.10: Nasr "إذا جاء نصر الله" ASR'de "فما جاء النصر" →
# 15:61 ("فلما جاء آل لوط") 90.5, 110:1 75.0; sonraki "والله والفتح" (2 kelime, 110:1 86.7) aranmadi, 20 sn Hicr.
FRESH_JUMP_CHUNKS = 2
FRESH_JUMP_MIN_SCORE = 80
# Erken Fatiha: zamm'da kilit dusmeden, son saglam eslesmeden (>= 3 kelime, >= ilk kilit esigi) bu kadar parca gecmeden
# gelen ve Fatiha'nin 1-2. ayetinde biten eslesme ("الحمد لله رب العالمين": dua / tesbihatta da gecen, ASR'nin uydurdugu kalip)
# hemen gecmez, gecis adayi olur; sonraki parca Fatiha'da dogrularsa gecilir. Yeni rekat rukû + iki secdeden sonra gelir
# (>= ~30 sn). Aksam 22.10: Kafirun 109:6'dan 21 sn sonra semiallah kuyrugu + sessizlik + secde tekbiri basi ASR'de
# "الحمد لله رب العالمين" → "yeni rekat" Fatiha'si, 2. rekat 31 sn erken. (Zayif / Fatiha'nin ilerisine oturan eslesme
# denendi: gurultu testinde rukû arasindaki cop eslesmeler gercek 2. Fatiha'yi 5-10 sn geciktirdi.)
FATIHA_MIN_GAP_CHUNKS = 6
FATIHA_EARLY_MAX_AYAH = 2
# Gecis adayi varken (onceki parca) yeni parca adayin +-PENDING_VERIFY_AYAH_WINDOW ayetinde tum Kuran eslesmesinden en
# fazla bu kadar kotu (ve >= ilk kilit esigi) eslesiyorsa aday dogrulanir. Ortak ifade tum Kuran'da baska yere oturuyordu:
# Fatiha → bozuk Asr "الإنسان لفيه السوء" (103:2 adayi) → "الذين آمنوا وعملوا" 2:25'e dogal gecis (103:3 ayni skor).
CANDIDATE_WINDOW_MARGIN = 2.0
# Namaz yapisi sinyalleri (ASR metninden, bkz. namaz_signal):
#   kamet/ezan → yeni namaz basliyor: kilit sifirlanir (BEKLEME), KAMET_HOLD_CHUNKS parca sadece Fatiha kilitlenir.
#     Cuma: kamet "الصلاة حي الصلاة" → 4:103, "بل قام بالصلاة" → 4:101 kilit; Fatiha 4:102'ye eslesti.
#   selam (kilit yokken) → namaz bitti: ayni sifirlama, RUKU_HOLD_CHUNKS parca (dua cumleleri kilitlemesin).
#   semiallah → rukû (zamm bitti): ARA'ya gecilir; RUKU_HOLD_CHUNKS parca boyunca sadece Fatiha (yeni rekat) ya
#     da kalinan yerden devam (pencere skoru >= HOLD_RESUME_MIN_SCORE). Cuma: semiallah sonrasi "لمن عمل" → 21:106.
#   Tek basina tekbir sinyal DEGIL (sadece metinden atilir): zorlama testinde okuma ortasina sahte "الله أكبر"
#     konunca ARA'ya gecmek / beklemek yeni sureyi kilitletmiyordu; gercek kayitlarda semiallah ayni isi guvenilir yapiyor.
# Bekleme her sinyalde yenilenir; Fatiha ya da devam kilitlenince biter.
# Tek parcada ilk kilit ("fark payi", taraweeh-companion-g2'deki high-margin lock fikri): BEKLEME'de eslesme
# skoru >= UNIQUE_LOCK_MIN_SCORE, >= UNIQUE_LOCK_MIN_WORDS kelime ve en iyi eslesmenin DISINDAKI en iyi yer
# (tum Kuran, ayni araliga degmeyen pencereler) en az UNIQUE_LOCK_MARGIN puan geride ise dogrulama beklemeden kilit.
# Kuran'da birden cok yerde gecen ifade ("قل أعوذ برب" 113:1 / 114:1, "يا رب العالمين", 16:4 / 36:77) farki ~0 →
# yine 2 parca dogrulamasi. Olcum (35 kayit, gercek RNNT transkriptleri): yanlis adaylarin farki en fazla 2.4,
# dogrular 9-33; ilk kilit 17/0/2 → 19/0/0, takip 43/46 → 46/46, yanlis kilit 0; zorlama testlerinde de yanlis
# kilit / aday artmadi (kilitlenen bolum 213/230 → 228/230). Ayni kural kilitliyken sure gecisi adayina da: dogal
# gecis noktasi degilse bile fark payi yeterliyse gecis ikinci parcayi beklemez.
UNIQUE_LOCK_MIN_SCORE = 90
UNIQUE_LOCK_MIN_WORDS = 3
UNIQUE_LOCK_MARGIN = 12
# Ayirt edici kelime (taraweeh-companion-g2'nin "prefix-ambiguity guard"inin tersi): harf benzerligi ikinci yeri
# yaklastirabiliyor — "قل أعوذ برب الفلق" 113:1'e 100, 114:1 "...الناس"e 91.4 (fark 8.6). Fark >= EXCLUSIVE_LOCK_MARGIN
# ve parcada en iyi yerin ayetlerinde birebir gecip ikinci yerin ayetlerinde gecmeyen, besmele disi, >=
# EXCLUSIVE_MIN_LETTERS harfli bir kelime varsa da tek parcada kilit. Olcum (35 kayit, BEKLEME adaylari, skor >= 90):
# yanlislarin farki 0-1.6 ve hicbirinde ayirt edici kelime yok ("قل أعوذ برب", ilahi "يا رب العالمين", "والعصر إن شاء
# الله" → 12:99); dogrular 6.7-10.6 ve hepsinde var ("الفلق", "الناس", "اهدنا", "والعصر", "الفيل"). Besmele kelimeleri
# sayilmaz: korpusta her 1. ayet besmeleyle basliyor (Ihlas'ta "بسم الرحمن الرحيم" ayirt edici gorunuyordu).
EXCLUSIVE_LOCK_MARGIN = 5
EXCLUSIVE_MIN_LETTERS = 3
BESMELE_TOKENS = {"بسم", "الله", "الرحمن", "الرحيم"}
# Birikmis metin (taraweeh-companion-g2: arama modunda son parcalarin metni birlestirilip eslestiriliyor): yavas
# okumada 5 sn'lik parcaya 1-2 kelime sigiyor ("خلق الإنسان" | "علمه البيان" tek tek too_short → Rahman ilk kilidi
# 20 sn; "قل أعوذ برب" | "محب الناس ملك الناس" → 113:1 / 114:1 belirsiz). BEKLEME'de (bekleme yokken) kilit vermeyen
# son SEARCH_CONCAT_CHUNKS parcanin temiz metni saklanir; yeni parca da kilit vermezse birlesik metin tum Kuran'da
# hizalanir ve sadece fark payi kuralini (UNIQUE_LOCK_*) gecerse kilit verir — ayni ses iki kez kanit sayilmasin diye
# aday / dogrulama uretmez. Sessizlik, namaz sinyali, bekleme ya da kilit birikimi siler; bos ASR parcasi silmez.
# Sabit 5 sn parcadaki 1 sn bindirme: sinirda tekrar eden kelimeler (en fazla SEARCH_CONCAT_MAX_OVERLAP) bir kez.
SEARCH_CONCAT_CHUNKS = 2
SEARCH_CONCAT_MAX_OVERLAP = 4
# BEKLEME'de aday dogrulamasi: aday penceresindeki eslesme tum Kuran'daki en iyi yerden bu kadar zayifsa dogrulama sayilmaz
VERIFY_GLOBAL_MARGIN = 15
# ARA'da / kilidi kaybolmus zamm'da (yeni rekat beklenir) Fatiha yoklamasi pencere disindaki en iyi yerden bu kadar
# dusuk olsa da kazanir
FATIHA_ARA_MARGIN = 8
# BEKLEME'de (bekleme yokken) en iyi eslesme Fatiha disinda ama belirsizse (ikinci yer AMBIGUOUS_MARGIN icinde) ve parca
# Fatiha'nin 1-3. ayetine >= FATIHA_FAST_LOCK_MIN_SCORE, en iyiden en fazla FATIHA_ARA_MARGIN kotu oturuyorsa Fatiha (namaz
# Fatiha ile baslar). Yatsi 22.10: kamet onceki oturumda kaldi (uygulama yeniden baslatildi), ilk parca "والحمد لله رب العالمين"
# 6:45 / 37:182 esit 100, Fatiha 1:2 92 → belirsiz aday, Fatiha 5 sn gec (1:3'ten). Bekleyen aday varken uygulanmaz: gurultu
# testinde asr'in 37:180'i kilitlenmeyince 37:181 aday oldu, "والحمد لله رب العالمين" (37:182, adayi dogruluyordu) Fatiha sanildi.


def runner_up_match(text, match, corpus):
    """En iyi eslesmenin araligina degmeyen en iyi ikinci yer (tum Kuran) ya da None."""
    return align_transcription(text, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS,
                               exclude_range=(match.start_word_idx, match.end_word_idx))


def match_ayah_words(match, corpus, ayah_to_range):
    """Eslesmenin kapsadigi ayetlerin tum normalize kelimeleri."""
    words = set()
    for s, a in collect_verses(corpus, match.start_word_idx, match.end_word_idx):
        lo, hi = ayah_to_range[(s, a)]
        for i in range(lo, hi + 1):
            words.update(corpus.words[i].normalized.split())
    return words


def is_unique_match(text, match, score, word_count, corpus, vocab, ayah_to_range):
    """Tek parcada kilit: ikinci yerden UNIQUE_LOCK_MARGIN fark ya da EXCLUSIVE_LOCK_MARGIN fark + ayirt edici kelime."""
    if score < UNIQUE_LOCK_MIN_SCORE or word_count < UNIQUE_LOCK_MIN_WORDS:
        return False
    ru = runner_up_match(text, match, corpus)
    margin = score - (score_transcription(text, ru, vocab) if ru else 0.0)
    if margin >= UNIQUE_LOCK_MARGIN:
        return True
    if margin < EXCLUSIVE_LOCK_MARGIN or ru is None:
        return False
    best = match_ayah_words(match, corpus, ayah_to_range)
    other = match_ayah_words(ru, corpus, ayah_to_range)
    return any(len(t) >= EXCLUSIVE_MIN_LETTERS and t not in BESMELE_TOKENS and t in best and t not in other
               for t in (bare_token(w) for w in text.split()))


# Belirsiz aday (UI): BEKLEME / kilit kaybi adayinda ikinci yer bu kadar yakinsa aday ekranda gosterilmez (state machine
# ayni; dogrulaninca kayar). 39 + 44 kayit (gercek, sentetik, dis kaynak) × 2 zincir: ekrandaki 22 yanlis adayin farki 0-2.7
# ("قل أعوذ برب" 113:1 / 114:1, "ألم تر كيف" 105:1 / 89:6 / 14:24, ilahi "يا رب العالمين" 1:2 / 5:28, "والحمد لله رب
# العالمين" 6:45 / 37:182); dogru adaylarin 9'u fark < 3 (Ayetel Kursi 2:255 / 3:2 ayni metin, Felak / Nas), 20'si >= 4.1.
AMBIGUOUS_MARGIN = 3.0

KAMET_HOLD_CHUNKS = 12
RUKU_HOLD_CHUNKS = 24
HOLD_RESUME_MIN_SCORE = 80


class NamazState(str, Enum):
    BEKLEME = "BEKLEME"
    FATIHA = "FATIHA"
    ZAMM = "ZAMM"
    ARA = "ARA"


@dataclass
class PendingMatch:
    surah: int
    ayah: int
    word_index: int
    chunk_index: int
    # Belirsiz aday: ikinci yerin son ayeti — dogrulayan parca aday ile ikinci yeri ayirt etmeli (bkz. AMBIGUOUS_MARGIN)
    alt_surah: Optional[int] = None
    alt_ayah: Optional[int] = None


@dataclass
class SessionState:
    state: NamazState = NamazState.BEKLEME
    last_word_index: Optional[int] = None
    last_surah: Optional[int] = None
    last_ayah: Optional[int] = None
    lost_chunks: int = 0
    total_chunks: int = 0
    matched_chunks: int = 0
    state_transitions: List[str] = field(default_factory=list)
    pending_match: Optional[PendingMatch] = None
    # Kilitliyken pencere disinda bulunan aday konum (sure gecisi) — bir sonraki chunk dogrularsa gecilir
    jump_candidate: Optional[PendingMatch] = None
    # Kilitli suredeki en ileri ayet (geri dogru cop eslesmeler dogal gecis kararini bozmasin)
    max_ayah: Optional[int] = None
    # Namaz sinyali beklemesi (kamet / rukû / selam): bu parca indeksine kadar sadece Fatiha ya da kalinan yerden devam
    hold_until: Optional[int] = None
    # BEKLEME'de kilit vermeyen son parcalarin temiz metni: [(parca indeksi, metin)] — bkz. SEARCH_CONCAT_CHUNKS
    search_texts: List[Tuple[int, str]] = field(default_factory=list)
    # Son zamm konumu (hatimle teravihte sonraki rekat buradan devam eder) — bkz. CONTINUE_AHEAD; selam/kamette silinmez
    zamm_surah: Optional[int] = None
    zamm_ayah: Optional[int] = None
    # Son "sadece tekbir" parcasinin indeksi — bkz. TEKBIR_TEVHID_CHUNKS
    last_tekbir_chunk: Optional[int] = None
    # Fatiha sonundaki taze (acilis / devam olmayan) dogal gecis: (parca indeksi, temiz metin) — bkz. FRESH_JUMP_CHUNKS
    fresh_jump: Optional[Tuple[int, str]] = None
    # Son kabul edilen eslesmenin parca indeksi — bkz. TILAVET_END_NAMAZ_GAP
    last_match_chunk: Optional[int] = None
    # Son saglam (>= MIN_WORD_COUNT_FIRST_LOCK kelime, >= ilk kilit esigi) eslesmenin parca indeksi — bkz. FATIHA_MIN_GAP_CHUNKS
    last_solid_chunk: Optional[int] = None


def build_aux_maps(corpus):
    ayah_to_range = {}
    surah_counts = {}
    for idx, w in enumerate(corpus.words):
        key = (w.surah, w.ayah)
        if key not in ayah_to_range:
            ayah_to_range[key] = [idx, idx]
        else:
            ayah_to_range[key][1] = idx
        prev = surah_counts.get(w.surah, 0)
        if w.ayah > prev:
            surah_counts[w.surah] = w.ayah
    vocab = corpus.vocab  # imla'i parcalar ("يا ايها" → يا, ايها)
    return ayah_to_range, surah_counts, vocab


def score_transcription(text, match, vocab):
    tokens = [normalize_arabic(t) for t in text.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return 0.0
    fuzzy = match.score if match else 0
    in_vocab = sum(1 for t in tokens if t in vocab)
    vocab_coverage = in_vocab / len(tokens)
    unique_ratio = len(set(tokens)) / len(tokens)
    max_consec = 1; c = 1
    for i in range(1, len(tokens)):
        if tokens[i] == tokens[i - 1]:
            c += 1; max_consec = max(max_consec, c)
        else:
            c = 1
    score = fuzzy * (vocab_coverage ** 0.5) * (unique_ratio ** 0.3)
    if max_consec >= 3: score *= 0.3
    if vocab_coverage < 0.3: score *= 0.5
    return round(score, 1)


def is_near_surah_end(surah, ayah, surah_counts):
    if surah not in surah_counts: return False
    return (surah_counts[surah] - ayah) < SURAH_END_THRESHOLD


def ayah_window(surah, ayah, back, forward, ayah_to_range, surah_counts):
    if surah not in surah_counts: return None
    total = surah_counts[surah]
    sa = max(1, ayah - back); ea = min(total, ayah + forward)
    sr = ayah_to_range.get((surah, sa)); er = ayah_to_range.get((surah, ea))
    if sr is None or er is None: return None
    return (sr[0], er[1])


def compute_preferred_range(state, ayah_to_range, surah_counts):
    if state.lost_chunks >= ABANDON_LOCK_AFTER_LOST: return None
    if state.state == NamazState.BEKLEME and state.pending_match:
        pm = state.pending_match
        return ayah_window(pm.surah, pm.ayah, PENDING_VERIFY_AYAH_WINDOW, PENDING_VERIFY_AYAH_WINDOW, ayah_to_range, surah_counts)
    if state.state == NamazState.FATIHA:
        # Pencere Fatiha'nin son kelimesinde biter (FATIHA_WORD_RANGE 30'a kadar Bakara 2:1-2'yi de kapsiyordu;
        # daralan pencerede cop eslesme 2:1'e kilitleniyordu)
        f_end = ayah_to_range[(1, 7)][1] if (1, 7) in ayah_to_range else FATIHA_WORD_RANGE[1]
        start = FATIHA_WORD_RANGE[0]
        lw = state.last_word_index
        if lw is not None and start <= lw <= f_end:
            start = max(start, lw - FATIHA_BACK_WORDS)
        return (start, f_end)
    if state.state == NamazState.ZAMM:
        if state.last_word_index is None: return None
        if state.last_surah and state.last_ayah:
            adaptive = min(PREFERRED_AYAH_WINDOW_BASE + state.lost_chunks, PREFERRED_AYAH_WINDOW_MAX)
            w = ayah_window(state.last_surah, state.last_ayah, 0, adaptive, ayah_to_range, surah_counts)
            if w: return w
        return (state.last_word_index, state.last_word_index + 60)
    if state.state == NamazState.ARA:
        if state.last_surah and state.last_ayah:
            w = ayah_window(state.last_surah, state.last_ayah, 2, PREFERRED_AYAH_WINDOW_ARA, ayah_to_range, surah_counts)
            if w: return w
        if state.last_word_index is not None:
            return (max(0, state.last_word_index - 30), state.last_word_index + 90)
        return None
    return None


def transition_state(state, matched, first_surah, first_ayah):
    current = state.state
    if matched:
        # Fatiha'nin herhangi bir ayeti (2. rekat Fatiha'si ortasindan da yakalanabilir: 1:4) → FATIHA.
        # Eskiden sadece 1:1-3; 1:4'ten yakalaninca ZAMM kaliyor, Fatiha → zamm gecisi aday'a dusuyordu.
        if first_surah == 1:
            return NamazState.FATIHA
        if current == NamazState.FATIHA:
            return NamazState.FATIHA if first_surah == 1 else NamazState.ZAMM
        if current in (NamazState.ZAMM, NamazState.ARA, NamazState.BEKLEME):
            return NamazState.ZAMM
    else:
        if current in (NamazState.FATIHA, NamazState.ZAMM):
            if state.lost_chunks >= ARA_AFTER_LOST_CHUNKS:
                return NamazState.ARA
    return current


def is_natural_transition(state, surah, ayah, surah_counts):
    """Kilitliyken dogal gecis noktasi mi (dogrulama beklemeden gecilir):
    Fatiha sonu → baska herhangi bir yer (zamm suresi), sure sonu → bir surenin 1-2. ayeti."""
    far = state.max_ayah or state.last_ayah or 0
    if state.state == NamazState.FATIHA:
        return surah != 1 and state.last_surah == 1 and far >= FATIHA_END_AYAH
    if state.state in (NamazState.ZAMM, NamazState.ARA) and state.last_surah and far:
        return ayah <= 2 and is_near_surah_end(state.last_surah, far, surah_counts)
    return False


def cleanup_stale_candidates(state, chunk_index):
    # Aday BEKLEME'de ve kilit kaybolduktan sonraki yeniden kilitte olusur; 2 chunk icinde dogrulanmazsa biter
    if state.pending_match:
        if chunk_index - state.pending_match.chunk_index >= 2:
            state.pending_match = None
    if state.jump_candidate and chunk_index - state.jump_candidate.chunk_index >= 2:
        state.jump_candidate = None


# Istiaze ayet degil ama "من الشيطان الرجيم" 16:98'e aday uretiyordu (ekranda kisa "ADAY 16:98").
# Chunk sinirinda bolunebilir: "الشيطان" iceren >=3 kelimelik ardisik parcalari cikar.
ISTIAZE_TOKENS = ["اعوذ", "بالله", "من", "الشيطان", "الرجيم"]
ISTIAZE_KEY = 3  # "الشيطان"

# Namaz zikirleri Kuran degil ama ayete "eslesiyordu" (gercek aksam namazi kaydi, 27.09): selam
# "السلام عليكم ورحمة الله" → 6:54 (84), "سمع الله لمن حمده" → 3:181 (74). Kuran'da "السلام عليكم/عليك" ve
# "ربنا (و)لك الحمد" hic gecmiyor, "سمع الله" hep "قول" ile devam ediyor → bu kaliplar cikarilir.
# "الله اكبر" 3 ayette geciyor (9:72, 29:45, 40:10) → sadece parca tamamen tekbirse atilir.
SELAM_TAIL = {"و", "ورحمه", "رحمه", "الله", "وبركاته", "بركاته"}
SELAM_MAX_WORDS = 5
# ASR (FastConformer) sessizlik/gurultu/tekbirde egitim verisindeki video girislerini uyduruyor:
# "شركة الهدى للخدمات التقنية", "موسوعة النابلسي للإعجاب", "لا تنسوا مشاركة العمل". Bu kelimeler Kuran'da
# yok (korpus vocab ile dogrulandi); iceren parca bos sayilir (okuma yok).
ASR_HALLUCINATION_TOKENS = {"شركه", "للخدمات", "الخدمات", "التقنيه", "موسوعه", "النابلسي", "مشاركه",
                            "لاتنسوا", "للاعجاب"}
# Namaz sonu duasi (imam, selamdan hemen sonra): "اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام".
# Gercek namaz #2 (01.10): "السلام منك السلام" → 59:23 ADAY, "تباركت يا ذا الجلال والاكرام" → 55:27 ADAY.
# Kuran'da "انت السلام", "(و)منك السلام", "تباركت", "ذا الجلال" yok (korpusla dogrulandi; Kuran'da ذو/ذي الجلال)
# → cikarilir. Dua basi parcada kaldiysa ("اللهم انت السلام") geriye dogru da silinir.
DUA_HEAD = {"اللهم", "انت", "السلام"}
DUA_TAIL = {"يا", "ذا", "ذو", "ذي", "الجلال", "والاكرام"}
DUA_HEAD_MAX = 3
# Tek kelimelik ASR uydurmasi: tekbir/gurultu/titresimde "المصدر كتاب", "المصدر صور من" (namaz #2'de 8 kez, ezanda da).
# "المصدر" Kuran'da yok; sadece kelime cikarilir (kalan kisa parca too_short olur, "كتاب" 13:43'e eslesmez).
ASR_NOISE_WORDS = {"المصدر"}
# Ders girisi uydurmasi: ASR sessizlik / yankida Nablusi tefsir dersinin acilisini yaziyor ("تفسير سورة الأعراف الدرس
# الثامن لفضيلة الدكتور محمد راتب النابلسي", "نهاية الدرس") — cogu zaman gercek okumayla ayni parcada: "تفسير سورة
# الأعراف الدرس اهدنا الصراط المستقيم", "نهاية الدرس الحمد لله رب العالمين" (sentetik teravih 78 parca, Collak kayitlari,
# cuma). "تفسير", "الدرس", "نهاية" ve siralama kelimeleri Kuran'da yok (korpus) → sadece giris kelimeleri cikarilir:
# "تفسير" (+ "سورة" + sure adi), "(سورة X) الدرس" (+ siralama kelimesi), "نهاية الدرس". Kalan okuma hizalanir.
LECTURE_ORDINAL_PREFIXES = ("الاول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع",
                            "العاشر", "الثلا", "العشر", "الاربع")
# Tekbir: ASR "الله اغبر" de yaziyor (cuma, 3 kez). "اغبر"/"اكبار" Kuran'da yok.
TEKBIR_WORDS = {"اكبر", "اغبر", "اكبار"}
# Bozuk semiallah (cuma #2): "يدع الله لمن حمده" (260 sn), "سمع القول لمن حمد" (156 sn) — "سمع الله" kalibina uymuyordu
# → rukû sinyali ve bekleme kaciyordu. "لمن حمد…" ve "حمده" Kuran'da yok (korpus); 35 kaydin RNNT + CTC
# transkriptlerinde (2782) sadece semiallahta geciyor. Onundeki en fazla SEMIALLAH_HEAD_MAX kisa kelime
# (<= SEMIALLAH_HEAD_LEN harf: "سمع", "يدع", "الله", "القول") da atilir.
SEMIALLAH_HEAD_MAX = 2
SEMIALLAH_HEAD_LEN = 5
# Tek basina semiallah sonu: "حمده", "حميده" (yatsi 22.10: "لمَن حميده"; Kuran'da "لمن"den sonra "حم" ile baslayan kelime yok —
# sadece "لمن حارب", "لمن حوله" — "لمن حم…" da semiallah)
SEMIALLAH_TAIL = {"حمده", "حميده"}
# Kamet / ezan: Kuran'da HIC gecmeyen kelime ve ikililer (korpusla dogrulandi; eval'deki 33 kaydin RNNT + CTC
# transkriptlerinde hic cikmadi). Cuma kameti: "أشهد ان لا إله", "الله محمد", "أن محمد", "الصلاة حي الصلاة",
# "بل قام بالصلاة". "لا اله الا الله", "محمد رسول الله", "الله اكبر", "حي" (21:30, 8:42) Kuran'da var → isaret degil.
KAMET_WORDS = {"الفلاح", "قامت", "محمدا"}
# Cuma #2 (09.10): kamet "حي على الصلاة" → ASR "خير الصلاة على الصلاة" hicbir kaliba uymadi → 4:142 aday (ekranda
# "Nisa"), kamet ancak 10 sn sonra "قد قام بالصلاة" ile yakalandi; "قد قامت الصلاة" → "مضت الصلاة". "على الصلاة",
# "خير الصلاة", "مضت الصلاة" Kuran'da yok (korpus), 34 kaydin 2405 transkriptinde (RNNT + CTC) hic gecmiyor.
KAMET_PAIRS = {("اشهد", "ان"), ("اشهد", "انه"), ("اشهد", "لا"), ("ان", "محمد"), ("الله", "محمد"), ("قد", "قام"),
               ("قام", "الصلاه"), ("قام", "بالصلاه"), ("حي", "علي"), ("حي", "الصلاه"), ("الصلاه", "حي"),
               ("حي", "الفلاح"), ("الصلاه", "خير"), ("من", "النوم"),
               ("علي", "الصلاه"), ("خير", "الصلاه"), ("مضت", "الصلاه")}
# Yatsi (19.10) vaazinda Felak "قل أعوذ برب الفلق" → ASR "أعوذ برب الفلاح": "الفلاح" kamet sayilip kilit/adaylar silindi,
# 12 parca Fatiha beklemesinde Felak hic kilitlenmedi (sabit parca zinciri). "رب/برب الفلاح" kamette yok (hayya → "حي على
# الفلاح"); tum transkriptlerde "الفلاح" 4 kez: 3 "ايها الفلاح" (hayya), 1 bu Felak.
FALAQ_PREV = {"برب", "رب"}
# Aksam 26.10: rukûdan kalkista (semiallahtan sonraki parca) tek basina "محمدا" ("ربنا لك الحمد حمدا…" ASR'de) kamet sayildi →
# rekat sayaci "kamet: yeni namaz", 2. rekat "1. rekat" goruldu. Kamet / ezanda "محمدا" hep "ان" ile (أشهد أن محمدا رسول
# الله; tum transkriptlerde 38 kez, hepsinde onunde "ان"): kamet kelimesi sadece onunde "ان / انه / اشهد" ya da arkasinda
# "رسول… / عبد…" varsa.
MUHAMMAD_PREV = {"ان", "وان", "انه", "اشهد", "واشهد"}
MUHAMMAD_NEXT_PREFIXES = ("رسول", "ورسول", "عبد", "وعبد")
# Ayar denemesi (tests/tune.py "eski kural" senaryolari) icin anahtarlar — uygulamada hep acik
MUHAMMAD_CONTEXT = True        # "محمدا" sadece sehadet baglaminda kamet
SELAM_SPLIT_SIGNAL = True      # "عليكم/عليك + (و)رحمه" de selam (yatsi 27.10)
_NON_LETTER = re.compile(r"[^\u0621-\u064A]")


def bare_token(word):
    """normalize_arabic + harf olmayan karakterleri (nokta vb.) at."""
    return _NON_LETTER.sub("", normalize_arabic(word))


def is_asr_hallucination(text):
    return any(bare_token(w) in ASR_HALLUCINATION_TOKENS for w in text.split())


# Uydurma ifade gercek okumayla ayni parcada (sabah namazi 21.10, 2. rekat Fatiha'si: "والحمد لله رب العالمين شركة
# الهدى للخدمات التقنية" — parcanin tamami bos sayildi, Fatiha kilidi 10 sn gecikti). "شركة" / "موسوعة" ile baslayan
# ifade (bas + marka kelimesi: الهدى / النابلسي / النحل ... + devam kelimeleri) cikarilir; kalan (istiaze / namaz
# zikirleri haric) en az MIN_WORD_COUNT_FIRST_LOCK kelimeyse parca o metinle islenir, degilse eskisi gibi bos. Baska
# uydurma kelimesi kalirsa ("لفضيلة الدكتور محمد راتب النابلسي", "لا تنسوا مشاركة العمل") yine bos. Tum transkriptlerde
# (gercek + dis + sentetik) bu kaliplar: "شركة الهدى للخدمات التقنية/التاريخية/للإنسان/للبناء/للنوم", "شركة اليابان",
# "شركة التابعين", "موسوعة النابلسي للعلوم الإسلامية", "موسوعة النحل/النعم مالك يوم الدين".
HALLUCINATION_HEADS = {"شركه", "موسوعه"}
HALLUCINATION_CONT = {"للخدمات", "الخدمات", "التقنيه", "التاريخ", "التاريخيه", "للعلوم", "الاسلاميه", "للبناء",
                      "للنوم", "للاعجاب", "شريك"}


# Tilavet sonu: asr / mukabele bitince okunan "صدق الله العظيم" (Kuran'da yok; "صدق الله" 3:95 / 33:22'de baska kelimeyle).
# Asr 21.10: Hasr 59:24'ten sonra bu ifade + Saffat 37:180-182 — kilit 59:24'te kaldi, 37:180 okunurken ekranda 59:24.
# Ifade cikarilir, kilit ve adaylar biter (BEKLEME, beklemesiz). Dis kaynak kayitlarinda (Collak, Harem) da kayit sonunda.
TILAVET_END = ("صدق", "الله", "العظيم")
# Namazda tilavet sonu yok: son eslesmeden sonra tekbir duyulduysa (rukû / secde) ve son eslesmeden en az TILAVET_END_NAMAZ_GAP
# parca gectiyse ifade sadece cikarilir, kilit bitmez. Yatsi 22.10: secdede (son eslesmeden 8 parca sonra) ASR "صدق الله العظيم"
# uydurdu → 1. rekat ortasinda kilit sifirlandi. Gercek tilavet sonu okumanin hemen ardindan (asr 21.10: 2 parca; sahte tekbir
# testinde 3); sadece tekbir sarti gurultu / sahte tekbir testinde asr'in tilavet sonunu kaciriyordu (37:180 kilitlenmedi).
TILAVET_END_NAMAZ_GAP = 5


def tekbir_after_reading(state):
    """Son saglam eslesmeden sonra tekbir duyuldu mu (namazda rukû / secde) — bkz. TILAVET_END."""
    return (state.last_tekbir_chunk is not None and state.last_solid_chunk is not None
            and state.last_tekbir_chunk > state.last_solid_chunk)


def strip_tilavet_end(text):
    """→ (ifade cikarilmis metin, bulundu mu)."""
    words = text.split()
    toks = [bare_token(w) for w in words]
    n = len(TILAVET_END)
    for i in range(len(toks) - n + 1):
        if tuple(toks[i:i + n]) == TILAVET_END:
            return " ".join(words[:i] + words[i + n:]), True
    return text, False


def strip_asr_hallucination(text):
    """ASR uydurmasi iceren parca → uydurma ifadesi cikarilmis metin ya da "" (bos sayilir; bkz. HALLUCINATION_HEADS)."""
    if not text or not is_asr_hallucination(text):
        return text
    words = text.split()
    out = []
    i = 0
    while i < len(words):
        if bare_token(words[i]) in HALLUCINATION_HEADS:
            i += 2                                  # bas + marka kelimesi
            while i < len(words) and bare_token(words[i]) in HALLUCINATION_CONT:
                i += 1
            continue
        out.append(words[i])
        i += 1
    rest = " ".join(out)
    if not rest or is_asr_hallucination(rest):
        return ""
    t, _ = strip_istiaze(rest)
    t, _ = strip_namaz_phrases(t)
    if len([w for w in (normalize_arabic(x) for x in t.split()) if w]) < MIN_WORD_COUNT_FIRST_LOCK:
        return ""
    return rest


# Kuran'da gecen ama namazda / ezan-kamette / sohbette tek basina soylenen ifadeler. Zamm suresi kilitli degilken
# (BEKLEME / ARA / FATIHA) parca sadece bunlardan biriyse (+ en fazla DHIKR_EXTRA_MAX kelime) bos sayilir: cuma #3'te
# kametteki "محمد رسول الله" 48:29'a tek parcada kilitlendi (fark payi), "لا اله الا الله" 37:35, "ان شاء الله" 12:99 /
# 28:27 adayi oluyordu. Tum transkriptlerde (35 kayit, RNNT + CTC) Kuran okunan anda tek ornek asr.wav "والعصر إن شاء
# الله" (ASR hatasi; teravih bilesiminde Fatiha sonunda 12:99'a dogal gecis olup 6 parca yanlis kilitti).
# Kelime-i sehadet ("محمد(ا) رسول الله") BEKLEME'de kamet sayilir (ezan/kamet; Fatiha beklemesi + ezan penceresi);
# bekleme surerken gelen zikir beklemeyi uzatir.
# Ezan koleksiyonu (dis kaynak): ezan sonu "الله أكبر الناس" / "الله أكبر لا" → 9:72'ye kilit (2 parca), kesik tevhid
# "إله إلا الله" → Fatiha beklemesinde 1:1 ADAY. "الله اكبر" 3 ayette (9:72, 29:45, 40:10), "اله الا الله" 4 ayette
# (3:62, 37:35, 38:65, 47:19) — hepsi ayet ortasinda; zamm kilitli degilken tek basina (+1 kelime) okuma degil.
# Tamamen tekbir olan parca eskisi gibi strip_namaz_phrases'ta atilir (too_short), zikir sayilmaz.
# Namaz sonu tesbihati "(لا حول) ولا قوة إلا بالله": Kuran'da sadece 18:39 ("ما شاء الله لا قوة إلا بالله"); aksam 22.10'da
# selamdan sonra "ولا قوة إلا بالله" 18:39'a tek parcada kilit (fark payi).
# Tesbihat "(الحمد) لله ولا إله إلا الله": "ولا اله الا الله" Kuran'da hic yok (aksam 22.10: Kotlin 2:255 / Python 37:35 belirsiz
# aday — aligner aday budamasi farki, Kotlin = Python izi bozuldu).
DHIKR_PHRASES = (("محمد", "رسول", "الله"), ("محمدا", "رسول", "الله"), ("لا", "اله", "الا", "الله"), ("ان", "شاء", "الله"),
                 ("اله", "الا", "الله"), ("الله", "اكبر"), ("قوه", "الا", "بالله"),
                 ("حول", "ولا", "قوه", "الا", "بالله"), ("ولا", "اله", "الا", "الله"), ("لله", "ولا", "اله", "الا", "الله"))
DHIKR_EXTRA_MAX = 1

# Kamet / ezan basi: tekbir + tevhid ("الله أكبر الله أكبر" | "أشهد أن لا إله إلا الله"). Yatsi (19.10): kamet 685'te
# basladi, ASR "الله اغبر" ×2 → "لا اله الا الله" (698.8) → ancak 708.8'de "أشهد أن سيدنا محمد" ile tanindi (24 sn geç;
# aradaki tekbirler TEKBIR karti acti). Zamm kilitli degilken (BEKLEME / ARA) ve bekleme yokken son TEKBIR_TEVHID_CHUNKS
# parca icinde sadece tekbir duyulduysa tek basina tevhid kamet/ezan sayilir. Ezan / kamet sonundaki tekbir + tevhid
# bekleme surerken geldigi icin tetiklemez (zikir olarak beklemeyi uzatir); namazda tevhid sesli soylenmez.
TEKBIR_TEVHID_CHUNKS = 2
# Kilit kaybolmussa (ABANDON_LOCK_AFTER_LOST+ kayip parca) zamm kilidi yok sayilir: zikir ifadesi ve tekbir + tevhid kurali
# orada da gecer. Yatsi #2 (20.10): namazdan once biri Saffat 37:180-182 okudu → ZAMM kilidi, 50 sn sessizlik, kamet
# "الله اغبر" ×2 → "شهود لا اله الا الله" (189 sn) ZAMM'da zikir sayilmadi, 37:35 belirsiz adayi oldu; kamet ancak 194'te.

# Zamm okunurken ara verildiyse (ZAMM'da PAUSE_LOST_CHUNKS+ ardisik kayip parca: rukû / secde, sessiz kisim) kisa (< ilk
# kilit kelime sayisi) ve zayif (< ilk kilit esigi) eslesme okumanin devami sayilmaz. Yatsi #2: Taha 20:111 bitti (436 sn),
# rukûdan kalkarken "سمع الله لمن حمده" → ASR "لم يعد" 20:112'ye 62.9 → rukûda ekranda henuz okunmamis ayet (20:112 2.
# rekatta okundu). FATIHA'da uygulanmaz: Fatiha → zamm arasindaki aminden sonra zammin kisa ilk parcasi ("إن الإنسان")
# Fatiha'ya zayif eslesip kayip sayacini sifirliyor; reddedilince bilesik teravihte Asr bolumu hic kilitlenmedi.
PAUSE_LOST_CHUNKS = 2
# Kilitliyken (FATIHA / ZAMM) parca sadece "(و)الحمد لله" ve pencere eslesmesi < ilk kilit esigi → okuma degil (kayip parca).
# Kuran'da 20+ yerde gecen kalip; ASR nefes / kuyruktan uyduruyor. Yatsi 22.10: Enbiya 21:79 bitti, 2.6 sn'lik kuyruk parcasi
# "الحمد لله" → 21:80-81'e 62.1 → rukûda ekranda henuz okunmamis 21:80 / 21:81 (2. rekatta okundu).
STOCK_PHRASES = {("الحمد", "لله"), ("والحمد", "لله")}
# Okumadan sonra tekbir duyulduysa (rukû; bkz. tekbir_after_reading) ZAMM'da kisa (< ilk kilit kelime sayisi) eslesme ancak
# >= TEKBIR_SHORT_MIN_SCORE ise okumanin devami. Yatsi 22.10 sabit parca: 21:79 bitti, rukû tekbiri, semiallah ASR'de
# "لمن قبله" → 21:82'ye 76 → son zamm konumu 21:82 oldu, 2. rekatin devam penceresi (21:82..) 21:80'i kacirdi, "فهل أنتم يا
# رب العالمين" 26:109'a dogal gecis (2 parca yanlis sure).
TEKBIR_SHORT_MIN_SCORE = 90


def is_tevhid(text):
    """Metinde "اله الا الله" (kelime-i tevhid) gecer mi."""
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    return any(tuple(toks[i:i + 3]) == ("اله", "الا", "الله") for i in range(len(toks) - 2))


def _drop_leading_tekbir(toks):
    """Bastaki tekbir (kamet / ezan kapanisi "الله أكبر الله أكبر لا إله إلا الله" — Kuran'da tekbirden hemen sonra tevhid yok):
    yatsi 21.10'da kayit kamet sonunda basladi, "الله اغبر لا اله الا الله" zikir sayilmadi → 37:35 / 28:88 belirsiz aday (Kotlin
    aligner'inin aday budamasi farkli yer buluyordu). Kalan kelimeler zikir ifadesiyse zikir (dhikr_only)."""
    while len(toks) > 1 and (toks[0] in TEKBIR_WORDS or (toks[0] == "الله" and toks[1] in TEKBIR_WORDS)):
        toks = toks[1:] if toks[0] in TEKBIR_WORDS else toks[2:]
    return toks


def dhikr_only(text):
    """→ (sadece zikir ifadesi mi, kelime-i sehadet mi)"""
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    if is_tekbir_only(toks):
        return False, False
    for cand in (toks, _drop_leading_tekbir(toks)):
        for ph in DHIKR_PHRASES:
            n = len(ph)
            if len(cand) - n <= DHIKR_EXTRA_MAX and any(tuple(cand[i:i + n]) == ph for i in range(len(cand) - n + 1)):
                return True, ph[1] == "رسول"
    return False, False


def strip_namaz_phrases(text):
    """Namaz zikirlerini (selam, semiallah, rabbena lekel hamd, tek basina tekbir), namaz sonu duasini
    ("اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام"), tek kelimelik ASR uydurmasini ("المصدر") ve ders
    girisi uydurmasini ("تفسير سورة الأعراف الدرس") cikar → (temiz metin, cikarilan kelime sayisi)."""
    words = text.split()
    norms = [bare_token(w) for w in words]
    n = len(words)
    keep, removed, i = [], 0, 0
    while i < n:
        k = 0
        if norms[i] == "السلام" and i + 1 < n and norms[i + 1] in ("عليكم", "عليك"):
            k = 2
            while i + k < n and k < SELAM_MAX_WORDS and norms[i + k] in SELAM_TAIL:
                k += 1
        elif norms[i] in ("عليكم", "عليك") and i + 1 < n and norms[i + 1] in ("ورحمه", "رحمه"):
            # Parca sinirinda bolunen selam ("السلام" onceki parcada): "عليكم ورحمة الله" (cuma #2, sabit parca → 1:1
            # ADAY). "عليكم/عليك + (و)رحمه" Kuran'da yok.
            k = 2
            while i + k < n and k < SELAM_MAX_WORDS and norms[i + k] in SELAM_TAIL:
                k += 1
        elif norms[i] == "سمع" and i + 2 < n and norms[i + 1] == "الله":
            if norms[i + 2].startswith("حمد"):
                k = 3
            elif norms[i + 2] == "لمن":
                k = 4 if i + 3 < n and norms[i + 3].startswith("حمد") else 3
        elif norms[i] == "ربنا" and i + 2 < n and norms[i + 1] in ("لك", "ولك") and norms[i + 2] == "الحمد":
            k = 3
        elif norms[i] == "لمن" and i + 1 < n and norms[i + 1].startswith("حم"):
            k = 2
            back = 0
            while keep and back < SEMIALLAH_HEAD_MAX and len(bare_token(keep[-1])) <= SEMIALLAH_HEAD_LEN:
                keep.pop()
                back += 1
            removed += back
        elif norms[i] in SEMIALLAH_TAIL:
            k = 1
        elif norms[i] in ASR_NOISE_WORDS:
            k = 1
        elif norms[i] == "تفسير":
            k = 1
            if i + 1 < n and norms[i + 1] == "سوره":
                k = 3 if i + 2 < n and norms[i + 2] != "الدرس" else 2
        elif norms[i] == "نهايه" and i + 1 < n and norms[i + 1] == "الدرس":
            k = 2
        elif norms[i] == "الدرس":
            k = 1
            if len(keep) >= 2 and bare_token(keep[-2]) == "سوره":
                keep.pop()
                keep.pop()
                removed += 2
        elif norms[i] in ("انت", "منك", "ومنك") and i + 1 < n and norms[i + 1] == "السلام":
            k = 2
            back = 0
            while keep and back < DUA_HEAD_MAX and bare_token(keep[-1]) in DUA_HEAD:
                keep.pop()
                back += 1
            removed += back
        elif norms[i] == "تباركت":
            k = 1
            while i + k < n and norms[i + k] in DUA_TAIL:
                k += 1
        elif norms[i] == "ذا" and i + 1 < n and norms[i + 1] == "الجلال":
            k = 3 if i + 2 < n and norms[i + 2] == "والاكرام" else 2
            if keep and bare_token(keep[-1]) == "يا":
                keep.pop()
                removed += 1
        if k and norms[i + k - 1] == "الدرس" and i + k < n and norms[i + k].startswith(LECTURE_ORDINAL_PREFIXES):
            k += 1      # "الدرس الثامن"
        if k:
            i += k
            removed += k
        else:
            keep.append(words[i])
            i += 1
    if is_tekbir_only(keep):
        removed += len(keep)
        keep = []
    return " ".join(keep), removed


def is_tekbir_only(words):
    """Parca sadece tekbirden mi ibaret ("الله اكبر", "الله اغبر الله أكبر", "أكبر")."""
    kept = [t for t in (bare_token(w) for w in words) if t]
    return bool(kept) and any(t in TEKBIR_WORDS for t in kept) and all(t == "الله" or t in TEKBIR_WORDS for t in kept)


def is_kamet_word(toks, i):
    """toks[i] kamet kelimesi mi ("الفلاح" Felak'ta degil, "محمدا" sadece sehadet baglaminda)."""
    t = toks[i]
    if t not in KAMET_WORDS:
        return False
    if t == "الفلاح":
        return not (i > 0 and toks[i - 1] in FALAQ_PREV)
    if t == "محمدا" and MUHAMMAD_CONTEXT:
        return (i > 0 and toks[i - 1] in MUHAMMAD_PREV) or \
            (i + 1 < len(toks) and toks[i + 1].startswith(MUHAMMAD_NEXT_PREFIXES))
    return True


def namaz_signal(text):
    """Namaz yapisi sinyali: "kamet" (kamet/ezan cumlesi), "selam", "ruku" (semiallah) ya da None. Semiallah, sonra kamet."""
    toks = [t for t in (bare_token(w) for w in text.split()) if t]
    # Semiallah kametten once: Kuran'da "سمع الله" hep "قول" ile devam ediyor (3:181, 58:1) → arkasindan baska kelime
    # gelirse semiallah. Sentetik teravihte "سمع الله لنا محمدا" ("محمدا" kamet kelimesi) kamet sayilip namaz sifirlaniyordu;
    # aksam kaydinda "سمع الله من حمداً" hicbir kaliba uymuyordu. Parca sonundaki "سمع الله" sinyal degil ("قول" sonraki parcada).
    if any(toks[i] == "سمع" and toks[i + 1] == "الله" and toks[i + 2] != "قول" for i in range(len(toks) - 2)):
        return "ruku"
    # "استمع الله" (ASR: semiallah, aksam 22.10): Kuran'da "استمع" sadece 72:1'de ("استمع نفر")
    if any(a == "استمع" and b == "الله" for a, b in zip(toks, toks[1:])):
        return "ruku"
    if any(is_kamet_word(toks, i) for i in range(len(toks))) or any(p in KAMET_PAIRS for p in zip(toks, toks[1:])):
        return "kamet"
    # Bolunmus / bozuk selam: "عليكم ورحمة الله" ("السلام" onceki parcada; yatsi 27.10, cuma #2), "ساء عليكم ورحمة",
    # "سلام عليكم ورحمة" — "عليكم/عليك + (و)رحمه" Kuran'da yok (strip_namaz_phrases ile ayni kural)
    if any((a == "السلام" and b in ("عليكم", "عليك"))
           or (SELAM_SPLIT_SIGNAL and a in ("عليكم", "عليك") and b in ("ورحمه", "رحمه"))
           for a, b in zip(toks, toks[1:])):
        return "selam"
    if any(t in SEMIALLAH_TAIL for t in toks) or any(a == "لمن" and b.startswith("حم") for a, b in zip(toks, toks[1:])):
        return "ruku"
    return None


def reset_for_new_namaz(state, chunk_index, hold_chunks):
    """Kamet / namaz sonu: onceki kilit ve adaylar silinir, BEKLEME + Fatiha beklemesi."""
    if state.state != NamazState.BEKLEME:
        state.state_transitions.append(f"{state.state.value} → {NamazState.BEKLEME.value}")
    state.state = NamazState.BEKLEME
    state.last_word_index = None
    state.last_surah = None
    state.last_ayah = None
    state.max_ayah = None
    state.lost_chunks = 0
    state.pending_match = None
    state.jump_candidate = None
    state.hold_until = chunk_index + hold_chunks


def fatiha_range(ayah_to_range):
    """Fatiha'nin tum kelimeleri (1:1-1:7)."""
    return (ayah_to_range[(1, 1)][0], ayah_to_range[(1, 7)][1])


def strip_istiaze(text):
    """Metinden istiaze parcalarini cikar → (temiz metin, cikarilan kelime sayisi)."""
    words = text.split()
    norms = [normalize_arabic(w) for w in words]
    keep, removed, i = [], 0, 0
    while i < len(words):
        best = 0
        for a in range(len(ISTIAZE_TOKENS)):
            n = 0
            while a + n < len(ISTIAZE_TOKENS) and i + n < len(norms) and norms[i + n] == ISTIAZE_TOKENS[a + n]:
                n += 1
            if n >= 3 and a <= ISTIAZE_KEY < a + n and n > best:
                best = n
        if best:
            i += best
            removed += best
        else:
            keep.append(words[i])
            i += 1
    return " ".join(keep), removed


BESMELE_NORMALIZED = ["بسم", "الله", "الرحمن", "الرحيم"]
_besmele_cache = {}


def besmele_positions(corpus, ayah_to_range):
    """Korpusta 1. ayetlerin basindaki besmele kelimelerinin pozisyonlari (Fatiha, Tevbe haric)."""
    key = id(corpus)
    if key not in _besmele_cache:
        pos = set()
        for (su, ay), (st, en) in ayah_to_range.items():
            if ay == 1 and su not in (1, 9) and en - st + 1 > 4 and \
                    [corpus.words[st + k].normalized for k in range(4)] == BESMELE_NORMALIZED:
                pos.update(range(st, st + 4))
        _besmele_cache[key] = pos
    return _besmele_cache[key]


_token_cache = {}


def corpus_tokens(corpus):
    """Korpusun normalize kelime dizisi (imla'i iki kelimelik kayitlar bolunmus)."""
    key = id(corpus)
    if key not in _token_cache:
        _token_cache[key] = [t for w in corpus.words for t in w.normalized.split()]
    return _token_cache[key]


def phrase_count(corpus, tokens, limit=2):
    """Normalize kelime dizisi korpusta birebir kac kez geciyor (limit'te durur)."""
    toks = corpus_tokens(corpus)
    n = len(tokens)
    if n == 0:
        return 0
    c = 0
    for i in range(len(toks) - n + 1):
        if toks[i] == tokens[0] and toks[i:i + n] == tokens:
            c += 1
            if c >= limit:
                break
    return c


def at_transition_point(state, surah_counts):
    """Kilitli surede dogal gecis noktasinda miyiz: Fatiha sonu ya da zamm suresinin son ayetleri."""
    far = state.max_ayah or state.last_ayah or 0
    if state.state == NamazState.FATIHA:
        return state.last_surah == 1 and far >= FATIHA_END_AYAH
    if state.state == NamazState.ZAMM and state.last_surah and far:
        return is_near_surah_end(state.last_surah, far, surah_counts)
    return False


def opening_first_word(surah, corpus, ayah_to_range):
    """Surenin 1. ayetinin besmele disi ilk kelimesinin pozisyonu."""
    st, en = ayah_to_range[(surah, 1)]
    bp = besmele_positions(corpus, ayah_to_range)
    p = st
    while p < en and p in bp:
        p += 1
    return p


def is_opening_match(match, corpus, ayah_to_range):
    """Eslesme bir surenin acilisindan mi basliyor (besmele ya da 1. ayetin ilk OPENING_START_SLACK+1 kelimesi)."""
    w = corpus.words[match.start_word_idx]
    if w.ayah != 1:
        return False
    return ayah_to_range[(w.surah, 1)][0] <= match.start_word_idx <= \
        opening_first_word(w.surah, corpus, ayah_to_range) + OPENING_START_SLACK


def continue_window(surah, ayah, ayah_to_range, surah_counts):
    """Hatim devam penceresi: son zamm ayeti .. +CONTINUE_AHEAD ayet; sure biterse sonraki surenin basina tasar
    (sentetik hatim: Ahkaf sonundan Muhammed 47:1'e gecis 4:167'ye kilitlendi — ayni metin)."""
    total = surah_counts.get(surah)
    if not total or (surah, ayah) not in ayah_to_range:
        return None
    start = ayah_to_range[(surah, ayah)][0]
    end_ayah = ayah + CONTINUE_AHEAD
    if end_ayah <= total:
        return (start, ayah_to_range[(surah, end_ayah)][1])
    if surah + 1 in surah_counts:
        return (start, ayah_to_range[(surah + 1, min(surah_counts[surah + 1], end_ayah - total))][1])
    return (start, ayah_to_range[(surah, total)][1])


# Huruf-u mukattaa (1. ayetin ilk kelimesi, normalize): ASR cogu zaman yazmiyor ("الر تلك آيات الكتاب المبين" → "تلك آيات
# الكتاب المبين") — ayet basi sayilirken atlanabilir (Rifai Yusuf 12:1 26:2'ye gecmesin)
MUQATTAAT = {"الم", "المص", "الر", "المر", "كهيعص", "طه", "طسم", "طس", "يس", "ص", "حم", "ق", "ن"}


def starts_ayah(match, corpus, ayah_to_range):
    """Eslesme bir ayetin ilk kelimesinden mi basliyor (1. ayetlerde besmele ve huruf-u mukattaa disi ilk kelime)."""
    w = corpus.words[match.start_word_idx]
    first = opening_first_word(w.surah, corpus, ayah_to_range) if w.ayah == 1 else ayah_to_range[(w.surah, w.ayah)][0]
    if match.start_word_idx == first:
        return True
    return w.ayah == 1 and match.start_word_idx == first + 1 and corpus.words[first].normalized in MUQATTAAT


def opening_tie(text, match, corpus, ayah_to_range):
    """Gecis eslesmesi baska bir surenin acilisina da ayni ham skorla oturuyor mu (bkz. OPENING_TIE_MARGIN)."""
    ru = runner_up_match(text, match, corpus)
    return (ru is not None and corpus.words[ru.start_word_idx].surah != corpus.words[match.start_word_idx].surah
            and is_opening_match(ru, corpus, ayah_to_range) and ru.score >= match.score - OPENING_TIE_MARGIN)


_opening_word_cache = {}


def opening_first_tokens(corpus, ayah_to_range):
    """Sure no → acilisin (1. ayet, besmele disi) ilk kelimesinin ilk parcasi (bare)."""
    key = id(corpus)
    if key not in _opening_word_cache:
        out = {}
        for s in range(1, 115):
            if (s, 1) in ayah_to_range:
                p = opening_first_word(s, corpus, ayah_to_range)
                out[s] = bare_token(corpus.words[p].normalized.split()[0])
        _opening_word_cache[key] = out
    return _opening_word_cache[key]


def opening_preference(text, corpus, ayah_to_range, surah_counts, vocab):
    """Fatiha sonu: ilk kelimesi parcanin ilk 2 kelimesinden biri olan surelerin acilisinda (1-2. ayet) en iyi
    eslesme → (eslesme, skor) ya da (None, -1) — bkz. OPENING_PREFER_MARGIN."""
    toks = [t for t in (bare_token(w) for w in text.split()) if t][:2]
    best, best_s = None, -1.0
    for s, fw in opening_first_tokens(corpus, ayah_to_range).items():
        if s == 1 or fw not in toks:
            continue
        ow = (ayah_to_range[(s, 1)][0], ayah_to_range[(s, min(2, surah_counts[s]))][1])
        m = align_transcription(text, corpus, preferred_range=ow, preferred_bonus=PREFERRED_BONUS)
        if m is None or m.score < OPENING_MIN_FUZZY or not is_opening_match(m, corpus, ayah_to_range):
            continue
        sc = score_transcription(text, m, vocab)
        if sc > best_s:
            best, best_s = m, sc
    return best, best_s


def early_fatiha(state, chunk_index, fatiha_ayah):
    """Zamm'da son saglam eslesmeden FATIHA_MIN_GAP_CHUNKS parca gecmeden Fatiha'nin 1-2. ayetinde biten eslesme ve onceki
    parcalarda Fatiha gecis adayi yok → erken (gecis adayi olur)."""
    if state.state != NamazState.ZAMM or state.last_solid_chunk is None or fatiha_ayah > FATIHA_EARLY_MAX_AYAH:
        return False
    if chunk_index - state.last_solid_chunk >= FATIHA_MIN_GAP_CHUNKS:
        return False
    jc = state.jump_candidate
    return not (jc is not None and jc.surah == 1 and chunk_index - jc.chunk_index <= 2)


def content_word_count(match, besmele_pos):
    """Eslesmedeki besmele-disi kelime sayisi (sadece besmeleye oturan eslesme sure gecisi sayilmaz)."""
    return sum(1 for p in range(match.start_word_idx, match.end_word_idx + 1) if p not in besmele_pos)


def verify_pending(pending, new_surah, new_ayah):
    if new_surah != pending.surah: return False
    return abs(new_ayah - pending.ayah) <= PENDING_VERIFY_AYAH_WINDOW


def collect_verses(corpus, start_idx, end_idx):
    seen = set(); verses = []
    for i in range(start_idx, end_idx + 1):
        w = corpus.words[i]
        key = (w.surah, w.ayah)
        if key not in seen:
            seen.add(key); verses.append(key)
    return verses


def clean_chunk_text(text):
    """Hizalanacak temiz metin: ASR uydurmasi bos, istiaze ve namaz zikirleri cikarilmis."""
    text = strip_asr_hallucination(text)
    if not text:
        return ""
    t, _ = strip_tilavet_end(text)
    t, _ = strip_istiaze(t)
    t, _ = strip_namaz_phrases(t)
    return t.strip()


def join_search_texts(texts):
    """Ardisik parca metinlerini birlestir; sinirda tekrar eden (bindirme) kelimeler bir kez sayilir."""
    out = []
    for t in texts:
        w = t.split()
        if out:
            a = [bare_token(x) for x in out]
            b = [bare_token(x) for x in w]
            for k in range(min(SEARCH_CONCAT_MAX_OVERLAP, len(a), len(b)), 0, -1):
                if a[-k:] == b[:k]:
                    w = w[k:]
                    break
        out.extend(w)
    return " ".join(out)


def process_chunk_simulated(rms, transcribed_text, chunk_index, state,
                            corpus, ayah_to_range, surah_counts, vocab):
    """app.py'deki process_chunk'in offline test versiyonu — audio yok, transkripsiyon hazir.
    Parca kilit vermezse BEKLEME'de birikmis metinle (onceki parcalar + bu parca) fark payi kilidi denenir."""
    was_search = state.state == NamazState.BEKLEME
    r = _process_chunk_core(rms, transcribed_text, chunk_index, state, corpus, ayah_to_range, surah_counts, vocab)
    hold = state.hold_until is not None and chunk_index <= state.hold_until
    if not (was_search and state.state == NamazState.BEKLEME and not hold and not r.get("signal")
            and r["status"] in ("too_short", "low_confidence", "pending", "empty")):
        state.search_texts = []
        return r
    if r["status"] == "empty":
        return r
    clean = clean_chunk_text(transcribed_text)
    prev = [t for k, t in state.search_texts if chunk_index - k <= SEARCH_CONCAT_CHUNKS]
    state.search_texts = [(k, t) for k, t in state.search_texts if chunk_index - k < SEARCH_CONCAT_CHUNKS]
    if clean:
        state.search_texts.append((chunk_index, clean))
    if not prev or not clean:
        return r
    comb = join_search_texts(prev + [clean])
    comb_words = len([t for t in (normalize_arabic(x) for x in comb.split()) if t])
    if comb == clean or comb_words < UNIQUE_LOCK_MIN_WORDS:
        return r
    g = align_transcription(comb, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
    gs = score_transcription(comb, g, vocab)
    if not g or not is_unique_match(comb, g, gs, comb_words, corpus, vocab, ayah_to_range):
        return r
    state.search_texts = []
    res = commit_match(state, g, gs, comb_words, chunk_index, r["state_before"], None, corpus)
    res["combined"] = True
    return res


def commit_match(state, match, score, word_count, chunk_index, state_before, jump, corpus):
    """Eslesmeyi kabul et: durum gecisi, en ileri ayet, bosluk doldurma, son konum."""
    verses = collect_verses(corpus, match.start_word_idx, match.end_word_idx)
    first_surah, first_ayah = verses[0]
    last_surah, last_ayah = verses[-1]
    new_state = transition_state(state, True, first_surah, first_ayah)
    if new_state != state.state:
        state.state_transitions.append(f"{state.state.value} → {new_state.value}")
        state.state = new_state
    state.pending_match = None
    state.hold_until = None
    # Aday, gecis yapildiysa ya da pencere emin eslestiyse biter; zayif pencere eslesmesinde bekler
    if jump in ("natural", "verified") or score >= JUMP_SEARCH_BELOW:
        state.jump_candidate = None
    # En ileri ayet: sure degisince / Fatiha'ya yeni girince sifirdan
    if state.last_surah != last_surah or (state.state == NamazState.FATIHA and state_before != NamazState.FATIHA.value):
        state.max_ayah = last_ayah
    else:
        state.max_ayah = max(state.max_ayah or 0, last_ayah)

    gap_filled = 0
    if state.last_surah and state.last_ayah and first_surah == state.last_surah:
        gap = first_ayah - state.last_ayah - 1
        if 0 < gap <= MAX_GAP_FILL: gap_filled = gap

    if state.state == NamazState.ZAMM:
        if state.zamm_surah == last_surah and state.zamm_ayah is not None:
            state.zamm_ayah = max(state.zamm_ayah, last_ayah)
        else:
            state.zamm_surah, state.zamm_ayah = last_surah, last_ayah
    state.last_word_index = match.end_word_idx
    state.last_surah = last_surah
    state.last_ayah = last_ayah
    state.lost_chunks = 0
    state.matched_chunks += 1
    state.fresh_jump = None
    state.last_match_chunk = chunk_index
    if word_count >= MIN_WORD_COUNT_FIRST_LOCK and score >= MIN_CONFIDENCE_FIRST_LOCK:
        state.last_solid_chunk = chunk_index

    return {
        "chunk_index": chunk_index,
        "state_before": state_before,
        "state": state.state.value,
        "status": "matched",
        "verses": verses,
        "match_start": match.start_word_idx,
        "match_end": match.end_word_idx,
        "score": score,
        "word_count": word_count,
        "gap_filled": gap_filled,
        "jump": jump,
        "first_surah": first_surah, "first_ayah": first_ayah,
        "last_surah": last_surah, "last_ayah": last_ayah,
    }


def _process_chunk_core(rms, transcribed_text, chunk_index, state,
                        corpus, ayah_to_range, surah_counts, vocab):
    state.total_chunks += 1
    state_before = state.state.value

    # Sessizlik
    if rms < MIN_RMS_ENERGY:
        if state.state in (NamazState.FATIHA, NamazState.ZAMM):
            state.lost_chunks += 1
        cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "silent"}

    # ASR uydurmasi (Kuran'da olmayan video girisi kelimeleri) → ifade cikarilir, okuma kalmazsa bos sayilir
    if transcribed_text:
        transcribed_text = strip_asr_hallucination(transcribed_text)
    # Tilavet sonu ("صدق الله العظيم") → kilit / adaylar biter — bkz. TILAVET_END
    tilavet_end = False
    if transcribed_text:
        transcribed_text, tilavet_end = strip_tilavet_end(transcribed_text)
        if (tilavet_end and state.last_tekbir_chunk is not None and state.last_match_chunk is not None
                and state.last_tekbir_chunk > state.last_match_chunk
                and chunk_index - state.last_match_chunk >= TILAVET_END_NAMAZ_GAP):
            tilavet_end = False
        if tilavet_end:
            reset_for_new_namaz(state, chunk_index, 0)
            state.hold_until = None
            state.search_texts = []

    # Bos
    if not transcribed_text:
        state.lost_chunks += 1
        cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "empty"}

    # Namaz yapisi sinyali (kamet / selam / rukû) — bkz. KAMET_HOLD_CHUNKS
    signal = namaz_signal(transcribed_text)
    # Zamm kilitli degilken (ya da kilit kaybolmusken) tek basina zikir ifadesi — bkz. DHIKR_PHRASES, TEKBIR_TEVHID_CHUNKS
    abandoned = (state.lost_chunks >= ABANDON_LOCK_AFTER_LOST and state.state in (NamazState.FATIHA, NamazState.ZAMM))
    dhikr, sehadet = (dhikr_only(transcribed_text) if signal is None and (state.state != NamazState.ZAMM or abandoned)
                      else (False, False))
    in_hold = state.hold_until is not None and chunk_index <= state.hold_until
    tekbir_tevhid = (dhikr and not in_hold and (state.state in (NamazState.BEKLEME, NamazState.ARA) or abandoned)
                     and state.last_tekbir_chunk is not None
                     and chunk_index - state.last_tekbir_chunk <= TEKBIR_TEVHID_CHUNKS and is_tevhid(transcribed_text))
    if is_tekbir_only([t for t in (bare_token(w) for w in transcribed_text.split()) if t]):
        state.last_tekbir_chunk = chunk_index
    if (dhikr and sehadet and state.state == NamazState.BEKLEME) or tekbir_tevhid:
        signal = "kamet"
    if signal == "kamet":
        # Kamet/ezan Kuran degil: parca bos sayilir, yeni namaz basliyor
        reset_for_new_namaz(state, chunk_index, KAMET_HOLD_CHUNKS)
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "empty", "signal": signal}
    if dhikr:
        # Kamet / rukû / selam beklemesindeyken zikir: namaz baslamadi, Fatiha beklemesi uzar (cuma #3: kamet sonrasi
        # "لا إله إلا الله", "إن شاء الله"; bekleme bitince "والحمد لله رب العالمين" 6:45 adayi olup Fatiha 7 sn gecikti)
        if state.hold_until is not None and chunk_index <= state.hold_until:
            state.hold_until = max(state.hold_until, chunk_index + KAMET_HOLD_CHUNKS)
        state.lost_chunks += 1
        cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "empty"}
    if signal == "selam" and state.state in (NamazState.BEKLEME, NamazState.ARA):
        reset_for_new_namaz(state, chunk_index, RUKU_HOLD_CHUNKS)
    elif signal == "ruku":
        if state.state in (NamazState.FATIHA, NamazState.ZAMM):
            state.state_transitions.append(f"{state.state.value} → {NamazState.ARA.value}")
            state.state = NamazState.ARA
        state.pending_match = None
        state.jump_candidate = None
        state.hold_until = chunk_index + RUKU_HOLD_CHUNKS
    hold = state.hold_until is not None and chunk_index <= state.hold_until

    # Istiaze kelimelerini cikar (hepsi istiazeyse kelime sayisi 0 → too_short)
    transcribed_text, _ = strip_istiaze(transcribed_text)
    transcribed_text, _ = strip_namaz_phrases(transcribed_text)
    tokens = [normalize_arabic(t) for t in transcribed_text.split() if t]
    word_count = len([t for t in tokens if t])
    is_hot = state.state in (NamazState.FATIHA, NamazState.ZAMM)
    min_words = MIN_WORD_COUNT_HOT if is_hot else MIN_WORD_COUNT_COLD
    if word_count < min_words:
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "too_short", "word_count": word_count}

    preferred_range = compute_preferred_range(state, ayah_to_range, surah_counts)
    lock_abandoned = (state.lost_chunks >= ABANDON_LOCK_AFTER_LOST and state.state in (NamazState.FATIHA, NamazState.ZAMM))

    resumed = False   # kilit kaybinda kalinan yerin penceresi secildi (asagidaki Fatiha yoklamasinda pencere ici sayilir)
    if hold:
        # Kamet / rukû / selam sonrasi: sadece Fatiha (yeni rekat) ya da kalinan yerden devam (ARA, ayni sure
        # son ayetin -RESUME_BACK..+PREFERRED_AYAH_WINDOW_ARA, skor >= HOLD_RESUME_MIN_SCORE). Tum Kuran aranmaz.
        match = align_transcription(transcribed_text, corpus, preferred_range=fatiha_range(ayah_to_range), preferred_bonus=PREFERRED_BONUS)
        score = score_transcription(transcribed_text, match, vocab)
        if state.state == NamazState.ARA and state.last_surah and state.last_ayah:
            rw = ayah_window(state.last_surah, state.last_ayah, RESUME_BACK, PREFERRED_AYAH_WINDOW_ARA, ayah_to_range, surah_counts)
            if rw:
                rm = align_transcription(transcribed_text, corpus, preferred_range=rw, preferred_bonus=PREFERRED_BONUS)
                rs = score_transcription(transcribed_text, rm, vocab)
                if rm and rs >= HOLD_RESUME_MIN_SCORE and rs > score:
                    match, score = rm, rs
    else:
        match = align_transcription(transcribed_text, corpus, preferred_range=preferred_range, preferred_bonus=PREFERRED_BONUS)
        score = score_transcription(transcribed_text, match, vocab)
        # Kilit kaybolmus (okuma ara verdi): kalinan yerin penceresi (ayni sure, son ayetin -RESUME_BACK..+ARA) tum Kuran'daki
        # en iyi yerle neredeyse esitse (CONTINUE_MARGIN) kalinan yerden devam. Asr 21.10: Hasr 59:23'ten sonra 4 parca ASR
        # bos, 59:24 sonu "وهو العزيز الحكيم" ("الا وهو العزيز") tum Kuran'da 3:6 / 3:18 93.9, 59:24 93.3 → belirsiz aday.
        if (lock_abandoned and state.last_surah and state.last_ayah and word_count >= MIN_WORD_COUNT_FIRST_LOCK
                and match is not None):
            rw = ayah_window(state.last_surah, state.last_ayah, RESUME_BACK, PREFERRED_AYAH_WINDOW_ARA, ayah_to_range, surah_counts)
            if rw and not rw[0] <= match.start_word_idx <= rw[1]:
                rm = align_transcription(transcribed_text, corpus, preferred_range=rw, preferred_bonus=PREFERRED_BONUS)
                rs = score_transcription(transcribed_text, rm, vocab)
                if rm and rw[0] <= rm.start_word_idx <= rw[1] and rs >= HOLD_RESUME_MIN_SCORE and rs >= score - CONTINUE_MARGIN:
                    match, score = rm, rs
                    resumed = True

    # Kilitliyken (ZAMM/ARA) pencere emin degilse Fatiha'yi ayrica dene: yeni rekat Fatiha ile baslar. Tum Kuran
    # aramasi Fatiha ifadelerini baska yere de oturtabiliyor ("الحمد لله رب العالمين" 6:45, 10:10, 37:182...);
    # cuma: 2. rekat Fatiha'si 21:107'ye (62) pencere eslesmesi aldi, kamet kilidinde Fatiha 4:102'ye eslesti.
    # ZAMM'da en az FATIHA_FAST_LOCK_MIN_WORDS kelime: "وإلى رب العالمين" (94:8, ASR bozuk) Fatiha'ya 92.6 aliyor.
    fatiha_jump = False
    fatiha_cand = None   # erken Fatiha (bkz. FATIHA_MIN_GAP_CHUNKS): gecis adayi, sonraki parca dogrular
    # Kilit kaybolmus zamm (ABANDON_LOCK_AFTER_LOST kayip parca, ~30 sn okuma yok) ARA gibi: yeni rekat beklenir. Sabah
    # 21.10: semiallah duyulmadi, 2. rekat Fatiha'si "والحمد لله رب العالمين" ZAMM'da (ARA'ya 12 kayip parca) tum Kuran'da
    # 6:45'e esit skor aldi (belirsiz aday) → Fatiha kilidi 10 sn gecikti.
    ara_like = state.state == NamazState.ARA or (state.state == NamazState.ZAMM and lock_abandoned)
    probe_words = MIN_WORD_COUNT_FIRST_LOCK if ara_like else FATIHA_FAST_LOCK_MIN_WORDS
    if (not hold and state.state in (NamazState.ZAMM, NamazState.ARA) and word_count >= probe_words
            and (not match or score < JUMP_SEARCH_BELOW or ara_like)):
        fm = align_transcription(transcribed_text, corpus, preferred_range=fatiha_range(ayah_to_range), preferred_bonus=PREFERRED_BONUS)
        fs = score_transcription(transcribed_text, fm, vocab)
        base = score if match else 0.0
        # ARA'da (rekat basi beklenir) esitlikte Fatiha kazanir; kalinan yerin penceresindeki eslesme haric
        # (zamm'da Fatiha ile ayni ifade: 37:182 "والحمد لله رب العالمين")
        in_window = resumed or (bool(match) and bool(preferred_range)
                                and preferred_range[0] <= match.start_word_idx <= preferred_range[1])
        if ara_like:
            # pencere disi: Fatiha'ya FATIHA_ARA_MARGIN pay (ASR basa "و" ekliyor: "والحمد لله رب العالمين" 6:45'te birebir
            # 100, Fatiha 1:2 92.4 — sabah 21.10)
            better = fs > base if in_window else fs >= base - FATIHA_ARA_MARGIN
        else:
            better = fs >= base + JUMP_MARGIN
        if fm and fs >= FATIHA_FAST_LOCK_MIN_SCORE and better:
            fv = collect_verses(corpus, fm.start_word_idx, fm.end_word_idx)[-1]
            if early_fatiha(state, chunk_index, fv[1]):
                fatiha_cand = PendingMatch(surah=1, ayah=fv[1], word_index=fm.end_word_idx, chunk_index=chunk_index)
            else:
                match, score = fm, fs
                fatiha_jump = True

    # BEKLEME + aday: aday penceresinde tutmadiysa ayni chunk'ta tum Kuran'da ara. Eskiden yanlis
    # aday (orn. 113:1 / 114:1 ortak ifadesi) 2 chunk bayatlayana kadar dogru yeri aratmiyordu.
    if (not hold and state.state == NamazState.BEKLEME and state.pending_match and preferred_range
            and word_count >= MIN_WORD_COUNT_FIRST_LOCK
            and (not match or score < MIN_CONFIDENCE_FIRST_LOCK)):
        g = align_transcription(transcribed_text, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs = score_transcription(transcribed_text, g, vocab)
        if g and gs >= MIN_CONFIDENCE_FIRST_LOCK:
            match, score = g, gs
    # BEKLEME + aday, pencere tuttu ama tam degil: tum Kuran'da baska yer tek parcada kilit kuralini geciyorsa o.
    # Belirsiz aday "قل أعوذ برب" (113:1) sonrasi "قل أعوذ برب الناس" pencerede 113:1'e ~91 alip adayi YANLIS
    # dogruluyordu (kilit Felak'ta kaliyordu); tum Kuran'da 114:1 100 ve "الناس" ayirt edici.
    elif (not hold and state.state == NamazState.BEKLEME and state.pending_match and preferred_range
            and word_count >= MIN_WORD_COUNT_FIRST_LOCK and match and score < 100):
        g = align_transcription(transcribed_text, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs = score_transcription(transcribed_text, g, vocab)
        outside = bool(g) and not preferred_range[0] <= g.start_word_idx <= preferred_range[1]
        if (outside and gs > score
                and is_unique_match(transcribed_text, g, gs, word_count, corpus, vocab, ayah_to_range)):
            match, score = g, gs
        # Aday penceresindeki eslesme tum Kuran'daki en iyi yerden cok zayifsa adayi dogrulamaz (yeni aday olur): asr
        # 21.10'da belirsiz 6:73 adayini ("عالم الغيب والشهادة", 9:94 ile esit) "هو الرحمن الرحيم" pencerede 71.3 ile
        # dogruladi (tum Kuran'da 100: 2:163 / 59:22) → okunan Hasr 59:22 iken 6:73'e kilit, 20 sn ekranda.
        elif outside and gs >= score + VERIFY_GLOBAL_MARGIN:
            match, score = g, gs

    # Kilitliyken (FATIHA/ZAMM/ARA) pencere emin degilse tum Kuran'da da ara: sure gecisi. Eskiden
    # ABANDON_LOCK_AFTER_LOST (6 chunk, ~30 sn) dolmadan baska yere gecilemiyordu; ustelik Fatiha
    # penceresi zamm suresinin besmelesine / kisa ifadelerine 50-80 skorla "eslesip" kilidi tutuyordu.
    # Taze gecisin yeniden kontrolu (bkz. FRESH_JUMP_CHUNKS): gecis parcasi da yeni surenin acilisina oturmali
    fresh_fix = False
    fj = state.fresh_jump
    if (not hold and state.state == NamazState.ZAMM and fj is not None and 0 < chunk_index - fj[0] <= FRESH_JUMP_CHUNKS
            and not lock_abandoned and not fatiha_jump and fatiha_cand is None and (not match or score < MIN_CONFIDENCE)):
        g = align_transcription(transcribed_text, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs = score_transcription(transcribed_text, g, vocab)
        if g and gs >= FRESH_JUMP_MIN_SCORE and gs >= (score if match else 0.0) + JUMP_MARGIN:
            gfs, gfa = collect_verses(corpus, g.start_word_idx, g.end_word_idx)[0]
            if gfs != state.last_surah and gfa <= 2:
                ow = (ayah_to_range[(gfs, 1)][0], ayah_to_range[(gfs, min(2, surah_counts[gfs]))][1])
                pm = align_transcription(fj[1], corpus, preferred_range=ow, preferred_bonus=PREFERRED_BONUS)
                if (pm and is_opening_match(pm, corpus, ayah_to_range) and pm.start_word_idx <= g.start_word_idx
                        and score_transcription(fj[1], pm, vocab) >= MIN_CONFIDENCE_FIRST_LOCK):
                    match, score = g, gs
                    fresh_fix = True

    jump = "natural" if fatiha_jump else None  # "natural" | "verified" (gecildi) | "candidate" (aday, sonraki chunk dogrulayacak)
    if fresh_fix:
        jump = "verified"
    opening = False
    fresh = False
    short_jump = word_count == JUMP_SHORT_WORDS and at_transition_point(state, surah_counts)
    if (not hold and state.state in (NamazState.FATIHA, NamazState.ZAMM, NamazState.ARA) and preferred_range
            and not lock_abandoned and (word_count >= MIN_WORD_COUNT_FIRST_LOCK or short_jump)
            and fatiha_cand is None and (not match or score < JUMP_SEARCH_BELOW)):
        g = align_transcription(transcribed_text, corpus, preferred_range=None, preferred_bonus=PREFERRED_BONUS)
        gs = score_transcription(transcribed_text, g, vocab)
        base = score if match else 0.0
        content_ok = bool(g) and content_word_count(g, besmele_positions(corpus, ayah_to_range)) >= 2
        ok = content_ok and gs >= MIN_CONFIDENCE_FIRST_LOCK and gs >= base + JUMP_MARGIN
        # Sure basi: gecis noktasinda surenin acilisina oturan eslesme ham hizalama skoruyla (bkz. OPENING_MIN_FUZZY)
        opening = False
        if content_ok and not ok and state.state in (NamazState.FATIHA, NamazState.ZAMM) \
                and at_transition_point(state, surah_counts) and g.score >= OPENING_MIN_FUZZY \
                and g.score >= base + JUMP_MARGIN and is_opening_match(g, corpus, ayah_to_range):
            gv = collect_verses(corpus, g.start_word_idx, g.end_word_idx)
            opening = ok = is_natural_transition(state, gv[0][0], gv[0][1], surah_counts)
        # Kalinan yerden devam da ham hizalama skoruyla: Fatiha sonunda tum Kuran'daki en iyi yer onceki zamm'in devam
        # penceresindeyse (bkz. CONTINUE_*) sozluk cezasi esige takilmasin. Yatsi 22.10 sabit parca: 2. rekat "وعلمناه صنعة
        # لبوس لكم" ASR'de "وعلمناه صنعة لوس لكل تعز" → en iyi yer 21:80 (ham 89.4, sozluk cezali 69.2 < 70) gecilmedi.
        elif content_ok and not ok and state.state == NamazState.FATIHA and state.zamm_surah \
                and at_transition_point(state, surah_counts) and g.score >= OPENING_MIN_FUZZY \
                and g.score >= base + JUMP_MARGIN:
            cw = continue_window(state.zamm_surah, state.zamm_ayah, ayah_to_range, surah_counts)
            ok = bool(cw) and cw[0] <= g.start_word_idx <= cw[1]
        if ok:
            gv = collect_verses(corpus, g.start_word_idx, g.end_word_idx)
            (gfs, gfa), (gls, gla) = gv[0], gv[-1]
        if ok and not opening and word_count < MIN_WORD_COUNT_FIRST_LOCK:
            # Kisa parca: sadece Kuran'da tek yerde gecen ifadeyle dogal gecis (aday da uretmez)
            ok = (gs >= JUMP_SHORT_MIN_SCORE and is_natural_transition(state, gfs, gfa, surah_counts)
                  and phrase_count(corpus, [bare_token(t) for t in transcribed_text.split()]) == 1)
        cont = False
        if ok and state.state == NamazState.FATIHA and state.zamm_surah and at_transition_point(state, surah_counts):
            # Hatim: onceki zamm'in kaldigi yerden devam (bkz. CONTINUE_*)
            cw = continue_window(state.zamm_surah, state.zamm_ayah, ayah_to_range, surah_counts)
            if cw and cw[0] <= g.start_word_idx <= cw[1]:
                cont = True
            elif cw:
                cm = align_transcription(transcribed_text, corpus, preferred_range=cw, preferred_bonus=PREFERRED_BONUS)
                cs = score_transcription(transcribed_text, cm, vocab)
                prior = (cm and not opening and cs >= MIN_CONFIDENCE_FIRST_LOCK and cs >= gs - CONTINUE_PRIOR_MARGIN
                         and not is_opening_match(g, corpus, ayah_to_range))
                if cm and ((cs >= NATURAL_MIN_SCORE and cs >= gs - CONTINUE_MARGIN) or prior):
                    g, gs, cont, opening = cm, cs, True, False
                    gv = collect_verses(corpus, g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
        if ok:
            jc = state.jump_candidate
            if jc and chunk_index - jc.chunk_index > 2:
                jc = None
            # Aday penceresi: tum Kuran eslesmesi adayin disindaysa adayin cevresinde de ara (bkz. CANDIDATE_WINDOW_MARGIN)
            if jc and not cont and not (verify_pending(jc, gfs, gfa) or verify_pending(jc, gls, gla)):
                jw = ayah_window(jc.surah, jc.ayah, PENDING_VERIFY_AYAH_WINDOW, PENDING_VERIFY_AYAH_WINDOW,
                                 ayah_to_range, surah_counts)
                jm = align_transcription(transcribed_text, corpus, preferred_range=jw, preferred_bonus=PREFERRED_BONUS) if jw else None
                js = score_transcription(transcribed_text, jm, vocab)
                if jm and js >= MIN_CONFIDENCE_FIRST_LOCK and js >= gs - CANDIDATE_WINDOW_MARGIN:
                    g, gs, opening = jm, js, False
                    gv = collect_verses(corpus, g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
            if not opening and not cont and state.state == NamazState.FATIHA and gs >= NATURAL_MIN_SCORE \
                    and is_natural_transition(state, gfs, gfa, surah_counts) and not starts_ayah(g, corpus, ayah_to_range):
                # Zamm ayet basindan baslar: ayni ifade iki yerde (yatsi 19.10: "الذين اتخذوا دينهم" 6:70 "وذر ..." ortasi /
                # 7:51 basi) → ayet basindaki ikinci yer (bkz. AYAH_START_TIE_MARGIN)
                ru = runner_up_match(transcribed_text, g, corpus)
                if ru is not None and ru.score >= g.score - AYAH_START_TIE_MARGIN and starts_ayah(ru, corpus, ayah_to_range):
                    rv = collect_verses(corpus, ru.start_word_idx, ru.end_word_idx)
                    rs = score_transcription(transcribed_text, ru, vocab)
                    if rs >= NATURAL_MIN_SCORE and is_natural_transition(state, rv[0][0], rv[0][1], surah_counts):
                        g, gs, gv = ru, rs, rv
                        (gfs, gfa), (gls, gla) = gv[0], gv[-1]
            if (not opening and not cont and state.state == NamazState.FATIHA and gs >= MIN_CONFIDENCE_FIRST_LOCK
                    and at_transition_point(state, surah_counts) and not is_opening_match(g, corpus, ayah_to_range)):
                # Sure acilisi onceligi: bkz. OPENING_PREFER_MARGIN
                om, oms = opening_preference(transcribed_text, corpus, ayah_to_range, surah_counts, vocab)
                if om is not None and oms >= gs - OPENING_PREFER_MARGIN:
                    g, gs, opening = om, oms, True
                    gv = collect_verses(corpus, g.start_word_idx, g.end_word_idx)
                    (gfs, gfa), (gls, gla) = gv[0], gv[-1]
            in_candidate = bool(jc) and (verify_pending(jc, gfs, gfa) or verify_pending(jc, gls, gla))
            # Devam (kalinan yer) dogal gecis: devam onceliginde skor NATURAL_MIN_SCORE altinda olabilir (bkz. CONTINUE_PRIOR_MARGIN)
            natural = opening or cont or (is_natural_transition(state, gfs, gfa, surah_counts) and gs >= NATURAL_MIN_SCORE)
            tie = (natural and not cont and is_opening_match(g, corpus, ayah_to_range)
                   and opening_tie(transcribed_text, g, corpus, ayah_to_range))
            if tie:
                natural = opening = False
            # Zamm sonundan Fatiha'ya dogal gecis en az FATIHA_FAST_LOCK_MIN_WORDS kelimeyle (Fatiha yoklamasindaki gibi):
            # sabah 21.10 sabit parca, Adiyat sonu "إن ربهم بهم" → ASR "إن رب العالمين" Fatiha 1:2'ye dogal gecis oldu (yeni
            # rekat rukû / secdeden sonra gelir — kilit kaybolmus zamm / ARA'da Fatiha yoklamasi 3 kelimeyle)
            early = gfs == 1 and early_fatiha(state, chunk_index, gla)
            if (natural and gfs == 1 and state.state == NamazState.ZAMM and not lock_abandoned
                    and word_count < FATIHA_FAST_LOCK_MIN_WORDS) or early:
                natural = opening = False
            if natural:
                jump = "natural"
            elif in_candidate:
                jump = "verified"
            elif not tie and not early and is_unique_match(transcribed_text, g, gs, word_count, corpus, vocab, ayah_to_range):
                # Fark payi: Kuran'da baska yerde benzeri olmayan net eslesme ikinci parcayi beklemez
                # (telefon kaydi: 55 → 107 gecisi 12 → 7 sn; gurultu testinde yanlis kilit artmadi)
                jump = "verified"
            elif (state.state == NamazState.ZAMM and score < MIN_CONFIDENCE_FIRST_LOCK and gfs == state.last_surah
                  and state.last_ayah is not None and state.last_ayah - RESUME_BACK <= gla < state.last_ayah):
                # Geri duzeltme: pencere eslesmesi zayif, ayni surede kalinan yerin 1-2 ayet gerisi tum Kuran'da en az
                # JUMP_MARGIN iyi → onceki zayif eslesme konumu ileri tasimis (okuma geri gitmez). Yatsi 21.10, 2. rekat: 21:24
                # okunurken bozuk "بدأ يدع لنا" 21:25'e 65 ile esleşti; pencere (21:25-27) 21:24'u kapsamadigindan sonraki
                # parcalar 21:27 / 21:28'e 50-57 ile kaydi (tum Kuran'da 21:24 84.5), sonra 21:25'e geri dondu.
                jump = "verified"
            else:
                jump = "candidate"
                state.jump_candidate = PendingMatch(surah=gls, ayah=gla, word_index=g.end_word_idx, chunk_index=chunk_index)
            if jump != "candidate":
                match, score = g, gs
            fresh = jump == "natural" and state.state == NamazState.FATIHA and not opening and not cont
    if fatiha_cand is not None:
        jump = "candidate"
        state.jump_candidate = fatiha_cand

    # BEKLEME'de belirsiz eslesme yerine Fatiha basi — bkz. FATIHA_ARA_MARGIN
    if (not hold and state.state == NamazState.BEKLEME and match is not None and jump is None
            and state.pending_match is None
            and word_count >= FATIHA_FAST_LOCK_MIN_WORDS and corpus.words[match.start_word_idx].surah != 1):
        fm = align_transcription(transcribed_text, corpus, preferred_range=fatiha_range(ayah_to_range), preferred_bonus=PREFERRED_BONUS)
        fs = score_transcription(transcribed_text, fm, vocab)
        if (fm and fs >= FATIHA_FAST_LOCK_MIN_SCORE and fs >= score - FATIHA_ARA_MARGIN
                and corpus.words[fm.start_word_idx].ayah <= 3):
            ru = runner_up_match(transcribed_text, match, corpus)
            if ru is not None and score - score_transcription(transcribed_text, ru, vocab) < AMBIGUOUS_MARGIN:
                match, score = fm, fs

    is_first_lock = state.state == NamazState.BEKLEME
    # Kilit kayboldu (6+ kayip chunk ya da ARA): yeniden kilit ilk kilit gibi. Eskiden ARA'da tum Kuran'da
    # 50 skorla tek chunk kilit veriyordu (gercek namaz: selam → 6:54, "سمع الله حمدا" → 3:181)
    relock = lock_abandoned or state.state == NamazState.ARA
    if relock or is_first_lock:
        eff_thresh = MIN_CONFIDENCE_FIRST_LOCK
        req_min = MIN_WORD_COUNT_FIRST_LOCK
    else:
        eff_thresh = MIN_CONFIDENCE
        req_min = 0
    insufficient = req_min > 0 and word_count < req_min
    # Okuma ara verdiyse kisa + zayif eslesme devam sayilmaz — bkz. PAUSE_LOST_CHUNKS
    # Kilitliyken tek basina "(و)الحمد لله" zayif eslesmesi okuma degil — bkz. STOCK_PHRASES
    stock_weak = (state.state in (NamazState.FATIHA, NamazState.ZAMM) and not relock and jump not in ("natural", "verified")
                  and score < MIN_CONFIDENCE_FIRST_LOCK
                  and tuple(t for t in (bare_token(w) for w in transcribed_text.split()) if t) in STOCK_PHRASES)
    tekbir_weak = (state.state == NamazState.ZAMM and not relock and not opening and jump not in ("natural", "verified")
                   and tekbir_after_reading(state) and word_count < MIN_WORD_COUNT_FIRST_LOCK and score < TEKBIR_SHORT_MIN_SCORE)
    paused_weak = (state.state == NamazState.ZAMM and not relock and not opening and state.lost_chunks >= PAUSE_LOST_CHUNKS
                   and word_count < MIN_WORD_COUNT_FIRST_LOCK and score < MIN_CONFIDENCE_FIRST_LOCK)

    # Sure basi gecisi kendi esigiyle (ham hizalama) dogrulandi; sozluk cezali skor esige takilmasin
    if (score < eff_thresh and not opening) or not match or insufficient or paused_weak or stock_weak or tekbir_weak:
        state.lost_chunks += 1
        cleanup_stale_candidates(state, chunk_index)
        new_state = transition_state(state, False, None, None)
        if new_state != state.state:
            state.state_transitions.append(f"{state.state.value} → {new_state.value}")
            state.state = new_state
        if jump == "candidate":
            jc = state.jump_candidate
            return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "pending", "pending_surah": jc.surah, "pending_ayah": jc.ayah, "score": score, "word_count": word_count, "jump": True}
        return {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "low_confidence", "score": score, "word_count": word_count, "match_start": match.start_word_idx if match else None, "match_end": match.end_word_idx if match else None}

    verses = collect_verses(corpus, match.start_word_idx, match.end_word_idx)
    first_surah, first_ayah = verses[0]
    last_surah, last_ayah = verses[-1]

    # Pending (Fatiha basina guclu eslesme haric — namazda ilk okunan Fatiha)
    fatiha_fast = (state.state == NamazState.BEKLEME and first_surah == 1 and score >= FATIHA_FAST_LOCK_MIN_SCORE
                   and ((first_ayah <= 3 and word_count >= FATIHA_FAST_LOCK_MIN_WORDS)
                        or (hold and word_count >= MIN_WORD_COUNT_FIRST_LOCK)))
    # Yeniden kilitte dogrulamasiz: rekat basi Fatiha (rukû/secde sonrasi beklenen), kalinan yerden devam ya da
    # 2 parcayla dogrulanmis gecis (ARA'da gecis adayi dogrulaninca bir de aday dogrulamasi bekleniyordu)
    relock_fast = relock and (
        jump == "verified"
        or (first_surah == 1 and score >= FATIHA_FAST_LOCK_MIN_SCORE and word_count >= MIN_WORD_COUNT_FIRST_LOCK)
        or (first_surah == state.last_surah and state.last_ayah is not None
            and state.last_ayah - RESUME_BACK <= first_ayah <= state.last_ayah + PREFERRED_AYAH_WINDOW_ARA))
    # Tek parcada kilit (fark payi): sadece ilk kilit (BEKLEME, bekleme yokken) — bkz. UNIQUE_LOCK_*
    unique = (state.state == NamazState.BEKLEME and not fatiha_fast and not hold
              and is_unique_match(transcribed_text, match, score, word_count, corpus, vocab, ayah_to_range))
    if ((state.state == NamazState.BEKLEME and not fatiha_fast) or (relock and not relock_fast)) and not unique:
        pm = state.pending_match
        verified = pm is not None and (verify_pending(pm, first_surah, first_ayah) or verify_pending(pm, last_surah, last_ayah))
        # Belirsiz adayi geriye giden parca dogrulamaz (okuma ileri gider): asr 21.10, "هو الرحمن الرحيم" 2:163 sonu / 59:22
        # sonu esit (belirsiz aday 2:163) → sonraki "لا اله الا هو" (59:23 basi) 2:163'te adayin GERISINE oturup dogruladi,
        # 2:163'e kilit. Ayetu'l-Kursi'de ("الله لا ال" 2:255 / 3:2 → "لا اله الا هو") dogrulayan parca ileride biter.
        # (Ayirt etmeyen parca dogrulamasin denendi: Kursi ilk kilidi 10 → 20 sn.)
        if verified and pm.alt_surah is not None and match.end_word_idx <= pm.word_index:
            verified = False
        if not verified:
            state.pending_match = PendingMatch(surah=last_surah, ayah=last_ayah, word_index=match.end_word_idx, chunk_index=chunk_index)
            res = {"chunk_index": chunk_index, "state_before": state_before, "state": state.state.value, "status": "pending", "pending_surah": last_surah, "pending_ayah": last_ayah, "score": score}
            # Belirsiz aday: ikinci yer (araliga degmeyen) neredeyse ayni iyi → ekranda gosterilmez (bkz. AMBIGUOUS_MARGIN)
            ru = runner_up_match(transcribed_text, match, corpus)
            if ru and score - score_transcription(transcribed_text, ru, vocab) < AMBIGUOUS_MARGIN:
                res["ambiguous"] = True
                ra = collect_verses(corpus, ru.start_word_idx, ru.end_word_idx)[-1]
                state.pending_match.alt_surah, state.pending_match.alt_ayah = ra
            return res

    res = commit_match(state, match, score, word_count, chunk_index, state_before, jump, corpus)
    if fresh:
        state.fresh_jump = (chunk_index, transcribed_text)
    return res


# ============================================================
# Senaryolar — gerçekçi namaz akışları
# ============================================================
# Her chunk: (rms, transcribed_text)
# rms = 0.0 → sessizlik chunk'i
# rms > 0.005 → konuşma var, transkripsiyon işlenir

SCENARIOS = [
    # ============ Senaryo 1: Fatiha + Ihlas ============
    {
        "description": "Fatiha + İhlas — temiz geçiş",
        "chunks": [
            (0.0, ""),                                      # 0: bekleme, sessiz
            (0.0, ""),                                      # 1: bekleme, sessiz
            (0.05, "بسم الله الرحمن الرحيم الحمد لله رب العالمين"),  # 2: Fatiha 1:1+1:2 (besmele atlanir)
            (0.05, "الرحمن الرحيم مالك يوم الدين"),         # 3: Fatiha 1:3-4
            (0.05, "اياك نعبد واياك نستعين"),               # 4: Fatiha 1:5
            (0.05, "اهدنا الصراط المستقيم"),                # 5: Fatiha 1:6
            (0.05, "صراط الذين انعمت عليهم"),               # 6: Fatiha 1:7
            (0.0, ""),                                      # 7: ara
            (0.05, "قل هو الله احد الله الصمد"),            # 8: Ihlas 112:1-2 (ZAMM gecisi)
            (0.05, "لم يلد ولم يولد"),                      # 9: Ihlas 112:3
            (0.05, "ولم يكن له كفوا احد"),                  # 10: Ihlas 112:4
            (0.0, ""),                                      # 11: sessiz
        ]
    },

    # ============ Senaryo 2: Pending dogrulama ============
    {
        "description": "Pending match — ilk match dogrulamali",
        "chunks": [
            (0.05, "الحمد لله رب العالمين"),  # 0: pending (Fatiha 1:2)
            (0.05, "الرحمن الرحيم مالك يوم الدين"),  # 1: dogrulandi, FATIHA
            (0.05, "اياك نعبد واياك نستعين"),  # 2: FATIHA
        ]
    },

    # ============ Senaryo 3: Düşük güven sonra eşleşme ============
    {
        "description": "Bozuk transkripsiyon → low_confidence, sonra duzgun",
        "chunks": [
            (0.05, "abc def ghi"),  # 0: gibberish, low_conf
            (0.05, "تست تست"),       # 1: too_short veya low_conf
            (0.05, "الحمد لله رب العالمين الرحمن الرحيم"),  # 2: pending
            (0.05, "مالك يوم الدين اياك نعبد"),  # 3: dogrulandi
        ]
    },

    # ============ Senaryo 4: Zamm sırasında kaybetme ============
    {
        "description": "ZAMM'da kaybetme - lost_chunks artar",
        "chunks": [
            (0.05, "الحمد لله رب العالمين"),  # 0: pending
            (0.05, "الرحمن الرحيم مالك يوم الدين"),  # 1: FATIHA
            (0.05, "قل هو الله احد"),  # 2: ZAMM (Ihlas)
            (0.0, ""),  # 3: sessiz, lost+1
            (0.0, ""),  # 4: sessiz, lost+1
            (0.05, "لم يلد ولم يولد"),  # 5: ZAMM devam
        ]
    },

    # ============ Senaryo 5: Gercek namaz (aksam, 27.09) — rekat arasi + zikirler + selam ============
    {
        "description": "Gercek namaz: zamm → rukû/secde → 2. rekat Fatiha → zamm → sessiz rekat → selam",
        "chunks": (
            [
                (0.05, "والأرض زلزالها وأخرجت الأرض أثقالها"),   # 0: pending 99:1-2
                (0.05, "وقال الإنسان ما لها"),                  # 1: dogrulandi → ZAMM
                (0.05, "يومئذ تحدث أخبارها بأن ربك أوحى لها"),  # 2: ZAMM 99:4-5
            ]
            + [(0.05, "")] * 6                                  # 3-8: rukû/secde, lost 6 → kilit terk
            + [
                (0.05, "شركة الهدى للخدمات التقنية"),           # 9: ASR uydurmasi → bos
                (0.05, "سمع الله لمن حمده"),                    # 10: zikir → too_short (3:181 degil)
                (0.05, "الحمد لله رب العالمين الرحمن الرحيم"),  # 11: rekat basi Fatiha → FATIHA (dogrulamasiz)
                (0.05, "إياك نعبد وإياك نستعين"),               # 12: FATIHA
                (0.05, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 13: FATIHA 1:7
                (0.05, "قل يا أيها الكافرون"),                  # 14: dogal gecis → ZAMM 109:1
                (0.05, "لا أعبد ما تعبدون"),                    # 15: ZAMM 109:2
            ]
            + [(0.0, "")] * 12                                  # 16-27: sessiz rekat → ARA
            + [
                (0.05, "السلام عليكم ورحمة الله"),              # 28: selam → too_short (6:54 degil)
                (0.05, "لا تنسوا مشاركة العمل"),                # 29: ASR uydurmasi → bos
            ]
        ),
    },

    # ============ Senaryo 6: Gercek namaz #2 (01.10) + telefon — kisa sure gecisi, "المصدر", namaz sonu duasi ============
    {
        "description": "Sure sonu 2 kelimeyle gecis (Maun → Kureys) + ASR 'المصدر' + selam ve namaz sonu duasi",
        "chunks": (
            [
                (0.05, "أرأيت الذي يكذب بالدين"),               # 0: pending 107:1
                (0.05, "فذلك الذي يدع اليتيم"),                 # 1: dogrulandi → ZAMM 107:2
                (0.05, "ولا يحض على طعام المسكين"),             # 2: ZAMM 107:3
                (0.05, "فويل للمصلين الذين هم عن صلاتهم ساهون"),  # 3: ZAMM 107:4-5
                (0.05, "الذين هم يراءون ويمنعون الماعون"),      # 4: ZAMM 107:6-7 (sure sonu)
                (0.05, "لإيلاف قريش"),                          # 5: 2 kelime, Kuran'da tek yer → dogal gecis 106:1
                (0.05, "إيلافهم رحلة الشتاء والصيف"),           # 6: ZAMM 106:2
                (0.05, "المصدر كتاب"),                          # 7: ASR uydurmasi cikar → too_short
            ]
            + [(0.0, "")] * 12                                  # 8-19: sessiz → ARA
            + [
                (0.05, "السلام عليكم ورحمة الله"),              # 20: selam → too_short
                (0.05, "السلام منك السلام"),                    # 21: namaz sonu duasi → too_short (59:23 adayi degil)
                (0.05, "تباركت يا ذا الجلال والإكرام"),         # 22: namaz sonu duasi → too_short (55:27 adayi degil)
            ]
        ),
    },
    {
        # Gercek cuma namazi (02.10) transkriptlerinden: kamet Kuran'a eslesiyordu (4:101 kilit), Fatiha 4:102'ye,
        # zamm basi 7:100'e (dogal gecis 74.5), semiallah sonrasi "لمن عمل" 21:106'ya
        "description": "Cuma: kamet → tekbir → Fatiha → Enbiya → rukû → Fatiha → İnşirah (yanlis tekbir) → selam",
        "chunks": [
            (0.19, "أشهد ان لا إله الا الله لا إله إلا الله"),   # 0: kamet → bos, BEKLEME + Fatiha beklemesi
            (0.17, "لا إله إلا الله محمد"),                   # 1: kamet (eskiden 37:35 adayi)
            (0.20, "الصلاة حي الصلاة"),                       # 2: kamet (eskiden 4:103 adayi)
            (0.16, "بل قام بالصلاة"),                         # 3: kamet (eskiden 4:101 kilit)
            (0.19, "الله اغبر"),                              # 4: tekbir (اغبر) → too_short
            (0.14, "لا اله الا الله"),                        # 5: bekleme: sadece Fatiha → low_confidence
            (0.09, "والشهداء رمضان الله تعالى"),              # 6: bekleme → low_confidence
            (0.0, ""),                                        # 7: sessiz
            (0.08, "الحمد لله رب العالمين"),                  # 8: beklemede Fatiha >= 90 → FATIHA 1:2
            (0.09, "الرحمن الرحيم مالك يوم الدين"),           # 9: FATIHA 1:3-4
            (0.09, "إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ"),        # 10: FATIHA 1:5
            (0.08, "اهدنا الصراط المستقيم"),                  # 11: FATIHA 1:6
            (0.09, "صراط الذين أنعمت عليهم"),                 # 12: FATIHA 1:7
            (0.13, "ولا الضالين"),                            # 13: FATIHA 1:7
            (0.09, "لا يسمعون عصيس"),                         # 14: 7:100 (< 77) → dogal gecis degil, aday
            (0.12, "لَهُمُ الْفَزَعُ الْأَكْبَرُ وَتَتَلَقَّاهُمْ"),     # 15: dogal gecis → ZAMM 21:103
            (0.10, "الذي كنتم توعدون"),                       # 16: ZAMM 21:103
            (0.11, "يوم نطوي السماء كطي السجل للكتب"),        # 17: ZAMM 21:104
            (0.11, "إنا كنا فاعلين"),                         # 18: ZAMM 21:104
            (0.06, "الله أكبر"),                              # 19: rukû tekbiri → too_short (sinyal degil)
            (0.09, "سمع الله لمن حمده"),                      # 20: semiallah → ARA + bekleme (sadece Fatiha / devam)
            (0.11, "لمن عمل"),                                # 21: too_short (eskiden 21:106 kilit)
            (0.11, "المصدر"),                                 # 22: too_short
            (0.11, "الحمد لله رب العالمين الرحمن الرحيم"),    # 23: 2. rekat Fatiha → FATIHA 1:2-3
            (0.09, "مالك يوم الدين إياك نعبد"),               # 24: FATIHA
            (0.10, "وإياك نستعين اهدنا الصراط المستقيم"),     # 25: FATIHA
            (0.09, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 26: FATIHA 1:7
            (0.12, "ألم نشرح لك صدرك"),                       # 27: dogal gecis → ZAMM 94:1
            (0.09, "الله أكبر"),                              # 28: okuma ortasinda tekbir → too_short, kilit surer
            (0.10, "ووضعنا عنك وزرك الذي أنقض ظهرك"),         # 29: ZAMM 94:2-3
            (0.10, "ورفعنا لك ذكرك"),                         # 30: ZAMM 94:4
            (0.09, "فإن مع العسر يسرا إن مع العسر يسرا"),     # 31: ZAMM 94:5-6
            (0.10, "فإذا فرغت فانصب وإلى ربك فارغب"),         # 32: ZAMM 94:7-8
            (0.09, "كفر الله أكبر"),                          # 33: sure sonu, 1 kelime kalir
            (0.08, "سمع الله لمن حمده"),                      # 34: semiallah → ARA + bekleme
            (0.10, "لمن عمل صالحا من ذكر"),                   # 35: beklemede tum Kuran aranmaz (16:97 adayi yok) → dusuk
        ]
        + [(0.0, "")] * 6                                     # 36-41: secde / tahiyyat
        + [
            (0.10, "السلام عليكم ورحمة الله"),                # 42: selam (ARA) → BEKLEME + bekleme
            (0.10, "السلام عليكم ورحمة الله"),                # 43: selam
            (0.02, "مبارك عليكم خير و سيدنا جعل"),            # 44: dua → low_confidence
        ],
    },
    {
        "name": "cuma2_kamet_varyant_sure_basi",
        "description": "Cuma #2: bozuk kamet (خير/على الصلاة, مضت) → Fatiha → Tekasur bozuk basi → Fatiha → Asr bozuk basi",
        "chunks": [
            (0.21, "خير الصلاة على الصلاة"),                  # 0: kamet (eskiden 4:142 adayi — ekranda "Nisa")
            (0.19, "قد قام بالصلاة"),                         # 1: kamet
            (0.19, "مضت الصلاة"),                             # 2: kamet (قد قامت الصلاة)
            (0.20, "الله اغبر الله اغبر يا الله"),            # 3: bekleme → low_confidence
            (0.20, "لا اله الا الله"),                        # 4: bekleme → low_confidence
            (0.12, "بالنسبة للشمس والشيطان وظل"),             # 5: low_confidence
            (0.06, "الله اغبر"),                              # 6: tekbir → too_short
            (0.09, "الحمد لله رب العالمين"),                  # 7: FATIHA 1:2
            (0.10, "الرحمن الرحيم مالك البيوت"),              # 8: FATIHA 1:3-4
            (0.09, "الدين إياك نعبد وإياك نستعين"),           # 9: FATIHA 1:4-5
            (0.08, "ذاك المستعين اهد إلى الصراط"),            # 10: low_confidence
            (0.08, "صراط الذين"),                             # 11: FATIHA 1:7
            (0.09, "أنعمت عليهم غير المضون"),                 # 12: FATIHA 1:7
            (0.13, "والمغضوب عليهم ولا الضال"),               # 13: FATIHA 1:7
            (0.03, ""),                                       # 14: bos
            (0.08, "ألهاكم التجاد"),                          # 15: sure basi (2 kelime, ASR bozuk) → ZAMM 102:1
            (0.08, "حَتَّى زُرْتُمُ الْمَقَابِرَ"),                # 16: ZAMM 102:2
            (0.10, "كلا سوف تعلمون"),                         # 17: ZAMM 102:3
            (0.11, "ثُمَّ كَلَّا سَوْفَ تَعْلَمُونَ"),               # 18: ZAMM 102:4
            (0.08, "كلا لو تعلمون علم"),                      # 19: ZAMM 102:5
            (0.09, "علم اليقين لترون الجحيم"),                # 20: ZAMM 102:5-6
            (0.09, "ثم لا ترى"),                              # 21: ZAMM 102:7
            (0.09, "لَهَا عَيْنَا الْيَقِينِ"),                    # 22: ZAMM 102:7
            (0.05, "ثُمَّ لَتَسْأَلُونَ"),                        # 23: ZAMM 102:8
            (0.06, "عن النعيم"),                              # 24: ZAMM 102:8
            (0.09, "الله أكبر"),                              # 25: rukû tekbiri → too_short
            (0.10, "سمع القول لمن حمد"),                      # 26: bozuk semiallah ("لمن حمد") → ARA + bekleme
            (0.0, ""),                                        # 27: sessiz
            (0.12, "الله اسمع الله اغبر"),                    # 28: low_confidence
            (0.12, "الحمد لله رب العالمين الرحمن الرحيم"),    # 29: 2. rekat Fatiha (yoklama) → FATIHA 1:2-3
            (0.08, "مالك يوم الدين إياك نعبد"),               # 30: FATIHA 1:4-5
            (0.10, "ندعو وإياك نستعين"),                      # 31: FATIHA 1:5
            (0.09, "صراط الذين"),                             # 32: FATIHA 1:7
            (0.09, "أنعمت عليهم غير المغضوب عليهم"),          # 33: FATIHA 1:7
            (0.13, "عَلَيْهِمْ وَلَا الضَّالِّ"),                  # 34: FATIHA 1:7
            (0.04, ""),                                       # 35: bos (amin)
            (0.09, "والعص إن الإنسان لعام"),                  # 36: sure basi (ASR bozuk) → ZAMM 103:1-2
            (0.11, "وَإِن سَانَ لَفِي خُسْرِ إِلَّا الَّذِينَ آمَنُوا"),  # 37: ZAMM 103:2-3
            (0.11, "وَعَمِلُوا الصَّالِحَاتِ"),                   # 38: ZAMM 103:3
            (0.10, "وتواصوا بالعربي"),                        # 39: ZAMM 103:3
            (0.07, "سمع الله لمن حمده"),                      # 40: semiallah → ARA + bekleme
        ]
        + [(0.0, "")] * 6                                     # 41-46: secde / tahiyyat
        + [
            (0.09, "السلام عليكم"),                           # 47: selam (ARA) → BEKLEME + bekleme
            (0.10, "السلام عليكم ورحمة الله"),                # 48: selam
            (0.10, "عليكم ورحمة الله"),                       # 49: parca sinirinda bolunen selam → too_short (eskiden 1:1 ADAY)
        ],
    },
    # ============ Senaryo 9: yavas okuma — birikmis metinle ilk kilit + bozuk semiallah ============
    {
        "description": "Yavaş okuma (Rahman): birikmiş metinle ilk kilit, bozuk semiallah, rekât başı Fatiha",
        "chunks": [
            (0.0, ""),                                        # 0: sessiz
            (0.07, "خلق الإنسان"),                            # 1: 2 kelime → too_short (birikir)
            (0.06, "علمه البيان"),                            # 2: birikmis "خلق الإنسان علمه البيان" → 55:3-4 kilit
            (0.08, "الشمس والقمر بحسبان"),                    # 3: ZAMM 55:5
            (0.07, "والنجم والشجر يسجدان"),                   # 4: ZAMM 55:6
            (0.07, "يدع الله لمن حمده"),                      # 5: bozuk semiallah ("لمن حمده") → ARA + bekleme
            (0.0, ""),                                        # 6: secde
            (0.08, "الحمد لله رب العالمين"),                  # 7: rekat basi Fatiha → FATIHA
        ],
    },
    # ============ Senaryo 10: belirsiz aday + pencere disinda ayirt edici kelime ============
    {
        "description": "Belirsiz aday (113:1 / 114:1) sonrası 'الناس' ile tek parçada Nas kilidi",
        "chunks": [
            (0.07, "قل أعوذ برب"),                            # 0: 113:1 / 114:1 fark 0 → aday
            (0.07, "قل أعوذ برب الناس"),                      # 1: aday penceresi 113:1 ~91 ama tum Kuran 114:1 + "الناس" → kilit
            (0.07, "ملك الناس"),                              # 2: ZAMM 114:2
        ],
    },
    # ============ Senaryo 11: ilahi belirsizligi kilit vermez, Felak tek parcada ============
    {
        "description": "İlahi 'يا رب العالمين' (fark 0) aday kalır, Felak ayırt edici kelimeyle tek parçada",
        "chunks": [
            (0.07, "يا رب العالمين"),                         # 0: 1:2 / 5:28 fark 0, ayirt edici kelime yok → aday
            (0.07, "قل أعوذ برب الفلق"),                      # 1: 113:1 fark 8.6 + "الفلق" → tek parcada kilit
            (0.07, "من شر ما خلق"),                           # 2: ZAMM 113:2
        ],
    },
    # ============ Senaryo 12: kamette kelime-i sehadet + zikir, uzayan Fatiha beklemesi (cuma #3) ============
    {
        "description": "Kamet 'محمد رسول الله' → kamet, zikirler beklemeyi uzatır, 'والحمد لله' Fatiha",
        "chunks": [
            (0.07, "محمد رسول الله"),                         # 0: kilit yok → kamet (48:29 degil), bekleme 12'ye
            (0.07, "لا إله إلا الله"),                        # 1: zikir → bos, bekleme 13'e
            (0.0, ""), (0.0, ""), (0.0, ""), (0.0, ""),       # 2-5
            (0.07, "المصدر كتاب"),                            # 6: uydurma → too_short
            (0.0, ""), (0.0, ""), (0.0, ""),                  # 7-9
            (0.07, "إن شاء الله"),                            # 10: zikir → bos, bekleme 22'ye
            (0.0, ""), (0.0, ""), (0.0, ""), (0.0, ""), (0.0, ""),  # 11-15
            (0.07, "والحمد لله رب العالمين"),                 # 16: beklemede Fatiha → FATIHA (beklemesiz 6:45 aday)
            (0.07, "الرحمن الرحيم مالك يوم الدين"),           # 17: FATIHA 1:3-4
        ],
    },
    # ============ Senaryo 13: iki surenin acilisi ayni → gecis adayi ============
    {
        "description": "Fatiha sonu 'قل أعوذ برب' (113:1 / 114:1 aynı) gecis adayi, 'ملك الناس' Nas",
        "chunks": [
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 0: Fatiha hizli kilit
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 1
            (0.07, "اهدنا الصراط المستقيم"),                  # 2
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 3
            (0.07, "قل أعوذ برب"),                            # 4: dogal gecis yerine gecis adayi (113:1 / 114:1)
            (0.07, "ملك الناس"),                              # 5: 114:2 (tek yerde gecen ifade) → ZAMM Nas
            (0.07, "إله الناس من شر الوسواس الخناس"),         # 6: 114:3-4
        ],
    },
    # ============ Senaryo 14: hatimle teravih, 2. rekat kalinan yerden devam ============
    {
        "description": "Hatim: Rahman 55:1-13, rukû, Fatiha, 'رب المشرقين والمغرب' → 55:17 (73:9 degil)",
        "chunks": [
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 0
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 1
            (0.07, "اهدنا الصراط المستقيم"),                  # 2
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 3
            (0.07, "الرحمن علم القرآن خلق الإنسان"),          # 4: Rahman 55:1-3
            (0.07, "علمه البيان الشمس والقمر بحسبان"),        # 5
            (0.07, "والنجم والشجر يسجدان والسماء رفعها"),     # 6
            (0.07, "ووضع الميزان ألا تطغوا في الميزان"),      # 7
            (0.07, "وأقيموا الوزن بالقسط ولا تخسروا الميزان"),  # 8
            (0.07, "والأرض وضعها للأنام فيها فاكهة"),         # 9
            (0.07, "والنخل ذات الأكمام والحب ذو العصف والريحان"),  # 10
            (0.07, "فبأي آلاء ربكما تكذبان"),                 # 11: 55:13
            (0.0, ""), (0.0, ""),                             # 12-13
            (0.07, "سمع الله لمن حمده"),                      # 14: rukû → ARA
            (0.0, ""), (0.0, ""), (0.0, ""), (0.0, ""),       # 15-18: secde
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 19: 2. rekat Fatiha
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 20
            (0.07, "اهدنا الصراط المستقيم"),                  # 21
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 22
            (0.07, "رب المشرقين والمغرب"),                    # 23: hatim devami 55:17 (tum Kuran'da 73:9 91.5 / 55:17 91.0)
            (0.07, "مرج البحرين يلتقيان"),                    # 24: 55:19
        ],
    },
    # ============ Senaryo 15: bozuk semiallah kamet kelimesi iceriyor ============
    {
        "description": "Semiallah 'سمع الله لنا محمدا' rukû (kamet degil), 2. rekat Fatiha hemen",
        "chunks": [
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 0
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 1
            (0.07, "اهدنا الصراط المستقيم"),                  # 2
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 3
            (0.07, "قل هو الله أحد الله الصمد"),              # 4: Ihlas
            (0.07, "لم يلد ولم يولد ولم يكن له كفوا أحد"),    # 5
            (0.07, "سمع الله لنا محمدا"),                     # 6: rukû → ARA ("محمدا" kamet kelimesi ama once semiallah)
            (0.0, ""), (0.0, ""),                             # 7-8: secde
            (0.07, "سمع الله من حمداً"),                      # 9: aksam kaydindaki bozuk semiallah → rukû
            (0.0, ""),                                        # 10
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 11: 2. rekat Fatiha
        ],
    },
    # ============ Senaryo 16: 2. rekatta mushaf sirasiyla sonraki sure ============
    {
        "description": "1. rekat Felak, 2. rekat 'قل أعوذ برب' → 114:1 (devam penceresi sonraki sureye tasar)",
        "chunks": [
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 0
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 1
            (0.07, "اهدنا الصراط المستقيم"),                  # 2
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 3
            (0.07, "قل أعوذ برب الفلق من شر ما خلق"),         # 4: 113:1-2
            (0.07, "ومن شر غاسق إذا وقب ومن شر النفاثات في العقد"),  # 5
            (0.07, "ومن شر حاسد إذا حسد"),                   # 6: 113:5
            (0.07, "سمع الله لمن حمده"),                      # 7: rukû
            (0.0, ""), (0.0, ""),                             # 8-9
            (0.07, "الحمد لله رب العالمين الرحمن الرحيم"),    # 10: 2. rekat
            (0.07, "مالك يوم الدين إياك نعبد وإياك نستعين"),  # 11
            (0.07, "اهدنا الصراط المستقيم"),                  # 12
            (0.07, "صراط الذين أنعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 13
            (0.07, "قل أعوذ برب"),                            # 14: 113:1 / 114:1 esit → devam penceresi 114:1
            (0.07, "ملك الناس إله الناس"),                    # 15: 114:2-3
        ],
    },
    # ============ Senaryo 17: ezan sonu zikri, ders girisi uydurmasi, belirsiz aday ============
    {
        "description": "Ezan sonu 'الله أكبر X' / 'إله إلا الله' zikir, ders girisi uydurmasi cikar, belirsiz aday 113:1",
        "chunks": [
            (0.07, "الله أكبر الناس"),                        # 0: zikir → bos (eskiden 9:72 adayi, sonra kilit)
            (0.07, "الله أكبر لا"),                           # 1: zikir → bos
            (0.07, "إله إلا الله"),                           # 2: zikir → bos
            (0.0, ""),                                        # 3
            (0.07, "تفسير سورة الأعراف الدرس قل أعوذ برب"),   # 4: ders girisi cikar → "قل أعوذ برب" belirsiz aday
            (0.07, "ملك الناس إله الناس"),                    # 5: 114 kilit (aday penceresi disi, tum Kuran)
            (0.07, "نهاية الدرس من شر الوسواس الخناس"),       # 6: ders girisi cikar → 114:4
        ],
    },
    # ============ Senaryo 18: kamet basi tekbir + tevhid (yatsi 19.10) ============
    {
        "description": "Kamet: tekbir + tekbir + tevhid → kamet (eskiden 'أشهد أن ... محمد'ye kadar 24 sn); tekbirden 3 parca "
                       "sonra tevhid kamet degil (fark: kamet beklemesinde Fatiha disi aday olmaz)",
        "chunks": [
            (0.03, "الله اغبر"),                              # 0: tekbir → too_short
            (0.0, ""),                                        # 1
            (0.0, ""),                                        # 2
            (0.035, "لا اله الا الله"),                       # 3: tekbirden 3 parca sonra → zikir (kamet degil)
            (0.07, "قل أعوذ برب"),                            # 4: bekleme yok → aday (belirsiz 113:1 / 114:1)
            (0.03, "الله اغبر"),                              # 5: tekbir
            (0.03, "الله اغبر"),                              # 6: tekbir
            (0.035, "لا اله الا الله"),                       # 7: tekbir + tevhid → KAMET (bekleme)
            (0.07, "قل أعوذ برب"),                            # 8: kamet beklemesi: sadece Fatiha → aday yok
            (0.023, "بسم الله الرحمن الرحيم أشهد أن سيدنا محمد"),  # 9: kamet
            (0.021, "الله أكبر الله أكبر"),                    # 10: tekbir → too_short
            (0.024, "لا اله الا الله"),                       # 11: kamet sonu tevhid — bekleme var → zikir
            (0.022, "الحمد لله رب العالمين"),                  # 12: Fatiha (bekleme)
        ],
    },
    # ============ Senaryo 19: Felak "برب الفلاح" kamet degil (yatsi 19.10 vaazi, sabit parca) ============
    {
        "description": "Felak bozuk basi 'أعوذ برب الفلاح' kamet sayilmaz (eskiden sifirla + Fatiha beklemesi, Felak kilitsiz)",
        "chunks": [
            (0.03, "أعوذ برب الفلاح"),                         # 0: kamet degil → hizalanir (113:1)
            (0.03, "من شر ماخلق ومن شر غاشق إذا عرف"),        # 1: Felak 113:2-3
            (0.03, "غاصق إذا وقب ومن شر النفاثات في الرقد"),   # 2: Felak 113:3-4
            (0.03, "في العقد ومن شر حاسد إذا حاسد"),          # 3: Felak 113:4-5
        ],
    },
    # ============ Senaryo 20: yatsi #2 (20.10) — kayip kilitte kamet, rukûda kisa zayif eslesme ============
    {
        "description": "Namaz oncesi Saffat kilidi → 7 parca sessiz (kilit kayip) → tekbir ×2 + tevhid KAMET (eskiden ZAMM'da "
                       "zikir sayilmiyordu); Taha 20:111 → 3 bos parca → 'لم يعد' (semiallah) devam sayilmaz, 3+ kelimelik "
                       "gercek devam kabul",
        "chunks": [
            (0.1, "سبحان ربك رب العزة عما يصفون"),             # 0: 37:180 aday
            (0.1, "وسلام على المرسلين والحمد لله رب العالمين"),  # 1: dogrulandi → ZAMM
            (0.0, ""), (0.0, ""), (0.0, ""), (0.0, ""),         # 2-5: sessiz
            (0.0, ""), (0.0, ""), (0.0, ""),                    # 6-8: sessiz (kayip 7 → kilit kayip)
            (0.1, "الله اغبر"),                                  # 9: tekbir
            (0.1, "الله اغبر"),                                  # 10: tekbir
            (0.12, "شهود لا الهَ الاّ الله"),                    # 11: kilit kayip + tekbir + tevhid → KAMET
            (0.1, "الحمد لله رب العالمين"),                      # 12: Fatiha (bekleme)
            (0.1, "الرحمن الرحيم مالك يوم الدين"),               # 13
            (0.1, "اياك نعبد واياك نستعين اهدنا الصراط المستقيم"),  # 14
            (0.1, "صراط الذين انعمت عليهم غير المغضوب عليهم ولا الضالين"),  # 15: Fatiha sonu
            (0.1, "يعلم ما بين ايديهم وما خلفهم ولا يحيطون به علما"),  # 16: Taha 20:110 dogal gecis
            (0.1, "وعنت الوجوه للحي القيوم وقد خاب من حمل ظلما"),   # 17: 20:111
            (0.1, ""), (0.1, ""), (0.1, ""),                    # 18-20: rukû (ASR bos)
            (0.1, "لم يعد"),                                     # 21: semiallah bozuk → devam sayilmaz
            (0.1, "ومن يعمل من الصالحات وهو مؤمن"),             # 22: gercek devam 20:112 (3+ kelime)
        ],
    },
    # ============ Senaryo 21: sabah 21.10 — Isra kilidi kayip, 2. rekat Fatiha'si uydurmayla ayni parcada ============
    {
        "description": "Isra 17:13-15 → 13 parca okuma yok (semiallah duyulmadi, ZAMM kilidi kayip) → 'والحمد لله رب العالمين شركة "
                       "الهدى للخدمات التقنية': uydurma ifadesi cikarilir, kilidi kaybolmus zamm ARA gibi → Fatiha 1:2 (eskiden "
                       "parca bos, sonraki parca 6:45 belirsiz adayi)",
        "chunks": [
            (0.016, "وَالسِنينَ وَالْحِسَابِ"),
            (0.015, "وكل شيء فصيل"),
            (0.023, "وكل انسان"),
            (0.025, "ألزمناه طائره"),
            (0.017, "في عمره ونخرج له يوم"),                            # 4: kilit Isra 17:13
            (0.018, "يوم القيامة كتابًا يَلْقَاهُ مَعَهُ"),
            (0.017, "منشورا اقرأ"),
            (0.017, "كفى بنفسي"),
            (0.018, "اليوم عليك حسي"),
            (0.019, "من اهتدى فإنما"),
            (0.013, "إنما يهتدي لنفسي"),
            (0.016, "ومن ضل فإنما يضل"),
            (0.018, "ولا تزر وازرة"),
            (0.018, ""),
            (0.02, "وَمَا كُنَّا مُعَذِّبِينَ حَتَّى"),
            (0.021, "حتى نبعث رسول الله"),                              # 15: 17:15 son okuma
            (0.04, ""),
            (0.027, ""),
            (0.009, ""),
            (0.024, ""),
            (0.032, ""),
            (0.038, "شركة التابعين"),                                   # 21: uydurma (kalan yok) → bos
            (0.026, ""),
            (0.003, ""),
            (0.035, "شكرا"),
            (0.027, "المصدر كتاب"),
            (0.003, ""),
            (0.013, ""),
            (0.032, "الله أكبر"),                                       # 28: tekbir
            (0.019, "الحمد لله"),                                       # 29: ZAMM'da kilit kayip (13 parca)
            (0.024, "والحمد لله رب العالمين شركة الهدى للخدمات التقنية"),  # 30: uydurma cikarilir → ZAMM kilidi kayip = ARA gibi: Fatiha 1:2 (eskiden bos, 6:45 belirsiz aday)
            (0.019, "مالك يوم الدين إياك نعين"),                        # 31: Fatiha 1:4
            (0.018, "نعبد وإياك نستعين اهدنا الصراط"),
            (0.016, "صراطا مستقيما"),
            (0.018, "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيهِم"),
            (0.02, "غير الموظوب"),
        ],
    },
    # ============ Senaryo 22: asr 21.10 — Hasr 59:22-24 + "صدق الله العظيم" + Saffat 37:180-181 ============
    {
        "description": "Istiaze + besmele → Hasr 59:22 belirsiz adaylar (2:163 / 6:73) dogrulanmaz, 59:23 kilit; kilit kayip "
                       "→ 59:24 kalinan yerden devam; 'صدق الله العظيم' kilidi bitirir → Saffat 37:180 birikmis metinle",
        "chunks": [
            (0.014, ""),
            (0.023, "أعوذ بالله السميع العليم"),
            (0.019, "أعوذ من الشيطان الرجيم"),
            (0.046, ""),
            (0.019, "من الشيطان الرجيم بسم الله الرحمن الرحيم"),
            (0.022, "بسم الله الرحمن الرحيم"),
            (0.026, "الله"),
            (0.033, "لا اله الا هو"),                                   # 7: aday 2:163 (belirsiz)
            (0.023, "عالم الغيب والشاهد"),                              # 8: 6:73 belirsiz aday
            (0.021, "هو الرحمن الرحيم"),                                # 9: tum Kuran 100 (2:163 / 59:22) — 6:73 penceresi 71.3 dogrulamaz
            (0.03, "والله الذي"),
            (0.043, "شركة"),
            (0.024, "لا إله هو الملك القدس"),                           # 12: aday 59:23
            (0.02, "السلام"),                                           # 13: kilit 59:23 (birikmis metin)
            (0.02, "أين العزيز الجفار"),
            (0.03, "جبار المتكبر سبحان الله"),
            (0.031, ""),
            (0.018, ""),
            (0.041, ""),
            (0.025, ""),
            (0.026, "شركة الهدى للخدمات التقنية"),                      # 20: uydurma (kalan yok)
            (0.029, ""),
            (0.033, "السماوات والأرض"),
            (0.024, "الا وهو العزيز"),                                  # 23: kilit kayip: kalinan yerden devam 59:24 (eskiden 3:6 belirsiz aday)
            (0.016, ""),
            (0.024, "صدق الله العظيم"),                                 # 25: tilavet sonu: kilit / adaylar biter (eskiden ekranda 59:24 / 69:33 adayi)
            (0.028, "سبحان ربي"),
            (0.019, "رب العزة عنك"),                                    # 27: Saffat 37:180 (birikmis metin)
            (0.024, "وسلام على الناس"),                                 # 28: 37:181
            (0.022, ""),
            (0.032, ""),
            (0.025, ""),
        ],
    },
    # ============ Senaryo 23: sabah 21.10 sabit parca — zamm sonunda kisa "Fatiha" ifadesi ============
    {
        "description": "2. rekat Fatiha → Adiyat; sure sonu 'إن ربهم بهم' ASR'de 'إن رب العالمين' (3 kelime): zamm sonundan "
                       "Fatiha'ya dogal gecis en az 4 kelime ister (eskiden 1:2 kilidi, rekat sayaci 3. rekat saydi)",
        "chunks": [
            (0.023, "الحمد لله رب العالمين الرحمن الرحيم"),             # 0: 2. rekat Fatiha (hizli kilit)
            (0.02, "بسم الله الرحمن الرحيم مالك يوم الدين إياك نعبد"),
            (0.018, "نعبد وإيَّاك نستعين اهدنا الصراط"),
            (0.017, "الصراط المستقيم صراط الذين أنعمه"),
            (0.019, "لما أَنْعَمْتَ عَلَيْهِمْ غير المَوْضُولِ عَنْهُمْ"),
            (0.026, "ولا الضال"),
            (0.019, "شركة التابعين"),                                   # 6: uydurma (kalan yok) → bos
            (0.027, "وَالْعاداتِ ضَوعًا فالمورِيَات"),                  # 7: Fatiha sonu → Adiyat 100:1 dogal gecis
            (0.022, "فالموريات قدحاً فالمغيرات سبعة"),
            (0.021, "سبحا فأثرنه نَقْعًا"),
            (0.024, "فَوَسَطْنَ بِهِ جَمْعًا"),
            (0.019, "إِنَّ الْإِنْسَانَ لِرَبِّهِ لَكَنُودٌ"),
            (0.018, "وإنه على الأرض"),
            (0.02, "وعلى ذلك لشهيد"),
            (0.018, "وإنه لحب الخير لشديد"),
            (0.022, "أفلا يعلم إذا بعثر ما"),
            (0.022, "وحصل ما في الصدور"),                               # 16: 100:10 (sure sonuna 1 ayet)
            (0.015, "إن رب العالمين"),                                  # 17: Adiyat sonu ASR'de bozuk: 3 kelimeyle Fatiha'ya dogal gecis yok (eskiden 1:2)
            (0.013, "إنهم يومئذ لخبير"),                                # 18: 100:11
            (0.014, "الله أكبر"),                                       # 19: tekbir
        ],
    },
    # ============ Senaryo 24: asr 21.10 hibrit (yeni kodun parca sinirlari) — belirsiz aday geriye dogrulanmaz ============
    {
        "description": "Hasr 59:22 'هو الرحمن الرحيم' 2:163 sonu / 59:22 sonu esit (belirsiz aday 2:163); 59:23 basi 'لا اله الا هو' "
                       "2:163'te adayin gerisine oturur → dogrulama sayilmaz (eskiden 2:163 kilidi), 59:23 kilit; 'صدق الله "
                       "العظيم' → Saffat 37:180 belirsiz aday ileride biten parcayla dogrulanir",
        "chunks": [
            (0.014, ""),
            (0.023, "أعوذ بالله السميع العليم"),
            (0.019, "أعوذ من الشيطان الرجيم"),
            (0.046, ""),
            (0.019, "من الشيطان الرجيم بسم الله الرحمن الرحيم"),
            (0.022, "بسم الله الرحمن الرحيم"),
            (0.026, "الله"),
            (0.033, "لا اله الا هو"),                                   # 7: belirsiz aday 2:163
            (0.023, "عالم الغيب والشاهد"),
            (0.021, "هو الرحمن الرحيم"),                                # 9: belirsiz aday 2:163 (59:22 ile esit, eslesme ayet sonunda)
            (0.03, "والله الذي"),
            (0.037, "لا اله الا هو"),                                   # 11: 2:163'te adayin gerisine oturuyor → dogrulamaz (eskiden 2:163 kilidi)
            (0.021, "السلام الملك القدوس السلام"),                      # 12: aday 59:23
            (0.02, "اللَّه المؤمن المؤيمن العزيز الجبار"),              # 13: kilit 59:23
            (0.02, "جفار مجهد"),
            (0.034, "سبحان الله"),
            (0.019, "شركة الهدى للإنسان"),
            (0.041, ""),
            (0.025, ""),
            (0.026, "شركة الهدى للخدمات التقنية"),
            (0.029, ""),
            (0.033, "السماوات والأرض"),                                 # 21: kalinan yerden devam 59:24
            (0.024, "الا وهو العزيز"),
            (0.016, ""),
            (0.024, "صدق الله العظيم"),                                 # 24: tilavet sonu: kilit biter
            (0.027, "الظلم العظيم سبحان ربك"),                          # 25: belirsiz aday 37:180
            (0.019, "رب العزة عمَّا يَصِفُونَ"),                        # 26: ileride biter → dogrular, kilit 37:180
            (0.022, "وسلام علي المرسلين"),
            (0.03, "والحمد لله رب"),
            (0.025, ""),
        ],
    },
    # ============ Senaryo 25: yatsi #3 (21.10) — 2. rekat 1. rekatin kaldigi yerden devam + geri duzeltme ============
    {
        "description": "Fatiha → Enbiya 21:11-23 → rukû / secde → Fatiha → 21:24 (ASR 'أم اتطعتم من دونه': devam penceresi 72.2, "
                       "Yunus 10:38 77.3 yerine devam) → bozuk parca 21:25'e erken → 'يلمون الحق فهم معرضون' ayni surede bir "
                       "ayet geri 21:24 (eskiden 21:27 / 21:28'e kayip 21:25'e donuyordu)",
        "chunks": [
            (0.0623, "الحمد لله رب العالمين"),                          # 0: Fatiha hizli kilit
            (0.0676, "موسوعة النابلسي للعلوم الإسلامية الرحمن الرحيم"),
            (0.0648, "مَالِكِ يَوْمِ الدِّينِ"),
            (0.0625, "إياك نعبد وإيانا"),
            (0.0423, "وإياك نستعين"),
            (0.0638, "اهدنا الصراط المستقيم صراط اللّيم"),
            (0.0674, "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ"),
            (0.0714, "غير المغضوب عليه"),
            (0.0691, "شركة الهدى للخدمات التقنية"),
            (0.058, "المريض"),
            (0.0499, ""),
            (0.0514, "وَكَمْ قَصَمْنَا"),                               # 11: Fatiha sonu → Enbiya 21:11
            (0.0632, "قرية كَانَتْ ظَالِمَةً وَأَنْشَأْنَا بِهَا"),
            (0.0626, "و جنبنا بعدها قوما آخرين فلما أخرجها."),
            (0.0701, "عفو بأسمائنا إلا"),
            (0.0666, "لا يعوض"),
            (0.0746, "لا تركضوا ورجعوا"),
            (0.067, "إلى ما أُترف فيه ومساكنه"),
            (0.0513, "لعلك"),
            (0.0593, "قالوا يا ويلنا"),
            (0.0643, "يَا وَيْلَنَا إِنَّا كُنا"),
            (0.0674, "فَمَا زَالَتْ تِلْكَ دَعْوَاهُمْ حَتَّى جَعَلْنَا"),
            (0.0602, "جَمَصِيدًا قَائِدِينَ وما خلق"),
            (0.0739, "مَا خَلَقْنَا السماءَ والأرضَ وَمَا بَيْنَهُمَا"),
            (0.0661, "لو أردنا أن نتعمق"),
            (0.0691, "اتخذ مغوًا لاتّخذناهُ مِن لدُنّا"),
            (0.0658, "إن كنا فاعلين"),
            (0.0629, "بل نقذف بالحق على البلاد"),
            (0.0679, "عَلَى الْبَاطِلِ فَيَدْمَغُهُ فَإِذَا هُوَ زَاهِقٌ"),
            (0.0605, "ذَلِكَ وَلَكُمُ الْوَيْلُ مِمَّا تَصِفُونَ الأنعام ستون"),
            (0.0711, "وَلَهُمْ مَنْ فِي السَّمَاءِ"),
            (0.0634, "السماوات والأرض"),
            (0.0756, "وَمَنْ عِنْدَهُ لَا يَسْتَكْبِرُونَ"),
            (0.0664, "عَنْ عِبَادَتِهِ وَلا يَسْتَكْسِرُونَ"),
            (0.0688, "يُسَبِّحُونَ اللَّيْلَ وَالنَّهَارَ لَا يَفْتَرُونَ"),
            (0.0696, "أَمِ اتَّخَذُوا آلِهَةً مِّنَ الْيَوْمِ"),
            (0.0537, "مِّن الْأَرْضِ هُم يَنشِرُونَ"),
            (0.0699, "لَوْ كَانَ فِي مَائِحٌ إِل"),
            (0.0736, "الا الله لفسدتا فسبحان الله ربي"),
            (0.0681, "رب العرش عادة"),
            (0.0741, ""),
            (0.0651, "لا يسمع ما يفعل"),                                # 41: 21:23 (1. rekat sonu)
            (0.0507, "لعلهم"),
            (0.0737, "المصدر كتاب"),
            (0.0085, ""),
            (0.0534, "جميعاً"),
            (0.0657, "المصدر كتاب"),
            (0.0436, ""),
            (0.0617, ""),
            (0.0613, ""),
            (0.0101, ""),
            (0.0564, ""),
            (0.0418, ""),
            (0.0677, "الحمد لله رب العالمين"),                          # 53: 2. rekat Fatiha (kilidi kaybolmus zamm)
            (0.0675, "الرحمن الرحيم مالك يوم الدين"),
            (0.0702, "إياك نعبد وإياك نستعين"),
            (0.0688, "المصدر"),
            (0.0696, "اهْدِنَا الصِّرَاطَ الْمُسْتَقِيمَ"),
            (0.0569, "صِرَاطَ الَّذِينَ أَنْعَمْتَ عَلَيْهِمْ"),
            (0.0584, "غير المغضوب عليهم"),
            (0.0676, "شركة الهدى للخدمات التقنية"),
            (0.0576, ""),
            (0.0651, "أَمِ اتَّطَعْتُم مِّن دُونِهِ"),                  # 62: devam onceligi: 21:24 72.2 (eskiden Yunus 10:38 77.3 dogal gecis)
            (0.0706, "آلِهَة قُلْ هَاتُوا قُرْآنَكُمْ"),                # 63: 21:24
            (0.0725, "هذا ذِكرُ من معي وذِكر مني"),
            (0.0756, "بدأ يدع لنا"),                                    # 65: bozuk parca 21:25'e 65
            (0.0646, "يلمون الحق فهم معرضون"),                          # 66: geri duzeltme: 21:24 84.5 (eskiden pencere 21:25-27 → 21:27 50.2)
            (0.0592, "وما حسدنا"),                                      # 67: 21:25 (eskiden 21:28)
            (0.0667, "مِن قَبلِكَ مِنَّا نُوحِي إِلَيْكَ"),
            (0.072, "إلي أنه لا إلهَ إِلَّا هُو"),
            (0.0664, "اتخذ الرحمن"),
            (0.0726, "ولداه بل عباد مؤمن"),
            (0.0712, "بِالْقَوْلِ وَالصَّدْرِ"),
            (0.0761, "وَبِالْقَوْلِ وَهُم بِأَمْرِهِ يَعْمَلُونَ"),
        ],
    },

    # ============ Senaryo 26: aksam 22.10 (APK #114 telefon parcalari) — Kafirun acilisi, secde uydurmasi, Nasr ============
    {
        "description": "kamet → Fatiha → 'قل يا أيها الرحم' (7:158 / 62:6 / 109:1 esit: sure acilisi onceligi 109:1) → Kafirun → "
                       "secde basinda uydurma 'الحمد لله رب العالمين' (erken Fatiha: gecis adayi, dogrulanmaz) → 2. rekat Fatiha → "
                       "'فما جاء النصر' 15:61'e dogal gecis → 'والله والفتح' taze gecis duzeltmesi 110:1 → 110:2-3 → 'استمع الله' rukû",
        "chunks": [
            (0.0263, "الصلاة حيها"),
            (0.0279, "قد قام الصلاة"),                      # 1: kamet
            (0.0243, "الله تاب الله أكثر"),
            (0.0242, "لا الهَ الاّ الله"),
            (0.0242, ""),
            (0.0263, ""),
            (0.0249, "الحمد لله رب العالمين"),              # 6: Fatiha hizli kilit
            (0.022, "بسم الله الرحمن الرحيم"),
            (0.0168, "إياك نعبد وإياك"),
            (0.0189, "وَإِيَّاكَ نَسْتَعِينُ اهدِنَا الصِّرَاطَ الْمُسْتَقِيمَ"),
            (0.019, "مستقيم. صراط"),
            (0.0261, "إذا أنت عليهم"),
            (0.0199, "غير الموبوع عليه منه"),
            (0.037, "الضال"),
            (0.023, "المليار"),
            (0.0298, "قل يا أيها الرحم"),                   # 15: Fatiha sonu: 7:158 / 62:6 / 109:1 esit 78.6 → sure acilisi onceligi 109:1 (eskiden 7:158)
            (0.0243, "الْكَافِرُونَ لَا أَعْبُدُ مَا تَعْبُدُونَ"),
            (0.0248, ""),
            (0.0259, ""),
            (0.028, "وَلَا أَنَا عَابِدٌ"),
            (0.0223, ""),
            (0.0238, "ما أعبد"),
            (0.0123, "لهم دينهم وليهم"),
            (0.0069, "شكراً لبس"),
            (0.0198, ""),
            (0.0074, ""),
            (0.0194, ""),
            (0.0396, "الحمد لله رب العالمين"),              # 27: secde basi uydurmasi: erken Fatiha (Kafirun'dan 5 parca) → gecis adayi (eskiden 'yeni rekat')
            (0.0911, ""),
            (0.0106, ""),
            (0.0258, ""),
            (0.0286, ""),
            (0.0042, ""),
            (0.0231, "المصدر"),
            (0.0231, ""),
            (0.0206, "الحمد لله رب العالمين"),              # 35: 2. rekat Fatiha (ARA'da yoklama)
            (0.0184, "بس الرحمن الرحيم مالك يوم الدين إياك"),
            (0.0197, "إياك نعبد وإياك نستعد"),
            (0.0175, "اهدنا الصراط المستقيم"),
            (0.0196, "صراط الذين أنعمت عليهم"),
            (0.0194, "أنعمت عليهم غير الموغول عليهم"),
            (0.0361, "ولا الضال"),
            (0.0178, "شركة التابعين"),
            (0.0291, "فما جاء النصر"),                      # 43: Fatiha sonu: 15:61 90.5 (110:1 75.0) dogal gecis
            (0.0215, "والله والفتح"),                       # 44: taze gecis duzeltmesi: 110:1 86.7, gecis parcasi 110 acilisina 75 (eskiden 15:61 penceresinde 48.4)
            (0.0187, "يدخلون في"),                          # 45: 110:2 (eskiden 15:62-63)
            (0.0199, "أفواج"),
            (0.018, "فَسَبِّحْ بِحَمْدِ رَبِّكَ وَاسْتَغْفِرْ"),
            (0.0197, "وَاسْتَغْفِرْ إِنَّهُ كَانَ تَوَّابًا"),
            (0.0216, "الله أكبر"),
            (0.0112, ""),
            (0.0347, "استمع الله"),                         # 51: semiallah 'استمع الله' → rukû
            (0.0524, "شركة التابعين"),
            (0.0635, ""),
        ],
    },

    # ============ Senaryo 27: yatsi 22.10 (APK #114 telefon parcalari) — Fatiha onceligi, kalip ifade, namazda tilavet sonu ============
    {
        "description": "kamet onceki oturumda: 'والحمد لله رب العالمين' belirsiz → Fatiha → Enbiya 21:71-79 → kuyruk 'الحمد لله' "
                       "(kalip ifade, 21:80-81'e gecmez) → rukû tekbiri → secdede 'صدق الله العظيم' (tekbirden sonra: kilit bitmez) → "
                       "2. rekat Fatiha → 21:80-87 (devam) → semiallah 'لمَن حميده' rukû",
        "chunks": [
            (0.0418, ""),
            (0.0688, "والحمد لله رب العالمين نهاية الدرس"), # 1: 'والحمد' 6:45 / 37:182 esit (belirsiz) → Fatiha 1:2 (bekleme yokken Fatiha onceligi)
            (0.062, "الرحمن الرحيم مالك يوم الدين"),
            (0.067, "إياك ندعو"),
            (0.0652, "المصدر"),
            (0.0537, "اهدنا الصراط المستقيم"),
            (0.0673, "المستقيم صراط الذين انعمت عليهم"),
            (0.0627, "ولا يقل"),
            (0.0818, "شركة الهدى للخدمات التقنية"),
            (0.0643, ""),
            (0.0448, "وجرى"),
            (0.0788, "وَنَجَّيْنَاهُ وَلُوطًا إِلَى الْأَرْضِ الَّتِي بَارَكْنَا"), # 11: Enbiya 21:71
            (0.0749, "وبارك لنا فيها للعالمين وغيرها."),
            (0.0804, "وَوَهَبْنَا لَهُ إِسْحَاقَ وَيَعْقُوبَ نَافِلًا"),
            (0.0686, "وكل جعلنا"),
            (0.0655, "وجعلناهم أئمة يهدون"),
            (0.0743, "وَأَوْحَيْنَا إِلَيْهِمْ"),
            (0.0705, "فِعْلِ الْخَيْرَاتِ وَإِقَامِ الصَّلاَةِ وَإِيتَاءِ الزَّكاة"),
            (0.0735, "وَإِقَامِ الصَّلَاةِ وَإِيتَارِ الزَّكَاةِ"),
            (0.0648, "وَإِنَّ لِلزَّكَاةِ وَكَانُوا لَنَا عَابِدِينَ"),
            (0.0802, "وَلُوطًا آتَيْنَاهُ حُكْمًا وَعِلْمًا"),
            (0.0775, "وَعِلْمًا وَنَجَّيْنَاهُ مِنَ الْقَرْيَةِ الَّتِي كَانَ"),
            (0.0731, "التي كانت تعمائر"),
            (0.0753, "إِنَّهُمْ كَانُوا قَوْمَ سَوْءٍ فَاسِقِينَ"),
            (0.0695, ""),
            (0.0644, "إنه من الصالحين"),
            (0.0648, "ودوحي نادت من قبل"),
            (0.0725, ""),
            (0.0736, "ونصرنا"),
            (0.078, "وَنَصَرْنَاهُ مِنَ الْقَوْمِ الَّذِينَ كَذَّبُوا بِآيَاتِنَا"),
            (0.0732, "إِنَّهُمْ كَانُوا قَوْمَ سَوْءٍ"),
            (0.0686, "فَأَغْرَقْنَاهُ أَجْمَعِينَ"),
            (0.0771, "وَدَاوُودَ وَسُلَيْمَانَ إِذْ يَحْكُمَانِ فِي الْحَمِيمِ"),
            (0.0717, "ألف الحث دفشت فيه ودم القمر"),
            (0.0679, "وكُنَّا لحكمهم شارِبين"),
            (0.0711, "فَفَتَّرْنَاهَا سُلَيْمَانَ وَكُلَّ مَكَانٍ"),
            (0.0764, "وَكُلًّا آتَيْنَاهُ حُكْمًا وَعِلْمًا وَسَفَّرَ"),
            (0.0773, "وَسَخَّرْنَا مَعَ دَاوُودَ الْجِبَالَ يُسَبِّحْنَ وَالطَّيْر"),
            (0.0742, "والطيق وكن لنا فاعلين"),
            (0.0574, "الحمد لله"),                          # 39: 21:79 sonu kuyruk uydurmasi 'الحمد لله' 21:80-81'e 62 → kalip ifade, kayip parca
            (0.0667, "الله اغبر"),                          # 40: rukû tekbiri
            (0.0308, ""),
            (0.0608, "يعنى"),
            (0.0592, ""),
            (0.0634, ""),
            (0.0144, ""),
            (0.069, "صدق الله العظيم"),                     # 46: secdede uydurma 'صدق الله العظيم': tekbirden sonra → kilit bitmez
            (0.0525, "أعوذ بالله"),
            (0.0259, ""),
            (0.0635, ""),
            (0.0188, ""),
            (0.0589, "الحمد لله رب العالمين"),              # 51: 2. rekat Fatiha
            (0.0677, "الرحمن الرحيم مالك يوم الدين"),
            (0.0731, "إياك نعبد وإياك نستعين"),
            (0.0663, "وإياك نستعين اهدنا الصراط"),
            (0.0651, "اهدِ الصراط المستقيم صراط الذين أنعمت"),
            (0.0673, "أنعمت عليهم غير المغضوب عليهم"),
            (0.0699, "ومتوب عليه ولا ض"),
            (0.0687, "الضالين"),
            (0.0567, ""),
            (0.0505, "وعلَّمناه صنعة"),                     # 60: 2. rekat devam 21:80
            (0.0642, "سِلَّة لِتُحْصِنَكُم مِّن بَأْسِكُمْ"),
            (0.0639, "فَهَلْ أَنتُم شَاكِرُونَ"),
            (0.0632, "وَلِسُلَيْمَانَ الرِّيحَ عَاصِفَةً تَجْرِي بِيَ"),
            (0.0641, "الي بارت بارت"),
            (0.0637, "وَلِسُلَيْمَانَ الرِّياسَ"),
            (0.0669, "عاصفة تجري بي"),
            (0.0665, "وَالَّتِي بَارَكْنَا فِيهَا لِلعَالَمِينَ"),
            (0.0662, "وَمِنَ الشياطِينِ مَنْ يَغُوصُونَ لَهُ"),
            (0.0687, "ويصلون له ويعملون عَمَلًا دُونَ ذَلِكَ"),
            (0.0692, "وكنا نحن حافظين"),
            (0.075, "وَأَيُّوبَ إِذْ نَادَى رَبَّهُ أَنِّي مَسَّنِيَ"),
            (0.0726, "مسني الضر وأنت أرحم الراحمين"),
            (0.0673, "فَاسْتَجَبْنَا لَهُ فَكَشَفْنَا مَا بِهِ"),
            (0.0704, "مِن ضُرٍّ وَآتَيْنَاهُ أَهْلَهُ"),
            (0.0585, "لهم ومِثلَهم معهم رحمةً من عندنا"),
            (0.0688, "ومثلهم رحمةً من عندنا وذكار"),
            (0.0607, "وذِكران للعابدين"),
            (0.0697, "وإسماعيل وإدريس وذا الكفل"),
            (0.0674, "كُلٌّ مِّنَ الصَّابِرِينَ وَأَدْخَلْنَا"),
            (0.0727, "وأدخلناهم في رحمتنا إنهم من المحسنين"),
            (0.0907, "الصالحين"),
            (0.0803, "وظنني إذ ناحاً غاضباً فض"),
            (0.0651, "فَظَنَّ أَن لَّن نَّقْدِرَ عَلَيْهِ"),
            (0.0696, "إِلا هدى في الظلمات الا اله"),
            (0.0697, "لا اله الا سبحانك إني"),
            (0.0555, "لي الغالبين"),
            (0.0714, "الله أكبر"),
            (0.0196, ""),
            (0.0453, ""),
            (0.0661, "لمَن حميده"),                         # 90: semiallah 'لمَن حميده' → rukû
            (0.0561, ""),
            (0.0282, ""),
        ],
    },
]


# Fixture telefondaki varsayilan ayarlarla uretilir: Kotlin test runner StateMachine/Aligner varsayilanlarini
# kullanir (minConfidenceFirstLock = 70, Aligner.defaultWindowSlack = 2; eval ile ayni). Eskiden 90 / ±5 ile
# uretiliyordu — senaryolar bu farka duyarsiz oldugu icin fark edilmemisti.
FIXTURE_FIRST_LOCK = 70
FIXTURE_WINDOW_SLACK = 2


def main():
    global MIN_CONFIDENCE_FIRST_LOCK, align_transcription
    MIN_CONFIDENCE_FIRST_LOCK = FIXTURE_FIRST_LOCK
    _align = align_transcription
    align_transcription = lambda *a, **k: _align(*a, **{**k, "window_slack": FIXTURE_WINDOW_SLACK})
    print("Korpus yukleniyor...")
    corpus = QuranCorpus.load()
    ayah_to_range, surah_counts, vocab = build_aux_maps(corpus)

    fixture = {
        "version": 1,
        "description": "StateMachine test fixture — Python referans davranisi",
        "scenarios": [],
    }

    for s_idx, scenario in enumerate(SCENARIOS):
        print(f"\n--- Senaryo {s_idx}: {scenario['description']} ---")
        state = SessionState()
        chunk_results = []

        for i, (rms, text) in enumerate(scenario["chunks"]):
            r = process_chunk_simulated(rms, text, i, state,
                                          corpus, ayah_to_range, surah_counts, vocab)
            chunk_results.append({
                "chunk_index": r["chunk_index"],
                "input": {"rms": rms, "text": text},
                "expected": {
                    "state_before": r["state_before"],
                    "state": r["state"],
                    "status": r["status"],
                    "score": r.get("score"),
                    "word_count": r.get("word_count"),
                    "match_start": r.get("match_start"),
                    "match_end": r.get("match_end"),
                    "first_surah": r.get("first_surah"),
                    "first_ayah": r.get("first_ayah"),
                    "last_surah": r.get("last_surah"),
                    "last_ayah": r.get("last_ayah"),
                    "pending_surah": r.get("pending_surah"),
                    "pending_ayah": r.get("pending_ayah"),
                    "ambiguous": bool(r.get("ambiguous")),
                    "gap_filled": r.get("gap_filled", 0),
                },
            })
            verses_str = ""
            if r.get("verses"):
                verses_str = " | " + ", ".join(f"{s}:{a}" for s, a in r["verses"])
            score_str = f" score={r.get('score')}" if r.get('score') is not None else ""
            wc_str = f" wc={r.get('word_count')}" if r.get('word_count') is not None else ""
            print(f"  [{i}] {r['state_before']:8s} → {r['state']:8s}  {r['status']:14s}{score_str}{wc_str}{verses_str}")

        fixture["scenarios"].append({
            "description": scenario["description"],
            "chunks": chunk_results,
            "final_state": {
                "state": state.state.value,
                "last_surah": state.last_surah,
                "last_ayah": state.last_ayah,
                "lost_chunks": state.lost_chunks,
                "total_chunks": state.total_chunks,
                "matched_chunks": state.matched_chunks,
                "transitions": state.state_transitions,
            },
        })

    repo_root = Path(__file__).resolve().parent.parent
    assets_root = Path(os.environ.get("TILAVET_ASSETS_DIR", repo_root / "android-assets-staged"))
    output = assets_root / "asr" / "state_machine_fixture.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    total_chunks = sum(len(s["chunks"]) for s in fixture["scenarios"])
    print(f"Toplam {len(fixture['scenarios'])} senaryo, {total_chunks} chunk")
    print(f"Kaydedildi: {output}")
    print(f"Boyut: {output.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
