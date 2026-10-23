package com.tilavet.takip.session

import com.tilavet.takip.aligner.AlignmentMatch
import com.tilavet.takip.aligner.Aligner
import com.tilavet.takip.aligner.Normalizer
import com.tilavet.takip.aligner.QuranIndex
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Namaz akış state machine'i — server/app.py'deki process_chunk + transition_state +
 * compute_preferred_range fonksiyonlarinin Kotlin port'u.
 *
 * Saf mantik: audio almaz, ASR cagirmaz. Verilen transkripsiyon ve audio_rms
 * uzerinden state degisikligini hesaplar.
 *
 * Asıl chunk islemesi:
 *   processChunk(rms, transcribedText, chunkIndex, state) → ChunkResult
 *
 * State'i mutate eder (Python ile birebir davranis).
 */
class StateMachine(
    private val index: QuranIndex,
    private val aligner: Aligner,
) {

    // Lazy build: ayah → corpus range, surah → ayah count
    // Python'daki AYAH_TO_CORPUS_RANGE ve SURAH_AYAH_COUNTS dict'leri ile birebir.
    // (eskiden iki lazy ayri ayri 78K getWord ile iki kez kuruyordu — tek geciste, string uretmeden)
    private val ayahMaps: Pair<Map<Pair<Int, Int>, Pair<Int, Int>>, Map<Int, Int>> by lazy { buildAyahMaps() }
    private val ayahToCorpusRange: Map<Pair<Int, Int>, Pair<Int, Int>> get() = ayahMaps.first
    private val surahAyahCounts: Map<Int, Int> get() = ayahMaps.second
    private fun buildAyahMaps(): Pair<Map<Pair<Int, Int>, Pair<Int, Int>>, Map<Int, Int>> {
        val rangeMap = HashMap<Pair<Int, Int>, IntArray>()
        val ayahCountMap = HashMap<Int, Int>()
        for (i in 0 until index.wordCount) {
            val sa = index.getSurahAyah(i)
            val surah = sa ushr 16
            val ayah = sa and 0xFFFF
            val key = Pair(surah, ayah)
            val range = rangeMap[key]
            if (range == null) {
                rangeMap[key] = intArrayOf(i, i)
            } else {
                range[1] = i
            }
            val prev = ayahCountMap[surah] ?: 0
            if (ayah > prev) ayahCountMap[surah] = ayah
        }
        val final = rangeMap.mapValues { (_, arr) -> Pair(arr[0], arr[1]) }
        return Pair(final, ayahCountMap)
    }

    /**
     * Korpusta 1. ayetlerin basindaki besmele kelimelerinin pozisyonlari (Fatiha, Tevbe haric).
     * Sadece besmeleye oturan eslesme sure gecisi sayilmaz (Python besmele_positions ile birebir).
     */
    private val besmelePositions: HashSet<Int> by lazy {
        val set = HashSet<Int>()
        for ((key, range) in ayahToCorpusRange) {
            val (su, ay) = key
            if (ay == 1 && su != 1 && su != 9 && range.second - range.first + 1 > 4 &&
                (0 until 4).all { k -> index.getNormalized(range.first + k) == BESMELE_NORMALIZED[k] }
            ) {
                for (k in 0 until 4) set.add(range.first + k)
            }
        }
        set
    }

    /**
     * Korpustaki tum normalize edilmiş token'lar (Python: CORPUS_VOCAB = corpus.vocab).
     * scoreTranscription icin vocab_coverage hesaplamada kullanilir.
     *
     * quran.bin'deki normalized alan imla'i karsiliktir; bazen iki kelime olur
     * ("يا ايها") → ASR token'lari tek tek geldigi icin bosluktan bolup ekliyoruz.
     */
    private val corpusVocab: HashSet<String> by lazy {
        val set = HashSet<String>(index.wordCount)
        for (i in 0 until index.wordCount) {
            // QuranIndex.getNormalized(i) ile direkt al — Normalizer'a gerek yok
            val normalized = index.getNormalized(i)
            for (part in normalized.split(' ')) {
                if (part.isNotEmpty()) set.add(part)
            }
        }
        set
    }


    /** Korpusun normalize kelime dizisi (imla'i iki kelimelik kayitlar bolunmus) — phraseCount icin. */
    private val corpusTokens: Array<String> by lazy {
        val list = ArrayList<String>(index.wordCount + 512)
        for (i in 0 until index.wordCount) {
            for (part in index.getNormalized(i).split(' ')) {
                if (part.isNotEmpty()) list.add(part)
            }
        }
        list.toTypedArray()
    }

    /** Normalize kelime dizisi korpusta birebir kac kez geciyor (limit'te durur). Python phrase_count. */
    private fun phraseCount(phrase: List<String>, limit: Int = 2): Int {
        if (phrase.isEmpty()) return 0
        val toks = corpusTokens
        val n = phrase.size
        var c = 0
        for (i in 0..toks.size - n) {
            if (toks[i] != phrase[0]) continue
            var all = true
            for (k in 1 until n) if (toks[i + k] != phrase[k]) { all = false; break }
            if (all) {
                c++
                if (c >= limit) break
            }
        }
        return c
    }

    /** Runtime'da degistirilebilen tuner ayarlari. Default: orta seviye. */
    @Volatile
    var minConfidence: Double = 50.0
    @Volatile
    var minConfidenceFirstLock: Double = 70.0

    companion object {
        // app.py konfigurasyonu — degismeyenler
        const val MIN_RMS_ENERGY = 0.005
        const val MIN_WORD_COUNT_COLD = 3
        const val MIN_WORD_COUNT_HOT = 2
        // eval: 4 → 3 ile yavas okunan chunk'lar (tertil: 5 sn'de 3 kelime) kilit verir, yanlis kilit yok
        const val MIN_WORD_COUNT_FIRST_LOCK = 3

        const val PREFERRED_AYAH_WINDOW_BASE = 2
        const val PREFERRED_AYAH_WINDOW_MAX = 6
        const val PREFERRED_AYAH_WINDOW_ARA = 3

        const val ABANDON_LOCK_AFTER_LOST = 6
        const val PENDING_VERIFY_AYAH_WINDOW = 4

        const val ARA_AFTER_LOST_CHUNKS = 12
        const val MAX_GAP_FILL = 3

        val FATIHA_WORD_RANGE = 0..30
        // Fatiha icinde geri gidilmez: pencere son eslesmenin bu kadar kelime gerisinden baslar. "الرحمن الرحيم"
        // hem 1:1'de (besmele) hem 1:3'te — 1:2'den sonra 1:1'e eslesip ekran geri zipliyordu (telefon, APK #15)
        const val FATIHA_BACK_WORDS = 3

        // Fatiha'nin bu ayetinden sonra (6-7) pencere disi guclu eslesme = zamm suresine gecis (hemen)
        const val FATIHA_END_AYAH = 6
        // Kilitliyken pencere skoru bunun altindaysa tum Kuran'da da ara (sure gecisi / pencere cop eslesmesi)
        const val JUMP_SEARCH_BELOW = 80.0
        // Pencere disindaki eslesme pencereden en az bu kadar iyi olmali
        const val JUMP_MARGIN = 15.0
        // Namazda sesli okunan ilk sey Fatiha: BEKLEME'de Fatiha basina (1:1-3) bu kadar guclu eslesme
        // (skor ve kelime) dogrulama beklemeden kilit verir (~5 sn erken). 3 kelime → ilahi yanlis kilit.
        const val FATIHA_FAST_LOCK_MIN_SCORE = 90.0
        const val FATIHA_FAST_LOCK_MIN_WORDS = 4
        // Kilit kaybolduktan sonra (rukû/secde/sessiz rekat) yeniden kilit ilk kilit gibi dogrulamali; istisnalar:
        // rekat basi Fatiha (herhangi bir ayet, skor >= FATIHA_FAST_LOCK_MIN_SCORE, >= MIN_WORD_COUNT_FIRST_LOCK
        // kelime) ve kalinan yerden devam (ayni sure, son ayetin -RESUME_BACK..+PREFERRED_AYAH_WINDOW_ARA arasi)
        const val RESUME_BACK = 2
        // Dogal gecis noktasinda (Fatiha sonu / sure sonu) yavas okumada parcaya 2 kelime sigiyor ("لإيلاف قريش",
        // "أعطيناك الكوثر"); sure atlamasi 3 kelime istedigi icin gecis bir parca gecikiyordu (Kureys 13 sn, hibrit).
        // 2 kelimelik parca da atlayabilir: ifade Kuran'da TEK yerde gecmeli (normalize, birebir), skor >=
        // JUMP_SHORT_MIN_SCORE ve hedef dogal gecis olmali. Cok yerde gecen ifade ("ولقد ارسلنا", "الرحمن الرحيم")
        // 3 kelimeyi bekler.
        const val JUMP_SHORT_WORDS = 2
        const val JUMP_SHORT_MIN_SCORE = 90.0
        // Dogal gecis (Fatiha sonu → zamm, sure sonu → sure basi) dogrulamasiz gecer, ama skor bunun altindaysa
        // sadece aday. Cuma namazi (02.10): Fatiha sonrasi "لا يسمعون عصيس" (21:102, ASR bozuk) → 7:100 (74.5) dogal
        // gecis sayilip yanlis kilit + 30 sn yapiskan pencere. Eval'deki 28 dogal gecisin hepsi dogru, en dusugu 79.3
        // (Kevser sonu → "قل أعوذ برب الفحص" 113:1) → esik ikisinin arasinda.
        const val NATURAL_MIN_SCORE = 77.0
        // Sure basi (cuma #2, 09.10): Fatiha sonrasi zamm basi ASR'de bozuk geliyor — "ألهاكم التجاد" (الهاكم التكاثر
        // 102:1), "والعص إن الإنسان لعام" (والعصر ان الانسان لفي خسر 103:1-2). Hizalama dogru yere 85 / 92 veriyor ama
        // scoreTranscription Kuran sozlugunde olmayan kelimeler icin ceza kesiyor (60 / 65) → gecis reddedildi, sure 2. /
        // 3. ayetinde kilitlendi (7 / 11.5 sn gec, surenin basi ekranda hic gorunmedi). Gecis noktasinda
        // (atTransitionPoint) hizalama bir surenin ACILISINDAN basliyorsa (1. ayetin besmele disi ilk
        // OPENING_START_SLACK+1 kelimesi) ham hizalama skoru (fuzzy, sozluk cezasiz) >= OPENING_MIN_FUZZY yeter →
        // dogal gecis. Imam zamm'i cogunlukla sure basindan okur; aday kumesi 114 sure acilisi oldugu icin ceza
        // olmadan da secici (eval: esik 65-85 arasi ayni sonuc, zorlama testlerinde yanlis kilit artmadi).
        const val OPENING_MIN_FUZZY = 75.0
        const val OPENING_START_SLACK = 1
        // Iki surenin acilisi ayni ifadeyse ("قل أعوذ برب" 113:1 / 114:1) dogal gecis tahmin etmez: eslesme bir sure
        // acilisi, baska suredeki ikinci yer de bir sure acilisi ve ham hizalama farki bundan azsa gecis adayi olur,
        // sonraki parca karar verir (cuma #3, 16.10: 2. rekatta Nas'in ilk parcasi Felak'a dogal gecis sayilip
        // kilitlendi). Her yakin ikinci yere genellemek denendi (fark < 2: 97 dogal gecisin 3 yanlisini yakaliyordu) ama
        // ayni metnin iki yerde gectigi dogru gecisleri de bekletiyordu (2:255 / 3:2, 14:1 / 38:29); hibritte Ayetel
        // Kursi'nin devami kisa parcalarla dogrulanamadi, "لا تدري" 65:1'e kilitlendi.
        const val OPENING_TIE_MARGIN = 2.0
        // Fatiha sonundaki dogal geciste en iyi eslesme ayet ortasindan basliyorsa ve ayet basindan baslayan ikinci yer en
        // fazla bu kadar geride ise ikincisi alinir: imam zamm'a ayet basindan baslar (yatsi 19.10, sabit parca:
        // "الذين اتخذوا دينهم" 6:70 ortasina gecti, okunan 7:51 basi; 2 parca yanlis kilit)
        const val AYAH_START_TIE_MARGIN = 2.0
        // Huruf-u mukattaa (1. ayetin ilk kelimesi, normalize): ASR cogu zaman yazmiyor ("الر تلك آيات الكتاب المبين" →
        // "تلك آيات الكتاب المبين") — ayet basi sayilirken atlanabilir (Rifai Yusuf 12:1 26:2'ye gecmesin)
        val MUQATTAAT = setOf("الم", "المص", "الر", "المر", "كهيعص", "طه", "طسم", "طس", "يس", "ص", "حم", "ق", "ن")
        // Hatimle teravih: Fatiha'dan sonra imam onceki rekatin kaldigi yerden devam eder. Fatiha sonundaki gecis
        // aramasinda devam penceresi (son zamm konumu .. +CONTINUE_AHEAD ayet, sure biterse sonraki surenin basina tasar)
        // tum Kuran eslesmesinden en fazla CONTINUE_MARGIN kotu ve >= NATURAL_MIN_SCORE ise devam secilir. Son zamm konumu
        // selam / kamette silinmez. Normal namazda da ise yariyor: 2. rekatta cogunlukla mushaf sirasiyla sonraki sure
        // okunur (cuma #3: Felak → Nas, "قل أعوذ برب" 113:1 / 114:1 esitligi 114:1 lehine, Nas 12.3 → 3.2 sn).
        const val CONTINUE_AHEAD = 6
        const val CONTINUE_MARGIN = 2.0
        // Devam onceligi: devam penceresi >= ilk kilit esigi ve tum Kuran'daki en iyi yerden en fazla CONTINUE_PRIOR_MARGIN kotu
        // ise, en iyi yer bir sure acilisi degilse devam secilir. Yatsi 21.10: 1. rekat Enbiya 21:23'te bitti, 2. rekat
        // "أَمِ اتَّخَذُوا مِن دُونِهِ" (21:24) ASR'de "أم اتطعتم من دونه" → Yunus 10:38'e ("استطعتم من دون الله") 77.3 dogal gecis,
        // devam penceresi 21:24 72.2 (sozluk cezasi) → 2 parca ekranda yanlis sure.
        const val CONTINUE_PRIOR_MARGIN = 6.0
        // Fatiha sonunda sure acilisi onceligi: dogal gecis acilis olmayan bir yere oturduysa, ilk kelimesi parcanin ilk 2
        // kelimesinden biri olan surelerin acilisi (1-2. ayet) ayrica hizalanir; tum Kuran'daki en iyi yerden en fazla bu
        // kadar kotuyse acilis alinir. Aksam 22.10: "قل يا أيها الرحم" 7:158 / 62:6 / 109:1 esit 78.6 → 7:158'e gecti,
        // Kafirun 5 sn gecikti.
        const val OPENING_PREFER_MARGIN = 1.0
        // Taze gecisin yeniden kontrolu: Fatiha sonunda acilis / devam olmayan yere dogal gecisten sonraki FRESH_JUMP_CHUNKS
        // parcada pencere eslesmesi minConfidence altindaysa parca (2 kelime de) tum Kuran'da aranir; en iyi yer baska bir
        // surenin 1-2. ayetinde, >= FRESH_JUMP_MIN_SCORE, pencereden >= JUMP_MARGIN iyi ve gecis parcasinin metni o surenin
        // acilisina >= ilk kilit esigi oturuyorsa (sirali) gecilir. Aksam 22.10: Nasr "إذا جاء نصر الله" ASR'de "فما جاء النصر"
        // → 15:61 ("فلما جاء آل لوط") 90.5, 110:1 75.0; sonraki "والله والفتح" (2 kelime, 110:1 86.7) aranmadi, 20 sn Hicr.
        const val FRESH_JUMP_CHUNKS = 2
        const val FRESH_JUMP_MIN_SCORE = 80.0
        // Erken Fatiha: zamm'da kilit dusmeden, son saglam eslesmeden (>= 3 kelime, >= ilk kilit esigi) bu kadar parca
        // gecmeden gelen ve Fatiha'nin 1-2. ayetinde biten eslesme ("الحمد لله رب العالمين": dua / tesbihatta da gecen, ASR'nin
        // uydurdugu kalip) hemen gecmez, gecis adayi olur; sonraki parca Fatiha'da dogrularsa gecilir. Yeni rekat rukû + iki
        // secdeden sonra gelir (>= ~30 sn). Aksam 22.10: Kafirun 109:6'dan 21 sn sonra semiallah kuyrugu + sessizlik + secde
        // tekbiri basi ASR'de "الحمد لله رب العالمين" → "yeni rekat" Fatiha'si, 2. rekat 31 sn erken. (Zayif / Fatiha'nin
        // ilerisine oturan eslesme denendi: gurultu testinde rukû arasindaki cop eslesmeler gercek 2. Fatiha'yi geciktirdi.)
        const val FATIHA_MIN_GAP_CHUNKS = 6
        const val FATIHA_EARLY_MAX_AYAH = 2
        // Gecis adayi varken (onceki parca) yeni parca adayin +-PENDING_VERIFY_AYAH_WINDOW ayetinde tum Kuran
        // eslesmesinden en fazla bu kadar kotu (ve >= ilk kilit esigi) eslesiyorsa aday dogrulanir. Ortak ifade tum
        // Kuran'da baska yere oturuyordu: Fatiha → bozuk Asr "الإنسان لفيه السوء" (103:2 adayi) → "الذين آمنوا وعملوا"
        // 2:25'e dogal gecis (103:3 ayni skor).
        const val CANDIDATE_WINDOW_MARGIN = 2.0
        // Kuran'da gecen ama namazda / ezan-kamette / sohbette tek basina soylenen ifadeler. Zamm suresi kilitli
        // degilken (BEKLEME / ARA / FATIHA) parca sadece bunlardan biriyse (+ en fazla DHIKR_EXTRA_MAX kelime) bos
        // sayilir: cuma #3'te kametteki "محمد رسول الله" 48:29'a tek parcada kilitlendi (fark payi), "لا اله الا الله"
        // 37:35, "ان شاء الله" 12:99 / 28:27 adayi oluyordu. Tum transkriptlerde (35 kayit, RNNT + CTC) Kuran okunan anda
        // tek ornek asr.wav "والعصر إن شاء الله" (ASR hatasi; teravih bilesiminde Fatiha sonunda 12:99'a dogal gecis olup
        // 6 parca yanlis kilitti). Kelime-i sehadet ("محمد(ا) رسول الله") BEKLEME'de kamet sayilir (ezan/kamet; Fatiha
        // beklemesi + ezan penceresi); bekleme surerken gelen zikir beklemeyi uzatir.
        // Ezan koleksiyonu (dis kaynak): ezan sonu "الله أكبر الناس" / "الله أكبر لا" → 9:72'ye kilit (2 parca), kesik
        // tevhid "إله إلا الله" → Fatiha beklemesinde 1:1 ADAY. "الله اكبر" 3 ayette (9:72, 29:45, 40:10), "اله الا
        // الله" 4 ayette (3:62, 37:35, 38:65, 47:19) — hepsi ayet ortasinda; zamm kilitli degilken tek basina (+1 kelime)
        // okuma degil. Tamamen tekbir olan parca eskisi gibi stripNamazPhrases'ta atilir (too_short), zikir sayilmaz.
        val DHIKR_PHRASES = listOf(
            listOf("محمد", "رسول", "الله"), listOf("محمدا", "رسول", "الله"),
            listOf("لا", "اله", "الا", "الله"), listOf("ان", "شاء", "الله"),
            listOf("اله", "الا", "الله"), listOf("الله", "اكبر"),
            // namaz sonu tesbihati "(لا حول) ولا قوة إلا بالله": Kuran'da sadece 18:39 ("ما شاء الله لا قوة إلا بالله");
            // aksam 22.10'da selamdan sonra "ولا قوة إلا بالله" 18:39'a tek parcada kilit
            listOf("قوه", "الا", "بالله"), listOf("حول", "ولا", "قوه", "الا", "بالله"),
            // tesbihat "(الحمد) لله ولا إله إلا الله": "ولا اله الا الله" Kuran'da hic yok (aksam 22.10: Kotlin 2:255 / Python
            // 37:35 belirsiz aday — aligner aday budamasi farki)
            listOf("ولا", "اله", "الا", "الله"), listOf("لله", "ولا", "اله", "الا", "الله"),
        )
        const val DHIKR_EXTRA_MAX = 1
        // Kamet / ezan basi: tekbir + tevhid ("الله أكبر الله أكبر" | "أشهد أن لا إله إلا الله"). Yatsi (19.10): kamet 685'te
        // basladi, ASR "الله اغبر" ×2 → "لا اله الا الله" (698.8) → ancak 708.8'de "أشهد أن سيدنا محمد" ile tanindi (24 sn
        // geç; aradaki tekbirler TEKBIR karti acti). Zamm kilitli degilken (BEKLEME / ARA) ve bekleme yokken son bu kadar
        // parca icinde sadece tekbir duyulduysa tek basina tevhid kamet/ezan sayilir. Ezan / kamet sonundaki tekbir + tevhid
        // bekleme surerken geldigi icin tetiklemez (zikir olarak beklemeyi uzatir); namazda tevhid sesli soylenmez.
        const val TEKBIR_TEVHID_CHUNKS = 2
        // Kilit kaybolmussa (ABANDON_LOCK_AFTER_LOST+ kayip parca) zamm kilidi yok sayilir: zikir ifadesi ve tekbir + tevhid
        // kurali orada da gecer. Yatsi #2 (20.10): namazdan once Saffat 37:180-182 → ZAMM kilidi, 50 sn sessizlik, kamet
        // "الله اغبر" ×2 → "شهود لا اله الا الله" (189 sn) ZAMM'da zikir sayilmadi (37:35 belirsiz adayi); kamet ancak 194'te.
        //
        // Zamm okunurken ara verildiyse (ZAMM'da bu kadar ardisik kayip parca: rukû / secde, sessiz kisim) kisa (< ilk kilit
        // kelime sayisi) ve zayif (< ilk kilit esigi) eslesme okumanin devami sayilmaz. Yatsi #2: Taha 20:111 bitti, rukûdan
        // kalkarken "سمع الله لمن حمده" → ASR "لم يعد" 20:112'ye 62.9 → rukûda ekranda henuz okunmamis ayet. FATIHA'da
        // uygulanmaz (aminden sonra zammin kisa ilk parcasi; bilesik teravihte Asr bolumu kilitsiz kaldi).
        const val PAUSE_LOST_CHUNKS = 2
        // Kilitliyken (FATIHA / ZAMM) parca sadece "(و)الحمد لله" ve pencere eslesmesi < ilk kilit esigi → okuma degil (kayip
        // parca). Kuran'da 20+ yerde gecen kalip; ASR nefes / kuyruktan uyduruyor. Yatsi 22.10: Enbiya 21:79 bitti, 2.6 sn'lik
        // kuyruk parcasi "الحمد لله" → 21:80-81'e 62.1 → rukûda ekranda henuz okunmamis 21:80 / 21:81 (2. rekatta okundu).
        val STOCK_PHRASES = setOf(listOf("الحمد", "لله"), listOf("والحمد", "لله"))
        // Okumadan sonra tekbir duyulduysa (rukû; bkz. tekbirAfterReading) ZAMM'da kisa (< ilk kilit kelime sayisi) eslesme
        // ancak bu skorla okumanin devami. Yatsi 22.10 sabit parca: 21:79 bitti, rukû tekbiri, semiallah ASR'de "لمن قبله" →
        // 21:82'ye 76 → son zamm konumu 21:82 oldu, 2. rekatin devam penceresi 21:80'i kacirdi, 26:109'a dogal gecis.
        const val TEKBIR_SHORT_MIN_SCORE = 90.0
        // Belirsiz aday (UI): BEKLEME / kilit kaybi adayinda ikinci yer bu kadar yakinsa aday ekranda gosterilmez
        // (ChunkResult.ambiguous; state machine ayni, dogrulaninca kayar). 39 + 44 kayit (gercek, sentetik, dis kaynak)
        // × 2 zincir: ekrandaki 22 yanlis adayin farki 0-2.7 ("قل أعوذ برب" 113:1 / 114:1, "ألم تر كيف" 105:1 / 89:6 /
        // 14:24, ilahi "يا رب العالمين" 1:2 / 5:28, "والحمد لله رب العالمين" 6:45 / 37:182); dogru adaylarin 9'u
        // fark < 3 (Ayetel Kursi 2:255 / 3:2 ayni metin, Felak / Nas), 20'si >= 4.1.
        const val AMBIGUOUS_MARGIN = 3.0
        // Namaz yapisi sinyalleri (ASR metninden, bkz. namazSignal):
        //   kamet/ezan → yeni namaz basliyor: kilit sifirlanir (BEKLEME), KAMET_HOLD_CHUNKS parca sadece Fatiha
        //     kilitlenir. Cuma: kamet "الصلاة حي الصلاة" → 4:103, "بل قام بالصلاة" → 4:101 kilit; Fatiha 4:102'ye eslesti.
        //   selam (kilit yokken) → namaz bitti: ayni sifirlama, RUKU_HOLD_CHUNKS parca (dua cumleleri kilitlemesin).
        //   semiallah → rukû (zamm bitti): ARA'ya gecilir; RUKU_HOLD_CHUNKS parca boyunca sadece Fatiha (yeni rekat)
        //     ya da kalinan yerden devam (pencere skoru >= HOLD_RESUME_MIN_SCORE). Cuma: semiallah sonrasi
        //     "لمن عمل" → 21:106 (55) kilitliydi.
        //   Tek basina tekbir sinyal DEGIL (sadece metinden atilir): zorlama testinde okuma ortasina sahte "الله أكبر"
        //     konunca ARA'ya gecmek / beklemek yeni sureyi kilitletmiyordu; gercek kayitlarda semiallah ayni isi yapiyor.
        // Bekleme her sinyalde yenilenir; Fatiha ya da devam kilitlenince biter.
        const val KAMET_HOLD_CHUNKS = 12
        const val RUKU_HOLD_CHUNKS = 24
        const val HOLD_RESUME_MIN_SCORE = 80.0
        // Tek parcada ilk kilit ("fark payi", taraweeh-companion-g2'deki high-margin lock fikri): BEKLEME'de skor
        // >= UNIQUE_LOCK_MIN_SCORE, >= UNIQUE_LOCK_MIN_WORDS kelime ve en iyi eslesmenin DISINDAKI en iyi yer (tum
        // Kuran, ayni araliga degmeyen pencereler) en az UNIQUE_LOCK_MARGIN puan geride → dogrulama beklemeden kilit.
        // Birden cok yerde gecen ifade ("قل أعوذ برب" 113:1/114:1, "يا رب العالمين", 16:4/36:77) farki ~0 → yine 2
        // parca dogrulamasi. Olcum (35 kayit): yanlis adaylarin farki en fazla 2.4, dogrular 9-33; ilk kilit
        // 17/0/2 → 19/0/0, takip 43/46 → 46/46, yanlis kilit 0; zorlama testlerinde yanlis kilit / aday artmadi.
        const val UNIQUE_LOCK_MIN_SCORE = 90.0
        const val UNIQUE_LOCK_MIN_WORDS = 3
        const val UNIQUE_LOCK_MARGIN = 12.0
        // Ayirt edici kelime (taraweeh-companion-g2'nin "prefix-ambiguity guard"inin tersi): harf benzerligi ikinci yeri
        // yaklastirabiliyor — "قل أعوذ برب الفلق" 113:1'e 100, 114:1 "...الناس"e 91.4 (fark 8.6). Fark >=
        // EXCLUSIVE_LOCK_MARGIN ve parcada en iyi yerin ayetlerinde birebir gecip ikinci yerin ayetlerinde gecmeyen,
        // besmele disi, >= EXCLUSIVE_MIN_LETTERS harfli bir kelime varsa da tek parcada kilit. Olcum (35 kayit, BEKLEME
        // adaylari, skor >= 90): yanlislarin farki 0-1.6 ve hicbirinde ayirt edici kelime yok ("قل أعوذ برب", ilahi
        // "يا رب العالمين", "والعصر إن شاء الله" → 12:99); dogrular 6.7-10.6 ve hepsinde var ("الفلق", "الناس", "اهدنا",
        // "والعصر", "الفيل"). Besmele kelimeleri sayilmaz (korpusta her 1. ayet besmeleyle basliyor).
        const val EXCLUSIVE_LOCK_MARGIN = 5.0
        const val EXCLUSIVE_MIN_LETTERS = 3
        val BESMELE_TOKENS = setOf("بسم", "الله", "الرحمن", "الرحيم")
        // Birikmis metin (taraweeh-companion-g2: arama modunda son parcalarin metni birlestirilip eslestiriliyor): yavas
        // okumada 5 sn'lik parcaya 1-2 kelime sigiyor ("خلق الإنسان" | "علمه البيان" tek tek too_short → Rahman ilk
        // kilidi 20 sn). BEKLEME'de (bekleme yokken) kilit vermeyen son SEARCH_CONCAT_CHUNKS parcanin temiz metni
        // saklanir; yeni parca da kilit vermezse birlesik metin tum Kuran'da hizalanir ve sadece tek parcada kilit
        // kuralini gecerse kilit verir — ayni ses iki kez kanit sayilmasin diye aday / dogrulama uretmez. Sessizlik,
        // namaz sinyali, bekleme ya da kilit birikimi siler; bos ASR parcasi silmez. Sabit 5 sn parcadaki 1 sn
        // bindirme: sinirda tekrar eden kelimeler (en fazla SEARCH_CONCAT_MAX_OVERLAP) bir kez.
        const val SEARCH_CONCAT_CHUNKS = 2
        const val SEARCH_CONCAT_MAX_OVERLAP = 4
        // BEKLEME'de aday dogrulamasi: aday penceresindeki eslesme tum Kuran'daki en iyi yerden bu kadar zayifsa dogrulama
        // sayilmaz. Asr 21.10: belirsiz 6:73 adayini ("عالم الغيب والشهادة", 9:94 ile esit) "هو الرحمن الرحيم" pencerede 71.3
        // ile dogruladi (tum Kuran'da 100: 2:163 / 59:22) → okunan Hasr 59:22 iken 6:73'e kilit, 20 sn ekranda.
        const val VERIFY_GLOBAL_MARGIN = 15.0
        // ARA'da / kilidi kaybolmus zamm'da (yeni rekat beklenir) Fatiha yoklamasi pencere disindaki en iyi yerden bu kadar
        // dusuk olsa da kazanir: ASR basa "و" ekliyor, "والحمد لله رب العالمين" 6:45'te birebir 100, Fatiha 1:2 92.4 (sabah 21.10)
        const val FATIHA_ARA_MARGIN = 8.0
        // BEKLEME'de (bekleme yokken) en iyi eslesme Fatiha disinda ama belirsizse (ikinci yer AMBIGUOUS_MARGIN icinde) ve
        // parca Fatiha'nin 1-3. ayetine >= FATIHA_FAST_LOCK_MIN_SCORE, en iyiden en fazla FATIHA_ARA_MARGIN kotu oturuyorsa
        // Fatiha (namaz Fatiha ile baslar). Yatsi 22.10: kamet onceki oturumda kaldi (uygulama yeniden baslatildi), ilk parca
        // "والحمد لله رب العالمين" 6:45 / 37:182 esit 100, Fatiha 1:2 92 → belirsiz aday, Fatiha 5 sn gec (1:3'ten). Bekleyen aday
        // varken uygulanmaz: gurultu testinde asr'in 37:180'i kilitlenmeyince 37:181 aday oldu, "والحمد لله رب العالمين" (37:182,
        // adayi dogruluyordu) Fatiha sanildi.

        // Istiaze ayet degil ama "من الشيطان الرجيم" 16:98'e aday uretiyordu. Chunk sinirinda
        // bolunebilir: "الشيطان" iceren >=3 kelimelik ardisik parcalari cikar.
        val ISTIAZE_TOKENS = listOf("اعوذ", "بالله", "من", "الشيطان", "الرجيم")
        const val ISTIAZE_KEY = 3  // "الشيطان"
        val BESMELE_NORMALIZED = listOf("بسم", "الله", "الرحمن", "الرحيم")

        /** Metinden istiaze parcalarini cikar → (temiz metin, cikarilan kelime sayisi). */
        fun stripIstiaze(text: String): Pair<String, Int> {
            val words = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            val norms = words.map { Normalizer.normalize(it) }
            val keep = ArrayList<String>(words.size)
            var removed = 0
            var i = 0
            while (i < words.size) {
                var best = 0
                for (a in ISTIAZE_TOKENS.indices) {
                    var n = 0
                    while (a + n < ISTIAZE_TOKENS.size && i + n < norms.size && norms[i + n] == ISTIAZE_TOKENS[a + n]) n++
                    if (n >= 3 && a <= ISTIAZE_KEY && ISTIAZE_KEY < a + n && n > best) best = n
                }
                if (best > 0) {
                    i += best
                    removed += best
                } else {
                    keep.add(words[i])
                    i++
                }
            }
            return Pair(keep.joinToString(" "), removed)
        }

        // Namaz zikirleri Kuran degil ama ayete "eslesiyordu" (gercek aksam namazi kaydi, 27.09): selam
        // "السلام عليكم ورحمة الله" → 6:54 (84), "سمع الله لمن حمده" → 3:181 (74). Kuran'da "السلام عليكم/عليك" ve
        // "ربنا (و)لك الحمد" hic gecmiyor, "سمع الله" hep "قول" ile devam ediyor → bu kaliplar cikarilir.
        // "الله اكبر" 3 ayette geciyor (9:72, 29:45, 40:10) → sadece parca tamamen tekbirse atilir.
        val SELAM_TAIL = setOf("و", "ورحمه", "رحمه", "الله", "وبركاته", "بركاته")
        const val SELAM_MAX_WORDS = 5
        // ASR (FastConformer) sessizlik/gurultu/tekbirde egitim verisindeki video girislerini uyduruyor:
        // "شركة الهدى للخدمات التقنية", "موسوعة النابلسي للإعجاب", "لا تنسوا مشاركة العمل". Bu kelimeler
        // Kuran'da yok (korpus vocab ile dogrulandi); iceren parca bos sayilir (okuma yok).
        val ASR_HALLUCINATION_TOKENS = setOf(
            "شركه", "للخدمات", "الخدمات", "التقنيه", "موسوعه", "النابلسي", "مشاركه", "لاتنسوا", "للاعجاب",
        )
        // Namaz sonu duasi (imam, selamdan hemen sonra): "اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام".
        // Gercek namaz #2 (01.10): "السلام منك السلام" → 59:23 ADAY, "تباركت يا ذا الجلال والاكرام" → 55:27 ADAY.
        // Kuran'da "انت السلام", "(و)منك السلام", "تباركت", "ذا الجلال" yok (korpusla dogrulandi; Kuran'da ذو/ذي
        // الجلال) → cikarilir. Dua basi parcada kaldiysa ("اللهم انت السلام") geriye dogru da silinir.
        val DUA_HEAD = setOf("اللهم", "انت", "السلام")
        val DUA_TAIL = setOf("يا", "ذا", "ذو", "ذي", "الجلال", "والاكرام")
        const val DUA_HEAD_MAX = 3
        // Tek kelimelik ASR uydurmasi: tekbir/gurultu/titresimde "المصدر كتاب", "المصدر صور من" (namaz #2'de 8 kez,
        // ezanda da). "المصدر" Kuran'da yok; sadece kelime cikarilir (kalan kisa parca too_short olur).
        val ASR_NOISE_WORDS = setOf("المصدر")
        // Ders girisi uydurmasi: ASR sessizlik / yankida Nablusi tefsir dersinin acilisini yaziyor ("تفسير سورة الأعراف
        // الدرس الثامن لفضيلة الدكتور محمد راتب النابلسي", "نهاية الدرس") — cogu zaman gercek okumayla ayni parcada:
        // "تفسير سورة الأعراف الدرس اهدنا الصراط المستقيم", "نهاية الدرس الحمد لله رب العالمين" (sentetik teravih 78
        // parca, Collak kayitlari, cuma). "تفسير", "الدرس", "نهاية" ve siralama kelimeleri Kuran'da yok (korpus) →
        // sadece giris kelimeleri cikarilir: "تفسير" (+ "سورة" + sure adi), "(سورة X) الدرس" (+ siralama kelimesi),
        // "نهاية الدرس". Kalan okuma hizalanir.
        val LECTURE_ORDINAL_PREFIXES = listOf(
            "الاول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع",
            "العاشر", "الثلا", "العشر", "الاربع",
        )
        // Tekbir: ASR "الله اغبر" de yaziyor (cuma, 3 kez). "اغبر"/"اكبار" Kuran'da yok.
        val TEKBIR_WORDS = setOf("اكبر", "اغبر", "اكبار")
        // Bozuk semiallah (cuma #2): "يدع الله لمن حمده" (260 sn), "سمع القول لمن حمد" (156 sn) — "سمع الله" kalibina
        // uymuyordu → rukû sinyali ve bekleme kaciyordu. "لمن حمد…" ve "حمده" Kuran'da yok (korpus); 35 kaydin RNNT + CTC
        // transkriptlerinde (2782) sadece semiallahta geciyor. Onundeki en fazla SEMIALLAH_HEAD_MAX kisa kelime
        // (<= SEMIALLAH_HEAD_LEN harf: "سمع", "يدع", "الله", "القول") da atilir.
        const val SEMIALLAH_HEAD_MAX = 2
        const val SEMIALLAH_HEAD_LEN = 5
        // Tek basina semiallah sonu: "حمده", "حميده" (yatsi 22.10: "لمَن حميده"; Kuran'da "لمن"den sonra "حم" ile baslayan kelime
        // yok — sadece "لمن حارب", "لمن حوله" — "لمن حم…" da semiallah)
        val SEMIALLAH_TAIL = setOf("حمده", "حميده")
        // Kamet / ezan: Kuran'da HIC gecmeyen kelime ve ikililer (korpusla dogrulandi; eval'deki 33 kaydin RNNT +
        // CTC transkriptlerinde hic cikmadi). Cuma kameti: "أشهد ان لا إله", "الله محمد", "أن محمد", "الصلاة حي الصلاة",
        // "بل قام بالصلاة". "لا اله الا الله", "محمد رسول الله", "الله اكبر", "حي" (21:30, 8:42) Kuran'da var → isaret degil.
        val KAMET_WORDS = setOf("الفلاح", "قامت", "محمدا")
        // Cuma #2 (09.10): kamet "حي على الصلاة" → ASR "خير الصلاة على الصلاة" hicbir kaliba uymadi → 4:142 aday
        // (ekranda "Nisa"), kamet ancak 10 sn sonra "قد قام بالصلاة" ile yakalandi; "قد قامت الصلاة" → "مضت الصلاة".
        // "على الصلاة", "خير الصلاة", "مضت الصلاة" Kuran'da yok (korpus), 34 kaydin 2405 transkriptinde hic gecmiyor.
        val KAMET_PAIRS = setOf(
            "اشهد" to "ان", "اشهد" to "انه", "اشهد" to "لا", "ان" to "محمد", "الله" to "محمد", "قد" to "قام",
            "قام" to "الصلاه", "قام" to "بالصلاه", "حي" to "علي", "حي" to "الصلاه", "الصلاه" to "حي",
            "حي" to "الفلاح", "الصلاه" to "خير", "من" to "النوم",
            "علي" to "الصلاه", "خير" to "الصلاه", "مضت" to "الصلاه",
        )
        // Yatsi (19.10) vaazinda Felak "قل أعوذ برب الفلق" → ASR "أعوذ برب الفلاح": "الفلاح" kamet sayilip kilit / adaylar
        // silindi, Fatiha beklemesinde Felak hic kilitlenmedi (sabit parca). "(ب)رب الفلاح" kamette yok (hayya → "حي على
        // الفلاح"); tum transkriptlerde "الفلاح" 4 kez: 3 "ايها الفلاح" (hayya), 1 bu Felak.
        val FALAQ_PREV = setOf("برب", "رب")
        private val NON_LETTER = Regex("[^\\u0621-\\u064A]")

        /** normalize + harf olmayan karakterleri (nokta vb.) at. */
        fun bareToken(word: String): String = NON_LETTER.replace(Normalizer.normalize(word), "")

        fun isAsrHallucination(text: String): Boolean =
            text.trim().split(Regex("\\s+")).any { it.isNotEmpty() && bareToken(it) in ASR_HALLUCINATION_TOKENS }

        // Uydurma ifade gercek okumayla ayni parcada (sabah namazi 21.10, 2. rekat Fatiha'si: "والحمد لله رب العالمين شركة
        // الهدى للخدمات التقنية" — parcanin tamami bos sayildi, Fatiha kilidi 10 sn gecikti). "شركة" / "موسوعة" ile baslayan
        // ifade (bas + marka kelimesi: الهدى / النابلسي / النحل ... + devam kelimeleri) cikarilir; kalan (istiaze / namaz
        // zikirleri haric) en az MIN_WORD_COUNT_FIRST_LOCK kelimeyse parca o metinle islenir, degilse eskisi gibi bos. Baska
        // uydurma kelimesi kalirsa ("لفضيلة الدكتور محمد راتب النابلسي", "لا تنسوا مشاركة العمل") yine bos. Tum transkriptlerde
        // (gercek + dis + sentetik): "شركة الهدى للخدمات التقنية/التاريخية/للإنسان/للبناء/للنوم", "شركة اليابان",
        // "شركة التابعين", "موسوعة النابلسي للعلوم الإسلامية", "موسوعة النحل/النعم مالك يوم الدين".
        val HALLUCINATION_HEADS = setOf("شركه", "موسوعه")
        val HALLUCINATION_CONT = setOf(
            "للخدمات", "الخدمات", "التقنيه", "التاريخ", "التاريخيه", "للعلوم", "الاسلاميه", "للبناء", "للنوم", "للاعجاب", "شريك",
        )
        // Tilavet sonu: asr / mukabele bitince okunan "صدق الله العظيم" (Kuran'da yok; "صدق الله" 3:95 / 33:22'de baska
        // kelimeyle). Asr 21.10: Hasr 59:24'ten sonra bu ifade + Saffat 37:180-182 — kilit 59:24'te kaldi, 37:180 okunurken
        // ekranda 59:24. Ifade cikarilir, kilit ve adaylar biter (BEKLEME, beklemesiz). Dis kaynak kayitlarinda (Collak, Harem)
        // da kayit sonunda. Namazda tilavet sonu yok: son eslesmeden sonra tekbir duyulduysa (rukû / secde) ve son eslesmeden en
        // az TILAVET_END_NAMAZ_GAP parca gectiyse ifade sadece cikarilir, kilit bitmez (yatsi 22.10: secdede, son eslesmeden 8 parca
        // sonra ASR "صدق الله العظيم" uydurdu → kilit sifirlandi; asr 21.10'da gercek tilavet sonu 2, sahte tekbir testinde 3 parca).
        val TILAVET_END = listOf("صدق", "الله", "العظيم")
        const val TILAVET_END_NAMAZ_GAP = 5

        /** "صدق الله العظيم" → (ifade cikarilmis metin, bulundu mu). */
        fun stripTilavetEnd(text: String): Pair<String, Boolean> {
            val words = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            val toks = words.map { bareToken(it) }
            val n = TILAVET_END.size
            for (i in 0..toks.size - n) {
                if (toks.subList(i, i + n) == TILAVET_END) {
                    return Pair((words.subList(0, i) + words.subList(i + n, words.size)).joinToString(" "), true)
                }
            }
            return Pair(text, false)
        }

        /** ASR uydurmasi iceren parca → uydurma ifadesi cikarilmis metin ya da "" (bos sayilir; bkz. HALLUCINATION_HEADS). */
        fun stripAsrHallucination(text: String): String {
            if (text.isBlank() || !isAsrHallucination(text)) return text
            val words = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            val out = ArrayList<String>(words.size)
            var i = 0
            while (i < words.size) {
                if (bareToken(words[i]) in HALLUCINATION_HEADS) {
                    i += 2                                  // bas + marka kelimesi
                    while (i < words.size && bareToken(words[i]) in HALLUCINATION_CONT) i += 1
                    continue
                }
                out += words[i]
                i += 1
            }
            val rest = out.joinToString(" ")
            if (rest.isEmpty() || isAsrHallucination(rest)) return ""
            val (noIstiaze, _) = stripIstiaze(rest)
            val (clean, _) = stripNamazPhrases(noIstiaze)
            val n = clean.split(Regex("\\s+")).map { Normalizer.normalize(it) }.count { it.isNotEmpty() }
            return if (n < MIN_WORD_COUNT_FIRST_LOCK) "" else rest
        }

        /** Metinde "اله الا الله" (kelime-i tevhid) gecer mi — bkz. TEKBIR_TEVHID_CHUNKS. */
        fun isTevhid(text: String): Boolean {
            val toks = text.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() }
            return (0..toks.size - 3).any { toks[it] == "اله" && toks[it + 1] == "الا" && toks[it + 2] == "الله" }
        }

        /** Sadece zikir ifadesi mi (bkz. DHIKR_PHRASES) → (zikir mi, kelime-i sehadet mi). */
        /**
         * Bastaki tekbir (kamet / ezan kapanisi "الله أكبر الله أكبر لا إله إلا الله" — Kuran'da tekbirden hemen sonra tevhid yok):
         * yatsi 21.10'da kayit kamet sonunda basladi, "الله اغبر لا اله الا الله" zikir sayilmadi → belirsiz aday (bu aligner aday
         * budamasiyla 28:88, Python 37:35). Kalan kelimeler zikir ifadesiyse zikir (dhikrOnly).
         */
        private fun dropLeadingTekbir(tokens: List<String>): List<String> {
            var toks = tokens
            while (toks.size > 1 && (toks[0] in TEKBIR_WORDS || (toks[0] == "الله" && toks[1] in TEKBIR_WORDS))) {
                toks = if (toks[0] in TEKBIR_WORDS) toks.drop(1) else toks.drop(2)
            }
            return toks
        }

        fun dhikrOnly(text: String): Pair<Boolean, Boolean> {
            val toks = text.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() }
            if (isTekbirOnly(toks)) return Pair(false, false)
            for (cand in listOf(toks, dropLeadingTekbir(toks))) {
                for (ph in DHIKR_PHRASES) {
                    val n = ph.size
                    if (cand.size - n <= DHIKR_EXTRA_MAX && (0..cand.size - n).any { cand.subList(it, it + n) == ph }) {
                        return Pair(true, ph[1] == "رسول")
                    }
                }
            }
            return Pair(false, false)
        }

        /**
         * Namaz zikirlerini (selam, semiallah, rabbena lekel hamd, tek basina tekbir), namaz sonu duasini
         * ("اللهم انت السلام ومنك السلام تباركت يا ذا الجلال والاكرام"), tek kelimelik ASR uydurmasini ("المصدر") ve
         * ders girisi uydurmasini ("تفسير سورة الأعراف الدرس") cikar → (temiz metin, cikarilan kelime sayisi).
         */
        fun stripNamazPhrases(text: String): Pair<String, Int> {
            val words = text.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
            val norms = words.map { bareToken(it) }
            val n = words.size
            var keep = ArrayList<String>(n)
            var removed = 0
            var i = 0
            while (i < n) {
                var k = 0
                if (norms[i] == "السلام" && i + 1 < n && (norms[i + 1] == "عليكم" || norms[i + 1] == "عليك")) {
                    k = 2
                    while (i + k < n && k < SELAM_MAX_WORDS && norms[i + k] in SELAM_TAIL) k++
                } else if ((norms[i] == "عليكم" || norms[i] == "عليك") && i + 1 < n &&
                    (norms[i + 1] == "ورحمه" || norms[i + 1] == "رحمه")
                ) {
                    // Parca sinirinda bolunen selam ("السلام" onceki parcada): "عليكم ورحمة الله" (cuma #2, sabit
                    // parca → 1:1 ADAY). "عليكم/عليك + (و)رحمه" Kuran'da yok.
                    k = 2
                    while (i + k < n && k < SELAM_MAX_WORDS && norms[i + k] in SELAM_TAIL) k++
                } else if (norms[i] == "سمع" && i + 2 < n && norms[i + 1] == "الله") {
                    if (norms[i + 2].startsWith("حمد")) {
                        k = 3
                    } else if (norms[i + 2] == "لمن") {
                        k = if (i + 3 < n && norms[i + 3].startsWith("حمد")) 4 else 3
                    }
                } else if (norms[i] == "ربنا" && i + 2 < n && (norms[i + 1] == "لك" || norms[i + 1] == "ولك") &&
                    norms[i + 2] == "الحمد"
                ) {
                    k = 3
                } else if (norms[i] == "لمن" && i + 1 < n && norms[i + 1].startsWith("حم")) {
                    k = 2
                    var back = 0
                    while (keep.isNotEmpty() && back < SEMIALLAH_HEAD_MAX && bareToken(keep.last()).length <= SEMIALLAH_HEAD_LEN) {
                        keep.removeAt(keep.size - 1)
                        back++
                    }
                    removed += back
                } else if (norms[i] in SEMIALLAH_TAIL) {
                    k = 1
                } else if (norms[i] in ASR_NOISE_WORDS) {
                    k = 1
                } else if (norms[i] == "تفسير") {
                    k = 1
                    if (i + 1 < n && norms[i + 1] == "سوره") {
                        k = if (i + 2 < n && norms[i + 2] != "الدرس") 3 else 2
                    }
                } else if (norms[i] == "نهايه" && i + 1 < n && norms[i + 1] == "الدرس") {
                    k = 2
                } else if (norms[i] == "الدرس") {
                    k = 1
                    if (keep.size >= 2 && bareToken(keep[keep.size - 2]) == "سوره") {
                        keep.removeAt(keep.size - 1)
                        keep.removeAt(keep.size - 1)
                        removed += 2
                    }
                } else if ((norms[i] == "انت" || norms[i] == "منك" || norms[i] == "ومنك") && i + 1 < n &&
                    norms[i + 1] == "السلام"
                ) {
                    k = 2
                    var back = 0
                    while (keep.isNotEmpty() && back < DUA_HEAD_MAX && bareToken(keep.last()) in DUA_HEAD) {
                        keep.removeAt(keep.size - 1)
                        back++
                    }
                    removed += back
                } else if (norms[i] == "تباركت") {
                    k = 1
                    while (i + k < n && norms[i + k] in DUA_TAIL) k++
                } else if (norms[i] == "ذا" && i + 1 < n && norms[i + 1] == "الجلال") {
                    k = if (i + 2 < n && norms[i + 2] == "والاكرام") 3 else 2
                    if (keep.isNotEmpty() && bareToken(keep.last()) == "يا") {
                        keep.removeAt(keep.size - 1)
                        removed++
                    }
                }
                if (k > 0 && norms[i + k - 1] == "الدرس" && i + k < n &&
                    LECTURE_ORDINAL_PREFIXES.any { norms[i + k].startsWith(it) }
                ) {
                    k++     // "الدرس الثامن"
                }
                if (k > 0) {
                    i += k
                    removed += k
                } else {
                    keep.add(words[i])
                    i++
                }
            }
            if (isTekbirOnly(keep)) {
                removed += keep.size
                keep = ArrayList()
            }
            return Pair(keep.joinToString(" "), removed)
        }

        /** Parca sadece tekbirden mi ibaret ("الله اكبر", "الله اغبر الله أكبر", "أكبر"). */
        fun isTekbirOnly(words: List<String>): Boolean {
            val kept = words.map { bareToken(it) }.filter { it.isNotEmpty() }
            return kept.isNotEmpty() && kept.any { it in TEKBIR_WORDS } && kept.all { it == "الله" || it in TEKBIR_WORDS }
        }

        /**
         * Namaz yapisi sinyali: "kamet" (kamet/ezan cumlesi), "selam", "ruku" (semiallah) ya da null. Semiallah, sonra kamet.
         */
        fun namazSignal(text: String): String? {
            val toks = text.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() }
            // Semiallah kametten once: Kuran'da "سمع الله" hep "قول" ile devam ediyor (3:181, 58:1) → arkasindan baska
            // kelime gelirse semiallah. Sentetik teravihte "سمع الله لنا محمدا" ("محمدا" kamet kelimesi) kamet sayilip namaz
            // sifirlaniyordu; aksam kaydinda "سمع الله من حمداً" hicbir kaliba uymuyordu. Parca sonundaki "سمع الله" sinyal degil.
            for (i in 0 until toks.size - 2) {
                if (toks[i] == "سمع" && toks[i + 1] == "الله" && toks[i + 2] != "قول") return "ruku"
            }
            // "استمع الله" (ASR: semiallah, aksam 22.10): Kuran'da "استمع" sadece 72:1'de ("استمع نفر")
            if ((0 until toks.size - 1).any { toks[it] == "استمع" && toks[it + 1] == "الله" }) return "ruku"
            val kametWord = toks.indices.any { i ->
                toks[i] in KAMET_WORDS && !(toks[i] == "الفلاح" && i > 0 && toks[i - 1] in FALAQ_PREV)
            }
            if (kametWord || (0 until toks.size - 1).any { (toks[it] to toks[it + 1]) in KAMET_PAIRS }) {
                return "kamet"
            }
            if ((0 until toks.size - 1).any { toks[it] == "السلام" && (toks[it + 1] == "عليكم" || toks[it + 1] == "عليك") }) {
                return "selam"
            }
            if (toks.any { it in SEMIALLAH_TAIL } || (0 until toks.size - 1).any { toks[it] == "لمن" && toks[it + 1].startsWith("حم") }) {
                return "ruku"
            }
            return null
        }

        /** Hizalanacak temiz metin: ASR uydurmasi bos, istiaze ve namaz zikirleri cikarilmis. */
        fun cleanChunkText(text: String): String {
            val t = stripAsrHallucination(text)
            if (t.isBlank()) return ""
            val (noEnd, _) = stripTilavetEnd(t)
            val (noIstiaze, _) = stripIstiaze(noEnd)
            val (clean, _) = stripNamazPhrases(noIstiaze)
            return clean.trim()
        }

        /** Ardisik parca metinlerini birlestir; sinirda tekrar eden (bindirme) kelimeler bir kez sayilir. */
        fun joinSearchTexts(texts: List<String>): String {
            val out = ArrayList<String>()
            for (t in texts) {
                var w = t.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
                if (out.isNotEmpty()) {
                    val a = out.map { bareToken(it) }
                    val b = w.map { bareToken(it) }
                    for (k in minOf(SEARCH_CONCAT_MAX_OVERLAP, a.size, b.size) downTo 1) {
                        if (a.subList(a.size - k, a.size) == b.subList(0, k)) {
                            w = w.drop(k)
                            break
                        }
                    }
                }
                out.addAll(w)
            }
            return out.joinToString(" ")
        }
        const val SURAH_END_THRESHOLD = 2
    }

    /**
     * Audio RMS hesabi.
     */
    fun computeRms(audio: FloatArray): Double {
        if (audio.isEmpty()) return 0.0
        var sumSq = 0.0
        for (s in audio) sumSq += s * s
        return sqrt(sumSq / audio.size)
    }

    /**
     * Bir chunk'i isle. Saf mantik — audio'yu transcribe ETMEZ, transkripsiyon
     * verilmis olarak gelir.
     *
     * @param rms Audio RMS enerji degeri
     * @param transcribedText ASR tarafından üretilen metin (boş olabilir)
     * @param chunkIndex Chunk index (0'dan basliyor)
     * @param state Mutate edilecek state
     */
    fun processChunk(
        rms: Double,
        transcribedText: String,
        chunkIndex: Int,
        state: SessionState,
    ): ChunkResult {
        val wasSearch = state.state == NamazState.BEKLEME
        val r = processChunkCore(rms, transcribedText, chunkIndex, state)
        // Kilit vermediyse BEKLEME'de birikmis metinle (onceki parcalar + bu parca) tek parcada kilit — bkz. SEARCH_CONCAT_*
        val hold = state.holdUntil.let { it != null && chunkIndex <= it }
        val searching = r.status == ChunkStatus.TOO_SHORT || r.status == ChunkStatus.LOW_CONFIDENCE ||
            r.status == ChunkStatus.PENDING || r.status == ChunkStatus.EMPTY
        if (!(wasSearch && state.state == NamazState.BEKLEME && !hold && !r.kamet && searching)) {
            state.searchTexts = emptyList()
            return r
        }
        if (r.status == ChunkStatus.EMPTY) return r
        val clean = cleanChunkText(transcribedText)
        val prev = state.searchTexts.filter { chunkIndex - it.first <= SEARCH_CONCAT_CHUNKS }.map { it.second }
        state.searchTexts = state.searchTexts.filter { chunkIndex - it.first < SEARCH_CONCAT_CHUNKS } +
            (if (clean.isNotEmpty()) listOf(Pair(chunkIndex, clean)) else emptyList())
        if (prev.isEmpty() || clean.isEmpty()) return r
        val comb = joinSearchTexts(prev + clean)
        val combTokens = comb.split(Regex("\\s+")).map { Normalizer.normalize(it) }.filter { it.isNotEmpty() }
        if (comb == clean || combTokens.size < UNIQUE_LOCK_MIN_WORDS) return r
        val g = aligner.align(comb, preferredRange = null) ?: return r
        val gs = scoreTranscription(combTokens, g)
        val uc = uniqueCheck(comb, combTokens, g, gs, combTokens.size)
        if (!uc.unique) return r
        state.searchTexts = emptyList()
        return commitMatch(
            state, chunkIndex, g, gs, combTokens.size, r.stateBefore, jump = null, rms = rms, text = transcribedText,
            reason = withNotes("birikmis metinle tek parcada kilit (${uc.note})", listOf("birlesik metin '${comb.take(60)}'")),
            preferredRange = null, inPreferred = false, nearSurahEnd = false, lockAbandoned = false,
        )
    }

    private fun processChunkCore(
        rms: Double,
        transcribedText: String,
        chunkIndex: Int,
        state: SessionState,
    ): ChunkResult {
        state.totalChunks += 1
        val stateBefore = state.state

        // 1. Sessizlik kontrolu
        if (rms < MIN_RMS_ENERGY) {
            if (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM) {
                state.lostChunks += 1
            }
            cleanupPendingIfStale(state, chunkIndex)
            applyTransition(state, matched = false, firstSurah = null, firstAyah = null)
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.SILENT,
                rms = rms,
                reason = "sessiz (RMS=${"%.4f".format(rms)})",
            )
        }

        // Gerekceli log: kararin baglami (sinyal, cikarilan kelimeler, aramanin nerede yapildigi) — bkz. ChunkResult.reason
        val notes = ArrayList<String>(4)
        // 2. ASR uydurmasi (Kuran'da olmayan video girisi kelimeleri) → ifade cikarilir, okuma kalmazsa bos sayilir —
        //    bkz. HALLUCINATION_HEADS. Tilavet sonu ("صدق الله العظيم") → kilit / adaylar biter — bkz. TILAVET_END.
        //    ChunkResult.text ASR'nin ham metni kalir (zikir karti / log); karar asrText ile.
        val hallucination = transcribedText.isNotBlank() && isAsrHallucination(transcribedText)
        var asrText = if (hallucination) stripAsrHallucination(transcribedText) else transcribedText
        if (hallucination && asrText.isNotBlank()) notes += "ASR uydurmasi cikarildi"
        var tilavetEnd = false
        if (asrText.isNotBlank()) {
            val (t, found) = stripTilavetEnd(asrText)
            val lt = state.lastTekbirChunk
            val lm = state.lastMatchChunk
            if (found && lt != null && lm != null && lt > lm && chunkIndex - lm >= TILAVET_END_NAMAZ_GAP) {
                asrText = t
                notes += "tilavet sonu ifadesi namazda (tekbirden sonra): sadece cikarildi"
            } else if (found) {
                asrText = t
                tilavetEnd = true
                resetForNewNamaz(state, chunkIndex, 0)
                state.holdUntil = null
                state.searchTexts = emptyList()
                notes += "tilavet sonu (صدق الله العظيم): kilit / adaylar bitti"
            }
        }
        if (asrText.isBlank()) {
            state.lostChunks += 1
            cleanupPendingIfStale(state, chunkIndex)
            applyTransition(state, matched = false, firstSurah = null, firstAyah = null)
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.EMPTY,
                rms = rms,
                text = transcribedText,
                reason = when {
                    tilavetEnd -> "tilavet sonu (صدق الله العظيم) — kilit / adaylar bitti"
                    hallucination -> "ASR uydurmasi (Kuran disi)"
                    else -> "ASR bos"
                },
                tilavetEnd = tilavetEnd,
            )
        }

        // 3a. Namaz yapisi sinyali (kamet / selam / rukû) — bkz. KAMET_HOLD_CHUNKS
        var signal = namazSignal(asrText)
        // Zamm kilitli degilken (ya da kilit kaybolmusken) tek basina zikir ifadesi — bkz. DHIKR_PHRASES, PAUSE_LOST_CHUNKS
        val abandoned = state.lostChunks >= ABANDON_LOCK_AFTER_LOST &&
            (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM)
        val (dhikr, sehadet) = if (signal == null && (state.state != NamazState.ZAMM || abandoned)) {
            dhikrOnly(asrText)
        } else {
            Pair(false, false)
        }
        val inHold = state.holdUntil.let { it != null && chunkIndex <= it }
        val lastTekbir = state.lastTekbirChunk
        val tekbirTevhid = dhikr && !inHold &&
            (state.state == NamazState.BEKLEME || state.state == NamazState.ARA || abandoned) &&
            lastTekbir != null && chunkIndex - lastTekbir <= TEKBIR_TEVHID_CHUNKS && isTevhid(asrText)
        if (isTekbirOnly(asrText.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() })) {
            state.lastTekbirChunk = chunkIndex
        }
        if ((dhikr && sehadet && state.state == NamazState.BEKLEME) || tekbirTevhid) signal = "kamet"
        if (signal == "kamet") {
            // Kamet/ezan Kuran degil: parca bos sayilir, yeni namaz basliyor
            resetForNewNamaz(state, chunkIndex, KAMET_HOLD_CHUNKS)
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.EMPTY,
                rms = rms,
                text = transcribedText,
                reason = when {
                    tekbirTevhid -> "tekbir + tevhid (kilit yok / kayip) — kamet/ezan, Fatiha bekleniyor"
                    dhikr -> "kelime-i sehadet (kilit yok) — kamet/ezan, Fatiha bekleniyor"
                    else -> "kamet/ezan — yeni namaz, Fatiha bekleniyor"
                },
                kamet = true,
            )
        }
        if (dhikr) {
            // Bekleme surerken zikir: namaz baslamadi, Fatiha beklemesi uzar (cuma #3: kamet sonrasi "لا إله إلا الله",
            // "إن شاء الله"; bekleme bitince "والحمد لله رب العالمين" 6:45 adayi olup Fatiha 7 sn gecikti)
            val hu = state.holdUntil
            val extended = hu != null && chunkIndex <= hu
            if (hu != null && extended) state.holdUntil = maxOf(hu, chunkIndex + KAMET_HOLD_CHUNKS)
            state.lostChunks += 1
            cleanupPendingIfStale(state, chunkIndex)
            applyTransition(state, matched = false, firstSurah = null, firstAyah = null)
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.EMPTY,
                rms = rms,
                text = transcribedText,
                reason = "zikir ifadesi (zamm kilidi yok)" + if (extended) "; bekleme parca ${state.holdUntil}'e uzadi" else "",
            )
        }
        if (signal == "selam" && (state.state == NamazState.BEKLEME || state.state == NamazState.ARA)) {
            resetForNewNamaz(state, chunkIndex, RUKU_HOLD_CHUNKS)
            notes += "selam: namaz bitti, $RUKU_HOLD_CHUNKS parca sadece Fatiha"
        } else if (signal == "ruku") {
            notes += "semiallah: rukû → ARA, $RUKU_HOLD_CHUNKS parca sadece Fatiha / kalinan yer"
            if (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM) {
                state.stateTransitions.add("${state.state.name} → ${NamazState.ARA.name}")
                state.state = NamazState.ARA
            }
            state.pendingMatch = null
            state.jumpCandidate = null
            state.holdUntil = chunkIndex + RUKU_HOLD_CHUNKS
        }
        val hold = state.holdUntil.let { it != null && chunkIndex <= it }

        // 3b. Istiaze + namaz zikirlerini cikar (hepsi cikarsa kelime sayisi 0 → too_short), kelime sayisi kontrolu
        val (noIstiaze, istiazeCut) = stripIstiaze(asrText)
        val (cleanText, namazCut) = stripNamazPhrases(noIstiaze)
        if (istiazeCut > 0) notes += "istiaze cikarildi ($istiazeCut kelime)"
        if (namazCut > 0) notes += "namaz zikri cikarildi ($namazCut kelime)"
        val tokens = cleanText.split(Regex("\\s+"))
            .map { Normalizer.normalize(it) }
            .filter { it.isNotEmpty() }
        val wordCount = tokens.size
        val isHot = state.state == NamazState.FATIHA || state.state == NamazState.ZAMM
        val minWords = if (isHot) MIN_WORD_COUNT_HOT else MIN_WORD_COUNT_COLD
        if (wordCount < minWords) {
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.TOO_SHORT,
                rms = rms,
                text = transcribedText,
                wordCount = wordCount,
                reason = withNotes("$wordCount kelime (min $minWords)", notes),
            )
        }

        // 4. Preferred range hesapla, align cagir
        val preferredRange = computePreferredRange(state)
        val lockAbandoned = state.lostChunks >= ABANDON_LOCK_AFTER_LOST &&
                (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM)
        val nearSurahEnd = state.state == NamazState.ZAMM &&
                state.lastSurah != null && state.lastAyah != null &&
                isNearSurahEnd(state.lastSurah!!, state.lastAyah!!)

        var match: AlignmentMatch?
        var score: Double
        var resumed = false   // kilit kaybinda kalinan yerin penceresi secildi (Fatiha yoklamasinda pencere ici sayilir)
        if (hold) notes += "bekleme (parca ${state.holdUntil}'e kadar): sadece Fatiha / kalinan yer"
        else notes += if (preferredRange != null) "pencere ${rangeLabel(preferredRange)}" else "tum Kuran"
        if (hold) {
            // Kamet / rukû / selam sonrasi: sadece Fatiha (yeni rekat) ya da kalinan yerden devam (ARA, ayni sure son
            // ayetin -RESUME_BACK..+PREFERRED_AYAH_WINDOW_ARA, skor >= HOLD_RESUME_MIN_SCORE). Tum Kuran aranmaz.
            match = aligner.align(cleanText, preferredRange = fatihaRange)
            score = scoreTranscription(tokens, match)
            val ls = state.lastSurah
            val la = state.lastAyah
            if (state.state == NamazState.ARA && ls != null && la != null) {
                val rw = ayahWindow(ls, la, back = RESUME_BACK, forward = PREFERRED_AYAH_WINDOW_ARA)
                if (rw != null) {
                    val rm = aligner.align(cleanText, preferredRange = rw)
                    val rs = scoreTranscription(tokens, rm)
                    if (rm != null && rs >= HOLD_RESUME_MIN_SCORE && rs > score) {
                        match = rm
                        score = rs
                    }
                }
            }
        } else {
            match = aligner.align(cleanText, preferredRange = preferredRange)
            score = scoreTranscription(tokens, match)
            // Kilit kaybolmus (okuma ara verdi): kalinan yerin penceresi (ayni sure, son ayetin -RESUME_BACK..+ARA) tum
            // Kuran'daki en iyi yerle neredeyse esitse (CONTINUE_MARGIN) kalinan yerden devam. Asr 21.10: Hasr 59:23'ten sonra
            // 4 parca ASR bos, 59:24 sonu "وهو العزيز الحكيم" ("الا وهو العزيز") tum Kuran'da 3:6 / 3:18 93.9, 59:24 93.3
            // → belirsiz aday.
            val ls = state.lastSurah
            val la = state.lastAyah
            val m0 = match
            if (lockAbandoned && ls != null && la != null && wordCount >= MIN_WORD_COUNT_FIRST_LOCK && m0 != null) {
                val rw = ayahWindow(ls, la, back = RESUME_BACK, forward = PREFERRED_AYAH_WINDOW_ARA)
                if (rw != null && m0.startWordIdx !in rw) {
                    val rm = aligner.align(cleanText, preferredRange = rw)
                    val rs = scoreTranscription(tokens, rm)
                    if (rm != null && rm.startWordIdx in rw && rs >= HOLD_RESUME_MIN_SCORE && rs >= score - CONTINUE_MARGIN) {
                        notes += "kalinan yerden devam ${"%.1f".format(rs)} (tum Kuran ${"%.1f".format(score)})"
                        match = rm
                        score = rs
                        resumed = true
                    }
                }
            }
        }

        // Kilitliyken (ZAMM/ARA) pencere emin degilse Fatiha'yi ayrica dene: yeni rekat Fatiha ile baslar. Tum Kuran
        // aramasi Fatiha ifadelerini baska yere de oturtabiliyor ("الحمد لله رب العالمين" 6:45, 10:10, 37:182...);
        // cuma: 2. rekat Fatiha'si 21:107'ye (62) pencere eslesmesi aldi, kamet kilidinde Fatiha 4:102'ye eslesti.
        // ZAMM'da en az FATIHA_FAST_LOCK_MIN_WORDS kelime: "وإلى رب العالمين" (94:8, ASR bozuk) Fatiha'ya 92.6 aliyor.
        var fatihaJump = false
        var fatihaCand: PendingMatch? = null   // erken Fatiha (bkz. FATIHA_MIN_GAP_CHUNKS): gecis adayi, sonraki parca dogrular
        var fatihaCandMatch: AlignmentMatch? = null
        // Kilit kaybolmus zamm (ABANDON_LOCK_AFTER_LOST kayip parca, ~30 sn okuma yok) ARA gibi: yeni rekat beklenir. Sabah
        // 21.10: semiallah duyulmadi, 2. rekat Fatiha'si "والحمد لله رب العالمين" ZAMM'da (ARA'ya 12 kayip parca) tum Kuran'da
        // 6:45'e esit skor aldi (belirsiz aday) → Fatiha kilidi 10 sn gecikti.
        val araLike = state.state == NamazState.ARA || (state.state == NamazState.ZAMM && lockAbandoned)
        val probeWords = if (araLike) MIN_WORD_COUNT_FIRST_LOCK else FATIHA_FAST_LOCK_MIN_WORDS
        if (!hold && (state.state == NamazState.ZAMM || state.state == NamazState.ARA) &&
            wordCount >= probeWords &&
            (match == null || score < JUMP_SEARCH_BELOW || araLike)
        ) {
            val fm = aligner.align(cleanText, preferredRange = fatihaRange)
            val fs = scoreTranscription(tokens, fm)
            val base = if (match != null) score else 0.0
            // ARA'da (rekat basi beklenir) esitlikte Fatiha kazanir; kalinan yerin penceresindeki eslesme haric
            // (zamm'da Fatiha ile ayni ifade: 37:182 "والحمد لله رب العالمين")
            val inWindow = resumed || (match != null && preferredRange != null && match.startWordIdx in preferredRange)
            val better = if (araLike) {
                // pencere disi: Fatiha'ya FATIHA_ARA_MARGIN pay (ASR basa "و" ekliyor)
                if (inWindow) fs > base else fs >= base - FATIHA_ARA_MARGIN
            } else {
                fs >= base + JUMP_MARGIN
            }
            if (fm != null && fs >= FATIHA_FAST_LOCK_MIN_SCORE && better) {
                val (_, fa) = collectVerses(fm.startWordIdx, fm.endWordIdx).last()
                if (earlyFatiha(state, chunkIndex, fa)) {
                    fatihaCand = PendingMatch(surah = 1, ayah = fa, wordIndex = fm.endWordIdx, chunkIndex = chunkIndex)
                    fatihaCandMatch = fm
                    notes += "Fatiha yoklamasi ${"%.1f".format(fs)}: erken (son saglam eslesmeden " +
                        "${chunkIndex - (state.lastSolidChunk ?: chunkIndex)} parca), gecis adayi"
                } else {
                    match = fm
                    score = fs
                    fatihaJump = true
                    notes += "Fatiha yoklamasi ${"%.1f".format(fs)} (yeni rekat)"
                }
            }
        }

        // BEKLEME + aday: aday penceresinde tutmadiysa ayni chunk'ta tum Kuran'da ara. Eskiden yanlis
        // aday (orn. 113:1 / 114:1 ortak ifadesi) 2 chunk bayatlayana kadar dogru yeri aratmiyordu.
        // (app.py / build_state_machine_fixture.py ile birebir)
        if (!hold && state.state == NamazState.BEKLEME && state.pendingMatch != null && preferredRange != null &&
            wordCount >= MIN_WORD_COUNT_FIRST_LOCK &&
            (match == null || score < minConfidenceFirstLock)
        ) {
            val g = aligner.align(cleanText, preferredRange = null)
            val gs = scoreTranscription(tokens, g)
            if (g != null && gs >= minConfidenceFirstLock) {
                match = g
                score = gs
                notes += "aday penceresi tutmadi, tum Kuran'da bulundu"
            }
        } else if (!hold && state.state == NamazState.BEKLEME && state.pendingMatch != null && preferredRange != null &&
            wordCount >= MIN_WORD_COUNT_FIRST_LOCK && match != null && score < 100.0
        ) {
            // BEKLEME + aday, pencere tuttu ama tam degil: tum Kuran'da baska yer tek parcada kilit kuralini geciyorsa o.
            // Belirsiz aday "قل أعوذ برب" (113:1) sonrasi "قل أعوذ برب الناس" pencerede 113:1'e ~91 alip adayi YANLIS
            // dogruluyordu (kilit Felak'ta kaliyordu); tum Kuran'da 114:1 100 ve "الناس" ayirt edici.
            val g = aligner.align(cleanText, preferredRange = null)
            val gs = scoreTranscription(tokens, g)
            val outside = g != null && g.startWordIdx !in preferredRange
            val uc = if (g != null && outside && gs > score) uniqueCheck(cleanText, tokens, g, gs, wordCount) else null
            if (g != null && uc != null && uc.unique) {
                match = g
                score = gs
                notes += "aday penceresi yerine tum Kuran (${uc.note})"
            } else if (g != null && outside && gs >= score + VERIFY_GLOBAL_MARGIN) {
                // Aday penceresindeki eslesme tum Kuran'daki en iyi yerden cok zayifsa adayi dogrulamaz (yeni aday olur)
                notes += "aday penceresi ${"%.1f".format(score)} << tum Kuran ${"%.1f".format(gs)}: dogrulama sayilmadi"
                match = g
                score = gs
            }
        }

        // Kilitliyken (FATIHA/ZAMM/ARA) pencere emin degilse tum Kuran'da da ara: sure gecisi. Eskiden
        // ABANDON_LOCK_AFTER_LOST (6 chunk, ~30 sn) dolmadan baska yere gecilemiyordu; ustelik Fatiha
        // penceresi zamm suresinin besmelesine / kisa ifadelerine 50-80 skorla "eslesip" kilidi tutuyordu.
        // "natural" | "verified" (gecildi) | "candidate" (aday, sonraki chunk dogrulayacak)
        // Taze gecisin yeniden kontrolu (bkz. FRESH_JUMP_CHUNKS): gecis parcasi da yeni surenin acilisina oturmali
        var freshFix = false
        val fj = state.freshJump
        if (!hold && state.state == NamazState.ZAMM && fj != null && chunkIndex - fj.first in 1..FRESH_JUMP_CHUNKS &&
            !lockAbandoned && !fatihaJump && fatihaCand == null && (match == null || score < minConfidence)
        ) {
            val g = aligner.align(cleanText, preferredRange = null)
            val gs = scoreTranscription(tokens, g)
            if (g != null && gs >= FRESH_JUMP_MIN_SCORE && gs >= (if (match != null) score else 0.0) + JUMP_MARGIN) {
                val (gfs, gfa) = collectVerses(g.startWordIdx, g.endWordIdx).first()
                val ow = openingWindow(gfs)
                if (gfs != state.lastSurah && gfa <= 2 && ow != null) {
                    val pm = aligner.align(fj.second, preferredRange = ow)
                    val pTokens = fj.second.trim().split(Regex("\\s+")).map { Normalizer.normalize(it) }.filter { it.isNotEmpty() }
                    if (pm != null && isOpeningMatch(pm) && pm.startWordIdx <= g.startWordIdx &&
                        scoreTranscription(pTokens, pm) >= minConfidenceFirstLock
                    ) {
                        notes += "taze gecis duzeltmesi: $gfs:$gfa ${"%.1f".format(gs)} (pencere " +
                            "${"%.1f".format(if (match != null) score else 0.0)}; gecis parcasi $gfs acilisina oturuyor)"
                        match = g
                        score = gs
                        freshFix = true
                    }
                }
            }
        }

        var jump: String? = if (fatihaJump) "natural" else if (freshFix) "verified" else null
        var jumpCandidateMatch: AlignmentMatch? = null  // UI adayi gosterebilsin diye
        var opening = false   // sure basi gecisi (bkz. OPENING_MIN_FUZZY)
        var fresh = false
        val shortJump = wordCount == JUMP_SHORT_WORDS && atTransitionPoint(state)
        if (!hold && (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM || state.state == NamazState.ARA) &&
            preferredRange != null && !lockAbandoned && (wordCount >= MIN_WORD_COUNT_FIRST_LOCK || shortJump) &&
            fatihaCand == null && (match == null || score < JUMP_SEARCH_BELOW)
        ) {
            val g = aligner.align(cleanText, preferredRange = null)
            val gs = scoreTranscription(tokens, g)
            val base = if (match != null) score else 0.0
            val contentOk = g != null && contentWordCount(g) >= 2
            if (g != null) {
                val (gs0, ga0) = collectVerses(g.startWordIdx, g.endWordIdx).firstOrNull() ?: Pair(0, 0)
                notes += "gecis aramasi: $gs0:$ga0 ${"%.1f".format(gs)} (pencere ${"%.1f".format(base)})"
            }
            var ok = contentOk && gs >= minConfidenceFirstLock && gs >= base + JUMP_MARGIN
            // Sure basi: gecis noktasinda surenin acilisina oturan eslesme ham hizalama skoruyla (bkz. OPENING_MIN_FUZZY)
            if (contentOk && !ok && (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM) &&
                atTransitionPoint(state) && g!!.score >= OPENING_MIN_FUZZY && g.score >= base + JUMP_MARGIN &&
                isOpeningMatch(g)
            ) {
                val (os, oa) = collectVerses(g.startWordIdx, g.endWordIdx).first()
                opening = isNaturalTransition(state, os, oa)
                ok = opening
            } else if (contentOk && !ok && state.state == NamazState.FATIHA && state.zammSurah != null &&
                atTransitionPoint(state) && g!!.score >= OPENING_MIN_FUZZY && g.score >= base + JUMP_MARGIN
            ) {
                // Kalinan yerden devam da ham hizalama skoruyla: Fatiha sonunda tum Kuran'daki en iyi yer onceki zamm'in
                // devam penceresindeyse (bkz. CONTINUE_*) sozluk cezasi esige takilmasin. Yatsi 22.10 sabit parca: 2. rekat
                // "وعلمناه صنعة لبوس لكم" ASR'de "وعلمناه صنعة لوس لكل تعز" → en iyi yer 21:80 (ham 89.4, cezali 69.2 < 70).
                val zs = state.zammSurah!!
                val cw = state.zammAyah?.let { continueWindow(zs, it) }
                ok = cw != null && g.startWordIdx in cw
                if (ok) notes += "kalinan yerden devam (ham hizalama ${"%.1f".format(g.score)})"
            }
            val gv = if (ok) collectVerses(g!!.startWordIdx, g.endWordIdx) else emptyList()
            if (ok && !opening && wordCount < MIN_WORD_COUNT_FIRST_LOCK) {
                // Kisa parca: sadece Kuran'da tek yerde gecen ifadeyle dogal gecis (aday da uretmez)
                val (fs, fa) = gv.first()
                val phrase = cleanText.trim().split(Regex("\\s+")).filter { it.isNotEmpty() }.map { bareToken(it) }
                ok = gs >= JUMP_SHORT_MIN_SCORE && isNaturalTransition(state, fs, fa) && phraseCount(phrase) == 1
            }
            if (ok && g != null) {
                var gm: AlignmentMatch = g
                var gsc = gs
                var gvv = gv
                // Hatim: Fatiha sonunda onceki zamm'in kaldigi yerden devam (bkz. CONTINUE_*)
                var cont = false
                val zs = state.zammSurah
                val za = state.zammAyah
                if (state.state == NamazState.FATIHA && zs != null && za != null && atTransitionPoint(state)) {
                    val cw = continueWindow(zs, za)
                    if (cw != null && gm.startWordIdx in cw) {
                        cont = true
                    } else if (cw != null) {
                        val cm = aligner.align(cleanText, preferredRange = cw)
                        val cs = scoreTranscription(tokens, cm)
                        val prior = cm != null && !opening && cs >= minConfidenceFirstLock &&
                            cs >= gsc - CONTINUE_PRIOR_MARGIN && !isOpeningMatch(gm)
                        if (cm != null && ((cs >= NATURAL_MIN_SCORE && cs >= gsc - CONTINUE_MARGIN) || prior)) {
                            gm = cm
                            gsc = cs
                            gvv = collectVerses(cm.startWordIdx, cm.endWordIdx)
                            cont = true
                            opening = false
                            val (c0s, c0a) = gvv.first()
                            notes += "hatim devami: $c0s:$c0a ${"%.1f".format(cs)} (onceki zamm $zs:$za)"
                        }
                    }
                }
                var jc = state.jumpCandidate
                if (jc != null && chunkIndex - jc.chunkIndex > 2) jc = null
                // Aday penceresi: tum Kuran eslesmesi adayin disindaysa adayin cevresinde de ara (CANDIDATE_WINDOW_MARGIN)
                if (jc != null && !cont) {
                    val (f0s, f0a) = gvv.first()
                    val (l0s, l0a) = gvv.last()
                    if (!(verifyPending(jc, f0s, f0a) || verifyPending(jc, l0s, l0a))) {
                        val jw = ayahWindow(jc.surah, jc.ayah, PENDING_VERIFY_AYAH_WINDOW, PENDING_VERIFY_AYAH_WINDOW)
                        val jm = if (jw != null) aligner.align(cleanText, preferredRange = jw) else null
                        val js = scoreTranscription(tokens, jm)
                        if (jm != null && js >= minConfidenceFirstLock && js >= gsc - CANDIDATE_WINDOW_MARGIN) {
                            gm = jm
                            gsc = js
                            gvv = collectVerses(jm.startWordIdx, jm.endWordIdx)
                            opening = false
                            notes += "aday penceresi: ${jc.surah}:${jc.ayah} cevresi ${"%.1f".format(js)}"
                        }
                    }
                }
                // Zamm ayet basindan baslar: ayni ifade iki yerde (yatsi 19.10: "الذين اتخذوا دينهم" 6:70 "وذر ..." ortasi /
                // 7:51 basi) → ayet basindaki ikinci yer (AYAH_START_TIE_MARGIN)
                run {
                    val (f0s, f0a) = gvv.first()
                    if (!opening && !cont && state.state == NamazState.FATIHA && gsc >= NATURAL_MIN_SCORE &&
                        isNaturalTransition(state, f0s, f0a) && !startsAyah(gm)) {
                        val ru = runnerUpMatch(cleanText, gm)
                        if (ru != null && ru.score >= gm.score - AYAH_START_TIE_MARGIN && startsAyah(ru)) {
                            val rv = collectVerses(ru.startWordIdx, ru.endWordIdx)
                            val rsc = scoreTranscription(tokens, ru)
                            val (r0s, r0a) = rv.first()
                            if (rsc >= NATURAL_MIN_SCORE && isNaturalTransition(state, r0s, r0a)) {
                                notes += "ayet basi tercih: $r0s:$r0a (ilk yer $f0s:$f0a ayet ortasi)"
                                gm = ru
                                gsc = rsc
                                gvv = rv
                            }
                        }
                    }
                }
                // Sure acilisi onceligi: bkz. OPENING_PREFER_MARGIN
                if (!opening && !cont && state.state == NamazState.FATIHA && gsc >= minConfidenceFirstLock &&
                    atTransitionPoint(state) && !isOpeningMatch(gm)
                ) {
                    val op = openingPreference(cleanText, tokens)
                    if (op != null && op.second >= gsc - OPENING_PREFER_MARGIN) {
                        val ov = collectVerses(op.first.startWordIdx, op.first.endWordIdx)
                        val (o0s, o0a) = ov.first()
                        val (f0s, f0a) = gvv.first()
                        notes += "sure acilisi onceligi: $o0s:$o0a ${"%.1f".format(op.second)} (ilk yer $f0s:$f0a ${"%.1f".format(gsc)})"
                        gm = op.first
                        gsc = op.second
                        gvv = ov
                        opening = true
                    }
                }
                val (gfs, gfa) = gvv.first()
                val (gls, gla) = gvv.last()
                val inCandidate = jc != null && (verifyPending(jc, gfs, gfa) || verifyPending(jc, gls, gla))
                // Devam (kalinan yer) dogal gecis: devam onceliginde skor NATURAL_MIN_SCORE altinda olabilir (CONTINUE_PRIOR_MARGIN)
                var natural = opening || cont || (isNaturalTransition(state, gfs, gfa) && gsc >= NATURAL_MIN_SCORE)
                val tieWith = if (natural && !cont && isOpeningMatch(gm)) openingTie(cleanText, gm) else null
                val tie = tieWith != null
                if (tie) {
                    natural = false
                    opening = false
                    notes += "iki surenin acilisi ayni (ikinci yer $tieWith): gecis adayi"
                }
                // Zamm sonundan Fatiha'ya dogal gecis en az FATIHA_FAST_LOCK_MIN_WORDS kelimeyle (Fatiha yoklamasindaki gibi):
                // sabah 21.10 sabit parca, Adiyat sonu "إن ربهم بهم" → ASR "إن رب العالمين" Fatiha 1:2'ye dogal gecis oldu
                // (yeni rekat rukû / secdeden sonra gelir — kilit kaybolmus zamm / ARA'da Fatiha yoklamasi 3 kelimeyle)
                val early = gfs == 1 && earlyFatiha(state, chunkIndex, gla)
                if (natural && gfs == 1 && state.state == NamazState.ZAMM && !lockAbandoned &&
                    wordCount < FATIHA_FAST_LOCK_MIN_WORDS) {
                    natural = false
                    opening = false
                    notes += "zamm sonundan Fatiha'ya $wordCount kelime (min $FATIHA_FAST_LOCK_MIN_WORDS): dogal gecis degil"
                } else if (early) {
                    natural = false
                    opening = false
                    notes += "erken Fatiha (son saglam eslesmeden ${chunkIndex - (state.lastSolidChunk ?: chunkIndex)} parca): gecis adayi"
                }
                jump = when {
                    natural -> "natural"
                    inCandidate -> "verified"
                    // Fark payi: Kuran'da baska yerde benzeri olmayan net eslesme ikinci parcayi beklemez
                    // (telefon kaydi: 55 → 107 gecisi 12 → 7 sn; gurultu testinde yanlis kilit artmadi)
                    !tie && !early && uniqueCheck(cleanText, tokens, gm, gsc, wordCount).let { uc ->
                        if (uc.unique) notes += "gecis tek parcada (${uc.note})"
                        uc.unique
                    } -> "verified"
                    // Geri duzeltme: pencere eslesmesi zayif, ayni surede kalinan yerin 1-2 ayet gerisi tum Kuran'da en az
                    // JUMP_MARGIN iyi → onceki zayif eslesme konumu ileri tasimis (okuma geri gitmez). Yatsi 21.10, 2. rekat: 21:24
                    // okunurken bozuk "بدأ يدع لنا" 21:25'e 65 ile eslesti; pencere (21:25-27) 21:24'u kapsamadigindan sonraki
                    // parcalar 21:27 / 21:28'e 50-57 ile kaydi (tum Kuran'da 21:24 84.5), sonra 21:25'e geri dondu.
                    state.state == NamazState.ZAMM && score < minConfidenceFirstLock && gfs == state.lastSurah &&
                        state.lastAyah.let { la -> la != null && gla >= la - RESUME_BACK && gla < la } -> {
                        notes += "geri duzeltme: $gls:$gla ${"%.1f".format(gsc)} (pencere ${"%.1f".format(score)})"
                        "verified"
                    }
                    else -> {
                        state.jumpCandidate = PendingMatch(
                            surah = gls, ayah = gla, wordIndex = gm.endWordIdx, chunkIndex = chunkIndex,
                        )
                        jumpCandidateMatch = gm
                        "candidate"
                    }
                }
                if (jump != "candidate") {
                    match = gm
                    score = gsc
                    notes += if (opening) "sure basi gecisi" else if (cont) "hatim devami" else if (jump == "natural") "dogal gecis" else "gecis dogrulandi"
                }
                fresh = jump == "natural" && state.state == NamazState.FATIHA && !opening && !cont
            }
        }
        if (fatihaCand != null) {
            jump = "candidate"
            state.jumpCandidate = fatihaCand
            jumpCandidateMatch = fatihaCandMatch
        }

        // BEKLEME'de belirsiz eslesme yerine Fatiha basi — bkz. FATIHA_ARA_MARGIN
        val m0 = match
        if (!hold && state.state == NamazState.BEKLEME && m0 != null && jump == null &&
            state.pendingMatch == null &&
            wordCount >= FATIHA_FAST_LOCK_MIN_WORDS && collectVerses(m0.startWordIdx, m0.startWordIdx).first().first != 1
        ) {
            val fm = aligner.align(cleanText, preferredRange = fatihaRange)
            val fs = scoreTranscription(tokens, fm)
            if (fm != null && fs >= FATIHA_FAST_LOCK_MIN_SCORE && fs >= score - FATIHA_ARA_MARGIN &&
                collectVerses(fm.startWordIdx, fm.startWordIdx).first().second <= 3
            ) {
                val ru = runnerUpMatch(cleanText, m0)
                if (ru != null && score - scoreTranscription(tokens, ru) < AMBIGUOUS_MARGIN) {
                    val (m0s, m0a) = collectVerses(m0.startWordIdx, m0.startWordIdx).first()
                    notes += "belirsiz eslesme ($m0s:$m0a ${"%.1f".format(score)}) yerine Fatiha ${"%.1f".format(fs)}"
                    match = fm
                    score = fs
                }
            }
        }

        val inPreferred = match != null && preferredRange != null &&
                match.startWordIdx in preferredRange

        // 5. Esik degerlerini belirle
        val isFirstLock = state.state == NamazState.BEKLEME
        // Kilit kayboldu (6+ kayip chunk ya da ARA): yeniden kilit ilk kilit gibi. Eskiden ARA'da tum Kuran'da
        // 50 skorla tek chunk kilit veriyordu (gercek namaz: selam → 6:54, "سمع الله حمدا" → 3:181)
        val relock = lockAbandoned || state.state == NamazState.ARA
        val effectiveThreshold: Double
        val requireMinWords: Int
        when {
            relock -> {
                effectiveThreshold = minConfidenceFirstLock
                requireMinWords = MIN_WORD_COUNT_FIRST_LOCK
            }
            isFirstLock -> {
                effectiveThreshold = minConfidenceFirstLock
                requireMinWords = MIN_WORD_COUNT_FIRST_LOCK
            }
            else -> {
                effectiveThreshold = minConfidence
                requireMinWords = 0
            }
        }

        val insufficientWords = requireMinWords > 0 && wordCount < requireMinWords
        // Okuma ara verdiyse kisa + zayif eslesme devam sayilmaz — bkz. PAUSE_LOST_CHUNKS
        val pausedWeak = state.state == NamazState.ZAMM && !relock && !opening && state.lostChunks >= PAUSE_LOST_CHUNKS &&
            wordCount < MIN_WORD_COUNT_FIRST_LOCK && score < minConfidenceFirstLock
        val tekbirWeak = state.state == NamazState.ZAMM && !relock && !opening && jump != "natural" && jump != "verified" &&
            tekbirAfterReading(state) && wordCount < MIN_WORD_COUNT_FIRST_LOCK && score < TEKBIR_SHORT_MIN_SCORE
        // Kilitliyken tek basina "(و)الحمد لله" zayif eslesmesi okuma degil — bkz. STOCK_PHRASES
        val stockWeak = (state.state == NamazState.FATIHA || state.state == NamazState.ZAMM) && !relock &&
            jump != "natural" && jump != "verified" && score < minConfidenceFirstLock &&
            cleanText.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() } in STOCK_PHRASES

        // 6. Skor / kelime yetersizse low_confidence
        // Sure basi gecisi kendi esigiyle (ham hizalama) dogrulandi; sozluk cezali skor esige takilmasin
        if ((score < effectiveThreshold && !opening) || match == null || insufficientWords || pausedWeak || stockWeak ||
            tekbirWeak
        ) {
            val where = match?.let { m ->
                collectVerses(m.startWordIdx, m.endWordIdx).firstOrNull()?.let { (s0, a0) -> " @ $s0:$a0" }
            } ?: ""
            val reason = withNotes(when {
                match == null -> "eslesme yok"
                insufficientWords -> "yetersiz kelime ($wordCount<$requireMinWords)$where"
                tekbirWeak && !stockWeak && score >= effectiveThreshold ->
                    "tekbirden sonra kisa eslesme ($wordCount kelime, skor ${"%.1f".format(score)}$where < " +
                        "${"%.0f".format(TEKBIR_SHORT_MIN_SCORE)})"
                stockWeak && score >= effectiveThreshold ->
                    "kalip ifade '${cleanText.trim()}' zayif eslesme (skor ${"%.1f".format(score)}$where < " +
                        "${"%.0f".format(minConfidenceFirstLock)})"
                pausedWeak && score >= effectiveThreshold ->
                    "okuma ara verdi (${state.lostChunks} kayip parca): kisa zayif eslesme ($wordCount kelime, " +
                        "skor ${"%.1f".format(score)}$where < ${"%.0f".format(minConfidenceFirstLock)})"
                else -> {
                    val tag = when {
                        relock -> "yeniden kilit esigi"
                        isFirstLock -> "ilk kilit esigi"
                        else -> "esik"
                    }
                    "skor ${"%.1f".format(score)}$where < $tag ${"%.0f".format(effectiveThreshold)}"
                }
            }, notes)
            state.lostChunks += 1
            cleanupPendingIfStale(state, chunkIndex)
            applyTransition(state, matched = false, firstSurah = null, firstAyah = null)
            val jc = state.jumpCandidate
            if (jump == "candidate" && jc != null) {
                // Sure gecisi adayi — kilit yerinde, UI adayi gosterir; sonraki chunk dogrularsa gecilir
                return ChunkResult(
                    chunkIndex = chunkIndex,
                    stateBefore = stateBefore,
                    state = state.state,
                    status = ChunkStatus.PENDING,
                    rms = rms,
                    text = transcribedText,
                    wordCount = wordCount,
                    confidence = score,
                    pendingSurah = jc.surah,
                    pendingAyah = jc.ayah,
                    matchStartWordIdx = jumpCandidateMatch?.startWordIdx,
                    matchEndWordIdx = jumpCandidateMatch?.endWordIdx,
                    reason = withNotes("sure gecisi adayi ${jc.surah}:${jc.ayah}, dogrulama bekleniyor", notes),
                    jumpCandidate = true,
                    preferredRange = preferredRange,
                    inPreferred = inPreferred,
                    nearSurahEnd = nearSurahEnd,
                )
            }
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.LOW_CONFIDENCE,
                rms = rms,
                text = transcribedText,
                wordCount = wordCount,
                confidence = score,
                reason = reason,
                preferredRange = preferredRange,
                inPreferred = inPreferred,
                lockAbandoned = lockAbandoned,
                nearSurahEnd = nearSurahEnd,
            )
        }

        // 7. Match bulundu — verses cikar
        val verses = collectVerses(match.startWordIdx, match.endWordIdx)
        if (verses.isEmpty()) {
            // Imkansiz ama defansif
            return ChunkResult(
                chunkIndex = chunkIndex,
                stateBefore = stateBefore,
                state = state.state,
                status = ChunkStatus.LOW_CONFIDENCE,
                rms = rms,
                text = transcribedText,
                wordCount = wordCount,
                reason = "iç hata: verses bos",
            )
        }
        val (firstSurah, firstAyah) = verses.first()
        val (lastSurah, lastAyah) = verses.last()

        // 8. BEKLEME ve yeniden kilit icin pending dogrulama (Fatiha basina guclu eslesme haric — namazda ilk okunan)
        // Bekleme (kamet / rukû / selam sonrasi) varken Fatiha'nin herhangi bir ayeti, 3 kelime yeter
        val fatihaFast = state.state == NamazState.BEKLEME && firstSurah == 1 && score >= FATIHA_FAST_LOCK_MIN_SCORE &&
                ((firstAyah <= 3 && wordCount >= FATIHA_FAST_LOCK_MIN_WORDS) ||
                    (hold && wordCount >= MIN_WORD_COUNT_FIRST_LOCK))
        // Yeniden kilitte dogrulamasiz: rekat basi Fatiha (rukû/secde sonrasi beklenen), kalinan yerden devam ya da
        // 2 parcayla dogrulanmis gecis (ARA'da gecis adayi dogrulaninca bir de aday dogrulamasi bekleniyordu)
        val prevAyah = state.lastAyah
        val relockFast = relock && (
            jump == "verified" ||
                (firstSurah == 1 && score >= FATIHA_FAST_LOCK_MIN_SCORE && wordCount >= MIN_WORD_COUNT_FIRST_LOCK) ||
                (firstSurah == state.lastSurah && prevAyah != null &&
                    firstAyah >= prevAyah - RESUME_BACK && firstAyah <= prevAyah + PREFERRED_AYAH_WINDOW_ARA)
            )
        // Tek parcada kilit (fark payi / ayirt edici kelime): sadece ilk kilit (BEKLEME, bekleme yokken) — bkz. UNIQUE_LOCK_*
        val uc = if (state.state == NamazState.BEKLEME && !fatihaFast && !hold) {
            uniqueCheck(cleanText, tokens, match, score, wordCount)
        } else {
            null
        }
        val unique = uc?.unique == true
        if (((state.state == NamazState.BEKLEME && !fatihaFast) || (relock && !relockFast)) && !unique) {
            uc?.note?.let { notes += it }
            val pm = state.pendingMatch
            if (pm == null) {
                // Ilk match — pending olarak kaydet
                val amb = ambiguity(cleanText, tokens, match, score)
                state.pendingMatch = PendingMatch(
                    surah = lastSurah, ayah = lastAyah,
                    wordIndex = match.endWordIdx, chunkIndex = chunkIndex,
                    altSurah = amb?.altSurah, altAyah = amb?.altAyah,
                )
                amb?.let { notes += it.note }
                return ChunkResult(
                    chunkIndex = chunkIndex,
                    stateBefore = stateBefore,
                    state = state.state,
                    status = ChunkStatus.PENDING,
                    rms = rms,
                    text = transcribedText,
                    wordCount = wordCount,
                    confidence = score,
                    pendingSurah = lastSurah,
                    pendingAyah = lastAyah,
                    ambiguous = amb != null,
                    // UI adayi (kilit oncesi) gosterebilsin diye — state machine karari etkilenmez
                    matchStartWordIdx = match.startWordIdx,
                    matchEndWordIdx = match.endWordIdx,
                    reason = withNotes("aday $lastSurah:$lastAyah (skor ${"%.1f".format(score)}), dogrulama bekleniyor", notes),
                    preferredRange = preferredRange,
                    inPreferred = inPreferred,
                )
            } else {
                // Onceki pending var — dogrulanabiliyor mu?
                var verified = verifyPending(pm, firstSurah, firstAyah) ||
                        verifyPending(pm, lastSurah, lastAyah)
                // Belirsiz adayi geriye giden parca dogrulamaz (okuma ileri gider): asr 21.10, "هو الرحمن الرحيم" 2:163 sonu /
                // 59:22 sonu esit (belirsiz aday 2:163) → sonraki "لا اله الا هو" (59:23 basi) 2:163'te adayin GERISINE oturup
                // dogruladi, 2:163'e kilit. Ayetu'l-Kursi'de ("الله لا ال" 2:255 / 3:2 → "لا اله الا هو") dogrulayan parca
                // ileride biter. (Ayirt etmeyen parca dogrulamasin denendi: Kursi ilk kilidi 10 → 20 sn.)
                if (verified && pm.altSurah != null && match.endWordIdx <= pm.wordIndex) {
                    verified = false
                    notes += "belirsiz aday ${pm.surah}:${pm.ayah} (ikinci yer ${pm.altSurah}:${pm.altAyah}) geriye giden " +
                        "parcayla dogrulanmaz"
                }
                if (!verified) {
                    // Reddedildi, yeni aday
                    val oldPending = pm
                    val amb = ambiguity(cleanText, tokens, match, score)
                    state.pendingMatch = PendingMatch(
                        surah = lastSurah, ayah = lastAyah,
                        wordIndex = match.endWordIdx, chunkIndex = chunkIndex,
                        altSurah = amb?.altSurah, altAyah = amb?.altAyah,
                    )
                    amb?.let { notes += it.note }
                    return ChunkResult(
                        chunkIndex = chunkIndex,
                        stateBefore = stateBefore,
                        state = state.state,
                        status = ChunkStatus.PENDING,
                        rms = rms,
                        text = transcribedText,
                        wordCount = wordCount,
                        confidence = score,
                        pendingSurah = lastSurah,
                        pendingAyah = lastAyah,
                        ambiguous = amb != null,
                        matchStartWordIdx = match.startWordIdx,
                        matchEndWordIdx = match.endWordIdx,
                        reason = withNotes(
                            "onceki aday (${oldPending.surah}:${oldPending.ayah}) tutmadi, yeni aday $lastSurah:$lastAyah", notes,
                        ),
                        preferredRange = preferredRange,
                        inPreferred = inPreferred,
                    )
                }
                // Dogrulandi, asagi gec
            }
        }

        // 9. Match kabul edildi - state guncelle
        val pmBefore = state.pendingMatch
        val acceptReason = when {
            fatihaFast -> "Fatiha hizli kilit"
            unique -> "tek parcada kilit (${uc?.note})"
            relock && relockFast -> when {
                jump == "verified" -> "yeniden kilit: gecis 2 parcayla dogrulandi"
                firstSurah == 1 -> "yeniden kilit: rekat basi Fatiha"
                else -> "yeniden kilit: kalinan yerden devam"
            }
            state.state == NamazState.BEKLEME || relock ->
                "aday dogrulandi (${pmBefore?.surah}:${pmBefore?.ayah} → $firstSurah:$firstAyah)"
            else -> "kilitli takip"
        }
        val res = commitMatch(
            state, chunkIndex, match, score, wordCount, stateBefore, jump, rms, transcribedText, withNotes(acceptReason, notes),
            preferredRange, inPreferred, nearSurahEnd, lockAbandoned,
        )
        if (fresh) state.freshJump = Pair(chunkIndex, cleanText)
        return res
    }

    /** Eslesmeyi kabul et: durum gecisi, en ileri ayet, bosluk doldurma, son konum (Python commit_match ile birebir). */
    private fun commitMatch(
        state: SessionState,
        chunkIndex: Int,
        match: AlignmentMatch,
        score: Double,
        wordCount: Int,
        stateBefore: NamazState,
        jump: String?,
        rms: Double,
        text: String,
        reason: String,
        preferredRange: IntRange?,
        inPreferred: Boolean,
        nearSurahEnd: Boolean,
        lockAbandoned: Boolean,
    ): ChunkResult {
        val verses = collectVerses(match.startWordIdx, match.endWordIdx)
        val (firstSurah, firstAyah) = verses.first()
        val (lastSurah, lastAyah) = verses.last()
        applyTransition(state, matched = true, firstSurah = firstSurah, firstAyah = firstAyah)
        state.pendingMatch = null
        state.holdUntil = null
        // Aday, gecis yapildiysa ya da pencere emin eslestiyse biter; zayif pencere eslesmesinde bekler
        if (jump == "natural" || jump == "verified" || score >= JUMP_SEARCH_BELOW) {
            state.jumpCandidate = null
        }
        // En ileri ayet: sure degisince / Fatiha'ya yeni girince sifirdan
        if (state.lastSurah != lastSurah || (state.state == NamazState.FATIHA && stateBefore != NamazState.FATIHA)) {
            state.maxAyah = lastAyah
        } else {
            state.maxAyah = max(state.maxAyah ?: 0, lastAyah)
        }

        // 10. Gap fill
        val gapFilledCount = computeGapFill(state, firstSurah, firstAyah)
        val finalVerses = if (gapFilledCount > 0) {
            val filled = (1..gapFilledCount).map { i ->
                Pair(state.lastSurah!!, state.lastAyah!! + i)
            }
            filled + verses
        } else {
            verses
        }

        val verseRefs = finalVerses.mapIndexed { i, (s, a) ->
            VerseRef(s, a, matchedFromAlignment = i >= gapFilledCount)
        }

        // 11. State guncelle (son zamm konumu: hatim devami icin, bkz. CONTINUE_AHEAD)
        if (state.state == NamazState.ZAMM) {
            val za = state.zammAyah
            if (state.zammSurah == lastSurah && za != null) {
                state.zammAyah = max(za, lastAyah)
            } else {
                state.zammSurah = lastSurah
                state.zammAyah = lastAyah
            }
        }
        state.lastWordIndex = match.endWordIdx
        state.lastSurah = lastSurah
        state.lastAyah = lastAyah
        state.lostChunks = 0
        state.matchedChunks += 1
        state.freshJump = null
        state.lastMatchChunk = chunkIndex
        if (wordCount >= MIN_WORD_COUNT_FIRST_LOCK && score >= minConfidenceFirstLock) state.lastSolidChunk = chunkIndex

        return ChunkResult(
            chunkIndex = chunkIndex,
            stateBefore = stateBefore,
            state = state.state,
            status = ChunkStatus.MATCHED,
            rms = rms,
            text = text,
            wordCount = wordCount,
            confidence = score,
            verses = verseRefs,
            matchStartWordIdx = match.startWordIdx,
            matchEndWordIdx = match.endWordIdx,
            reason = reason,
            preferredRange = preferredRange,
            inPreferred = inPreferred,
            nearSurahEnd = nearSurahEnd,
            lockAbandoned = lockAbandoned,
            gapFilled = gapFilledCount,
        )
    }

    /** En iyi eslesmenin araligina degmeyen en iyi ikinci yer (fark payi, bkz. UNIQUE_LOCK_*). */
    private fun runnerUpMatch(cleanText: String, best: AlignmentMatch): AlignmentMatch? =
        aligner.align(cleanText, preferredRange = null, excludeRange = best.startWordIdx..best.endWordIdx)

    /**
     * Belirsiz aday: ikinci yer (araliga degmeyen) AMBIGUOUS_MARGIN'den yakinsa gerekceli log notu, degilse null
     * (Python: runner_up_match + score_transcription, birebir). Aligner onbellegi ayni aramayi tekrar yapmaz.
     */
    /** Belirsiz aday: gerekceli log notu + ikinci yerin son ayeti. */
    private class Ambiguity(val note: String, val altSurah: Int?, val altAyah: Int?)

    private fun ambiguity(cleanText: String, tokens: List<String>, match: AlignmentMatch, score: Double): Ambiguity? {
        val ru = runnerUpMatch(cleanText, match) ?: return null
        val ruScore = scoreTranscription(tokens, ru)
        if (score - ruScore >= AMBIGUOUS_MARGIN) return null
        val last = collectVerses(ru.startWordIdx, ru.endWordIdx).lastOrNull()
        val ref = last?.let { (s0, a0) -> "$s0:$a0" } ?: "?"
        return Ambiguity(
            "belirsiz aday (ikinci yer $ref ${"%.1f".format(ruScore)}, fark ${"%.1f".format(score - ruScore)} < " +
                "$AMBIGUOUS_MARGIN): ekranda gosterilmez",
            last?.first, last?.second,
        )
    }

    /** Tek parcada kilit karari + gerekceli log notu (ikinci yer, fark, ayirt edici kelime). */
    private class UniqueCheck(val unique: Boolean, val note: String?)

    /**
     * Tek parcada kilit: skor >= UNIQUE_LOCK_MIN_SCORE, >= UNIQUE_LOCK_MIN_WORDS kelime ve ikinci yerden
     * UNIQUE_LOCK_MARGIN fark ya da EXCLUSIVE_LOCK_MARGIN fark + ayirt edici kelime (Python is_unique_match ile birebir).
     */
    private fun uniqueCheck(
        cleanText: String,
        tokens: List<String>,
        match: AlignmentMatch,
        score: Double,
        wordCount: Int,
    ): UniqueCheck {
        if (score < UNIQUE_LOCK_MIN_SCORE || wordCount < UNIQUE_LOCK_MIN_WORDS) return UniqueCheck(false, null)
        val ru = runnerUpMatch(cleanText, match)
        val ruScore = if (ru != null) scoreTranscription(tokens, ru) else 0.0
        val margin = score - ruScore
        val ref = ru?.let { collectVerses(it.startWordIdx, it.endWordIdx).firstOrNull() }
            ?.let { (s0, a0) -> " $s0:$a0" } ?: ""
        val base = "ikinci yer$ref ${"%.1f".format(ruScore)}, fark ${"%.1f".format(margin)}"
        if (margin >= UNIQUE_LOCK_MARGIN) return UniqueCheck(true, "$base >= $UNIQUE_LOCK_MARGIN")
        if (margin < EXCLUSIVE_LOCK_MARGIN || ru == null) return UniqueCheck(false, "$base < $UNIQUE_LOCK_MARGIN")
        val best = matchAyahWords(match)
        val other = matchAyahWords(ru)
        val exclusive = cleanText.trim().split(Regex("\\s+")).map { bareToken(it) }.firstOrNull {
            it.length >= EXCLUSIVE_MIN_LETTERS && it !in BESMELE_TOKENS && it in best && it !in other
        }
        return if (exclusive != null) {
            UniqueCheck(true, "$base, ayirt edici kelime '$exclusive'")
        } else {
            UniqueCheck(false, "$base < $UNIQUE_LOCK_MARGIN, ayirt edici kelime yok")
        }
    }

    /** Eslesmenin kapsadigi ayetlerin tum normalize kelimeleri (Python match_ayah_words). */
    private fun matchAyahWords(m: AlignmentMatch): Set<String> {
        val out = HashSet<String>()
        for (key in collectVerses(m.startWordIdx, m.endWordIdx)) {
            val r = ayahToCorpusRange[key] ?: continue
            for (i in r.first..r.second) {
                for (part in index.getNormalized(i).split(' ')) if (part.isNotEmpty()) out.add(part)
            }
        }
        return out
    }

    /** Gerekceli log: ana neden + baglam notlari ("skor 62 @ 12:99 < ilk kilit esigi 70; pencere 103:1-103:3"). */
    private fun withNotes(main: String, notes: List<String>): String =
        if (notes.isEmpty()) main else main + "; " + notes.joinToString("; ")

    /** Kelime araligini "55:3-55:9" olarak yaz (log icin). */
    private fun rangeLabel(r: IntRange): String {
        val a = collectVerses(r.first, r.first).firstOrNull()
        val b = collectVerses(r.last, r.last).firstOrNull()
        return if (a == null || b == null) "${r.first}-${r.last}" else "${a.first}:${a.second}-${b.first}:${b.second}"
    }

    // ============================================================
    // Score transcription — Python score_transcription
    // ============================================================
    /**
     * Skor hesabi: fuzzy * sqrt(vocab_coverage) * pow(unique_ratio, 0.3)
     * Tekrar veya dusuk vocab penaltisi.
     */
    private fun scoreTranscription(tokens: List<String>, match: AlignmentMatch?): Double {
        if (tokens.isEmpty()) return 0.0
        val fuzzy = match?.score ?: 0.0
        val inVocab = tokens.count { it in corpusVocab }
        val vocabCoverage = inVocab.toDouble() / tokens.size
        val uniqueRatio = tokens.toSet().size.toDouble() / tokens.size

        // Ardisik tekrarlar
        var maxConsec = 1
        var c = 1
        for (i in 1 until tokens.size) {
            if (tokens[i] == tokens[i - 1]) {
                c++
                if (c > maxConsec) maxConsec = c
            } else {
                c = 1
            }
        }

        var score = fuzzy * Math.pow(vocabCoverage, 0.5) * Math.pow(uniqueRatio, 0.3)
        if (maxConsec >= 3) score *= 0.3
        if (vocabCoverage < 0.3) score *= 0.5
        return Math.round(score * 10.0) / 10.0  // 1 decimal place gibi
    }

    // ============================================================
    // Preferred range — Python compute_preferred_range
    // ============================================================
    fun computePreferredRange(state: SessionState): IntRange? {
        if (state.lostChunks >= ABANDON_LOCK_AFTER_LOST) return null

        // BEKLEME + pending varsa pending civari
        if (state.state == NamazState.BEKLEME && state.pendingMatch != null) {
            val pm = state.pendingMatch!!
            return ayahWindow(pm.surah, pm.ayah,
                back = PENDING_VERIFY_AYAH_WINDOW,
                forward = PENDING_VERIFY_AYAH_WINDOW)
        }

        if (state.state == NamazState.FATIHA) {
            // Pencere Fatiha'nin son kelimesinde biter (FATIHA_WORD_RANGE 30'a kadar Bakara 2:1-2'yi de
            // kapsiyordu; daralan pencerede cop eslesme 2:1'e kilitleniyordu)
            val fEnd = ayahToCorpusRange[Pair(1, 7)]?.second ?: FATIHA_WORD_RANGE.last
            var start = FATIHA_WORD_RANGE.first
            val lw = state.lastWordIndex
            if (lw != null && lw >= start && lw <= fEnd) start = max(start, lw - FATIHA_BACK_WORDS)
            return start..fEnd
        }

        if (state.state == NamazState.ZAMM) {
            if (state.lastWordIndex == null) return null
            val ls = state.lastSurah
            val la = state.lastAyah
            if (ls != null && la != null) {
                val adaptive = min(
                    PREFERRED_AYAH_WINDOW_BASE + state.lostChunks,
                    PREFERRED_AYAH_WINDOW_MAX,
                )
                val w = ayahWindow(ls, la, back = 0, forward = adaptive)
                if (w != null) return w
            }
            // fallback: lastWordIndex etrafinda
            return state.lastWordIndex!!..(state.lastWordIndex!! + 60)
        }

        if (state.state == NamazState.ARA) {
            val ls = state.lastSurah
            val la = state.lastAyah
            if (ls != null && la != null) {
                val w = ayahWindow(ls, la, back = 2, forward = PREFERRED_AYAH_WINDOW_ARA)
                if (w != null) return w
            }
            if (state.lastWordIndex != null) {
                val li = state.lastWordIndex!!
                return max(0, li - 30)..(li + 90)
            }
            return null
        }

        return null
    }

    // ============================================================
    // Transition — Python transition_state
    // ============================================================
    private fun applyTransition(
        state: SessionState,
        matched: Boolean,
        firstSurah: Int?,
        firstAyah: Int?,
    ) {
        val current = state.state
        val newState: NamazState = when {
            matched -> when {
                // Fatiha'nin herhangi bir ayeti (2. rekat Fatiha'si ortasindan da yakalanabilir: 1:4) → FATIHA.
                // Eskiden sadece 1:1-3; 1:4'ten yakalaninca ZAMM kaliyor, Fatiha → zamm gecisi aday'a dusuyordu.
                firstSurah == 1 -> NamazState.FATIHA
                current == NamazState.FATIHA -> if (firstSurah == 1) NamazState.FATIHA else NamazState.ZAMM
                current == NamazState.ZAMM ||
                        current == NamazState.ARA ||
                        current == NamazState.BEKLEME -> NamazState.ZAMM
                else -> current
            }
            else -> when {
                (current == NamazState.FATIHA || current == NamazState.ZAMM) &&
                        state.lostChunks >= ARA_AFTER_LOST_CHUNKS -> NamazState.ARA
                else -> current
            }
        }
        if (newState != current) {
            state.stateTransitions.add("${current.name} → ${newState.name}")
            state.state = newState
        }
    }

    // ============================================================
    // Helpers
    // ============================================================
    /** Fatiha'nin tum kelimeleri (1:1-1:7). */
    private val fatihaRange: IntRange by lazy {
        ayahToCorpusRange[Pair(1, 1)]!!.first..ayahToCorpusRange[Pair(1, 7)]!!.second
    }

    /** Kamet / namaz sonu: onceki kilit ve adaylar silinir, BEKLEME + Fatiha beklemesi. */
    private fun resetForNewNamaz(state: SessionState, chunkIndex: Int, holdChunks: Int) {
        if (state.state != NamazState.BEKLEME) {
            state.stateTransitions.add("${state.state.name} → ${NamazState.BEKLEME.name}")
        }
        state.state = NamazState.BEKLEME
        state.lastWordIndex = null
        state.lastSurah = null
        state.lastAyah = null
        state.maxAyah = null
        state.lostChunks = 0
        state.pendingMatch = null
        state.jumpCandidate = null
        state.holdUntil = chunkIndex + holdChunks
    }

    private fun cleanupPendingIfStale(state: SessionState, chunkIndex: Int) {
        // Aday BEKLEME'de ve kilit kaybolduktan sonraki yeniden kilitte olusur; 2 chunk icinde dogrulanmazsa biter
        if (state.pendingMatch != null) {
            if (chunkIndex - state.pendingMatch!!.chunkIndex >= 2) {
                state.pendingMatch = null
            }
        }
        val jc = state.jumpCandidate
        if (jc != null && chunkIndex - jc.chunkIndex >= 2) state.jumpCandidate = null
    }

    /**
     * Kilitliyken dogal gecis noktasi mi (dogrulama beklemeden gecilir):
     * Fatiha sonu → baska herhangi bir yer (zamm suresi), sure sonu → bir surenin 1-2. ayeti.
     */
    private fun isNaturalTransition(state: SessionState, surah: Int, ayah: Int): Boolean {
        val far = state.maxAyah ?: state.lastAyah ?: 0
        val ls = state.lastSurah
        return when (state.state) {
            NamazState.FATIHA -> surah != 1 && ls == 1 && far >= FATIHA_END_AYAH
            NamazState.ZAMM, NamazState.ARA -> ls != null && far > 0 && ayah <= 2 && isNearSurahEnd(ls, far)
            else -> false
        }
    }

    /** Kilitli surede dogal gecis noktasinda miyiz: Fatiha sonu ya da zamm suresinin son ayetleri. */
    private fun atTransitionPoint(state: SessionState): Boolean {
        val far = state.maxAyah ?: state.lastAyah ?: 0
        val ls = state.lastSurah
        return when (state.state) {
            NamazState.FATIHA -> ls == 1 && far >= FATIHA_END_AYAH
            NamazState.ZAMM -> ls != null && far > 0 && isNearSurahEnd(ls, far)
            else -> false
        }
    }

    /**
     * Eslesme bir surenin acilisindan mi basliyor: besmele ya da 1. ayetin besmele disi ilk
     * OPENING_START_SLACK+1 kelimesi.
     */
    private fun isOpeningMatch(m: AlignmentMatch): Boolean {
        val (surah, ayah) = collectVerses(m.startWordIdx, m.startWordIdx).first()
        if (ayah != 1) return false
        val (st, en) = ayahToCorpusRange[Pair(surah, 1)] ?: return false
        var first = st
        while (first < en && first in besmelePositions) first++
        return m.startWordIdx in st..(first + OPENING_START_SLACK)
    }

    /** Eslesme bir ayetin ilk kelimesinden mi basliyor (1. ayetlerde besmele ve huruf-u mukattaa disi ilk kelime). */
    private fun startsAyah(m: AlignmentMatch): Boolean {
        val (surah, ayah) = collectVerses(m.startWordIdx, m.startWordIdx).first()
        val (st, en) = ayahToCorpusRange[Pair(surah, ayah)] ?: return false
        var first = st
        if (ayah == 1) while (first < en && first in besmelePositions) first++
        if (m.startWordIdx == first) return true
        return ayah == 1 && m.startWordIdx == first + 1 && index.getNormalized(first) in MUQATTAAT
    }

    /**
     * Hatim devam penceresi: son zamm ayeti .. +CONTINUE_AHEAD ayet; sure biterse sonraki surenin basina tasar
     * (sentetik hatim: Ahkaf sonundan Muhammed 47:1'e gecis 4:167'ye kilitlendi — ayni metin).
     */
    private fun continueWindow(surah: Int, ayah: Int): IntRange? {
        val total = surahAyahCounts[surah] ?: return null
        val start = ayahToCorpusRange[Pair(surah, ayah)]?.first ?: return null
        val endAyah = ayah + CONTINUE_AHEAD
        if (endAyah <= total) return ayahToCorpusRange[Pair(surah, endAyah)]?.let { start..it.second }
        val next = surahAyahCounts[surah + 1]
        if (next != null) return ayahToCorpusRange[Pair(surah + 1, min(next, endAyah - total))]?.let { start..it.second }
        return ayahToCorpusRange[Pair(surah, total)]?.let { start..it.second }
    }

    /**
     * Gecis eslesmesi baska bir surenin acilisina da ayni ham skorla oturuyor mu (bkz. OPENING_TIE_MARGIN) →
     * ikinci yer ("114:1 100.0") ya da null.
     */
    private fun openingTie(cleanText: String, m: AlignmentMatch): String? {
        val ru = runnerUpMatch(cleanText, m) ?: return null
        val (rs, ra) = collectVerses(ru.startWordIdx, ru.startWordIdx).first()
        val (ms, _) = collectVerses(m.startWordIdx, m.startWordIdx).first()
        return if (rs != ms && isOpeningMatch(ru) && ru.score >= m.score - OPENING_TIE_MARGIN) {
            "$rs:$ra ${"%.1f".format(ru.score)}"
        } else {
            null
        }
    }

    /** Son saglam eslesmeden sonra tekbir duyuldu mu (namazda rukû / secde) — bkz. TILAVET_END. */
    private fun tekbirAfterReading(state: SessionState): Boolean {
        val t = state.lastTekbirChunk ?: return false
        val s = state.lastSolidChunk ?: return false
        return t > s
    }

    /** Sure no → acilisin (1. ayet, besmele disi) ilk kelimesinin ilk parcasi (bare) — Python opening_first_tokens. */
    private val openingFirstTokens: Map<Int, String> by lazy {
        val out = LinkedHashMap<Int, String>()
        for (s in 1..114) {
            val (st, en) = ayahToCorpusRange[Pair(s, 1)] ?: continue
            var p = st
            while (p < en && p in besmelePositions) p++
            out[s] = bareToken(index.getNormalized(p).split(' ').first())
        }
        out
    }

    /** Surenin acilis penceresi (1-2. ayet). */
    private fun openingWindow(surah: Int): IntRange? {
        val total = surahAyahCounts[surah] ?: return null
        val st = ayahToCorpusRange[Pair(surah, 1)]?.first ?: return null
        val en = ayahToCorpusRange[Pair(surah, min(2, total))]?.second ?: return null
        return st..en
    }

    /**
     * Fatiha sonu: ilk kelimesi parcanin ilk 2 kelimesinden biri olan surelerin acilisinda (1-2. ayet) en iyi eslesme
     * → (eslesme, skor) ya da null — bkz. OPENING_PREFER_MARGIN (Python opening_preference ile birebir).
     */
    private fun openingPreference(cleanText: String, tokens: List<String>): Pair<AlignmentMatch, Double>? {
        val toks = cleanText.trim().split(Regex("\\s+")).map { bareToken(it) }.filter { it.isNotEmpty() }.take(2)
        var best: Pair<AlignmentMatch, Double>? = null
        for ((s, fw) in openingFirstTokens) {
            if (s == 1 || fw !in toks) continue
            val ow = openingWindow(s) ?: continue
            val m = aligner.align(cleanText, preferredRange = ow) ?: continue
            if (m.score < OPENING_MIN_FUZZY || !isOpeningMatch(m)) continue
            val sc = scoreTranscription(tokens, m)
            if (best == null || sc > best.second) best = Pair(m, sc)
        }
        return best
    }

    /**
     * Zamm'da son saglam eslesmeden FATIHA_MIN_GAP_CHUNKS parca gecmeden Fatiha'nin 1-2. ayetinde biten eslesme ve onceki
     * parcalarda Fatiha gecis adayi yok → erken (gecis adayi olur).
     */
    private fun earlyFatiha(state: SessionState, chunkIndex: Int, fatihaAyah: Int): Boolean {
        if (state.state != NamazState.ZAMM || fatihaAyah > FATIHA_EARLY_MAX_AYAH) return false
        val solid = state.lastSolidChunk ?: return false
        if (chunkIndex - solid >= FATIHA_MIN_GAP_CHUNKS) return false
        val jc = state.jumpCandidate
        return !(jc != null && jc.surah == 1 && chunkIndex - jc.chunkIndex <= 2)
    }

    /** Eslesmedeki besmele-disi kelime sayisi. */
    private fun contentWordCount(m: AlignmentMatch): Int {
        var n = 0
        for (p in m.startWordIdx..m.endWordIdx) if (p !in besmelePositions) n++
        return n
    }

    private fun verifyPending(pending: PendingMatch, newSurah: Int, newAyah: Int): Boolean {
        if (newSurah != pending.surah) return false
        return abs(newAyah - pending.ayah) <= PENDING_VERIFY_AYAH_WINDOW
    }

    private fun isNearSurahEnd(surah: Int, ayah: Int): Boolean {
        val total = surahAyahCounts[surah] ?: return false
        return (total - ayah) < SURAH_END_THRESHOLD
    }

    /**
     * Bir sure'nin (back..forward) ayet penceresini corpus index aralığına çevir.
     */
    private fun ayahWindow(surah: Int, ayah: Int, back: Int, forward: Int): IntRange? {
        val total = surahAyahCounts[surah] ?: return null
        val startAyah = max(1, ayah - back)
        val endAyah = min(total, ayah + forward)
        val startRange = ayahToCorpusRange[Pair(surah, startAyah)] ?: return null
        val endRange = ayahToCorpusRange[Pair(surah, endAyah)] ?: return null
        return startRange.first..endRange.second
    }

    /**
     * Match aralığındaki uniq (surah, ayah) ciftlerini cikar.
     */
    private fun collectVerses(startIdx: Int, endIdx: Int): List<Pair<Int, Int>> {
        val seen = HashSet<Pair<Int, Int>>()
        val verses = mutableListOf<Pair<Int, Int>>()
        for (i in startIdx..endIdx) {
            val w = index.getWord(i)
            val key = Pair(w.surah, w.ayah)
            if (key !in seen) {
                seen.add(key)
                verses.add(key)
            }
        }
        return verses
    }

    /**
     * Eger yeni match ile son match arasinda ufak bir bosluk varsa (ayni sure,
     * en cok MAX_GAP_FILL ayet), arada kalan ayetleri "boslugu doldur" olarak ekle.
     */
    private fun computeGapFill(state: SessionState, firstSurah: Int, firstAyah: Int): Int {
        val ls = state.lastSurah ?: return 0
        val la = state.lastAyah ?: return 0
        if (firstSurah != ls) return 0
        val gap = firstAyah - la - 1
        return if (gap in 1..MAX_GAP_FILL) gap else 0
    }
}
