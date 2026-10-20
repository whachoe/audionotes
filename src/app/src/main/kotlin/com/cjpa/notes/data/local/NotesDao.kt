package com.cjpa.notes.data.local

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

enum class NoteSortField { CREATED_AT, DURATION, STATUS }
enum class SortOrder { ASC, DESC }

data class NoteSort(val field: NoteSortField, val order: SortOrder) {
    companion object {
        val DEFAULT = NoteSort(NoteSortField.CREATED_AT, SortOrder.DESC)
    }
}

@Dao
interface NotesDao {

    @Query("SELECT * FROM notes ORDER BY createdAt ASC")
    fun observeAllByCreatedAtAsc(): Flow<List<NoteEntity>>

    @Query("SELECT * FROM notes ORDER BY createdAt DESC")
    fun observeAllByCreatedAtDesc(): Flow<List<NoteEntity>>

    @Query("SELECT * FROM notes ORDER BY durationMs ASC")
    fun observeAllByDurationAsc(): Flow<List<NoteEntity>>

    @Query("SELECT * FROM notes ORDER BY durationMs DESC")
    fun observeAllByDurationDesc(): Flow<List<NoteEntity>>

    @Query("SELECT * FROM notes ORDER BY status ASC")
    fun observeAllByStatusAsc(): Flow<List<NoteEntity>>

    @Query("SELECT * FROM notes ORDER BY status DESC")
    fun observeAllByStatusDesc(): Flow<List<NoteEntity>>

    /**
     * Dispatches to one of the concrete @Query methods above. Room only
     * generates implementations for abstract DAO members, so this default
     * (has-a-body) function is left untouched by the annotation processor and
     * simply picks the right underlying query.
     */
    fun observeAll(sort: NoteSort): Flow<List<NoteEntity>> = when (sort.field) {
        NoteSortField.CREATED_AT -> if (sort.order == SortOrder.ASC) observeAllByCreatedAtAsc() else observeAllByCreatedAtDesc()
        NoteSortField.DURATION -> if (sort.order == SortOrder.ASC) observeAllByDurationAsc() else observeAllByDurationDesc()
        NoteSortField.STATUS -> if (sort.order == SortOrder.ASC) observeAllByStatusAsc() else observeAllByStatusDesc()
    }

    @Query("SELECT * FROM notes WHERE localId = :localId LIMIT 1")
    fun observeByLocalId(localId: String): Flow<NoteEntity?>

    @Upsert
    suspend fun upsert(note: NoteEntity)

    @Upsert
    suspend fun upsertAll(notes: List<NoteEntity>)

    @Query("UPDATE notes SET status = :status, updatedAt = :updatedAt WHERE localId = :localId")
    suspend fun updateStatus(localId: String, status: String, updatedAt: Long)

    @Query("SELECT * FROM notes WHERE localId = :localId LIMIT 1")
    suspend fun getByLocalId(localId: String): NoteEntity?

    @Query("SELECT * FROM notes WHERE remoteId = :remoteId LIMIT 1")
    suspend fun getByRemoteId(remoteId: String): NoteEntity?

    /** Every row the server has acknowledged - candidates for pruning on refresh. */
    @Query("SELECT * FROM notes WHERE remoteId IS NOT NULL")
    suspend fun getSynced(): List<NoteEntity>

    @Query("DELETE FROM notes WHERE localId IN (:localIds)")
    suspend fun deleteByLocalIds(localIds: List<String>)

    /**
     * Recordings whose audio never reached the server. Used at app start to
     * re-enqueue upload work WorkManager has lost track of - see
     * NotesRepository.resumePendingUploads.
     *
     * uploadState is persisted as the enum's name (see Converters), hence
     * the string literals.
     */
    @Query("SELECT * FROM notes WHERE remoteId IS NULL AND uploadState IN ('PENDING', 'UPLOADING')")
    suspend fun getUnfinishedUploads(): List<NoteEntity>
}
