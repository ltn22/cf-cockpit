package com.example.cockpit.network

import java.io.ByteArrayInputStream
import java.io.InputStream
import java.nio.charset.StandardCharsets

object CborDecoder {
    fun decode(bytes: ByteArray): Any? {
        val stream = ByteArrayInputStream(bytes)
        return try {
            decodeValue(stream)
        } catch (e: Exception) {
            e.printStackTrace()
            null
        }
    }

    private fun decodeValue(stream: InputStream): Any? {
        val first = stream.read()
        if (first == -1) throw Exception("Unexpected EOF")
        
        val major = first ushr 5
        val info = first and 0x1F

        val length = when {
            info < 24 -> info.toLong()
            info == 24 -> stream.read().toLong()
            info == 25 -> {
                val b1 = stream.read()
                val b2 = stream.read()
                ((b1 shl 8) or b2).toLong()
            }
            info == 26 -> {
                var acc = 0L
                for (i in 0 until 4) {
                    acc = (acc shl 8) or stream.read().toLong()
                }
                acc
            }
            info == 27 -> {
                var acc = 0L
                for (i in 0 until 8) {
                    acc = (acc shl 8) or stream.read().toLong()
                }
                acc
            }
            info == 31 -> -1L // indefinite length
            else -> throw Exception("Unsupported CBOR length info: $info")
        }

        return when (major) {
            0 -> length // positive integer
            1 -> -1L - length // negative integer
            2 -> { // byte string
                if (length == -1L) throw Exception("Indefinite byte strings not supported")
                val buf = ByteArray(length.toInt())
                var read = 0
                while (read < buf.size) {
                    val r = stream.read(buf, read, buf.size - read)
                    if (r == -1) throw Exception("EOF in byte string")
                    read += r
                }
                buf
            }
            3 -> { // text string
                if (length == -1L) throw Exception("Indefinite text strings not supported")
                val buf = ByteArray(length.toInt())
                var read = 0
                while (read < buf.size) {
                    val r = stream.read(buf, read, buf.size - read)
                    if (r == -1) throw Exception("EOF in text string")
                    read += r
                }
                String(buf, StandardCharsets.UTF_8)
            }
            4 -> { // array
                if (length == -1L) {
                    val list = mutableListOf<Any?>()
                    while (true) {
                        stream.mark(1)
                        val next = stream.read()
                        if (next == 0xFF) break
                        stream.reset()
                        list.add(decodeValue(stream))
                    }
                    list
                } else {
                    val list = ArrayList<Any?>(length.toInt())
                    for (i in 0 until length.toInt()) {
                        list.add(decodeValue(stream))
                    }
                    list
                }
            }
            5 -> { // map
                if (length == -1L) {
                    val map = mutableMapOf<Any?, Any?>()
                    while (true) {
                        stream.mark(1)
                        val next = stream.read()
                        if (next == 0xFF) break
                        stream.reset()
                        val key = decodeValue(stream)
                        val value = decodeValue(stream)
                        map[key] = value
                    }
                    map
                } else {
                    val map = LinkedHashMap<Any?, Any?>(length.toInt())
                    for (i in 0 until length.toInt()) {
                        val key = decodeValue(stream)
                        val value = decodeValue(stream)
                        map[key] = value
                    }
                    map
                }
            }
            6 -> { // tag (skip and decode)
                decodeValue(stream)
            }
            7 -> { // simple / float
                if (info == 20) false
                else if (info == 21) true
                else if (info == 22) null
                else if (info == 26) { // 32-bit float
                    val bits = (stream.read() shl 24) or (stream.read() shl 16) or (stream.read() shl 8) or stream.read()
                    java.lang.Float.intBitsToFloat(bits)
                } else if (info == 27) { // 64-bit double
                    var bits = 0L
                    for (i in 0 until 8) {
                        bits = (bits shl 8) or stream.read().toLong()
                    }
                    java.lang.Double.longBitsToDouble(bits)
                } else {
                    null
                }
            }
            else -> throw Exception("Unknown major type: $major")
        }
    }
}

object CborEncoder {
    fun encode(value: Any?): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        write(value, out)
        return out.toByteArray()
    }

    private fun write(value: Any?, out: java.io.OutputStream) {
        when (value) {
            null -> out.write(0xF6)
            is Boolean -> out.write(if (value) 0xF5 else 0xF4)
            is Byte -> writeInt(value.toLong(), out)
            is Short -> writeInt(value.toLong(), out)
            is Int -> writeInt(value.toLong(), out)
            is Long -> writeInt(value, out)
            is String -> {
                val bytes = value.toByteArray(Charsets.UTF_8)
                writeHeader(3, bytes.size.toLong(), out)
                out.write(bytes)
            }
            is ByteArray -> {
                writeHeader(2, value.size.toLong(), out)
                out.write(value)
            }
            is List<*> -> {
                writeHeader(4, value.size.toLong(), out)
                for (item in value) {
                    write(item, out)
                }
            }
            is Map<*, *> -> {
                writeHeader(5, value.size.toLong(), out)
                for ((k, v) in value) {
                    write(k, out)
                    write(v, out)
                }
            }
            else -> throw Exception("Unsupported type for CBOR encoding: ${value::class.java.name}")
        }
    }

    private fun writeHeader(major: Int, value: Long, out: java.io.OutputStream) {
        val majorShifted = major shl 5
        when {
            value in 0..23 -> out.write(majorShifted or value.toInt())
            value in 24..255 -> {
                out.write(majorShifted or 24)
                out.write(value.toInt())
            }
            value in 256..65535 -> {
                out.write(majorShifted or 25)
                out.write((value ushr 8).toInt())
                out.write((value and 0xFF).toInt())
            }
            value in 65536..4294967295L -> {
                out.write(majorShifted or 26)
                out.write((value ushr 24).toInt())
                out.write(((value ushr 16) and 0xFF).toInt())
                out.write(((value ushr 8) and 0xFF).toInt())
                out.write((value and 0xFF).toInt())
            }
            else -> {
                out.write(majorShifted or 27)
                for (i in 7 downTo 0) {
                    out.write(((value ushr (i * 8)) and 0xFFL).toInt())
                }
            }
        }
    }

    private fun writeInt(value: Long, out: java.io.OutputStream) {
        if (value >= 0) {
            writeHeader(0, value, out)
        } else {
            writeHeader(1, -1L - value, out)
        }
    }

    fun encodeInt(value: Long): ByteArray = encode(value)
    fun encodeIntArray(array: List<Long>): ByteArray = encode(array)
}
