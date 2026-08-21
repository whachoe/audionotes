package com.cjpa.notes

import com.cjpa.notes.data.remote.parseIsoInstantOrNow
import com.google.common.truth.Truth.assertThat
import org.junit.Test
import java.time.Instant

class IsoDateUtilsTest {

    @Test
    fun `parses strict UTC instant`() {
        val millis = parseIsoInstantOrNow("2026-08-21T10:15:30Z")
        assertThat(millis).isEqualTo(Instant.parse("2026-08-21T10:15:30Z").toEpochMilli())
    }

    @Test
    fun `parses offset date time`() {
        val millis = parseIsoInstantOrNow("2026-08-21T10:15:30+02:00")
        assertThat(millis).isGreaterThan(0L)
    }

    @Test
    fun `falls back to now for null input`() {
        val before = System.currentTimeMillis()
        val millis = parseIsoInstantOrNow(null)
        val after = System.currentTimeMillis()
        assertThat(millis).isAtLeast(before)
        assertThat(millis).isAtMost(after)
    }

    @Test
    fun `falls back to now for garbage input`() {
        val before = System.currentTimeMillis()
        val millis = parseIsoInstantOrNow("not-a-date")
        val after = System.currentTimeMillis()
        assertThat(millis).isAtLeast(before)
        assertThat(millis).isAtMost(after)
    }
}
