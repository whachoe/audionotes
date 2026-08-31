package com.cjpa.notes.recording

import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.MediaRecorder
import android.os.Build
import androidx.core.app.NotificationManagerCompat
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.widget.updateRecordingWidget
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import java.io.File
import java.util.UUID
import javax.inject.Inject

/**
 * Single source of truth for recording. Started/stopped via
 * ACTION_START_RECORDING / ACTION_STOP_RECORDING, sent identically by the
 * in-app circular button, the notification's Stop action, and the home-screen
 * widget - none of them duplicate any recording logic.
 */
@AndroidEntryPoint
class RecordingService : LifecycleService() {

    @Inject
    lateinit var notesRepository: NotesRepository

    @Inject
    lateinit var recordingPrefsDataStore: DataStore<Preferences>

    private var mediaRecorder: MediaRecorder? = null
    private var currentFile: File? = null
    private var currentLocalId: String? = null
    private var startTimeMs: Long = 0L

    override fun onCreate() {
        super.onCreate()
        RecordingNotification.createChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        // Android 14+ requires startForeground() within a few seconds of every
        // startForegroundService() call - regardless of which action triggered
        // it, or the whole process gets killed with
        // ForegroundServiceDidNotStartInTimeException. Satisfy that unconditionally
        // and immediately, before doing anything that could fail or branch away
        // (a MediaRecorder error, or the stop path, which stops right back out).
        goForeground(RecordingNotification.build(this, startTimeMs.takeIf { mediaRecorder != null } ?: System.currentTimeMillis()))
        when (intent?.action) {
            ACTION_START_RECORDING -> startRecording()
            ACTION_STOP_RECORDING -> stopRecording()
        }
        return START_NOT_STICKY
    }

    private fun startRecording() {
        if (mediaRecorder != null) return // already recording; ignore duplicate start

        val dir = File(filesDir, "recordings").apply { mkdirs() }
        val id = UUID.randomUUID().toString()
        val file = File(dir, "$id.m4a")

        val recorder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(this)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

        try {
            recorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioEncodingBitRate(128_000)
                setAudioSamplingRate(44_100)
                setOutputFile(file.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            recorder.release()
            stopSelf()
            return
        }

        mediaRecorder = recorder
        currentFile = file
        currentLocalId = id
        startTimeMs = System.currentTimeMillis()

        RecordingStateHolder.setRecording(isRecording = true, startTimeMs = startTimeMs)
        goForeground(RecordingNotification.build(this, startTimeMs))

        lifecycleScope.launch {
            setRecordingPref(true)
            updateRecordingWidget(applicationContext)
        }
    }

    private fun stopRecording() {
        val recorder = mediaRecorder
        val file = currentFile
        val localId = currentLocalId
        if (recorder == null || file == null || localId == null) {
            stopSelf()
            return
        }

        var validRecording = true
        try {
            recorder.stop()
        } catch (e: RuntimeException) {
            // stop() throws if called before any data was recorded; treat as invalid.
            validRecording = false
        } finally {
            recorder.reset()
            recorder.release()
        }

        val durationMs = System.currentTimeMillis() - startTimeMs
        mediaRecorder = null
        currentFile = null
        currentLocalId = null

        RecordingStateHolder.setRecording(isRecording = false, startTimeMs = null)

        lifecycleScope.launch {
            setRecordingPref(false)
            if (validRecording && durationMs > 0) {
                notesRepository.createLocalNoteAndEnqueueUpload(localId, file.absolutePath, durationMs)
            } else {
                file.delete()
            }
            updateRecordingWidget(applicationContext)

            // Only stop the service once the DB write + upload enqueue above have
            // actually completed. lifecycleScope is cancelled the moment onDestroy()
            // runs, so calling stopSelf() synchronously right after launch{} (as this
            // used to) raced this coroutine and silently dropped the note before any
            // of it ran - stopping had to move to the end of the coroutine itself.
            NotificationManagerCompat.from(this@RecordingService).cancel(RecordingNotification.NOTIFICATION_ID)
            stopForegroundCompat()
            stopSelf()
        }
    }

    private suspend fun setRecordingPref(isRecording: Boolean) {
        recordingPrefsDataStore.edit { prefs ->
            prefs[RecordingPrefsKeys.IS_RECORDING] = isRecording
        }
    }

    private fun goForeground(notification: android.app.Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(RecordingNotification.NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(RecordingNotification.NOTIFICATION_ID, notification)
        }
    }

    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
    }

    companion object {
        const val ACTION_START_RECORDING = "com.cjpa.notes.action.START_RECORDING"
        const val ACTION_STOP_RECORDING = "com.cjpa.notes.action.STOP_RECORDING"
    }
}
