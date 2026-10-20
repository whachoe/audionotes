package com.cjpa.notes.data.repository

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

data class SettingsState(
    val baseUrl: String?,
    val sessionToken: String?,
    val statusFilter: Set<String> = SettingsRepository.DEFAULT_STATUS_FILTER,
    val signedInEmail: String? = null
) {
    val isSignedIn: Boolean get() = !sessionToken.isNullOrBlank()
    val isConfigured: Boolean get() = !baseUrl.isNullOrBlank() && isSignedIn
}

/**
 * Server base URL + the Google-sign-in-issued session token, stored together
 * in one EncryptedSharedPreferences file (Phase 3: there's no manually-typed
 * API token anymore - signing in with Google IS how you get a session token).
 * Reads are synchronous on purpose: OkHttp interceptors (AuthInterceptor,
 * BaseUrlInterceptor) run on background threads already and need these values
 * without any extra coroutine/DataStore plumbing.
 */
@Singleton
class SettingsRepository @Inject constructor(
    @ApplicationContext context: Context
) {

    private val prefs: SharedPreferences = openOrResetEncryptedPrefs(context)

    /**
     * EncryptedSharedPreferences keeps its Tink keyset inside this prefs file
     * and the master key in the Android Keystore. Those two can get
     * separated - most easily by uninstalling and reinstalling, where
     * Android's auto-backup restores the file while the keystore key is gone
     * for good - and the mismatch surfaces as an exception out of create().
     *
     * Thrown from a @Singleton constructor that every other dependency hangs
     * off, it takes the whole Hilt graph down: the app then crashes on
     * launch, every launch, with no way back short of clearing app data.
     * Dropping the unreadable file instead costs a re-entered server URL and
     * a fresh sign-in - and those values were unrecoverable anyway, since
     * nothing can decrypt them without the key.
     */
    private fun openOrResetEncryptedPrefs(context: Context): SharedPreferences = try {
        openEncryptedPrefs(context)
    } catch (e: Exception) {
        Log.w(TAG, "Settings keyset unreadable - resetting $PREFS_FILE_NAME", e)
        context.deleteSharedPreferences(PREFS_FILE_NAME)
        openEncryptedPrefs(context)
    }

    private fun openEncryptedPrefs(context: Context): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            PREFS_FILE_NAME,
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    private val _state = MutableStateFlow(
        SettingsState(getBaseUrl(), getSessionToken(), getStatusFilter(), getSignedInEmail())
    )
    val state: StateFlow<SettingsState> = _state.asStateFlow()

    fun getBaseUrl(): String? = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL)

    fun getSessionToken(): String? = prefs.getString(KEY_SESSION_TOKEN, null)

    fun getSignedInEmail(): String? = prefs.getString(KEY_SIGNED_IN_EMAIL, null)

    /** Which note statuses (wire values) should show in the notes list. */
    fun getStatusFilter(): Set<String> =
        prefs.getStringSet(KEY_STATUS_FILTER, DEFAULT_STATUS_FILTER) ?: DEFAULT_STATUS_FILTER

    /** Server URL + status filter, independent of sign-in state. */
    fun saveServerSettings(baseUrl: String, statusFilter: Set<String>) {
        prefs.edit()
            .putString(KEY_BASE_URL, baseUrl)
            .putStringSet(KEY_STATUS_FILTER, statusFilter)
            .apply()
        _state.value = _state.value.copy(baseUrl = baseUrl, statusFilter = statusFilter)
    }

    /** Called once the Google sign-in deep link hands back a session token. */
    fun saveSession(sessionToken: String, email: String?) {
        prefs.edit()
            .putString(KEY_SESSION_TOKEN, sessionToken)
            .putString(KEY_SIGNED_IN_EMAIL, email)
            .apply()
        _state.value = _state.value.copy(sessionToken = sessionToken, signedInEmail = email)
    }

    /** Refreshes the cached display email without touching the session token itself. */
    fun updateSignedInEmail(email: String?) {
        prefs.edit().putString(KEY_SIGNED_IN_EMAIL, email).apply()
        _state.value = _state.value.copy(signedInEmail = email)
    }

    /** Local sign-out: clears the session only, keeps the server URL and status filter. */
    fun clearSession() {
        prefs.edit()
            .remove(KEY_SESSION_TOKEN)
            .remove(KEY_SIGNED_IN_EMAIL)
            .apply()
        _state.value = _state.value.copy(sessionToken = null, signedInEmail = null)
    }

    companion object {
        private const val TAG = "SettingsRepository"
        private const val PREFS_FILE_NAME = "cjpa_notes_secure_settings"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_SESSION_TOKEN = "session_token"
        private const val KEY_SIGNED_IN_EMAIL = "signed_in_email"
        private const val KEY_STATUS_FILTER = "status_filter"
        private const val DEFAULT_BASE_URL = "https://notes.copywaste.org"

        // Every status except Closed, by default.
        val DEFAULT_STATUS_FILTER: Set<String> = setOf("open", "in_progress", "todo")
    }
}
