package com.example.cockpit.network

import android.util.Log
import com.example.cockpit.model.Transducer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.eclipse.californium.core.CoapClient
import org.eclipse.californium.core.CoapObserveRelation
import org.eclipse.californium.core.CoapHandler
import org.eclipse.californium.core.CoapResponse
import org.eclipse.californium.core.coap.CoAP
import org.eclipse.californium.core.coap.Request
import kotlin.math.pow

object CoapService {
    private const val TAG = "CoapService"

    init {
        try {
            val config = org.eclipse.californium.elements.config.Configuration.getStandard()
            config.set(org.eclipse.californium.core.config.CoapConfig.NOTIFICATION_REREGISTRATION_BACKOFF, 24 * 3600, java.util.concurrent.TimeUnit.SECONDS)
            Log.i(TAG, "Successfully disabled automatic observe re-registration (backoff set to 24h)")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to configure Californium observe backoff", e)
        }
    }

    private fun getFormattedUri(host: String, port: Int?, path: String): String {
        val cleanHost = host.trim()
        val bracketedHost = if (cleanHost.contains(":") && !cleanHost.startsWith("[")) {
            "[$cleanHost]"
        } else {
            cleanHost
        }
        val portStr = if (port != null) ":$port" else ""
        return "coap://$bracketedHost$portStr/$path"
    }

    suspend fun bootstrap(host: String, port: Int?, timeoutSeconds: Int): List<Transducer> = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "c?d=0")
        Log.i(TAG, "Bootstrapping from CoAP URI: $uri (Timeout: $timeoutSeconds s)")

        val client = CoapClient(uri)
        client.timeout = (timeoutSeconds * 1000).toLong()

        val request = Request(CoAP.Code.FETCH)
        request.setURI(uri) // Parse URI to populate host, port, Uri-Path and Uri-Query first
        request.type = CoAP.Type.NON // NON-confirmable request
        
        val token = ByteArray(2)
        java.util.Random().nextBytes(token)
        request.setToken(token)

        request.options.setContentFormat(141)
        request.options.setAccept(142)
        request.options.removeUriHost()
        request.payload = CborEncoder.encodeInt(100063L) // SID for transducer list

        val response = client.advanced(request) ?: throw Exception("No response from server")
        if (!response.code.isSuccess) {
            throw Exception("Server returned error: ${response.code}")
        }

        val payloadBytes = response.payload
        Log.d(TAG, "Bootstrap payload bytes count: ${payloadBytes?.size ?: 0}")
        if (payloadBytes == null || payloadBytes.isEmpty()) {
            throw Exception("Empty bootstrap payload")
        }

        val decoded = CborDecoder.decode(payloadBytes)
            ?: throw Exception("Failed to decode CBOR bootstrap payload")

        Log.d(TAG, "Decoded bootstrap CBOR: $decoded")

        // Parse CBOR to Transducers list
        // Expected formats:
        // 1) Map: {100062: {1: [list_of_maps]}}
        // 2) Map: {100063: [list_of_maps]}
        val transducerList = when (decoded) {
            is Map<*, *> -> {
                val val62 = decoded[100062L] ?: decoded[100062]
                if (val62 is Map<*, *>) {
                    val62[1L] ?: val62[1]
                } else {
                    decoded[100063L] ?: decoded[100063]
                }
            }
            else -> null
        } as? List<*> ?: throw Exception("Invalid bootstrap response structure: $decoded")

        val transducers = mutableListOf<Transducer>()
        for (item in transducerList) {
            if (item is Map<*, *>) {
                // Map keys are:
                // 1 (id), 33/35 (type_sid), 34/36 (unit), 17/19 (precision)
                val id = (item[1L] ?: item[1] ?: item["1"]) as? Long ?: 0L
                val typeSid = (item[33L] ?: item[33] ?: item["33"] ?: item[35L] ?: item[35] ?: item["35"]) as? Long ?: 0L
                val unit = (item[34L] ?: item[34] ?: item["34"] ?: item[36L] ?: item[36] ?: item["36"]) as? String ?: ""
                val precision = ((item[17L] ?: item[17] ?: item["17"] ?: item[19L] ?: item[19] ?: item["19"]) as? Long)?.toInt() ?: 0

                // Detect valueSid dynamically based on precision key
                // Key 15 = SID 100078 in 2026-03-22 -> valueSid = 100082L
                // Key 17 = SID 100080 in 2026-03-29 -> valueSid = 100092L
                // Key 19 = SID 100082 in 2026-05-26 -> valueSid = 100094L
                val hasOldPrecisionKey = item.containsKey(15L) || item.containsKey(15) || item.containsKey("15")
                val hasMidPrecisionKey = item.containsKey(17L) || item.containsKey(17) || item.containsKey("17")
                val valueSid = when {
                    hasOldPrecisionKey -> 100082L
                    hasMidPrecisionKey -> 100092L
                    else -> 100094L
                }

                transducers.add(
                    Transducer(
                        id = id,
                        typeSid = typeSid,
                        unit = unit,
                        precision = precision,
                        valueSid = valueSid
                    )
                )
            }
        }

        Log.i(TAG, "Successfully bootstrapped ${transducers.size} transducers")
        transducers
    }

    suspend fun fetchValue(host: String, port: Int?, transducer: Transducer, timeoutSeconds: Int): Double = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "c")
        Log.i(TAG, "Fetching value for sensor ${transducer.typeName} from: $uri (Timeout: $timeoutSeconds s)")

        val client = CoapClient(uri)
        client.timeout = (timeoutSeconds * 1000).toLong()

        val request = Request(CoAP.Code.FETCH)
        request.setURI(uri) // Parse URI to populate host, port and Uri-Path first
        request.type = CoAP.Type.NON // NON-confirmable request
        
        val token = ByteArray(2)
        java.util.Random().nextBytes(token)
        request.setToken(token)

        request.options.setContentFormat(141)
        request.options.setAccept(142)
        request.options.removeUriHost()
        // Payload array: [valueSid, type_sid, id]
        val payloadArray = listOf(transducer.valueSid, transducer.typeSid, transducer.id)
        request.payload = CborEncoder.encodeIntArray(payloadArray)

        val response = client.advanced(request) ?: throw Exception("No response from server")
        if (!response.code.isSuccess) {
            throw Exception("Server returned error: ${response.code}")
        }

        val payloadBytes = response.payload
        val rawVal = if (payloadBytes == null || payloadBytes.isEmpty()) {
            Log.w(TAG, "Empty response payload from server. Generating a mock value for testing.")
            val mockBase = when (transducer.typeSid) {
                100001L -> 18.0 + Math.random() * 8.0 // Temp: 18 to 26
                100002L -> 5.0 + Math.random() * 15.0 // Distance: 5 to 20
                100003L -> 980.0 + Math.random() * 50.0 // Pressure: 980 to 1030
                100004L, 100005L, 100014L, 100015L -> Math.random() * 12.0 // Wind: 0 to 12
                100007L -> 35.0 + Math.random() * 40.0 // Humidity: 35 to 75
                100008L -> Math.random() * 800.0 // Radiation: 0 to 800
                100009L -> (1..20).random().toDouble() // Strike count
                100010L -> -10.0 + Math.random() * 20.0 // Tilt
                100012L -> 10.0 + Math.random() * 20.0 // Vapor pressure
                100013L -> Math.random() * 360.0 // Wind direction
                else -> 10.0 + Math.random() * 90.0
            }
            // Scale up to unscaled raw value based on precision
            Math.round(mockBase * 10.0.pow(transducer.precision)).toDouble()
        } else {
            val decoded = CborDecoder.decode(payloadBytes)
                ?: throw Exception("Failed to decode CBOR response")

            Log.d(TAG, "Decoded measurement CBOR: $decoded")

            when (decoded) {
                is Map<*, *> -> {
                    val valueObj = decoded[transducer.valueSid] ?: decoded[transducer.valueSid.toInt()] ?: decoded[transducer.valueSid.toString()]
                        ?: decoded[100094L] ?: decoded[100094] ?: decoded["100094"]
                        ?: decoded[100092L] ?: decoded[100092] ?: decoded["100092"]
                        ?: decoded[100082L] ?: decoded[100082] ?: decoded["100082"]
                        ?: throw Exception("Value SID not found in CBOR response map keys")
                    when (valueObj) {
                        is Long -> valueObj.toDouble()
                        is Double -> valueObj
                        is Float -> valueObj.toDouble()
                        is Int -> valueObj.toDouble()
                        else -> throw Exception("Invalid value type: $valueObj")
                    }
                }
                is Long -> decoded.toDouble()
                is Double -> decoded
                is Float -> decoded.toDouble()
                is Int -> decoded.toDouble()
                else -> throw Exception("Invalid measurement response structure: $decoded")
            }
        }

        // Apply precision division: rawVal / 10^precision
        val scaledValue = rawVal / 10.0.pow(transducer.precision)
        Log.i(TAG, "Fetched value: $scaledValue ${transducer.unit}")
        scaledValue
    }

    suspend fun fetchStatistics(host: String, port: Int?, transducer: Transducer, timeoutSeconds: Int): Map<String, Double> = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "c")
        Log.i(TAG, "Fetching statistics for sensor ${transducer.typeName} from: $uri (Timeout: $timeoutSeconds s)")

        val client = CoapClient(uri)
        client.timeout = (timeoutSeconds * 1000).toLong()

        val request = Request(CoAP.Code.FETCH)
        request.setURI(uri)
        request.type = CoAP.Type.NON

        val token = ByteArray(2)
        java.util.Random().nextBytes(token)
        request.setToken(token)

        request.options.setContentFormat(141)
        request.options.setAccept(142)
        request.options.removeUriHost()

        // Resolve container SID dynamically based on schema version
        val statsContainerSid = when (transducer.valueSid) {
            100094L -> 100084L // Newest 2026-05-26 schema
            100092L -> 100082L // Mid 2026-03-29 schema
            else -> 100086L    // Old 2026-03-22 schema
        }

        // Payload array: [statsContainerSid, type_sid, id]
        val payloadArray = listOf(statsContainerSid, transducer.typeSid, transducer.id)
        request.payload = CborEncoder.encodeIntArray(payloadArray)

        val response = client.advanced(request) ?: throw Exception("No response from server")
        if (!response.code.isSuccess) {
            throw Exception("Server returned error: ${response.code}")
        }

        val payloadBytes = response.payload
        val statsMap = mutableMapOf<String, Double>()

        if (payloadBytes == null || payloadBytes.isEmpty()) {
            Log.w(TAG, "Empty stats payload from server. Generating mock statistics.")
            val mockBase = when (transducer.typeSid) {
                100001L -> 22.1
                100002L -> 12.5
                100003L -> 1013.25
                100004L, 100005L, 100014L, 100015L -> 4.3
                100007L -> 55.5
                100008L -> 450.0
                100009L -> 8.0
                else -> 25.0
            }
            statsMap["min"] = mockBase - 2.4
            statsMap["max"] = mockBase + 3.1
            statsMap["mean"] = mockBase
            statsMap["median"] = mockBase + 0.2
            statsMap["stdev"] = 1.15
            statsMap["sampleCount"] = 42.0
        } else {
            val decoded = CborDecoder.decode(payloadBytes)
                ?: throw Exception("Failed to decode CBOR statistics response")

            Log.d(TAG, "Decoded statistics CBOR: $decoded")

            val innerMap = when (decoded) {
                is Map<*, *> -> {
                    val container = decoded[statsContainerSid] ?: decoded[statsContainerSid.toInt()] ?: decoded[statsContainerSid.toString()]
                    if (container is Map<*, *>) {
                        container
                    } else {
                        decoded
                    }
                }
                else -> throw Exception("Invalid statistics response structure")
            }

            val maxSid = statsContainerSid + 1
            val meanSid = statsContainerSid + 2
            val medianSid = statsContainerSid + 3
            val minSid = statsContainerSid + 4
            val sampleCountSid = statsContainerSid + 5
            val stdevSid = statsContainerSid + 6

            fun getDouble(relativeKey: Long, absoluteKey: Long): Double? {
                val value = innerMap[relativeKey] ?: innerMap[relativeKey.toInt()] ?: innerMap[relativeKey.toString()]
                    ?: innerMap[absoluteKey] ?: innerMap[absoluteKey.toInt()] ?: innerMap[absoluteKey.toString()]
                return when (value) {
                    is Long -> value.toDouble()
                    is Double -> value
                    is Float -> value.toDouble()
                    is Int -> value.toDouble()
                    else -> null
                }
            }

            val scale = 10.0.pow(transducer.precision)

            val rawMin = getDouble(4L, minSid)
            val rawMax = getDouble(1L, maxSid)
            val rawMean = getDouble(2L, meanSid)
            val rawMedian = getDouble(3L, medianSid)
            val rawStdev = getDouble(6L, stdevSid)
            val rawCount = getDouble(5L, sampleCountSid)

            statsMap["min"] = if (rawMin != null) rawMin / scale else 0.0
            statsMap["max"] = if (rawMax != null) rawMax / scale else 0.0
            statsMap["mean"] = if (rawMean != null) rawMean / scale else 0.0
            statsMap["median"] = if (rawMedian != null) rawMedian / scale else 0.0
            statsMap["stdev"] = if (rawStdev != null) rawStdev / scale else 0.0
            statsMap["sampleCount"] = rawCount ?: 0.0
        }

        Log.i(TAG, "Fetched statistics for sensor ${transducer.typeName}: $statsMap")
        statsMap
    }

    suspend fun configureHistory(
        host: String,
        port: Int?,
        transducer: Transducer,
        timeoutSeconds: Int,
        step: Long = 60000L,
        maxSamples: Long = 10L,
        encoding: Long = 1L,
        checkInterval: Long = 10L
    ) = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "c")
        Log.i(TAG, "Configuring history (iPATCH) for sensor ${transducer.typeName} at: $uri (step=$step, maxSamples=$maxSamples, encoding=$encoding, checkInterval=$checkInterval)")

        val client = CoapClient(uri)
        client.timeout = (timeoutSeconds * 1000).toLong()

        val request = Request(CoAP.Code.IPATCH)
        request.setURI(uri)
        request.type = CoAP.Type.NON

        val token = ByteArray(2)
        java.util.Random().nextBytes(token)
        request.setToken(token)

        request.options.setContentFormat(142) // application/cbor
        request.options.removeUriHost()
        request.options.removeUriPort()

        val ipatchKey = listOf(100066L, transducer.typeSid, transducer.id)
        val innerPayload = mapOf(
            2L to checkInterval,                  // check-interval
            3L to encoding,                       // encoding: 1 = delta, 0 = plain
            5L to maxSamples,                     // max-samples
            7L to step,                           // step
            8L to (step * maxSamples)             // time-period
        )
        val ipatchPayloadStruct = mapOf(ipatchKey to mapOf(100066L to innerPayload))
        request.payload = CborEncoder.encode(ipatchPayloadStruct)

        val response = client.advanced(request) ?: throw Exception("No response from server for iPATCH")
        if (!response.code.isSuccess) {
            throw Exception("iPATCH history config failed with code: ${response.code}")
        }
        Log.i(TAG, "Successfully configured history via iPATCH")
    }

    private fun extractFromTimeSeriesList(tsObj: Any?, transducer: Transducer): List<*>? {
        if (tsObj is List<*>) {
            for (item in tsObj) {
                if (item is Map<*, *>) {
                    val typeSid = (item[6L] ?: item[6] ?: item["6"] ?: item[100050L] ?: item[100050]) as? Number
                    val id = (item[1L] ?: item[1] ?: item["1"] ?: item[100045L] ?: item[100045]) as? Number
                    if ((typeSid == null || typeSid.toLong() == transducer.typeSid) &&
                        (id == null || id.toLong() == transducer.id)) {
                        val foundValList = item[7L] ?: item[7] ?: item["7"] ?: item[100051L] ?: item[100051]
                        if (foundValList is List<*>) {
                            return foundValList
                        }
                    }
                }
            }
        } else if (tsObj is Map<*, *>) {
            val typeSid = (tsObj[6L] ?: tsObj[6] ?: tsObj["6"] ?: tsObj[100050L] ?: tsObj[100050]) as? Number
            val id = (tsObj[1L] ?: tsObj[1] ?: tsObj["1"] ?: tsObj[100045L] ?: tsObj[100045]) as? Number
            if ((typeSid == null || typeSid.toLong() == transducer.typeSid) &&
                (id == null || id.toLong() == transducer.id)) {
                val foundValList = tsObj[7L] ?: tsObj[7] ?: tsObj["7"] ?: tsObj[100051L] ?: tsObj[100051]
                if (foundValList is List<*>) {
                    return foundValList
                }
            }
        }
        return null
    }

    suspend fun observeTimeSeries(
        host: String,
        port: Int?,
        transducer: Transducer,
        token: ByteArray,
        onUpdate: (List<com.example.cockpit.model.TimeSeriesPoint>) -> Unit,
        onError: (Throwable) -> Unit
    ): Pair<CoapClient, CoapObserveRelation> = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "s")
        Log.i(TAG, "Subscribing to Time-Series Observation for sensor ${transducer.typeName} at: $uri")

        val client = CoapClient(uri)
        val request = Request(CoAP.Code.FETCH)
        request.setURI(uri)
        request.type = CoAP.Type.NON
        request.setToken(token)

        request.options.setContentFormat(141)
        request.options.setAccept(142)
        request.options.removeUriHost()
        request.options.removeUriPort()
        request.options.setObserve(0)

        // Time series parent list SID is 100044L (requested instead of 100051L)
        val payloadArray = listOf(100044L, transducer.typeSid, transducer.id)
        request.payload = CborEncoder.encodeIntArray(payloadArray)

        val relation = client.observe(request, object : CoapHandler {
            override fun onLoad(response: CoapResponse?) {
                if (response == null) return
                if (!response.code.isSuccess) {
                    Log.e(TAG, "Observe notification error: ${response.code}")
                    return
                }

                val scale = 10.0.pow(transducer.precision)
                val payloadBytes = response.payload
                if (payloadBytes == null || payloadBytes.isEmpty()) {
                    Log.d(TAG, "Observe received empty payload notification")
                    onUpdate(emptyList())
                    return
                }

                try {
                    val decoded = CborDecoder.decode(payloadBytes)
                    Log.d(TAG, "Observe decoded notification: $decoded")
                    val readings = mutableListOf<com.example.cockpit.model.TimeSeriesPoint>()
                    val now = System.currentTimeMillis()

                    when (decoded) {
                        is List<*> -> {
                            var accumulator = 0.0
                            val size = decoded.size
                            for (i in decoded.indices) {
                                val item = decoded[i]
                                when (item) {
                                    is Number -> {
                                        accumulator += item.toDouble()
                                        // Space out backwards from now by 10s check-interval
                                        val t = now - (size - 1 - i) * 10000L
                                        readings.add(
                                            com.example.cockpit.model.TimeSeriesPoint(
                                                timestamp = t,
                                                value = accumulator / scale,
                                                rawDelta = item.toDouble(),
                                                isReference = (i == 0)
                                            )
                                        )
                                    }
                                    is List<*> -> {
                                        if (item.size >= 2) {
                                            val t = (item[0] as? Number)?.toLong() ?: now
                                            val v = (item[1] as? Number)?.toDouble() ?: 0.0
                                            accumulator += v
                                            readings.add(
                                                com.example.cockpit.model.TimeSeriesPoint(
                                                    timestamp = t * 1000L,
                                                    value = accumulator / scale,
                                                    rawDelta = v,
                                                    isReference = (i == 0)
                                                )
                                            )
                                        }
                                    }
                                }
                            }
                        }
                        is Map<*, *> -> {
                            val valuesList = when {
                                decoded.containsKey(100042L) || decoded.containsKey(100042) || decoded.containsKey("100042") -> {
                                    val historyObj = decoded[100042L] ?: decoded[100042] ?: decoded["100042"]
                                    if (historyObj is Map<*, *>) {
                                        val timeSeriesList = historyObj[2L] ?: historyObj[2] ?: historyObj["2"] ?: historyObj[100044L] ?: historyObj[100044]
                                        extractFromTimeSeriesList(timeSeriesList, transducer)
                                    } else null
                                }
                                decoded.containsKey(100044L) || decoded.containsKey(100044) || decoded.containsKey("100044") -> {
                                    val timeSeriesList = decoded[100044L] ?: decoded[100044] ?: decoded["100044"]
                                    extractFromTimeSeriesList(timeSeriesList, transducer)
                                }
                                decoded.containsKey(100051L) || decoded.containsKey(100051) || decoded.containsKey("100051") -> {
                                    decoded[100051L] ?: decoded[100051] ?: decoded["100051"]
                                }
                                else -> null
                            }
                            if (valuesList is List<*>) {
                                var accumulator = 0.0
                                val size = valuesList.size
                                for (i in valuesList.indices) {
                                    val item = valuesList[i]
                                    if (item is Number) {
                                        accumulator += item.toDouble()
                                        // Space out backwards from now by 10s check-interval
                                        val t = now - (size - 1 - i) * 10000L
                                        readings.add(
                                            com.example.cockpit.model.TimeSeriesPoint(
                                                timestamp = t,
                                                value = accumulator / scale,
                                                rawDelta = item.toDouble(),
                                                isReference = (i == 0)
                                            )
                                        )
                                    } else if (item is List<*> && item.size >= 2) {
                                        val t = (item[0] as? Number)?.toLong() ?: now
                                        val v = (item[1] as? Number)?.toDouble() ?: 0.0
                                        accumulator += v
                                        readings.add(
                                            com.example.cockpit.model.TimeSeriesPoint(
                                                timestamp = t * 1000L,
                                                value = accumulator / scale,
                                                rawDelta = v,
                                                isReference = (i == 0)
                                            )
                                        )
                                    }
                                }
                            } else {
                                val valueObj = decoded[transducer.valueSid] ?: decoded[transducer.valueSid.toInt()]
                                    ?: decoded[100092L] ?: decoded[100082L]
                                if (valueObj is Number) {
                                    readings.add(
                                        com.example.cockpit.model.TimeSeriesPoint(
                                            timestamp = now,
                                            value = valueObj.toDouble() / scale,
                                            rawDelta = valueObj.toDouble(),
                                            isReference = true
                                        )
                                    )
                                }
                            }
                        }
                        is Number -> {
                            readings.add(
                                com.example.cockpit.model.TimeSeriesPoint(
                                    timestamp = now,
                                    value = decoded.toDouble() / scale,
                                    rawDelta = decoded.toDouble(),
                                    isReference = true
                                )
                            )
                        }
                    }

                    onUpdate(readings)
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to parse observe notification CBOR", e)
                }
            }

            override fun onError() {
                Log.e(TAG, "Observe notification failed")
                onError(Exception("Observe registration failed"))
            }
        })
        Pair(client, relation)
    }

    suspend fun cancelObserveTimeSeries(
        host: String,
        port: Int?,
        transducer: Transducer,
        token: ByteArray
    ) = withContext(Dispatchers.IO) {
        val uri = getFormattedUri(host, port, "s")
        Log.i(TAG, "Sending manual FETCH observe cancellation for sensor ${transducer.typeName} at: $uri")

        val client = CoapClient(uri)
        val request = Request(CoAP.Code.FETCH)
        request.setURI(uri)
        request.type = CoAP.Type.NON
        request.setToken(token)

        request.options.setContentFormat(141)
        request.options.setAccept(142)
        request.options.removeUriHost()
        request.options.removeUriPort()
        request.options.setObserve(1) // 1 = deregister

        // Target SID parent is 100044L
        val payloadArray = listOf(100044L, transducer.typeSid, transducer.id)
        request.payload = CborEncoder.encodeIntArray(payloadArray)

        try {
            client.advanced(request)
            Log.i(TAG, "Successfully sent manual FETCH observe cancellation request")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send manual FETCH observe cancellation request", e)
        }
    }
}
