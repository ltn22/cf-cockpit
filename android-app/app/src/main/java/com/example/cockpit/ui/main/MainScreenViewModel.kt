package com.example.cockpit.ui.main

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.cockpit.model.ConnectionState
import com.example.cockpit.model.ServerSession
import com.example.cockpit.model.Transducer
import com.example.cockpit.network.CoapService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainScreenViewModel : ViewModel() {
    private val _sessions = MutableStateFlow<List<ServerSession>>(listOf(ServerSession()))
    val sessions: StateFlow<List<ServerSession>> = _sessions.asStateFlow()

    private fun getSession(sessionId: String): ServerSession? {
        return _sessions.value.find { it.id == sessionId }
    }

    private fun updateSession(sessionId: String, transform: (ServerSession) -> ServerSession) {
        val list = _sessions.value.map { session ->
            if (session.id == sessionId) transform(session) else session
        }
        _sessions.value = list
    }

    fun updateHost(sessionId: String, newHost: String) {
        updateSession(sessionId) { it.copy(host = newHost) }
    }

    fun updatePort(sessionId: String, newPortStr: String) {
        val port = newPortStr.toIntOrNull()
        updateSession(sessionId) { it.copy(port = port) }
    }

    fun updateTimeout(sessionId: String, newTimeoutStr: String) {
        val timeout = newTimeoutStr.toIntOrNull() ?: 10
        updateSession(sessionId) { it.copy(timeout = timeout) }
    }

    fun showAddDialog(sessionId: String, show: Boolean) {
        updateSession(sessionId) { it.copy(showAddDialog = show) }
    }

    fun bootstrap(sessionId: String) {
        val session = getSession(sessionId) ?: return
        viewModelScope.launch {
            updateSession(sessionId) {
                it.copy(
                    connectionState = ConnectionState.Connecting,
                    showAddDialog = false,
                    transducers = emptyList()
                )
            }
            try {
                val list = CoapService.bootstrap(session.host, session.port, session.timeout)
                updateSession(sessionId) {
                    it.copy(
                        connectionState = ConnectionState.Connected,
                        transducers = list
                    )
                }
                
                // If the connected session was the only idle/error one, append a new empty session
                val current = _sessions.value
                val hasIdle = current.any { it.connectionState is ConnectionState.Idle }
                if (!hasIdle) {
                    _sessions.value = current + ServerSession()
                }
            } catch (e: Exception) {
                e.printStackTrace()
                updateSession(sessionId) {
                    it.copy(
                        connectionState = ConnectionState.Error(e.message ?: "Failed to connect")
                    )
                }
                
                // If the failed session was the only idle one, append a new empty session
                val current = _sessions.value
                val hasIdle = current.any { it.connectionState is ConnectionState.Idle }
                if (!hasIdle) {
                    _sessions.value = current + ServerSession()
                }
            }
        }
    }

    fun fetchSensorValue(sessionId: String, transducer: Transducer) {
        val session = getSession(sessionId) ?: return
        val currentTransducers = session.transducers.toMutableList()
        val index = currentTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
        if (index == -1) return

        currentTransducers[index] = currentTransducers[index].copy(isLoading = true)
        updateSession(sessionId) { it.copy(transducers = currentTransducers) }

        viewModelScope.launch {
            try {
                val value = CoapService.fetchValue(session.host, session.port, transducer, session.timeout)
                val activeSession = getSession(sessionId) ?: return@launch
                val updatedTransducers = activeSession.transducers.toMutableList()
                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                if (idx != -1) {
                    updatedTransducers[idx] = updatedTransducers[idx].copy(value = value, isLoading = false)
                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                }

                // Keep the fetched value displayed on the screen for exactly 1 minute, then clear it back to ---
                kotlinx.coroutines.delay(60000)
                val resetSession = getSession(sessionId) ?: return@launch
                val resetTransducers = resetSession.transducers.toMutableList()
                val rIdx = resetTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                if (rIdx != -1) {
                    // Only reset if the current value matches the one we set (avoids clearing a more recent fetch)
                    if (resetTransducers[rIdx].value == value) {
                        resetTransducers[rIdx] = resetTransducers[rIdx].copy(value = null)
                        updateSession(sessionId) { it.copy(transducers = resetTransducers) }
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                val activeSession = getSession(sessionId) ?: return@launch
                val updatedTransducers = activeSession.transducers.toMutableList()
                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                if (idx != -1) {
                    updatedTransducers[idx] = updatedTransducers[idx].copy(isLoading = false)
                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                }
            }
        }
    }

    fun disconnect(sessionId: String) {
        val current = _sessions.value.toMutableList()
        val index = current.indexOfFirst { it.id == sessionId }
        if (index == -1) return

        if (current.size == 1) {
            current[0] = ServerSession()
        } else {
            current.removeAt(index)
        }
        _sessions.value = current
    }

    private val activeObservations = mutableMapOf<String, org.eclipse.californium.core.CoapObserveRelation>()
    private val activeClients = mutableMapOf<String, org.eclipse.californium.core.CoapClient>()
    private val activeTokens = mutableMapOf<String, ByteArray>()

    fun toggleStatsView(sessionId: String, transducer: Transducer) {
        val session = getSession(sessionId) ?: return
        val currentTransducers = session.transducers.toMutableList()
        val index = currentTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
        if (index == -1) return

        val targetTransducer = currentTransducers[index]
        val nextShowStats = !targetTransducer.showStats
        currentTransducers[index] = targetTransducer.copy(showStats = nextShowStats)
        updateSession(sessionId) { it.copy(transducers = currentTransducers) }

        if (nextShowStats && targetTransducer.statistics == null) {
            fetchSensorStatistics(sessionId, targetTransducer)
        }
    }

    fun fetchSensorStatistics(sessionId: String, transducer: Transducer) {
        val session = getSession(sessionId) ?: return
        val currentTransducers = session.transducers.toMutableList()
        val index = currentTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
        if (index == -1) return

        currentTransducers[index] = currentTransducers[index].copy(isStatsLoading = true)
        updateSession(sessionId) { it.copy(transducers = currentTransducers) }

        viewModelScope.launch {
            try {
                val stats = CoapService.fetchStatistics(session.host, session.port, transducer, session.timeout)
                val activeSession = getSession(sessionId) ?: return@launch
                val updatedTransducers = activeSession.transducers.toMutableList()
                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                if (idx != -1) {
                    updatedTransducers[idx] = updatedTransducers[idx].copy(
                        statistics = stats,
                        isStatsLoading = false
                    )
                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                }
            } catch (e: Exception) {
                e.printStackTrace()
                val activeSession = getSession(sessionId) ?: return@launch
                val updatedTransducers = activeSession.transducers.toMutableList()
                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                if (idx != -1) {
                    updatedTransducers[idx] = updatedTransducers[idx].copy(isStatsLoading = false)
                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                }
            }
        }
    }

    fun toggleTimeSeriesObservation(
        sessionId: String,
        transducer: Transducer,
        step: Long = 60000L,
        maxSamples: Long = 10L,
        encoding: Long = 1L,
        checkInterval: Long = 10L
    ) {
        val session = getSession(sessionId) ?: return
        val currentTransducers = session.transducers.toMutableList()
        val index = currentTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
        if (index == -1) return

        val targetTransducer = currentTransducers[index]
        val obsKey = "${sessionId}-${transducer.typeSid}-${transducer.id}"

        if (targetTransducer.isObserving) {
            // Stop observation
            val token = activeTokens[obsKey]
            if (token != null) {
                viewModelScope.launch {
                    try {
                        CoapService.cancelObserveTimeSeries(session.host, session.port, targetTransducer, token)
                    } catch (e: Exception) {
                        e.printStackTrace()
                    }
                }
                activeTokens.remove(obsKey)
            }
            activeObservations.remove(obsKey)
            activeClients[obsKey]?.shutdown()
            activeClients.remove(obsKey)

            currentTransducers[index] = targetTransducer.copy(isObserving = false)
            updateSession(sessionId) { it.copy(transducers = currentTransducers) }
            android.util.Log.i("MainScreenViewModel", "Cancelled observation for key: $obsKey")
        } else {
            // Start observation by first running iPATCH in a coroutine, then establishing subscription
            currentTransducers[index] = targetTransducer.copy(isObserving = true, timeSeries = emptyList())
            updateSession(sessionId) { it.copy(transducers = currentTransducers) }

            viewModelScope.launch {
                try {
                    // 1. iPATCH to configure history parameters
                    CoapService.configureHistory(
                        host = session.host,
                        port = session.port,
                        transducer = targetTransducer,
                        timeoutSeconds = session.timeout,
                        step = step,
                        maxSamples = maxSamples,
                        encoding = encoding,
                        checkInterval = checkInterval
                    )

                    // 2. Generate a 2-byte token and subscribe to observe relation
                    val token = ByteArray(2)
                    java.util.Random().nextBytes(token)
                    activeTokens[obsKey] = token

                    val (client, relation) = CoapService.observeTimeSeries(
                        host = session.host,
                        port = session.port,
                        transducer = targetTransducer,
                        token = token,
                        onUpdate = { newPoints ->
                            viewModelScope.launch {
                                val activeSession = getSession(sessionId) ?: return@launch
                                val updatedTransducers = activeSession.transducers.toMutableList()
                                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                                if (idx != -1) {
                                    val mergedHistory = newPoints.takeLast(100)

                                    updatedTransducers[idx] = updatedTransducers[idx].copy(timeSeries = mergedHistory)
                                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                                }
                            }
                        },
                        onError = {
                            viewModelScope.launch {
                                val activeSession = getSession(sessionId) ?: return@launch
                                val updatedTransducers = activeSession.transducers.toMutableList()
                                val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                                if (idx != -1) {
                                    updatedTransducers[idx] = updatedTransducers[idx].copy(isObserving = false)
                                    updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                                }
                            }
                        }
                    )
                    activeObservations[obsKey] = relation
                    activeClients[obsKey] = client
                    android.util.Log.i("MainScreenViewModel", "Successfully started observation for key: $obsKey")
                } catch (e: Exception) {
                    e.printStackTrace()
                    // Restore UI state to not observing upon failure
                    val activeSession = getSession(sessionId) ?: return@launch
                    val updatedTransducers = activeSession.transducers.toMutableList()
                    val idx = updatedTransducers.indexOfFirst { it.id == transducer.id && it.typeSid == transducer.typeSid }
                    if (idx != -1) {
                        updatedTransducers[idx] = updatedTransducers[idx].copy(isObserving = false)
                        updateSession(sessionId) { it.copy(transducers = updatedTransducers) }
                    }
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        // Manually send FETCH observe cancellation for all active observations, then clear maps
        activeObservations.keys.forEach { obsKey ->
            val token = activeTokens[obsKey]
            val parts = obsKey.split("-")
            if (token != null && parts.size >= 3) {
                val sessionId = parts[0]
                val session = getSession(sessionId)
                if (session != null) {
                    val typeSid = parts[1].toLongOrNull() ?: 0L
                    val id = parts[2].toLongOrNull() ?: 0L
                    val transducer = session.transducers.find { it.id == id && it.typeSid == typeSid }
                    if (transducer != null) {
                        viewModelScope.launch {
                            try {
                                CoapService.cancelObserveTimeSeries(session.host, session.port, transducer, token)
                            } catch (e: Exception) {
                                e.printStackTrace()
                            }
                        }
                    }
                }
            }
        }
        activeObservations.clear()
        activeTokens.clear()
    }
}
