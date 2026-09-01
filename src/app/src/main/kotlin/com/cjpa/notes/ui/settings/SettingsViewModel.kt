package com.cjpa.notes.ui.settings

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.cjpa.notes.data.remote.resolveServerUrl
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.data.repository.SettingsRepository
import com.cjpa.notes.ui.notes.NoteStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val baseUrl: String = "",
    val apiToken: String = "",
    val enabledStatuses: Set<NoteStatus> = emptySet(),
    val saved: Boolean = false,
    val googleCalendarLinked: Boolean = false,
    val isCheckingGoogleLink: Boolean = false
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository,
    private val notesRepository: NotesRepository,
    @ApplicationContext private val appContext: Context
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(
            baseUrl = settingsRepository.getBaseUrl().orEmpty(),
            apiToken = settingsRepository.getApiToken().orEmpty(),
            enabledStatuses = settingsRepository.getStatusFilter().map { NoteStatus.fromWireValue(it) }.toSet()
        )
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        refreshGoogleLinkStatus()
    }

    fun refreshGoogleLinkStatus() {
        if (!settingsRepository.state.value.isConfigured) return
        viewModelScope.launch {
            _uiState.update { it.copy(isCheckingGoogleLink = true) }
            val linked = notesRepository.isGoogleCalendarLinked()
            _uiState.update { it.copy(googleCalendarLinked = linked, isCheckingGoogleLink = false) }
        }
    }

    /** Opens the backend's OAuth start URL in the system browser to link a Google account. */
    fun linkGoogleCalendar() {
        val state = _uiState.value
        val startUrl = resolveServerUrl(state.baseUrl.trim(), "/api/google/auth/start") ?: return
        val url = "$startUrl?token=${Uri.encode(state.apiToken.trim())}"
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        appContext.startActivity(intent)
    }

    fun onBaseUrlChanged(value: String) {
        _uiState.update { it.copy(baseUrl = value, saved = false) }
    }

    fun onApiTokenChanged(value: String) {
        _uiState.update { it.copy(apiToken = value, saved = false) }
    }

    fun onStatusFilterToggled(status: NoteStatus, checked: Boolean) {
        _uiState.update { current ->
            val updated = if (checked) current.enabledStatuses + status else current.enabledStatuses - status
            current.copy(enabledStatuses = updated, saved = false)
        }
    }

    fun save() {
        val state = _uiState.value
        settingsRepository.saveSettings(
            baseUrl = state.baseUrl.trim(),
            apiToken = state.apiToken.trim(),
            statusFilter = state.enabledStatuses.map { it.wireValue }.toSet()
        )
        _uiState.update { it.copy(saved = true) }
        refreshGoogleLinkStatus()
    }
}
