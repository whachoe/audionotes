package com.cjpa.notes

import com.cjpa.notes.ui.notes.NoteStatus
import com.google.common.truth.Truth.assertThat
import org.junit.Test

class NoteStatusTest {

    @Test
    fun `fromWireValue maps every backend enum value`() {
        assertThat(NoteStatus.fromWireValue("open")).isEqualTo(NoteStatus.OPEN)
        assertThat(NoteStatus.fromWireValue("in_progress")).isEqualTo(NoteStatus.IN_PROGRESS)
        assertThat(NoteStatus.fromWireValue("todo")).isEqualTo(NoteStatus.TODO)
        assertThat(NoteStatus.fromWireValue("closed")).isEqualTo(NoteStatus.CLOSED)
    }

    @Test
    fun `fromWireValue falls back to OPEN for unknown values`() {
        assertThat(NoteStatus.fromWireValue("something_unexpected")).isEqualTo(NoteStatus.OPEN)
    }

    @Test
    fun `wireValue round-trips through fromWireValue`() {
        NoteStatus.entries.forEach { status ->
            assertThat(NoteStatus.fromWireValue(status.wireValue)).isEqualTo(status)
        }
    }
}
