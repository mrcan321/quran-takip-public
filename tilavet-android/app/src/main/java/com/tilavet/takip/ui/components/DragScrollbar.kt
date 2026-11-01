package com.tilavet.takip.ui.components

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import kotlin.math.roundToInt

/** Kaydirma cubugunun genisligi: icerik sagdan bu kadar bosluk birakir (cubugun altina girmez). */
val SCROLLBAR_WIDTH: Dp = 34.dp
private val THUMB_HEIGHT: Dp = 76.dp

/**
 * Ayarlar sayfasinin saginda boydan boya kalin kaydirma cubugu + tutulup cekilen kaydirma tutamagi (ikonlu). Kullanici
 * (30.10 / 01.11): "ayarlar kisminda asagi cekerken bir dugmeye yanlislikla basma ihtimali var; en sagda boydan boya kalin
 * bir scroll dikmesi ve gorunur bir kaydirma ikonu olsun, tutup cekerek kaydirayim" (APK #133'te yanlislikla ana ekrandaki
 * Mushaf listesine konmustu, oradan kaldirildi).
 *
 * - Cubugun herhangi bir yerinden surukleme (dokunup kaydirma esigini gecince) tutamagi parmagin altina alir, sayfa
 *   tutamagin konumuna gore kayar. Sadece dokunmak bir sey yapmaz (yanlislikla dokunma sayfayi oynatmaz).
 * - Cubuk suruklemeyi kendisi tuketir: alt sayfa (ModalBottomSheet) asagi cekilip kapanmaz.
 * - Icerik sigiyorsa (kaydirma yok) cizilmez.
 *
 * [modifier] kaydirilan alanin tamamini kaplamali (ornegin Box icinde matchParentSize); cubuk sagda.
 */
@Composable
fun DragScrollbar(scrollState: ScrollState, modifier: Modifier = Modifier) {
    val max = scrollState.maxValue
    if (max <= 0 || max == Int.MAX_VALUE) return
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val density = LocalDensity.current
    var trackPx by remember { mutableIntStateOf(0) }
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableFloatStateOf(0f) }
    var target by remember { mutableIntStateOf(-1) }

    // Surukleme hedefine kaydir (yeni hedef eskisini iptal eder)
    LaunchedEffect(target) {
        if (target >= 0) scrollState.scrollTo(target)
    }
    val fraction = if (dragging) dragFraction else (scrollState.value.toFloat() / max).coerceIn(0f, 1f)
    val thumbPx = with(density) { THUMB_HEIGHT.toPx() }
    val thumbYDp = with(density) { ((trackPx - thumbPx).coerceAtLeast(0f) * fraction).toDp() }

    Box(modifier = modifier) {
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .width(SCROLLBAR_WIDTH)
                .fillMaxHeight()
                .onSizeChanged { trackPx = it.height }
                .pointerInput(Unit) {
                    fun frac(y: Float): Float =
                        ((y - thumbPx / 2f) / (size.height - thumbPx).coerceAtLeast(1f)).coerceIn(0f, 1f)
                    detectVerticalDragGestures(
                        onDragStart = { o ->
                            dragging = true
                            dragFraction = frac(o.y)
                            target = (dragFraction * scrollState.maxValue).roundToInt()
                        },
                        onDragEnd = { dragging = false },
                        onDragCancel = { dragging = false },
                    ) { change, _ ->
                        change.consume()
                        dragFraction = frac(change.position.y)
                        target = (dragFraction * scrollState.maxValue).roundToInt()
                    }
                },
        ) {
            // Dikme
            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .width(12.dp)
                    .fillMaxHeight()
                    .padding(vertical = 4.dp)
                    .background(palette.fgFaded.copy(alpha = 0.22f), RoundedCornerShape(6.dp)),
            )
            // Tutamak (ikonlu)
            val thumbShape = RoundedCornerShape(15.dp)
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .offset(y = thumbYDp)
                    .width(SCROLLBAR_WIDTH - 4.dp)
                    .height(THUMB_HEIGHT)
                    .shadow(if (dragging) 8.dp else 4.dp, thumbShape)
                    .background(palette.accent, thumbShape)
                    .then(
                        if (style.ornate) Modifier.border(1.dp, style.gold.copy(alpha = 0.8f), thumbShape)
                        else Modifier
                    ),
            ) {
                Icon(
                    imageVector = Icons.Filled.UnfoldMore,
                    contentDescription = "Kaydırma tutamağı",
                    tint = palette.bg,
                    modifier = Modifier.size(24.dp),
                )
            }
        }
    }
}
