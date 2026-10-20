#!/usr/bin/env python3
"""Ince ayar — Asama C: NVIDIA FastConformer Hybrid (RNNT + CTC) modelini kendi verimizle egit (kiralik GPU).

Tokenizer, mimari ve cikti yazimi (harekeli imla'i) temel modelle ayni kalir → uygulamadaki ONNX export / RNNT greedy
cozucu / SentencePiece cozucu degismez; sadece agirliklar degisir. Unutmayi (kamet, semiallah, selam, dua, genel Arapca)
onlemek icin: dusuk ogrenme hizi, kisa egitim, veride genel Arapca hatirlatma parcalari (prepare_labels.py), istege bagli
kodlayicinin alt katmanlarini dondurma.

Girdi: prepare_labels.py'nin train.jsonl / val.jsonl'u (NeMo manifest).
Cikti (<out>/): best.nemo (dogrulama WER'i en iyi), final.nemo, tensorboard log'lari, train_report.json.

Kullanim:
  python training/finetune.py --data /data/tt --out /data/run1                 # varsayilanlar: A100/H100 tek GPU
  python training/finetune.py --data /tmp/tt --out /tmp/run --smoke            # 20 adim (boru hattini dene)
  python training/finetune.py --init /path/base.nemo ...                       # temel model yerine .nemo
"""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

# torch >= 2.6 torch.load(weights_only=True) varsayilani NeMo'nun kendi checkpoint'ini (OmegaConf iceriyor) "en iyi
# model → .nemo" adiminda acamiyor; kendi urettigimiz dosyalar → guvenli
os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

DEFAULT_MODEL = "nvidia/stt_ar_fastconformer_hybrid_large_pcd_v1.0"


def load_model(name):
    import torch
    from nemo.collections.asr.models import ASRModel, EncDecHybridRNNTCTCBPEModel
    cpu = torch.device("cpu")
    if name.endswith(".nemo") and Path(name).exists():
        return ASRModel.restore_from(name, map_location=cpu)
    return EncDecHybridRNNTCTCBPEModel.from_pretrained(model_name=name, map_location=cpu)


def ds_config(base, manifest, batch, workers, shuffle, max_dur, lhotse_dur):
    """Temel modelin train_ds / validation_ds ayarini bizim manifest'imizle guncelle (tarred / bucketing kapali)."""
    from omegaconf import OmegaConf, open_dict
    c = OmegaConf.create(OmegaConf.to_container(base, resolve=True)) if base is not None else OmegaConf.create({})
    with open_dict(c):
        for k in ("tarred_audio_filepaths", "bucketing_strategy", "bucketing_batch_size", "bucketing_weights"):
            c.pop(k, None)
        c.manifest_filepath = manifest
        c.sample_rate = 16000
        c.batch_size = batch
        c.shuffle = shuffle
        c.num_workers = workers
        c.pin_memory = True
        c.is_tarred = False
        c.max_duration = max_dur
        c.min_duration = 0.2
        c.trim_silence = False
        c.use_start_end_token = False
        if lhotse_dur > 0:
            c.use_lhotse = True
            c.batch_duration = lhotse_dur
            c.batch_size = None
            c.quadratic_duration = 30
            c.num_buckets = 20
            c.shuffle_buffer_size = 10000
            c.bucket_buffer_size = 20000
        else:
            c.use_lhotse = False
    return c


def freeze_encoder(model, n_layers):
    """Ön isleyici + alt ornekleme + ilk n Conformer katmanini dondur (az veride unutmayi azaltir)."""
    if n_layers <= 0:
        return 0
    frozen = 0
    for name in ("pre_encode",):
        m = getattr(model.encoder, name, None)
        if m is not None:
            m.requires_grad_(False)
    for i, layer in enumerate(model.encoder.layers):
        if i < n_layers:
            layer.requires_grad_(False)
            frozen += 1
    return frozen


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, required=True, help="prepare_labels.py ciktisi (train.jsonl, val.jsonl)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--init", default=DEFAULT_MODEL, help="baslangic modeli (NGC/HF adi ya da .nemo)")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--max-steps", type=int, default=-1, help=">0 ise epoch yerine adim sayisi")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--accum", type=int, default=1)
    ap.add_argument("--lhotse-batch-duration", type=float, default=0.0,
                    help=">0: lhotse dinamik paket (toplam ses sn / paket; A100 80GB ~600) — sabit --batch yerine")
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--min-lr", type=float, default=1e-6)
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--weight-decay", type=float, default=1e-3)
    ap.add_argument("--freeze-encoder-layers", type=int, default=0)
    ap.add_argument("--max-duration", type=float, default=20.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--precision", default="bf16-mixed")
    ap.add_argument("--devices", type=int, default=-1)
    ap.add_argument("--val-every", type=float, default=0.5, help="epoch'un bu kesrinde bir dogrulama")
    ap.add_argument("--smoke", action="store_true", help="20 adim, kucuk paket (boru hattini dene)")
    args = ap.parse_args()

    import lightning.pytorch as pl
    import torch
    from omegaconf import open_dict
    from nemo.utils.exp_manager import exp_manager

    args.out.mkdir(parents=True, exist_ok=True)
    train_m, val_m = str((args.data / "train.jsonl").resolve()), str((args.data / "val.jsonl").resolve())
    gpu = torch.cuda.is_available()
    if args.smoke:
        args.max_steps, args.batch, args.accum, args.warmup, args.workers = 20, min(args.batch, 4), 1, 2, 0
    if not gpu:
        args.precision, args.devices = "32", 1
    t0 = time.time()

    # lhotse paketleri yinelenebilir (uzunlugu bilinmez) → epoch sayisini adima cevir (kosinus takvimi icin gerekli)
    val_interval = 10 if args.smoke else args.val_every
    if args.lhotse_batch_duration > 0 and args.max_steps <= 0:
        total = sum(json.loads(x)["duration"] for x in Path(train_m).read_text(encoding="utf-8").splitlines() if x)
        per_epoch = max(1, int(total / (args.lhotse_batch_duration * 0.85) / args.accum))
        args.max_steps = per_epoch * args.epochs
        val_interval = max(1, int(per_epoch * args.val_every)) * args.accum
        print(f"lhotse: {total / 3600:.1f} sa egitim verisi → epoch ~{per_epoch} adim, toplam {args.max_steps}",
              flush=True)

    model = load_model(args.init)
    cfg = model.cfg
    with open_dict(cfg):
        cfg.train_ds = ds_config(cfg.get("train_ds"), train_m, args.batch, args.workers, True, args.max_duration,
                                 args.lhotse_batch_duration)
        cfg.validation_ds = ds_config(cfg.get("validation_ds"), val_m, max(1, args.batch // 2), args.workers, False,
                                      40.0, 0.0)
        cfg.test_ds = None
        cfg.optim.name = "adamw"
        cfg.optim.lr = args.lr
        cfg.optim.weight_decay = args.weight_decay
        cfg.optim.betas = [0.9, 0.98]
        cfg.optim.sched = {"name": "CosineAnnealing", "warmup_steps": args.warmup, "min_lr": args.min_lr}
    model.setup_training_data(cfg.train_ds)
    model.setup_multiple_validation_data(cfg.validation_ds)
    frozen = freeze_encoder(model, args.freeze_encoder_layers)

    trainer = pl.Trainer(
        accelerator="gpu" if gpu else "cpu", devices=args.devices, precision=args.precision,
        max_epochs=-1 if args.max_steps > 0 else args.epochs, max_steps=args.max_steps,
        accumulate_grad_batches=args.accum, gradient_clip_val=1.0, log_every_n_steps=10 if args.smoke else 50,
        val_check_interval=val_interval, num_sanity_val_steps=0,
        check_val_every_n_epoch=None if isinstance(val_interval, int) else 1,
        enable_checkpointing=False, logger=False, benchmark=False,
    )
    exp_dir = exp_manager(trainer, {
        "exp_dir": str(args.out), "name": "tilavet", "use_datetime_version": False,
        "create_tensorboard_logger": True, "create_checkpoint_callback": True,
        "checkpoint_callback_params": {"monitor": "val_wer", "mode": "min", "save_top_k": 2,
                                       "always_save_nemo": True, "save_best_model": True},
        "resume_if_exists": True, "resume_ignore_no_checkpoint": True,
    })
    model.set_trainer(trainer)
    model.setup_optimization(cfg.optim)

    # Egitim oncesi dogrulama WER'i (temel model) — rapora
    base_val = trainer.validate(model, verbose=False)
    print(f"Temel model dogrulama: {base_val}", flush=True)
    trainer.fit(model)

    final = args.out / "final.nemo"
    model.save_to(str(final))
    best = None
    ck = Path(exp_dir) / "checkpoints"
    nemo_files = sorted(ck.glob("*.nemo"), key=lambda p: p.stat().st_mtime) if ck.exists() else []
    if nemo_files:
        best = args.out / "best.nemo"
        shutil.copy(nemo_files[-1], best)   # save_best_model: egitim sonunda en iyi agirliklarla yazilir
    best_score = None
    cb = getattr(trainer, "checkpoint_callback", None)
    if cb is not None and getattr(cb, "best_model_score", None) is not None:
        best_score = float(cb.best_model_score)
    report = {"init": args.init, "steps": trainer.global_step, "epochs": trainer.current_epoch,
              "frozen_layers": frozen, "base_val": base_val, "best_val_wer": best_score,
              "best": str(best) if best else None, "final": str(final), "minutes": round((time.time() - t0) / 60, 1),
              "args": {k: str(v) for k, v in vars(args).items()}}
    (args.out / "train_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
