package com.cjpa.notes.ui.detail

import android.content.Context
import android.media.MediaPlayer
import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cjpa.notes.data.remote.resolveServerUrl
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.data.repository.SettingsRepository
import com.cjpa.notes.ui.notes.NoteStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.io.IOException
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
    val errorMessage: String? = null,
    val audioUrl: String? = null,
    val isPlaying: Boolean = false,
    val isPlayerPreparing: Boolean = false,
    val playbackPositionMs: Long = 0L,
    val playbackDurationMs: Long = 0L
)

@HiltViewModel
class NoteDetailViewModel @Inject constructor(
    private val notesRepository: NotesRepository,
    private val settingsRepository: SettingsRepository,
    @ApplicationContext private val appContext: Context,
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

    private var mediaPlayer: MediaPlayer? = null
    private var progressJob: Job? = null

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
                        markdown = if (isDirty) current.markdown else entity.transcriptMd.orEmpty(),
                        audioUrl = entity.audioUrl
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

    fun togglePlayback() {
        val player = mediaPlayer
        if (player == null) {
            startPlayback()
            return
        }
        if (_uiState.value.isPlaying) {
            player.pause()
            progressJob?.cancel()
            _uiState.update { it.copy(isPlaying = false) }
        } else {
            player.start()
            _uiState.update { it.copy(isPlaying = true) }
            startProgressLoop()
        }
    }

    fun seekTo(positionMs: Long) {
        mediaPlayer?.seekTo(positionMs.toInt())
        _uiState.update { it.copy(playbackPositionMs = positionMs) }
    }

    private fun startPlayback() {
        val relativeUrl = _uiState.value.audioUrl ?: return
        val absoluteUrl = resolveServerUrl(settingsRepository.getBaseUrl(), relativeUrl)
        if (absoluteUrl == null) {
            _uiState.update { it.copy(errorMessage = "Server not configured — check Settings.") }
            return
        }
        val token = settingsRepository.getApiToken()
        val headers = if (!token.isNullOrBlank()) mapOf("Authorization" to "Bearer $token") else emptyMap()

        _uiState.update { it.copy(isPlayerPreparing = true) }
        val player = MediaPlayer().apply {
            setOnPreparedListener {
                _uiState.update {
                    it.copy(
                        isPlayerPreparing = false,
                        isPlaying = true,
                        playbackDurationMs = duration.toLong().coerceAtLeast(0L)
                    )
                }
                start()
                startProgressLoop()
            }
            setOnCompletionListener {
                progressJob?.cancel()
                _uiState.update { it.copy(isPlaying = false, playbackPositionMs = 0L) }
                seekTo(0)
            }
            setOnErrorListener { _, _, _ ->
                progressJob?.cancel()
                _uiState.update {
                    it.copy(isPlayerPreparing = false, isPlaying = false, errorMessage = "Couldn't play the recording.")
                }
                true
            }
        }
        try {
            player.setDataSource(appContext, Uri.parse(absoluteUrl), headers)
            player.prepareAsync()
            mediaPlayer = player
        } catch (e: IOException) {
            player.release()
            _uiState.update { it.copy(isPlayerPreparing = false, errorMessage = "Couldn't play the recording.") }
        }
    }

    private fun startProgressLoop() {
        progressJob?.cancel()
        progressJob = viewModelScope.launch {
            val player = mediaPlayer ?: return@launch
            while (isActive) {
                _uiState.update { it.copy(playbackPositionMs = player.currentPosition.toLong()) }
                delay(200)
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        progressJob?.cancel()
        mediaPlayer?.release()
        mediaPlayer = null
    }
}
