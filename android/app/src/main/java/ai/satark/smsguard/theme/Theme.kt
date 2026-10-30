package ai.satark.smsguard.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val Scheme = darkColorScheme(
    primary = Indigo, onPrimary = TextMain, secondary = Sky, background = Ink, onBackground = TextMain,
    surface = Panel, onSurface = TextMain, surfaceVariant = PanelRaised, onSurfaceVariant = TextSoft, outline = Line,
)

/** One fixed look, so the app is the same on every phone at the demo. */
@Composable
fun SatarkPayTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = Scheme, typography = Typography, content = content)
}
