package com.cjpa.notes.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

// The approved mockup specifies a light theme only (no dark theme variant).
private val AppLightColorScheme = lightColorScheme(
    primary = Indigo,
    onPrimary = OnIndigo,
    primaryContainer = IndigoLight,
    onPrimaryContainer = IndigoDark,
    secondary = IndigoDark,
    onSecondary = OnIndigo,
    error = Red,
    onError = OnRed,
    errorContainer = RedDark,
    onErrorContainer = OnRed
)

@Composable
fun CjpasNotesTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = AppLightColorScheme,
        typography = AppTypography,
        content = content
    )
}
