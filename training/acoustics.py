"""Cami / telefon akustigi — ince ayar verisinin bozma (augmentation) adimi.

tests/synth/build_synth.py'nin oda yankisi / bant gecirme yardimcilarini kullanir (sentetik namaz kayitlariyla ayni
fizik), ustune egitim icin cesitlilik: hoparlor (PA) rengi, hafif kirpma / sikistirma, telefon mikrofonu, arka plan
gurultusu (gercek cami kayitlarinin okuma disi bolumleri + sentetik: pembe / kahverengi gurultu, sebeke ugultusu,
ust uste konusma uguldamasi, telefon titresimi), seviye.

Gercek gurultu SADECE egitim bolumundeki (real_labels.json "split": "train") kayitlardan alinir — test kayitlarinin
cami sesi egitime sizmasin.
"""
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "synth"))
sys.path.insert(0, str(REPO / "scripts"))
import build_synth as bs  # noqa: E402

SR = bs.SR
load_any = bs.load_any
trim = bs.trim
fft_filter = bs.fft_filter
convolve = bs.convolve
rms = bs.rms


def _shape_noise(n, rng, exponent):
    """1/f^exponent renkli gurultu (0 beyaz, 1 pembe, 2 kahverengi)."""
    m = 1 << max(1, (n - 1).bit_length())
    spec = rng.standard_normal(m // 2 + 1) + 1j * rng.standard_normal(m // 2 + 1)
    f = np.fft.rfftfreq(m, 1 / SR)
    f[0] = f[1]
    spec /= f ** (exponent / 2)
    x = np.fft.irfft(spec, m)[:n]
    return (x / (rms(x) + 1e-9)).astype(np.float32)


def synth_noise(n, rng, babble_pool=None):
    """Sentetik cami arka plani (rms 1'e olcekli). babble_pool: kisa konusma parcalari (uguldama icin)."""
    kind = rng.choice(["pink", "brown", "hum", "babble", "vibration"], p=[0.3, 0.25, 0.15, 0.2, 0.1])
    if kind in ("pink", "brown"):
        x = _shape_noise(n, rng, 1.0 if kind == "pink" else 2.0)
        return fft_filter(x, lo=rng.uniform(40, 120), hi=rng.uniform(3000, 7500))
    if kind == "hum":
        t = np.arange(n) / SR
        f0 = rng.choice([50.0, 100.0])
        x = sum(rng.uniform(0.2, 1.0) / k * np.sin(2 * np.pi * f0 * k * t + rng.uniform(0, 6.3)) for k in range(1, 6))
        x = x + 0.3 * _shape_noise(n, rng, 1.0)
        return (x / (rms(x) + 1e-9)).astype(np.float32)
    if kind == "vibration":
        # akşam #2'deki cagri titresimi: ~200 Hz, 1-1.5 sn darbe, 3-4 sn periyot
        t = np.arange(n) / SR
        per, on = rng.uniform(3.0, 4.0), rng.uniform(1.0, 1.5)
        env = ((t % per) < on).astype(np.float32)
        x = np.sin(2 * np.pi * rng.uniform(170, 230) * t) * env + 0.05 * _shape_noise(n, rng, 1.0)
        return (x / (rms(x) + 1e-9)).astype(np.float32)
    # babble: birkac konusma parcasinin ust uste toplami (uzak, yankili cemaat uguldamasi)
    x = np.zeros(n, dtype=np.float32)
    if babble_pool:
        for _ in range(rng.integers(4, 9)):
            src = babble_pool[rng.integers(len(babble_pool))]
            if len(src) == 0:
                continue
            reps = int(np.ceil(n / len(src))) + 1
            off = rng.integers(len(src))
            x += np.tile(src, reps)[off:off + n] * rng.uniform(0.5, 1.0)
        x = fft_filter(x, lo=150, hi=rng.uniform(2000, 3500))
    if rms(x) < 1e-6:
        x = _shape_noise(n, rng, 1.0)
    return (x / (rms(x) + 1e-9)).astype(np.float32)


def pa_color(a, rng):
    """Cami hoparloru: bant (150 Hz - 5-8 kHz) + 1-3 rastgele tepe / cukur (±6 dB), bazen hafif kirpma."""
    n = len(a)
    if n == 0:
        return a
    m = 1 << (n - 1).bit_length()
    A = np.fft.rfft(a, m)
    f = np.fft.rfftfreq(m, 1 / SR)
    g_db = np.zeros_like(f)
    for _ in range(rng.integers(1, 4)):
        fc = np.exp(rng.uniform(np.log(200), np.log(5000)))
        bw = fc * rng.uniform(0.3, 1.0)
        g_db += rng.uniform(-6, 6) * np.exp(-0.5 * ((f - fc) / bw) ** 2)
    y = np.fft.irfft(A * 10 ** (g_db / 20), m)[:n].astype(np.float32)
    y = fft_filter(y, lo=rng.uniform(100, 200), hi=rng.uniform(5000, 8000))
    if rng.random() < 0.3:
        drive = rng.uniform(1.5, 4.0)
        peak = np.max(np.abs(y)) + 1e-9
        y = (np.tanh(drive * y / peak) / np.tanh(drive) * peak).astype(np.float32)
    return y


def mosque(a, rng, noise_pool=None, babble_pool=None, real_room=False):
    """Kuru okumayi cami + telefon kaydina benzet. real_room: ses zaten camide alinmis (yanki / PA ekleme).

    Donus: (ses, aciklama) — aciklama manifest'e yazilir (hangi bozmalarin uygulandigi).
    """
    desc = []
    y = a.astype(np.float32)
    if not real_room:
        if rng.random() < 0.8:
            y = pa_color(y, rng)
            desc.append("pa")
        if rng.random() < 0.85:
            rt60 = rng.uniform(0.6, 3.0)
            ir = bs.room_ir(rng, rt60)
            y = convolve(y, ir)[:len(a) + int(0.4 * SR)]
            desc.append(f"rt{rt60:.1f}")
    y = fft_filter(y, lo=rng.uniform(80, 130), hi=rng.uniform(5000, 7500))       # telefon mikrofonu
    level = rng.uniform(0.02, 0.1)
    y *= level / (rms(y) + 1e-9)
    # arka plan: gercek cami gurultusu (egitim kayitlarindan) ya da sentetik; SNR 0-25 dB
    if rng.random() < 0.9:
        n = len(y)
        if noise_pool and rng.random() < 0.6:
            src = noise_pool[rng.integers(len(noise_pool))]
            reps = int(np.ceil(n / max(1, len(src)))) + 1
            off = rng.integers(max(1, len(src)))
            nz = np.tile(src, reps)[off:off + n]
            nz = nz / (rms(nz) + 1e-9)
            desc.append("realnoise")
        else:
            nz = synth_noise(n, rng, babble_pool)
            desc.append("synthnoise")
        snr = rng.uniform(0, 25)
        y = y + nz * (rms(y) / 10 ** (snr / 20))
        desc.append(f"snr{snr:.0f}")
    peak = np.max(np.abs(y)) if len(y) else 1.0
    if peak > 0.99:
        y *= 0.99 / peak
    return y.astype(np.float32), "+".join(desc) or "temiz"


def noise_only(n, rng, noise_pool=None, babble_pool=None):
    """Olumsuz ornek (etiket bos): sadece arka plan — ASR sessizlikte / gurultude metin uydurmasin."""
    if noise_pool and rng.random() < 0.5:
        src = noise_pool[rng.integers(len(noise_pool))]
        reps = int(np.ceil(n / max(1, len(src)))) + 1
        off = rng.integers(max(1, len(src)))
        x = np.tile(src, reps)[off:off + n]
    else:
        x = synth_noise(n, rng, babble_pool)
    x = fft_filter(x, lo=rng.uniform(80, 130), hi=rng.uniform(5000, 7500))
    x *= rng.uniform(0.003, 0.03) / (rms(x) + 1e-9)
    return x.astype(np.float32)
