package com.tilavet.takip.util

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.tilavet.takip.MainActivity
import com.tilavet.takip.R

/**
 * On plan servisi, iki is (ayni bildirim):
 *  - **Dinleme** (mikrofon turu): ekran kilitlenince ya da baska uygulamaya (ör. G2 gozluk icin Even uygulamasi)
 *    gecilince Android arka plandaki uygulamanin mikrofonunu susturuyor — servis acikken dinleme surer.
 *  - **G2 koprusu** (specialUse turu, Android 14+): Ayarlar → G2 GÖZLÜK: AÇIK iken uygulama arka planda da canli kalsin
 *    (yerel kopru 127.0.0.1:18765 cevap versin). Kullanici: "G2 ile iletisim kurmak icin mikrofon tusuna basmami
 *    beklemesin; telefondaki app arka planda surekli acik kalabilsin". Servis yokken Android arka plandaki sureci
 *    dondurabiliyor → eklenti "Tilavet Takip bekleniyor"da kalir, mikrofona basinca (servis) baglanirdi.
 * Servis sadece bildirimi tutar; ses kaydi, pipeline ve kopru MainViewModel'de (ayni surec).
 *
 * Bilerek startService (startForegroundService degil) + onStartCommand'da startForeground: uygulama on plandayken
 * (kullanici dinlemeyi baslatti / uygulama acik) bu izinli; startForeground hata verirse (izin yok vb.) yakalanir,
 * dinleme yine calisir (sadece uygulama ekranda degilken susar). startForegroundService'te "zamaninda startForeground
 * cagrilmadi" cokmesi riski var.
 */
class ListenService : Service() {

    companion object {
        private const val TAG = "ListenService"
        private const val CHANNEL_ID = "dinleme"
        private const val NOTIFICATION_ID = 41
        private const val EXTRA_TEXT = "text"
        private const val EXTRA_MIC = "mic"
        private const val EXTRA_GLASSES = "glasses"

        /**
         * startForeground basarili ve servis mikrofon turuyla acik. Yatsi 23.10 (APK #116): mikrofona model yuklenirken
         * basilip Even uygulamasina gecildi; servis model hazir olunca (uygulama arka plandayken) baslatilmak istendi →
         * Android reddetti (hata sadece logcat'te, oturum log'unda yoktu) → uygulama ekranda olmadigi her an mikrofon sifir
         * (8 dk). MainViewModel dinleme baslarken (dokunma aninda) ve uygulama her one geldiginde bunu kontrol eder.
         */
        @Volatile
        var active = false
            private set

        /** Servis on planda (dinleme ya da G2 koprusu). */
        @Volatile
        var running = false
            private set

        @Volatile
        private var wantMic = false
        @Volatile
        private var wantGlasses = false
        @Volatile
        private var micText = "Dinleniyor"

        /** Dinleme basladi: servisi mikrofon turuyla ac (mikrofon izni yoksa acilmaz — on plan mikrofon servisi izin ister). */
        fun start(ctx: Context, text: String) {
            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                SessionLog.w(TAG, "servis acilmadi: mikrofon izni yok")
                return
            }
            wantMic = true
            micText = text
            sync(ctx)
        }

        /** Dinleme bitti: G2 koprusu aciksa servis mikrofonsuz surer, degilse kapanir. */
        fun stop(ctx: Context) {
            wantMic = false
            sync(ctx)
        }

        /**
         * Ayarlar → G2 GÖZLÜK acik / kapali. Uygulama her one geldiginde de cagrilir: servis arka planda baslatilamadiysa
         * (running false) simdi tekrar denenir.
         */
        fun setGlasses(ctx: Context, on: Boolean) {
            if (wantGlasses == on && (!on || running)) return
            wantGlasses = on
            sync(ctx)
        }

        private fun sync(ctx: Context) {
            if (!wantMic && !wantGlasses) {
                try {
                    ctx.stopService(Intent(ctx, ListenService::class.java))
                } catch (e: Throwable) {
                    SessionLog.w(TAG, "servis durdurulamadi: ${e.message}")
                }
                return
            }
            try {
                ctx.startService(
                    Intent(ctx, ListenService::class.java)
                        .putExtra(EXTRA_TEXT, if (wantMic) micText else "G2 gözlük bağlantısı açık")
                        .putExtra(EXTRA_MIC, wantMic)
                        .putExtra(EXTRA_GLASSES, wantGlasses)
                )
            } catch (e: Throwable) {
                // Uygulama arka plandayken Android servis baslatmaya izin vermez (IllegalStateException)
                SessionLog.w(TAG, "servis baslatilamadi (uygulama arka planda?): ${e.javaClass.simpleName} ${e.message}")
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Dinleniyor"
        val mic = intent?.getBooleanExtra(EXTRA_MIC, true) ?: true
        val glasses = intent?.getBooleanExtra(EXTRA_GLASSES, false) ?: false
        try {
            val nm = getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm.getNotificationChannel(CHANNEL_ID) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL_ID, "Dinleme", NotificationManager.IMPORTANCE_LOW).apply {
                        description = "Tilavet Takip dinlerken / G2 gözlük bağlıyken (ekran kapalı)"
                        setShowBadge(false)
                    }
                )
            }
            val open = PendingIntent.getActivity(
                this, 0,
                Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val n = NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_stat_listen)
                .setContentTitle("Tilavet Takip")
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(true)
                .setSilent(true)
                .setCategory(NotificationCompat.CATEGORY_SERVICE)
                .build()
            var type = 0
            if (mic && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            if (glasses && Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                type = type or ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            }
            ServiceCompat.startForeground(this, NOTIFICATION_ID, n, type)
            active = mic
            running = true
            SessionLog.d(TAG, "on plan servisi acik: $text (${if (mic) "mikrofon" else "mikrofonsuz"}${if (glasses) " + G2" else ""})")
        } catch (e: Throwable) {
            // Dinleme yine calisir; sadece uygulama ekranda degilken Android mikrofonu susturur
            active = false
            running = false
            SessionLog.w(TAG, "startForeground basarisiz: ${e.javaClass.simpleName} ${e.message}")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        active = false
        running = false
        SessionLog.d(TAG, "on plan servisi kapandi")
        super.onDestroy()
    }
}
