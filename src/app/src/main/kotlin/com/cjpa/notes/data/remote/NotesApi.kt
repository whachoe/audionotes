package com.cjpa.notes.data.remote

import com.cjpa.notes.data.remote.dto.GoogleAuthStatusDto
import com.cjpa.notes.data.remote.dto.NoteDetailDto
import com.cjpa.notes.data.remote.dto.NoteListItemDto
import com.cjpa.notes.data.remote.dto.UpdateStatusRequest
import com.cjpa.notes.data.remote.dto.UpdateTranscriptRequest
import okhttp3.MultipartBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit is built with a fixed placeholder base URL ("https://placeholder.invalid/")
 * and every path here is rooted at "api/..." - [BaseUrlInterceptor] rewrites the
 * scheme/host/port (and prefixes any user-configured path) against the base URL
 * stored in Settings, so we never need to rebuild Retrofit when settings change.
 */
interface NotesApi {

    @Multipart
    @POST("api/notes")
    suspend fun uploadNote(@Part file: MultipartBody.Part): Response<NoteDetailDto>

    @GET("api/notes")
    suspend fun listNotes(
        @Query("sort_by") sortBy: String,
        @Query("order") order: String
    ): Response<List<NoteListItemDto>>

    @GET("api/notes/{id}")
    suspend fun getNote(@Path("id") id: String): Response<NoteDetailDto>

    @PATCH("api/notes/{id}/status")
    suspend fun updateStatus(@Path("id") id: String, @Body body: UpdateStatusRequest): Response<Unit>

    @PUT("api/notes/{id}/transcript")
    suspend fun updateTranscript(@Path("id") id: String, @Body body: UpdateTranscriptRequest): Response<Unit>

    @GET("api/google/auth/status")
    suspend fun getGoogleAuthStatus(): Response<GoogleAuthStatusDto>

    @POST("api/google/auth/logout")
    suspend fun logout(): Response<Unit>
}
