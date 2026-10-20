package com.cjpa.notes.data.repository

import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.WorkRequest
import androidx.work.workDataOf
import com.cjpa.notes.data.local.NoteEntity
import com.cjpa.notes.data.local.NoteSort
import com.cjpa.notes.data.local.NoteSortField
import com.cjpa.notes.data.local.NotesDao
import com.cjpa.notes.data.local.SortOrder
import com.cjpa.notes.data.local.UploadState
import com.cjpa.notes.data.remote.NotesApi
import com.cjpa.notes.data.remote.dto.GoogleAuthStatusDto
import com.cjpa.notes.data.remote.dto.UpdateStatusRequest
import com.cjpa.notes.data.remote.dto.UpdateTranscriptRequest
import com.cjpa.notes.data.remote.parseIsoInstantOrNow
import com.cjpa.notes.data.remote.parseIsoInstantOrNull
import com.cjpa.notes.data.work.UploadNoteWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class NotesRepository @Inject constructor(
    private val dao: NotesDao,
    private val api: NotesApi,
    private val workManager: WorkManager
) {

    /** Room Flow - any local write anywhere reactively repaints the UI. */
    fun observeNotes(sort: NoteSort): Flow<List<NoteEntity>> = dao.observeAll(sort)

    fun observeNote(localId: String): Flow<NoteEntity?> = dao.observeByLocalId(localId)

    /**
     * Called by RecordingService right after MediaRecorder stops: creates the
     * local-only row immediately (so it shows up in the list right away) and
     * enqueues the upload work.
     */
    suspend fun createLocalNoteAndEnqueueUpload(localId: String, audioPath: String, durationMs: Long) {
        val now = System.currentTimeMillis()
        val entity = NoteEntity(
            localId = localId,
            remoteId = null,
            createdAt = now,
            title = null,
            status = "open",
            processingStatus = "queued",
            durationMs = durationMs,
            localAudioPath = audioPath,
            uploadState = UploadState.PENDING,
            uploadError = null,
            transcriptMd = null,
            processingError = null,
            audioUrl = null,
            updatedAt = now
        )
        dao.upsert(entity)
        enqueueUpload(localId)
    }

    fun uploadWorkName(localId: String): String = "upload-$localId"

    fun enqueueUpload(localId: String, policy: ExistingWorkPolicy = ExistingWorkPolicy.KEEP) {
        val request = OneTimeWorkRequestBuilder<UploadNoteWorker>()
            .setInputData(workDataOf(UploadNoteWorker.KEY_LOCAL_ID to localId))
            .setConstraints(
                Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()
            )
            .setBackoffCriteria(
                BackoffPolicy.EXPONENTIAL,
                WorkRequest.MIN_BACKOFF_MILLIS,
                TimeUnit.MILLISECONDS
            )
            // Run immediately at high priority instead of waiting on normal Doze/App
            // Standby background-job scheduling - some OEM battery managers (seen on
            // this project's own test device) otherwise defer a plain background
            // OneTimeWorkRequest indefinitely once the app leaves the foreground.
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()
        workManager.enqueueUniqueWork(uploadWorkName(localId), policy, request)
    }

    /**
     * Re-enqueue upload work for recordings that never reached the server.
     *
     * WorkManager retries on its own, but its database and the system
     * JobScheduler can drift apart - a package replace cancels the app's
     * system jobs while WorkManager still lists the work as ENQUEUED. After
     * that the upload never runs again, the note sits on "Uploading…"
     * forever, and nothing re-enqueues it: the only other call site is a
     * just-finished recording, and the UI offers a retry affordance for
     * FAILED but not for UPLOADING.
     *
     * REPLACE rather than KEEP precisely because that stuck state still
     * *looks* healthy to WorkManager - KEEP would decline to touch it. Work
     * that is genuinely RUNNING is skipped instead, so an upload in flight
     * is never cancelled and re-sent as a duplicate note.
     */
    suspend fun resumePendingUploads() = withContext(Dispatchers.IO) {
        val unfinished = dao.getUnfinishedUploads()
        for (note in unfinished) {
            val isRunning = runCatching {
                workManager.getWorkInfosForUniqueWork(uploadWorkName(note.localId)).get()
                    .any { it.state == WorkInfo.State.RUNNING }
            }.getOrDefault(false)
            if (isRunning) continue
            Log.i(TAG, "Resuming stalled upload for note ${note.localId}")
            enqueueUpload(note.localId, ExistingWorkPolicy.REPLACE)
        }
    }

    /**
     * Pulls GET /api/notes and upserts by remote id. Rows with no remote id yet
     * (still-local pending uploads) are never matched by a server row, so they
     * are left completely untouched - never clobbered or duplicated.
     *
     * The endpoint returns the user's full note set (no pagination), so synced
     * rows the server no longer lists were deleted server-side and are pruned
     * here along with their local audio. The candidates are snapshotted
     * *before* the request: an upload that completes while the request is in
     * flight gains its remoteId afterwards and so can't be mistaken for a
     * deletion just because the (older) response doesn't include it.
     */
    suspend fun refresh(sort: NoteSort) {
        val syncedBefore = dao.getSynced()
        val response = api.listNotes(sortBy = sort.field.toWireValue(), order = sort.order.toWireValue())
        if (!response.isSuccessful) {
            throw IOException("List notes failed: HTTP ${response.code()}")
        }
        val remoteNotes = response.body().orEmpty()
        val entities = remoteNotes.map { dto ->
            val existing = dao.getByRemoteId(dto.id)
            NoteEntity(
                localId = existing?.localId ?: dto.id,
                remoteId = dto.id,
                createdAt = parseIsoInstantOrNow(dto.createdAt),
                title = dto.title,
                status = dto.status,
                processingStatus = dto.processingStatus,
                durationMs = ((dto.durationSeconds ?: 0.0) * 1000).toLong(),
                localAudioPath = existing?.localAudioPath,
                uploadState = UploadState.UPLOADED,
                uploadError = null,
                transcriptMd = existing?.transcriptMd,
                processingError = existing?.processingError,
                audioUrl = dto.audioUrl,
                updatedAt = parseIsoInstantOrNow(dto.updatedAt),
                scheduledAt = parseIsoInstantOrNull(dto.scheduledAt)
            )
        }
        dao.upsertAll(entities)

        val remoteIds = remoteNotes.mapTo(HashSet()) { it.id }
        val stale = syncedBefore.filter { it.remoteId !in remoteIds }
        if (stale.isNotEmpty()) {
            Log.i(TAG, "Pruning ${stale.size} note(s) deleted on the server")
            dao.deleteByLocalIds(stale.map { it.localId })
            withContext(Dispatchers.IO) {
                stale.forEach { note -> note.localAudioPath?.let { File(it).delete() } }
            }
        }
    }

    /** Background refresh of a single note's full detail (incl. transcript). */
    suspend fun refreshNoteDetail(localId: String) {
        val note = dao.getByLocalId(localId) ?: return
        val remoteId = note.remoteId ?: return // hasn't finished uploading yet - nothing to fetch
        val response = api.getNote(remoteId)
        if (!response.isSuccessful) {
            throw IOException("Get note failed: HTTP ${response.code()}")
        }
        val body = response.body() ?: return
        dao.upsert(
            note.copy(
                title = body.title,
                status = body.status,
                processingStatus = body.processingStatus,
                durationMs = ((body.durationSeconds ?: 0.0) * 1000).toLong(),
                audioUrl = body.audioUrl,
                transcriptMd = body.transcriptMarkdown,
                processingError = body.processingError,
                updatedAt = parseIsoInstantOrNow(body.updatedAt),
                scheduledAt = parseIsoInstantOrNull(body.scheduledAt)
            )
        )
    }

    /** Identity + Calendar-link status for the signed-in account (Phase 3), or null on failure. */
    suspend fun fetchGoogleAuthStatus(): GoogleAuthStatusDto? {
        return try {
            val response = api.getGoogleAuthStatus()
            if (response.isSuccessful) response.body() else null
        } catch (e: IOException) {
            null
        }
    }

    /** Best-effort server-side session revocation - local sign-out proceeds regardless. */
    suspend fun logout() {
        try {
            api.logout()
        } catch (e: IOException) {
            // Ignored: the caller clears the local session either way.
        }
    }

    /**
     * Optimistically updates the status locally, then syncs to the backend.
     * Reverts the local write and returns false on failure so the caller can
     * show a Snackbar.
     */
    suspend fun updateStatus(localId: String, newStatusWire: String): Boolean {
        val note = dao.getByLocalId(localId) ?: return false
        val previousStatus = note.status
        val now = System.currentTimeMillis()
        dao.updateStatus(localId, newStatusWire, now)

        val remoteId = note.remoteId ?: return true // local-only note; nothing to sync yet

        return try {
            val response = api.updateStatus(remoteId, UpdateStatusRequest(newStatusWire))
            if (response.isSuccessful) {
                true
            } else {
                dao.updateStatus(localId, previousStatus, now)
                false
            }
        } catch (e: IOException) {
            dao.updateStatus(localId, previousStatus, now)
            false
        }
    }

    suspend fun updateTranscript(localId: String, remoteId: String, markdown: String): Boolean {
        return try {
            val response = api.updateTranscript(remoteId, UpdateTranscriptRequest(markdown))
            if (response.isSuccessful) {
                val note = dao.getByLocalId(localId)
                if (note != null) {
                    dao.upsert(note.copy(transcriptMd = markdown, updatedAt = System.currentTimeMillis()))
                }
                true
            } else {
                false
            }
        } catch (e: IOException) {
            false
        }
    }

    private fun NoteSortField.toWireValue(): String = when (this) {
        NoteSortField.CREATED_AT -> "created_at"
        NoteSortField.DURATION -> "duration_seconds"
        NoteSortField.STATUS -> "status"
    }

    private fun SortOrder.toWireValue(): String = when (this) {
        SortOrder.ASC -> "asc"
        SortOrder.DESC -> "desc"
    }

    private companion object {
        const val TAG = "NotesRepository"
    }
}
