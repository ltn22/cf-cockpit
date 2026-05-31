package com.example.cockpit.ui.main

import androidx.compose.animation.core.*
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation3.runtime.NavKey
import com.example.cockpit.model.ConnectionState
import com.example.cockpit.model.ServerSession
import com.example.cockpit.model.Transducer

// Premium harmonious dark palette colors
val DeepBackground = Color(0xFF0F0F1A)
val CardBackground = Color(0xFF19192C)
val BorderColor = Color(0xFF2E2E4B)
val TextPrimary = Color(0xFFFFFFFF)
val TextSecondary = Color(0xFF8C8CA8)
val AccentCyan = Color(0xFF00F0FF)
val AccentPurple = Color(0xFF9D4EDD)
val NeonGreen = Color(0xFF39FF14)
val NeonRed = Color(0xFFFF3333)

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun MainScreen(
    onItemClick: (NavKey) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: MainScreenViewModel = viewModel()
) {
    val sessions by viewModel.sessions.collectAsStateWithLifecycle()
    val pagerState = rememberPagerState(pageCount = { sessions.size })

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    val currentPage = pagerState.currentPage
                    val currentSession = sessions.getOrNull(currentPage)
                    val titleText = if (currentSession != null && currentSession.connectionState is ConnectionState.Connected) {
                        "Connected: ${currentSession.host}"
                    } else {
                        "Cockpit IoT Client"
                    }
                    Text(
                        text = titleText,
                        fontWeight = FontWeight.Bold,
                        color = TextPrimary
                    )
                },
                actions = {
                    val currentPage = pagerState.currentPage
                    val currentSession = sessions.getOrNull(currentPage)
                    if (currentSession != null && currentSession.connectionState is ConnectionState.Connected) {
                        IconButton(onClick = { viewModel.disconnect(currentSession.id) }) {
                            Text("❌", color = NeonRed, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = DeepBackground,
                    titleContentColor = TextPrimary
                )
            )
        },
        containerColor = DeepBackground
    ) { innerPadding ->
        Column(
            modifier = modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // Horizontal viewpager for servers
            HorizontalPager(
                state = pagerState,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
            ) { page ->
                val session = sessions[page]
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 16.dp)
                ) {
                    when (val state = session.connectionState) {
                        is ConnectionState.Idle -> {
                            // Pulsing central plus button screen
                            ServerPlusScreen(
                                session = session,
                                onAddClick = { viewModel.showAddDialog(session.id, true) }
                            )

                            // Glassmorphic Connection Dialog
                            if (session.showAddDialog) {
                                AddServerDialog(
                                    session = session,
                                    onDismiss = { viewModel.showAddDialog(session.id, false) },
                                    onConnect = { host, port, timeout ->
                                        viewModel.updateHost(session.id, host)
                                        viewModel.updatePort(session.id, port)
                                        viewModel.updateTimeout(session.id, timeout)
                                        viewModel.bootstrap(session.id)
                                    }
                                )
                            }
                        }
                        is ConnectionState.Error -> {
                            // Dedicated Error screen for failed connections
                            ServerErrorScreen(
                                session = session,
                                onRetryClick = { viewModel.bootstrap(session.id) },
                                onEditClick = { viewModel.showAddDialog(session.id, true) }
                            )

                            // Glassmorphic Connection Dialog
                            if (session.showAddDialog) {
                                AddServerDialog(
                                    session = session,
                                    onDismiss = { viewModel.showAddDialog(session.id, false) },
                                    onConnect = { host, port, timeout ->
                                        viewModel.updateHost(session.id, host)
                                        viewModel.updatePort(session.id, port)
                                        viewModel.updateTimeout(session.id, timeout)
                                        viewModel.bootstrap(session.id)
                                    }
                                )
                            }
                        }
                        is ConnectionState.Connecting -> {
                            // Loading state
                            Box(
                                modifier = Modifier.fillMaxSize(),
                                contentAlignment = Alignment.Center
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    CircularProgressIndicator(
                                        color = AccentCyan,
                                        modifier = Modifier.size(48.dp),
                                        strokeWidth = 4.dp
                                    )
                                    Spacer(modifier = Modifier.height(16.dp))
                                    Text(
                                        text = "Connecting to ${session.host}...",
                                        color = AccentCyan,
                                        fontWeight = FontWeight.SemiBold,
                                        fontSize = 16.sp
                                    )
                                }
                            }
                        }
                        is ConnectionState.Connected -> {
                            var activeGraphTransducer by remember { mutableStateOf<Transducer?>(null) }
                            var activeValuesTransducer by remember { mutableStateOf<Transducer?>(null) }
                            var configHistoryTransducer by remember { mutableStateOf<Transducer?>(null) }

                            SensorDashboardGrid(
                                transducers = session.transducers,
                                onSensorClick = { transducer ->
                                    viewModel.fetchSensorValue(session.id, transducer)
                                },
                                onSensorLongClick = { transducer ->
                                    if (transducer.isObserving) {
                                        activeValuesTransducer = transducer
                                    } else {
                                        configHistoryTransducer = transducer
                                    }
                                },
                                onStatsClick = { transducer ->
                                    viewModel.toggleStatsView(session.id, transducer)
                                },
                                onGraphClick = { transducer ->
                                    activeGraphTransducer = transducer
                                }
                            )

                            activeGraphTransducer?.let { transducer ->
                                val liveTransducer = session.transducers.find { it.id == transducer.id && it.typeSid == transducer.typeSid } ?: transducer
                                TimeSeriesGraphDialog(
                                    transducer = liveTransducer,
                                    onDismiss = { activeGraphTransducer = null },
                                    onShowValues = {
                                        activeGraphTransducer = null
                                        activeValuesTransducer = liveTransducer
                                    }
                                )
                            }

                            activeValuesTransducer?.let { transducer ->
                                val liveTransducer = session.transducers.find { it.id == transducer.id && it.typeSid == transducer.typeSid } ?: transducer
                                TimeSeriesValuesDialog(
                                    transducer = liveTransducer,
                                    onDismiss = { activeValuesTransducer = null },
                                    onStopObservation = {
                                        viewModel.toggleTimeSeriesObservation(session.id, liveTransducer)
                                    },
                                    onShowGraph = {
                                        activeValuesTransducer = null
                                        activeGraphTransducer = liveTransducer
                                    }
                                )
                            }

                            configHistoryTransducer?.let { transducer ->
                                HistoryConfigDialog(
                                    transducer = transducer,
                                    onDismiss = { configHistoryTransducer = null },
                                    onSubmit = { step, maxSamples, encoding, checkInterval ->
                                        viewModel.toggleTimeSeriesObservation(
                                            sessionId = session.id,
                                            transducer = transducer,
                                            step = step,
                                            maxSamples = maxSamples,
                                            encoding = encoding,
                                            checkInterval = checkInterval
                                        )
                                        configHistoryTransducer = null
                                    }
                                )
                            }
                        }
                    }
                }
            }

            // Dot indicators showing pages count at the bottom
            if (sessions.size > 1) {
                Row(
                    horizontalArrangement = Arrangement.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(bottom = 16.dp)
                ) {
                    repeat(sessions.size) { i ->
                        val active = pagerState.currentPage == i
                        Box(
                            modifier = Modifier
                                .padding(horizontal = 4.dp)
                                .size(if (active) 8.dp else 6.dp)
                                .clip(RoundedCornerShape(50))
                                .background(if (active) AccentCyan else TextSecondary.copy(alpha = 0.5f))
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun ServerPlusScreen(
    session: ServerSession,
    onAddClick: () -> Unit
) {
    val infiniteTransition = rememberInfiniteTransition(label = "GlowAnimation")
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 1.0f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "ScalePulse"
    )
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 0.1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "AlphaPulse"
    )

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {


        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier.size(160.dp)
        ) {
            // Pulsing outer glow ring
            Box(
                modifier = Modifier
                    .size(100.dp)
                    .scale(pulseScale)
                    .border(
                        width = 4.dp,
                        color = AccentCyan.copy(alpha = pulseAlpha),
                        shape = RoundedCornerShape(50)
                    )
            )

            // Main glowing central plus button
            Box(
                modifier = Modifier
                    .size(100.dp)
                    .clip(RoundedCornerShape(50))
                    .background(CardBackground)
                    .border(
                        2.dp,
                        Brush.horizontalGradient(listOf(AccentCyan, AccentPurple)),
                        RoundedCornerShape(50)
                    )
                    .clickable(onClick = onAddClick),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "+",
                    color = AccentCyan,
                    fontSize = 48.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.offset(y = (-3).dp) // visual adjustment
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = "Add CoAP Server",
            color = TextPrimary,
            fontWeight = FontWeight.Bold,
            fontSize = 18.sp
        )
        Text(
            text = "Tap + to monitor a machine",
            color = TextSecondary,
            fontSize = 14.sp,
            modifier = Modifier.padding(top = 4.dp)
        )
    }
}

@Composable
fun HistoryConfigDialog(
    transducer: Transducer,
    onDismiss: () -> Unit,
    onSubmit: (Long, Long, Long, Long) -> Unit
) {
    var step by remember { mutableStateOf("60000") }
    var maxSamples by remember { mutableStateOf("10") }
    var checkInterval by remember { mutableStateOf("10") }
    var encodingDelta by remember { mutableStateOf(true) } // true = delta (1), false = plain (0)

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Configure History - ${transducer.typeName}",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 18.sp
            )
        },
        text = {
            Column(
                verticalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.padding(top = 8.dp)
            ) {
                OutlinedTextField(
                    value = step,
                    onValueChange = { step = it },
                    label = { Text("Step (milliseconds)", color = TextSecondary) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                OutlinedTextField(
                    value = maxSamples,
                    onValueChange = { maxSamples = it },
                    label = { Text("Max Samples", color = TextSecondary) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                OutlinedTextField(
                    value = checkInterval,
                    onValueChange = { checkInterval = it },
                    label = { Text("Check Interval (messages)", color = TextSecondary) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                Text(
                    text = "Encoding Mode",
                    color = TextSecondary,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold
                )

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (encodingDelta) AccentCyan.copy(alpha = 0.2f) else DeepBackground)
                            .border(
                                1.dp,
                                if (encodingDelta) AccentCyan else BorderColor,
                                RoundedCornerShape(8.dp)
                            )
                            .clickable { encodingDelta = true }
                            .padding(vertical = 10.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "Delta Encodé",
                            color = if (encodingDelta) AccentCyan else TextSecondary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp
                        )
                    }

                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .clip(RoundedCornerShape(8.dp))
                            .background(if (!encodingDelta) AccentCyan.copy(alpha = 0.2f) else DeepBackground)
                            .border(
                                1.dp,
                                if (!encodingDelta) AccentCyan else BorderColor,
                                RoundedCornerShape(8.dp)
                            )
                            .clickable { encodingDelta = false }
                            .padding(vertical = 10.dp),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "Brut (Plain)",
                            color = if (!encodingDelta) AccentCyan else TextSecondary,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp
                        )
                    }
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val sVal = step.toLongOrNull() ?: 60000L
                    val mVal = maxSamples.toLongOrNull() ?: 10L
                    val cVal = checkInterval.toLongOrNull() ?: 10L
                    val eVal = if (encodingDelta) 1L else 0L
                    onSubmit(sVal, mVal, eVal, cVal)
                },
                colors = ButtonDefaults.buttonColors(containerColor = AccentPurple),
                shape = RoundedCornerShape(8.dp)
            ) {
                Text("Start Observation", fontWeight = FontWeight.Bold, color = TextPrimary)
            }
        },
        dismissButton = {
            Button(
                onClick = onDismiss,
                colors = ButtonDefaults.buttonColors(containerColor = DeepBackground),
                shape = RoundedCornerShape(8.dp),
                border = BorderStroke(1.dp, BorderColor)
            ) {
                Text("Cancel", fontWeight = FontWeight.Bold, color = TextSecondary)
            }
        },
        containerColor = CardBackground,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.border(1.dp, BorderColor, RoundedCornerShape(16.dp))
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AddServerDialog(
    session: ServerSession,
    onDismiss: () -> Unit,
    onConnect: (String, String, String) -> Unit
) {
    var host by remember { mutableStateOf(session.host) }
    var port by remember { mutableStateOf(session.port?.toString() ?: "5683") }
    var timeout by remember { mutableStateOf(session.timeout.toString()) }

    val context = androidx.compose.ui.platform.LocalContext.current
    val resolvedSid = remember {
        com.example.cockpit.util.CoreconfHelper.getBootstrapSid(context)
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                text = "Connect to Machine",
                color = TextPrimary,
                fontWeight = FontWeight.Bold,
                fontSize = 18.sp
            )
        },
        text = {
            Column(
                verticalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.padding(top = 8.dp)
            ) {
                // Display the resolved SID obtained via pycoreconf
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(DeepBackground)
                        .border(1.dp, AccentCyan.copy(alpha = 0.3f), RoundedCornerShape(8.dp))
                        .padding(10.dp)
                ) {
                    Column {
                        Text(
                            text = "Resolved SID (via pycoreconf)",
                            color = AccentCyan,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 1.sp
                        )
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "/coreconf-m2m:transducers/transducer -> $resolvedSid",
                            color = TextPrimary,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Medium
                        )
                    }
                }
                OutlinedTextField(
                    value = host,
                    onValueChange = { host = it },
                    label = { Text("Server IP or Domain name", color = TextSecondary) },
                    singleLine = true,
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                OutlinedTextField(
                    value = port,
                    onValueChange = { port = it },
                    label = { Text("Port", color = TextSecondary) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )

                OutlinedTextField(
                    value = timeout,
                    onValueChange = { timeout = it },
                    label = { Text("Timeout (seconds)", color = TextSecondary) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = TextPrimary,
                        unfocusedTextColor = TextPrimary,
                        focusedBorderColor = AccentCyan,
                        unfocusedBorderColor = BorderColor,
                        focusedContainerColor = DeepBackground,
                        unfocusedContainerColor = DeepBackground
                    ),
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onConnect(host, port, timeout) },
                colors = ButtonDefaults.buttonColors(containerColor = AccentPurple),
                shape = RoundedCornerShape(8.dp),
                modifier = Modifier.border(
                    width = 1.dp,
                    brush = Brush.horizontalGradient(listOf(AccentCyan, AccentPurple)),
                    shape = RoundedCornerShape(8.dp)
                )
            ) {
                Text("Connect", fontWeight = FontWeight.Bold, color = TextPrimary)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancel", color = TextSecondary)
            }
        },
        containerColor = CardBackground,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.border(1.dp, BorderColor, RoundedCornerShape(16.dp))
    )
}

@Composable
fun SensorDashboardGrid(
    transducers: List<Transducer>,
    onSensorClick: (Transducer) -> Unit,
    onSensorLongClick: (Transducer) -> Unit,
    onStatsClick: (Transducer) -> Unit,
    onGraphClick: (Transducer) -> Unit
) {
    if (transducers.isEmpty()) {
        Box(
            modifier = Modifier.fillMaxSize(),
            contentAlignment = Alignment.Center
        ) {
            Text("No transducers discovered on this server.", color = TextSecondary)
        }
    } else {
        LazyVerticalGrid(
            columns = GridCells.Adaptive(minSize = 160.dp),
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(top = 16.dp, bottom = 24.dp)
        ) {
            items(transducers, key = { "${it.typeSid}-${it.id}" }) { transducer ->
                SensorCard(
                    transducer = transducer,
                    onClick = { onSensorClick(transducer) },
                    onLongClick = { onSensorLongClick(transducer) },
                    onStatsClick = { onStatsClick(transducer) },
                    onGraphClick = { onGraphClick(transducer) }
                )
            }
        }
    }
}

@Composable
fun SensorCard(
    transducer: Transducer,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
    onStatsClick: () -> Unit,
    onGraphClick: () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val isPressed by interactionSource.collectIsPressedAsState()

    val scale by animateFloatAsState(
        targetValue = if (isPressed) 0.95f else 1.0f,
        label = "PressScaleAnimation"
    )

    Card(
        colors = CardDefaults.cardColors(
            containerColor = CardBackground
        ),
        modifier = Modifier
            .fillMaxWidth()
            .height(160.dp)
            .scale(scale)
            .border(1.dp, BorderColor, RoundedCornerShape(12.dp))
            .shadow(4.dp, RoundedCornerShape(12.dp))
            .clip(RoundedCornerShape(12.dp))
            .combinedClickable(
                interactionSource = interactionSource,
                indication = LocalIndication.current,
                onClick = onClick,
                onLongClick = onLongClick
            )
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp),
            verticalArrangement = Arrangement.SpaceBetween,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            // Header: Sensor Name & ID
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = transducer.typeName,
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    textAlign = TextAlign.Center
                )
                Text(
                    text = "ID: #${transducer.id} | SID: ${transducer.typeSid}",
                    color = TextSecondary,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }

            // Value or Stats Display
            Box(
                modifier = Modifier.weight(1f),
                contentAlignment = Alignment.Center
            ) {
                if (transducer.isLoading || transducer.isStatsLoading) {
                    CircularProgressIndicator(
                        color = AccentCyan,
                        modifier = Modifier.size(24.dp),
                        strokeWidth = 2.dp
                    )
                } else if (transducer.showStats) {
                    val stats = transducer.statistics
                    if (stats != null) {
                        Column(
                            verticalArrangement = Arrangement.spacedBy(3.dp),
                            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp)
                        ) {
                            val format = "%.${transducer.precision}f"
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                MiniStatLabel("Min", String.format(format, stats["min"] ?: 0.0))
                                MiniStatLabel("Max", String.format(format, stats["max"] ?: 0.0))
                            }
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                MiniStatLabel("Mean", String.format(format, stats["mean"] ?: 0.0))
                                MiniStatLabel("Med", String.format(format, stats["median"] ?: 0.0))
                            }
                            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                MiniStatLabel("σ", String.format(format, stats["stdev"] ?: 0.0))
                                MiniStatLabel("N", String.format("%.0f", stats["sampleCount"] ?: 0.0))
                            }
                        }
                    } else {
                        Text("No stats available", color = TextSecondary, fontSize = 11.sp)
                    }
                } else {
                    val valueText = if (transducer.value != null) {
                        String.format("%.${transducer.precision}f", transducer.value)
                    } else {
                        "---"
                    }
                    Text(
                        text = "$valueText ${transducer.unit}",
                        color = if (transducer.value != null) AccentCyan else TextSecondary,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.ExtraBold,
                        textAlign = TextAlign.Center
                    )
                }
            }

            // Bottom Action Bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                IconButton(
                    onClick = onStatsClick,
                    modifier = Modifier
                        .size(24.dp)
                        .background(if (transducer.showStats) AccentCyan.copy(alpha = 0.15f) else Color.Transparent, RoundedCornerShape(4.dp))
                        .border(if (transducer.showStats) 0.5.dp else 0.dp, if (transducer.showStats) AccentCyan.copy(alpha = 0.5f) else Color.Transparent, RoundedCornerShape(4.dp))
                ) {
                    Text(
                        text = "📊",
                        fontSize = 12.sp
                    )
                }

                Text(
                    text = if (transducer.isObserving) {
                        val count = transducer.timeSeries.size
                        if (count == 1) "1 sample" else "$count samples"
                    } else "Hold to Observe",
                    color = if (transducer.isObserving) AccentCyan else TextSecondary,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Medium
                )

                if (transducer.isObserving) {
                    val infiniteTransition = rememberInfiniteTransition(label = "HourglassTransition")
                    val rotation by infiniteTransition.animateFloat(
                        initialValue = 0f,
                        targetValue = 360f,
                        animationSpec = infiniteRepeatable(
                            animation = tween(2500, easing = LinearEasing),
                            repeatMode = RepeatMode.Restart
                        ),
                        label = "HourglassRotation"
                    )

                    IconButton(
                        onClick = onGraphClick,
                        modifier = Modifier
                            .size(24.dp)
                            .scale(1.1f)
                    ) {
                        Text(
                            text = "⏳",
                            fontSize = 13.sp,
                            modifier = Modifier.graphicsLayer(rotationZ = rotation)
                        )
                    }
                } else {
                    Spacer(modifier = Modifier.width(24.dp))
                }
            }
        }
    }
}

@Composable
fun MiniStatLabel(label: String, value: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(text = "$label:", color = TextSecondary, fontSize = 9.sp, fontWeight = FontWeight.SemiBold)
        Text(text = value, color = AccentCyan, fontSize = 9.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun TimeSeriesGraphDialog(
    transducer: Transducer,
    onDismiss: () -> Unit,
    onShowValues: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Column {
                Text(
                    text = "${transducer.typeName} - History Graph",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp
                )
                val pointCount = transducer.timeSeries.size
                Text(
                    text = "Observe Active ⏳ | N: $pointCount ${if (pointCount == 1) "point" else "points"}",
                    color = AccentCyan,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }
        },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(280.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                if (transducer.timeSeries.isEmpty()) {
                    CircularProgressIndicator(color = AccentCyan, modifier = Modifier.size(36.dp))
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "Waiting for first CoAP Observe notification...",
                        color = TextSecondary,
                        fontSize = 13.sp,
                        textAlign = TextAlign.Center
                    )
                } else {
                    Spacer(modifier = Modifier.height(10.dp))
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .border(1.dp, BorderColor, RoundedCornerShape(8.dp))
                            .background(DeepBackground.copy(alpha = 0.5f))
                            .padding(8.dp)
                    ) {
                        val textMeasurer = rememberTextMeasurer()
                        androidx.compose.foundation.Canvas(modifier = Modifier.fillMaxSize()) {
                            val points = transducer.timeSeries
                            if (points.isNotEmpty()) {
                                val minTimeRaw = points.first().timestamp
                                val maxTimeRaw = points.last().timestamp
                                val (minTime, maxTime, timeRange) = if (maxTimeRaw > minTimeRaw) {
                                    Triple(minTimeRaw, maxTimeRaw, (maxTimeRaw - minTimeRaw).toFloat())
                                } else {
                                    Triple(minTimeRaw - 30000L, minTimeRaw + 30000L, 60000f)
                                }

                                val minValRaw = points.minOf { it.value }.toFloat()
                                val maxValRaw = points.maxOf { it.value }.toFloat()
                                val (minVal, maxVal, valRange) = if (maxValRaw > minValRaw) {
                                    Triple(minValRaw, maxValRaw, maxValRaw - minValRaw)
                                } else {
                                    val span = if (minValRaw != 0f) Math.abs(minValRaw) * 0.2f else 1f
                                    Triple(minValRaw - span, minValRaw + span, span * 2f)
                                }

                                val labelPaddingLeft = 40.dp.toPx()
                                val labelPaddingBottom = 20.dp.toPx()
                                val chartWidth = size.width - labelPaddingLeft - 10.dp.toPx()
                                val chartHeight = size.height - labelPaddingBottom - 10.dp.toPx()
                                val chartLeft = labelPaddingLeft
                                val chartTop = 10.dp.toPx()

                                // Draw Y-axis grid lines & labels (3 rows)
                                val gridLineCount = 3
                                for (i in 0 until gridLineCount) {
                                    val ratio = i.toFloat() / (gridLineCount - 1)
                                    val y = chartTop + chartHeight * (1f - ratio)
                                    
                                    // Grid line
                                    drawLine(
                                        color = BorderColor.copy(alpha = 0.3f),
                                        start = Offset(chartLeft, y),
                                        end = Offset(chartLeft + chartWidth, y),
                                        strokeWidth = 1.dp.toPx()
                                    )

                                    // Y Label
                                    val labelVal = minVal + ratio * valRange
                                    val labelText = String.format("%.${transducer.precision}f", labelVal)
                                    drawText(
                                        textMeasurer = textMeasurer,
                                        text = labelText,
                                        style = androidx.compose.ui.text.TextStyle(
                                            color = TextSecondary,
                                            fontSize = 9.sp,
                                            fontWeight = FontWeight.Medium
                                        ),
                                        topLeft = Offset(2.dp.toPx(), y - 7.dp.toPx())
                                    )
                                }

                                // Draw X-axis grid lines & labels (2 columns: start and end time)
                                val gridColCount = 2
                                val sdf = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault())
                                for (i in 0 until gridColCount) {
                                    val ratio = i.toFloat() / (gridColCount - 1)
                                    val x = chartLeft + chartWidth * ratio
                                    
                                    // Grid line
                                    drawLine(
                                        color = BorderColor.copy(alpha = 0.3f),
                                        start = Offset(x, chartTop),
                                        end = Offset(x, chartTop + chartHeight),
                                        strokeWidth = 1.dp.toPx()
                                    )

                                    // X Label
                                    val labelTime = minTime + (ratio * timeRange).toLong()
                                    val labelText = sdf.format(java.util.Date(labelTime))
                                    val textLayoutResult = textMeasurer.measure(
                                        text = labelText,
                                        style = androidx.compose.ui.text.TextStyle(
                                            color = TextSecondary,
                                            fontSize = 8.sp,
                                            fontWeight = FontWeight.Medium
                                        )
                                    )
                                    val textWidth = textLayoutResult.size.width
                                    val textX = if (i == 0) x else if (i == gridColCount - 1) x - textWidth else x - textWidth / 2
                                    drawText(
                                        textLayoutResult = textLayoutResult,
                                        topLeft = Offset(textX, chartTop + chartHeight + 4.dp.toPx())
                                    )
                                }

                                // Draw chart path
                                if (points.size >= 2) {
                                    val path = Path()
                                    val fillPath = Path()

                                    points.forEachIndexed { idx, point ->
                                        val ratioX = if (timeRange > 0) (point.timestamp - minTime).toFloat() / timeRange else 0f
                                        val ratioY = if (valRange > 0) (point.value.toFloat() - minVal) / valRange else 0.5f

                                        val x = chartLeft + ratioX * chartWidth
                                        val y = chartTop + chartHeight * (1f - ratioY)

                                        if (idx == 0) {
                                            path.moveTo(x, y)
                                            fillPath.moveTo(x, chartTop + chartHeight)
                                            fillPath.lineTo(x, y)
                                        } else {
                                            path.lineTo(x, y)
                                            fillPath.lineTo(x, y)
                                        }
                                        if (idx == points.lastIndex) {
                                            fillPath.lineTo(x, chartTop + chartHeight)
                                            fillPath.close()
                                        }
                                    }

                                    drawPath(
                                        path = fillPath,
                                        brush = Brush.verticalGradient(
                                            colors = listOf(AccentCyan.copy(alpha = 0.3f), Color.Transparent)
                                        )
                                    )

                                    drawPath(
                                        path = path,
                                        color = AccentCyan,
                                        style = Stroke(
                                            width = 2.5.dp.toPx()
                                        )
                                    )
                                }

                                // Draw circles on points
                                points.forEach { point ->
                                    val ratioX = if (timeRange > 0) (point.timestamp - minTime).toFloat() / timeRange else 0f
                                    val ratioY = if (valRange > 0) (point.value.toFloat() - minVal) / valRange else 0.5f

                                    val x = chartLeft + ratioX * chartWidth
                                    val y = chartTop + chartHeight * (1f - ratioY)

                                    drawCircle(
                                        color = AccentCyan,
                                        radius = 3.dp.toPx(),
                                        center = Offset(x, y)
                                    )
                                    drawCircle(
                                        color = AccentPurple.copy(alpha = 0.6f),
                                        radius = 5.dp.toPx(),
                                        center = Offset(x, y),
                                        style = Stroke(width = 1.dp.toPx())
                                    )
                                }
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(10.dp))
                    
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        val minV = transducer.timeSeries.minOf { it.value }
                        val maxV = transducer.timeSeries.maxOf { it.value }
                        Text(
                            text = String.format("Min: %.${transducer.precision}f %s", minV, transducer.unit),
                            color = TextSecondary,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Medium
                        )
                        Text(
                            text = String.format("Max: %.${transducer.precision}f %s", maxV, transducer.unit),
                            color = AccentCyan,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
        },
        confirmButton = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = onShowValues,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentCyan),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Table", fontWeight = FontWeight.Bold, color = DeepBackground)
                }
                Button(
                    onClick = onDismiss,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentPurple),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Close", fontWeight = FontWeight.Bold, color = TextPrimary)
                }
            }
        },
        containerColor = CardBackground,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.border(1.dp, BorderColor, RoundedCornerShape(16.dp))
    )
}

@Composable
fun TimeSeriesValuesDialog(
    transducer: Transducer,
    onDismiss: () -> Unit,
    onStopObservation: () -> Unit,
    onShowGraph: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Column {
                Text(
                    text = "${transducer.typeName} - History Values",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 18.sp
                )
                val sampleCount = transducer.timeSeries.size
                Text(
                    text = "Observe Active ⏳ | N: $sampleCount ${if (sampleCount == 1) "sample" else "samples"}",
                    color = AccentCyan,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold
                )
            }
        },
        text = {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(300.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                if (transducer.timeSeries.isEmpty()) {
                    CircularProgressIndicator(color = AccentCyan, modifier = Modifier.size(36.dp))
                    Spacer(modifier = Modifier.height(12.dp))
                    Text(
                        text = "Waiting for first CoAP Observe notification...",
                        color = TextSecondary,
                        fontSize = 13.sp,
                        textAlign = TextAlign.Center
                    )
                } else {
                    Spacer(modifier = Modifier.height(10.dp))
                    
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(CardBackground, RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp))
                            .border(1.dp, BorderColor, RoundedCornerShape(topStart = 8.dp, topEnd = 8.dp))
                            .padding(horizontal = 6.dp, vertical = 4.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(text = "Index & Time", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1.2f))
                        Text(text = "Raw CBOR", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1.0f), textAlign = TextAlign.Center)
                        Text(text = "Decoded Value", color = TextSecondary, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1.2f), textAlign = TextAlign.End)
                    }

                    androidx.compose.foundation.lazy.LazyColumn(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .border(1.dp, BorderColor, RoundedCornerShape(bottomStart = 8.dp, bottomEnd = 8.dp))
                            .background(DeepBackground.copy(alpha = 0.5f))
                            .padding(horizontal = 4.dp, vertical = 4.dp),
                        verticalArrangement = Arrangement.spacedBy(2.dp)
                    ) {
                        val indexedPoints = transducer.timeSeries.mapIndexed { index, point -> Pair(index, point) }.reversed()
                        items(indexedPoints.size) { listIdx ->
                            val (cborIdx, point) = indexedPoints[listIdx]
                            val sdf = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault())
                            val timeStr = sdf.format(java.util.Date(point.timestamp))
                            
                            val rawText = if (point.isReference) {
                                "Ref: ${point.rawDelta.toInt()}"
                            } else {
                                "Δ: ${if (point.rawDelta >= 0) "+" else ""}${point.rawDelta.toInt()}"
                            }

                            val badgeBg = if (point.isReference) AccentPurple.copy(alpha = 0.25f) else AccentCyan.copy(alpha = 0.15f)
                            val badgeBorder = if (point.isReference) AccentPurple else AccentCyan.copy(alpha = 0.5f)
                            val badgeText = if (point.isReference) AccentPurple else AccentCyan

                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(CardBackground.copy(alpha = 0.5f), RoundedCornerShape(6.dp))
                                    .border(0.5.dp, BorderColor, RoundedCornerShape(6.dp))
                                    .padding(horizontal = 6.dp, vertical = 3.dp),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1.2f)) {
                                    Text(
                                        text = "[#$cborIdx] $timeStr",
                                        color = TextSecondary,
                                        fontSize = 10.sp,
                                        fontWeight = FontWeight.Medium
                                    )
                                }

                                Box(
                                    modifier = Modifier
                                        .weight(1.0f)
                                        .align(Alignment.CenterVertically),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Text(
                                        text = rawText,
                                        color = badgeText,
                                        fontSize = 9.sp,
                                        fontWeight = FontWeight.Bold,
                                        modifier = Modifier
                                            .background(badgeBg, RoundedCornerShape(4.dp))
                                            .border(0.5.dp, badgeBorder, RoundedCornerShape(4.dp))
                                            .padding(horizontal = 4.dp, vertical = 1.dp),
                                        textAlign = TextAlign.Center
                                    )
                                }

                                Text(
                                    text = String.format("%.${transducer.precision}f %s", point.value, transducer.unit),
                                    color = TextPrimary,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold,
                                    modifier = Modifier.weight(1.2f),
                                    textAlign = TextAlign.End
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Button(
                    onClick = {
                        onStopObservation()
                        onDismiss()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = NeonRed.copy(alpha = 0.85f)),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Stop", fontWeight = FontWeight.Bold, color = TextPrimary)
                }
                Button(
                    onClick = onShowGraph,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentCyan),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Graph", fontWeight = FontWeight.Bold, color = DeepBackground)
                }
                Button(
                    onClick = onDismiss,
                    colors = ButtonDefaults.buttonColors(containerColor = AccentPurple),
                    shape = RoundedCornerShape(8.dp)
                ) {
                    Text("Close", fontWeight = FontWeight.Bold, color = TextPrimary)
                }
            }
        },
        containerColor = CardBackground,
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.border(1.dp, BorderColor, RoundedCornerShape(16.dp))
    )
}

@Composable
fun ServerErrorScreen(
    session: ServerSession,
    onRetryClick: () -> Unit,
    onEditClick: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // Red warning icon / indicator
        Box(
            contentAlignment = Alignment.Center,
            modifier = Modifier
                .size(80.dp)
                .clip(RoundedCornerShape(50))
                .background(CardBackground)
                .border(2.dp, NeonRed, RoundedCornerShape(50))
        ) {
            Text(
                text = "⚠",
                color = NeonRed,
                fontSize = 36.sp,
                fontWeight = FontWeight.Bold
            )
        }

        Spacer(modifier = Modifier.height(24.dp))

        Text(
            text = "Connection Failed",
            color = TextPrimary,
            fontWeight = FontWeight.Bold,
            fontSize = 22.sp
        )

        Spacer(modifier = Modifier.height(8.dp))

        // Show details about the attempted server
        Text(
            text = "Target: ${session.host}:${session.port ?: 5683} (Timeout: ${session.timeout}s)",
            color = TextSecondary,
            fontSize = 14.sp,
            fontWeight = FontWeight.Medium
        )

        Spacer(modifier = Modifier.height(20.dp))

        // Glassmorphic neon-bordered error card
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(CardBackground)
                .border(1.dp, NeonRed.copy(alpha = 0.5f), RoundedCornerShape(12.dp))
                .padding(16.dp)
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = "ERROR DETAILS",
                    color = NeonRed,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 1.5.sp
                )
                Spacer(modifier = Modifier.height(8.dp))
                val errorMsg = (session.connectionState as? ConnectionState.Error)?.message ?: "Unknown Error"
                Text(
                    text = errorMsg,
                    color = TextPrimary,
                    fontSize = 14.sp,
                    textAlign = TextAlign.Center,
                    fontWeight = FontWeight.Normal
                )
            }
        }

        Spacer(modifier = Modifier.height(32.dp))

        // Glowy primary action button: Retry
        Button(
            onClick = onRetryClick,
            colors = ButtonDefaults.buttonColors(containerColor = AccentPurple),
            shape = RoundedCornerShape(10.dp),
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp)
                .border(
                    width = 1.dp,
                    brush = Brush.horizontalGradient(listOf(AccentCyan, AccentPurple)),
                    shape = RoundedCornerShape(10.dp)
                )
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center
            ) {
                Text(
                    text = "↺",
                    color = TextPrimary,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "Retry Connection",
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Secondary action button: Edit Server
        OutlinedButton(
            onClick = onEditClick,
            border = ButtonDefaults.outlinedButtonBorder.copy(brush = Brush.horizontalGradient(listOf(BorderColor, BorderColor))),
            shape = RoundedCornerShape(10.dp),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = TextSecondary),
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp)
        ) {
            Text(
                text = "Edit Server Settings",
                fontWeight = FontWeight.SemiBold,
                fontSize = 15.sp,
                color = AccentCyan
            )
        }
    }
}

