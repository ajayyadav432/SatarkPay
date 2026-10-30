package ai.satark.smsguard

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import ai.satark.smsguard.theme.SatarkAISMSGuardTheme
import java.text.DateFormat
import java.util.Date

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannels(this)
        enableEdgeToEdge()
        // A QR picture shared to this app from WhatsApp or the gallery.
        val shared = if (intent?.action == Intent.ACTION_SEND)
            IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java) ?: intent.clipData?.getItemAt(0)?.uri else null
        setContent {
            SatarkAISMSGuardTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { App(shared) }
            }
        }
    }
}

private sealed class Screen {
    data object Home : Screen()
    data object Scan : Screen()
    data class Review(val qr: Scanned.Upi?) : Screen()
    data class Result(val check: PayCheck) : Screen()
    data class Link(val url: String) : Screen()
    data class NotPayment(val text: String) : Screen()
}

@Composable
private fun App(shared: Uri?) {
    val context = LocalContext.current
    val store = remember { Store(context) }
    var screen by remember { mutableStateOf<Screen>(Screen.Home) }
    var note by remember { mutableStateOf("") }
    fun show(raw: String) {
        screen = when (val q = UpiQr.parse(raw)) {
            is Scanned.Upi -> Screen.Review(q)
            is Scanned.Link -> Screen.Link(q.url)
            is Scanned.Other -> Screen.NotPayment(q.text)
        }
    }
    LaunchedEffect(shared) {
        if (shared != null) readQrFromImage(context, shared) { text -> if (text != null) show(text) else note = "No QR code found in that picture." }
    }
    val home = { screen = Screen.Home }
    BackHandler(screen != Screen.Home) { if (screen !is Screen.Result) home() }
    when (val s = screen) {
        Screen.Home -> HomeScreen(store, note, onScan = { note = ""; screen = Screen.Scan }, onEnter = { note = ""; screen = Screen.Review(null) })
        Screen.Scan -> ScanScreen(home, ::show)
        is Screen.Review -> ReviewScreen(s.qr, store, home) { screen = Screen.Result(it) }
        is Screen.Result -> ResultScreen(s.check, store, home)
        is Screen.Link -> LinkScreen(s.url, store, home)
        is Screen.NotPayment -> {
            LaunchedEffect(s) { note = "That QR code is not a UPI payment or a web link: " + s.text.take(80); screen = Screen.Home }
        }
    }
}

private val LEVEL_COLOR = mapOf(
    "Safe" to Color(0xFF16A34A), "Low" to Color(0xFF8A8FA3), "Medium" to Color(0xFFF5A524),
    "High" to Color(0xFFF07A4A), "Critical" to Color(0xFFDC3545),
)
private val EMERALD = Color(0xFF059669)
private const val SAMPLE_SCAM =
    "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login"

private fun permissionsNeeded(): Array<String> =
    if (Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.POST_NOTIFICATIONS)
    else arrayOf(Manifest.permission.RECEIVE_SMS)

@Composable
private fun HomeScreen(store: Store, note: String, onScan: () -> Unit, onEnter: () -> Unit) {
    val context = LocalContext.current
    var showConnection by remember { mutableStateOf(false) }
    var server by remember { mutableStateOf(store.serverUrl) }
    var code by remember { mutableStateOf(store.pairingCode) }
    var recent by remember { mutableStateOf(store.recent()) }
    var status by remember { mutableStateOf("") }
    fun granted() = permissionsNeeded().all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }
    var allowed by remember { mutableStateOf(granted()) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { allowed = granted() }

    // Refresh the list when a new SMS has been checked.
    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) { recent = store.recent() }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(SmsReceiver.ACTION_UPDATED), ContextCompat.RECEIVER_NOT_EXPORTED)
        onDispose { context.unregisterReceiver(receiver) }
    }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Image(painterResource(R.drawable.ic_logo), contentDescription = "SatarkAI logo", modifier = Modifier.size(48.dp))
            Spacer(Modifier.width(10.dp))
            Column {
                Text("SatarkPay", fontWeight = FontWeight.Bold, fontSize = 20.sp)
                Text("Check a UPI payment before you pay", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }

        Button(onClick = onScan, modifier = Modifier.fillMaxWidth().height(64.dp), colors = ButtonDefaults.buttonColors(containerColor = EMERALD)) {
            Text("Scan UPI QR", fontSize = 18.sp, fontWeight = FontWeight.Bold)
        }
        OutlinedButton(onClick = onEnter, modifier = Modifier.fillMaxWidth()) { Text("Enter a UPI ID") }
        if (note.isNotEmpty()) Text(note, color = Color(0xFFF07A4A), fontSize = 14.sp)

        if (!allowed) {
            Button(onClick = { ask.launch(permissionsNeeded()) }, modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(containerColor = EMERALD)) { Text("Also check my SMS: allow SMS and notifications") }
        } else {
            Text("✓ SMS protection is on", color = EMERALD, fontWeight = FontWeight.SemiBold)
        }

        OutlinedButton(onClick = { showConnection = !showConnection }, modifier = Modifier.fillMaxWidth()) {
            Text(if (showConnection) "Hide laptop connection" else "Laptop connection")
        }
        if (showConnection) {
        OutlinedTextField(value = server, onValueChange = { server = it; store.serverUrl = it }, singleLine = true,
            label = { Text("SatarkPay address (laptop)") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = code, onValueChange = { code = it; store.pairingCode = it }, singleLine = true,
            label = { Text("Pairing code") }, modifier = Modifier.fillMaxWidth())
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = {
                status = "Checking…"
                Thread {
                    val ok = runCatching { SatarkClient.health(store.serverUrl) }.getOrDefault(false)
                    val fixed = if (ok) Retry.unchecked(context) else 0
                    (context as? ComponentActivity)?.runOnUiThread {
                        recent = store.recent()
                        status = when {
                            !ok -> "✗ Cannot reach the laptop"
                            fixed > 0 -> "✓ Connected · $fixed rechecked"
                            else -> "✓ Connected"
                        }
                    }
                }.start()
            }) { Text("Test connection") }
            Spacer(Modifier.width(12.dp))
            Text(status, fontSize = 14.sp)
        }

        OutlinedButton(onClick = {
            status = "Sending sample…"
            Thread {
                // Same path as a real SMS (laptop analysis + notification), clearly marked as a sample.
                val sender = "Sample (test)"
                val item = try {
                    val r = SatarkClient.checkSms(store.serverUrl, store.pairingCode, sender, SAMPLE_SCAM, "sample-${System.currentTimeMillis()}")
                    Checked.fromResponse(sender, SAMPLE_SCAM, r)
                } catch (e: Exception) {
                    Checked(System.currentTimeMillis(), sender, SAMPLE_SCAM, null, null, null, null, e.message ?: e.javaClass.simpleName)
                }
                store.add(item)
                Notifier.show(context, item)
                (context as? ComponentActivity)?.runOnUiThread { recent = store.recent(); status = if (item.level != null) "✓ Sample checked" else "✗ Cannot reach the laptop" }
            }.start()
        }, modifier = Modifier.fillMaxWidth()) { Text("Try a sample scam SMS") }
        }

        val unchecked = recent.count { it.level == null }
        if (unchecked > 0) {
            Button(onClick = {
                status = "Rechecking…"
                Thread {
                    val fixed = Retry.unchecked(context)
                    (context as? ComponentActivity)?.runOnUiThread {
                        recent = store.recent()
                        status = if (fixed > 0) "✓ $fixed rechecked" else "✗ Cannot reach the laptop"
                    }
                }.start()
            }, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF07A4A))) {
                Text("Retry $unchecked unchecked message" + if (unchecked == 1) "" else "s")
            }
        }

        Text("Recently checked", fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
        if (recent.isEmpty()) {
            Text("Nothing checked yet. Scans and SMS appear here.", color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 14.sp)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(recent) { RecentCard(it) }
        }
    }
}

@Composable
private fun RecentCard(item: Checked) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                val color = LEVEL_COLOR[item.level] ?: Color.Gray
                Box(Modifier.background(color, RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 2.dp)) {
                    Text(if (item.level != null) "${item.level} ${item.score}" else "Not checked", color = Color.White,
                        fontWeight = FontWeight.Bold, fontSize = 13.sp)
                }
                Spacer(Modifier.width(8.dp))
                Text(item.sender, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, modifier = Modifier.weight(1f))
                Text(DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(item.time)), fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (item.ownLevel != null)
                Text("This message alone: ${item.ownLevel} ${item.ownScore} · raised by this sender's earlier messages",
                    fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(item.text, maxLines = 2, overflow = TextOverflow.Ellipsis, fontSize = 14.sp)
            val note = item.error ?: listOfNotNull(item.category?.takeIf { it != "None" }, item.reason).joinToString(" · ")
            if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
