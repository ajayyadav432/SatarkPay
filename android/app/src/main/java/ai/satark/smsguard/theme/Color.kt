package ai.satark.smsguard.theme

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor

// The Twitter theme from tweakcn, in dark and light. Reading a colour follows AppTheme, so the screen redraws when it changes.
object AppTheme {
    /** "system", "light" or "dark". */
    var mode by mutableStateOf("system")
    var systemDark by mutableStateOf(true)
    val dark: Boolean get() = when (mode) { "light" -> false; "dark" -> true; else -> systemDark }
}

private fun pick(dark: Long, light: Long) = Color(if (AppTheme.dark) dark else light)

val Ink: Color get() = pick(0xFF000000, 0xFFFFFFFF)
val Panel: Color get() = pick(0xFF17181C, 0xFFF7F8F8)
val PanelRaised: Color get() = pick(0xFF202327, 0xFFEFF3F4)
val Line: Color get() = pick(0xFF2F3336, 0xFFE1EAEF)
val TextMain: Color get() = pick(0xFFE7E9EA, 0xFF0F1419)
val TextSoft: Color get() = pick(0xFF9AA3AB, 0xFF536471)
val Blue = Color(0xFF1C9CF0)
/** Blue for text and thin lines, which needs to be darker on white. */
val Sky: Color get() = pick(0xFF1C9CF0, 0xFF0B6FB8)
val BrandBrush = SolidColor(Blue)

// Risk colours are used for risk and nothing else.
val RiskSafe = Color(0xFF16A34A)
val RiskWarn = Color(0xFFD97706)
val RiskHold = Color(0xFFEA580C)
val RiskBlock = Color(0xFFDC2626)
val RiskUnknown = Color(0xFF475569)
