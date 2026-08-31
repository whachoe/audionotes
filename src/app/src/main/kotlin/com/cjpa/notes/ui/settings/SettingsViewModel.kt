package com.cjpa.notes.ui.settings

import androidx.lifecycle.ViewModel
import com.cjpa.notes.data.repository.SettingsRepository
import com.cjpa.notes.ui.notes.NoteStatus
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject

data class SettingsUiState(
    val baseUrl: String = "",
    val apiToken: String = "",
    val enabledStatuses: Set<NoteStatus> = emptySet(),
    val saved: Boolean = false
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(
            baseUrl = settingsRepository.getBaseUrl().orEmpty(),
            apiToken = settingsRepository.getApiToken().orEmpty(),
            enabledStatuses = settingsRepository.getStatusFilter().map { NoteStatus.fromWireValue(it) }.toSet()
        )
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

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
    }
}
