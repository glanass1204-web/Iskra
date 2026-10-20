package ru.iskra.assistant.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Ember = Color(0xFFFF7A1A)
val EmberDeep = Color(0xFFC2310B)
val Glow = Color(0xFFFFB25A)
val Coal = Color(0xFF0F0A08)
val Surface1 = Color(0xFF1A120E)
val Surface2 = Color(0xFF241913)
val Line = Color(0xFF3A2A20)
val Muted = Color(0xFFB39D8D)
val Ok = Color(0xFF7FD18B)

private val scheme = darkColorScheme(
    primary = Ember,
    onPrimary = Color(0xFF1A0B02),
    secondary = Glow,
    background = Coal,
    onBackground = Color(0xFFF6ECE4),
    surface = Surface1,
    onSurface = Color(0xFFF6ECE4),
    surfaceVariant = Surface2,
    onSurfaceVariant = Muted,
    outline = Line,
    error = Color(0xFFFF5A4F),
)

@Composable
fun IskraTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme, content = content)
}
