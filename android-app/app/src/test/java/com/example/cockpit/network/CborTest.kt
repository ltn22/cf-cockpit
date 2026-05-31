package com.example.cockpit.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CborTest {

    @Test
    fun testEncodeInt_smallValues() {
        val b0 = CborEncoder.encodeInt(0L)
        assertEquals(1, b0.size)
        assertEquals(0.toByte(), b0[0])

        val b23 = CborEncoder.encodeInt(23L)
        assertEquals(1, b23.size)
        assertEquals(23.toByte(), b23[0])
    }

    @Test
    fun testEncodeInt_largerValues() {
        // 100063L SID
        val bSID = CborEncoder.encodeInt(100063L)
        assertEquals(5, bSID.size)
        assertEquals(26.toByte(), bSID[0]) // Major type 0, 32-bit (info=26)
        
        val hex = bSID.joinToString("") { String.format("%02x", it) }
        assertEquals("1a000186df", hex)
    }

    @Test
    fun testEncodeIntArray() {
        // [100092L, 100001L, 0L]
        val array = listOf(100092L, 100001L, 0L)
        val encoded = CborEncoder.encodeIntArray(array)
        val hex = encoded.joinToString("") { String.format("%02x", it) }
        assertEquals("831a000186fc1a000186a100", hex)
    }

    @Test
    @Suppress("UNCHECKED_CAST")
    fun testDecode_nestedBootstrap() {
        // Hex bytes of: {100062L: {1L: [{1L: 0L, 17L: 1L, 33L: 100001L, 34L: "C"}, {1L: 1L, 17L: 0L, 33L: 100007L, 34L: "%"}]}}
        val hex = "a11a000186dea10182a5010018211a000186a118226143110112a10b18e1a5010118211a000186a718226125110012a10b182d"
        // Wait, let's use actual bytes
        val bytes = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val decoded = CborDecoder.decode(bytes)
        
        assertNotNull(decoded)
        assertTrue(decoded is Map<*, *>)
        
        val map = decoded as Map<Any, Any>
        val rootKey = 100062L
        assertTrue(map.containsKey(rootKey))
        
        val innerMap = map[rootKey] as Map<Any, Any>
        assertTrue(innerMap.containsKey(1L))
        
        val list = innerMap[1L] as List<Any>
        assertEquals(2, list.size) // our simulated hex has 2 items
        
        val firstItem = list[0] as Map<Any, Any>
        assertEquals(0L, firstItem[1L])
        assertEquals(100001L, firstItem[33L])
        assertEquals("C", firstItem[34L])
        assertEquals(1L, firstItem[17L])
    }

    @Test
    fun testDecode_fetchDirectResponse() {
        // Hex of: {100092: 225} -> a11a000186fc18e1
        val hex = "a11a000186fc18e1"
        val bytes = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val decoded = CborDecoder.decode(bytes)
        
        assertNotNull(decoded)
        assertTrue(decoded is Map<*, *>)
        
        val map = decoded as Map<Any, Any>
        assertEquals(225L, map[100092L])
    }

    @Test
    fun testEncode_recursiveStruct() {
        val ipatchKey = listOf(100066L, "strike-count", 0L)
        val innerPayload = mapOf(2L to 10L, 3L to 1L, 5L to 10L, 8L to 60000L)
        val ipatchPayloadStruct = mapOf(ipatchKey to mapOf(100066L to innerPayload))
        val encoded = CborEncoder.encode(ipatchPayloadStruct)
        val hex = encoded.joinToString("") { String.format("%02x", it) }
        assertEquals("a1831a000186e26c737472696b652d636f756e7400a11a000186e2a4020a0301050a0819ea60", hex)
    }
}







