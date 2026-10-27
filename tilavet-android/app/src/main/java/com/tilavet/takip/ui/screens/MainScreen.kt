package com.tilavet.takip.ui.screens

import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.collectIsDraggedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.Functions
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.IosShare
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Science
import androidx.compose.material.icons.filled.Tag
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.SimRecording
import com.tilavet.takip.UiState
import com.tilavet.takip.session.EzanView
import com.tilavet.takip.session.NamazZikri
import com.tilavet.takip.ui.components.*
import com.tilavet.takip.ui.theme.AppPalette
import com.tilavet.takip.ui.theme.AppStyle
import com.tilavet.takip.ui.theme.JetBrainsMonoFamily
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import java.io.File
import kotlin.math.abs

/**
 * Uzak atlama: okunan ayet ekranin ustundeki satirdan bu kadar satirdan (ayet / sure basligi) uzaksa
 * animasyonsuz gidilir. Imam baska sureye gecince yuzlerce ayetlik kaydirma animasyonu ayetin ekrana
 * gelmesini geciktiriyordu (kullanici: 7-8 ayetten uzaksa animasyon olmasin, yakinsa kalsin).
 */
private const val FAR_JUMP_ITEMS = 8

/** Okunan ayetin ekrandaki yeri: liste alaninin ustunden bu kadar asagi (onceki ayetin sonu gorunsun). */
private val CURRENT_AYAH_TOP_OFFSET = 90.dp

/**
 * Ana ekran — ustten alta tek sutun:
 *   TopBar (durum + sure + test ikonlari) → StatusLine (tek satir, sabit) → Mushaf listesi → Footer
 *
 * Zumrut temasi (ornate): TopBar + StatusLine tek koyu zumrut bantta (alti yuvarlak, cami silueti, kemer
 * amblemi, serif sure adi), zemin krem gradyan, Footer golgeli beyaz alt bar.
 *
 * Liste kendi alaninda kayar; ust bar ve durum satirinin altina girmez (eskiden liste tum ekrani
 * kaplayip ust bar ve ASR TEST kutusu uzerine biniyordu — kutu model hazir olunca hic kapanmiyordu).
 *
 * @param buildLabel durum satirinin en saginda gosterilen surum/commit ("#16 · 221c127") — hangi kodun
 *                   test edildigi ekrandan okunur.
 */
@Composable
fun MainScreen(
    state: UiState,
    onToggleListening: () -> Unit,
    onOpenSettings: () -> Unit,
    onAsrTest: () -> Unit = {},
    onAlignerTest: () -> Unit = {},
    onFuzzyTest: () -> Unit = {},
    onStateMachineTest: () -> Unit = {},
    onLogExport: () -> Unit = {},
    onReport: () -> Unit = {},
    buildLabel: String = "",
    onSimMenuOpen: () -> Unit = {},
    onSimRecording: (File) -> Unit = {},
    onSimPickFile: () -> Unit = {},
    onSimStop: () -> Unit = {},
    onEzanDismiss: () -> Unit = {},
    onZikirDismiss: () -> Unit = {},
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val listState = rememberLazyListState()
    val mushaf = state.mushaf
    val focusOffsetPx = with(LocalDensity.current) { CURRENT_AYAH_TOP_OFFSET.roundToPx() }

    // Sese gore takip (otomatik kaydirma). Kullanici listeyi parmakla kaydirinca DURUR ve kendiliginden
    // geri donmez (eskiden 1.5 sn sonra okunan ayete donuyordu — kullanici onceki/sonraki ayetlere bakarken
    // ekran elinden kaciyordu). Sagda beliren ok butonuna basinca takip devam eder ve okunan ayete gidilir.
    // Yeni dinleme / simulasyon baslayinca takip acik baslar. Sadece suruklemeye bakilir: dokunup
    // birakmak (kaydirmadan) takibi bozmaz; programatik kaydirma suruklenme sayilmaz.
    var followPaused by remember { mutableStateOf(false) }
    val dragged by listState.interactionSource.collectIsDraggedAsState()
    LaunchedEffect(dragged) { if (dragged) followPaused = true }
    LaunchedEffect(state.isListening) { if (state.isListening) followPaused = false }

    val targetItem = if (mushaf != null && state.currentAyah != null) mushaf.listIndexOfAyah(state.currentAyah) else null
    LaunchedEffect(targetItem, followPaused, mushaf) {
        if (targetItem == null || followPaused) return@LaunchedEffect
        scrollToCurrent(listState, targetItem, focusOffsetPx, animate = state.settings.motion > 0f)
    }

    // Ekranin ustundeki sure (ust bar'da gosterilir)
    val visibleSurah by remember(mushaf) {
        derivedStateOf { mushaf?.let { it.surahOfItem(listState.firstVisibleItemIndex) } }
    }

    // Test sonuc paneli (Σ # ▶): dokununca kapanir; sonuc/durum degisince (yeni test) tekrar acilir
    var dismissedPanel by remember { mutableStateOf("") }

    val rootBg = if (style.ornate) Modifier.ornateBackground(palette, style) else Modifier.background(palette.bg)
    Column(modifier = Modifier.fillMaxSize().then(rootBg)) {
        if (style.ornate) {
            OrnateHeader(
                statusText = if (state.isListening && state.micSilenced) "Mikrofon susturuldu" else state.statusText,
                surahName = visibleSurah?.let { s -> mushaf?.surahNameTr(s) },
                surahNo = visibleSurah,
                isListening = state.isListening,
                motion = state.settings.motion,
                info = statusLineInfo(state),
                buildLabel = buildLabel,
                onSettings = onOpenSettings,
                onAsrTest = onAsrTest,
                onAlignerTest = onAlignerTest,
                onFuzzyTest = onFuzzyTest,
                onStateMachineTest = onStateMachineTest,
                onLogExport = onLogExport,
                onReport = onReport,
            )
        } else {
            TopBar(
                statusText = if (state.isListening && state.micSilenced) "Mikrofon susturuldu" else state.statusText,
                surahText = visibleSurah?.let { s -> "${mushaf?.surahNameTr(s) ?: ""} · $s" } ?: "",
                isListening = state.isListening,
                motion = state.settings.motion,
                onSettings = onOpenSettings,
                onAsrTest = onAsrTest,
                onAlignerTest = onAlignerTest,
                onFuzzyTest = onFuzzyTest,
                onStateMachineTest = onStateMachineTest,
                onLogExport = onLogExport,
                onReport = onReport,
            )

            StatusLine(info = statusLineInfo(state), buildLabel = buildLabel)
        }

        // Icerik alani: liste + (varsa) test paneli + alt bilgi. Liste bu alanin disina tasmaz.
        Box(modifier = Modifier.fillMaxWidth().weight(1f)) {
            if (mushaf != null) {
                Box(modifier = Modifier.fillMaxSize()) {
                    MushafList(
                        mushaf = mushaf,
                        listState = listState,
                        // Ses kesildi (TextHold): okunan ayet vurgusu kalkar, liste yerinde kalir
                        currentAyah = if (state.textHidden) null else state.currentAyah,
                        tentative = state.tentative,
                        hlStart = state.hlStart,
                        hlEnd = state.hlEnd,
                        arabicSizeSp = state.settings.arabicSize,
                        mealSizeSp = state.settings.mealSize,
                        idleOpacity = state.settings.idleOpacity / 100f,
                        motion = state.settings.motion.coerceAtLeast(0.001f),
                        contentPadding = PaddingValues(top = if (style.ornate) 4.dp else 8.dp, bottom = 150.dp),
                    )
                }
            } else {
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    EmptyState()
                }
            }

            // Test sonuc panelleri — birden fazla varken en son aktif olan
            val panel: Triple<String, String, String>? = when {
                state.stateMachineResult.isNotEmpty() || state.stateMachineState.isNotEmpty() ->
                    Triple("STATE MACHINE TEST", state.stateMachineState, state.stateMachineResult)
                state.fuzzyResult.isNotEmpty() || state.fuzzyState.isNotEmpty() ->
                    Triple("FUZZY TEST", state.fuzzyState, state.fuzzyResult)
                state.alignerResult.isNotEmpty() || state.alignerState.isNotEmpty() ->
                    Triple("ALIGNER TEST", state.alignerState, state.alignerResult)
                else -> null
            }
            if (panel != null) {
                val key = panel.toString()
                if (key != dismissedPanel) {
                    TestPanel(
                        title = panel.first,
                        stateText = panel.second,
                        resultText = panel.third,
                        onDismiss = { dismissedPanel = key },
                        modifier = Modifier.align(Alignment.TopCenter).padding(top = 8.dp),
                    )
                }
            }

            // Takip durdurulduysa (elle kaydirma) okunan ayete donus butonu: ok, ayetin yonunu gosterir
            if (followPaused && targetItem != null) {
                val targetAbove = targetItem < listState.firstVisibleItemIndex
                FollowButton(
                    up = targetAbove,
                    onClick = { followPaused = false },
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .navigationBarsPadding()
                        .padding(end = 18.dp, bottom = 104.dp),
                )
            }

            // Ezan / kamet penceresi: listenin ustunde; kapaninca son icerik solarak gider
            var lastEzan by remember { mutableStateOf<EzanView?>(null) }
            if (state.ezan != null) lastEzan = state.ezan
            // (tam ad: dis Column'un ColumnScope.AnimatedVisibility'si secilmesin)
            androidx.compose.animation.AnimatedVisibility(
                visible = state.ezan != null,
                enter = fadeIn() + slideInVertically { -it / 4 },
                exit = fadeOut(),
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(start = 12.dp, end = 12.dp, top = 10.dp, bottom = 96.dp),
            ) {
                lastEzan?.let { EzanPopup(view = it, onDismiss = onEzanDismiss, modifier = Modifier.fillMaxWidth()) }
            }

            // Namaz zikri karti (tekbir, semiallah, selam...): ezan penceresiyle ayni yerde, o kapaliyken
            var lastZikir by remember { mutableStateOf<NamazZikri?>(null) }
            if (state.zikir != null) lastZikir = state.zikir
            androidx.compose.animation.AnimatedVisibility(
                visible = state.zikir != null && state.ezan == null,
                enter = fadeIn() + slideInVertically { -it / 4 },
                exit = fadeOut(),
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(start = 12.dp, end = 12.dp, top = 10.dp),
            ) {
                lastZikir?.let { ZikirPopup(zikir = it, onDismiss = onZikirDismiss, modifier = Modifier.fillMaxWidth()) }
            }

            Footer(
                audioLevel = state.audioLevel,
                isListening = state.isListening,
                label = if (state.textHidden) "" else state.currentLabel,
                confidence = state.confidence,
                tentative = state.tentative,
                motion = state.settings.motion,
                onToggleMic = onToggleListening,
                simActive = state.isListening && state.simFile != null,
                simRecordings = state.simRecordings,
                onSimMenuOpen = onSimMenuOpen,
                onSimRecording = onSimRecording,
                onSimPickFile = onSimPickFile,
                onSimStop = onSimStop,
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }
}

/**
 * Durum satiri parcalari: rekat + durus (en basta, kisalmaz; RakatTracker) + etiket (vurgulu, opsiyonel) + govde
 * (kisalir) + kuyruk (opsiyonel).
 */
private data class StatusInfo(val tag: String, val body: String, val tail: String, val lead: String = "")

/**
 * Durum satiri (tek satir):
 *   - ASR testi calisiyor / sonucu var → [ASR TEST] <arapca metin> <RNNT 612ms> (dinlemeye baslayinca temizlenir)
 *   - Dinlerken → "Model hazır · güven %91 · gecikme 0,6 sn"
 *   - Aksi halde model durumu (bekliyor / kopyalaniyor / yukleniyor / hazir / hata)
 * Arapca sonuc ayri Text'te: Latin + Arapca tek metinde kisaltma (…) Arapcayi tamamen yutuyordu.
 */
private fun statusLineInfo(state: UiState): StatusInfo {
    val info = statusLineInfoBase(state)
    return if (state.isListening && state.rakatLabel != null) info.copy(lead = state.rakatLabel) else info
}

private fun statusLineInfoBase(state: UiState): StatusInfo {
    if (state.asrInProgress || state.asrLastResult.isNotEmpty()) {
        return StatusInfo("ASR TEST", state.asrLastResult, state.asrTimingInfo)
    }
    val model = when {
        state.asrState.isEmpty() -> "Model beklemede"
        state.asrState == "Hazır" -> "Model hazır"
        else -> state.asrState
    }
    if (!state.isListening) return StatusInfo("", model, "")
    // Simulasyonda satir dar (etiket + konum): model hazirsa yazilmaz
    val sim = state.simFile != null
    val parts = if (sim && state.asrState == "Hazır") mutableListOf<String>() else mutableListOf(model)
    state.confidence?.let { parts += "güven %$it" }
    state.lastLatencyMs?.let { parts += "gecikme ${"%.1f".format(it / 1000.0)} sn" }
    // Simulasyon modu: kisa etiket (satir dar) + dosyadaki konum / toplam sure
    if (sim) {
        val tail = mmss(state.simPositionSec) + if (state.simDurationSec > 0) "/${mmss(state.simDurationSec)}" else ""
        return StatusInfo("SİM", parts.joinToString(" · "), tail)
    }
    return StatusInfo("", parts.joinToString(" · "), "")
}

private fun mmss(sec: Int): String = "%d:%02d".format(sec / 60, sec % 60)

/** Oturum kaydi adi "tilavet-20261001-190350.wav" → "01.10 19:03"; uymazsa dosya adi. */
private fun recordingTitle(f: File): String {
    val n = f.name
    if (n.length != 27 || !n.startsWith("tilavet-") || !n.endsWith(".wav")) return n
    return "${n.substring(14, 16)}.${n.substring(12, 14)} ${n.substring(17, 19)}:${n.substring(19, 21)}"
}

/**
 * Okunan ayeti liste alaninin ust kismina (onceki ayetin sonu gorunecek sekilde) getir.
 * Yakinsa (FAR_JUMP_ITEMS satir icinde) yumusak kayar; uzaksa (baska sure) animasyonsuz atlar.
 */
private suspend fun scrollToCurrent(listState: LazyListState, itemIndex: Int, offsetPx: Int, animate: Boolean) {
    // Negatif offset: oge icerik alaninin ustunden offsetPx asagida durur (layout'tan bagimsiz, ilk karede de dogru)
    val offset = -offsetPx
    val near = abs(itemIndex - listState.firstVisibleItemIndex) <= FAR_JUMP_ITEMS
    if (animate && near) {
        listState.animateScrollToItem(itemIndex, scrollOffset = offset)
    } else {
        listState.scrollToItem(itemIndex, scrollOffset = offset)
    }
}

/** Takibe donus butonu (elle kaydirmadan sonra): yuvarlak, vurgu renginde, ok okunan ayetin yonunde. */
@Composable
private fun FollowButton(up: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Box(
        modifier = modifier
            .size(48.dp)
            .then(
                if (style.ornate) Modifier
                    .shadow(8.dp, CircleShape, ambientColor = style.shadow, spotColor = style.shadow)
                    .background(palette.accent, CircleShape)
                    .border(1.dp, style.gold.copy(alpha = 0.7f), CircleShape)
                else Modifier
                    .shadow(6.dp, CircleShape)
                    .background(palette.accent, CircleShape)
            )
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = if (up) Icons.Filled.KeyboardArrowUp else Icons.Filled.KeyboardArrowDown,
            contentDescription = "Okunan ayete dön",
            tint = palette.bg,
            modifier = Modifier.size(30.dp),
        )
    }
}

@Composable
private fun TopBar(
    statusText: String,
    surahText: String,
    isListening: Boolean,
    motion: Float,
    onSettings: () -> Unit,
    onAsrTest: () -> Unit,
    onAlignerTest: () -> Unit,
    onFuzzyTest: () -> Unit,
    onStateMachineTest: () -> Unit,
    onLogExport: () -> Unit,
    onReport: () -> Unit,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current

    // Row + weight: uzun durum metni ikonlarin altina tasmaz, "…" ile kisalir
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .background(palette.bg)
            .statusBarsPadding()
            .padding(horizontal = 18.dp)
            .padding(top = 14.dp, bottom = 10.dp)
    ) {
        Column(
            modifier = Modifier.weight(1f).padding(end = 8.dp),
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                LiveDot(isActive = isListening, motion = motion)
                Text(
                    text = statusText.uppercase(),
                    fontFamily = style.label,
                    fontSize = 11.sp,
                    color = palette.fgDim,
                    letterSpacing = 0.6.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (surahText.isNotEmpty()) {
                Text(
                    text = surahText.uppercase(),
                    fontFamily = style.label,
                    fontSize = 10.sp,
                    color = palette.fgFaded,
                    letterSpacing = 0.6.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        TestIcons(
            spacing = 8.dp,
            onSettings = onSettings,
            onAsrTest = onAsrTest,
            onAlignerTest = onAlignerTest,
            onFuzzyTest = onFuzzyTest,
            onStateMachineTest = onStateMachineTest,
            onLogExport = onLogExport,
            onReport = onReport,
        )
    }
}

/** Ust bar ikonlari: Σ # ▶ 🔬 📄 📤 ⚙ (test sonuclari durum satirinda / panelde; 📄 namaz raporu). */
@Composable
private fun TestIcons(
    spacing: androidx.compose.ui.unit.Dp,
    onSettings: () -> Unit,
    onAsrTest: () -> Unit,
    onAlignerTest: () -> Unit,
    onFuzzyTest: () -> Unit,
    onStateMachineTest: () -> Unit,
    onLogExport: () -> Unit,
    onReport: () -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(spacing),
    ) {
        // Fuzzy test
        IconBtn(
            onClick = onFuzzyTest,
            contentDescription = "Fuzzy Test",
            icon = Icons.Filled.Functions,
        )
        // Aligner test
        IconBtn(
            onClick = onAlignerTest,
            contentDescription = "Aligner Test",
            icon = Icons.Filled.Tag,
        )
        // State Machine test
        IconBtn(
            onClick = onStateMachineTest,
            contentDescription = "State Machine Test",
            icon = Icons.Filled.PlayArrow,
        )
        // ASR Test (sonucu durum satirinda)
        IconBtn(
            onClick = onAsrTest,
            contentDescription = "ASR Test",
            icon = Icons.Filled.Science,
        )
        // Namaz raporu: son 3 kayitta okunan ayetler (Arapca + meal + tefsir)
        IconBtn(
            onClick = onReport,
            contentDescription = "Namaz raporu",
            icon = Icons.Filled.Description,
        )
        // Log Export
        IconBtn(
            onClick = onLogExport,
            contentDescription = "Logu Paylas",
            icon = Icons.Filled.IosShare,
        )
        IconBtn(
            onClick = onSettings,
            contentDescription = "Ayarlar",
            icon = Icons.Outlined.Settings,
        )
    }
}

/**
 * Zumrut ust bant: koyu zumrut gradyan, sag ustte altin isilti, sag altta soluk cami silueti, alti yuvarlak.
 *   [logo madalyonu] DURUM (canli nokta)     [Σ # ▶ 🔬 📤 ⚙ cam daireler]
 *                   Sure adi · no (serif)
 *   ─────────── ince altin cizgi ───────────
 *   REKAT · DURUS (altin)  durum satiri (model / guven / gecikme / ASR test)           #surum · commit
 */
@Composable
private fun OrnateHeader(
    statusText: String,
    surahName: String?,
    surahNo: Int?,
    isListening: Boolean,
    motion: Float,
    info: StatusInfo,
    buildLabel: String,
    onSettings: () -> Unit,
    onAsrTest: () -> Unit,
    onAlignerTest: () -> Unit,
    onFuzzyTest: () -> Unit,
    onStateMachineTest: () -> Unit,
    onLogExport: () -> Unit,
    onReport: () -> Unit,
) {
    val style = LocalAppStyle.current
    val shape = RoundedCornerShape(bottomStart = 26.dp, bottomEnd = 26.dp)
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .shadow(14.dp, shape, ambientColor = style.shadow, spotColor = style.shadow)
            .headerBackground(style)
            .statusBarsPadding()
            .padding(start = 18.dp, end = 14.dp, top = 10.dp, bottom = 11.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            // Marka logosu: krem madalyon, ince altin halka
            BrandLogo(Modifier.size(38.dp).border(1.dp, style.gold.copy(alpha = 0.7f), CircleShape))
            Spacer(Modifier.width(11.dp))
            Column(modifier = Modifier.weight(1f).padding(end = 8.dp)) {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    LiveDot(isActive = isListening, motion = motion)
                    Text(
                        text = statusText.uppercase(),
                        fontFamily = style.label,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 9.5.sp,
                        lineHeight = 12.sp,
                        letterSpacing = 1.6.sp,
                        color = style.onHeaderDim,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                // Sure adi (ekranin ustundeki sure) + numarasi altin; liste yokken uygulama adi
                val title = buildAnnotatedString {
                    append(surahName?.takeIf { it.isNotEmpty() } ?: "Tilavet Takip")
                    if (surahNo != null) {
                        withStyle(SpanStyle(fontFamily = style.label, fontWeight = FontWeight.Bold, fontSize = 12.sp,
                            color = style.gold, letterSpacing = 0.5.sp)) { append("  ·  $surahNo") }
                    }
                }
                // Sigmazsa (uzun sure adi, ikonlar yer kapliyor) 22 → 16 sp kuculur, yine sigmazsa "…"
                var titleSp by remember(title) { mutableStateOf(22f) }
                Text(
                    text = title,
                    fontFamily = style.display,
                    fontWeight = FontWeight.SemiBold,
                    fontSize = titleSp.sp,
                    lineHeight = 28.sp,
                    color = style.onHeader,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    onTextLayout = { r -> if (r.hasVisualOverflow && titleSp > 16f) titleSp -= 1f },
                )
            }
            TestIcons(
                spacing = 6.dp,
                onSettings = onSettings,
                onAsrTest = onAsrTest,
                onAlignerTest = onAlignerTest,
                onFuzzyTest = onFuzzyTest,
                onStateMachineTest = onStateMachineTest,
                onLogExport = onLogExport,
                onReport = onReport,
            )
        }
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(
                    Brush.horizontalGradient(
                        listOf(style.gold.copy(alpha = 0.05f), style.gold.copy(alpha = 0.5f), style.gold.copy(alpha = 0.05f))
                    )
                )
        )
        Spacer(Modifier.height(7.dp))
        StatusRow(
            info = info,
            buildLabel = buildLabel,
            tagColor = style.glow,
            leadColor = style.glow,
            bodyColor = style.onHeaderDim,
            tailColor = style.onHeaderDim.copy(alpha = 0.75f),
            buildColor = style.onHeaderDim.copy(alpha = 0.55f),
            fontFamily = style.label,
            modifier = Modifier.padding(end = 4.dp),
        )
    }
}

/**
 * Sabit, tek satirlik durum alani: solda durum (model / guven / gecikme / ASR test sonucu), en sagda
 * surum + commit. Mushaf metninin ustune binmez — kendi yeri var, alt cizgiyle listeden ayrilir.
 */
@Composable
private fun StatusLine(info: StatusInfo, buildLabel: String) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    Column(modifier = Modifier.fillMaxWidth().background(palette.bg)) {
        StatusRow(
            info = info,
            buildLabel = buildLabel,
            tagColor = palette.accent,
            leadColor = palette.accent,
            bodyColor = palette.fgDim,
            tailColor = palette.fgFaded,
            buildColor = palette.fgFaded,
            fontFamily = style.label,
            modifier = Modifier
                .padding(horizontal = 18.dp)
                .padding(top = 2.dp, bottom = 7.dp),
        )
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(palette.border))
    }
}

/** Durum satirinin icerigi (klasik: kendi satirinda; zumrut: ust bandin icinde). */
@Composable
private fun StatusRow(
    info: StatusInfo,
    buildLabel: String,
    tagColor: Color,
    leadColor: Color,
    bodyColor: Color,
    tailColor: Color,
    buildColor: Color,
    fontFamily: androidx.compose.ui.text.font.FontFamily,
    modifier: Modifier = Modifier,
) {
    // Acik, kompakt stil: Text varsayilani MaterialTheme bodyLarge (lineHeight 24sp) — 10sp yazi 24sp'lik satir
    // kutusuyla sabit yukseklige sigmiyor, commit etiketi asagi kayip kesiliyordu (telefon, APK #17).
    // Sabit yukseklik de yok: buyuk sistem yazi boyutunda satir kendi yuksekligini alir.
    val lineStyle = TextStyle(
        fontFamily = fontFamily,
        fontSize = 10.sp,
        lineHeight = 13.sp,
        letterSpacing = 0.3.sp,
    )
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        modifier = modifier.fillMaxWidth(),
    ) {
        if (info.lead.isNotEmpty()) {
            Text(
                text = info.lead,
                style = lineStyle.copy(fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp),
                color = leadColor,
                maxLines = 1,
                softWrap = false,
            )
        }
        if (info.tag.isNotEmpty()) {
            Text(
                text = info.tag,
                style = lineStyle.copy(letterSpacing = 0.6.sp),
                color = tagColor,
                maxLines = 1,
                softWrap = false,
            )
        }
        // Govde: yon icerikten (Arapca → sagdan sola), sigmazsa kendi icinde kisalir
        Text(
            text = info.body,
            style = lineStyle.copy(textDirection = TextDirection.Content),
            color = bodyColor,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        if (info.tail.isNotEmpty()) {
            Text(
                text = info.tail,
                style = lineStyle,
                color = tailColor,
                maxLines = 1,
                softWrap = false,
            )
        }
        if (buildLabel.isNotEmpty()) {
            Text(
                text = buildLabel,
                style = lineStyle.copy(fontSize = 9.sp, lineHeight = 12.sp),
                color = buildColor,
                maxLines = 1,
                softWrap = false,
            )
        }
    }
}

@Composable
private fun TestPanel(
    title: String,
    stateText: String,
    resultText: String,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val palette = LocalAppPalette.current

    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 18.dp)
            .background(palette.bgElev, RoundedCornerShape(12.dp))
            .border(1.dp, palette.borderStrong, RoundedCornerShape(12.dp))
            .clickable(onClick = onDismiss)
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
            .heightIn(max = 480.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = title,
                fontFamily = JetBrainsMonoFamily,
                fontSize = 10.sp,
                color = palette.accent,
                letterSpacing = 1.0.sp,
                modifier = Modifier.weight(1f),
            )
            Text(
                text = "dokun: kapat",
                fontFamily = JetBrainsMonoFamily,
                fontSize = 9.sp,
                color = palette.fgFaded,
            )
        }

        if (stateText.isNotEmpty()) {
            Spacer(Modifier.height(6.dp))
            Text(
                text = stateText,
                fontFamily = JetBrainsMonoFamily,
                fontSize = 11.sp,
                color = palette.fgDim,
            )
        }

        if (resultText.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Text(
                text = resultText,
                fontFamily = JetBrainsMonoFamily,
                fontSize = 11.sp,
                color = palette.fg,
                lineHeight = 16.sp,
            )
        }
    }
}

@Composable
private fun Footer(
    audioLevel: Float,
    isListening: Boolean,
    label: String,
    confidence: Int?,
    tentative: Boolean,
    motion: Float,
    onToggleMic: () -> Unit,
    simActive: Boolean,
    simRecordings: List<SimRecording>,
    onSimMenuOpen: () -> Unit,
    onSimRecording: (File) -> Unit,
    onSimPickFile: () -> Unit,
    onSimStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    var simMenu by remember { mutableStateOf(false) }

    val surahLabel = label.ifEmpty { "—" } + if (label.isNotEmpty() && tentative) " (aday)" else ""
    val confidenceLabel = confidence?.let { "%$it" } ?: "—"

    // Zumrut: golgeli beyaz alt bar (ustu yuvarlak, ust kenarda ince altin cizgi); klasik: listeye karisan gradyan
    val barShape = RoundedCornerShape(topStart = 26.dp, topEnd = 26.dp)
    val container = if (style.ornate) Modifier
        // clip yok: mikrofonun dalga halkasi barin ust kenarindan tasabilir
        .shadow(18.dp, barShape, clip = false, ambientColor = style.shadow, spotColor = style.shadow)
        .background(palette.bgElev, barShape)
        .drawBehind {
            val inset = 26.dp.toPx()
            drawLine(
                Brush.horizontalGradient(
                    listOf(style.gold.copy(alpha = 0f), style.gold.copy(alpha = 0.55f), style.gold.copy(alpha = 0f)),
                    startX = inset, endX = size.width - inset,
                ),
                Offset(inset, 0.5f), Offset(size.width - inset, 0.5f), strokeWidth = 1.dp.toPx(),
            )
        }
        .navigationBarsPadding()
        .padding(start = 22.dp, end = 18.dp, top = 12.dp, bottom = 12.dp)
    else Modifier
        .background(
            Brush.verticalGradient(
                0f to Color.Transparent,
                0.4f to palette.bg.copy(alpha = 0.92f),
                1f to palette.bg,
            )
        )
        .navigationBarsPadding()
        .padding(horizontal = 18.dp)
        .padding(top = 16.dp, bottom = 18.dp)

    Row(
        modifier = modifier
            .fillMaxWidth()
            .then(container),
        verticalAlignment = if (style.ornate) Alignment.CenterVertically else Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(if (style.ornate) 14.dp else 16.dp),
    ) {
        if (style.ornate) {
            OrnateFooterInfo(
                surahLabel = surahLabel,
                confidenceLabel = confidenceLabel,
                isListening = isListening,
                audioLevel = audioLevel,
                palette = palette,
                style = style,
                modifier = Modifier.weight(1f),
            )
        } else {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("SURE", fontFamily = style.label, fontSize = 10.sp,
                        color = palette.fgFaded, letterSpacing = 0.6.sp)
                    Spacer(Modifier.width(10.dp))
                    Text(surahLabel, fontFamily = style.label, fontSize = 10.sp,
                        color = if (isListening) palette.fg else palette.fgDim,
                        letterSpacing = 0.4.sp, maxLines = 1)
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("GÜVEN", fontFamily = style.label, fontSize = 10.sp,
                        color = palette.fgFaded, letterSpacing = 0.6.sp)
                    Spacer(Modifier.width(10.dp))
                    Text(confidenceLabel, fontFamily = style.label, fontSize = 10.sp,
                        color = if (isListening) palette.fg else palette.fgDim)
                    Spacer(Modifier.weight(1f))
                    Text("SES", fontFamily = style.label, fontSize = 10.sp,
                        color = palette.fgFaded, letterSpacing = 0.6.sp)
                    Spacer(Modifier.width(10.dp))
                    AudioLevelBar(level = if (isListening) audioLevel else 0f, modifier = Modifier.width(50.dp))
                }
            }
        }

        // Simulasyon: kayitli sesi mikrofon gibi oynat (menu: son oturum kayitlari + telefondan dosya)
        Box(modifier = Modifier.padding(bottom = if (style.ornate) 0.dp else 6.dp)) {   // 44dp buton, 56dp mikrofonla ortali
            SimButton(
                simActive = simActive,
                onClick = {
                    if (simActive) {
                        onSimStop()
                    } else {
                        onSimMenuOpen()
                        simMenu = true
                    }
                },
            )
            DropdownMenu(
                expanded = simMenu,
                onDismissRequest = { simMenu = false },
                modifier = Modifier.background(palette.bgElev),
            ) {
                Text(
                    text = "SİMÜLASYON — KAYITLI SESİ OYNAT",
                    fontFamily = style.label,
                    fontWeight = if (style.ornate) FontWeight.Bold else null,
                    fontSize = 9.sp,
                    letterSpacing = (0.8f * style.labelTracking).sp,
                    color = if (style.ornate) style.goldInk else palette.accent,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                )
                for (r in simRecordings) {
                    DropdownMenuItem(
                        text = {
                            Text(
                                text = "${recordingTitle(r.file)} · ${mmss(r.durationSec)}",
                                fontFamily = style.label,
                                fontSize = 12.sp,
                                color = palette.fg,
                            )
                        },
                        onClick = {
                            simMenu = false
                            onSimRecording(r.file)
                        },
                    )
                }
                DropdownMenuItem(
                    text = {
                        Text(
                            text = "Telefondan dosya seç…",
                            fontFamily = style.label,
                            fontSize = 12.sp,
                            color = palette.fg,
                        )
                    },
                    leadingIcon = {
                        Icon(
                            Icons.Filled.FolderOpen, contentDescription = null, tint = palette.fgDim,
                            modifier = Modifier.size(18.dp),
                        )
                    },
                    onClick = {
                        simMenu = false
                        onSimPickFile()
                    },
                )
            }
        }

        MicButton(isListening = isListening, motion = motion, onToggle = onToggleMic)
    }
}

/**
 * Zumrut alt bar bilgisi. Dinlerken: altin buyuk harf etiketler (SURE / GÜVEN / SES) + koyu degerler. Bostayken
 * (tirelerle dolu bilgi yerine) marka dili: "Dinle ve anla" + "İmam okur, sen anlamını takip et."
 */
@Composable
private fun OrnateFooterInfo(
    surahLabel: String,
    confidenceLabel: String,
    isListening: Boolean,
    audioLevel: Float,
    palette: AppPalette,
    style: AppStyle,
    modifier: Modifier = Modifier,
) {
    val labelStyle = TextStyle(
        fontFamily = style.label, fontWeight = FontWeight.Bold, fontSize = 9.sp, lineHeight = 12.sp,
        letterSpacing = 1.8.sp, color = style.goldInk,
    )
    val valueColor = if (isListening) palette.fg else palette.fgDim
    if (!isListening) {
        Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                "Dinle ve anla", fontFamily = style.display, fontWeight = FontWeight.SemiBold, fontSize = 18.sp,
                lineHeight = 23.sp, color = style.headerTop, maxLines = 1,
            )
            Text(
                "İmam okur, sen anlamını takip et.", fontFamily = style.label, fontWeight = FontWeight.Medium,
                fontSize = 11.5.sp, lineHeight = 15.sp, color = style.olive, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        return
    }
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("SURE", style = labelStyle)
            Spacer(Modifier.width(10.dp))
            Text(
                surahLabel, fontFamily = style.label, fontWeight = FontWeight.SemiBold, fontSize = 13.sp,
                lineHeight = 16.sp, color = valueColor, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("GÜVEN", style = labelStyle)
            Spacer(Modifier.width(10.dp))
            Text(
                confidenceLabel, fontFamily = style.label, fontWeight = FontWeight.Bold, fontSize = 13.sp,
                lineHeight = 16.sp, color = if (isListening) palette.accent else palette.fgDim,
            )
            Spacer(Modifier.weight(1f))
            Text("SES", style = labelStyle)
            Spacer(Modifier.width(8.dp))
            AudioLevelBar(level = if (isListening) audioLevel else 0f, modifier = Modifier.width(54.dp))
        }
    }
}
