package com.example.cockpit.util

import android.content.Context
import com.chaquo.python.Python
import java.io.BufferedReader
import java.io.InputStreamReader

object CoreconfHelper {
    private var cachedSid: String? = null

    /**
     * Reads the coreconf-m2m@2026-05-26.sid file from assets,
     * passes its contents to the pycoreconf Python library via Chaquopy,
     * and returns the resolved SID for '/transducers/transducer'.
     */
    fun getBootstrapSid(context: Context): String {
        if (cachedSid != null) return cachedSid!!
        
        return try {
            val assetManager = context.assets
            val inputStream = assetManager.open("coreconf-m2m@2026-05-26.sid")
            val reader = BufferedReader(InputStreamReader(inputStream))
            val content = reader.use { it.readText() }

            val py = Python.getInstance()
            val pyModule = py.getModule("coreconf_helper")
            val sidVal = pyModule.callAttr("get_bootstrap_sid", content, "coreconf-m2m").toString()
            
            cachedSid = sidVal
            sidVal
        } catch (e: Exception) {
            e.printStackTrace()
            "Error: ${e.message}"
        }
    }
}
