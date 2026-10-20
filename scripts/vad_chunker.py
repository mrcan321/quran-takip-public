"""
Duraklamada kesen parcalayici (VAD chunker) — AudioPipeline.kt ChunkBuilder'in referansi (birebir).

Eskiden ses sabit 5 sn'lik parcalarla isleniyordu: okunan son kelime ekrana ortalama ~3.5 sn geriden
geliyordu ve parca siniri kelimeyi ortasindan kesebiliyordu. Imam ayet sonlarinda (ve uzun ayetlerde
vakf yerlerinde) duraklar — parcayi duraklamada kesip hemen islersek sonuc duraklamanin icinde gelir,
kelime de bolunmez.

Kural (her 100 ms'lik cercevede):
  - Sessizlik esigi uyarlamali: son 5 sn'nin cerceve RMS'lerinden gurultu (p20) ve konusma (p90);
    esik = gurultu + 0.3 * (konusma - gurultu). Dinamik aralik yoksa (konusma < 2*gurultu + 0.002)
    duraklama algilanmaz.
  - Parcada >= 1.5 sn yeni ses ve >= 1 sn konusma varken son 0.5 sn sessizse → kes (duraklama
    kesimi, bindirme yok — sinirda kelime yok).
  - Duraklama gelmezse 5 sn'de kes (eski sabit parca gibi, 1 sn bindirmeyle).

HIBRIT (APK #14+): duraklama kesimi sadece kilitliyken (FATIHA/ZAMM) acik; BEKLEME/ARA'da sabit 5 sn.
Sebep (CI eval, 30 kayit, RNNT): her yerde duraklama kesimi → 1-3 kelimelik parcalar BEKLEME'de belirsiz
aday uretip birbirini "dogruluyordu" — ilk kilit 17/0 → 14/2 (Nas → 113, ilahi → 2:258), yanlis kilitli
chunk 0 → 7. Hepsi BEKLEME'deydi; kilitliyken kisa parca yanlis kilit uretmedi (pencere + surenin kendisi
belirsizligi cozer). Parca basina en az konusmayi artirmak (2-3 sn) hiz kazancini tamamen yok ediyordu.
Telefonda anahtar her parcanin state machine sonucundan sonra guncellenir (~1 sn ASR); 1.5 sn'den (MIN)
once kesim olmadigi icin isleme 1.5 sn'den kisa surdukce parca sinirlari buradakiyle ayni.

Olcum (30 kayit, ASR'siz, ~1 sn islem dahil, her yerde duraklama kesimi): kelime → ekran ort. 3.4 → 3.0 sn,
ayet sonu duraklamasi → ekran medyan 3.4 → 2.1 sn. En uzun parca 5 sn oldugu icin hicbir durumda sabit
parcadan kotu degil. Dusuk SNR'li kayitta (konusma < 2*gurultu) duraklama algilanmaz → sabit 5 sn davranisi.
"""
from typing import Callable, List, Optional, Tuple

import numpy as np

SR = 16000
FRAME = 1600                 # 100 ms analiz cercevesi (AudioRecorder.FRAME_SAMPLES)
HISTORY_FRAMES = 50          # esik icin son 5 sn
MIN_CHUNK_FRAMES = 15        # 1.5 sn: bundan kisa parca duraklamada kesilmez (2.5 → zorunlu 5 sn
                             # kesiminden hemen sonraki duraklamalar kaciyordu, parcalar 5 sn izgarasinda kaliyordu)
MAX_CHUNK_FRAMES = 50        # 5.0 sn: duraklama gelmezse (eski sabit parca)
PAUSE_FRAMES = 5             # 0.5 sn sessizlik = duraklama
MIN_SPEECH_FRAMES = 10       # parcada en az 1 sn konusma
OVERLAP_SAMPLES = SR         # zorunlu (5 sn) kesimde 1 sn bindirme; duraklama kesiminde yok
SILENT_RATIO = 0.3


class PauseChunker:
    def __init__(self):
        self.history: List[float] = []
        self.frames: List[np.ndarray] = []
        self.silent: List[bool] = []
        self.tail = np.zeros(0, dtype=np.float32)
        # Hibrit: False iken sadece 5 sn'de kesilir (sabit parca). Sessizlik gecmisi her durumda tutulur.
        self.pause_enabled = True

    def _is_silent(self, rms: float) -> bool:
        self.history.append(rms)
        if len(self.history) > HISTORY_FRAMES:
            self.history.pop(0)
        s = sorted(self.history)
        n = len(s)
        noise = s[int(0.2 * (n - 1))]
        speech = s[int(0.9 * (n - 1))]
        if speech < 2 * noise + 0.002:
            return False
        return rms < noise + SILENT_RATIO * (speech - noise)

    def add_frame(self, frame: np.ndarray) -> Optional[Tuple[np.ndarray, bool]]:
        """100 ms cerceve ekle; parca hazirsa (ses, duraklama_kesimi_mi) don."""
        rms = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))) if len(frame) else 0.0
        self.silent.append(self._is_silent(rms))
        self.frames.append(frame)
        n = len(self.frames)
        speech = n - sum(self.silent)
        pause = n >= PAUSE_FRAMES and all(self.silent[-PAUSE_FRAMES:])
        if self.pause_enabled and n >= MIN_CHUNK_FRAMES and pause and speech >= MIN_SPEECH_FRAMES:
            return self._cut(True)
        if n >= MAX_CHUNK_FRAMES:
            return self._cut(False)
        return None

    def _cut(self, pause_cut: bool) -> Tuple[np.ndarray, bool]:
        combined = np.concatenate([self.tail] + self.frames).astype(np.float32)
        self.tail = np.zeros(0, dtype=np.float32) if pause_cut else combined[max(0, len(combined) - OVERLAP_SAMPLES):]
        self.frames, self.silent = [], []
        return combined, pause_cut


def chunks_pause(audio: np.ndarray, pause_enabled: Optional[Callable[[], bool]] = None):
    """Kayit → (parca, bitis_sn, duraklama_kesimi) — telefondaki ChunkBuilder ile ayni.

    pause_enabled: her cercevede sorulur (hibrit: state machine kilitli mi). Uretec tembel oldugu icin
    tuketici bir parcayi isleyip state'i guncelledikten sonra sonraki cerceveler yeni degeri gorur.
    None → her zaman duraklamada kes."""
    ch = PauseChunker()
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        if pause_enabled is not None:
            ch.pause_enabled = bool(pause_enabled())
        out = ch.add_frame(audio[i:i + FRAME])
        if out is not None:
            yield out[0], (i + FRAME) / SR, out[1]
