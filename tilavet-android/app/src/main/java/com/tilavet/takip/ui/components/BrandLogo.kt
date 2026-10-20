package com.tilavet.takip.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.res.painterResource
import com.tilavet.takip.R

/**
 * Marka logosu madalyon olarak (krem daire + yesil halka + kemer/yildiz/N + gozluk + kitap): uygulama ikonunun
 * kendisi (res/drawable/ic_launcher_*, tilavet-android/tools/gen_launcher_icon.py). Ikonun 108'lik alaninda halka
 * r=30 — 66'lik daire gorunecek sekilde buyutulup kirpilir (halkanin disinda ince krem pay kalir).
 *
 * (Masaustu Compose duzeneginde ayni XML dosyadan yuklenir — bu dosya orada stub'lanir.)
 */
@Composable
fun BrandLogo(modifier: Modifier = Modifier) {
    Box(modifier.clip(CircleShape)) {
        Box(Modifier.fillMaxSize().scale(108f / 66f)) {
            Image(painterResource(R.drawable.ic_launcher_background), contentDescription = null, modifier = Modifier.fillMaxSize())
            Image(painterResource(R.drawable.ic_launcher_foreground), contentDescription = "Logo", modifier = Modifier.fillMaxSize())
        }
    }
}
