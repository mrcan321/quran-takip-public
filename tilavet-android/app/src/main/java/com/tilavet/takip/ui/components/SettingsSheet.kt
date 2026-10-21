package com.tilavet.takip.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.audio.TextHold
import com.tilavet.takip.data.AppSettings
import com.tilavet.takip.data.MealCatalog
import com.tilavet.takip.glasses.GlassesState
import com.tilavet.takip.ui.theme.AppTheme
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import com.tilavet.takip.ui.theme.Palettes
import com.tilavet.takip.ui.theme.Styles
import kotlin.math.roundToInt

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsSheet(
    settings: AppSettings,
    onDismiss: () -> Unit,
    onTheme: (AppTheme) -> Unit,
    onArabicSize: (Int) -> Unit,
    onMealSize: (Int) -> Unit,
    onMotion: (Float) -> Unit,
    meals: List<MealCatalog.MealEdition> = emptyList(),
    onMealId: (String) -> Unit = {},
    onIdleOpacity: (Int) -> Unit,
    onSkippedAyahTenths: (Int) -> Unit = {},
    onTextHoldTenths: (Int) -> Unit = {},
    glassesLink: String? = null,
    onGlassesEnabled: (Boolean) -> Unit = {},
    onGlassesArabic: (Boolean) -> Unit = {},
    onGlassesBigText: (Boolean) -> Unit = {},
    onGlassesTextPx: (Int) -> Unit = {},
    onGlassesBigHeader: (Boolean) -> Unit = {},
    onGlassesFixedSize: (Boolean) -> Unit = {},
    onGlassesHideRakat: (Boolean) -> Unit = {},
    onGlassesFont: (String) -> Unit = {},
    onGlassesFontWeight: (Int) -> Unit = {},
    onGlassesOnePage: (Boolean) -> Unit = {},
    onGlassesOnePageMinPx: (Int) -> Unit = {},
    onGlassesHideBlankHeader: (Boolean) -> Unit = {},
    onGlassesHideStatus: (Boolean) -> Unit = {},
    onMinConfidence: (Int) -> Unit = {},
    onMinConfidenceFirstLock: (Int) -> Unit = {},
    onWindowSlack: (Int) -> Unit = {},
    onAsrDecoder: (String) -> Unit = {},
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = palette.bgElev,
        contentColor = palette.fg,
        scrimColor = Color(0x80000000),
        dragHandle = {
            Box(
                Modifier
                    .padding(top = 10.dp, bottom = 4.dp)
                    .width(36.dp)
                    .height(4.dp)
                    .background(if (style.ornate) style.gold.copy(alpha = 0.6f) else palette.fgFaded, RoundedCornerShape(2.dp))
            )
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(bottom = 30.dp)
        ) {
            // Header
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp)
                    .padding(top = 8.dp, bottom = 16.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (style.ornate) {
                        ArchEmblem(style.gold, Modifier.size(20.dp, 24.dp))
                        Spacer(Modifier.width(10.dp))
                    }
                    Text(
                        text = "Ayarlar",
                        fontSize = if (style.ornate) 26.sp else 22.sp,
                        fontFamily = style.display,
                        fontWeight = if (style.ornate) FontWeight.SemiBold else null,
                        color = if (style.ornate) style.headerTop else palette.fg,
                    )
                }
                Text(
                    text = "KAPAT",
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = 11.sp,
                    color = if (style.ornate) style.goldInk else palette.fgDim,
                    letterSpacing = style.tracking(0.8f).sp,
                    modifier = Modifier
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                        ) { onDismiss() }
                        .padding(8.dp)
                )
            }

            SheetDivider()

            Spacer(Modifier.height(20.dp))

            // === Theme ===
            SettingGroup(label = "TEMA") {
                ThemeGrid(currentTheme = settings.theme, onTheme = onTheme)
            }

            // === Arabic size ===
            SettingGroup(
                label = "ARAPÇA YAZI BOYUTU",
                trailing = "${settings.arabicSize} px"
            ) {
                AppSlider(
                    value = settings.arabicSize.toFloat(),
                    onValueChange = { onArabicSize(it.toInt()) },
                    valueRange = 18f..44f,
                )
            }

            // === Meal (Ayarlar → MEAL; liste meals/index.tsv'den, scripts/build_meals.py) ===
            if (meals.size > 1) {
                SettingGroup(
                    label = "MEAL",
                    hint = "Telefonda ve G2 gözlükte gösterilen Türkçe meal. Hepsi uygulamanın içinde, internet gerekmez.",
                ) {
                    MealPicker(meals = meals, currentId = settings.mealId, onSelect = onMealId)
                }
            }

            // === Meal size ===
            SettingGroup(
                label = "TÜRKÇE MEAL BOYUTU",
                trailing = "${settings.mealSize} px"
            ) {
                AppSlider(
                    value = settings.mealSize.toFloat(),
                    onValueChange = { onMealSize(it.toInt()) },
                    valueRange = 14f..32f,
                )
            }

            // === Motion ===
            SettingGroup(label = "HAREKET / ANİMASYON") {
                MotionRow(currentMotion = settings.motion, onMotion = onMotion)
            }

            // === Idle opacity ===
            SettingGroup(
                label = "ESKİ AYET SOLUKLUĞU",
                trailing = "%${settings.idleOpacity}"
            ) {
                AppSlider(
                    value = settings.idleOpacity.toFloat(),
                    onValueChange = { onIdleOpacity(it.toInt()) },
                    valueRange = 0f..80f,
                )
            }

            // === Atlanan ayetler: takip 2 → 5 gibi ileri atlayinca aradaki ayetlerin ekranda kalma suresi ===
            SettingGroup(
                label = "ATLANAN AYET SÜRESİ",
                trailing = if (settings.skippedAyahTenths == 0) "KAPALI"
                else "${settings.skippedAyahTenths / 10},${settings.skippedAyahTenths % 10} sn",
                hint = "Takip birden fazla ayet ileri atlarsa (ör. 2. ayetten 5.'ye) aradaki her ayet bu kadar gösterilir",
            ) {
                AppSlider(
                    value = settings.skippedAyahTenths.toFloat(),
                    onValueChange = { onSkippedAyahTenths(it.roundToInt()) },
                    valueRange = 0f..20f,
                    steps = 19,     // 0.1 sn adimlar
                )
            }

            // === Ses kesilince metin: zamm bitip rukuya gidilince ayet ekranda asili kalmasin (bkz. audio/TextHold) ===
            SettingGroup(
                label = "SES KESİLİNCE METİN",
                trailing = "${settings.textHoldTenths / 10},${settings.textHoldTenths % 10} sn",
                hint = "İmamın sesi kesildikten (rükû, secde) bu kadar sonra okunan ayet ekrandan ve gözlükten kalkar (gözlükte " +
                    "üstte rekât bilgisi: G2 BOŞ EKRANDA ÜST BİLGİYİ GİZLE ayarı). Okuma devam edince ayet geri gelir.",
            ) {
                AppSlider(
                    value = settings.textHoldTenths.toFloat(),
                    onValueChange = { onTextHoldTenths(it.roundToInt()) },
                    valueRange = 0f..TextHold.MAX_TENTHS.toFloat(),
                    steps = TextHold.MAX_TENTHS - 1,     // 0.1 sn adimlar
                )
            }

            // === Even Realities G2 gozluk: okunan ayet + meal gozlukte (bkz. glasses/GlassesBridge, assets/g2) ===
            SettingGroup(
                label = "G2 GÖZLÜK",
                trailing = if (settings.glassesEnabled) (glassesLink ?: "açılıyor").uppercase(java.util.Locale.forLanguageTag("tr")) else null,
                hint = "Okunan ayetin sure/ayet bilgisi ve meali Even Realities G2 gözlüğe de yazılır. Önce bu uygulama açık " +
                    "olmalı (güncellemeden sonra bir kez açın), sonra Even uygulamasında Tilavet Takip eklentisini açın " +
                    "(geliştirici modunda adres: http://localhost:18765/). Telefon cepte, ekran kapalıyken de dinleme sürer.",
            ) {
                OnOffRow(current = settings.glassesEnabled, onSelect = onGlassesEnabled)
            }
            if (settings.glassesEnabled) {
                SettingGroup(
                    label = "G2 YAZI",
                    hint = "BÜYÜK: gözlükte meal, sığan en büyük yazıyla ve ekranın ortasında (uzun meal sayfalara " +
                        "bölünür, imam okudukça ilerler; üstte isteğe bağlı sure/ayet satırı). NORMAL: gözlüğün kendi " +
                        "yazısı — sure/ayet başlığı + daha çok satır.",
                ) {
                    OnOffRow(current = settings.glassesBigText, onSelect = onGlassesBigText, labels = "NORMAL" to "BÜYÜK")
                }
                if (settings.glassesBigText && !settings.glassesArabic) {
                    SettingGroup(
                        label = "G2 YAZI TİPİ",
                        hint = "Sadece gözlükteki büyük yazı (telefon değişmez); seçince gözlükte hemen değişir. " +
                            "Atkinson Hyperlegible: Braille Enstitüsü, az görenlerle test edilerek; benzer harfler (I l 1, " +
                            "O 0) kolay ayrılır. Lexend: okuma akıcılığı araştırmasına dayanır, harf aralığı geniş. Inter: " +
                            "ekran için, küçük harfleri iri (yüksek x-yüksekliği). Manrope: şimdiye kadarki yazı.",
                    ) {
                        ChoiceGrid(
                            options = GlassesState.FONTS.map { (id, name) -> name.uppercase(java.util.Locale.ROOT) to id },
                            current = settings.glassesFont,
                            onSelect = onGlassesFont,
                            columns = 2,
                        )
                    }
                    SettingGroup(
                        label = "G2 YAZI KALINLIĞI",
                        hint = "Gözlüğün yeşil ekranında ince yazı daha soluk görünür; uzun okumada KALIN önerilir.",
                    ) {
                        ChoiceGrid(
                            options = GlassesState.WEIGHTS.map { (w, name) -> name to w },
                            current = settings.glassesFontWeight,
                            onSelect = onGlassesFontWeight,
                            columns = 4,
                        )
                    }
                    SettingGroup(
                        label = "G2 YAZI BOYUTU",
                        trailing = "${settings.glassesTextPx} px",
                        hint = if (settings.glassesOnePage) {
                            "Gözlükte yazı bu boyutta" + (if (settings.glassesFixedSize) "" else " ya da kısa metinde daha büyük") +
                                " (gözlüğün kendi yazısının satırı 27 px); sığmayan ayet tek ekrana sığana kadar küçülür " +
                                "(en çok G2 TEK EKRAN EN KÜÇÜK YAZI'ya kadar). Değişiklik gözlükte hemen görünür."
                        } else if (settings.glassesFixedSize) {
                            "Gözlükte yazı her zaman bu boyutta (gözlüğün kendi yazısının satırı 27 px); sığmayan meal " +
                                "sayfalara bölünür, sayfalar imam okudukça ilerler. Değişiklik gözlükte hemen görünür."
                        } else {
                            "Gözlükte yazı en az bu boyutta (gözlüğün kendi yazısının satırı 27 px). Kısa metin daha da " +
                                "büyük çizilir; sığmayan meal sayfalara bölünür, sayfalar imam okudukça ilerler. Değişiklik " +
                                "gözlükte hemen görünür."
                        },
                    ) {
                        AppSlider(
                            value = settings.glassesTextPx.toFloat(),
                            onValueChange = { onGlassesTextPx((it.roundToInt() / 2) * 2) },
                            valueRange = GlassesState.MIN_TEXT_PX.toFloat()..GlassesState.MAX_TEXT_PX.toFloat(),
                            steps = (GlassesState.MAX_TEXT_PX - GlassesState.MIN_TEXT_PX) / 2 - 1,   // 2 px adimlar
                        )
                    }
                    SettingGroup(
                        label = "G2 SABİT YAZI BOYUTU",
                        hint = "Açıkken her metin G2 YAZI BOYUTU'nda: kısa metin büyütülmez, uzun meal küçültülmez (sayfalara " +
                            "bölünür). Kapalıyken kısa metin sığdığı kadar büyük çizilir, uzun meal ayardaki boyuta kadar küçülür.",
                    ) {
                        OnOffRow(current = settings.glassesFixedSize, onSelect = onGlassesFixedSize)
                    }
                    SettingGroup(
                        label = "G2 AYETİ TEK EKRANA SIĞDIR",
                        hint = "Açıkken uzun ayet sayfalara bölünmez, tamamı tek ekranda: yazı gerektiği kadar küçülür (en çok " +
                            "G2 TEK EKRAN EN KÜÇÜK YAZI'ya kadar). Sığan metin eskisi gibi çizilir (SABİT YAZI BOYUTU açıksa " +
                            "ayardaki boyutta). Kapalıyken sığmayan meal G2 YAZI BOYUTU'nda sayfalara bölünür.",
                    ) {
                        OnOffRow(current = settings.glassesOnePage, onSelect = onGlassesOnePage)
                    }
                    if (settings.glassesOnePage) {
                        SettingGroup(
                            label = "G2 TEK EKRAN EN KÜÇÜK YAZI",
                            trailing = "${minOf(settings.glassesOnePageMinPx, settings.glassesTextPx)} px",
                            hint = "Tek ekrana sığdırırken yazı en çok bu boyuta küçülür (gözlüğün kendi yazısının satırı 27 px). " +
                                "Bu boyutta da sığmayan ayet sayfalara bölünür: olabildiğince az sayfa, o sayfa sayısına sığan en " +
                                "büyük yazı. 12 px'te bütün ayetler tek ekrana sığar (en uzunu Bakara 282); 20 px'te ~100 uzun " +
                                "ayet 2-3 sayfa olur. G2 YAZI BOYUTU'ndan büyük olamaz.",
                        ) {
                            AppSlider(
                                value = settings.glassesOnePageMinPx.toFloat(),
                                onValueChange = { onGlassesOnePageMinPx((it.roundToInt() / 2) * 2) },
                                valueRange = GlassesState.MIN_ONE_PAGE_PX.toFloat()..GlassesState.MAX_ONE_PAGE_PX.toFloat(),
                                steps = (GlassesState.MAX_ONE_PAGE_PX - GlassesState.MIN_ONE_PAGE_PX) / 2 - 1,   // 2 px adimlar
                            )
                        }
                    }
                }
                SettingGroup(
                    label = "G2 ÜST BİLGİ (AYET OKUNURKEN)",
                    hint = "Açıkken gözlükte üstte küçük bir satırda sure adı, ayet numarası, rekât ve sayfa (ör. Bakara: 255 · " +
                        "1. REKÂT · KIYAM 1/3) gözlüğün kendi yazısıyla görünür; aday ayet orada \"ADAY\" yazar. Kapalıyken üst " +
                        "bilgi hiç çıkmaz, ekranın tamamı meal (büyük yazıda da, gözlüğün kendi yazısında ve Arapçada da).",
                ) {
                    OnOffRow(current = settings.glassesBigHeader, onSelect = onGlassesBigHeader)
                }
                if (settings.glassesBigHeader) {
                    SettingGroup(
                        label = "G2 REKÂT BİLGİSİNİ GİZLE",
                        hint = "Açıkken üst bilgide rekât ve duruş (1. REKÂT · KIYAM) yazmaz, sadece sure adı ve ayet numarası " +
                            "(ör. Bakara: 255); boş ekranın üst satırında da rekât yazmaz.",
                    ) {
                        OnOffRow(current = settings.glassesHideRakat, onSelect = onGlassesHideRakat)
                    }
                }
                SettingGroup(
                    label = "G2 BOŞ EKRANDA ÜST BİLGİYİ GİZLE",
                    hint = "Ses kesilince (rükû, secde — SES KESİLİNCE METİN) gözlükte ayet kalkar. Açıkken ekran bomboş kalır; " +
                        "kapalıyken üstte rekât ve duruş (ör. 1. REKÂT · RÜKÛ / SECDE) yazar.",
                ) {
                    OnOffRow(current = settings.glassesHideBlankHeader, onSelect = onGlassesHideBlankHeader)
                }
                SettingGroup(
                    label = "G2 DURUM YAZISINI GİZLE",
                    hint = "Açıkken gözlükte \"Dinleme kapalı\", \"Dinleniyor\", \"Kamet · Fatiha bekleniyor\" gibi durum yazıları " +
                        "çıkmaz, ekran bomboş kalır; ayet bulununca meal gelir. Zikir / ezan kartı yine gösterilir.",
                ) {
                    OnOffRow(current = settings.glassesHideStatus, onSelect = onGlassesHideStatus)
                }
                SettingGroup(
                    label = "G2'DE ARAPÇA",
                    hint = "Varsayılan kapalı. Açıkken ayet metni de görüntü olarak çizilir (gözlük fontunda Arapça harf yok); " +
                        "meal gözlüğün kendi yazısıyla, daha az satıra sığar.",
                ) {
                    OnOffRow(current = settings.glassesArabic, onSelect = onGlassesArabic)
                }
            }

            // === DEBUG TUNER ===
            Spacer(Modifier.height(8.dp))
            SheetDivider()
            Spacer(Modifier.height(8.dp))

            SectionHeader(label = "TUNER (DEBUG)")

            // === ASR decoder ===
            SettingGroup(label = "ASR DECODER") {
                DecoderRow(current = settings.asrDecoder, onSelect = onAsrDecoder)
            }

            // === Min confidence (kilitli iken) ===
            SettingGroup(
                label = "GUVEN ESIGI (KILITLI)",
                trailing = "${settings.minConfidence}",
            ) {
                AppSlider(
                    value = settings.minConfidence.toFloat(),
                    onValueChange = { onMinConfidence(it.toInt()) },
                    valueRange = 30f..95f,
                )
            }

            // === Min confidence first lock ===
            SettingGroup(
                label = "GUVEN ESIGI (ILK KILIT)",
                trailing = "${settings.minConfidenceFirstLock}",
            ) {
                AppSlider(
                    value = settings.minConfidenceFirstLock.toFloat(),
                    onValueChange = { onMinConfidenceFirstLock(it.toInt()) },
                    valueRange = 50f..95f,
                )
            }

            // === Window slack ===
            SettingGroup(
                label = "ALIGNER PENCERE GENISLIGI",
                trailing = "±${settings.windowSlack}",
            ) {
                AppSlider(
                    value = settings.windowSlack.toFloat(),
                    onValueChange = { onWindowSlack(it.toInt()) },
                    valueRange = 0f..5f,
                )
            }
        }
    }
}

/** Bolum ayraci: klasikte ince cizgi, zumrutte iki yana solan altin cizgi. */
@Composable
private fun SheetDivider() {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    if (style.ornate) {
        Box(
            Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .height(1.dp)
                .background(
                    Brush.horizontalGradient(
                        listOf(style.gold.copy(alpha = 0f), style.gold.copy(alpha = 0.5f), style.gold.copy(alpha = 0f))
                    )
                )
        )
    } else {
        Box(Modifier.fillMaxWidth().height(1.dp).background(palette.border))
    }
}

@Composable
private fun SectionHeader(label: String) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 6.dp),
    ) {
        Text(
            text = label,
            fontFamily = style.label,
            fontWeight = if (style.ornate) FontWeight.Bold else null,
            fontSize = 11.sp,
            color = if (style.ornate) style.goldInk else palette.accent,
            letterSpacing = style.tracking(1.2f).sp,
        )
    }
}

@Composable
private fun SettingGroup(
    label: String,
    trailing: String? = null,
    hint: String? = null,
    content: @Composable () -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                fontFamily = style.label,
                fontWeight = if (style.ornate) FontWeight.SemiBold else null,
                fontSize = 10.sp,
                color = palette.fgDim,
                letterSpacing = style.tracking(1.0f).sp,
            )
            trailing?.let {
                Text(
                    text = it,
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = if (style.ornate) 11.sp else 10.sp,
                    color = palette.accent,
                )
            }
        }
        Spacer(Modifier.height(10.dp))
        content()
        hint?.let {
            Text(
                text = it,
                fontSize = 11.sp,
                lineHeight = if (style.ornate) 16.sp else androidx.compose.ui.unit.TextUnit.Unspecified,
                color = palette.fgDim,
            )
        }
    }
}

@Composable
private fun ThemeGrid(
    currentTheme: AppTheme,
    onTheme: (AppTheme) -> Unit,
) {
    Column {
        AppTheme.entries.chunked(4).forEach { row ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                row.forEach { theme ->
                    ThemeSwatch(
                        theme = theme,
                        isActive = currentTheme == theme,
                        onClick = { onTheme(theme) },
                        modifier = Modifier.weight(1f),
                    )
                }
                repeat(4 - row.size) {
                    Box(modifier = Modifier.weight(1f))
                }
            }
            Spacer(Modifier.height(10.dp))
        }
    }
}

@Composable
private fun ThemeSwatch(
    theme: AppTheme,
    isActive: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val currentPalette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val themePalette = Palettes.forTheme(theme)
    val themeStyle = Styles.forTheme(theme)
    val labelColor = if (theme.isLight) Color(0xCC000000) else Color(0xE6FFFFFF)

    // Zumrut ornegi: ustte koyu zumrut bant + kucuk cami silueti, altta krem, arada altin cizgi
    val swatchBg = if (themeStyle.ornate) Modifier.drawBehind {
        val band = size.height * 0.48f
        drawRect(themePalette.bg)
        drawRect(Brush.verticalGradient(listOf(themeStyle.headerTop, themeStyle.headerBottom), endY = band), size = size.copy(height = band))
        drawMosqueSkyline(themeStyle.skyline, cx = size.width * 0.5f, baseY = band, u = band / 175f)
        drawLine(themeStyle.gold, Offset(0f, band), Offset(size.width, band), strokeWidth = 1.5f)
    } else Modifier.background(
        Brush.linearGradient(
            0.0f to themePalette.bg,
            0.6f to themePalette.bg,
            0.6f to themePalette.accent,
            1.0f to themePalette.accent,
        )
    )

    Box(
        modifier = modifier
            .aspectRatio(1f)
            .clip(RoundedCornerShape(12.dp))
            .then(swatchBg)
            .border(
                width = 2.dp,
                color = if (isActive) currentPalette.accent else Color.Transparent,
                shape = RoundedCornerShape(12.dp),
            )
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
            ) { onClick() },
        contentAlignment = Alignment.BottomCenter,
    ) {
        Text(
            text = theme.displayName.uppercase(),
            fontFamily = style.label,
            fontWeight = if (style.ornate) FontWeight.Bold else null,
            fontSize = 8.sp,
            color = if (themeStyle.ornate) themeStyle.headerTop else labelColor,
            letterSpacing = style.tracking(0.6f).sp,
            modifier = Modifier.padding(bottom = 6.dp),
        )
    }
}

@Composable
private fun MotionRow(
    currentMotion: Float,
    onMotion: (Float) -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val options = listOf(
        Triple("YOK", 0f, currentMotion == 0f),
        Triple("AZ", 0.5f, currentMotion in 0.4f..0.6f),
        Triple("TAM", 1f, currentMotion >= 0.9f),
    )

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEach { (label, value, isActive) ->
            Box(
                modifier = Modifier
                    .weight(1f)
                    .border(
                        width = 1.dp,
                        color = if (isActive) palette.accent else palette.borderStrong,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .background(
                        color = if (isActive) palette.accentDim else Color.Transparent,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                    ) { onMotion(value) }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = label,
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = 11.sp,
                    color = if (isActive) palette.accent else palette.fgDim,
                    letterSpacing = style.tracking(0.8f).sp,
                )
            }
        }
    }
}

/**
 * Meal secimi: kapaliyken secili meal (ad + aciklama) tek satir; dokununca tum mealler acilir, birine dokununca secilir ve
 * liste kapanir. Bilinmeyen id (eski / silinmis baski) → ilk meal (varsayilan) secili gorunur.
 */
@Composable
private fun MealPicker(
    meals: List<MealCatalog.MealEdition>,
    currentId: String,
    onSelect: (String) -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    var open by remember { mutableStateOf(false) }
    val current = meals.firstOrNull { it.id == currentId } ?: meals.first()
    val shown = if (open) meals else listOf(current)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        shown.forEach { m ->
            val isActive = m.id == current.id
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .border(
                        width = 1.dp,
                        color = if (isActive) palette.accent else palette.borderStrong,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .background(
                        color = if (isActive) palette.accentDim else Color.Transparent,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                    ) {
                        if (open) {
                            onSelect(m.id)
                            open = false
                        } else {
                            open = true
                        }
                    }
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = m.name,
                        fontFamily = style.body,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp,
                        color = if (isActive) palette.accent else palette.fg,
                    )
                    if (m.desc.isNotBlank()) {
                        Text(
                            text = m.desc,
                            fontFamily = style.body,
                            fontSize = 11.sp,
                            color = palette.fgDim,
                        )
                    }
                }
                if (!open) {
                    Text(
                        text = "DEĞİŞTİR",
                        fontFamily = style.label,
                        fontWeight = if (style.ornate) FontWeight.Bold else null,
                        fontSize = 10.sp,
                        color = palette.accent,
                        letterSpacing = style.tracking(0.8f).sp,
                    )
                }
            }
        }
    }
}

/** Secenek kutulari (G2 yazi tipi / kalinligi): [options] = (etiket, deger), [columns] sutunlu satirlar. */
@Composable
private fun <T> ChoiceGrid(
    options: List<Pair<String, T>>,
    current: T,
    onSelect: (T) -> Unit,
    columns: Int,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        options.chunked(columns).forEach { row ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                row.forEach { (label, value) ->
                    val isActive = current == value
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .border(
                                width = 1.dp,
                                color = if (isActive) palette.accent else palette.borderStrong,
                                shape = RoundedCornerShape(10.dp),
                            )
                            .background(
                                color = if (isActive) palette.accentDim else Color.Transparent,
                                shape = RoundedCornerShape(10.dp),
                            )
                            .clickable(
                                interactionSource = remember { MutableInteractionSource() },
                                indication = null,
                            ) { onSelect(value) }
                            .padding(vertical = 12.dp, horizontal = 4.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = label,
                            fontFamily = style.label,
                            fontWeight = if (style.ornate) FontWeight.Bold else null,
                            fontSize = 11.sp,
                            color = if (isActive) palette.accent else palette.fgDim,
                            letterSpacing = style.tracking(0.8f).sp,
                            maxLines = 1,
                        )
                    }
                }
                repeat(columns - row.size) { Box(modifier = Modifier.weight(1f)) }
            }
        }
    }
}

/** Iki secenek (G2 ayarlari): [labels] = (false etiketi, true etiketi), varsayilan KAPALI / AÇIK. */
@Composable
private fun OnOffRow(
    current: Boolean,
    onSelect: (Boolean) -> Unit,
    labels: Pair<String, String> = "KAPALI" to "AÇIK",
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        listOf(labels.first to false, labels.second to true).forEach { (label, value) ->
            val isActive = current == value
            Box(
                modifier = Modifier
                    .weight(1f)
                    .border(
                        width = 1.dp,
                        color = if (isActive) palette.accent else palette.borderStrong,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .background(
                        color = if (isActive) palette.accentDim else Color.Transparent,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                    ) { onSelect(value) }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = label,
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = 11.sp,
                    color = if (isActive) palette.accent else palette.fgDim,
                    letterSpacing = style.tracking(0.8f).sp,
                )
            }
        }
    }
}

/**
 * RNNT / CTC secimi. RNNT daha dogru (eval: medyan skor 79 → 91), CTC biraz daha hizli.
 * Model RNNT icermiyorsa motor otomatik CTC'ye duser.
 */
@Composable
private fun DecoderRow(
    current: String,
    onSelect: (String) -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val options = listOf("RNNT", "CTC")

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEach { value ->
            val isActive = current.equals(value, ignoreCase = true)
            Box(
                modifier = Modifier
                    .weight(1f)
                    .border(
                        width = 1.dp,
                        color = if (isActive) palette.accent else palette.borderStrong,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .background(
                        color = if (isActive) palette.accentDim else Color.Transparent,
                        shape = RoundedCornerShape(10.dp),
                    )
                    .clickable(
                        interactionSource = remember { MutableInteractionSource() },
                        indication = null,
                    ) { onSelect(value) }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = value,
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = 11.sp,
                    color = if (isActive) palette.accent else palette.fgDim,
                    letterSpacing = style.tracking(0.8f).sp,
                )
            }
        }
    }
}

@Composable
private fun AppSlider(
    value: Float,
    onValueChange: (Float) -> Unit,
    valueRange: ClosedFloatingPointRange<Float>,
    steps: Int = 0,
) {
    val palette = LocalAppPalette.current
    Slider(
        value = value,
        onValueChange = onValueChange,
        valueRange = valueRange,
        steps = steps,
        colors = SliderDefaults.colors(
            thumbColor = palette.accent,
            activeTrackColor = palette.accent,
            inactiveTrackColor = palette.fgGhost,
            activeTickColor = Color.Transparent,
            inactiveTickColor = Color.Transparent,
        ),
    )
}
