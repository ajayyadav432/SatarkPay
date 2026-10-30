package ai.satark.smsguard

import androidx.annotation.DrawableRes
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.satark.smsguard.theme.BrandBrush
import ai.satark.smsguard.theme.Line
import ai.satark.smsguard.theme.Panel
import ai.satark.smsguard.theme.PanelRaised
import ai.satark.smsguard.theme.TextMain
import ai.satark.smsguard.theme.TextSoft

val CARD_SHAPE = RoundedCornerShape(20.dp)
val PILL_SHAPE = RoundedCornerShape(50)

@Composable
fun UiIcon(@DrawableRes id: Int, description: String?, tint: Color = TextMain, size: Dp = 22.dp) {
    Icon(painterResource(id), description, tint = tint, modifier = Modifier.size(size))
}

/** A flat panel. Depth comes from colour and a thin line, not shadows. */
@Composable
fun Panel(modifier: Modifier = Modifier, padding: Dp = 16.dp, content: @Composable () -> Unit) {
    Box(modifier.fillMaxWidth().clip(CARD_SHAPE).background(Panel).border(BorderStroke(1.dp, Line), CARD_SHAPE).padding(padding)) { content() }
}

/** The one main action of a screen. */
@Composable
fun PrimaryButton(text: String, modifier: Modifier = Modifier, enabled: Boolean = true, color: Color? = null, @DrawableRes icon: Int? = null, onClick: () -> Unit) {
    val fill = if (color != null) Modifier.background(color) else Modifier.background(BrandBrush)
    Row(modifier.fillMaxWidth().height(56.dp).clip(PILL_SHAPE).then(if (enabled) fill else Modifier.background(PanelRaised))
        .clickable(enabled = enabled, onClick = onClick), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally)) {
        if (icon != null) UiIcon(icon, null, if (enabled) Color.White else TextSoft)
        Text(text, color = if (enabled) Color.White else TextSoft, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
    }
}

@Composable
fun SecondaryButton(text: String, modifier: Modifier = Modifier, @DrawableRes icon: Int? = null, onClick: () -> Unit) {
    Row(modifier.fillMaxWidth().height(52.dp).clip(PILL_SHAPE).background(PanelRaised).border(BorderStroke(1.dp, Line), PILL_SHAPE).clickable(onClick = onClick),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally)) {
        if (icon != null) UiIcon(icon, null, TextMain, 20.dp)
        Text(text, color = TextMain, fontWeight = FontWeight.Medium, fontSize = 15.sp)
    }
}

@Composable
fun BackButton(onClick: () -> Unit) {
    Box(Modifier.size(44.dp).clip(CircleShape).background(PanelRaised).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        UiIcon(R.drawable.ic_ui_back, "Back")
    }
}

@Composable
fun ScreenTitle(title: String, onBack: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        BackButton(onBack)
        Text(title, fontWeight = FontWeight.Bold, fontSize = 22.sp, color = TextMain)
    }
}

/** A small round icon, used for rows and reasons. */
@Composable
fun IconDot(@DrawableRes id: Int, color: Color, size: Dp = 40.dp) {
    Box(Modifier.size(size).clip(CircleShape).background(color.copy(alpha = 0.18f)), contentAlignment = Alignment.Center) {
        UiIcon(id, null, color, size * 0.55f)
    }
}

/** A half-open dial that fills up to the score. The number counts up with it. */
@Composable
fun RiskGauge(score: Int, color: Color, modifier: Modifier = Modifier) {
    val progress = remember { Animatable(0f) }
    LaunchedEffect(score) { progress.animateTo(score / 100f, tween(900, easing = FastOutSlowInEasing)) }
    Box(modifier.size(150.dp), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val width = 14.dp.toPx()
            val inset = width / 2
            val arc = Size(size.width - width, size.height - width)
            drawArc(Color.White.copy(alpha = 0.22f), 135f, 270f, false, Offset(inset, inset), arc, style = Stroke(width, cap = StrokeCap.Round))
            drawArc(Color.White, 135f, 270f * progress.value, false, Offset(inset, inset), arc, style = Stroke(width, cap = StrokeCap.Round))
        }
        Text("${(progress.value * 100).toInt()}", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 44.sp)
    }
}

/** Soft colour at the top of a screen, fading into the background. */
fun verdictBrush(color: Color) = Brush.verticalGradient(listOf(color, color.copy(alpha = 0.72f)))
