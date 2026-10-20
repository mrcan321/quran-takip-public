package com.tilavet.takip.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.tilavet.takip.ui.theme.AppPalette
import com.tilavet.takip.ui.theme.AppStyle
import kotlin.math.cos
import kotlin.math.sin

/*
 * Zumrut temasinin susleri — hepsi kodla cizilir (resim dosyasi yok, her boyutta keskin):
 *   - ArchEmblem: logodaki sivri (sogan uclu) kemer + 4 koseli yildiz + altta acik kitap kivrimlari
 *     (sure basligi, ayarlar, ezan penceresi)
 *   - drawMosqueSkyline: kubbeler + minareler silueti (ust bandin sag alti, cok soluk)
 *   - starPatternPath: 8 koseli yildiz + hac deseni (Islami geometrik; ust bantta cok soluk altin)
 *   - OrnamentDivider: "———✦———" altin ayrac
 *   - ArchTopShape: ustu kemerli kart (sure basligi; mihrap / pencere kemeri)
 *   - ornateBackground / headerBackground: krem zemin + gun batimi isiltisi + altta soluk kemer dizisi (mihrap
 *     cagrisimi), koyu zumrut bant + desen + silueti
 */

/** Hilal: dis daireden kaydirilmis daire cikarilir (zemin rengine bagli degil). */
private fun crescentPath(cx: Float, cy: Float, r: Float): Path {
    val outer = Path().apply { addOval(Rect(cx - r, cy - r, cx + r, cy + r)) }
    val cut = Path().apply {
        val rc = r * 0.82f
        val ox = cx + r * 0.42f
        val oy = cy - r * 0.18f
        addOval(Rect(ox - rc, oy - rc, ox + rc, oy + rc))
    }
    return Path().apply { op(outer, cut, PathOperation.Difference) }
}

/**
 * Logodaki kemer (orta cizgi): dikey bacaklar, omuzdan once disa siskin sonra ice kivrilan (sogan / ogee) tepe.
 * [left]..[right] bacaklar, [bottom] taban, [spring] omuz (kivrimin basladigi yer), [apex] tepe ucu.
 */
private fun ogeeArchPath(left: Float, right: Float, bottom: Float, spring: Float, apex: Float): Path {
    val w = right - left
    val cx = left + w / 2f
    val rise = spring - apex
    return Path().apply {
        moveTo(left, bottom)
        lineTo(left, spring)
        cubicTo(left, spring - rise * 0.62f, cx - w * 0.17f, spring - rise * 0.78f, cx - w * 0.17f * 0.35f, apex + rise * 0.14f)
        cubicTo(cx - w * 0.02f, apex + rise * 0.06f, cx, apex + rise * 0.02f, cx, apex)
        cubicTo(cx, apex + rise * 0.02f, cx + w * 0.02f, apex + rise * 0.06f, cx + w * 0.17f * 0.35f, apex + rise * 0.14f)
        cubicTo(cx + w * 0.17f, spring - rise * 0.78f, right, spring - rise * 0.62f, right, spring)
        lineTo(right, bottom)
    }
}

/**
 * Marka amblemi (logodan): sivri kemer, icinde 4 koseli yildiz, altta acik kitabin iki kivrimi.
 * [color] kemer ve kitap, [fill] yildiz (null = [color]).
 */
@Composable
fun ArchEmblem(color: Color, modifier: Modifier = Modifier, fill: Color? = null) {
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val stroke = (w * 0.11f).coerceAtLeast(1.2f)
        val bookH = h * 0.20f
        val left = w * 0.17f
        val right = w * 0.83f
        val bottom = h - bookH - stroke * 0.3f
        val apex = stroke * 0.6f
        val spring = apex + (bottom - apex) * 0.40f
        drawPath(ogeeArchPath(left, right, bottom, spring, apex), color, style = Stroke(stroke, cap = StrokeCap.Butt, join = StrokeJoin.Round))
        // Yildiz: kemerin ic tepesinde
        drawPath(sparklePath(Offset(w / 2f, spring + (bottom - spring) * 0.18f), w * 0.15f), fill ?: color)
        // Acik kitap: ortada birlesen iki kivrim (uclar kalin)
        val top = h - bookH
        val page = Path().apply {
            moveTo(0f, top + bookH * 0.05f)
            cubicTo(w * 0.22f, top, w * 0.40f, top + bookH * 0.35f, w / 2f, h)
            cubicTo(w * 0.60f, top + bookH * 0.35f, w * 0.78f, top, w, top + bookH * 0.05f)
            lineTo(w, top + bookH * 0.48f)
            cubicTo(w * 0.80f, top + bookH * 0.45f, w * 0.62f, top + bookH * 0.70f, w / 2f, h)
            cubicTo(w * 0.38f, top + bookH * 0.70f, w * 0.20f, top + bookH * 0.45f, 0f, top + bookH * 0.48f)
            close()
        }
        drawPath(page, color)
    }
}

/**
 * Cami silueti: ortada sogan kubbe, iki yanda kucuk kubbeler, iki minare. [cx] merkez, [baseY] taban, [u] birim
 * (silueti olcekler; toplam genislik ~230u, yukseklik ~150u).
 */
fun DrawScope.drawMosqueSkyline(color: Color, cx: Float, baseY: Float, u: Float) {
    // Govde
    drawRect(color, Offset(cx - 96 * u, baseY - 22 * u), Size(192 * u, 22 * u))
    // Orta kubbe kasnagi + sogan kubbe
    drawRect(color, Offset(cx - 38 * u, baseY - 40 * u), Size(76 * u, 18 * u))
    val dome = Path().apply {
        moveTo(cx - 40 * u, baseY - 40 * u)
        cubicTo(cx - 44 * u, baseY - 78 * u, cx - 12 * u, baseY - 84 * u, cx, baseY - 104 * u)
        cubicTo(cx + 12 * u, baseY - 84 * u, cx + 44 * u, baseY - 78 * u, cx + 40 * u, baseY - 40 * u)
        close()
    }
    drawPath(dome, color)
    drawLine(color, Offset(cx, baseY - 104 * u), Offset(cx, baseY - 118 * u), strokeWidth = 2.2f * u)
    drawPath(crescentPath(cx, baseY - 122 * u, 4.2f * u), color)
    // Yan kubbeler
    for (s in listOf(-1f, 1f)) {
        val x = cx + s * 62 * u
        drawArc(color, 180f, 180f, true, Offset(x - 22 * u, baseY - 22 * u - 22 * u), Size(44 * u, 44 * u))
        drawLine(color, Offset(x, baseY - 44 * u), Offset(x, baseY - 52 * u), strokeWidth = 1.6f * u)
    }
    // Minareler: govde, iki serefe, kulah, alem
    for (s in listOf(-1f, 1f)) {
        val x = cx + s * 108 * u
        val top = baseY - 140 * u
        drawRect(color, Offset(x - 4.5f * u, top), Size(9 * u, 140 * u))
        for (b in listOf(0.38f, 0.66f)) {
            val y = baseY - 140 * u * b
            drawRect(color, Offset(x - 7.5f * u, y - 3 * u), Size(15 * u, 4.5f * u))
        }
        val cone = Path().apply {
            moveTo(x - 6 * u, top)
            lineTo(x, top - 24 * u)
            lineTo(x + 6 * u, top)
            close()
        }
        drawPath(cone, color)
        drawLine(color, Offset(x, top - 24 * u), Offset(x, top - 31 * u), strokeWidth = 1.4f * u)
    }
}

/**
 * 8 koseli yildiz + hac deseni: yildizlar kare izgarada uc uca degerek dizilir, aralarda hac (arti) bosluklari
 * kendiliginden olusur. [r] yildiz yaricapi (izgara araligi 2r). Alani tasan yildizlar da cizilir (kenarlar kesik).
 */
fun starPatternPath(width: Float, height: Float, r: Float): Path {
    val path = Path()
    val rIn = r * 0.7654f   // cos45 / cos22.5: iki kare ust uste → 16 kose
    val step = 2f * r
    var cy = 0f
    while (cy <= height + r) {
        var cx = 0f
        while (cx <= width + r) {
            for (k in 0 until 16) {
                val a = Math.toRadians(k * 22.5 - 90.0)
                val rr = if (k % 2 == 0) r else rIn
                val x = cx + (rr * cos(a)).toFloat()
                val y = cy + (rr * sin(a)).toFloat()
                if (k == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            path.close()
            cx += step
        }
        cy += step
    }
    return path
}

/** 4 koseli yildiz (✦). */
private fun sparklePath(c: Offset, r: Float): Path = Path().apply {
    val k = r * 0.28f
    moveTo(c.x, c.y - r)
    quadraticBezierTo(c.x + k, c.y - k, c.x + r, c.y)
    quadraticBezierTo(c.x + k, c.y + k, c.x, c.y + r)
    quadraticBezierTo(c.x - k, c.y + k, c.x - r, c.y)
    quadraticBezierTo(c.x - k, c.y - k, c.x, c.y - r)
    close()
}

/** Altin ayrac: iki yana solan ince cizgiler + ortada yildiz. */
@Composable
fun OrnamentDivider(color: Color, modifier: Modifier = Modifier, width: Dp = 150.dp) {
    Canvas(modifier = modifier.width(width).height(12.dp)) {
        val y = size.height / 2f
        val cx = size.width / 2f
        val gap = size.height * 0.95f
        drawLine(
            Brush.horizontalGradient(listOf(color.copy(alpha = 0f), color), startX = 0f, endX = cx - gap),
            Offset(0f, y), Offset(cx - gap, y), strokeWidth = 1.2f,
        )
        drawLine(
            Brush.horizontalGradient(listOf(color, color.copy(alpha = 0f)), startX = cx + gap, endX = size.width),
            Offset(cx + gap, y), Offset(size.width, y), strokeWidth = 1.2f,
        )
        drawPath(sparklePath(Offset(cx, y), size.height * 0.5f), color)
    }
}

/**
 * Ustu kemerli kart: omuzlardan ortadaki tepeye "kavsara" (S egrili sivri kemer), alt koseler yuvarlak.
 * [rise] kemerin omuz cizgisinden yuksekligi.
 */
class ArchTopShape(private val rise: Dp, private val corner: Dp) : Shape {
    override fun createOutline(size: Size, layoutDirection: LayoutDirection, density: Density): Outline {
        val r = with(density) { corner.toPx() }
        val a = with(density) { rise.toPx() }
        val w = size.width
        val h = size.height
        val path = Path().apply {
            moveTo(0f, a + r)
            quadraticBezierTo(0f, a, r, a)
            lineTo(w * 0.30f, a)
            cubicTo(w * 0.41f, a, w * 0.46f, a * 0.45f, w * 0.5f, 0f)
            cubicTo(w * 0.54f, a * 0.45f, w * 0.59f, a, w * 0.70f, a)
            lineTo(w - r, a)
            quadraticBezierTo(w, a, w, a + r)
            lineTo(w, h - r)
            quadraticBezierTo(w, h, w - r, h)
            lineTo(r, h)
            quadraticBezierTo(0f, h, 0f, h - r)
            close()
        }
        return Outline.Generic(path)
    }
}

/**
 * Krem kagit zemin: ustten alta hafif koyulasan krem, sag ustte gun batimi isiltisi, altta cok soluk kemer dizisi
 * (cami ici / mihrap cagrisimi; yukari dogru kaybolur — metnin arkasinda neredeyse gorunmez).
 */
fun Modifier.ornateBackground(palette: AppPalette, style: AppStyle): Modifier = drawWithCache {
    val arches = Path()
    val n = 3
    val aw = size.width / n
    val base = size.height
    val archTop = size.height * 0.52f
    for (i in 0 until n) {
        val l = i * aw + aw * 0.12f
        val r = (i + 1) * aw - aw * 0.12f
        val spring = archTop + (base - archTop) * 0.30f
        arches.addPath(ogeeArchPath(l, r, base, spring, archTop))
        val inset = aw * 0.07f
        arches.addPath(ogeeArchPath(l + inset, r - inset, base, spring + inset * 0.6f, archTop + inset * 1.6f))
    }
    // Tepeler de secilsin (yoksa sadece dikey bacaklar "cizgi" gibi gorunuyor); en ustte yumusak baslangic
    val archBrush = Brush.verticalGradient(
        0f to style.gold.copy(alpha = 0f),
        0.10f to style.gold.copy(alpha = 0.13f),
        1f to style.gold.copy(alpha = 0.07f),
        startY = archTop - 8.dp.toPx(), endY = base,
    )
    val stroke = Stroke(1.dp.toPx())
    val bg = Brush.verticalGradient(listOf(palette.bg, style.bgBottom))
    val glow = Brush.radialGradient(
        listOf(style.glow.copy(alpha = 0.28f), style.glow.copy(alpha = 0f)),
        center = Offset(size.width * 0.92f, 0f),
        radius = size.width * 0.95f,
    )
    onDrawBehind {
        drawRect(bg)
        drawRect(glow)
        drawPath(arches, archBrush, style = stroke)
    }
}

/**
 * Koyu zumrut ust bant: dikey gradyan, cok soluk altin 8 koseli yildiz deseni (soldan saga belirginlesir — baslik
 * okunakli kalsin), sag ustte altin isilti, sag altta soluk cami silueti.
 */
fun Modifier.headerBackground(style: AppStyle): Modifier = drawWithCache {
    val pattern = starPatternPath(size.width, size.height, 14.dp.toPx())
    val patternBrush = Brush.horizontalGradient(
        listOf(style.gold.copy(alpha = 0.02f), style.gold.copy(alpha = 0.11f)), startX = size.width * 0.15f, endX = size.width,
    )
    val stroke = Stroke(0.8.dp.toPx())
    val bg = Brush.verticalGradient(listOf(style.headerTop, style.headerBottom))
    val glow = Brush.radialGradient(
        listOf(style.glow.copy(alpha = 0.22f), style.glow.copy(alpha = 0f)),
        center = Offset(size.width * 0.86f, size.height * 0.05f),
        radius = size.width * 0.55f,
    )
    val u = size.height / 165f
    onDrawBehind {
        drawRect(bg)
        drawPath(pattern, patternBrush, style = stroke)
        drawRect(glow)
        drawMosqueSkyline(style.skyline.copy(alpha = 0.7f), cx = size.width * 0.80f, baseY = size.height + 2f, u = u)
    }
}

/** Kucuk altin harf etiket araligi: klasik temada eskisi gibi, zumrutte daha genis. */
fun AppStyle.tracking(base: Float): Float = base * labelTracking
