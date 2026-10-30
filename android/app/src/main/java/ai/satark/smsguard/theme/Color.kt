package ai.satark.smsguard.theme

import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color

// Taken from the logo: deep indigo with an indigo-to-sky gradient.
val Ink = Color(0xFF0B1020)
val Panel = Color(0xFF151B30)
val PanelRaised = Color(0xFF1E2642)
val Line = Color(0xFF2B3456)
val TextMain = Color(0xFFF1F4FF)
val TextSoft = Color(0xFFA3ADCB)
val Indigo = Color(0xFF6366F1)
val Sky = Color(0xFF0EA5E9)
val BrandBrush = Brush.linearGradient(listOf(Indigo, Sky))

// Risk colours are used for risk and nothing else.
val RiskSafe = Color(0xFF16A34A)
val RiskWarn = Color(0xFFD97706)
val RiskHold = Color(0xFFEA580C)
val RiskBlock = Color(0xFFDC2626)
val RiskUnknown = Color(0xFF475569)
