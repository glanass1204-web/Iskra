package ru.iskra.assistant.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color

data class IskraPalette(
    val top: Color,
    val bg: Color,
    val surface: Color,
    val bubble: Color,
    val line: Color,
    val muted: Color,
    val accent: Color,
    val glow: Color,
    val deep: Color,
    val ok: Color,
    val text: Color,
)

// Светлая тема по умолчанию: тёмно-оранжевый на белом читается при любом освещении.
private val Light = IskraPalette(
    top = Color(0xFFFFE4CC),
    bg = Color(0xFFFFF8F2),
    surface = Color(0xFFFFFFFF),
    bubble = Color(0xFFFFFFFF),
    line = Color(0xFFD6BCA8),
    muted = Color(0xFF5A4334),
    accent = Color(0xFFC2410C),
    glow = Color(0xFFFB923C),
    deep = Color(0xFF9A3412),
    ok = Color(0xFF15803D),
    text = Color(0xFF1C120C),
)

private val Dark = IskraPalette(
    top = Color(0xFF3A1E0E),
    bg = Color(0xFF15100D),
    surface = Color(0xFF241A14),
    bubble = Color(0xFF2E221A),
    line = Color(0xFF6B5446),
    muted = Color(0xFFD9C5B6),
    accent = Color(0xFFFF8A3D),
    glow = Color(0xFFFFB25A),
    deep = Color(0xFFC2410C),
    ok = Color(0xFF86EFAC),
    text = Color(0xFFFFF4EC),
)

private val LocalPalette = staticCompositionLocalOf { Light }

val Ember: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.accent
val EmberDeep: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.deep
val Glow: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.glow
val Coal: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.bg
val Top: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.top
val Surface1: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.surface
val Surface2: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.bubble
val Line: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.line
val Muted: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.muted
val Ok: Color @Composable @ReadOnlyComposable get() = LocalPalette.current.ok

@Composable
fun IskraTheme(dark: Boolean, content: @Composable () -> Unit) {
    val p = if (dark) Dark else Light
    val scheme = if (dark) {
        darkColorScheme(
            primary = p.accent, onPrimary = Color(0xFF1A0B02), secondary = p.glow,
            background = p.bg, onBackground = p.text, surface = p.surface, onSurface = p.text,
            surfaceVariant = p.bubble, onSurfaceVariant = p.muted, outline = p.line, error = Color(0xFFFF6B60),
        )
    } else {
        lightColorScheme(
            primary = p.accent, onPrimary = Color.White, secondary = p.deep,
            background = p.bg, onBackground = p.text, surface = p.surface, onSurface = p.text,
            surfaceVariant = Color(0xFFF5E6DA), onSurfaceVariant = p.muted, outline = p.line, error = Color(0xFFB91C1C),
        )
    }
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme, content = content)
    }
}
