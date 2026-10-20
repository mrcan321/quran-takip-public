package com.tilavet.takip.asr

import java.io.InputStream

/**
 * SentencePiece BPE Tokenizer Decoder (manuel protobuf parser).
 *
 * Bu sinif SentencePiece native library'sine ihtiyac duymaz.
 * Tokenizer.model dosyasini direkt parse eder ve decode_ids ile
 * token ID'leri orijinal Arapca metne cevirir.
 *
 * Python tarafindaki sp_manual_decoder.py ile birebir aynidir
 * ve resmi sentencepiece library'si ile bit-perfect karsilastirilmistir.
 */
class SentencePieceDecoder private constructor(
    private val pieces: Array<Piece>
) {

    /** Bir SentencePiece piece — text + score + type */
    private data class Piece(
        val text: String,
        val score: Float,
        val type: Int,
    ) {
        // SP type degerleri:
        //   0 = UNDEFINED
        //   1 = NORMAL
        //   2 = UNKNOWN ("<unk>")
        //   3 = CONTROL (<s>, </s>) - decode'da atilir
        //   4 = USER_DEFINED
        //   5 = BYTE (byte fallback)
        //   6 = UNUSED - decode'da atilir
        val isPrintable: Boolean get() = type != 3 && type != 6
    }

    val vocabSize: Int get() = pieces.size

    /** Verilen token ID listesini orijinal text'e cevirir. */
    fun decode(ids: IntArray): String {
        val sb = StringBuilder()
        for (id in ids) {
            if (id < 0 || id >= pieces.size) continue
            val p = pieces[id]
            if (!p.isPrintable) continue
            sb.append(p.text)
        }
        // SentencePiece space marker: ▁ (U+2581 LOWER ONE EIGHTH BLOCK)
        return sb.toString().replace(SP_SPACE, ' ').trim()
    }

    fun decode(ids: List<Int>): String = decode(ids.toIntArray())

    /** Debug icin — tek bir id'nin hangi piece'a karsilik geldigini dondurur */
    fun pieceAt(id: Int): String? = pieces.getOrNull(id)?.text

    companion object {
        private const val SP_SPACE = '▁'  // U+2581

        // Protobuf wire types
        private const val WIRE_VARINT = 0
        private const val WIRE_FIXED64 = 1
        private const val WIRE_LENGTH_DELIMITED = 2
        private const val WIRE_FIXED32 = 5

        /**
         * Tokenizer.model dosyasini parse edip Decoder olusturur.
         * Dosya formati: SentencePiece ModelProto protobuf.
         */
        fun fromInputStream(input: InputStream): SentencePieceDecoder {
            val data = input.readBytes()
            val pieces = parseModel(data)
            return SentencePieceDecoder(pieces.toTypedArray())
        }

        // ============================================================
        // Protobuf parser — sadece pieces (field 1) okunuyor
        // ============================================================
        private fun parseModel(data: ByteArray): List<Piece> {
            val pieces = mutableListOf<Piece>()
            var offset = 0
            while (offset < data.size) {
                val (tag, newOffset) = readVarint(data, offset)
                offset = newOffset
                val fieldNum = (tag shr 3).toInt()
                val wireType = (tag and 0x07L).toInt()

                if (fieldNum == 1 && wireType == WIRE_LENGTH_DELIMITED) {
                    // SentencePiece submessage
                    val (len, off2) = readVarint(data, offset)
                    offset = off2
                    val msgLen = len.toInt()
                    val piece = parseSentencePiece(data, offset, msgLen)
                    pieces.add(piece)
                    offset += msgLen
                } else {
                    // Skip diger field'lar
                    offset = skipField(data, offset, wireType)
                }
            }
            return pieces
        }

        private fun parseSentencePiece(data: ByteArray, start: Int, length: Int): Piece {
            var offset = start
            val end = start + length
            var text = ""
            var score = 0f
            var type = 1  // NORMAL default

            while (offset < end) {
                val (tag, newOffset) = readVarint(data, offset)
                offset = newOffset
                val fieldNum = (tag shr 3).toInt()
                val wireType = (tag and 0x07L).toInt()

                when {
                    fieldNum == 1 && wireType == WIRE_LENGTH_DELIMITED -> {
                        // piece text
                        val (len, off2) = readVarint(data, offset)
                        offset = off2
                        val sLen = len.toInt()
                        text = String(data, offset, sLen, Charsets.UTF_8)
                        offset += sLen
                    }
                    fieldNum == 2 && wireType == WIRE_FIXED32 -> {
                        // score (float32 little-endian)
                        score = java.lang.Float.intBitsToFloat(readInt32LE(data, offset))
                        offset += 4
                    }
                    fieldNum == 3 && wireType == WIRE_VARINT -> {
                        val (typeVal, off2) = readVarint(data, offset)
                        type = typeVal.toInt()
                        offset = off2
                    }
                    else -> {
                        offset = skipField(data, offset, wireType)
                    }
                }
            }

            return Piece(text, score, type)
        }

        // Protobuf helpers
        private fun readVarint(data: ByteArray, start: Int): Pair<Long, Int> {
            var result = 0L
            var shift = 0
            var offset = start
            while (true) {
                if (offset >= data.size) throw IllegalArgumentException("Varint okuma sirasinda dosya sonu")
                val b = data[offset].toInt() and 0xFF
                offset++
                result = result or ((b.toLong() and 0x7F) shl shift)
                if ((b and 0x80) == 0) break
                shift += 7
                if (shift >= 64) throw IllegalArgumentException("Varint cok uzun")
            }
            return Pair(result, offset)
        }

        private fun readInt32LE(data: ByteArray, offset: Int): Int {
            return (data[offset].toInt() and 0xFF) or
                    ((data[offset + 1].toInt() and 0xFF) shl 8) or
                    ((data[offset + 2].toInt() and 0xFF) shl 16) or
                    ((data[offset + 3].toInt() and 0xFF) shl 24)
        }

        private fun skipField(data: ByteArray, start: Int, wireType: Int): Int {
            return when (wireType) {
                WIRE_VARINT -> readVarint(data, start).second
                WIRE_FIXED32 -> start + 4
                WIRE_FIXED64 -> start + 8
                WIRE_LENGTH_DELIMITED -> {
                    val (len, off) = readVarint(data, start)
                    off + len.toInt()
                }
                else -> throw IllegalArgumentException("Bilinmeyen wire type: $wireType")
            }
        }
    }
}
