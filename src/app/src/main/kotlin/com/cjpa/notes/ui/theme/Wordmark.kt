package com.cjpa.notes.ui.theme

import androidx.compose.runtime.Composable
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.sp
import com.cjpa.notes.R

// Oswald (OFL-licensed, fonts.google.com/specimen/Oswald), the bold condensed
// face used for the approved "Copywaste Notes" wordmark lockup, matching the
// copyWaste brand wordmark's letterforms.
@OptIn(ExperimentalTextApi::class)
private val OswaldFamily = FontFamily(
    Font(
        R.font.oswald_variable,
        weight = FontWeight.Bold,
        variationSettings = FontVariation.Settings(FontVariation.weight(700))
    )
)

/** The "Copywaste Notes" wordmark lockup - navy "Copywaste" + red "Notes". */
@Composable
fun WordmarkTitle() {
    androidx.compose.material3.Text(
        text = buildAnnotatedString {
            withStyle(SpanStyle(color = CopywasteNavy)) { append("Copywaste") }
            withStyle(SpanStyle(color = CopywasteRed)) { append(" Notes") }
        },
        fontFamily = OswaldFamily,
        fontWeight = FontWeight.Bold,
        fontSize = 22.sp
    )
}
