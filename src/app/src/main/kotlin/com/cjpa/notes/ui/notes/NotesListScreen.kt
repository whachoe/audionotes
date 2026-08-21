package com.cjpa.notes.ui.notes

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.cjpa.notes.R
import com.cjpa.notes.data.local.UploadState
import kotlinx.coroutines.delay
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotesListScreen(
    onNoteClick: (String) -> Unit,
    onSettingsClick: () -> Unit,
    viewModel: NotesListViewModel = hiltViewModel()
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val recordingState by viewModel.recordingState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(Unit) {
        viewModel.snackbarMessages.collect { message ->
            snackbarHostState.showSnackbar(message)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.app_name)) },
                actions = {
                    IconButton(onClick = onSettingsClick) {
                        Icon(Icons.Filled.Settings, contentDescription = "Settings")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            RecordingFooterBar(
                isRecording = recordingState.isRecording,
                startTimeMs = recordingState.startTimeMs,
                onClick = viewModel::onRecordButtonClick
            )
        }
    ) { paddingValues ->
        PullToRefreshBox(
            isRefreshing = uiState.isRefreshing,
            onRefresh = viewModel::refresh,
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            if (uiState.notes.isEmpty() && !uiState.isRefreshing) {
                EmptyNotesMessage(modifier = Modifier.fillMaxSize())
            } else {
                LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(uiState.notes, key = { it.localId }) { note ->
                        NoteRow(
                            note = note,
                            onClick = { onNoteClick(note.localId) },
                            onStatusSelected = { newStatus -> viewModel.onStatusSelected(note, newStatus) }
                        )
                        HorizontalDivider()
                    }
                }
            }
        }
    }
}

@Composable
private fun EmptyNotesMessage(modifier: Modifier = Modifier) {
    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Text(
            text = "No notes yet. Tap the record button below to create your first note.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(32.dp)
        )
    }
}

@Composable
private fun NoteRow(
    note: NoteUiModel,
    onClick: () -> Unit,
    onStatusSelected: (NoteStatus) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = note.displayTitle,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = "${formatTimestamp(note.createdAt)} • ${formatDuration(note.durationMs)}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            UploadOrProcessingBadge(note)
        }
        Spacer(Modifier.width(12.dp))
        StatusChip(status = note.status, onStatusSelected = onStatusSelected)
    }
}

@Composable
private fun UploadOrProcessingBadge(note: NoteUiModel) {
    val text = when (note.uploadState) {
        UploadState.PENDING, UploadState.UPLOADING -> "Uploading…"
        UploadState.FAILED -> "Upload failed — tap to retry"
        UploadState.UPLOADED -> if (note.processingStatus != "done") "Processing…" else null
    }
    if (text != null) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            color = if (note.uploadState == UploadState.FAILED) {
                MaterialTheme.colorScheme.error
            } else {
                MaterialTheme.colorScheme.primary
            }
        )
    }
}

@Composable
private fun RecordingFooterBar(isRecording: Boolean, startTimeMs: Long?, onClick: () -> Unit) {
    var elapsedMs by remember { mutableLongStateOf(0L) }

    LaunchedEffect(isRecording, startTimeMs) {
        if (isRecording && startTimeMs != null) {
            while (true) {
                elapsedMs = System.currentTimeMillis() - startTimeMs
                delay(200)
            }
        } else {
            elapsedMs = 0L
        }
    }

    Surface(tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 16.dp)
        ) {
            FloatingActionButton(
                onClick = onClick,
                shape = CircleShape,
                containerColor = if (isRecording) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
                contentColor = if (isRecording) MaterialTheme.colorScheme.onError else MaterialTheme.colorScheme.onPrimary
            ) {
                Icon(
                    painter = painterResource(id = if (isRecording) R.drawable.ic_stop else R.drawable.ic_mic),
                    contentDescription = if (isRecording) "Stop recording" else "Start recording"
                )
            }
            Spacer(Modifier.height(6.dp))
            Text(
                text = if (isRecording) formatElapsed(elapsedMs) else "Start Recording",
                style = MaterialTheme.typography.labelMedium
            )
        }
    }
}

private val timestampFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM d, HH:mm").withZone(ZoneId.systemDefault())

internal fun formatTimestamp(epochMs: Long): String =
    timestampFormatter.format(Instant.ofEpochMilli(epochMs))

internal fun formatDuration(ms: Long): String {
    val totalSeconds = ms / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return String.format("%d:%02d", minutes, seconds)
}

internal fun formatElapsed(ms: Long): String {
    val totalSeconds = ms / 1000
    val minutes = totalSeconds / 60
    val seconds = totalSeconds % 60
    return String.format("%02d:%02d", minutes, seconds)
}
