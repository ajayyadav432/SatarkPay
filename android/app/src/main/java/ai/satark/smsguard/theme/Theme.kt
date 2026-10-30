package ai.satark.smsguard.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

@Composable
private fun scheme() = if (AppTheme.dark)
    darkColorScheme(primary = Blue, onPrimary = Color.White, secondary = Sky, background = Ink, onBackground = TextMain,
        surface = Panel, onSurface = TextMain, surfaceVariant = PanelRaised, onSurfaceVariant = TextSoft, outline = Line)
else
    lightColorScheme(primary = Blue, onPrimary = Color.White, secondary = Sky, background = Ink, onBackground = TextMain,
        surface = Panel, onSurface = TextMain, surfaceVariant = PanelRaised, onSurfaceVariant = TextSoft, outline = Color(0xFFCFD9DE))

@Composable
fun SatarkPayTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = scheme(), typography = Typography, content = content)
}
