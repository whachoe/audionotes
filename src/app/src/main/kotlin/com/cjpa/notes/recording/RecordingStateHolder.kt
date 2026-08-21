package com.cjpa.notes.recording

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * In-process, always-up-to-date recording state. The Activity/ViewModel and the
 * Glance widget (which runs in this same app process) both collect this
 * directly for instant UI updates while [RecordingService] is alive.
 */
object RecordingStateHolder {

    data class State(val isRecording: Boolean, val startTimeMs: Long?)

    private val _state = MutableStateFlow(State(isRecording = false, startTimeMs = null))
    val state: StateFlow<State> = _state.asStateFlow()

    fun setRecording(isRecording: Boolean, startTimeMs: Long?) {
        _state.value = State(isRecording, startTimeMs)
    }
}

/**
 * DataStore<Preferences> boolean mirroring "is a recording currently active".
 * This is the *same* DataStore instance used by [com.cjpa.notes.widget.RecordingGlanceStateDefinition],
 * so the widget can render the correct state on a cold start (app process
 * killed) before RecordingStateHolder's live in-memory state is available again.
 */
val Context.recordingPrefsDataStore by preferencesDataStore(name = RECORDING_PREFS_NAME)

const val RECORDING_PREFS_NAME = "recording_status"

object RecordingPrefsKeys {
    val IS_RECORDING: Preferences.Key<Boolean> = booleanPreferencesKey("is_recording")
}
