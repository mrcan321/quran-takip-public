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
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.tilavet.takip.MainActivity
import com.tilavet.takip.R

/**
 * Dinleme surerken on plan servisi (mikrofon turu): ekran kilitlenince ya da baska uygulamaya (ör. G2 gozluk icin Even
 * uygulamasi) gecilince Android arka plandaki uygulamanin mikrofonunu susturuyor — servis acikken dinleme surer.
 * Servis sadece bildirimi tutar; ses kaydi ve pipeline MainViewModel'de (ayni surec).
 *
 * Bilerek startService (startForegroundService degil) + onStartCommand'da startForeground: uygulama on plandayken
 * (kullanici dinlemeyi baslatti) bu izinli; startForeground hata verirse (izin yok vb.) yakalanir, dinleme yine
 * calisir (sadece ekran kilitlenince susar — eski davranis). startForegroundService'te "zamaninda startForeground
 * cagrilmadi" cokmesi riski var.
 */
class ListenService : Service() {

    companion object {
        private const val TAG = "ListenService"
        private const val CHANNEL_ID = "dinleme"
        private const val NOTIFICATION_ID = 41
        private const val EXTRA_TEXT = "text"

        /** Dinleme basladi: servisi ac (mikrofon izni yoksa acilmaz — on plan mikrofon servisi izin ister). */
        fun start(ctx: Context, text: String) {
            if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
            try {
                ctx.startService(Intent(ctx, ListenService::class.java).putExtra(EXTRA_TEXT, text))
            } catch (e: Throwable) {
                Log.w(TAG, "servis baslatilamadi: ${e.message}")
            }
        }

        fun stop(ctx: Context) {
            try {
                ctx.stopService(Intent(ctx, ListenService::class.java))
            } catch (e: Throwable) {
                Log.w(TAG, "servis durdurulamadi: ${e.message}")
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val text = intent?.getStringExtra(EXTRA_TEXT) ?: "Dinleniyor"
        try {
            val nm = getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm.getNotificationChannel(CHANNEL_ID) == null) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL_ID, "Dinleme", NotificationManager.IMPORTANCE_LOW).apply {
                        description = "Tilavet Takip dinlerken (ekran kapali / gozluk)"
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
            ServiceCompat.startForeground(
                this, NOTIFICATION_ID, n,
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0,
            )
            Log.d(TAG, "on plan servisi acik: $text")
        } catch (e: Throwable) {
            // Dinleme yine calisir; sadece ekran kilitlenince Android mikrofonu susturur
            Log.w(TAG, "startForeground basarisiz: ${e.message}")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        Log.d(TAG, "on plan servisi kapandi")
        super.onDestroy()
    }
}
