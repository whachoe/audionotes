package com.cjpa.notes.ui.settings

import android.content.Context
import android.content.Intent
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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val baseUrl: String = "",
    val enabledStatuses: Set<NoteStatus> = emptySet(),
    val saved: Boolean = false,
    val isSignedIn: Boolean = false,
    val signedInEmail: String? = null,
    val isCheckingStatus: Boolean = false,
    val calendarLinked: Boolean = false,
    val errorMessage: String? = null
)

/**
 * Phase 3 (multi-user): there's no manually-entered API token anymore -
 * signing in with Google IS how you get a session token, and the same
 * consent screen also links Google Calendar. See google_auth.py on the
 * backend and NavGraph.kt's Settings deep link for the other halves of
 * this flow.
 */
@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsRepository: SettingsRepository,
    private val notesRepository: NotesRepository,
    @ApplicationContext private val appContext: Context,
    savedStateHandle: SavedStateHandle
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        SettingsUiState(
            baseUrl = settingsRepository.getBaseUrl().orEmpty(),
            enabledStatuses = settingsRepository.getStatusFilter().map { NoteStatus.fromWireValue(it) }.toSet(),
            isSignedIn = !settingsRepository.getSessionToken().isNullOrBlank(),
            signedInEmail = settingsRepository.getSignedInEmail()
        )
    )
    val uiState: StateFlow<SettingsUiState> = _uiState.asStateFlow()

    init {
        // Present only when this screen was opened via the Google sign-in
        // deep link (copywastenotes://auth?token=...), never on a plain
        // in-app navigation to Settings - see NavGraph.kt.
        val incomingToken = savedStateHandle.get<String>("token")
        if (!incomingToken.isNullOrBlank()) {
            completeSignIn(incomingToken)
        } else if (_uiState.value.isSignedIn) {
            refreshStatus()
        }
    }

    fun onBaseUrlChanged(value: String) {
        _uiState.update { it.copy(baseUrl = value, saved = false) }
    }

    fun onStatusFilterToggled(status: NoteStatus, checked: Boolean) {
        _uiState.update { current ->
            val updated = if (checked) current.enabledStatuses + status else current.enabledStatuses - status
            current.copy(enabledStatuses = updated, saved = false)
        }
    }

    fun save() {
        val state = _uiState.value
        settingsRepository.saveServerSettings(
            baseUrl = state.baseUrl.trim(),
            statusFilter = state.enabledStatuses.map { it.wireValue }.toSet()
        )
        _uiState.update { it.copy(saved = true) }
    }

    /** Opens the backend's combined sign-in + Calendar-authorization page in the system browser. */
    fun signIn() {
        val baseUrl = _uiState.value.baseUrl.trim()
        if (baseUrl.isBlank()) {
            _uiState.update { it.copy(errorMessage = "Enter a server URL first.") }
            return
        }
        // Persist the base URL now so it survives the round trip to the
        // browser even if Android kills this process while backgrounded.
        settingsRepository.saveServerSettings(baseUrl, _uiState.value.enabledStatuses.map { it.wireValue }.toSet())

        val startUrl = resolveServerUrl(baseUrl, "/api/google/auth/start")
        if (startUrl == null) {
            _uiState.update { it.copy(errorMessage = "That doesn't look like a valid server URL.") }
            return
        }
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(startUrl)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        appContext.startActivity(intent)
    }

    private fun completeSignIn(token: String) {
        settingsRepository.saveSession(sessionToken = token, email = null)
        _uiState.update { it.copy(isSignedIn = true, saved = true) }
        refreshStatus()
    }

    /** Confirms the session is live and refreshes the displayed email + Calendar-link status. */
    fun refreshStatus() {
        viewModelScope.launch {
            _uiState.update { it.copy(isCheckingStatus = true) }
            val status = notesRepository.fetchGoogleAuthStatus()
            if (status != null) {
                settingsRepository.updateSignedInEmail(status.email)
            }
            _uiState.update { current ->
                current.copy(
                    isCheckingStatus = false,
                    signedInEmail = status?.email ?: current.signedInEmail,
                    calendarLinked = status?.calendarLinked ?: current.calendarLinked
                )
            }
        }
    }

    fun signOut() {
        viewModelScope.launch {
            notesRepository.logout()
            settingsRepository.clearSession()
            _uiState.update {
                it.copy(isSignedIn = false, signedInEmail = null, calendarLinked = false, saved = false)
            }
        }
    }

    fun errorMessageShown() {
        _uiState.update { it.copy(errorMessage = null) }
    }
}
