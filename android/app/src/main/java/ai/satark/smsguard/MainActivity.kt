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
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat
import ai.satark.smsguard.theme.BrandBrush
import ai.satark.smsguard.theme.Ink
import ai.satark.smsguard.theme.RiskBlock
import ai.satark.smsguard.theme.RiskHold
import ai.satark.smsguard.theme.RiskSafe
import ai.satark.smsguard.theme.RiskUnknown
import ai.satark.smsguard.theme.RiskWarn
import ai.satark.smsguard.theme.SatarkPayTheme
import ai.satark.smsguard.theme.Sky
import ai.satark.smsguard.theme.TextMain
import ai.satark.smsguard.theme.TextSoft
import java.text.DateFormat
import java.util.Date

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannels(this)
        enableEdgeToEdge(SystemBarStyle.dark(android.graphics.Color.TRANSPARENT), SystemBarStyle.dark(android.graphics.Color.TRANSPARENT))
        // A QR picture shared to this app from WhatsApp or the gallery.
        val shared = if (intent?.action == Intent.ACTION_SEND)
            IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java) ?: intent.clipData?.getItemAt(0)?.uri else null
        setContent {
            SatarkPayTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { App(shared) }
            }
        }
    }
}

private sealed class Screen {
    data object Home : Screen()
    data object Scan : Screen()
    data object Connection : Screen()
    data object Login : Screen()
    data object Message : Screen()
    data object LinkEntry : Screen()
    data class Review(val qr: Scanned.Upi?) : Screen()
    data class Result(val check: PayCheck) : Screen()
    data class Link(val url: String) : Screen()
}

@Composable
private fun App(shared: Uri?) {
    val context = LocalContext.current
    val store = remember { Store(context) }
    var screen by remember { mutableStateOf<Screen>(if (store.sessionToken != null) Screen.Home else Screen.Login) }
    var role by remember { mutableStateOf(store.sessionRole) }
    var note by remember { mutableStateOf("") }
    remember { SatarkClient.token = store.sessionToken }
    fun endSession() {
        store.clearSession()
        SatarkClient.token = null
        role = null
        screen = Screen.Login
    }
    fun logOut() {
        val server = store.serverUrl
        Thread { runCatching { SatarkClient.logout(server) }; SatarkClient.token = null }.start()
        store.clearSession()
        role = null
        screen = Screen.Login
    }
    // The server forgets logins when it restarts, so check this one is still good.
    LaunchedEffect(Unit) {
        if (store.sessionToken != null) Thread {
            val ended = runCatching { SatarkClient.me(store.serverUrl) }.exceptionOrNull() is SatarkClient.LoginNeeded
            if (ended) (context as? ComponentActivity)?.runOnUiThread { endSession() }
        }.start()
    }
    fun show(raw: String) {
        when (val q = UpiQr.parse(raw)) {
            is Scanned.Upi -> screen = Screen.Review(q)
            is Scanned.Link -> screen = Screen.Link(q.url)
            is Scanned.Other -> { note = "That QR code is not a UPI payment or a web link: " + q.text.take(80); screen = Screen.Home }
        }
    }
    fun showPicture(uri: Uri) {
        readQrFromImage(context, uri) { text -> if (text != null) show(text) else { note = "No QR code found in that picture."; screen = Screen.Home } }
    }
    LaunchedEffect(shared, role) { if (shared != null && role == "user") showPicture(shared) }
    val home = { screen = Screen.Home }
    BackHandler(screen != Screen.Home && screen != Screen.Login) {
        if (screen !is Screen.Result) { if (store.sessionToken != null) home() else screen = Screen.Login }
    }
    when (val s = screen) {
        Screen.Login -> LoginScreen(store, onConnection = { screen = Screen.Connection }) { role = store.sessionRole; screen = Screen.Home }
        Screen.Home -> when (role) {
            "merchant" -> MerchantHome(store, ::logOut, ::endSession)
            "admin" -> AdminHome(store, ::logOut, ::endSession)
            else -> HomeScreen(store, note, onScan = { note = ""; screen = Screen.Scan }, onEnter = { note = ""; screen = Screen.Review(null) },
                onPicture = { note = ""; showPicture(it) }, onConnection = { screen = Screen.Connection }, onLogout = ::logOut, onMessage = { screen = Screen.Message }, onLink = { screen = Screen.LinkEntry })
        }
        Screen.Scan -> ScanScreen(home, ::show, ::showPicture)
        Screen.Message -> MessageScreen(store, home)
        Screen.LinkEntry -> LinkEntryScreen(home) { screen = Screen.Link(it) }
        Screen.Connection -> ConnectionScreen(store) { screen = if (store.sessionToken != null) Screen.Home else Screen.Login }
        is Screen.Review -> ReviewScreen(s.qr, store, home) { screen = Screen.Result(it) }
        is Screen.Result -> ResultScreen(s.check, store, home)
        is Screen.Link -> LinkScreen(s.url, store, home)
    }
}

private fun levelColor(level: String?) = when (level) {
    "Safe", "Low" -> RiskSafe
    "Medium" -> RiskWarn
    "High" -> RiskHold
    "Critical" -> RiskBlock
    else -> RiskUnknown
}
private const val SAMPLE_SCAM =
    "Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login"

private fun permissionsNeeded(): Array<String> =
    if (Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.POST_NOTIFICATIONS)
    else arrayOf(Manifest.permission.RECEIVE_SMS)

@Composable
private fun HomeScreen(store: Store, note: String, onScan: () -> Unit, onEnter: () -> Unit, onPicture: (Uri) -> Unit, onConnection: () -> Unit, onLogout: () -> Unit, onMessage: () -> Unit, onLink: () -> Unit) {
    val context = LocalContext.current
    var recent by remember { mutableStateOf(store.recent()) }
    var online by remember { mutableStateOf<Boolean?>(null) }
    fun granted() = permissionsNeeded().all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }
    var allowed by remember { mutableStateOf(granted()) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { allowed = granted() }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri: Uri? -> if (uri != null) onPicture(uri) }

    LaunchedEffect(Unit) {
        Thread {
            val ok = runCatching { SatarkClient.health(store.serverUrl) }.getOrDefault(false)
            (context as? ComponentActivity)?.runOnUiThread { online = ok }
        }.start()
    }
    // Refresh the list when a new SMS has been checked.
    DisposableEffect(Unit) {
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) { recent = store.recent() }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(SmsReceiver.ACTION_UPDATED), ContextCompat.RECEIVER_NOT_EXPORTED)
        onDispose { context.unregisterReceiver(receiver) }
    }

    val bars = WindowInsets.safeDrawing.asPaddingValues()
    Box(Modifier.fillMaxSize()) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = bars.calculateTopPadding() + 12.dp, bottom = bars.calculateBottomPadding() + 16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Image(painterResource(R.drawable.ic_logo), contentDescription = "SatarkPay logo", modifier = Modifier.size(42.dp))
                Spacer(Modifier.width(10.dp))
                Text("SatarkPay", fontWeight = FontWeight.Bold, fontSize = 24.sp, color = TextMain, modifier = Modifier.weight(1f))
                ConnectionPill(online, onConnection)
                Spacer(Modifier.width(8.dp))
                LogoutButton(onLogout)
            }
        }
        item {
            Column(Modifier.fillMaxWidth().clip(CARD_SHAPE).background(BrandBrush).padding(20.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Check before you pay", fontWeight = FontWeight.Bold, fontSize = 26.sp, color = Color.White)
                Text("Scan any UPI QR. See the risk and the reasons before you enter your PIN.", fontSize = 14.sp, color = Color.White.copy(alpha = 0.9f))
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth().height(58.dp).clip(PILL_SHAPE).background(Color.White).clickable(onClick = onScan),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.CenterHorizontally)) {
                    UiIcon(R.drawable.ic_ui_qr, null, Ink, 24.dp)
                    Text("Scan UPI QR", color = Ink, fontWeight = FontWeight.Bold, fontSize = 17.sp)
                }
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                SecondaryButton("From photo", Modifier.weight(1f), R.drawable.ic_ui_image) { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                SecondaryButton("Enter UPI ID", Modifier.weight(1f), R.drawable.ic_ui_edit, onEnter)
            }
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                SecondaryButton("Check message", Modifier.weight(1f), R.drawable.ic_ui_sms, onMessage)
                SecondaryButton("Check link", Modifier.weight(1f), R.drawable.ic_ui_link, onLink)
            }
        }
        if (note.isNotEmpty()) item { Text(note, color = RiskWarn, fontSize = 14.sp) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Stat("Checked here", recent.count { it.level != null }.toString(), TextMain, Modifier.weight(1f))
                Stat("Flagged", recent.count { it.level in setOf("Medium", "High", "Critical") }.toString(), RiskBlock, Modifier.weight(1f))
            }
        }
        item {
            Panel(Modifier.clickable(enabled = !allowed) { ask.launch(permissionsNeeded()) }, padding = 14.dp) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    IconDot(R.drawable.ic_ui_sms, if (allowed) RiskSafe else Sky)
                    Column(Modifier.weight(1f)) {
                        Text("SMS protection", fontWeight = FontWeight.SemiBold, color = TextMain, fontSize = 15.sp)
                        Text(if (allowed) "On. Scam messages raise a warning." else "Tap to also check incoming SMS.", color = TextSoft, fontSize = 13.sp)
                    }
                    if (allowed) UiIcon(R.drawable.ic_ui_check, "On", RiskSafe)
                }
            }
        }
        item {
            Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Recently checked", fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = TextMain, modifier = Modifier.weight(1f))
                if (recent.isNotEmpty()) Text("Clear", color = Sky, fontWeight = FontWeight.Medium, fontSize = 14.sp,
                    modifier = Modifier.clip(PILL_SHAPE).clickable { store.clearRecent(); recent = store.recent() }.padding(horizontal = 10.dp, vertical = 6.dp))
            }
            if (recent.isEmpty()) Text("Nothing checked yet. Scans and SMS appear here.", color = TextSoft, fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp))
        }
        items(recent) { RecentCard(it) }
    }
    // Keeps the list from running under the clock.
    Box(Modifier.fillMaxWidth().height(bars.calculateTopPadding()).background(Ink))
    }
}

@Composable
private fun ConnectionPill(online: Boolean?, onClick: () -> Unit) {
    val (text, color) = when (online) {
        true -> "Connected" to RiskSafe
        false -> "Laptop offline" to RiskBlock
        null -> "Checking" to TextSoft
    }
    Row(Modifier.clip(PILL_SHAPE).background(color.copy(alpha = 0.16f)).clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(color))
        Text(text, color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun Stat(label: String, value: String, color: Color, modifier: Modifier) {
    Panel(modifier, padding = 14.dp) {
        Column {
            Text(value, fontWeight = FontWeight.Bold, fontSize = 28.sp, color = color)
            Text(label, fontSize = 13.sp, color = TextSoft)
        }
    }
}

/** The address and pairing code, kept off the main screen. */
@Composable
private fun ConnectionScreen(store: Store, onBack: () -> Unit) {
    val context = LocalContext.current
    var server by remember { mutableStateOf(store.serverUrl) }
    var code by remember { mutableStateOf(store.pairingCode) }
    var status by remember { mutableStateOf("") }
    var unchecked by remember { mutableStateOf(store.recent().count { it.level == null }) }
    fun refresh() { unchecked = store.recent().count { it.level == null } }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ScreenTitle("Laptop connection", onBack)
        Text("Over USB, run ./run.sh phone on the laptop and use http://127.0.0.1:8000. Over Wi-Fi, use the address printed by ./run.sh wifi.", color = TextSoft, fontSize = 14.sp)
        OutlinedTextField(value = server, onValueChange = { server = it; store.serverUrl = it }, singleLine = true,
            label = { Text("SatarkPay address (laptop)") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = code, onValueChange = { code = it; store.pairingCode = it }, singleLine = true,
            label = { Text("Pairing code (for SMS)") }, modifier = Modifier.fillMaxWidth())
        PrimaryButton("Test connection", icon = R.drawable.ic_ui_laptop, onClick = {
            status = "Checking…"
            Thread {
                val ok = runCatching { SatarkClient.health(store.serverUrl) }.getOrDefault(false)
                val fixed = if (ok) Retry.unchecked(context) else 0
                (context as? ComponentActivity)?.runOnUiThread {
                    refresh()
                    status = when {
                        !ok -> "✗ Cannot reach the laptop"
                        fixed > 0 -> "✓ Connected · $fixed rechecked"
                        else -> "✓ Connected"
                    }
                }
            }.start()
        })
        SecondaryButton("Try a sample scam SMS", icon = R.drawable.ic_ui_sms) {
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
                (context as? ComponentActivity)?.runOnUiThread { refresh(); status = if (item.level != null) "✓ Sample checked" else "✗ Cannot reach the laptop" }
            }.start()
        }
        if (unchecked > 0) {
            SecondaryButton("Retry $unchecked unchecked message" + if (unchecked == 1) "" else "s") {
                status = "Rechecking…"
                Thread {
                    val fixed = Retry.unchecked(context)
                    (context as? ComponentActivity)?.runOnUiThread { refresh(); status = if (fixed > 0) "✓ $fixed rechecked" else "✗ Cannot reach the laptop" }
                }.start()
            }
        }
        if (status.isNotEmpty()) Text(status, color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun RecentCard(item: Checked) {
    // A real UPI ID has no history here, so a low score is "no warnings", never "safe".
    val realScan = item.sender.startsWith("QR: ") && !isSimulatedId(item.sender) && item.level in setOf("Safe", "Low")
    val color = if (realScan) RiskUnknown else levelColor(item.level)
    val label = if (realScan) "No warnings found" else item.level ?: "Not checked"
    Panel(padding = 14.dp) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.size(46.dp).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
                Text(item.score?.toString() ?: "?", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.sender, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = TextMain, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                    Text(DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(item.time)), fontSize = 12.sp, color = TextSoft)
                }
                Text(label, color = if (realScan) TextSoft else color, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
                if (item.ownLevel != null)
                    Text("This message alone: ${item.ownLevel} ${item.ownScore} · raised by this sender's earlier messages", fontSize = 12.sp, color = TextSoft)
                Text(item.text, maxLines = 2, overflow = TextOverflow.Ellipsis, fontSize = 14.sp, color = TextMain)
                val note = if (realScan) "" else item.error ?: listOfNotNull(item.category?.takeIf { it != "None" }, item.reason).joinToString(" · ")
                if (note.isNotEmpty()) Text(note, fontSize = 12.sp, color = TextSoft, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
