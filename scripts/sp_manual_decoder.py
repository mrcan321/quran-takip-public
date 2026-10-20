#!/usr/bin/env python3
"""
SentencePiece Manual Decoder — Reference implementation

Hedef:
  SP model dosyasini protobuf olarak okuyup, NeMo'nun decode_ids ile
  AYNI cikti veren manuel decoder yazmak. Boylelikle Kotlin'e portable.

Strateji:
  SP model = protobuf serialized format
  Icinde "pieces" listesi var: [(piece_text, score, type), ...]
  ID = bu listedeki indeks
  decode_ids = piece_text'leri concatenate, ▁ -> space replacement

Calistirma:
  python scripts/sp_manual_decoder.py
"""

from pathlib import Path
import struct
import sentencepiece as spm

HOME = Path.home()
SP_MODEL = HOME / "projects" / "quran-asr" / "onnx" / "tokenizer" / "43c84e71237048ddab3bb273bdc00fa0_tokenizer.model"

# ============================================================
# 1. Protobuf wire format'i manuel okuma
# ============================================================
# SP model formatı: protobuf2 messages
# Her piece bir submessage:
#   message SentencePiece {
#     optional string piece = 1;
#     optional float score = 2;
#     optional Type type = 3 [default = NORMAL];
#   }
#
# Top-level message:
#   message ModelProto {
#     repeated SentencePiece pieces = 1;
#     optional TrainerSpec trainer_spec = 2;
#     optional NormalizerSpec normalizer_spec = 3;
#     ...
#   }

def read_varint(data, offset):
    """Protobuf varint okuma — variable-length unsigned int"""
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, offset

def read_tag(data, offset):
    """Protobuf field tag — (field_number, wire_type)"""
    tag, offset = read_varint(data, offset)
    field_num = tag >> 3
    wire_type = tag & 0x07
    return field_num, wire_type, offset

def read_length_delimited(data, offset):
    """Wire type 2: length-delimited (string, bytes, embedded message)"""
    length, offset = read_varint(data, offset)
    payload = data[offset:offset + length]
    return payload, offset + length

def read_fixed32(data, offset):
    """Wire type 5: 32-bit (float)"""
    val = struct.unpack("<f", data[offset:offset + 4])[0]
    return val, offset + 4

def parse_sentencepiece(data):
    """Tek bir SentencePiece mesajini parse et"""
    piece = ""
    score = 0.0
    sp_type = 1  # NORMAL default
    offset = 0
    while offset < len(data):
        field_num, wire_type, offset = read_tag(data, offset)
        if field_num == 1 and wire_type == 2:
            payload, offset = read_length_delimited(data, offset)
            piece = payload.decode("utf-8")
        elif field_num == 2 and wire_type == 5:
            score, offset = read_fixed32(data, offset)
        elif field_num == 3 and wire_type == 0:
            sp_type, offset = read_varint(data, offset)
        else:
            # Skip
            if wire_type == 0:
                _, offset = read_varint(data, offset)
            elif wire_type == 2:
                _, offset = read_length_delimited(data, offset)
            elif wire_type == 5:
                offset += 4
            elif wire_type == 1:
                offset += 8
    return piece, score, sp_type

def parse_model(model_path):
    """SP model dosyasini parse et, pieces listesini dondur"""
    with open(model_path, "rb") as f:
        data = f.read()

    pieces = []
    offset = 0
    while offset < len(data):
        field_num, wire_type, offset = read_tag(data, offset)
        if field_num == 1 and wire_type == 2:
            # SentencePiece message
            payload, offset = read_length_delimited(data, offset)
            piece, score, sp_type = parse_sentencepiece(payload)
            pieces.append((piece, score, sp_type))
        else:
            # Diger fieldlari atla
            if wire_type == 0:
                _, offset = read_varint(data, offset)
            elif wire_type == 2:
                _, offset = read_length_delimited(data, offset)
            elif wire_type == 5:
                offset += 4
            elif wire_type == 1:
                offset += 8
            else:
                # Bilinmeyen wire type
                break
    return pieces

# ============================================================
# 2. Manuel decode
# ============================================================
def manual_decode_ids(ids, pieces):
    """SentencePiece BPE decode — ▁ -> space, gerisini birlestir"""
    # SP type'lar:
    # 0 = UNDEFINED
    # 1 = NORMAL  → kullanilir
    # 2 = UNKNOWN → "<unk>"
    # 3 = CONTROL → "<s>", "</s>" → atilir decode'da
    # 4 = USER_DEFINED → kullanilir
    # 5 = BYTE     → byte fallback (0x00..0xFF)
    # 6 = UNUSED   → atilir

    text_parts = []
    for tid in ids:
        if tid >= len(pieces):
            continue
        piece, score, sp_type = pieces[tid]
        if sp_type in (3, 6):  # CONTROL veya UNUSED
            continue
        text_parts.append(piece)

    # Tum piece'leri birlestir
    raw = "".join(text_parts)
    # SP'nin space markeri: ▁ (U+2581)
    decoded = raw.replace("▁", " ").strip()
    return decoded

# ============================================================
# 3. Test
# ============================================================
def main():
    print(f"SP model: {SP_MODEL}")

    # Manuel parse
    print("Manuel protobuf parse...")
    pieces = parse_model(SP_MODEL)
    print(f"  {len(pieces)} piece bulundu")
    print(f"  Ilk 5: {pieces[:5]}")
    print(f"  Son 5: {pieces[-5:]}")

    # Resmi sentencepiece ile karsilastir
    print(f"\nResmi sentencepiece ile karsilastirma...")
    sp = spm.SentencePieceProcessor()
    sp.load(str(SP_MODEL))
    print(f"  vocab_size: {sp.get_piece_size()}")

    if len(pieces) != sp.get_piece_size():
        print(f"  HATA: Piece sayisi farkli! Manual={len(pieces)}, SP={sp.get_piece_size()}")
        return

    # ID by ID karsilastir
    diffs = 0
    for i in range(len(pieces)):
        manual_piece = pieces[i][0]
        sp_piece = sp.id_to_piece(i)
        if manual_piece != sp_piece:
            diffs += 1
            if diffs <= 5:
                print(f"  Fark ID={i}: manual='{manual_piece}' sp='{sp_piece}'")
    print(f"  Toplam fark: {diffs}/{len(pieces)}")

    if diffs > 0:
        print("  Manuel parse'da hata var, durduruluyor")
        return
    print(f"  ✓ Tum ID'ler ayni piece'a maplanmis")

    # ============================================================
    # Decode test — gercek bir transkripsiyon kullanip karsilastir
    # ============================================================
    import json
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf

    ONNX_PATH = HOME / "projects" / "quran-asr" / "onnx" / "fastconformer_full.onnx"
    META_PATH = HOME / "projects" / "quran-asr" / "onnx" / "fastconformer_full.json"
    TEST_WAV = HOME / "projects" / "benchmark" / "benchmark_workspace" / "dataset" / "clips" / "base_005.wav"

    print(f"\nGercek inference ile decode testi...")
    audio, _ = sf.read(str(TEST_WAV))
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    audio = audio.astype(np.float32)

    sess = ort.InferenceSession(str(ONNX_PATH), providers=['CPUExecutionProvider'])
    result = sess.run(None, {
        "audio_signal": audio[np.newaxis, :].astype(np.float32),
        "length": np.array([audio.shape[0]], dtype=np.int64),
    })
    pred_ids = result[0][0].argmax(axis=-1)

    with open(META_PATH) as f:
        meta = json.load(f)
    blank_idx = meta["blank_idx"]

    decoded_ids = []
    prev = -1
    for tid in pred_ids:
        if tid != blank_idx and tid != prev:
            decoded_ids.append(int(tid))
        prev = tid

    sp_text = sp.decode_ids(decoded_ids)
    manual_text = manual_decode_ids(decoded_ids, pieces)

    print(f"\nSP decode:    {sp_text[:120]}{'...' if len(sp_text) > 120 else ''}")
    print(f"Manual decode: {manual_text[:120]}{'...' if len(manual_text) > 120 else ''}")
    print(f"\nEsit mi: {'EVET ✓' if sp_text == manual_text else 'HAYIR ✗'}")

    if sp_text != manual_text:
        # Detayli
        print(f"\nUzunluk: SP={len(sp_text)}, Manual={len(manual_text)}")
        for i, (a, b) in enumerate(zip(sp_text, manual_text)):
            if a != b:
                print(f"  Ilk fark karakter {i}: '{a}' (U+{ord(a):04X}) vs '{b}' (U+{ord(b):04X})")
                print(f"  SP:     ...{sp_text[max(0,i-10):i+10]}...")
                print(f"  Manual: ...{manual_text[max(0,i-10):i+10]}...")
                break
        else:
            print(f"  Karakterler ayni ama uzunluk farkli")
            print(f"  SP fazla:     '{sp_text[len(manual_text):]}'")
            print(f"  Manual fazla: '{manual_text[len(sp_text):]}'")

    # Manuel decode'un her id icin output'unu yazdir
    print(f"\n--- Ilk 30 token (manual vs SP) ---")
    for i, tid in enumerate(decoded_ids[:30]):
        manual_piece = pieces[tid][0]
        sp_piece = sp.id_to_piece(tid)
        sp_decode = sp.decode_ids([tid])
        match = "✓" if manual_piece == sp_piece else "✗"
        print(f"  [{i:3d}] ID={tid:5d} {match} piece='{manual_piece}' SP_decode='{sp_decode}'")

if __name__ == "__main__":
    main()
