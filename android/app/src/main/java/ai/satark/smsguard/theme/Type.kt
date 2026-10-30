package ai.satark.smsguard.theme

import ai.satark.smsguard.R
import androidx.compose.material3.Typography
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

@OptIn(ExperimentalTextApi::class)
private fun openSans(weight: FontWeight) =
    Font(R.font.open_sans, weight, variationSettings = FontVariation.Settings(FontVariation.weight(weight.weight)))

val OpenSans = FontFamily(listOf(FontWeight.Normal, FontWeight.Medium, FontWeight.SemiBold, FontWeight.Bold, FontWeight.ExtraBold).map(::openSans))

// Every Material text style uses Open Sans, so screens do not have to name it.
val Typography = Typography().run {
    fun TextStyle.sans() = copy(fontFamily = OpenSans)
    copy(
        displayLarge = displayLarge.sans(), displayMedium = displayMedium.sans(), displaySmall = displaySmall.sans(),
        headlineLarge = headlineLarge.sans(), headlineMedium = headlineMedium.sans(), headlineSmall = headlineSmall.sans(),
        titleLarge = titleLarge.sans(), titleMedium = titleMedium.sans(), titleSmall = titleSmall.sans(),
        bodyLarge = bodyLarge.sans(), bodyMedium = bodyMedium.sans(), bodySmall = bodySmall.sans(),
        labelLarge = labelLarge.sans(), labelMedium = labelMedium.sans(), labelSmall = labelSmall.sans(),
    )
}
