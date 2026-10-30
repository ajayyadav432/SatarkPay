package ai.satark.smsguard

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import org.json.JSONObject

private val ACTION_COLOR = mapOf(
    "ALLOW" to Color(0xFF16A34A), "WARN" to Color(0xFFF5A524), "HOLD" to Color(0xFFF07A4A), "BLOCK" to Color(0xFFDC3545),
)
private val SIMULATED_ID = Regex("@sim[a-z]*$")
private const val WARN_PAUSE_SECONDS = 5    // the server enforces these too
private const val HOLD_PAUSE_SECONDS = 15

/** Simulated IDs have a history in this demo. A real ID has none, so what the model says about its history means nothing. */
fun isSimulatedId(vpa: String) = SIMULATED_ID.containsMatchIn(vpa)

@Composable
private fun ScreenHeader(title: String, onBack: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(onClick = onBack) { Text("Back") }
        Spacer(Modifier.width(12.dp))
        Text(title, fontWeight = FontWeight.Bold, fontSize = 20.sp)
    }
}

/** The camera, with a way out for a QR code that is on this same phone. */
@Composable
fun ScanScreen(onBack: () -> Unit, onFound: (String) -> Unit) {
    val context = LocalContext.current
    fun granted() = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    var allowed by remember { mutableStateOf(granted()) }
    var problem by remember { mutableStateOf("") }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed = it }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? ->
        if (uri != null) readQrFromImage(context, uri) { text -> if (text != null) onFound(text) else problem = "No QR code found in that picture." }
    }
    LaunchedEffect(Unit) { if (!allowed) ask.launch(Manifest.permission.CAMERA) }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenHeader("Scan a UPI QR", onBack)
        if (allowed) {
            QrCamera(Modifier.fillMaxWidth().aspectRatio(1f), onFound)
            Text("Point the camera at the QR code. Nothing is paid by scanning here.", fontSize = 14.sp)
        } else {
            Text("The camera is needed to scan. Pictures stay on this phone.", fontSize = 14.sp)
            Button(onClick = { ask.launch(Manifest.permission.CAMERA) }, modifier = Modifier.fillMaxWidth()) { Text("Allow camera") }
        }
        OutlinedButton(onClick = { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }, modifier = Modifier.fillMaxWidth()) {
            Text("Use a screenshot or photo instead")
        }
        if (problem.isNotEmpty()) Text(problem, color = Color(0xFFDC3545), fontSize = 14.sp)
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

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenHeader(if (start != null) "What the QR says" else "Enter a UPI ID", onBack)
        if (start?.name != null) {
            Text("Name in the QR: ${start.name}", fontWeight = FontWeight.SemiBold)
            Text("Anyone can type any name into a QR code. It does not prove who gets the money.", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        OutlinedTextField(value = payee, onValueChange = { payee = it }, singleLine = true, readOnly = start != null,
            label = { Text("Money goes to (UPI ID)") }, modifier = Modifier.fillMaxWidth())
        // A fixed amount in a QR stays fixed. The person may change only what the QR left open.
        OutlinedTextField(value = amount, onValueChange = { amount = it }, singleLine = true, readOnly = start?.amount != null,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text("Amount (₹)") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = note, onValueChange = { note = it.take(200) }, readOnly = start?.note != null,
            label = { Text("Note") }, modifier = Modifier.fillMaxWidth())
        Button(enabled = !busy, modifier = Modifier.fillMaxWidth().height(52.dp), colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF059669)), onClick = {
            val value = amount.trim().toDoubleOrNull()
            val id = payee.trim().lowercase()
            problem = when {
                !UpiQr.isUpiId(id) -> "That does not look like a UPI ID. Example: name@bank"
                value == null || value <= 0 || value > 10_000_000 -> "Enter an amount in rupees."
                else -> ""
            }
            if (problem.isNotEmpty() || value == null) return@Button
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
        }) { Text(if (busy) "Checking…" else "Check before paying", fontSize = 16.sp) }
        if (problem.isNotEmpty()) Text(problem, color = Color(0xFFDC3545), fontSize = 14.sp)
    }
}

/** One finished check. */
data class PayCheck(val payee: String, val amount: Double, val result: JSONObject?, val error: String?) {
    fun toChecked(note: String): Checked {
        val r = result!!
        return Checked(System.currentTimeMillis(), "QR: $payee", "₹${amount.toLong()}" + if (note.isNotEmpty()) " · $note" else "",
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

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // Green would read as "safe". For a real ID the system does not know that, so the banner stays neutral.
        val banner = if (!simulated && action == "ALLOW") Color(0xFF475569) else ACTION_COLOR[action] ?: Color.Gray
        Box(Modifier.fillMaxWidth().background(banner, RoundedCornerShape(16.dp)).padding(16.dp)) {
            Column {
                Text(headline, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 22.sp)
                Text("Risk ${r.optInt("score")} / 100", color = Color.White, fontSize = 14.sp)
            }
        }
        Text("₹${"%,.2f".format(check.amount)} to ${check.payee}", fontFamily = FontFamily.Monospace, fontSize = 14.sp)
        OutlinedButton(onClick = { hindi = !hindi }) { Text(if (hindi) "English" else "हिंदी") }
        if (reasons.isNotEmpty()) Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(if (hindi) "क्यों" else "Why", fontWeight = FontWeight.SemiBold)
                reasons.forEach { Text("• $it", fontSize = 14.sp) }
            }
        }
        advice.forEach { Text(it, fontSize = 14.sp) }
        if (!simulated) Text(
            if (hindi) "यह असली UPI ID है। SatarkPay के पास सिर्फ़ सिम्युलेटेड भुगतानों का इतिहास है, इसलिए यह सिर्फ़ ID, राशि और नोट देखता है। यह गारंटी नहीं है कि यह सुरक्षित है।"
            else "This is a real UPI ID. SatarkPay only has history for simulated payments, so this checks the ID, the amount and the note. It is not a guarantee that the payment is safe.",
            fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)

        val done = finished
        if (done != null) {
            Text(done, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
            Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) { Text("Done") }
        } else {
            if (action != "ALLOW") {
                Button(onClick = { decide("reported", "Reported. No money moved.") }, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFDC3545))) { Text("Report this scam") }
                OutlinedButton(onClick = { context.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:1930"))) }, modifier = Modifier.fillMaxWidth()) { Text("Call 1930 (cyber fraud helpline)") }
            }
            OutlinedButton(onClick = { decide("cancelled", "Stopped. No money moved.") }, modifier = Modifier.fillMaxWidth()) { Text(if (simulated) "Do not pay" else "Done") }
            // Only simulated money can move here. For a real ID the person pays in their own UPI app, or does not.
            if (simulated && action != "BLOCK") {
                Button(enabled = left <= 0, onClick = { decide("paid", "Simulated payment sent. It is on the dashboard.") }, modifier = Modifier.fillMaxWidth()) {
                    Text(when {
                        left > 0 -> "Pay anyway (wait $left s)"
                        action == "ALLOW" -> "Simulate payment"
                        else -> "Pay anyway (simulated)"
                    })
                }
            }
        }
        if (problem.isNotEmpty()) Text(problem, color = Color(0xFFDC3545), fontSize = 14.sp)
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
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenHeader("This QR is a web link", onDone)
        Text("Not a UPI payment. It opens this page:", fontSize = 14.sp)
        Text(url, fontFamily = FontFamily.Monospace, fontSize = 14.sp)
        val a = answer
        if (a != null) {
            val risky = a.optBoolean("needs_warning")
            Box(Modifier.fillMaxWidth().background(if (risky) Color(0xFFDC3545) else Color(0xFF16A34A), RoundedCornerShape(16.dp)).padding(16.dp)) {
                Text((if (risky) "Do not open or pay. " else "No warning signs found. ") + "${a.optString("level")} ${a.optInt("score")} / 100", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            }
            a.optJSONArray("factors")?.let { arr -> (0 until arr.length()).forEach { Text("• " + arr.getJSONObject(it).optString("title"), fontSize = 14.sp) } }
        } else if (problem.isEmpty()) Text("Checking…")
        if (problem.isNotEmpty()) Text(problem, color = Color(0xFFDC3545), fontSize = 14.sp)
    }
}
