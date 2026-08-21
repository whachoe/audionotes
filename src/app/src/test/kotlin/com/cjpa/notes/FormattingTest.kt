package com.cjpa.notes

import com.cjpa.notes.ui.notes.formatDuration
import com.cjpa.notes.ui.notes.formatElapsed
import com.google.common.truth.Truth.assertThat
import org.junit.Test

class FormattingTest {

    @Test
    fun `formatDuration renders minutes and seconds`() {
        assertThat(formatDuration(0L)).isEqualTo("0:00")
        assertThat(formatDuration(65_000L)).isEqualTo("1:05")
        assertThat(formatDuration(3_600_000L)).isEqualTo("60:00")
    }

    @Test
    fun `formatElapsed zero-pads minutes`() {
        assertThat(formatElapsed(0L)).isEqualTo("00:00")
        assertThat(formatElapsed(5_000L)).isEqualTo("00:05")
        assertThat(formatElapsed(75_000L)).isEqualTo("01:15")
    }
}
