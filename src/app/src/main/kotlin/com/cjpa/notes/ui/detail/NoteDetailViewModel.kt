package com.cjpa.notes.ui.detail

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.ui.notes.NoteStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class NoteDetailUiState(
    val isLoading: Boolean = true,
    val remoteId: String? = null,
    val createdAt: Long = 0L,
    val title: String? = null,
    val status: NoteStatus = NoteStatus.OPEN,
    val durationMs: Long = 0L,
    val processingStatus: String = "queued",
    val processingError: String? = null,
    val markdown: String = "",
    val canSave: Boolean = false,
    val isSaving: Boolean = false,
    val errorMessage: String? = null
)

@HiltViewModel
class NoteDetailViewModel @Inject constructor(
    private val notesRepository: NotesRepository,
    savedStateHandle: SavedStateHandle
) : ViewModel() {

    private val localId: String = checkNotNull(savedStateHandle["noteId"])

    private val _uiState = MutableStateFlow(NoteDetailUiState())
    val uiState: StateFlow<NoteDetailUiState> = _uiState.asStateFlow()

    /**
     * Once the user starts typing we stop letting the background refresh (or
     * any other Room write) overwrite the editable markdown field - tracked
     * with this flag rather than relying on Compose recomposition timing.
     */
    private var isDirty = false

    init {
        viewModelScope.launch {
            notesRepository.observeNote(localId).collect { entity ->
                if (entity == null) return@collect
                _uiState.update { current ->
                    current.copy(
                        isLoading = false,
                        remoteId = entity.remoteId,
                        createdAt = entity.createdAt,
                        title = entity.title,
                        status = NoteStatus.fromWireValue(entity.status),
                        durationMs = entity.durationMs,
                        processingStatus = entity.processingStatus,
                        processingError = entity.processingError,
                        markdown = if (isDirty) current.markdown else entity.transcriptMd.orEmpty()
                    )
                }
            }
        }
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            try {
                notesRepository.refreshNoteDetail(localId)
            } catch (e: Exception) {
                _uiState.update { it.copy(errorMessage = "Couldn't refresh: ${e.message ?: "unknown error"}") }
            }
        }
    }

    fun onMarkdownChanged(newValue: String) {
        isDirty = true
        _uiState.update { it.copy(markdown = newValue, canSave = true) }
    }

    fun save() {
        val state = _uiState.value
        val remoteId = state.remoteId
        if (remoteId == null) {
            _uiState.update { it.copy(errorMessage = "This note hasn't finished uploading yet — try again once it's uploaded.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSaving = true) }
            val success = notesRepository.updateTranscript(localId, remoteId, state.markdown)
            if (success) {
                isDirty = false
                _uiState.update { it.copy(isSaving = false, canSave = false) }
            } else {
                _uiState.update { it.copy(isSaving = false, errorMessage = "Save failed — try again.") }
            }
        }
    }

    fun errorMessageShown() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
