package com.cjpa.notes

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.cjpa.notes.data.local.AppDatabase
import com.cjpa.notes.data.local.NoteEntity
import com.cjpa.notes.data.local.NoteSort
import com.cjpa.notes.data.local.NoteSortField
import com.cjpa.notes.data.local.NotesDao
import com.cjpa.notes.data.local.SortOrder
import com.cjpa.notes.data.local.UploadState
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NotesDaoTest {

    private lateinit var db: AppDatabase
    private lateinit var dao: NotesDao

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        dao = db.notesDao()
    }

    @After
    fun tearDown() {
        db.close()
    }

    private fun note(localId: String, createdAt: Long, durationMs: Long, status: String, remoteId: String? = null) =
        NoteEntity(
            localId = localId,
            remoteId = remoteId,
            createdAt = createdAt,
            title = "Title $localId",
            status = status,
            durationMs = durationMs,
            uploadState = UploadState.PENDING,
            updatedAt = createdAt
        )

    @Test
    fun upsertAndGetByLocalId() = runBlocking {
        val entity = note("a", 1_000L, 5_000L, "open")
        dao.upsert(entity)

        val fetched = dao.getByLocalId("a")
        assertThat(fetched).isEqualTo(entity)
    }

    @Test
    fun getByRemoteId_findsUploadedNote() = runBlocking {
        dao.upsert(note("a", 1_000L, 5_000L, "open", remoteId = "remote-1"))

        val fetched = dao.getByRemoteId("remote-1")
        assertThat(fetched?.localId).isEqualTo("a")
    }

    @Test
    fun updateStatus_changesOnlyStatusAndUpdatedAt() = runBlocking {
        dao.upsert(note("a", 1_000L, 5_000L, "open"))

        dao.updateStatus("a", "closed", 9_999L)

        val fetched = dao.getByLocalId("a")
        assertThat(fetched?.status).isEqualTo("closed")
        assertThat(fetched?.updatedAt).isEqualTo(9_999L)
    }

    @Test
    fun observeAll_sortsByCreatedAtDescending() = runBlocking {
        dao.upsert(note("a", 1_000L, 1_000L, "open"))
        dao.upsert(note("b", 3_000L, 1_000L, "open"))
        dao.upsert(note("c", 2_000L, 1_000L, "open"))

        val result = dao.observeAll(NoteSort(NoteSortField.CREATED_AT, SortOrder.DESC)).first()

        assertThat(result.map { it.localId }).isEqualTo(listOf("b", "c", "a"))
    }

    @Test
    fun observeAll_sortsByDurationAscending() = runBlocking {
        dao.upsert(note("a", 1_000L, 30_000L, "open"))
        dao.upsert(note("b", 1_000L, 10_000L, "open"))
        dao.upsert(note("c", 1_000L, 20_000L, "open"))

        val result = dao.observeAll(NoteSort(NoteSortField.DURATION, SortOrder.ASC)).first()

        assertThat(result.map { it.localId }).isEqualTo(listOf("b", "c", "a"))
    }

    @Test
    fun upsertAll_leavesLocalOnlyRowsUntouched() = runBlocking {
        // A pending, not-yet-uploaded local recording (no remoteId).
        dao.upsert(note("local-pending", 500L, 1_000L, "open", remoteId = null))
        // A refresh from the server only ever contains rows that already have a remoteId.
        dao.upsertAll(listOf(note("remote-only-local-id", 2_000L, 4_000L, "todo", remoteId = "remote-x")))

        val all = dao.observeAll(NoteSort.DEFAULT).first()
        assertThat(all).hasSize(2)
        val pending = all.first { it.localId == "local-pending" }
        assertThat(pending.remoteId).isNull()
        assertThat(pending.uploadState).isEqualTo(UploadState.PENDING)
    }
}
