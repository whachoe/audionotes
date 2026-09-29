package com.cjpa.notes

import android.app.Application
import android.util.Log
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.cjpa.notes.data.repository.NotesRepository
import com.cjpa.notes.recording.RecordingNotification
import dagger.Lazy
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltAndroidApp
class NotesApplication : Application(), Configuration.Provider {

    @Inject
    lateinit var hiltWorkerFactory: HiltWorkerFactory

    // Lazy: resolving the repository builds WorkManager, which needs the
    // Configuration this class itself provides. Deferring it to the
    // coroutine below keeps that off onCreate's main-thread path.
    @Inject
    lateinit var notesRepository: Lazy<NotesRepository>

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        RecordingNotification.createChannel(this)

        // A recording whose upload work WorkManager has lost would otherwise
        // stay on "Uploading…" forever - nothing else ever re-enqueues it.
        appScope.launch {
            try {
                notesRepository.get().resumePendingUploads()
            } catch (e: Exception) {
                Log.e(TAG, "Couldn't resume pending uploads", e)
            }
        }
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(hiltWorkerFactory)
            .build()

    private companion object {
        const val TAG = "NotesApplication"
    }
}
