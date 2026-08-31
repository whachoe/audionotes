package com.cjpa.notes.ui.notes

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cjpa.notes.data.local.NoteEntity
import com.cjpa.notes.data.local.NoteSort
import com.cjpa.notes.data.local.NoteSortField
import com.cjpa.notes.data.local.SortOrder
import com.cjpa.notes.data.local.UploadState
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.data.repository.SettingsRepository
import com.cjpa.notes.recording.RecordingService
import com.cjpa.notes.recording.RecordingStateHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

data class NoteUiModel(
    val localId: String,
    val remoteId: String?,
    val createdAt: Long,
    val displayTitle: String,
    val status: NoteStatus,
    val durationMs: Long,
    val uploadState: UploadState,
    val uploadError: String?,
    val processingStatus: String
)

data class NotesListUiState(
    val notes: List<NoteUiModel> = emptyList(),
    val sort: NoteSort = NoteSort.DEFAULT,
    val isRefreshing: Boolean = false
)

private fun NoteEntity.toUiModel(): NoteUiModel {
    val displayTitle = title?.takeIf { it.isNotBlank() }
        ?: if (uploadState != UploadState.UPLOADED) "(untitled — uploading…)" else "(untitled)"
    return NoteUiModel(
        localId = localId,
        remoteId = remoteId,
        createdAt = createdAt,
        displayTitle = displayTitle,
        status = NoteStatus.fromWireValue(status),
        durationMs = durationMs,
        uploadState = uploadState,
        uploadError = uploadError,
        processingStatus = processingStatus
    )
}

@HiltViewModel
class NotesListViewModel @Inject constructor(
    private val notesRepository: NotesRepository,
    private val settingsRepository: SettingsRepository,
    @ApplicationContext private val appContext: Context
) : ViewModel() {

    private val sort = MutableStateFlow(NoteSort.DEFAULT)
    private val isRefreshing = MutableStateFlow(false)

    private val _snackbarMessages = MutableSharedFlow<String>()
    val snackbarMessages = _snackbarMessages.asSharedFlow()

    val recordingState: StateFlow<RecordingStateHolder.State> = RecordingStateHolder.state

    val uiState: StateFlow<NotesListUiState> = combine(
        sort.flatMapLatest { s -> notesRepository.observeNotes(s) },
        sort,
        isRefreshing,
        settingsRepository.state
    ) { notes, currentSort, refreshing, settings ->
        NotesListUiState(
            notes = notes.filter { it.status in settings.statusFilter }.map { it.toUiModel() },
            sort = currentSort,
            isRefreshing = refreshing
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), NotesListUiState())

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            isRefreshing.value = true
            try {
                notesRepository.refresh(sort.value)
            } catch (e: Exception) {
                _snackbarMessages.emit("Refresh failed: ${e.message ?: "unknown error"}")
            } finally {
                isRefreshing.value = false
            }
        }
    }

    fun onSortChanged(field: NoteSortField, order: SortOrder) {
        sort.value = NoteSort(field, order)
        refresh()
    }

    fun onStatusSelected(note: NoteUiModel, newStatus: NoteStatus) {
        viewModelScope.launch {
            val success = notesRepository.updateStatus(note.localId, newStatus.wireValue)
            if (!success) {
                _snackbarMessages.emit("Couldn't update status for \"${note.displayTitle}\"")
            }
        }
    }

    fun onRecordButtonClick() {
        val isRecording = RecordingStateHolder.state.value.isRecording
        val action = if (isRecording) RecordingService.ACTION_STOP_RECORDING else RecordingService.ACTION_START_RECORDING
        val intent = Intent(appContext, RecordingService::class.java).setAction(action)
        ContextCompat.startForegroundService(appContext, intent)
    }
}
