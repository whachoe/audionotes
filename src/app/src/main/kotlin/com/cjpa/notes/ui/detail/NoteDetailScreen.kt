package com.cjpa.notes.ui.detail

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cjpa.notes.ui.notes.StatusChip
import com.cjpa.notes.ui.notes.formatDuration
import com.cjpa.notes.ui.notes.formatTimestamp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NoteDetailScreen(
    onBack: () -> Unit,
    viewModel: NoteDetailViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(uiState.errorMessage) {
        val message = uiState.errorMessage
        if (message != null) {
            snackbarHostState.showSnackbar(message)
            viewModel.errorMessageShown()
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(uiState.title?.takeIf { it.isNotBlank() } ?: "Note") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                actions = {
                    TextButton(onClick = viewModel::save, enabled = uiState.canSave && !uiState.isSaving) {
                        Text(if (uiState.isSaving) "Saving…" else "Save")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        if (uiState.isLoading) {
            Box(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    StatusChip(status = uiState.status, onStatusSelected = {}, enabled = false)
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    text = "${formatTimestamp(uiState.createdAt)} • ${formatDuration(uiState.durationMs)}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                uiState.scheduledAtMs?.let { scheduledAtMs ->
                    Text(
                        text = "Scheduled: ${formatTimestamp(scheduledAtMs)}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                if (uiState.processingStatus != "done") {
                    Text(
                        text = "Processing (${uiState.processingStatus})…",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                }
                uiState.processingError?.let { error ->
                    Text(
                        text = "Processing error: $error",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                }
                if (uiState.audioUrl != null) {
                    Spacer(Modifier.height(12.dp))
                    AudioPlayerRow(
                        isPlaying = uiState.isPlaying,
                        isPreparing = uiState.isPlayerPreparing,
                        positionMs = uiState.playbackPositionMs,
                        durationMs = uiState.playbackDurationMs.takeIf { it > 0L } ?: uiState.durationMs,
                        onToggle = viewModel::togglePlayback,
                        onSeek = viewModel::seekTo
                    )
                }
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(
                    value = uiState.markdown,
                    onValueChange = viewModel::onMarkdownChanged,
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    label = { Text("Transcript (Markdown)") },
                    textStyle = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}

@Composable
private fun AudioPlayerRow(
    isPlaying: Boolean,
    isPreparing: Boolean,
    positionMs: Long,
    durationMs: Long,
    onToggle: () -> Unit,
    onSeek: (Long) -> Unit
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        FilledIconButton(onClick = onToggle, enabled = !isPreparing) {
            if (isPreparing) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
            } else {
                Icon(
                    imageVector = if (isPlaying) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                    contentDescription = if (isPlaying) "Pause" else "Play recording"
                )
            }
        }
        Spacer(Modifier.width(8.dp))
        Slider(
            value = positionMs.coerceAtMost(durationMs.coerceAtLeast(1L)).toFloat(),
            valueRange = 0f..durationMs.coerceAtLeast(1L).toFloat(),
            onValueChange = { onSeek(it.toLong()) },
            modifier = Modifier.weight(1f)
        )
        Spacer(Modifier.width(4.dp))
        Text(
            text = "${formatDuration(positionMs)} / ${formatDuration(durationMs)}",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
