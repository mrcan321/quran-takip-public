#!/usr/bin/env python3
"""
Offline pipeline degerlendirmesi — telefondaki zinciri PC'de/CI'da taklit eder:

  WAV → 16kHz → ChunkBuilder (5sn + 1sn overlap) → ONNX ASR (APK'daki model, CTC veya RNNT)
      → align_transcription (preferred_range yok = BEKLEME, windowSlack=2) → score_transcription

Amac: skor/esik ve decoder kararlarini telefona APK kurmadan vermek.
Iki olcum:
  1. Chunk bazinda skor (BEKLEME modu — her chunk bagimsiz)
  2. Namaz simulasyonu: kaydi bastan sona state machine'den gecir (pending dogrulama, kilit,
     preferred range) → ILK KILIT kacinci saniyede ve dogru sureye mi? (hesaplama suresi haric,
     sadece algoritmik gecikme; telefonda aligner suresi bunun ustune eklenir)
Karsilastirilan zincirler:
  eski-app : eski chunk (overlap hatasi) + Uthmani korpus + CTC   (build #1-2)
  guncel   : duzeltilmis chunk + imla'i korpus + CTC              (build #3+)
  rnnt     : duzeltilmis chunk + imla'i korpus + RNNT greedy      (build #6-10)
  rnnt-hibrit : RNNT + BEKLEME/ARA'da sabit 5 sn, kilitliyken duraklamada kes (build #14+)

Calistirma:
  python scripts/eval_pipeline.py --model-dir android-assets-staged/asr
  python scripts/eval_pipeline.py --model-dir model-out --audio data/ihlas.wav

Bagimliliklar: onnxruntime sentencepiece soundfile soxr rapidfuzz numpy
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aligner import QuranCorpus, align_transcription, normalize_arabic  # noqa: E402
from onnx_asr import OnnxAsr  # noqa: E402
from vad_chunker import chunks_pause  # noqa: E402  — telefondaki ChunkBuilder (duraklamada kes)
import build_state_machine_fixture as sm  # noqa: E402  — referans state machine (Kotlin ile birebir)

# Simulasyonlarda ayni parca metni (ayni pencereyle) defalarca hizalaniyor (ilk kilit + takip + iki zincir + tum Kuran
# / ikinci yer aramalari) — sonuc bellekte tutulur (saf fonksiyon). Eskiden eval 45 dk sinirina takiliyordu.
_sm_align = sm.align_transcription
_align_memo = {}


def _memo_align(transcription, corpus, window_slack=5, preferred_range=None, preferred_bonus=8.0,
                min_score_threshold=40.0, exclude_range=None):
    key = (id(corpus), transcription, window_slack, tuple(preferred_range) if preferred_range else None,
           preferred_bonus, min_score_threshold, tuple(exclude_range) if exclude_range is not None else None)
    if key not in _align_memo:
        _align_memo[key] = _sm_align(transcription, corpus, window_slack=window_slack, preferred_range=preferred_range,
                                     preferred_bonus=preferred_bonus, min_score_threshold=min_score_threshold,
                                     exclude_range=exclude_range)
    return _align_memo[key]


sm.align_transcription = _memo_align

REPO_ROOT = Path(__file__).resolve().parent.parent
SR = 16000
CHUNK = 5 * SR
OVERLAP = 1 * SR
FRAME = 1600                 # AudioRecorder: 100ms frame
MIN_RMS_ENERGY = 0.005       # StateMachine ile ayni
MIN_WORD_COUNT_COLD = 3
WINDOW_SLACK = 2             # Aligner.defaultWindowSlack (telefon varsayilani)
FIRST_LOCK_THRESHOLD = 70    # StateMachine.minConfidenceFirstLock (telefon varsayilani)
CHUNK_SEC = CHUNK / SR
PROC_SEC = 1.0                # telefonda parca bitisinden ekrana: ASR ~0.8 sn + hizalama (log, APK #8)

# Dosya adi → beklenen sure (None = Kuran degil, eslesme OLMAMALI)
EXPECTED = {
    "Kevser.wav": 108, "Nas.wav": 114, "nas3.wav": 114, "felak.wav": 113,
    "fil.wav": 105, "ihlas.wav": 112, "ayetel_kursi.wav": 2, "test_fatiha.wav": 1, "asr.wav": 103,
    "test_turkce.wav": None, "test_arapca_sohbet.wav": None, "test_sessizlik.wav": None,
    # server/recordings — icerige gore etiketlendi (RNNT transkriptlerinden)
    "session_1777003510.wav": 1, "session_1777003559.wav": 1,
    "session_1777003574.wav": 103, "session_1777005364.wav": 103, "session_1777006513.wav": 103,
    "session_1777005126.wav": 55, "session_1777006567.wav": 55, "session_1777009737.wav": 55,
    "session_1777024461.wav": 94, "session_1777027487.wav": 94,   # 27487: araya tefsir konusmasi da giriyor
    "session_1777027721.wav": None,   # ilahi ("يا رب العالمين صل على طه الأمين") — Kuran degil, kilit olmamali
    "session_1777005218.wav": None, "session_1777005276.wav": None, "session_1777005325.wav": None,
    "session_1777023877.wav": None,   # neredeyse bos / anlasilmaz
    # Cok sureli kayitlar: tek sure yok, dogruluk TIMELINE ile olculur
    "telefon_rahman_maun_kevser_felak.wav": "coklu",
    "sentetik_namaz_fatiha_ihlas.wav": "coklu", "sentetik_namaz_fatiha_ayetelkursi.wav": "coklu",
    # GERCEK NAMAZ (cami, 27.09 aksam, telefon kaydi): 1. rekat Fatiha + Zilzal, 2. rekat Fatiha + Kafirun,
    # 3. rekat sessiz, selam
    "namaz_aksam_fatiha_zilzal_fatiha_kafirun.wav": "coklu",
    # Telefon (APK #15, 27.09): Fatiha → Maun (107) → Kureys (106). APK'da "الرحمن الرحيم" 1:1'e (geri) gitti,
    # sonda bozuk parca ("شعور وما لا") ekrani 22:12 adayina kaydirdi
    "telefon_fatiha_maun_kureys.wav": "coklu",
    # GERCEK NAMAZ #2 (cami, 01.10 aksam, APK #19, telefon cebinde): 1. rekat Fatiha + Ra'd 13:38-43,
    # 2. rekat Fatiha + Ibrahim 14:1-3, 3. rekat sessiz, selam, namaz sonu dua. 151-163 sn telefon titresimi (cagri).
    "namaz_aksam2_fatiha_rad_fatiha_ibrahim.wav": "coklu",
    # GERCEK CUMA NAMAZI (cami, 02.10, APK #22): KAMET (6-56 sn) → tekbir → Fatiha → Enbiya 21:10x → rukû/secde →
    # Fatiha → Insirah (94) → secde/oturus → selam → yuksek sesli dua. APK kameti Kuran sandi (4:101 kilit).
    "namaz_cuma_kamet_fatiha_enbiya_fatiha_insirah.wav": "coklu",
    "namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav": "coklu",
    # Cuma #3 (16.10, camide telefon, APK #33): salavat/kamet 0-45 (ASR: "محمد رسول الله" → 48:29 yanlis kilit) →
    # iftitah 72 → Fatiha 83-110 → Felak 113 (118-141) → rukû/secde (semiallah 154) → Fatiha 193-219 → Nas 114
    # (~227-249, "قل أعوذ" ASR'de yok) → semiallah 263 → secde/oturus → selam 345-356 → dua
    "namaz_cuma3_kamet_fatiha_felak_fatiha_nas.wav": "coklu",
    # Yatsi (19.10, camide telefon, APK #51, 20.8 dk): vaaz (Turkce, hoparlor; ASR "المصدر كتاب" uyduruyor) icinde
    # okunan Fatiha (9-34), Felak (333-350), Fatiha (423-451) → kamet 685-735 → Fatiha → A'raf 7:51-53 → rukû/secde →
    # Fatiha → A'raf 7:54-55 → 3-4. rekat sessiz (semiallah 1075, 1135) → selam 1217/1224 → dua 1237
    "namaz_yatsi_kamet_fatiha_araf_fatiha_araf.wav": "coklu",
    "namaz_yatsi2_kamet_fatiha_taha_fatiha_taha.wav": "coklu",
    # Sabah (21.10, camide telefon, 9.5 dk): kamet 0-50 → iftitah 52 → Fatiha 63.7 → Isra 17:8-15 (101-263) →
    # rukû / secde (semiallah ASR'de yok) → Fatiha 320 → Adiyat 100 (355-412) → semiallah 426 → secde / oturus → selam
    # 516-530 → istigfar ("...الذي لا إله إلا هو الحي القيوم"), "اللهم أنت السلام", salavat, tesbih
    "namaz_sabah_kamet_fatiha_isra_fatiha_adiyat.wav": "coklu",
    # Ayni sabah namazdan sonra (21.10): istiaze x2 + besmele → Hasr 59:22-24 (31-106) → "صدق الله العظيم" → Saffat
    # 37:180-182 (114-130)
    "tilavet_hasr_22_24_namaz_sonu.wav": "coklu",
}

# Takip simulasyonu icin zaman cizelgesi: [(baslangic_sn, sure | None), ...] — sure gecisleri.
# Tek sureli etiketli kayitlar otomatik [(0, sure)] sayilir.
TIMELINE = {
    # Telefon (APK #8, 27.09): 55:1-2 → sus → 107 (Maun) → 108 (Kevser, 108:3 uc kez) → 113 (Felak) → sus
    # 55:1-3 ("خلقي" 10.0 sn'de), sonra 18. sn'ye kadar sessizlik (ses kesilince metin kaldirma olcumu)
    "telefon_rahman_maun_kevser_felak.wav": [(0, 55), (10, None), (18, 107), (56, 108), (85, 113), (110, None)],
    # Sentetik namaz: session_1777003510 (1:2-5) + test_fatiha (1:6-7) + 1.5 sn sessizlik + zamm (16 kHz)
    # Fatiha → zamm gecisi: eskiden FATIHA penceresi disi 6 chunk (~30 sn) aranmiyordu
    "sentetik_namaz_fatiha_ihlas.wav": [(0, 1), (29.7, 112)],
    "sentetik_namaz_fatiha_ayetelkursi.wav": [(0, 1), (29.7, 2)],
    # Gercek aksam namazi (cami, cemaat arasindan telefon, 27.09): tekbir → Fatiha → Zilzal → rukû/secde →
    # Fatiha → Kafirun → rukû/secde/tahiyyat, 3. rekat sessiz → selam (~356 sn). Sinirlar RNNT transkripti +
    # enerji zarfindan. ASR tekbir/gurultude Kuran disi metin uyduruyor ("شركة الهدى للخدمات", "لا تنسوا مشاركة").
    "namaz_aksam_fatiha_zilzal_fatiha_kafirun.wav": [(0, None), (18, 1), (56, 99), (101, None), (138, 1),
                                                     (175, 109), (210, None)],
    # Telefon oturumu (APK #15 log'undaki parca sureleri + transkript): besmele+Fatiha, besmele+Maun (~40 sn),
    # Kureys (~84 sn), sessizlik (~108 sn)
    "telefon_fatiha_maun_kureys.wav": [(0, 1), (40, 107), (84, 106), (108, None)],
    # Gercek aksam namazi #2 (01.10): tekbir (1 sn) → Fatiha (~11 sn) → amin korosu (46-53) → Ra'd 13:38-43
    # (54-151) → titresim 4×1.5 sn 200 Hz (151-163, cagri) + rukû tekbiri → rukû/secde → Fatiha (199) →
    # Ibrahim 14:1-3 (238-295) → rukû/secde/oturus, 3. rekat sessiz → selam (446) → "اللهم انت السلام..." duasi.
    # Sinirlar enerji zarfi + telefon log'undaki RNNT metninden.
    "namaz_aksam2_fatiha_rad_fatiha_ibrahim.wav": [(0, None), (11, 1), (54, 13), (151, None), (199, 1),
                                                   (238, 14), (295, None)],
    # Cuma (02.10, camide telefon): kamet 6-56 (None — kilit/aday olmamali), tekbir ~70, Fatiha 82-115,
    # Enbiya 21:102-104 (117-166; 21:101 okunmadi), rukû/secde, Fatiha 215-248, Insirah 94 (249-284),
    # secde/oturus, selam 366-378, dua 380-398. Sinirlar enerji zarfi + RNNT transkriptinden (CI eval).
    "namaz_cuma_kamet_fatiha_enbiya_fatiha_insirah.wav": [(0, None), (82, 1), (117, 21), (166, None), (215, 1),
                                                          (249, 94), (284, None)],
    # Cuma #2 (09.10, camide telefon, APK #27): kamet 0-35 → iftitah 48.4 → Fatiha 60.3-88 (1:1 sessiz) → Tekasur 102
    # (96.1 "الهاكم", 99.2 102:2, 103.2 102:3, ... 131.4 102:8, 138 son) → rukû tekbiri 141.4 → rukû/secde → Fatiha
    # 189.5-216 → Asr 103 (223.8 "والعصر", 226.1 103:2, 231.4 103:3, 242.6 son) → rukû tekbiri 245.4 → selam 335.2.
    # Sinirlar CI kelime zamanli transkriptinden (eval.yml words) + enerji zarfi.
    "namaz_cuma2_kamet_fatiha_tekasur_fatiha_asr.wav": [(0, None), (60, 1), (96, 102), (141, None), (189, 1),
                                                        (223, 103), (245, None)],
    # Cuma #3 (16.10): sinirlar CI kelime zamanli transkriptinden (eval.yml words): "الحمد" 82.96, "قل" 118.56,
    # rukû tekbiri 143.9, "الحمد" 192.96, "برب" 227.84 (imam ~226'da basladi), "والناس" 248.8
    "namaz_cuma3_kamet_fatiha_felak_fatiha_nas.wav": [(0, None), (82, 1), (118, 113), (143, None), (192, 1),
                                                      (226, 114), (250, None)],
    # Yatsi (19.10): sinirlar CI kelime zamanli transkriptinden — vaaz icindeki okumalar "الحمد" 9.2, "أعوذ" 333.3,
    # "الحمد" 423.1; kamet "الله" 684.9; "الحمد" 744.4, "الذين اتخذوا" 776.9 (7:51), "يفترون" 849.4 (7:53 sonu),
    # "الحمد" 893, "إن ربكم" 930.6 (7:54), "المعتدين" 975 (7:55 sonu), rukû tekbiri 980.9
    "namaz_yatsi_kamet_fatiha_araf_fatiha_araf.wav": [(0, None), (9, 1), (35, None), (333, 113), (351, None),
                                                      (423, 1), (451, None), (744, 1), (776, 7), (855, None),
                                                      (892, 1), (930, 7), (980, None)],
    # yatsi #2 (20.10, APK #102): namazdan once biri Ihlas'i 3 kez (62-65 arasi 3 sn duraklama + besmele) ve Saffat
    # 37:180-182 okuyor; kamet 165-247; Fatiha 274; Taha 20:100-111 (321-436); semiallah ~451; Fatiha 487; Taha 20:112-115
    # (527-586); 3-4. rekat sessiz; selam 820-830 + dua. Fatiha → zamm arasi diger kayitlardaki gibi Fatiha bolumunde.
    "namaz_yatsi2_kamet_fatiha_taha_fatiha_taha.wav": [(0, None), (20, 112), (62, None), (67, 112), (95, 37),
                                                       (121, None), (274, 1), (321, 20), (437, None), (487, 1),
                                                       (527, 20), (587, None)],
    # sabah 21.10 (kelime zamanli transkript): Fatiha "الحمد" 63.7, "عسى" 101.0 (17:8), "رسول الله" 262.6 (17:15 sonu),
    # 2. Fatiha "الحمد" 320.1, "والعاديات" 355.2, "لخبير" 411.6
    "namaz_sabah_kamet_fatiha_isra_fatiha_adiyat.wav": [(0, None), (63.5, 1), (100.5, 17), (265, None), (319.8, 1),
                                                        (354.8, 100), (414, None)],
    # Hasr 59:22 "هو الله" ~31 ("الذي" 33.1), 59:24 sonu "الحكيم" 105.7, "صدق الله العظيم" 110-112, "سبحان ربك" 114.2
    "tilavet_hasr_22_24_namaz_sonu.wav": [(0, None), (31, 59), (108, None), (113.8, 37), (131, None)],
}


# ============================================================
# Ses + chunk
# ============================================================
def load_audio(path: Path) -> np.ndarray:
    import soundfile as sf
    audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if sr != SR:
        import soxr
        audio = soxr.resample(audio, sr, SR, quality="HQ")
    return audio.astype(np.float32)


def transcribe_rnnt_ctc(asr, audio: np.ndarray):
    """RNNT metni + son token zamani + AYNI encoder ciktisindan CTC metni (tani icin, bedava: logprobs zaten
    hesaplaniyor). Gercek namaz #2'de RNNT konusma olan parcada bos dondu (13:38 basi) — CTC ne diyor?"""
    from onnx_asr import FRAME_SEC
    has_len = "enc_len" in asr.output_names
    out = asr.encode(audio, ["enc_proj", "logprobs"] + (["enc_len"] if has_len else []))
    enc_proj, logprobs = out[0][0], out[1][0]
    if has_len:
        n = int(out[2][0])
        enc_proj, logprobs = enc_proj[:n], logprobs[:n]
    frames = []
    text = asr.decode(asr.rnnt_ids(enc_proj, frames))
    t_tok = (frames[-1] + 1) * FRAME_SEC if frames and text else None
    return text, t_tok, asr.decode(asr.ctc_ids(logprobs))


def word_timeline(asr, audio: np.ndarray, win: float = 12.0, hop: float = 6.0):
    """Kelime zamanli RNNT transkripti (TIMELINE cikarmak / gecikme olcmek icin): win sn pencere, hop sn
    kaydirma; her pencerenin ortasindaki hop sn'lik dilimdeki kelimeler alinir (pencere kenarinda kesik kelime
    yok). Kelime zamani = ilk token'inin frame'i (80 ms). → [(sn, kelime)]"""
    from onnx_asr import FRAME_SEC
    has_len = "enc_len" in asr.output_names
    dur = len(audio) / SR
    margin = (win - hop) / 2
    words, t = [], 0.0
    while t < dur:
        seg = audio[int(t * SR):int(min(dur, t + win) * SR)]
        if len(seg) < SR // 2:
            break
        out = asr.encode(seg, ["enc_proj"] + (["enc_len"] if has_len else []))
        enc = out[0][0][:int(out[1][0])] if has_len else out[0][0]
        frames = []
        ids = asr.rnnt_ids(enc, frames)
        groups = []   # [(ilk_frame, [id...])] — SentencePiece "▁" kelime basi
        for k, fr in zip(ids, frames):
            if asr.sp.id_to_piece(k).startswith("\u2581") or not groups:
                groups.append((fr, [k]))
            else:
                groups[-1][1].append(k)
        lo = t + (margin if t > 0 else 0.0)
        hi = t + win - margin if t + win < dur else dur + 1.0
        for fr, g in groups:
            wt = t + fr * FRAME_SEC
            w = asr.decode(g)
            if lo <= wt < hi and w:
                words.append((round(wt, 2), w))
        t += hop
    return words


def chunks_legacy(audio: np.ndarray):
    """ChunkBuilder.kt / app.py'nin eski hali (build #1-2, birebir)."""
    tail = np.zeros(0, dtype=np.float32)
    buf, buf_n = [], 0
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        buf.append(audio[i:i + FRAME]); buf_n += FRAME
        if buf_n < CHUNK:
            continue
        combined = np.concatenate([tail] + buf)
        yield combined[:min(len(combined), CHUNK + OVERLAP)], (i + FRAME) / SR, False
        tail = combined[CHUNK - OVERLAP:CHUNK] if len(combined) >= CHUNK else np.zeros(0, dtype=np.float32)
        buf, buf_n = [], 0


def chunks_fixed(audio: np.ndarray):
    """Duzeltilmis: her chunk = onceki chunk'in son 1sn'si + yeni 5sn (kesintisiz)."""
    tail = np.zeros(0, dtype=np.float32)
    buf, buf_n = [], 0
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        buf.append(audio[i:i + FRAME]); buf_n += FRAME
        if buf_n < CHUNK:
            continue
        combined = np.concatenate([tail] + buf)
        yield combined, (i + FRAME) / SR, False
        tail = combined[max(0, len(combined) - OVERLAP):]
        buf, buf_n = [], 0


class HybridChunker:
    """Telefondaki parcalayici (APK #14+): BEKLEME/ARA'da sabit 5 sn, kilitliyken (FATIHA/ZAMM) duraklamada kes.

    Parca sinirlari state'e bagli oldugu icin state machine ASR ile ayni dongude calisir (feed):
    her parcanin sonucu sonraki cercevelerin modunu belirler — telefonda da state machine sonucu
    ChunkBuilder.pauseCutEnabled'i gunceller. Ayar/sira simulasyonlarla ayni oldugundan (ilk kilit
    esigi 70, windowSlack 2, ayni parca indeksi) simulate_* bu transkriptlerde ayni state izini verir."""

    LOCKED = ("FATIHA", "ZAMM")

    def __init__(self, corpus):
        self.corpus = corpus
        self.aux = sm.build_aux_maps(corpus)
        self.state = sm.SessionState()
        self.idx = 0

    def __call__(self, audio: np.ndarray):
        self.state = sm.SessionState()
        self.idx = 0
        return chunks_pause(audio, pause_enabled=lambda: self._locked())

    def _locked(self) -> bool:
        st = self.state.state
        return (st.value if hasattr(st, "value") else str(st)) in self.LOCKED

    def feed(self, rms: float, text: str):
        sm.MIN_CONFIDENCE_FIRST_LOCK = FIRST_LOCK_THRESHOLD
        orig_align = sm.align_transcription
        sm.align_transcription = lambda *a, **k: orig_align(*a, **{**k, "window_slack": WINDOW_SLACK})
        try:
            ayah_to_range, surah_counts, vocab = self.aux
            sm.process_chunk_simulated(rms, text, self.idx, self.state, self.corpus, ayah_to_range, surah_counts, vocab)
        finally:
            sm.align_transcription = orig_align
        self.idx += 1


# ============================================================
# Skor (server/app.py score_transcription ile ayni)
# ============================================================
def score_transcription(tokens, match, vocab) -> float:
    fuzzy = match.score if match else 0.0
    cov = sum(1 for t in tokens if t in vocab) / len(tokens)
    uniq = len(set(tokens)) / len(tokens)
    mc = c = 1
    for i in range(1, len(tokens)):
        c = c + 1 if tokens[i] == tokens[i - 1] else 1
        mc = max(mc, c)
    score = fuzzy * cov ** 0.5 * uniq ** 0.3
    if mc >= 3:
        score *= 0.3
    if cov < 0.3:
        score *= 0.5
    return round(score, 1)


def evaluate_chunk(text: str, rms: float, corpus: QuranCorpus):
    if rms < MIN_RMS_ENERGY:
        return {"status": "silent"}
    tokens = [t for t in (normalize_arabic(x) for x in text.split()) if t]
    if not tokens:
        return {"status": "empty"}
    if len(tokens) < MIN_WORD_COUNT_COLD:
        return {"status": "too_short"}
    match = align_transcription(text, corpus, window_slack=WINDOW_SLACK)
    score = score_transcription(tokens, match, corpus.vocab)
    res = {"status": "scored", "score": score, "fuzzy": round(match.score, 1) if match else 0.0,
           "cov": round(sum(1 for t in tokens if t in corpus.vocab) / len(tokens), 2)}
    if match:
        w = corpus.words[match.start_word_idx]
        res["surah"], res["ayah"] = w.surah, w.ayah
    return res


def fmt(res) -> str:
    if res["status"] != "scored":
        return f"{res['status']:>9}"
    loc = f"{res.get('surah', '-')}:{res.get('ayah', '-')}"
    return f"{res['score']:5.1f} (f{res['fuzzy']:.0f} v{res['cov']:.2f} @{loc})"


# ============================================================
# Namaz simulasyonu — ilk kilit suresi
# ============================================================
def simulate_sessions(files, configs, transcripts, corpora):
    """
    Her kaydi referans state machine'den gecir. Telefonla ayni ayarlar: ilk kilit esigi 70,
    windowSlack 2. Chunk k'nin sonucu en erken (k+1)*5 sn'de gelir (chunk 5 sn dolunca islenir).
    """
    sm.MIN_CONFIDENCE_FIRST_LOCK = FIRST_LOCK_THRESHOLD
    sim_names = [name for name, _, co, _ in configs if co == "imlai"]
    aux = {}
    lines = ["", "### Namaz simulasyonu — ilk kilit (sn, sure:ayet) [hesaplama suresi haric]", "",
             "| kayit | beklenen | " + " | ".join(sim_names) + " |",
             "|---|---|" + "---|" * len(sim_names)]
    stats = {n: {"ok": 0, "wrong": 0, "none": 0, "times": []} for n in sim_names}
    for f in files:
        cells = []
        exp = EXPECTED.get(f.name, "?")
        for name in sim_names:
            co_name = next(co for n, _, co, _ in configs if n == name)
            corpus = corpora[co_name]
            if co_name not in aux:
                aux[co_name] = sm.build_aux_maps(corpus)
            ayah_to_range, surah_counts, vocab = aux[co_name]
            orig_align = sm.align_transcription
            sm.align_transcription = lambda *a, **k: orig_align(*a, **{**k, "window_slack": WINDOW_SLACK})
            trace = []
            try:
                state = sm.SessionState()
                first = None
                chunks = transcripts[name].get(f.name, [])
                for idx, c in enumerate(chunks):
                    r = sm.process_chunk_simulated(c[0], c[1], idx, state, corpus, ayah_to_range, surah_counts, vocab)
                    trace.append(trace_cell(idx, r))
                    if r["status"] == "matched" and first is None:
                        first = (idx, r["first_surah"], r["first_ayah"], chunk_time(c, idx))
                        break
            finally:
                sm.align_transcription = orig_align
            # Chunk chunk iz (log): kilit neden gecikti / hic olmadi — P=aday, M=kilit, L=dusuk, S=kisa, -=sessiz/bos
            print(f"[sim {name:6s}] {f.name}: {' '.join(trace)}", flush=True)
            if first is None:
                cells.append("kilit yok")
                if isinstance(exp, int):
                    stats[name]["none"] += 1
                continue
            idx, su, ay, t = first
            mark = ""
            if isinstance(exp, int):
                ok = su == exp
                mark = " ✓" if ok else " ✗"
                stats[name]["ok" if ok else "wrong"] += 1
                if ok:
                    stats[name]["times"].append(t)
            elif exp is None:
                mark = " ✗ (Kuran degil)"
            cells.append(f"{t:.0f} sn · {su}:{ay}{mark}")
        lines.append(f"| {f.name} | {exp} | " + " | ".join(cells) + " |")
    lines += ["", "| zincir | dogru kilit | yanlis kilit | kilit yok | dogru kilit medyan sn |", "|---|---|---|---|---|"]
    for name in sim_names:
        st = stats[name]
        med = statistics.median(st["times"]) if st["times"] else 0
        lines.append(f"| {name} | {st['ok']} | {st['wrong']} | {st['none']} | {med:.0f} |")
    return lines


def trace_cell(idx, r):
    st = r["status"]
    sc = r.get("score")
    sc = f"({sc:.0f})" if isinstance(sc, (int, float)) else ""
    if st == "matched":
        return f"{idx}:M{r.get('first_surah')}:{r.get('first_ayah')}{sc}"
    if st == "pending":
        return f"{idx}:P{r.get('pending_surah', r.get('first_surah'))}:{r.get('pending_ayah', r.get('first_ayah'))}{sc}"
    if st == "low_confidence":
        return f"{idx}:L{sc}"
    if st == "too_short":
        return f"{idx}:S"
    return f"{idx}:-"


def chunk_time(c, idx):
    """Parcanin bitis zamani (sn): TRJSON'da varsa oradan, yoksa sabit 5 sn izgarasi."""
    return c[2] if len(c) > 2 and c[2] is not None else (idx + 1) * CHUNK_SEC


def timeline_for(fn):
    if fn in TIMELINE:
        return TIMELINE[fn]
    exp = EXPECTED.get(fn)
    if isinstance(exp, int):
        return [(0, exp)]
    if fn in EXPECTED and exp is None:
        return [(0, None)]
    return None


def track_file(sm_mod, chunks, corpus, aux, timeline):
    """Kaydi bastan sona state machine'den gecir; her sure bolumu icin kilit/aday gecikmesi,
    yanlis kilitli chunk sayisi ve ekranin sonraki ayete on-kaydirmasi (MainViewModel kurali).
    Zamanlar parca bitisi (sabit parcada (k+1)*5 sn)."""
    ayah_to_range, surah_counts, vocab = aux
    state = sm_mod.SessionState()
    results = []
    for idx, c in enumerate(chunks):
        r = sm_mod.process_chunk_simulated(c[0], c[1], idx, state, corpus, ayah_to_range, surah_counts, vocab)
        results.append(r)
    times = [chunk_time(c, k) for k, c in enumerate(chunks)]

    def seg_at(t):
        cur = prev = None
        for st, su in timeline:
            if t >= st:
                prev, cur = cur, su
        return cur, prev

    segs = []
    for i, (st, su) in enumerate(timeline):
        if su is None:
            continue
        end = timeline[i + 1][0] if i + 1 < len(timeline) else 1e9
        lock = cand = None
        for k, r in enumerate(results):
            t_res = times[k]
            if t_res < st or t_res > end + 3 * CHUNK_SEC:
                continue
            if r["status"] == "matched" and su in (r.get("first_surah"), r.get("last_surah")) and lock is None:
                lock = t_res - st
            # Aday = ekranda gorunen: kilitliyken gelen gecis adayi (jump, APK #16+) ve belirsiz aday (ambiguous) UI'da
            # gosterilmez
            shown = r["status"] == "matched" or (r["status"] == "pending" and not r.get("jump") and not r.get("ambiguous"))
            if shown and cand is None and su in (r.get("first_surah"), r.get("last_surah"), r.get("pending_surah")):
                cand = t_res - st
        segs.append((st, su, lock, cand))
    wrong = 0
    for k, r in enumerate(results):
        if r["status"] != "matched":
            continue
        cur, prev = seg_at(times[k] - 1.0)
        if r.get("first_surah") not in (cur, prev) and r.get("last_surah") not in (cur, prev):
            wrong += 1
    # Ekranda gorunen yanlis aday ("ADAY": BEKLEME / kilit kaybi adayi; kilitliyken gecis adayi gosterilmez).
    # Cuma kameti 37:35 / 4:28 / 4:103 adaylari boyleydi. Belirsiz aday (ikinci yer cok yakin) da gosterilmez.
    wrong_cand = 0
    for k, r in enumerate(results):
        if r["status"] == "pending" and not r.get("jump") and not r.get("ambiguous"):
            if r.get("pending_surah") not in seg_at(times[k] - 1.0):
                wrong_cand += 1

    # On-kaydirma (MainViewModel ile ayni kural): kilitli eslesmenin son kelimesi ayetin son kelimesiyse
    # (duraklama kesiminde sondan bir onceki de sayilir) ekran sonraki ayete gecer. Isabet: bir sonraki
    # eslesme o ayette (ya da ilerisinde) mi, yoksa ekran geri mi dondu.
    adv = {"n": 0, "ok": 0, "back": 0, "lat": [], "wrong_cand": wrong_cand}
    expect = None
    besmele = sm_mod.besmele_positions(corpus, ayah_to_range) if hasattr(sm_mod, "besmele_positions") else set()
    for k, r in enumerate(results):
        if r["status"] != "matched" or r.get("match_end") is None:
            continue
        w = corpus.words[r["match_end"]]
        s_, a_ = w.surah, w.ayah
        if expect is not None:
            if s_ == expect[0] and a_ >= expect[1]:
                adv["ok"] += 1
            elif s_ == expect[0] and a_ == expect[1] - 1:
                adv["back"] += 1
            expect = None
        if r.get("state") not in ("FATIHA", "ZAMM"):
            continue
        c = chunks[k]
        pcut = bool(c[3]) if len(c) > 3 else False
        a_start, a_last = ayah_to_range[(s_, a_)]
        shown = a_last - a_start + 1 - sum(1 for q in range(a_start, a_last + 1) if q in besmele)
        slack = 1 if (pcut and shown >= 3) else 0
        if r["match_end"] >= a_last - slack and (s_, a_ + 1) in ayah_to_range:
            adv["n"] += 1
            expect = (s_, a_ + 1)
            if len(c) > 4 and c[4] is not None:
                adv["lat"].append(times[k] + PROC_SEC - c[4])
    trace = " ".join(trace_cell(k, r) for k, r in enumerate(results))
    return segs, wrong, trace, adv


def simulate_tracking(files, configs, transcripts, corpora, sm_mod=None):
    """Takip: ilk kilit + sure gecisleri + yanlis kilit (tum kayit boyunca)."""
    sm_mod = sm_mod or sm
    sm_mod.MIN_CONFIDENCE_FIRST_LOCK = FIRST_LOCK_THRESHOLD
    sim_names = [name for name, _, co, _ in configs if co == "imlai"]
    lines = ["", "### Takip simulasyonu — sure bolumu basina kilit gecikmesi (sn) [aday] / yanlis kilitli chunk", "",
             "| kayit | " + " | ".join(sim_names) + " |", "|---|" + "---|" * len(sim_names)]
    stats = {n: {"delays": [], "cand": [], "missed": 0, "segs": 0, "wrong": 0, "wrong_cand": 0,
                 "adv": 0, "adv_ok": 0, "adv_back": 0, "adv_lat": []} for n in sim_names}
    aux = {}
    for f in files:
        tl = timeline_for(f.name)
        if tl is None:
            continue
        cells = []
        for name in sim_names:
            co_name = next(co for n, _, co, _ in configs if n == name)
            corpus = corpora[co_name]
            if co_name not in aux:
                aux[co_name] = sm_mod.build_aux_maps(corpus)
            orig_align = sm_mod.align_transcription
            sm_mod.align_transcription = lambda *a, **k: orig_align(*a, **{**k, "window_slack": WINDOW_SLACK})
            try:
                segs, wrong, trace, adv = track_file(sm_mod, transcripts[name].get(f.name, []), corpus, aux[co_name], tl)
            finally:
                sm_mod.align_transcription = orig_align
            print(f"[takip {name:6s}] {f.name}: {trace}", flush=True)
            st = stats[name]
            st["wrong"] += wrong
            st["wrong_cand"] += adv["wrong_cand"]
            st["adv"] += adv["n"]
            st["adv_ok"] += adv["ok"]
            st["adv_back"] += adv["back"]
            st["adv_lat"] += adv["lat"]
            parts = []
            for s0, su, lock, cand in segs:
                st["segs"] += 1
                if lock is None:
                    st["missed"] += 1
                    parts.append(f"{su}: kacti" + (f" [aday {cand:.0f}]" if cand is not None else ""))
                else:
                    st["delays"].append(lock)
                    if cand is not None:
                        st["cand"].append(cand)
                    parts.append(f"{su}: {lock:.0f}" + (f" [{cand:.0f}]" if cand is not None else ""))
            cells.append(", ".join(parts) + (f" · **{wrong} yanlis**" if wrong else "")
                         + (f" · {adv['wrong_cand']} yanlis aday" if adv["wrong_cand"] else ""))
        lines.append(f"| {f.name} | " + " | ".join(cells) + " |")
    lines += ["", "| zincir | bolum | kilitlenen | kacan | kilit medyan sn | aday medyan sn | yanlis kilitli chunk | "
              "ekranda yanlis aday |", "|---|---|---|---|---|---|---|---|"]
    for name in sim_names:
        st = stats[name]
        med = statistics.median(st["delays"]) if st["delays"] else 0
        cmed = statistics.median(st["cand"]) if st["cand"] else 0
        lines.append(f"| {name} | {st['segs']} | {len(st['delays'])} | {st['missed']} | {med:.0f} | {cmed:.0f} | "
                     f"{st['wrong']} | {st['wrong_cand']} |")

    # Hiz: son kelimenin duyulmasindan sonucun ekrana gelmesine (parca bitisi + ~1 sn islem - son token)
    lines += ["", "### Hiz ve on-kaydirma", "",
              "| zincir | son kelime → ekran medyan / ort sn | duraklama kesimi | sonraki ayete on-kaydirma | "
              "isabetli | geri donen | ayet sonu → sonraki ayet medyan sn |",
              "|---|---|---|---|---|---|---|"]
    for name in sim_names:
        lats, n_text, n_pause = [], 0, 0
        for chunks in transcripts[name].values():
            for c in chunks:
                if len(c) > 4 and c[4] is not None:
                    lats.append(c[2] + PROC_SEC - c[4])
                if c[1]:
                    n_text += 1
                    n_pause += bool(c[3]) if len(c) > 3 else 0
        st = stats[name]
        lat = f"{statistics.median(lats):.1f} / {statistics.mean(lats):.1f}" if lats else "-"
        judged = st["adv_ok"] + st["adv_back"]
        ok = f"{st['adv_ok']}/{judged}" if judged else "-"
        alat = f"{statistics.median(st['adv_lat']):.1f}" if st["adv_lat"] else "-"
        lines.append(f"| {name} | {lat} | %{100 * n_pause / max(1, n_text):.0f} | {st['adv']} | {ok} | "
                     f"{st['adv_back']} | {alat} |")
    return lines


# ============================================================
# Ana
# ============================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--audio", type=Path, nargs="*")
    ap.add_argument("--summary", type=Path, help="Markdown ozet dosyasi (GITHUB_STEP_SUMMARY)")
    ap.add_argument("--words", action="store_true",
                    help="Her kayit icin kelime zamanli RNNT transkripti de yaz (WORDS satirlari, TIMELINE icin)")
    ap.add_argument("--chains", default="", help="Sadece bu zincirler (virgulle: guncel,rnnt,rnnt-hibrit; bos = hepsi)")
    ap.add_argument("--trjson-out", type=Path, help="TRJSON satirlarini bu dosyaya da yaz (tests/trjson icin)")
    ap.add_argument("--stats-out", type=Path,
                    help="ASR suresi (parca basina ms, medyan / p90) json — ASR model yarisi (tests/asr_compare.py)")
    ap.add_argument("--manifest", type=Path,
                    help="Sentetik kayitlar (tests/synth): {dosya: {expected, timeline}} → EXPECTED / TIMELINE'a eklenir")
    args = ap.parse_args()
    if args.manifest:
        man = json.loads(args.manifest.read_text(encoding="utf-8"))
        for fn, m in man.get("files", {}).items():
            EXPECTED[fn] = m.get("expected", "coklu")
            if m.get("timeline"):
                TIMELINE[fn] = [(float(t), su) for t, su in m["timeline"]]

    files = args.audio or sorted((REPO_ROOT / "data").glob("*.wav")) + \
        sorted((REPO_ROOT / "server" / "recordings").glob("*.wav"))

    asr = OnnxAsr(args.model_dir)
    corpora = {"imlai": QuranCorpus.load(imlaei=True)}
    # (isim, chunker, korpus, decoder) — eski-app (build #1-2, Uthmani + hatali parca) artik olculmuyor;
    # chunks_legacy / QuranCorpus.load(imlaei=False) karsilastirma icin duruyor.
    # rnnt-vad (her yerde duraklama kesimi, APK #11-13) BEKLEME'de yanlis kilit uretti → olculmuyor;
    # chunks_pause (pause_enabled=None) ASR'siz karsilastirma icin duruyor.
    configs = [("guncel", chunks_fixed, "imlai", "ctc")]
    if asr.has_rnnt:
        configs.append(("rnnt", chunks_fixed, "imlai", "rnnt"))
        configs.append(("rnnt-hibrit", HybridChunker(corpora["imlai"]), "imlai", "rnnt"))   # APK #14+
    else:
        print("UYARI: model RNNT parcalarini icermiyor, sadece CTC karsilastirilacak")
    if args.chains:
        keep = set(args.chains.split(","))
        configs = [c for c in configs if c[0] in keep]

    results = {name: [] for name, *_ in configs}   # name → [(file, idx, res)]
    asr_ms = {name: [] for name, *_ in configs}
    # name → file → [(rms, metin, bitis_sn, duraklama, son_kelime_sn, ctc_metni)] — ctc_metni sadece RNNT zincirlerinde
    # (ayni parcanin CTC cozumu, tani icin)
    transcripts = {name: {} for name, *_ in configs}
    t0 = time.time()
    for f in files:
        audio = load_audio(f)
        print(f"\n=== {f.name} ({len(audio) / SR:.1f}s, beklenen sure: {EXPECTED.get(f.name, '?')})", flush=True)
        for name, chunker, co_name, decoder in configs:
            for idx, (chunk, t_end, pcut) in enumerate(chunker(audio)):
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                text, t_last, ctc_text = "", None, None
                if rms >= MIN_RMS_ENERGY:
                    ta = time.time()
                    if decoder == "rnnt":
                        text, t_tok, ctc_text = transcribe_rnnt_ctc(asr, chunk)
                    else:
                        text, t_tok = asr.transcribe_timed(chunk, decoder)
                    asr_ms[name].append((time.time() - ta) * 1000)
                    if t_tok is not None:
                        t_last = t_end - len(chunk) / SR + t_tok
                if hasattr(chunker, "feed"):
                    chunker.feed(rms, text)   # hibrit: sonraki parcanin modu bu sonuca bagli
                res = evaluate_chunk(text, rms, corpora[co_name])
                results[name].append((f.name, idx, res))
                transcripts[name].setdefault(f.name, []).append((rms, text, t_end, pcut, t_last, ctc_text))
                alt = f" || CTC: {ctc_text[:60]}" if ctc_text is not None and ctc_text != text else ""
                print(f"[{name:11s} {idx:2d}] {t_end:6.1f}{'p' if pcut else ' '} {fmt(res)} | {text[:80]}{alt}",
                      flush=True)
    print(f"\nSure: {time.time() - t0:.0f}s")
    if args.words and asr.has_rnnt:
        # Kelime zamanli transkript: "[kelime] 96.32 الهاكم" satirlari + WORDS json (yerelde okunur)
        for f in files:
            wl = word_timeline(asr, load_audio(f))
            print(f"\n=== kelimeler {f.name} ({len(wl)} kelime)")
            for wt, w in wl:
                print(f"[kelime] {wt:7.2f} {w}")
            print("WORDS " + json.dumps({"file": f.name, "words": wl}, ensure_ascii=False))
    # Transkriptler (rms, metin) — state machine deneyleri ASR'siz tekrar oynatilabilsin diye (log'dan alinir)
    tr_lines = []
    for name in transcripts:
        for fn, chunks in transcripts[name].items():
            tr_lines.append("TRJSON " + json.dumps({"config": name, "file": fn, "chunks": [
                [round(r, 5), t, round(te, 2), bool(pc), None if tl is None else round(tl, 2), ct]
                for r, t, te, pc, tl, ct in chunks]}, ensure_ascii=False))
            print(tr_lines[-1])
    if args.trjson_out:
        args.trjson_out.write_text("\n".join(tr_lines) + "\n", encoding="utf-8")
    if args.stats_out:
        args.stats_out.write_text(json.dumps({"files": len(files), "asr_ms": {
            name: {"n": len(v), "median": round(statistics.median(v), 1) if v else None,
                   "p90": round(sorted(v)[int(0.9 * (len(v) - 1))], 1) if v else None}
            for name, v in asr_ms.items()}}, indent=1), encoding="utf-8")

    # ---------------- Ozet ----------------
    md = ["## Pipeline degerlendirmesi (BEKLEME modu, windowSlack=2)", "",
          f"{len(files)} kayit. Skor = score_transcription (ilk kilit esigi 70). "
          "guncel = CTC, rnnt = RNNT sabit 5 sn parca (APK #6-10), "
          "rnnt-hibrit = RNNT, kilitliyken duraklamada kes (APK #14+).", "",
          "| zincir | skorlanan | medyan | ≥50 | ≥70 | ≥90 | dogru sure (≥70) | Kuran-disi max | ASR ms/chunk |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, *_ in configs:
        scored = [(fn, r) for fn, _, r in results[name] if r["status"] == "scored"]
        scores = [r["score"] for _, r in scored]
        known = [(fn, r) for fn, r in scored if isinstance(EXPECTED.get(fn), int) and r["score"] >= 70]
        correct = sum(1 for fn, r in known if r.get("surah") == EXPECTED[fn])
        neg = [r["score"] for fn, r in scored if fn in EXPECTED and EXPECTED[fn] is None]
        med = statistics.median(scores) if scores else 0
        ms = statistics.median(asr_ms[name]) if asr_ms[name] else 0
        md.append(f"| {name} | {len(scores)} | {med:.1f} | "
                  f"{sum(s >= 50 for s in scores)} | {sum(s >= 70 for s in scores)} | {sum(s >= 90 for s in scores)} | "
                  f"{correct}/{len(known)} | {max(neg) if neg else '-'} | {ms:.0f} |")

    # Dosya bazinda: guncel (CTC) vs rnnt
    cmp_names = [n for n in ("rnnt", "rnnt-hibrit") if n in results]
    md += ["", "### Dosya bazinda (skor ≥70 eslesen sureler / medyan skor)", "",
           "| kayit | beklenen | " + " | ".join(cmp_names) + " |",
           "|---|---|" + "---|" * len(cmp_names)]
    for f in files:
        cells = []
        for name in cmp_names:
            rs = [r for fn, _, r in results[name] if fn == f.name and r["status"] == "scored"]
            hits = Counter(r.get("surah") for r in rs if r["score"] >= 70)
            med = statistics.median([r["score"] for r in rs]) if rs else 0
            cells.append(f"{', '.join(f'{s}×{n}' for s, n in hits.most_common(3)) or '-'} / {med:.1f}")
        md.append(f"| {f.name} | {EXPECTED.get(f.name, '?')} | " + " | ".join(cells) + " |")

    md += simulate_sessions(files, configs, transcripts, corpora)
    md += simulate_tracking(files, configs, transcripts, corpora)

    text = "\n".join(md) + "\n"
    print("\n" + text)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    main()
