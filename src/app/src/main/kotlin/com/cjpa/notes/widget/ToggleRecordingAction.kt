package com.cjpa.notes.widget

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import androidx.glance.GlanceId
import androidx.glance.action.ActionParameters
import androidx.glance.appwidget.action.ActionCallback
import com.cjpa.notes.recording.RecordingPrefsKeys
import com.cjpa.notes.recording.RecordingService
import com.cjpa.notes.recording.recordingPrefsDataStore
import kotlinx.coroutines.flow.first

/**
 * Dispatches the same start/stop intent RecordingService already understands -
 * no recording logic is duplicated here. Whether to start or stop is decided
 * from the mirrored DataStore boolean (the widget's own last-known state).
 */
class ToggleRecordingAction : ActionCallback {

    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val prefs = context.recordingPrefsDataStore.data.first()
        val isRecording = prefs[RecordingPrefsKeys.IS_RECORDING] ?: false

        val action = if (isRecording) {
            RecordingService.ACTION_STOP_RECORDING
        } else {
            RecordingService.ACTION_START_RECORDING
        }

        val intent = Intent(context, RecordingService::class.java).setAction(action)
        ContextCompat.startForegroundService(context, intent)
    }
}
