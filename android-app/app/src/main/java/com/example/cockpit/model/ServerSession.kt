package com.example.cockpit.model

import java.util.UUID

sealed interface ConnectionState {
    object Idle : ConnectionState
    object Connecting : ConnectionState
    object Connected : ConnectionState
    data class Error(val message: String) : ConnectionState
}

data class ServerSession(
    val id: String = UUID.randomUUID().toString(),
    val host: String = "atmos.openschc.net",
    val port: Int? = 5683,
    val timeout: Int = 10,
    val connectionState: ConnectionState = ConnectionState.Idle,
    val transducers: List<Transducer> = emptyList(),
    val showAddDialog: Boolean = false
)
