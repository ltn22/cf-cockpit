package com.example.cockpit.network

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.cockpit.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

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
    private var wifiLock: WifiManager.WifiLock? = null
    private var heartbeatJob: Job? = null
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
            
            // Acquire locks if not already held
            acquireLocks()
            
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

    private fun acquireLocks() {
        if (wakeLock == null) {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "fr.schcchair.coreconf_m2m::CoapObserveWakeLock"
            ).apply {
                setReferenceCounted(false)
                acquire()
            }
            Log.i(TAG, "PARTIAL_WAKE_LOCK acquired")
        }
        if (wifiLock == null) {
            val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            wifiLock = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                wifiManager.createWifiLock(
                    WifiManager.WIFI_MODE_FULL_HIGH_PERF,
                    "fr.schcchair.coreconf_m2m::CoapObserveWifiLock"
                )
            } else {
                @Suppress("DEPRECATION")
                wifiManager.createWifiLock(
                    WifiManager.WIFI_MODE_FULL,
                    "fr.schcchair.coreconf_m2m::CoapObserveWifiLock"
                )
            }.apply {
                setReferenceCounted(false)
                acquire()
            }
            Log.i(TAG, "WifiLock acquired")
        }
        startHeartbeat()
    }

    private fun releaseLocks() {
        stopHeartbeat()
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
                Log.i(TAG, "PARTIAL_WAKE_LOCK released")
            }
        }
        wakeLock = null

        wifiLock?.let {
            if (it.isHeld) {
                it.release()
                Log.i(TAG, "WifiLock released")
            }
        }
        wifiLock = null
    }

    private fun startHeartbeat() {
        if (heartbeatJob == null) {
            val scope = CoroutineScope(Dispatchers.IO)
            heartbeatJob = scope.launch {
                while (isActive) {
                    try {
                        val url = java.net.URL("https://connectivitycheck.gstatic.com/generate_204")
                        val connection = url.openConnection() as java.net.HttpURLConnection
                        connection.connectTimeout = 3000
                        connection.readTimeout = 3000
                        connection.requestMethod = "GET"
                        connection.useCaches = false
                        val responseCode = connection.responseCode
                        Log.d(TAG, "Heartbeat check response: $responseCode")
                        connection.disconnect()
                    } catch (e: Exception) {
                        Log.w(TAG, "Heartbeat check failed: ${e.message}")
                    }
                    delay(30000L)
                }
            }
            Log.i(TAG, "Background network heartbeat started")
        }
    }

    private fun stopHeartbeat() {
        heartbeatJob?.cancel()
        heartbeatJob = null
        Log.i(TAG, "Background network heartbeat stopped")
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
        releaseLocks()
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
        releaseLocks()
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }
}
