package com.cjpa.notes.ui.settings

import androidx.lifecycle.ViewModel
import com.cjpa.notes.data.repository.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject

data class SettingsUiState(
    val baseUrl: String = "",
    val apiToken: String = "",
    val saved: Boolean = false
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(
            baseUrl = settingsRepository.getBaseUrl().orEmpty(),
            apiToken = settingsRepository.getApiToken().orEmpty()
        )
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    fun onBaseUrlChanged(value: String) {
        _uiState.update { it.copy(baseUrl = value, saved = false) }
    }

    fun onApiTokenChanged(value: String) {
        _uiState.update { it.copy(apiToken = value, saved = false) }
    }

    fun save() {
        val state = _uiState.value
        settingsRepository.saveSettings(state.baseUrl.trim(), state.apiToken.trim())
        _uiState.update { it.copy(saved = true) }
    }
}
