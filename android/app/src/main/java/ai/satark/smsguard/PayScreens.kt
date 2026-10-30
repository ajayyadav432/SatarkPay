package ai.satark.smsguard

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import ai.satark.smsguard.theme.BrandBrush
import ai.satark.smsguard.theme.Ink
import ai.satark.smsguard.theme.RiskBlock
import ai.satark.smsguard.theme.RiskHold
import ai.satark.smsguard.theme.RiskSafe
import ai.satark.smsguard.theme.RiskUnknown
import ai.satark.smsguard.theme.RiskWarn
import ai.satark.smsguard.theme.Sky
import ai.satark.smsguard.theme.TextMain
import ai.satark.smsguard.theme.TextSoft
import kotlinx.coroutines.delay
import org.json.JSONObject

private val ACTION_COLOR = mapOf("ALLOW" to RiskSafe, "WARN" to RiskWarn, "HOLD" to RiskHold, "BLOCK" to RiskBlock)
private val SIMULATED_ID = Regex("@sim[a-z]*$")
private const val WARN_PAUSE_SECONDS = 5    // the server enforces these too
private const val HOLD_PAUSE_SECONDS = 15

/** Simulated IDs have a history in this demo. A real ID has none, so what the model says about its history means nothing. */
fun isSimulatedId(vpa: String) = SIMULATED_ID.containsMatchIn(vpa)

/** The dimmed camera, with a clear window, corners and a moving line. */
@Composable
fun ScanOverlay(modifier: Modifier = Modifier) {
    val line by rememberInfiniteTransition(label = "scan").animateFloat(0f, 1f, infiniteRepeatable(tween(1800, easing = LinearEasing), RepeatMode.Reverse), label = "line")
    Canvas(modifier.graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }) {
        val side = size.width * 0.72f
        val left = (size.width - side) / 2
        val top = (size.height - side) / 2 - 40.dp.toPx()
        val radius = 24.dp.toPx()
        drawRect(Color.Black.copy(alpha = 0.62f))
        drawRoundRect(Color.Transparent, Offset(left, top), Size(side, side), CornerRadius(radius), blendMode = BlendMode.Clear)
        val arm = side * 0.16f
        val stroke = Stroke(5.dp.toPx(), cap = StrokeCap.Round)
        val box = Rect(left, top, left + side, top + side)
        fun corner(start: Float, x: Float, y: Float) = drawArc(Color.White, start, 90f, false, Offset(x, y), Size(radius * 2, radius * 2), style = stroke)
        corner(180f, box.left, box.top); corner(270f, box.right - radius * 2, box.top); corner(0f, box.right - radius * 2, box.bottom - radius * 2); corner(90f, box.left, box.bottom - radius * 2)
        fun bar(a: Offset, b: Offset) = drawLine(Color.White, a, b, 5.dp.toPx(), StrokeCap.Round)
        bar(Offset(box.left + radius, box.top), Offset(box.left + radius + arm, box.top)); bar(Offset(box.left, box.top + radius), Offset(box.left, box.top + radius + arm))
        bar(Offset(box.right - radius, box.top), Offset(box.right - radius - arm, box.top)); bar(Offset(box.right, box.top + radius), Offset(box.right, box.top + radius + arm))
        bar(Offset(box.left + radius, box.bottom), Offset(box.left + radius + arm, box.bottom)); bar(Offset(box.left, box.bottom - radius), Offset(box.left, box.bottom - radius - arm))
        bar(Offset(box.right - radius, box.bottom), Offset(box.right - radius - arm, box.bottom)); bar(Offset(box.right, box.bottom - radius), Offset(box.right, box.bottom - radius - arm))
        val y = top + radius + (side - radius * 2) * line
        drawLine(Sky, Offset(left + 16.dp.toPx(), y), Offset(left + side - 16.dp.toPx(), y), 3.dp.toPx(), StrokeCap.Round)
    }
}

/** The words over the camera. Kept apart from the camera so it can be seen in a test without filming the room. */
@Composable
fun ScanChrome(onBack: () -> Unit, onPhoto: () -> Unit, problem: String) {
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            BackButton(onBack)
            Text("Scan a UPI QR", fontWeight = FontWeight.Bold, fontSize = 22.sp, color = Color.White)
        }
        Spacer(Modifier.weight(1f))
        Text("Point the camera at the QR code. Nothing is paid by scanning here.", color = Color.White, fontSize = 15.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(bottom = 14.dp))
        if (problem.isNotEmpty()) Text(problem, color = Color.White, fontSize = 14.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp))
        SecondaryButton("Use a screenshot or photo instead", icon = R.drawable.ic_ui_image, onClick = onPhoto)
    }
}

/** The camera, with a way out for a QR code that is on this same phone. */
@Composable
fun ScanScreen(onBack: () -> Unit, onFound: (String) -> Unit, onPicture: (Uri) -> Unit) {
    val context = LocalContext.current
    val haptic = LocalHapticFeedback.current
    fun granted() = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    var allowed by remember { mutableStateOf(granted()) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed = it }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? -> if (uri != null) onPicture(uri) }
    LaunchedEffect(Unit) { if (!allowed) ask.launch(Manifest.permission.CAMERA) }

    Box(Modifier.fillMaxSize().background(Ink)) {
        if (allowed) {
            QrCamera(Modifier.fillMaxSize()) { haptic.performHapticFeedback(HapticFeedbackType.LongPress); onFound(it) }
            ScanOverlay(Modifier.fillMaxSize())
        }
        ScanChrome(onBack, { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, "")
        if (!allowed) Column(Modifier.align(Alignment.Center).padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("The camera is needed to scan. Pictures stay on this phone.", color = TextMain, fontSize = 15.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
            PrimaryButton("Allow camera") { ask.launch(Manifest.permission.CAMERA) }
        }
    }
}

/** What the QR says, before anything is sent to the laptop. */
@Composable
fun ReviewScreen(start: Scanned.Upi?, store: Store, onBack: () -> Unit, onResult: (PayCheck) -> Unit) {
    val context = LocalContext.current
    var payee by remember { mutableStateOf(start?.payee ?: "") }
    var amount by remember { mutableStateOf(start?.amount?.let { if (it % 1.0 == 0.0) it.toLong().toString() else it.toString() } ?: "") }
    var note by remember { mutableStateOf(start?.note ?: "") }
    var problem by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ScreenTitle(if (start != null) "What the QR says" else "Enter a UPI ID", onBack)

        Panel(padding = 20.dp) {
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val shown = (start?.name ?: payee).trim()
                Box(Modifier.size(64.dp).clip(CircleShape).background(BrandBrush), contentAlignment = Alignment.Center) {
                    Text(shown.take(1).uppercase().ifEmpty { "₹" }, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 26.sp)
                }
                if (start?.name != null) Text(start.name, fontWeight = FontWeight.SemiBold, fontSize = 18.sp, color = TextMain, textAlign = TextAlign.Center)
                if (start != null) Text(start.payee, fontFamily = FontFamily.Monospace, fontSize = 14.sp, color = TextSoft, textAlign = TextAlign.Center)
                if (start?.amount != null) Text("₹" + "%,.2f".format(start.amount), fontWeight = FontWeight.Bold, fontSize = 38.sp, color = TextMain)
                if (start?.note != null) Text("“${start.note}”", fontSize = 15.sp, color = TextMain, textAlign = TextAlign.Center)
            }
        }
        if (start == null) OutlinedTextField(value = payee, onValueChange = { payee = it }, singleLine = true,
            label = { Text("Money goes to (UPI ID)") }, modifier = Modifier.fillMaxWidth())
        // A fixed amount in a QR stays fixed. The person may change only what the QR left open.
        if (start?.amount == null) OutlinedTextField(value = amount, onValueChange = { amount = it }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("Amount (₹)") }, modifier = Modifier.fillMaxWidth())
        if (start?.note == null) OutlinedTextField(value = note, onValueChange = { note = it.take(200) },
            label = { Text("Note (optional)") }, modifier = Modifier.fillMaxWidth())
        if (start?.name != null) Text("Anyone can type any name into a QR code. It does not prove who gets the money.", fontSize = 13.sp, color = TextSoft)

        PrimaryButton(if (busy) "Checking…" else "Check before paying", enabled = !busy, icon = R.drawable.ic_ui_check, onClick = {
            val value = amount.trim().toDoubleOrNull()
            val id = payee.trim().lowercase()
            problem = when {
                !UpiQr.isUpiId(id) -> "That does not look like a UPI ID. Example: name@bank"
                value == null || value <= 0 || value > 10_000_000 -> "Enter an amount in rupees."
                else -> ""
            }
            if (problem.isNotEmpty() || value == null) return@PrimaryButton
            busy = true
            Thread {
                val check = try {
                    val r = SatarkClient.scorePayment(store.serverUrl, id, value, if (start != null) "QR" else "PAY", note.trim())
                    PayCheck(id, value, r, null)
                } catch (e: Exception) {
                    PayCheck(id, value, null, e.message ?: e.javaClass.simpleName)
                }
                if (check.result != null) store.add(check.toChecked(note.trim()))
                (context as? ComponentActivity)?.runOnUiThread {
                    busy = false
                    if (check.result != null) onResult(check) else problem = "Could not check: the laptop did not answer. Do not pay until you can check. (${check.error})"
                }
            }.start()
        })
        if (problem.isNotEmpty()) Text(problem, color = RiskBlock, fontSize = 14.sp)
    }
}

/** One finished check. */
data class PayCheck(val payee: String, val amount: Double, val result: JSONObject?, val error: String?) {
    fun toChecked(note: String): Checked {
        val r = result!!
        return Checked(System.currentTimeMillis(), "QR: $payee", "₹" + "%,.0f".format(amount) + if (note.isNotEmpty()) " · $note" else "",
            r.optString("level"), r.optInt("score"), null, r.optString("headline_en"), null)
    }
}

/** The decision, the reasons, and what the person can do next. This app never moves real money. */
@Composable
fun ResultScreen(check: PayCheck, store: Store, onDone: () -> Unit) {
    val context = LocalContext.current
    val r = check.result!!
    val action = r.optString("action")
    val simulated = isSimulatedId(check.payee)
    var hindi by remember { mutableStateOf(false) }
    var finished by remember { mutableStateOf<String?>(null) }
    var problem by remember { mutableStateOf("") }
    var left by remember { mutableIntStateOf(when (action) { "WARN" -> WARN_PAUSE_SECONDS; "HOLD" -> HOLD_PAUSE_SECONDS; else -> 0 }) }
    LaunchedEffect(Unit) { while (left > 0) { delay(1000); left -= 1 } }

    fun decide(decision: String, then: String) {
        Thread {
            val err = try { SatarkClient.outcome(store.serverUrl, r.optString("txn_id"), r.optString("token"), decision); null } catch (e: Exception) { e.message ?: e.javaClass.simpleName }
            (context as? ComponentActivity)?.runOnUiThread { if (err == null) finished = then else problem = err }
        }.start()
    }
    val lang = if (hindi) "text_hi" else "text_en"
    val reasons = r.optJSONArray("reasons")?.let { arr ->
        (0 until arr.length()).map { arr.getJSONObject(it) }
            .filter { simulated || it.optString("source") != "model" }     // "this account is 1 day old" is false for an ID the system has simply never seen
            .map { it.optString(lang) }
    }.orEmpty()
    val advice = r.optJSONArray("advice")?.let { arr -> (0 until arr.length()).map { arr.getJSONObject(it).optString(lang) } }.orEmpty()
    val headline = when {
        !simulated && action == "ALLOW" -> if (hindi) "कोई चेतावनी संकेत नहीं मिला" else "No warning signs found"
        hindi -> r.optString("headline_hi")
        else -> r.optString("headline_en")
    }
    // Green would read as "safe". For a real ID the system does not know that, so the banner stays neutral.
    val banner = if (!simulated && action == "ALLOW") RiskUnknown else ACTION_COLOR[action] ?: RiskUnknown

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Column(Modifier.fillMaxWidth().background(verdictBrush(banner)).statusBarsPadding().padding(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            RiskGauge(r.optInt("score"), banner)
            Text(headline, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 22.sp, textAlign = TextAlign.Center)
            Text("Risk ${r.optInt("score")} / 100", color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp)
        }
        Column(Modifier.navigationBarsPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Panel(padding = 14.dp) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("₹" + "%,.2f".format(check.amount), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = TextMain)
                        Text(check.payee, fontFamily = FontFamily.Monospace, fontSize = 13.sp, color = TextSoft)
                    }
                    SecondaryButton(if (hindi) "English" else "हिंदी", Modifier.size(width = 96.dp, height = 44.dp)) { hindi = !hindi }
                }
            }
            if (reasons.isNotEmpty()) Panel {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(if (hindi) "क्यों" else "Why", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = TextMain)
                    reasons.forEach {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            IconDot(R.drawable.ic_ui_warning, banner, 28.dp)
                            Text(it, fontSize = 14.sp, color = TextMain, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
            advice.forEach { Text(it, fontSize = 14.sp, color = TextSoft) }
            if (!simulated) Text(
                if (hindi) "यह असली UPI ID है। SatarkPay के पास सिर्फ़ सिम्युलेटेड भुगतानों का इतिहास है, इसलिए यह सिर्फ़ ID, राशि और नोट देखता है। यह गारंटी नहीं है कि यह सुरक्षित है।"
                else "This is a real UPI ID. SatarkPay only has history for simulated payments, so this checks the ID, the amount and the note. It is not a guarantee that the payment is safe.",
                fontSize = 13.sp, color = TextSoft)

            val done = finished
            if (done != null) {
                Text(done, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = TextMain)
                PrimaryButton("Done", onClick = onDone)
            } else {
                if (action != "ALLOW") {
                    PrimaryButton("Report this scam", color = RiskBlock, icon = R.drawable.ic_ui_flag) { decide("reported", "Reported. No money moved.") }
                    SecondaryButton("Call 1930 (cyber fraud helpline)", icon = R.drawable.ic_ui_phone) { context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:1930"))) }
                }
                SecondaryButton(if (simulated) "Do not pay" else "Done") { decide("cancelled", "Stopped. No money moved.") }
                // Only simulated money can move here. For a real ID the person pays in their own UPI app, or does not.
                if (simulated && action != "BLOCK") {
                    val label = when {
                        left > 0 -> "Pay anyway (wait $left s)"
                        action == "ALLOW" -> "Simulate payment"
                        else -> "Pay anyway (simulated)"
                    }
                    if (action == "ALLOW") PrimaryButton(label, enabled = left <= 0) { decide("paid", "Simulated payment sent. It is on the dashboard.") }
                    else PrimaryButton(label, enabled = left <= 0, color = RiskUnknown) { decide("paid", "Simulated payment sent. It is on the dashboard.") }
                }
            }
            if (problem.isNotEmpty()) Text(problem, color = RiskBlock, fontSize = 14.sp)
        }
    }
}

/** A QR code that holds a web link: scanning it opens a page, so the page is what gets checked. */
@Composable
fun LinkScreen(url: String, store: Store, onDone: () -> Unit) {
    var answer by remember { mutableStateOf<JSONObject?>(null) }
    var problem by remember { mutableStateOf("") }
    LaunchedEffect(url) {
        val result = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { runCatching { SatarkClient.checkUrl(store.serverUrl, url) } }
        result.onSuccess { answer = it }.onFailure { problem = "Could not check: the laptop did not answer. Do not open this link." }
    }
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ScreenTitle("This QR is a web link", onDone)
        Panel {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                IconDot(R.drawable.ic_ui_link, Sky)
                Column(Modifier.weight(1f)) {
                    Text("Not a UPI payment. It opens this page:", fontSize = 13.sp, color = TextSoft)
                    Text(url, fontFamily = FontFamily.Monospace, fontSize = 14.sp, color = TextMain)
                }
            }
        }
        val a = answer
        if (a != null) {
            val risky = a.optBoolean("needs_warning")
            val color = if (risky) RiskBlock else RiskUnknown
            Column(Modifier.fillMaxWidth().clip(CARD_SHAPE).background(verdictBrush(color)).padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                RiskGauge(a.optInt("score"), color)
                Text((if (risky) "Do not open or pay. " else "No warning signs found. ") + a.optString("level"), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 20.sp, textAlign = TextAlign.Center)
            }
            a.optJSONArray("factors")?.let { arr ->
                if (arr.length() > 0) Panel {
                    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Why", fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = TextMain)
                        (0 until arr.length()).forEach { i ->
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                IconDot(R.drawable.ic_ui_warning, color, 28.dp)
                                Text(arr.getJSONObject(i).optString("title"), fontSize = 14.sp, color = TextMain, modifier = Modifier.weight(1f))
                            }
                        }
                    }
                }
            }
        } else if (problem.isEmpty()) Text("Checking…", color = TextMain)
        if (problem.isNotEmpty()) Text(problem, color = RiskBlock, fontSize = 14.sp)
    }
}
