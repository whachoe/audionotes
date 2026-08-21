package com.cjpa.notes.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetManager
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.currentState
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.size
import androidx.glance.state.GlanceStateDefinition
import com.cjpa.notes.R
import com.cjpa.notes.recording.RECORDING_PREFS_NAME
import com.cjpa.notes.recording.RecordingPrefsKeys
import com.cjpa.notes.recording.recordingPrefsDataStore
import java.io.File

/**
 * A GlanceStateDefinition backed by the exact same DataStore<Preferences> file
 * that RecordingService mirrors "is recording" into - not the default
 * per-widget PreferencesGlanceStateDefinition - so the widget reads the same
 * boolean the service writes.
 */
object RecordingGlanceStateDefinition : GlanceStateDefinition<Preferences> {

    override suspend fun getDataStore(context: Context, fileKey: String): DataStore<Preferences> =
        context.recordingPrefsDataStore

    override fun getLocation(context: Context, fileKey: String): File =
        context.preferencesDataStoreFile(RECORDING_PREFS_NAME)
}

/** Plain round icon-only home-screen button: mic (idle) or stop (recording). */
class RecordingWidget : GlanceAppWidget() {

    override val stateDefinition: GlanceStateDefinition<*> = RecordingGlanceStateDefinition

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent {
            val prefs = currentState<Preferences>()
            val isRecording = prefs[RecordingPrefsKeys.IS_RECORDING] ?: false
            RecordingWidgetContent(isRecording)
        }
    }
}

@Composable
private fun RecordingWidgetContent(isRecording: Boolean) {
    val backgroundRes = if (isRecording) R.drawable.widget_background_recording else R.drawable.widget_background_idle
    val iconRes = if (isRecording) R.drawable.ic_stop else R.drawable.ic_mic
    val description = if (isRecording) "Stop recording" else "Start recording"

    Box(
        modifier = GlanceModifier
            .size(56.dp)
            .background(ImageProvider(backgroundRes))
            .clickable(actionRunCallback<ToggleRecordingAction>()),
        contentAlignment = Alignment.Center
    ) {
        Image(
            provider = ImageProvider(iconRes),
            contentDescription = description
        )
    }
}

/** Called by RecordingService after it updates recording state, so the widget repaints immediately. */
suspend fun updateRecordingWidget(context: Context) {
    val manager = GlanceAppWidgetManager(context)
    val widget = RecordingWidget()
    val ids = manager.getGlanceIds(RecordingWidget::class.java)
    ids.forEach { id -> widget.update(context, id) }
}
