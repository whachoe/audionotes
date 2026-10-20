package com.cjpa.notes.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Local upload lifecycle for a note's audio file. This is intentionally distinct
 * from the backend's `processing_status` (queued|transcribing|summarizing|done|failed):
 * uploadState tracks *our* client-to-server transfer, processingStatus tracks the
 * server's transcription/summarization pipeline once the file has arrived.
 */
enum class UploadState {
    PENDING,
    UPLOADING,
    UPLOADED,
    FAILED
}

/**
 * Room row = the single local source of truth for a note. Rows are created
 * locally the moment recording stops (remoteId == null, uploadState == PENDING)
 * and are later reconciled with the backend once the upload succeeds, and again
 * on every list refresh / detail fetch.
 *
 * `status` and `processingStatus` are stored exactly as the wire snake_case
 * values (open/in_progress/todo/closed, queued/transcribing/...); the UI layer
 * is responsible for mapping them to display labels.
 */
@Entity(tableName = "notes")
data class NoteEntity(
    @PrimaryKey val localId: String,
    val remoteId: String? = null,
    val createdAt: Long,
    val title: String? = null,
    val status: String = "open",
    val processingStatus: String = "queued",
    val durationMs: Long = 0L,
    val localAudioPath: String? = null,
    val uploadState: UploadState = UploadState.PENDING,
    val uploadError: String? = null,
    val transcriptMd: String? = null,
    val processingError: String? = null,
    val audioUrl: String? = null,
    val updatedAt: Long = createdAt,
    /** Set when the backend recognizes a date/time in the transcript (Phase 2). */
    val scheduledAt: Long? = null
)
