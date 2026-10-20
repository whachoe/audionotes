package com.cjpa.notes.data.remote.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** GET /api/notes list item - metadata only. */
@Serializable
data class NoteListItemDto(
    val id: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val title: String? = null,
    val status: String,
    @SerialName("processing_status") val processingStatus: String,
    // Nullable: the backend's duration_seconds is Optional[float]. It is
    // null for a markdown-only note (no recording to measure) and for any
    // note whose ffprobe failed - decoding null into a non-null Double
    // threw, which failed the *whole* list response, not just that row.
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
    @SerialName("audio_url") val audioUrl: String? = null,
    @SerialName("scheduled_at") val scheduledAt: String? = null
)

/**
 * GET /api/notes/{id} detail, and also the body returned by POST /api/notes
 * on a successful upload (which includes the same fields, with
 * processing_status = "queued" and no transcript yet).
 */
@Serializable
data class NoteDetailDto(
    val id: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val title: String? = null,
    val status: String,
    @SerialName("processing_status") val processingStatus: String,
    // Nullable: the backend's duration_seconds is Optional[float]. It is
    // null for a markdown-only note (no recording to measure) and for any
    // note whose ffprobe failed - decoding null into a non-null Double
    // threw, which failed the *whole* list response, not just that row.
    @SerialName("duration_seconds") val durationSeconds: Double? = null,
    @SerialName("audio_url") val audioUrl: String? = null,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
    @SerialName("transcript_markdown") val transcriptMarkdown: String? = null,
    @SerialName("processing_error") val processingError: String? = null,
    @SerialName("audio_original_filename") val audioOriginalFilename: String? = null,
    @SerialName("audio_mime_type") val audioMimeType: String? = null
)

@Serializable
data class UpdateStatusRequest(val status: String)

@Serializable
data class UpdateTranscriptRequest(val markdown: String)

/** GET /api/google/auth/status. */
@Serializable
data class GoogleAuthStatusDto(
    val email: String,
    val name: String? = null,
    @SerialName("calendar_linked") val calendarLinked: Boolean
)
