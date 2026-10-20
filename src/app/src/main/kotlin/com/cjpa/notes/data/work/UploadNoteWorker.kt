package com.cjpa.notes.data.work

import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.ForegroundInfo
import androidx.work.WorkerParameters
import com.cjpa.notes.R
import com.cjpa.notes.data.local.NotesDao
import com.cjpa.notes.data.local.UploadState
import com.cjpa.notes.data.remote.NotesApi
import com.cjpa.notes.data.remote.parseIsoInstantOrNull
import com.cjpa.notes.recording.RecordingNotification
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.IOException
import kotlin.coroutines.cancellation.CancellationException

/**
 * Uploads one recorded audio file as multipart field "file". Unique work name
 * is "upload-$localId" (enforced by the caller via WorkManager.enqueueUniqueWork).
 *
 * - Unrecoverable failure (4xx): uploadState = FAILED with a retry affordance,
 *   Result.failure().
 * - Transient failure (IOException / 5xx): leaves uploadState as UPLOADING
 *   (still "Uploading…" to the user) and returns Result.retry(), relying on
 *   WorkManager's exponential backoff.
 */
@HiltWorker
class UploadNoteWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val notesDao: NotesDao,
    private val notesApi: NotesApi
) : CoroutineWorker(context, params) {

    // Required for expedited work: on API 26-30 (below WorkManager's own
    // JobScheduler-based expediting), this is what actually lets the upload run
    // promptly as a short-lived foreground service instead of a deferrable job.
    override suspend fun getForegroundInfo(): ForegroundInfo {
        val notification = NotificationCompat.Builder(applicationContext, RecordingNotification.CHANNEL_ID)
            .setContentTitle(applicationContext.getString(R.string.app_name))
            .setContentText("Uploading note…")
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(UPLOAD_NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            ForegroundInfo(UPLOAD_NOTIFICATION_ID, notification)
        }
    }

    override suspend fun doWork(): Result {
        val localId = inputData.getString(KEY_LOCAL_ID) ?: return Result.failure()
        val note = notesDao.getByLocalId(localId) ?: return Result.failure()

        if (note.uploadState == UploadState.UPLOADED) {
            return Result.success()
        }

        val path = note.localAudioPath
        val file = path?.let { File(it) }
        if (file == null || !file.exists()) {
            notesDao.upsert(note.copy(uploadState = UploadState.FAILED, uploadError = "Local audio file missing"))
            return Result.failure()
        }

        notesDao.upsert(note.copy(uploadState = UploadState.UPLOADING, uploadError = null))

        return try {
            val requestBody = file.asRequestBody("audio/mp4".toMediaType())
            val part = MultipartBody.Part.createFormData("file", file.name, requestBody)
            val response = notesApi.uploadNote(part)

            if (response.isSuccessful) {
                val body = response.body()
                val latest = notesDao.getByLocalId(localId) ?: note
                if (body != null) {
                    notesDao.upsert(
                        latest.copy(
                            remoteId = body.id,
                            title = body.title,
                            status = body.status,
                            processingStatus = body.processingStatus,
                            durationMs = ((body.durationSeconds ?: 0.0) * 1000).toLong(),
                            audioUrl = body.audioUrl,
                            scheduledAt = parseIsoInstantOrNull(body.scheduledAt),
                            transcriptMd = body.transcriptMarkdown,
                            processingError = body.processingError,
                            uploadState = UploadState.UPLOADED,
                            uploadError = null,
                            updatedAt = System.currentTimeMillis()
                        )
                    )
                } else {
                    notesDao.upsert(latest.copy(uploadState = UploadState.UPLOADED, uploadError = null))
                }
                Result.success()
            } else if (response.code() in 400..499) {
                notesDao.upsert(note.copy(uploadState = UploadState.FAILED, uploadError = "Upload rejected by server (HTTP ${response.code()})"))
                Result.failure()
            } else {
                // Transient server-side failure - keep showing "Uploading…" while WorkManager retries.
                Result.retry()
            }
        } catch (e: CancellationException) {
            // Cooperative cancellation is not a failure - never swallow it,
            // or WorkManager can't stop this worker.
            throw e
        } catch (e: IOException) {
            // Transient network failure - keep showing "Uploading…" while WorkManager retries.
            Log.w(TAG, "Upload of $localId failed, will retry", e)
            Result.retry()
        } catch (e: Exception) {
            // Anything else - an unparseable response, an unexpected runtime
            // error - used to escape doWork() entirely. WorkManager then
            // marked the work terminally failed while the note stayed on
            // UPLOADING with uploadError still null, which is
            // indistinguishable from an upload still in progress and leaves
            // the user no way to retry. Record it so it shows as FAILED.
            Log.e(TAG, "Upload of $localId failed permanently", e)
            notesDao.upsert(
                note.copy(
                    uploadState = UploadState.FAILED,
                    uploadError = e.message ?: e.javaClass.simpleName
                )
            )
            Result.failure()
        }
    }

    companion object {
        const val KEY_LOCAL_ID = "local_id"
        private const val TAG = "UploadNoteWorker"
        private const val UPLOAD_NOTIFICATION_ID = 1002
    }
}
