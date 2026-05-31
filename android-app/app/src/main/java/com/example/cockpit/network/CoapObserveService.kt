package com.example.cockpit.network

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.cockpit.MainActivity

class CoapObserveService : Service() {

    companion object {
        private const val TAG = "CoapObserveService"
        private const val CHANNEL_ID = "CoapObserveChannel"
        private const val NOTIFICATION_ID = 1001

        private const val ACTION_START = "START"
        private const val ACTION_STOP = "STOP"
        private const val EXTRA_HOST = "HOST"

        private var activeObservationsCount = 0

        fun startMonitoring(context: Context, host: String) {
            val intent = Intent(context, CoapObserveService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_HOST, host)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stopMonitoring(context: Context) {
            val intent = Intent(context, CoapObserveService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    private var wakeLock: PowerManager.WakeLock? = null
    private var notificationManager: NotificationManager? = null
    private var currentHost: String = "atmos.openschc.net"

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Service onCreate")
        notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        val host = intent?.getStringExtra(EXTRA_HOST)
        if (host != null) {
            currentHost = host
        }

        Log.i(TAG, "onStartCommand action: $action, host: $host")

        if (action == ACTION_START) {
            activeObservationsCount++
            Log.d(TAG, "Starting observation, active count: $activeObservationsCount")
            
            // Acquire wake lock if not already held
            acquireWakeLock()
            
            // Build and show/update foreground notification
            val notification = buildNotification("Monitoring active: $currentHost")
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(
                    NOTIFICATION_ID, 
                    notification, 
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                )
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
        } else if (action == ACTION_STOP) {
            if (activeObservationsCount > 0) {
                activeObservationsCount--
            }
            Log.d(TAG, "Stopping observation, active count: $activeObservationsCount")

            if (activeObservationsCount == 0) {
                Log.i(TAG, "No more active observations, stopping service")
                stopForegroundAndService()
            } else {
                // Update notification with remaining count if needed
                val notification = buildNotification("Monitoring active: $currentHost")
                notificationManager?.notify(NOTIFICATION_ID, notification)
            }
        }

        return START_NOT_STICKY
    }

    private fun acquireWakeLock() {
        if (wakeLock == null) {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "com.example.cockpit::CoapObserveWakeLock"
            ).apply {
                setReferenceCounted(false)
                acquire()
            }
            Log.i(TAG, "PARTIAL_WAKE_LOCK acquired")
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
                Log.i(TAG, "PARTIAL_WAKE_LOCK released")
            }
        }
        wakeLock = null
    }

    private fun buildNotification(text: String): Notification {
        val notificationIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            notificationIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Cockpit IoT Telemetry")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_popup_sync)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Cockpit CoAP Observation Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps CoAP Observe connections active in background"
                setShowBadge(false)
            }
            notificationManager?.createNotificationChannel(channel)
            Log.d(TAG, "Notification channel created")
        }
    }

    private fun stopForegroundAndService() {
        releaseWakeLock()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        stopSelf()
    }

    override fun onDestroy() {
        super.onDestroy()
        Log.i(TAG, "Service onDestroy")
        releaseWakeLock()
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }
}
