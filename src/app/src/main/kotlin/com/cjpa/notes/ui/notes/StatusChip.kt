package com.cjpa.notes.ui.notes

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.cjpa.notes.ui.theme.StatusClosedColor
import com.cjpa.notes.ui.theme.StatusInProgressColor
import com.cjpa.notes.ui.theme.StatusOpenColor
import com.cjpa.notes.ui.theme.StatusTodoColor

/** The four note statuses. Wire values are the exact snake_case backend enum. */
enum class NoteStatus(val wireValue: String, val displayLabel: String) {
    OPEN("open", "Open"),
    IN_PROGRESS("in_progress", "In Progress"),
    TODO("todo", "Todo"),
    CLOSED("closed", "Closed");

    companion object {
        fun fromWireValue(value: String): NoteStatus =
            entries.firstOrNull { it.wireValue == value } ?: OPEN
    }
}

fun statusColor(status: NoteStatus): Color = when (status) {
    NoteStatus.OPEN -> StatusOpenColor
    NoteStatus.IN_PROGRESS -> StatusInProgressColor
    NoteStatus.TODO -> StatusTodoColor
    NoteStatus.CLOSED -> StatusClosedColor
}

/**
 * Small colored pill per status. When [enabled], tapping it opens a dropdown
 * of the 4 status options; when disabled it's a read-only display (used on
 * the detail screen, where status isn't editable per the requirements).
 */
@Composable
fun StatusChip(
    status: NoteStatus,
    onStatusSelected: (NoteStatus) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier = modifier) {
        Surface(
            shape = RoundedCornerShape(50),
            color = statusColor(status),
            modifier = if (enabled) Modifier.clickable { expanded = true } else Modifier
        ) {
            Text(
                text = status.displayLabel,
                color = Color.White,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp)
            )
        }
        if (enabled) {
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                NoteStatus.entries.forEach { option ->
                    DropdownMenuItem(
                        text = { Text(option.displayLabel) },
                        onClick = {
                            expanded = false
                            if (option != status) onStatusSelected(option)
                        }
                    )
                }
            }
        }
    }
}
