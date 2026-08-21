package com.cjpa.notes.ui.theme

import androidx.compose.material3.Typography
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

// Roboto is Android's default system sans-serif font, so FontFamily.Default
// already resolves to Roboto on-device - no custom font resources are needed.
private val RobotoFontFamily = FontFamily.Default

val AppTypography = Typography(
    displayLarge = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Normal, fontSize = 57.sp),
    headlineSmall = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Normal, fontSize = 24.sp),
    titleLarge = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Medium, fontSize = 22.sp),
    titleMedium = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Medium, fontSize = 16.sp),
    bodyLarge = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Normal, fontSize = 16.sp),
    bodyMedium = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Normal, fontSize = 14.sp),
    labelLarge = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Medium, fontSize = 14.sp),
    labelMedium = TextStyle(fontFamily = RobotoFontFamily, fontWeight = FontWeight.Medium, fontSize = 12.sp)
)
