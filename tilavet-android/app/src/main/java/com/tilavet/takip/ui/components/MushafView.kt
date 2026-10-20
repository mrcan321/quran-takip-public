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
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.withStyle
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
 */
@Composable
fun MushafList(
    mushaf: MushafData,
    listState: LazyListState,
    currentAyah: Int?,
    tentative: Boolean,
    hlStart: Int,
    hlEnd: Int,
    arabicSizeSp: Int,
    mealSizeSp: Int,
    idleOpacity: Float,   // 0..1 — okunan ayet varken digerlerinin soluklugu
    motion: Float,        // 0..1
    contentPadding: PaddingValues,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        state = listState,
        contentPadding = contentPadding,
        modifier = modifier.fillMaxSize(),
    ) {
        items(
            count = mushaf.itemCount,
            key = { mushaf.itemKey(it) },
            contentType = { if (mushaf.itemAt(it) < 0) 0 else 1 },
        ) { i ->
            val item = mushaf.itemAt(i)
            if (item < 0) {
                SurahHeader(mushaf = mushaf, surah = -item, arabicSizeSp = arabicSizeSp)
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
                )
            }
        }
    }
}

@Composable
private fun SurahHeader(mushaf: MushafData, surah: Int, arabicSizeSp: Int) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val info = remember(mushaf, surah) { mushaf.surahInfo(surah) }
    val ayahCount = remember(mushaf, surah) { mushaf.surahAyahCount(surah) }

    if (style.ornate) {
        OrnateSurahHeader(mushaf, surah, info?.nameTr ?: "Sure $surah", info?.nameAr, ayahCount, arabicSizeSp, palette, style)
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
                    style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
                )
            }
        }

        // Besmele: Fatiha'da 1. ayetin kendisi, Tevbe'de yok
        if (surah != 1 && surah != 9 && mushaf.besmele.isNotEmpty()) {
            Spacer(Modifier.height(16.dp))
            Text(
                text = mushaf.besmele,
                fontFamily = QuranFontFamily,
                fontSize = (arabicSizeSp * QURAN_FONT_SCALE).sp,
                lineHeight = (arabicSizeSp * QURAN_FONT_SCALE * 1.9).sp,
                color = palette.fg,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
                style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
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
    arabicSizeSp: Int,
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
                    style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
                )
            }
            Spacer(Modifier.height(8.dp))
            OrnamentDivider(style.gold, width = 170.dp)
        }

        // Besmele: Fatiha'da 1. ayetin kendisi, Tevbe'de yok
        if (surah != 1 && surah != 9 && mushaf.besmele.isNotEmpty()) {
            Spacer(Modifier.height(18.dp))
            Text(
                text = mushaf.besmele,
                fontFamily = QuranFontFamily,
                fontSize = (arabicSizeSp * QURAN_FONT_SCALE).sp,
                lineHeight = (arabicSizeSp * QURAN_FONT_SCALE * 1.9).sp,
                color = style.headerTop,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
                style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
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
    arabicSizeSp: Int,
    mealSizeSp: Int,
    idleOpacity: Float,
    motion: Float,
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
    // ayri ayri" gorunuyordu)
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

    if (style.ornate) {
        OrnateAyahItem(
            tag = mushaf.ayahTag(ayah), annotated = annotated, meal = meal,
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

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(rowBg)
            .alpha(alpha),
    ) {
        Box(Modifier.fillMaxWidth().height(1.dp).background(palette.border))
        Column(Modifier.padding(horizontal = 20.dp, vertical = 16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .border(1.dp, labelColor, RoundedCornerShape(3.dp))
                        .padding(horizontal = 7.dp, vertical = 2.dp)
                ) {
                    Text(
                        text = mushaf.ayahTag(ayah),   // "İbrâhîm: 2"
                        fontFamily = style.label,
                        fontSize = 10.sp,
                        color = labelColor,
                        letterSpacing = 0.6.sp,
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

            Spacer(Modifier.height(10.dp))

            Text(
                text = annotated,
                fontFamily = QuranFontFamily,
                fontSize = (arabicSizeSp * QURAN_FONT_SCALE).sp,
                lineHeight = (arabicSizeSp * QURAN_FONT_SCALE * 1.9).sp,
                textAlign = TextAlign.Start,
                style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
                modifier = Modifier.fillMaxWidth(),
            )

            if (!meal.isNullOrEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text(
                    text = meal,
                    fontFamily = style.body,
                    fontSize = mealSizeSp.sp,
                    lineHeight = (mealSizeSp * 1.45).sp,
                    fontWeight = FontWeight.Medium,
                    color = if (isCurrent) palette.fg else palette.fgDim,
                )
            }
        }
    }
}

/**
 * Zumrut ayet satiri. Tum satirlar ayni yerlesimde (ic/dis bosluk sabit) — okunan ayet olunca sadece kart belirir,
 * metin yerinden oynamaz. Kart marka metnindeki "yari saydam yesil HUD": fildisi → cok acik yesil zemin, yumusak
 * yesil isilti (golge), ince orman yesili cerceve; Arapca ustte, meal altta.
 */
@Composable
private fun OrnateAyahItem(
    tag: String,
    annotated: AnnotatedString,
    meal: String?,
    isCurrent: Boolean,
    tentative: Boolean,
    alpha: Float,
    anim: Int,
    arabicSizeSp: Int,
    mealSizeSp: Int,
    palette: AppPalette,
    style: AppStyle,
) {
    val card by animateFloatAsState(
        targetValue = if (isCurrent) 1f else 0f,
        animationSpec = tween(anim),
        label = "ayahCard",
    )
    val shape = RoundedCornerShape(22.dp)
    val mealSp = mealSizeSp * style.bodyScale
    val hudBrush = remember(card, palette, style) {
        Brush.verticalGradient(listOf(palette.bgElev.copy(alpha = 0.97f * card), style.hudTint.copy(alpha = 0.95f * card)))
    }

    Column(modifier = Modifier.fillMaxWidth().alpha(alpha)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 6.dp)
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
                .padding(horizontal = 12.dp, vertical = 14.dp),
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
                        .padding(horizontal = 11.dp, vertical = 3.dp)
                ) {
                    Text(
                        text = tag,   // "14-İbrâhîm:2"
                        fontFamily = style.label,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 10.5.sp,
                        color = pillFg,
                        letterSpacing = 0.5.sp,
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

            Spacer(Modifier.height(10.dp))

            // Arapca: genis satir araligi (ferah, saygili)
            Text(
                text = annotated,
                fontFamily = QuranFontFamily,
                fontSize = (arabicSizeSp * QURAN_FONT_SCALE).sp,
                lineHeight = (arabicSizeSp * QURAN_FONT_SCALE * 2.0).sp,
                textAlign = TextAlign.Start,
                style = androidx.compose.ui.text.TextStyle(textDirection = TextDirection.Rtl),
                modifier = Modifier.fillMaxWidth(),
            )

            if (!meal.isNullOrEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text(
                    text = meal,
                    fontFamily = style.body,
                    fontWeight = FontWeight.Normal,
                    fontSize = mealSp.sp,
                    lineHeight = (mealSp * 1.55).sp,
                    color = if (isCurrent) palette.fg else palette.fgDim,
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
