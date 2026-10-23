package com.tilavet.takip.util

import android.annotation.SuppressLint
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioManager
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings

/**
 * Telefonun kendisiyle ilgili ayarlar: arka planda calisma izni (pil kisitlamasi) ve Ayarlar → MUTE ON RECORDING
 * (dinlerken telefonu sessize al, dinleme bitince eski haline dondur).
 *
 * Kullanici: "telefondaki app arka planda surekli acik kalabilsin, gerekirse izin istesin, arka plan izni istesin yoksa
 * uyarsin"; "mikrofon tusuna basinca telefonu sessize alsin, mikrofon ile aktif dinleme yapmiyorsa telefonu yine sesliye
 * alsin; ayarlarda on / off, adi mute on recording".
 */
object PhoneControl {
    private const val TAG = "PhoneControl"
    private const val PREFS = "telefon"
    /** Sessize almadan onceki zil modu (bizim aldigimizi gosterir; uygulama kapansa da bir sonraki acilista geri alinir). */
    private const val KEY_PREV = "zil_onceki"
    /** Bizim ayarladigimiz mod: geri alirken telefon hala bu moddaysa eskiye doner (kullanici elle degistirdiyse dokunmaz). */
    private const val KEY_SET = "zil_bizim"

    // ------------------------------------------------------------------ arka planda calisma

    /** Pil kisitlamasindan muaf mi (Samsung: Uygulama → Pil → Kısıtlanmamış). */
    fun isBackgroundUnrestricted(ctx: Context): Boolean {
        val pm = ctx.getSystemService(PowerManager::class.java) ?: return true
        return pm.isIgnoringBatteryOptimizations(ctx.packageName)
    }

    /** Android'in "arka planda calismaya izin ver" penceresi (olmazsa uygulamanin pil ayarlari). */
    @SuppressLint("BatteryLife")
    fun requestBackgroundUnrestricted(ctx: Context) {
        try {
            ctx.startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Throwable) {
            SessionLog.w(TAG, "pil izni penceresi acilamadi: ${e.message}")
            openAppSettings(ctx)
        }
    }

    fun openAppSettings(ctx: Context) {
        try {
            ctx.startActivity(
                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Throwable) {
            SessionLog.w(TAG, "uygulama ayarlari acilamadi: ${e.message}")
        }
    }

    // ------------------------------------------------------------------ mute on recording

    /** Rahatsiz Etmeyin erisimi (telefonu tam sessize almak icin gerekli; yoksa titresime alinir). */
    fun hasDndAccess(ctx: Context): Boolean =
        ctx.getSystemService(NotificationManager::class.java)?.isNotificationPolicyAccessGranted == true

    fun requestDndAccess(ctx: Context) {
        try {
            ctx.startActivity(Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (e: Throwable) {
            SessionLog.w(TAG, "Rahatsiz Etmeyin ayari acilamadi: ${e.message}")
            openAppSettings(ctx)
        }
    }

    private fun modeName(m: Int) = when (m) {
        AudioManager.RINGER_MODE_SILENT -> "sessiz"
        AudioManager.RINGER_MODE_VIBRATE -> "titresim"
        AudioManager.RINGER_MODE_NORMAL -> "sesli"
        else -> "$m"
    }

    /**
     * Dinleme basladi: telefonu sessize al (Rahatsiz Etmeyin erisimi yoksa titresime — Android tam sessizi izinsiz
     * vermiyor). Onceki mod saklanir. Donus: log satiri.
     */
    fun mute(ctx: Context): String {
        val am = ctx.getSystemService(AudioManager::class.java) ?: return "ses servisi yok"
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.contains(KEY_PREV)) return "zaten sessize alinmis"
        val prev = am.ringerMode
        if (prev == AudioManager.RINGER_MODE_SILENT) return "telefon zaten sessiz"
        val target = if (hasDndAccess(ctx)) AudioManager.RINGER_MODE_SILENT else AudioManager.RINGER_MODE_VIBRATE
        if (prev == target) return "telefon zaten ${modeName(prev)} (Rahatsız Etmeyin izni yok, tam sessize alınamadı)"
        val set = try {
            am.ringerMode = target
            target
        } catch (e: SecurityException) {
            try {
                am.ringerMode = AudioManager.RINGER_MODE_VIBRATE
                AudioManager.RINGER_MODE_VIBRATE
            } catch (e2: Throwable) {
                return "sessize alinamadi: ${e2.message}"
            }
        } catch (e: Throwable) {
            return "sessize alinamadi: ${e.message}"
        }
        prefs.edit().putInt(KEY_PREV, prev).putInt(KEY_SET, set).apply()
        return "telefon ${modeName(set)} (onceki: ${modeName(prev)})" +
            if (set != AudioManager.RINGER_MODE_SILENT) " — tam sessiz icin Rahatsız Etmeyin izni gerekli" else ""
    }

    /**
     * Dinleme bitti (ya da uygulama acilisinda yarim kalan): telefonu eski moduna dondur — telefon hala bizim
     * ayarladigimiz moddaysa (kullanici bu arada elle degistirdiyse dokunmaz). Donus: log satiri, yapacak is yoksa null.
     */
    fun restore(ctx: Context): String? {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.contains(KEY_PREV)) return null
        val prev = prefs.getInt(KEY_PREV, AudioManager.RINGER_MODE_NORMAL)
        val set = prefs.getInt(KEY_SET, -1)
        prefs.edit().remove(KEY_PREV).remove(KEY_SET).apply()
        val am = ctx.getSystemService(AudioManager::class.java) ?: return "ses servisi yok"
        val cur = am.ringerMode
        if (cur != set) return "telefon elle ${modeName(cur)} yapilmis, dokunulmadi"
        return try {
            am.ringerMode = prev
            "telefon tekrar ${modeName(prev)}"
        } catch (e: Throwable) {
            "eski moda donulemedi (${modeName(prev)}): ${e.message}"
        }
    }
}
