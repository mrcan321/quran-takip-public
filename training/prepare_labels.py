#!/usr/bin/env python3
"""Ince ayar verisi — Asama B (temel model gerekir; GPU'da dakikalar, CPU'da saatler).

build_dataset.py'nin ciktisini egitime hazirlar:
  1. Etiket dogrulama (EveryAyah): her (kari, ayet) TEMIZ MP3'u temel modelle yazdirilir; normalize kelime hatasi
     > --max-wer olan ayetler (eksik / yanlis ses, farkli kiraat) iceren parcalar atilir. 1. ayette kari besmeleyi de
     okuduysa (model ciktisi besmeleyle basliyor, etiket degil) etikete besmele eklenir.
  2. Zorla hizalama (to_align.jsonl): 20 sn'den uzun ayetler, gercek cami kayitlarinin okuma bolumleri, kamet —
     temel modelin CTC cikisiyla Viterbi hizalama → kelime zamanlari → kelime sinirindan 4-15 sn parcalar. Kelime
     guveni (yol log olasiligi − karenin en iyisi) dusuk parcalar atilir (imam farkli okumus / metin tutmuyor).
     Gercek kayitlarda bolumun ilk / son kelimesi kullanilmaz (sinir belirsiz).
  3. Genel Arapca hatirlatma (to_label.jsonl, FLEURS ar): etiket = temel modelin kendi ciktisi (unutmayi onler);
     FLEURS metniyle normalize kelime hatasi > --max-wer ya da ASR uydurma kelimesi iceren atilir.
Cikti (<data>/): train.jsonl, val.jsonl (NeMo manifest), stats_b.json, rejected.jsonl (atilanlar + neden).

Kullanim:
  python training/prepare_labels.py --data /data/tt
  python training/prepare_labels.py --data /tmp/tt --init /tmp/tiny.nemo --no-verify   # yerel mekanik deneme
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "scripts"))
import acoustics as ac  # noqa: E402
from build_dataset import EVERYAYAH, load_texts, uid, write_flac  # noqa: E402,F401
from finetune import DEFAULT_MODEL, load_model  # noqa: E402

SR = ac.SR
BESMELE_NORM = None


def norm_words(text):
    import aligner
    return [w for w in aligner.normalize_arabic(text or "").split() if w]


def wer(ref, hyp):
    """Normalize kelime hatasi (ref kelime sayisina gore)."""
    r, h = norm_words(ref), norm_words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / len(r)


def texts_of(result):
    """NeMo transcribe() ciktisi (surume gore tuple / liste / Hypothesis) → metin listesi."""
    if isinstance(result, tuple):
        result = result[0]
    out = []
    for x in result:
        if isinstance(x, list):
            x = x[0] if x else ""
        out.append(x.text if hasattr(x, "text") else str(x))
    return out


class Model:
    def __init__(self, name, batch):
        import torch
        self.torch = torch
        self.m = load_model(name)
        self.dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.m = self.m.to(self.dev).eval()
        self.m.change_decoding_strategy(decoder_type="rnnt")
        self.batch = batch
        cfg = self.m.cfg
        self.hop = float(cfg.preprocessor.window_stride) * int(cfg.encoder.get("subsampling_factor", 8))

    def transcribe(self, audios):
        out = []
        for i in range(0, len(audios), self.batch):
            chunk = [np.asarray(a, dtype=np.float32) for a in audios[i:i + self.batch]]
            with self.torch.no_grad():
                out += texts_of(self.m.transcribe(chunk, batch_size=len(chunk), verbose=False))
        return out

    def ctc_logprobs(self, audio):
        t = self.torch
        sig = t.tensor(audio, dtype=t.float32, device=self.dev)[None]
        ln = t.tensor([len(audio)], device=self.dev)
        with t.no_grad():
            feats, fl = self.m.preprocessor(input_signal=sig, length=ln)
            enc, el = self.m.encoder(audio_signal=feats, length=fl)
            lp = self.m.ctc_decoder(encoder_output=enc)
        return lp[0, :int(el[0])].float().cpu().numpy()

    def word_tokens(self, words):
        return [self.m.tokenizer.text_to_ids(w) for w in words]


# ---------------- CTC Viterbi zorla hizalama ----------------
def viterbi(lp, tokens, blank):
    """lp: (T, V+1) log olasilik, tokens: hedef token dizisi → her token'in (bas_kare, son_kare) araligi; olmazsa None."""
    T, S = lp.shape[0], 2 * len(tokens) + 1
    if len(tokens) == 0 or T < len(tokens):
        return None
    ext = np.full(S, blank, dtype=np.int64)
    ext[1::2] = tokens
    # s-2'den gecis: blank degil ve onceki token'dan farkliysa
    skip = np.zeros(S, dtype=bool)
    skip[3::2] = np.array(tokens[1:]) != np.array(tokens[:-1])
    NEG = -1e30
    dp = np.full(S, NEG)
    dp[0], dp[1] = lp[0, ext[0]], lp[0, ext[1]]
    back = np.zeros((T, S), dtype=np.int8)       # 0: ayni durum, 1: s-1, 2: s-2
    for t in range(1, T):
        stay = dp
        prev1 = np.concatenate(([NEG], dp[:-1]))
        prev2 = np.where(skip, np.concatenate(([NEG, NEG], dp[:-2])), NEG)
        best = np.maximum(stay, np.maximum(prev1, prev2))
        back[t] = np.where(best == stay, 0, np.where(best == prev1, 1, 2))
        dp = best + lp[t, ext]
    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    if dp[s] <= NEG / 2:
        return None
    path = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= int(back[t, s])
    spans = [[None, None] for _ in tokens]
    for t, st in enumerate(path):
        if st % 2 == 1:
            k = st // 2
            if spans[k][0] is None:
                spans[k][0] = t
            spans[k][1] = t
    if any(a is None for a, _ in spans):
        return None
    return spans, path


def align_words(model, audio, text):
    """→ [(kelime, bas_sn, son_sn, guven)] ya da None. guven: kelime karelerinde (yol − en iyi) log olasilik ortalamasi."""
    words = text.split()
    lp = model.ctc_logprobs(audio)
    blank = lp.shape[1] - 1
    wt = model.word_tokens(words)
    if any(len(ids) == 0 for ids in wt):
        return None
    flat = [t for ids in wt for t in ids]
    res = viterbi(lp, flat, blank)
    if res is None:
        return None
    spans, path = res
    best = lp.max(axis=1)
    on_path = np.array([lp[t, flat[s // 2] if s % 2 else blank] for t, s in enumerate(path)]) - best
    out, k0 = [], 0
    for i, w in enumerate(words):
        k1 = k0 + len(wt[i])
        a, b = spans[k0][0], spans[k1 - 1][1]
        out.append((w, a * model.hop, (b + 1) * model.hop, float(on_path[a:b + 1].mean())))
        k0 = k1
    return out


def cut_pieces(words, rng, min_sec=4.0, max_sec=15.0, hard_max=18.0):
    """Kelime zamanlarindan parca sinirlari: hedef sureye ulasinca en yakin genis (>= 0.15 sn) bosluktan kes."""
    pieces, cur = [], []
    target = rng.uniform(min_sec, max_sec)
    for i, w in enumerate(words):
        cur.append(w)
        dur = cur[-1][2] - cur[0][1]
        gap = (words[i + 1][1] - w[2]) if i + 1 < len(words) else 9.9
        if (dur >= target and gap >= 0.15) or dur >= hard_max or i + 1 == len(words):
            pieces.append(cur)
            cur, target = [], rng.uniform(min_sec, max_sec)
    return pieces


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--init", default=DEFAULT_MODEL)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "everyayah")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--max-wer", type=float, default=0.5)
    ap.add_argument("--min-word-conf", type=float, default=-4.0, help="parcadaki en kotu kelime guveni alt siniri")
    ap.add_argument("--min-piece-conf", type=float, default=-1.5, help="parca ortalama kelime guveni alt siniri")
    ap.add_argument("--real-copies", type=int, default=2, help="gercek cami parcalari: 1 asil + (n-1) ek gurultulu kopya")
    ap.add_argument("--no-verify", action="store_true", help="EveryAyah dogrulamasini atla (yerel mekanik deneme)")
    ap.add_argument("--seed", type=int, default=2)
    args = ap.parse_args()
    data = args.data.resolve()
    rng = np.random.default_rng(args.seed)
    t0 = time.time()

    def read(name):
        p = data / name
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []

    stage_a, val_a, to_align, to_label = (read("stage_a.jsonl"), read("val_a.jsonl"), read("to_align.jsonl"),
                                          read("to_label.jsonl"))
    texts, bism, _ = load_texts()
    model = Model(args.init, args.batch)
    rejected = []

    # gurultu havuzu (ek gurultulu kopyalar icin): olumsuz orneklerden gercek olanlar
    noise_pool = [sf.read(r["audio_filepath"], dtype="float32")[0] for r in stage_a
                  if r["kind"] == "negative" and r.get("aug") == "gercek"][:200]

    # ---- 1. EveryAyah etiket dogrulamasi (temiz MP3'lerle) ----
    bad, has_bism = set(), set()
    if not args.no_verify:
        keys = sorted({(r["reciter"], a) for r in stage_a + val_a + to_align if r.get("source") == "everyayah"
                       for a in r["ayahs"]})
        print(f"Dogrulama: {len(keys)} (kari, ayet) temiz kayit", flush=True)
        for i in range(0, len(keys), 512):
            part = keys[i:i + 512]
            audios, ok = [], []
            for rec, a in part:
                s, ay = map(int, a.split(":"))
                p = args.cache / rec / f"{s:03d}{ay:03d}.mp3"
                try:
                    x = ac.trim(ac.load_any(p))
                except Exception:  # noqa: BLE001
                    bad.add((rec, a))
                    continue
                if len(x) / SR > 30:      # uzun ayetler zorla hizalamada denetlenir
                    continue
                audios.append(x)
                ok.append((rec, a))
            hyps = model.transcribe(audios)
            for (rec, a), h in zip(ok, hyps):
                s, ay = map(int, a.split(":"))
                ref = texts[(s, ay)]
                if ay == 1 and s in bism and norm_words(h)[:2] == norm_words(bism[s])[:2] \
                        and norm_words(ref)[:2] != norm_words(bism[s])[:2]:
                    has_bism.add((rec, a))
                    ref = bism[s] + " " + ref
                if wer(ref, h) > args.max_wer:
                    bad.add((rec, a))
            print(f"  {min(i + 512, len(keys))}/{len(keys)} · hatali {len(bad)} · besmeleli {len(has_bism)} · "
                  f"{time.time() - t0:.0f} sn", flush=True)

    def relabel(r):
        """Parcanin etiketini ayetlerden yeniden kur (besmele duzeltmesi); hatali ayet varsa None."""
        if r.get("source") != "everyayah":
            return r
        if any((r["reciter"], a) in bad for a in r["ayahs"]):
            rejected.append({"audio_filepath": r["audio_filepath"], "neden": "dogrulama"})
            return None
        parts = []
        for a in r["ayahs"]:
            s, ay = map(int, a.split(":"))
            parts.append((bism[s] + " " if (r["reciter"], a) in has_bism else "") + texts[(s, ay)])
        return dict(r, text=" ".join(parts))

    train = [x for x in (relabel(r) for r in stage_a) if x is not None]
    val = [x for x in (relabel(r) for r in val_a) if x is not None]

    # ---- 2. Zorla hizalama + bolme ----
    n_ok = n_bad = 0
    for k, r in enumerate(to_align):
        audio = sf.read(r["audio_filepath"], dtype="float32")[0]
        text = r["text"]
        if r.get("source") == "everyayah":
            a = r["ayahs"][0]
            if (r["reciter"], a) in bad:
                continue
        words = align_words(model, audio, text)
        if words is None:
            rejected.append({"audio_filepath": r["audio_filepath"], "neden": "hizalanamadi"})
            n_bad += 1
            continue
        if r.get("trim_edges") and len(words) > 4:
            words = words[1:-1]
        split = r.get("split", "train")
        out_dir = data / "audio" / f"aligned_{split}"
        for piece in cut_pieces(words, rng):
            confs = [w[3] for w in piece]
            dur = piece[-1][2] - piece[0][1]
            if dur > 20.0 or dur < 0.5 or max(w[2] - w[1] for w in piece) > 4.0:
                rejected.append({"audio_filepath": r["audio_filepath"], "neden": "sure",
                                 "metin": " ".join(w[0] for w in piece), "sure": round(dur, 1)})
                n_bad += 1
                continue
            if min(confs) < args.min_word_conf or float(np.mean(confs)) < args.min_piece_conf:
                rejected.append({"audio_filepath": r["audio_filepath"], "neden": "guven",
                                 "metin": " ".join(w[0] for w in piece), "guven": round(float(np.mean(confs)), 2)})
                n_bad += 1
                continue
            st = max(0.0, piece[0][1] - 0.15)
            en = min(len(audio) / SR, piece[-1][2] + 0.15)
            seg = audio[int(st * SR):int(en * SR)]
            label = " ".join(w[0] for w in piece)
            copies = args.real_copies if r["kind"] in ("real", "kamet") else 1
            for c in range(copies):
                if r.get("augment", True):
                    y, desc = ac.mosque(seg, rng, noise_pool)
                elif c == 0:
                    y, desc = seg, "gercek"
                else:
                    y, desc = ac.mosque(seg, rng, noise_pool, real_room=True)
                p = out_dir / f"{uid(r['audio_filepath'], st, c)}.flac"
                row = {"audio_filepath": str(p), "duration": write_flac(p, y), "text": label, "kind": r["kind"],
                       "source": r.get("source"), "aug": desc}
                (val if split == "val" else train).append(row)
            n_ok += 1
        if k % 50 == 0:
            print(f"  hizalama {k + 1}/{len(to_align)} · parca {n_ok} · atilan {n_bad} · {time.time() - t0:.0f} sn",
                  flush=True)

    # ---- 3. Genel Arapca: temel modelin kendi etiketi ----
    if to_label:
        import build_state_machine_fixture as sm
        audios = [sf.read(r["audio_filepath"], dtype="float32")[0] for r in to_label]
        hyps = model.transcribe(audios)
        for r, h in zip(to_label, hyps):
            h = h.strip()
            if not h or sm.is_asr_hallucination(h) or (r.get("ref") and wer(r["ref"], h) > args.max_wer):
                rejected.append({"audio_filepath": r["audio_filepath"], "neden": "hatirlatma", "metin": h})
                continue
            train.append(dict(r, text=h))

    def dump(name, rows):
        with open(data / name, "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    dump("train.jsonl", train)
    dump("val.jsonl", val)
    dump("rejected.jsonl", rejected)
    stats = {}
    for row in train:
        s = stats.setdefault(row["kind"], {"parca": 0, "saat": 0.0})
        s["parca"] += 1
        s["saat"] += row["duration"] / 3600
    stats = {k: {"parca": v["parca"], "saat": round(v["saat"], 2)} for k, v in stats.items()}
    stats["val"] = {"parca": len(val), "saat": round(sum(r["duration"] for r in val) / 3600, 2)}
    stats["dogrulama"] = {"hatali_ayet": len(bad), "besmeleli_ayet": len(has_bism)}
    stats["atilan"] = len(rejected)
    stats["dakika"] = round((time.time() - t0) / 60, 1)
    (data / "stats_b.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
