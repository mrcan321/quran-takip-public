package com.tilavet.takip.ui.components

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.data.MushafData
import com.tilavet.takip.ui.theme.AppPalette
import com.tilavet.takip.ui.theme.AppStyle
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import com.tilavet.takip.ui.theme.QURAN_FONT_SCALE
import com.tilavet.takip.ui.theme.QuranFontFamily

/**
 * Tum Kuran — Tarteel benzeri kesintisiz liste: sure basligi + ayetler (Arapca, ayet sonu isareti, meal).
 * Okunan ayet arka planla, eslesen kelimeler vurguyla gosterilir. Kaydirma/takip MainScreen'de.
 *
 * Zumrut temasi (ornate): sure basligi ustu kemerli beyaz kart (altin hat, amblem, soluk yildiz deseni, ayrac),
 * okunan ayet yesil isiltili yari saydam "HUD" karti (Arapca ustte, meal altta), diger ayetler arasinda ince altin
 * cizgi, ayet etiketi nane yesili hap. Klasik temalar eskisi gibi.
 *
 * Yazi boyutlari Float: Ayarlar → EKRANA SIĞDIR acikken okunan ayet sigmazsa iki boyut ayni oranda kuculur
 * ([rememberFitScale]); [showArabic] / [showMeal] Ayarlar → EKRANDA METİN (data/TextMode).
 */
@Composable
fun MushafList(
    mushaf: MushafData,
    listState: LazyListState,
    currentAyah: Int?,
    tentative: Boolean,
    hlStart: Int,
    hlEnd: Int,
    arabicSizeSp: Float,
    mealSizeSp: Float,
    idleOpacity: Float,   // 0..1 — okunan ayet varken digerlerinin soluklugu
    motion: Float,        // 0..1
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
    showArabic: Boolean = true,
    showMeal: Boolean = true,
    // Yatayda false: liste elle kaydirilmaz (namazda ekrana dokunulmaz), sadece takip kaydirir
    userScrollEnabled: Boolean = true,
) {
    LazyColumn(
        state = listState,
        contentPadding = contentPadding,
        modifier = modifier.fillMaxSize(),
        userScrollEnabled = userScrollEnabled,
    ) {
        items(
            count = mushaf.itemCount,
            key = { mushaf.itemKey(it) },
            contentType = { if (mushaf.itemAt(it) < 0) 0 else 1 },
        ) { i ->
            val item = mushaf.itemAt(i)
            if (item < 0) {
                SurahHeader(mushaf = mushaf, surah = -item, arabicSizeSp = arabicSizeSp, showArabic = showArabic)
            } else {
                AyahItem(
                    mushaf = mushaf,
                    ayah = item,
                    isCurrent = item == currentAyah,
                    tentative = tentative,
                    dimmed = currentAyah != null && item != currentAyah,
                    hlStart = hlStart,
                    hlEnd = hlEnd,
                    arabicSizeSp = arabicSizeSp,
                    mealSizeSp = mealSizeSp,
                    idleOpacity = idleOpacity,
                    motion = motion,
                    showArabic = showArabic,
                    showMeal = showMeal,
                )
            }
        }
    }
}

// ============================================================
// Ayet satirinin yazi stilleri ve olculeri — liste ile EKRANA SIĞDIR hesabi ayni degerleri kullanir
// ============================================================

/** Arapca ayet metni (KFGQPC; zumrutte satir araligi 2.0, klasikte 1.9). */
private fun arabicTextStyle(sizeSp: Float, ornate: Boolean): TextStyle = TextStyle(
    fontFamily = QuranFontFamily,
    fontSize = (sizeSp * QURAN_FONT_SCALE).sp,
    lineHeight = (sizeSp * QURAN_FONT_SCALE * (if (ornate) 2.0f else 1.9f)).sp,
    textAlign = TextAlign.Start,
    textDirection = TextDirection.Rtl,
)

/** Meal: tema govde yazisi; [base] = LocalTextStyle (Material Text'in varsayilani — harf araligi vb. ondan gelir). */
private fun mealTextStyle(base: TextStyle, sizeSp: Float, style: AppStyle): TextStyle =
    if (style.ornate) {
        val sp = sizeSp * style.bodyScale
        base.merge(TextStyle(fontFamily = style.body, fontWeight = FontWeight.Normal, fontSize = sp.sp, lineHeight = (sp * 1.55f).sp))
    } else {
        base.merge(TextStyle(fontFamily = style.body, fontWeight = FontWeight.Medium, fontSize = sizeSp.sp, lineHeight = (sizeSp * 1.45f).sp))
    }

/** Ayet etiketi ("Bakara: 255") yazisi. */
private fun tagTextStyle(base: TextStyle, style: AppStyle): TextStyle =
    if (style.ornate) {
        base.merge(TextStyle(fontFamily = style.label, fontWeight = FontWeight.SemiBold, fontSize = 10.5.sp, letterSpacing = 0.5.sp))
    } else {
        base.merge(TextStyle(fontFamily = style.label, fontSize = 10.sp, letterSpacing = 0.6.sp))
    }

/** Zumrut ayet satiri: dis bosluk (yatay / dikey), kart ic boslugu (yatay / dikey), etiket hapi dikey boslugu. */
private val ORNATE_OUTER_H = 12.dp
private val ORNATE_OUTER_V = 6.dp
private val ORNATE_INNER_H = 12.dp
private val ORNATE_INNER_V = 14.dp
private val ORNATE_PILL_V = 3.dp
private val ORNATE_GAP_TAG = 10.dp     // etiket → ilk metin
private val ORNATE_GAP_MEAL = 8.dp     // Arapca → meal
/** Klasik ayet satiri: yatay / dikey bosluk, etiket kutusu dikey boslugu. */
private val CLASSIC_PAD_H = 20.dp
private val CLASSIC_PAD_V = 16.dp
private val CLASSIC_TAG_V = 2.dp
private val CLASSIC_GAP = 10.dp

/** EKRANA SIĞDIR: en kucuk olcek (bundan da sigmazsa bu olcekte kalir — pratikte 2:282 yatayda bile ustunde). */
const val FIT_MIN_SCALE = 0.15f

/** EKRANA SIĞDIR olcumunde guvenlik payi (yazi tipi yuvarlamalari, cizgi / golge). */
private val FIT_SAFETY = 6.dp

/**
 * Ayet metninin ekrandaki duz hali (vurgu yok; olcum icin): kelimeler + ayet sonu isareti — [AyahItem]'daki
 * AnnotatedString ile ayni karakterler (vurgu sadece renk / zemin, satir kirilmasini degistirmez).
 */
private fun ayahPlainText(words: List<String>, ayahNo: Int): String =
    buildString {
        for (w in words) {
            append(w)
            append(' ')
        }
        append(arabicDigits(ayahNo))
    }

/** Ayet satirinin olculmus hali: toplam yukseklik (px) — EKRANA SIĞDIR hesabi ve ayetin ekrandaki yeri icin. */
data class FitResult(val scale: Float, val itemHeightPx: Int)

/**
 * EKRANA SIĞDIR: okunan ayetin (etiket + Arapca + meal) [availableHeightPx]'e sigdigi en buyuk olcek (≤ 1). Arapca ve
 * meal puntosu AYNI oranda kuculur (kullanici 04.11: "Arapca 20, Turkce 30 secilmisse yariya dusurmen gerekiyorsa
 * 10 / 15"); sadece Arapca / sadece Turkce secildiyse o metin. Satir kirilmasi puntoyla dogrusal degismedigi icin
 * olcek ikili aramayla bulunur (her adimda gercek yazi olcumu, TextMeasurer). Sigiyorsa 1.
 *
 * @param widthPx liste genisligi (ayet satirinin tam genisligi)
 */
@Composable
fun rememberFitScale(
    mushaf: MushafData,
    ayah: Int?,
    widthPx: Int,
    availableHeightPx: Int,
    arabicSizeSp: Float,
    mealSizeSp: Float,
    showArabic: Boolean,
    showMeal: Boolean,
    enabled: Boolean,
): FitResult? {
    val style = LocalAppStyle.current
    val density = LocalDensity.current
    val base = LocalTextStyle.current
    val measurer = rememberTextMeasurer(cacheSize = 32)
    if (!enabled || ayah == null || widthPx <= 0 || availableHeightPx <= 0) return null
    return remember(mushaf, ayah, widthPx, availableHeightPx, arabicSizeSp, mealSizeSp, showArabic, showMeal, style, density, base) {
        val ornate = style.ornate
        val arabic = if (showArabic) ayahPlainText(mushaf.words(ayah), mushaf.ayahNumber(ayah)) else null
        val meal = if (showMeal) mushaf.meal(ayah)?.takeIf { it.isNotEmpty() } else null
        with(density) {
            val textW = (widthPx - (if (ornate) (ORNATE_OUTER_H + ORNATE_INNER_H) * 2 else CLASSIC_PAD_H * 2).roundToPx())
                .coerceAtLeast(1)
            val tagH = measurer.measure(AnnotatedString(mushaf.ayahTag(ayah)), tagTextStyle(base, style)).size.height
            // Olcekle degismeyen kisim: bosluklar + etiket satiri (+ Arapca → meal arasi)
            val both = arabic != null && meal != null
            val spacing = if (ornate) {
                ORNATE_OUTER_V * 2 + ORNATE_INNER_V * 2 + ORNATE_PILL_V * 2 + ORNATE_GAP_TAG +
                    (if (both) ORNATE_GAP_MEAL else 0.dp) + 1.dp
            } else {
                1.dp + CLASSIC_PAD_V * 2 + CLASSIC_TAG_V * 2 + CLASSIC_GAP + (if (both) CLASSIC_GAP else 0.dp)
            }
            val fixed = (spacing + FIT_SAFETY).roundToPx() + tagH
            val constraints = Constraints(maxWidth = textW)
            fun heightAt(s: Float): Int {
                var h = fixed
                if (arabic != null) h += measurer.measure(AnnotatedString(arabic), arabicTextStyle(arabicSizeSp * s, ornate),
                    constraints = constraints).size.height
                if (meal != null) h += measurer.measure(AnnotatedString(meal), mealTextStyle(base, mealSizeSp * s, style),
                    constraints = constraints).size.height
                return h
            }
            val full = heightAt(1f)
            if (full <= availableHeightPx) return@remember FitResult(1f, full)
            var lo = FIT_MIN_SCALE
            var hi = 1f
            repeat(14) {
                val mid = (lo + hi) / 2f
                if (heightAt(mid) <= availableHeightPx) lo = mid else hi = mid
            }
            FitResult(lo, heightAt(lo))
        }
    }
}

@Composable
private fun SurahHeader(mushaf: MushafData, surah: Int, arabicSizeSp: Float, showArabic: Boolean) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val info = remember(mushaf, surah) { mushaf.surahInfo(surah) }
    val ayahCount = remember(mushaf, surah) { mushaf.surahAyahCount(surah) }

    if (style.ornate) {
        OrnateSurahHeader(mushaf, surah, info?.nameTr ?: "Sure $surah", info?.nameAr, ayahCount, arabicSizeSp, showArabic, palette, style)
        return
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp)
            .padding(top = 28.dp, bottom = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .background(palette.bgElev, RoundedCornerShape(10.dp))
                .border(1.dp, palette.borderStrong, RoundedCornerShape(10.dp))
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    text = (info?.nameTr ?: "Sure $surah"),
                    fontFamily = style.display,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = 22.sp,
                    color = palette.fg,
                )
                Text(
                    text = "$surah. SURE · $ayahCount AYET",
                    fontFamily = style.label,
                    fontSize = 10.sp,
                    color = palette.fgDim,
                    letterSpacing = 0.8.sp,
                )
            }
            if (!info?.nameAr.isNullOrEmpty()) {
                Text(
                    text = MushafData.displayText(info!!.nameAr),
                    fontFamily = QuranFontFamily,
                    fontSize = (22 * QURAN_FONT_SCALE).sp,
                    color = palette.accent,
                    style = TextStyle(textDirection = TextDirection.Rtl),
                )
            }
        }

        // Besmele: Fatiha'da 1. ayetin kendisi, Tevbe'de yok; EKRANDA METİN: TÜRKÇE iken gizli
        if (showArabic && surah != 1 && surah != 9 && mushaf.besmele.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            Text(
                text = mushaf.besmele,
                color = palette.fg,
                modifier = Modifier.fillMaxWidth(),
                style = arabicTextStyle(arabicSizeSp, ornate = false).copy(textAlign = TextAlign.Center),
            )
        }
    }
}

/** Zumrut: ustu kemerli beyaz kart — amblem, "55. SURE · 78 AYET", buyuk serif sure adi, Arapca ad, altin ayrac. */
@Composable
private fun OrnateSurahHeader(
    mushaf: MushafData,
    surah: Int,
    nameTr: String,
    nameAr: String?,
    ayahCount: Int,
    arabicSizeSp: Float,
    showArabic: Boolean,
    palette: AppPalette,
    style: AppStyle,
) {
    val shape = remember { ArchTopShape(rise = 24.dp, corner = 20.dp) }
    // Kartin ust kisminda (kemer altinda) asagi dogru kaybolan cok soluk 8 koseli yildiz deseni
    val pattern = Modifier.drawWithCache {
        val p = starPatternPath(size.width, size.height, 11.dp.toPx())
        val brush = Brush.verticalGradient(
            listOf(style.gold.copy(alpha = 0.16f), style.gold.copy(alpha = 0f)), startY = 0f, endY = size.height * 0.55f,
        )
        val clip = (shape.createOutline(size, layoutDirection, this) as Outline.Generic).path
        val stroke = Stroke(0.7.dp.toPx())
        onDrawBehind {
            clipPath(clip) { drawPath(p, brush, style = stroke) }
        }
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(top = 30.dp, bottom = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .shadow(10.dp, shape, ambientColor = style.shadow, spotColor = style.shadow.copy(alpha = 0.35f))
                .background(palette.bgElev, shape)
                .then(pattern)
                .border(1.dp, style.gold.copy(alpha = 0.55f), shape)
                .padding(start = 20.dp, end = 20.dp, top = 12.dp, bottom = 18.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            ArchEmblem(style.gold, Modifier.size(20.dp, 26.dp), fill = palette.accent)
            Spacer(Modifier.height(10.dp))
            Text(
                text = "$surah. SURE  ·  $ayahCount AYET",
                fontFamily = style.label,
                fontWeight = FontWeight.SemiBold,
                fontSize = 10.sp,
                letterSpacing = 2.2.sp,
                color = style.goldInk,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = nameTr,
                fontFamily = style.display,
                fontWeight = FontWeight.Bold,
                fontSize = 30.sp,
                lineHeight = 36.sp,
                color = style.headerTop,
                textAlign = TextAlign.Center,
            )
            if (!nameAr.isNullOrEmpty()) {
                Text(
                    text = MushafData.displayText(nameAr),
                    fontFamily = QuranFontFamily,
                    fontSize = (22 * QURAN_FONT_SCALE).sp,
                    color = style.goldInk,
                    style = TextStyle(textDirection = TextDirection.Rtl),
                )
            }
            Spacer(Modifier.height(8.dp))
            OrnamentDivider(style.gold, width = 170.dp)
        }

        // Besmele: Fatiha'da 1. ayetin kendisi, Tevbe'de yok; EKRANDA METİN: TÜRKÇE iken gizli
        if (showArabic && surah != 1 && surah != 9 && mushaf.besmele.isNotEmpty()) {
            Spacer(Modifier.height(18.dp))
            Text(
                text = mushaf.besmele,
                color = style.headerTop,
                modifier = Modifier.fillMaxWidth(),
                // besmele satir araligi eskisi gibi 1.9 (ayet metninde zumrut 2.0)
                style = arabicTextStyle(arabicSizeSp, ornate = false).copy(textAlign = TextAlign.Center),
            )
        }
    }
}

@Composable
private fun AyahItem(
    mushaf: MushafData,
    ayah: Int,
    isCurrent: Boolean,
    tentative: Boolean,
    dimmed: Boolean,
    hlStart: Int,
    hlEnd: Int,
    arabicSizeSp: Float,
    mealSizeSp: Float,
    idleOpacity: Float,
    motion: Float,
    showArabic: Boolean,
    showMeal: Boolean,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val words = remember(mushaf, ayah) { mushaf.words(ayah) }
    val meal = remember(mushaf, ayah) { mushaf.meal(ayah) }
    val ayahNo = mushaf.ayahNumber(ayah)
    val firstWord = mushaf.firstShownWord(ayah)
    val anim = (600 / motion.coerceAtLeast(0.001f)).toInt()

    val alpha by animateFloatAsState(
        targetValue = if (dimmed) (1f - idleOpacity).coerceIn(0.2f, 1f) else 1f,
        animationSpec = tween(anim),
        label = "ayahAlpha",
    )

    // Eslesen kelimeler (bu ayete dusenler) — kilitliyken accent, adayken daha soluk
    val hlBg = if (tentative) palette.accentDim.copy(alpha = palette.accentDim.alpha * 0.6f) else palette.accentDim
    val hlFg = if (tentative) palette.fg else palette.accent
    // Ayet sonu isareti: klasikte vurgu rengi, zumrutte altin
    val markColor = if (style.ornate) style.goldInk else palette.accent
    // Vurgulu kelimeler tek parca bant: aradaki bosluk da vurgulanir (eskiden her kelime ayri kutu → "kelimeler
    // ayri ayri" gorunuyordu). Karakterler ayahPlainText ile ayni (EKRANA SIĞDIR olcumu).
    val annotated: AnnotatedString = remember(words, hlStart, hlEnd, tentative, palette, firstWord, ayahNo, markColor) {
        fun hl(pos: Int) = hlStart >= 0 && pos in hlStart..hlEnd
        buildAnnotatedString {
            words.forEachIndexed { k, w ->
                val pos = firstWord + k
                if (hl(pos)) {
                    withStyle(SpanStyle(color = hlFg, background = hlBg)) {
                        append(w)
                        if (k + 1 < words.size && hl(pos + 1)) append(' ')
                    }
                    if (!(k + 1 < words.size && hl(pos + 1))) append(' ')
                } else {
                    withStyle(SpanStyle(color = palette.fg)) { append(w) }
                    append(' ')
                }
            }
            // Ayet sonu: KFGQPC fontu Arapca rakamlari sus cerceveli ayet isareti olarak ciziyor (Tarteel'deki gibi)
            withStyle(SpanStyle(color = markColor)) { append(arabicDigits(ayahNo)) }
        }
    }
    val shownMeal = if (showMeal) meal?.takeIf { it.isNotEmpty() } else null

    if (style.ornate) {
        OrnateAyahItem(
            tag = mushaf.ayahTag(ayah), annotated = if (showArabic) annotated else null, meal = shownMeal,
            isCurrent = isCurrent, tentative = tentative, alpha = alpha, anim = anim,
            arabicSizeSp = arabicSizeSp, mealSizeSp = mealSizeSp, palette = palette, style = style,
        )
        return
    }

    val rowBg by animateColorAsState(
        targetValue = if (isCurrent) palette.bgElev else Color.Transparent,
        animationSpec = tween(anim),
        label = "ayahBg",
    )
    val labelColor = if (isCurrent) palette.accent else palette.fgFaded
    val base = LocalTextStyle.current

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBg)
            .alpha(alpha),
    ) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(palette.border))
        Column(Modifier.padding(horizontal = CLASSIC_PAD_H, vertical = CLASSIC_PAD_V)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .border(1.dp, labelColor, RoundedCornerShape(3.dp))
                        .padding(horizontal = 7.dp, vertical = CLASSIC_TAG_V)
                ) {
                    Text(
                        text = mushaf.ayahTag(ayah),   // "İbrâhîm: 2"
                        color = labelColor,
                        style = tagTextStyle(base, style),
                    )
                }
                if (isCurrent && tentative) {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = "ADAY",
                        fontFamily = style.label,
                        fontSize = 9.sp,
                        color = palette.fgDim,
                        letterSpacing = 1.0.sp,
                    )
                }
            }

            if (showArabic) {
                Spacer(Modifier.height(CLASSIC_GAP))
                Text(
                    text = annotated,
                    style = arabicTextStyle(arabicSizeSp, ornate = false),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            if (shownMeal != null) {
                Spacer(Modifier.height(CLASSIC_GAP))
                Text(
                    text = shownMeal,
                    color = if (isCurrent) palette.fg else palette.fgDim,
                    style = mealTextStyle(base, mealSizeSp, style),
                )
            }
        }
    }
}

/**
 * Zumrut ayet satiri. Tum satirlar ayni yerlesimde (ic/dis bosluk sabit) — okunan ayet olunca sadece kart belirir,
 * metin yerinden oynamaz. Kart marka metnindeki "yari saydam yesil HUD": fildisi → cok acik yesil zemin, yumusak
 * yesil isilti (golge), ince orman yesili cerceve; Arapca ustte, meal altta. [annotated] / [meal] null: EKRANDA METİN.
 */
@Composable
private fun OrnateAyahItem(
    tag: String,
    annotated: AnnotatedString?,
    meal: String?,
    isCurrent: Boolean,
    tentative: Boolean,
    alpha: Float,
    anim: Int,
    arabicSizeSp: Float,
    mealSizeSp: Float,
    palette: AppPalette,
    style: AppStyle,
) {
    val card by animateFloatAsState(
        targetValue = if (isCurrent) 1f else 0f,
        animationSpec = tween(anim),
        label = "ayahCard",
    )
    val shape = RoundedCornerShape(22.dp)
    val base = LocalTextStyle.current
    val hudBrush = remember(card, palette, style) {
        Brush.verticalGradient(listOf(palette.bgElev.copy(alpha = 0.97f * card), style.hudTint.copy(alpha = 0.95f * card)))
    }

    Column(modifier = Modifier.fillMaxWidth().alpha(alpha)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = ORNATE_OUTER_H, vertical = ORNATE_OUTER_V)
                .then(
                    if (card > 0.01f) Modifier
                        .shadow(
                            (18 * card).dp, shape,
                            ambientColor = style.hudGlow, spotColor = style.hudGlow.copy(alpha = 0.7f * card),
                        )
                        .background(hudBrush, shape)
                        .border(1.dp, style.hudGlow.copy(alpha = 0.30f * card), shape)
                    else Modifier
                )
                .padding(horizontal = ORNATE_INNER_H, vertical = ORNATE_INNER_V),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                // Ayet etiketi: nane yesili hap (zeytin yazi); okunan ayette dolu orman yesili
                val pillBg = if (isCurrent && !tentative) palette.accent else style.mint
                val pillFg = when {
                    isCurrent && !tentative -> style.onHeader
                    isCurrent -> palette.accent
                    else -> style.olive
                }
                Box(
                    modifier = Modifier
                        .background(pillBg, RoundedCornerShape(50))
                        .padding(horizontal = 11.dp, vertical = ORNATE_PILL_V)
                ) {
                    Text(
                        text = tag,   // "İbrâhîm: 2"
                        color = pillFg,
                        style = tagTextStyle(base, style),
                    )
                }
                if (isCurrent && tentative) {
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = "ADAY",
                        fontFamily = style.label,
                        fontWeight = FontWeight.Bold,
                        fontSize = 9.sp,
                        color = style.goldInk,
                        letterSpacing = 1.8.sp,
                    )
                }
            }

            Spacer(Modifier.height(ORNATE_GAP_TAG))

            // Arapca: genis satir araligi (ferah, saygili)
            if (annotated != null) {
                Text(
                    text = annotated,
                    style = arabicTextStyle(arabicSizeSp, ornate = true),
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            if (meal != null) {
                if (annotated != null) Spacer(Modifier.height(ORNATE_GAP_MEAL))
                Text(
                    text = meal,
                    color = if (isCurrent) palette.fg else palette.fgDim,
                    style = mealTextStyle(base, mealSizeSp, style),
                )
            }
        }
        // Ayetler arasi ince altin cizgi (iki yana solar); okunan ayet kartinin altinda gizlenir
        Box(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 36.dp)
                .height(1.dp)
                .alpha(1f - card)
                .background(
                    Brush.horizontalGradient(
                        listOf(style.gold.copy(alpha = 0f), style.gold.copy(alpha = 0.38f), style.gold.copy(alpha = 0f))
                    )
                )
        )
    }
}

private fun arabicDigits(n: Int): String {
    val s = n.toString()
    val sb = StringBuilder(s.length)
    for (c in s) sb.append('٠' + (c - '0'))
    return sb.toString()
}
