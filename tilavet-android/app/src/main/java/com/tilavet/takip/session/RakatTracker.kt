package com.tilavet.takip.session

/**
 * Rekat sayaci + kaba durus gostergesi (UI; state machine'i etkilemez). Fikir taraweeh-companion-g2'deki rekat
 * takibinden; bizim gercek cami kayitlarimiza gore sadelestirildi.
 *
 * Neden sadece bu sinyaller: 4 gercek namaz kaydinda (2 aksam, 2 cuma) telefonun duydugu seste tekbirler ASR'de
 * cogunlukla bos / uydurma ("شركة الهدى") — aksamda 0, aksam #2'de 1 tekbir tanindi; semiallah cumalarda 4 rukûnun
 * 3'unde, aksamlarda sadece sessiz 3. rekatta bir kez duyuldu. Guvenilir olanlar:
 *   - Sesli rekatin Fatiha'si (her kayitta, kilit 4-7 sn) → yeni rekat
 *   - Selam (her kayitta) → namaz bitti
 *   - Semiallah (duyulursa) → rukû; okuma bittikten [SILENT_RAKAT_AFTER_SEC] sn'den sonra gelen semiallah ayni
 *     rekatin rukûsu olamaz (rukû okumanin hemen ardindan) → sessiz rekat (aksamin 3., yatsinin 3-4. rekati)
 * Tekbir sayarak durus (secde / celse / oturus) cikarmak bu veriyle guvenilir degil → durus kaba: kiyam (okuma) /
 * rukû-secde (semiallah ya da okuma [POST_RECITATION_SEC] sn sustu) / sessiz bolum (son olaydan [SILENT_PHASE_SEC] sn
 * sonra: oturus ya da sessiz rekat — hangisi bilinmiyor, rekat "N. REKÂT SONRASI" yazilir) / selam.
 *
 * Kayit basladiginda rekat bilinmiyorsa (namazin ortasi; Fatiha'siz ilk kilit) sayi gosterilmez, ilk Fatiha'dan baslar.
 * Okunan zammin hemen ardindan semiallah geldiyse (kayit sesli bir rekatin zammi ortasinda basladi) sonraki Fatiha 2. rekat
 * (yatsi 25.10: Bakara 2:104-107 → semiallah → Fatiha "1. rekat" sayiliyordu; sesli rekatlar 1-2, 2. rekatin rukûsundan
 * sonra sesli Fatiha ancak selamdan sonra — yeni namaz — gelir).
 * Teravih / ardisik namazlar: selamdan sonraki Fatiha yeni namazin 1. rekati; oturum toplami ayrica tutulur.
 * Android'e bagli degil (JVM'de gercek kayitlarin transkriptleriyle test edilir).
 */
class RakatTracker {
    enum class Posture { KIYAM, RUKU_SECDE, SESSIZ, SELAM }

    companion object {
        /** Okumadan bu kadar sn sonra gelen semiallah sessiz bir rekatin rukûsu (cuma kayitlarinda okuma sonu → semiallah 9-13 sn). */
        const val SILENT_RAKAT_AFTER_SEC = 40.0
        /** Ayni semiallahin ardisik parcalarda tekrari (iki parcaya bolunme) tek sayilir. */
        const val SEMIALLAH_DEDUP_SEC = 15.0
        /** Ayni rekatta Fatiha kilidinin tekrari (kayip → yeniden kilit) yeni rekat sayilmaz. */
        const val MIN_RAKAT_SEC = 25.0
        /**
         * Okuma bu kadar sn sustuysa durus rukû/secde gosterilir (15 sn'de cuma'da zamm basindaki tanima boslugu
         * 18 sn "rukû" gosterdi; gercek rukû okuma bitince 5-13 sn icinde).
         */
        const val POST_RECITATION_SEC = 25.0
        /**
         * Son olaydan (okuma / semiallah) bu kadar sn sonra "sessiz bolum": oturus mu sessiz rekat mi bilinmiyor
         * (cuma: semiallah → selam 75 sn; aksam: 2. rekat okumasi → selam 150 sn, arada sessiz 3. rekat).
         */
        const val SILENT_PHASE_SEC = 70.0
        /** Selamdan sonra etiket bu kadar sn gorunur. */
        const val SELAM_SHOW_SEC = 20.0
        /**
         * Okumadan bu kadar sn icinde gelen selam yok sayilir: gercek selam tesehhudden sonra gelir (son okumadan 60-150 sn:
         * aksam, cuma kayitlari). Hani Rifai teravihinde (dis kaynak) Hicr 15:4 okunurken kisa duraklamada ASR
         * "السلام عليكم" uydurdu → namaz bitti sayilip rekat sayaci sifirlaniyordu (state machine kilitliyken selami
         * zaten yok sayiyor).
         */
        const val SELAM_MIN_AFTER_RECITATION_SEC = 20.0
        /**
         * Semiallah duyulmadiysa sessiz rekatlar sayilamiyor → selamda son okumadan gecen sureden tahmin. Son okuma → selam
         * (parca sonu zamanlari): 2 rekatli gercek cumalar 90-100 sn, sentetik namaz / teravih / hatim 95-125 sn, bilesik
         * teravih 85-95 sn; 3 rekatli aksamlar 140 / 150 sn; 4 rekatli yatsilar 240 / 250 sn. Yatsi #2 (20.10): hicbir semiallah
         * taninmadi, sayac "2 rekat" dedi; aksam #2 de "2 rekat". Bu kadar sn ve ustu → 1 / 2 sessiz rekat (125 denendi:
         * sentetik teravihte 125 sn'lik 2 rekatli namaz 3 sayildi).
         */
        const val SILENT_ONE_RAKAT_SEC = 132.0
        const val SILENT_TWO_RAKAT_SEC = 195.0
    }

    /** Su anki namazin rekati (0 = bilinmiyor / namaz yok). */
    var rakat = 0
        private set
    var posture: Posture? = null
        private set
    /** Bu oturumda selamla biten namazlarin rekatlari (teravih / ardisik namaz toplami). */
    var completedTotal = 0
        private set
    /** Bu oturumda selamla biten (rekati bilinen) namaz sayisi — toplam ancak ikinci namazdan itibaren gosterilir. */
    var completedNamaz = 0
        private set

    private var rukuDone = false
    private var lastRecitationSec = Double.NEGATIVE_INFINITY
    private var lastSemiallahSec = Double.NEGATIVE_INFINITY
    private var rakatStartSec = Double.NEGATIVE_INFINITY
    private var selamSec: Double? = null
    private var maxFatihaAyah = 0
    /** Rekat bilinmezken (kayit namaz ortasinda basladi) okunan zammin ardindan semiallah: sonraki Fatiha 2. rekat. */
    private var midRuku = false

    fun reset() {
        rakat = 0; posture = null; completedTotal = 0; completedNamaz = 0
        rukuDone = false
        lastRecitationSec = Double.NEGATIVE_INFINITY
        lastSemiallahSec = Double.NEGATIVE_INFINITY
        rakatStartSec = Double.NEGATIVE_INFINITY
        selamSec = null
        maxFatihaAyah = 0
        midRuku = false
    }

    /**
     * Her parca sonucundan sonra cagrilir. [t] parcanin oturumdaki bitis zamani (sn).
     * @return log icin olay aciklamasi ("2. rekat (Fatiha)", "sessiz rekat 3 (semiallah)", "selam"...) ya da null
     */
    fun onChunk(r: ChunkResult, t: Double): String? {
        if (r.kamet) {
            val had = rakat > 0 || posture != null
            rakat = 0; posture = null; rukuDone = false; maxFatihaAyah = 0; midRuku = false
            rakatStartSec = Double.NEGATIVE_INFINITY
            return if (had) "kamet: yeni namaz" else null
        }
        val signal = r.text?.let { StateMachine.namazSignal(it) }
        if (signal == "selam") {
            if (rakat == 0 && posture == Posture.SELAM) return null   // selamin ikinci tarafi
            if (t - lastRecitationSec < SELAM_MIN_AFTER_RECITATION_SEC) return null   // okuma arasinda uydurma selam
            // Sessiz rekatlar (semiallah duyulmadiysa) okuma → selam suresinden — bkz. SILENT_ONE_RAKAT_SEC
            val gap = t - lastRecitationSec
            val estimated = when {
                rakat < 2 -> rakat
                gap >= SILENT_TWO_RAKAT_SEC -> 4
                gap >= SILENT_ONE_RAKAT_SEC -> 3
                else -> 2
            }
            val ended = maxOf(rakat, estimated)
            if (ended > 0) { completedTotal += ended; completedNamaz += 1 }
            rakat = 0; posture = Posture.SELAM; selamSec = t; rukuDone = false; maxFatihaAyah = 0; midRuku = false
            rakatStartSec = Double.NEGATIVE_INFINITY
            return "selam (namaz bitti${if (ended > 0) ", $ended rekat" else ""})"
        }
        if (signal == "ruku") {
            if (t - lastSemiallahSec < SEMIALLAH_DEDUP_SEC) return null
            lastSemiallahSec = t
            if (rakat == 0) {
                // Rekat bilinmiyor (namazin ortasindan basladi): sadece durus; okumanin hemen ardindansa sesli rekatin rukûsu
                posture = Posture.RUKU_SECDE
                if (t - lastRecitationSec <= SILENT_RAKAT_AFTER_SEC) {
                    midRuku = true
                    return "semiallah (rekat bilinmiyor, okumadan sonra: sonraki Fatiha 2. rekat)"
                }
                return "semiallah (rekat bilinmiyor)"
            }
            posture = Posture.RUKU_SECDE
            return if (!rukuDone && t - lastRecitationSec <= SILENT_RAKAT_AFTER_SEC) {
                rukuDone = true
                "$rakat. rekat rukû (semiallah)"
            } else {
                rakat += 1
                rukuDone = true
                rakatStartSec = t
                "sessiz rekat: $rakat. rekat (semiallah, okumadan ${"%.0f".format(t - lastRecitationSec)} sn sonra)"
            }
        }
        val reciting = r.status == ChunkStatus.MATCHED &&
            (r.state == NamazState.FATIHA || r.state == NamazState.ZAMM)
        if (!reciting) return null
        lastRecitationSec = t
        posture = Posture.KIYAM
        selamSec = null
        if (r.state != NamazState.FATIHA) return null
        // Fatiha: yeni rekat mi? Fatiha'ya giris (onceki durum FATIHA degil) ya da FATIHA icinde basa donus
        // (onceki rekatin zammi / rukûsu kilit kaybettirmeden kacirildiysa)
        val firstAyah = r.verses?.getOrNull(r.gapFilled)?.ayah ?: 1
        val restart = r.stateBefore == NamazState.FATIHA && firstAyah <= 2 && maxFatihaAyah >= 5
        val enter = r.stateBefore != NamazState.FATIHA
        var event: String? = null
        if ((enter || restart) && t - rakatStartSec >= MIN_RAKAT_SEC) {
            rakat = if (rakat == 0 && midRuku) 2 else rakat + 1
            midRuku = false
            rukuDone = false
            rakatStartSec = t
            maxFatihaAyah = 0
            event = "$rakat. rekat (Fatiha)"
        }
        maxFatihaAyah = maxOf(maxFatihaAyah, r.verses?.lastOrNull()?.ayah ?: firstAyah)
        return event
    }

    /** Durus, zamana gore (okuma sustuysa rukû/secde, uzun sessizlikte sessiz bolum). */
    fun postureAt(t: Double): Posture? {
        val since = t - maxOf(lastRecitationSec, lastSemiallahSec)
        return when {
            posture == Posture.SELAM -> if (selamSec != null && t - selamSec!! > SELAM_SHOW_SEC) null else Posture.SELAM
            (posture == Posture.KIYAM || posture == Posture.RUKU_SECDE) && since >= SILENT_PHASE_SEC -> Posture.SESSIZ
            posture == Posture.KIYAM && t - lastRecitationSec >= POST_RECITATION_SEC -> Posture.RUKU_SECDE
            else -> posture
        }
    }

    /**
     * Ust bantta gosterilecek etiket ("2. REKÂT · KIYAM", "2. REKÂT · RÜKÛ / SECDE", "2. REKÂT SONRASI · SESSİZ",
     * "SELAM · TOPLAM 8"); null = gosterme.
     */
    fun label(t: Double): String? {
        val p = postureAt(t)
        return when {
            p == Posture.SELAM -> "SELAM" + if (completedNamaz >= 2) " · TOPLAM $completedTotal" else ""
            rakat == 0 -> null
            else -> buildString {
                append("$rakat. REKÂT")
                when (p) {
                    Posture.KIYAM -> append(" · KIYAM")
                    Posture.RUKU_SECDE -> append(" · RÜKÛ / SECDE")
                    Posture.SESSIZ -> append(" SONRASI · SESSİZ")
                    else -> Unit
                }
                if (completedNamaz >= 1) append(" · TOPLAM ${completedTotal + rakat}")
            }
        }
    }
}
