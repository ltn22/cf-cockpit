package com.example.cockpit.ui.main

import com.example.cockpit.model.ConnectionState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MainScreenViewModelTest {
    @Test
    fun testInitialState() {
        val viewModel = MainScreenViewModel()
        val sessions = viewModel.sessions.value
        assertEquals(1, sessions.size)
        
        val firstSession = sessions[0]
        assertEquals("atmos.openschc.net", firstSession.host)
        assertEquals(5683, firstSession.port)
        assertEquals(ConnectionState.Idle, firstSession.connectionState)
        assertTrue(firstSession.transducers.isEmpty())
        assertTrue(!firstSession.showAddDialog)
    }

    @Test
    fun testUpdateHostAndPort() {
        val viewModel = MainScreenViewModel()
        val sessionId = viewModel.sessions.value[0].id
        
        viewModel.updateHost(sessionId, "fe80::1")
        viewModel.updatePort(sessionId, "8080")
        
        val updatedSession = viewModel.sessions.value[0]
        assertEquals("fe80::1", updatedSession.host)
        assertEquals(8080, updatedSession.port)
    }

    @Test
    fun testUpdateTimeout() {
        val viewModel = MainScreenViewModel()
        val sessionId = viewModel.sessions.value[0].id
        
        viewModel.updateTimeout(sessionId, "15")
        
        val updatedSession = viewModel.sessions.value[0]
        assertEquals(15, updatedSession.timeout)
    }

    @Test
    fun testShowAddDialog() {
        val viewModel = MainScreenViewModel()
        val sessionId = viewModel.sessions.value[0].id
        
        viewModel.showAddDialog(sessionId, true)
        assertTrue(viewModel.sessions.value[0].showAddDialog)
        
        viewModel.showAddDialog(sessionId, false)
        assertTrue(!viewModel.sessions.value[0].showAddDialog)
    }
}
