package com.tilavet.takip.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.UnfoldMore
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tilavet.takip.ui.theme.LocalAppPalette
import com.tilavet.takip.ui.theme.LocalAppStyle
import kotlin.math.roundToInt

/** Kaydirma cubugunun genisligi: liste sagdan bu kadar bosluk birakir (ayet kartlari cubugun altina girmez). */
val SCROLLBAR_WIDTH: Dp = 34.dp
private val THUMB_HEIGHT: Dp = 76.dp

/**
 * Mushaf listesinin saginda boydan boya kalin kaydirma cubugu + tutulup cekilen kaydirma tutamagi (ikonlu). Kullanici
 * (30.10): "ekrani asagi cekerken bir dugmeye yanlislikla basma ihtimali var; en sagda boydan boya kalin bir scroll
 * dikmesi ve gorunur bir kaydirma ikonu olsun, tutup cekerek kaydirayim".
 *
 * - Cubugun herhangi bir yerinden surukleme (dokunup kaydirma esigini gecince) tutamagi parmagin altina alir; liste
 *   tutamagin konumuna gore satira atlar (114 sure basligi + 6236 ayet, satir sirasiyla orantili). Sadece dokunmak bir
 *   sey yapmaz (yanlislikla dokunma listeyi oynatmaz).
 * - Surukleme surerken solda sure / ayet etiketi ("Bakara 2:255").
 * - [onUserDrag]: sese gore takip durur (elle kaydirma gibi; ok butonuyla devam).
 *
 * [modifier] tum liste alanini kaplamali (etiket solda cizilir); dokunmalar sadece sagdaki cubukta alinir.
 */
@Composable
fun QuranScrollbar(
    listState: LazyListState,
    itemCount: Int,
    labelOf: (Int) -> String,
    onUserDrag: () -> Unit,
    modifier: Modifier = Modifier,
) {
    if (itemCount <= 1) return
    val palette = LocalAppPalette.current
    val style = LocalAppStyle.current
    val density = LocalDensity.current
    var trackPx by remember { mutableIntStateOf(0) }
    var dragging by remember { mutableStateOf(false) }
    var dragFraction by remember { mutableFloatStateOf(0f) }
    var target by remember { mutableIntStateOf(-1) }
    val last = itemCount - 1

    // Listenin konumu (0..1): ilk gorunen satir + o satirin ne kadari gecildi
    val listFraction by remember(listState, itemCount) {
        derivedStateOf {
            val first = listState.firstVisibleItemIndex
            val size = listState.layoutInfo.visibleItemsInfo.firstOrNull()?.size ?: 1
            val within = listState.firstVisibleItemScrollOffset.toFloat() / size.coerceAtLeast(1)
            ((first + within) / last).coerceIn(0f, 1f)
        }
    }
    // Surukleme hedefine atla (yeni hedef eskisini iptal eder)
    LaunchedEffect(target) {
        if (target >= 0) listState.scrollToItem(target)
    }
    val fraction = if (dragging) dragFraction else listFraction
    val thumbPx = with(density) { THUMB_HEIGHT.toPx() }
    val thumbY = ((trackPx - thumbPx).coerceAtLeast(0f) * fraction)
    val thumbYDp = with(density) { thumbY.toDp() }

    Box(modifier = modifier) {
        // Cubuk (dokunma alani): boydan boya, sagda
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .width(SCROLLBAR_WIDTH)
                .fillMaxHeight()
                .onSizeChanged { trackPx = it.height }
                .pointerInput(itemCount) {
                    fun frac(y: Float): Float =
                        ((y - thumbPx / 2f) / (size.height - thumbPx).coerceAtLeast(1f)).coerceIn(0f, 1f)
                    detectVerticalDragGestures(
                        onDragStart = { o ->
                            dragging = true
                            onUserDrag()
                            dragFraction = frac(o.y)
                            target = (dragFraction * last).roundToInt()
                        },
                        onDragEnd = { dragging = false },
                        onDragCancel = { dragging = false },
                    ) { change, _ ->
                        change.consume()
                        dragFraction = frac(change.position.y)
                        target = (dragFraction * last).roundToInt()
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
        // Surukleme etiketi: tutamagin solunda, sure / ayet
        if (dragging) {
            val idx = (dragFraction * last).roundToInt().coerceIn(0, last)
            Text(
                text = labelOf(idx),
                fontFamily = style.label,
                fontWeight = FontWeight.Bold,
                fontSize = 15.sp,
                color = palette.bg,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(end = SCROLLBAR_WIDTH + 10.dp)
                    .offset(y = thumbYDp + THUMB_HEIGHT / 2 - 20.dp)
                    .shadow(6.dp, RoundedCornerShape(12.dp))
                    .background(palette.accent, RoundedCornerShape(12.dp))
                    .padding(horizontal = 14.dp, vertical = 9.dp),
            )
        }
    }
}
