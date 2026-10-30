package ai.satark.smsguard

import androidx.activity.ComponentActivity
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
import androidx.compose.foundation.layout.fillMaxHeight
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ai.satark.smsguard.theme.BrandBrush
import ai.satark.smsguard.theme.Ink
import ai.satark.smsguard.theme.PanelRaised
import ai.satark.smsguard.theme.RiskBlock
import ai.satark.smsguard.theme.RiskHold
import ai.satark.smsguard.theme.RiskSafe
import ai.satark.smsguard.theme.RiskUnknown
import ai.satark.smsguard.theme.RiskWarn
import ai.satark.smsguard.theme.Sky
import ai.satark.smsguard.theme.TextMain
import ai.satark.smsguard.theme.TextSoft
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject

private const val REFRESH_MS = 3000L
private val ROLES = listOf(
    Triple("user", "User", "Check a payment before you pay."),
    Triple("merchant", "Merchant", "See what really reached your shop."),
    Triple("admin", "Admin", "Watch every payment and review alerts."),
)
private val ATTACKS = listOf("fake_collect" to "Fake collect", "phishing_link" to "Phishing link", "mule_ring" to "Mule ring", "takeover" to "SIM swap", "coached" to "\"Digital arrest\"")

fun rupees(value: Double): String = "₹" + "%,.0f".format(value)

private fun actionColor(action: String) = when (action) {
    "ALLOW" -> RiskSafe
    "WARN" -> RiskWarn
    "HOLD" -> RiskHold
    "BLOCK" -> RiskBlock
    else -> RiskUnknown
}

/** One login screen for the three kinds of account. The server checks the password and each role's rights. */
@Composable
fun LoginScreen(store: Store, onConnection: () -> Unit, onLoggedIn: () -> Unit) {
    val context = LocalContext.current
    var role by remember { mutableStateOf("user") }
    var signingUp by remember { mutableStateOf(false) }
    var name by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var problem by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    if (role == "admin") signingUp = false

    fun run(call: () -> JSONObject) {
        busy = true
        problem = ""
        Thread {
            val result = runCatching(call)
            (context as? ComponentActivity)?.runOnUiThread {
                busy = false
                result.onSuccess {
                    store.saveSession(it.getString("token"), it.getString("role"), it.getString("name"))
                    SatarkClient.token = store.sessionToken
                    onLoggedIn()
                }.onFailure {
                    problem = if (it is java.io.IOException) "Cannot reach the laptop. Check the laptop connection." else it.message ?: "Could not log in."
                }
            }
        }.start()
    }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(20.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Image(painterResource(R.drawable.ic_logo), contentDescription = "SatarkPay logo", modifier = Modifier.size(60.dp).align(Alignment.CenterHorizontally))
        Text("SatarkPay", fontWeight = FontWeight.Bold, fontSize = 28.sp, color = TextMain, modifier = Modifier.align(Alignment.CenterHorizontally))
        Row(Modifier.fillMaxWidth().clip(PILL_SHAPE).background(PanelRaised).padding(4.dp)) {
            ROLES.forEach { (id, label, _) ->
                val on = id == role
                Box(Modifier.weight(1f).height(44.dp).clip(PILL_SHAPE).then(if (on) Modifier.background(BrandBrush) else Modifier).clickable { role = id; problem = "" }, contentAlignment = Alignment.Center) {
                    Text(label, color = if (on) Color.White else TextSoft, fontWeight = FontWeight.SemiBold, fontSize = 15.sp)
                }
            }
        }
        Text(ROLES.first { it.first == role }.third, color = TextSoft, fontSize = 14.sp)
        val roleLabel = ROLES.first { it.first == role }.second
        PrimaryButton("Use test login: $roleLabel", enabled = !busy) { run { SatarkClient.testLogin(store.serverUrl, role) } }
        Text("No password needed. Simulated data only.", color = TextSoft, fontSize = 13.sp, modifier = Modifier.align(Alignment.CenterHorizontally))
        if (signingUp) OutlinedTextField(value = name, onValueChange = { name = it }, singleLine = true,
            label = { Text(if (role == "merchant") "Shop name" else "Your name") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = username, onValueChange = { username = it }, singleLine = true, label = { Text("Username") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(value = password, onValueChange = { password = it }, singleLine = true, label = { Text("Password") }, modifier = Modifier.fillMaxWidth(),
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
        if (problem.isNotEmpty()) Text(problem, color = RiskBlock, fontSize = 14.sp)
        SecondaryButton(when { busy -> "Please wait…"; signingUp -> "Sign up"; else -> "Log in" }) {
            if (busy || username.isBlank() || password.isEmpty()) return@SecondaryButton
            if (signingUp) run { SatarkClient.signUp(store.serverUrl, role, username.trim(), password, name.trim()) }
            else run { SatarkClient.login(store.serverUrl, role, username.trim(), password) }
        }
        if (role == "admin") Text("Admin accounts cannot be created here.", color = TextSoft, fontSize = 13.sp, modifier = Modifier.align(Alignment.CenterHorizontally))
        else Text(if (signingUp) "Already have an account? Log in" else "New here? Sign up", color = Sky, fontWeight = FontWeight.Medium, fontSize = 15.sp,
            modifier = Modifier.align(Alignment.CenterHorizontally).clip(PILL_SHAPE).clickable { signingUp = !signingUp; problem = "" }.padding(8.dp))
        SecondaryButton("Laptop connection", icon = R.drawable.ic_ui_laptop, onClick = onConnection)
    }
}

@Composable
fun RoleHeader(title: String, subtitle: String, onLogout: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Image(painterResource(R.drawable.ic_logo), contentDescription = "SatarkPay logo", modifier = Modifier.size(42.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.Bold, fontSize = 20.sp, color = TextMain, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, fontSize = 13.sp, color = TextSoft, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        LogoutButton(onLogout)
    }
}

@Composable
fun LogoutButton(onClick: () -> Unit) {
    Box(Modifier.size(44.dp).clip(CircleShape).background(PanelRaised).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        UiIcon(R.drawable.ic_ui_logout, "Log out", TextMain, 20.dp)
    }
}

@Composable
private fun Tile(label: String, value: String, color: Color, modifier: Modifier) {
    Panel(modifier, padding = 14.dp) {
        Column {
            Text(value, fontWeight = FontWeight.Bold, fontSize = 24.sp, color = color, maxLines = 1)
            Text(label, fontSize = 13.sp, color = TextSoft)
        }
    }
}

/** Runs a request off the main thread. Tells the caller when the login has ended, so it can return to the login screen. */
private suspend fun <T> load(onLoggedOut: () -> Unit, onProblem: (String) -> Unit, block: () -> T): T? {
    val result = withContext(Dispatchers.IO) { runCatching(block) }
    result.onFailure { if (it is SatarkClient.LoginNeeded) onLoggedOut() else onProblem("The laptop did not answer. Trying again…") }
    if (result.isSuccess) onProblem("")
    return result.getOrNull()
}

/** The shop's view: what really arrived. A customer's screenshot proves nothing. */
@Composable
fun MerchantHome(store: Store, onLogout: () -> Unit, onLoggedOut: () -> Unit) {
    val context = LocalContext.current
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var problem by remember { mutableStateOf("") }
    var refresh by remember { mutableIntStateOf(0) }
    LaunchedEffect(refresh) {
        while (true) {
            load(onLoggedOut, { problem = it }) { SatarkClient.merchantPayments(store.serverUrl) }?.let { data = it }
            delay(REFRESH_MS)
        }
    }
    val bars = WindowInsets.safeDrawing.asPaddingValues()
    val rows = data?.optJSONArray("rows")?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } }.orEmpty()
    Box(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = bars.calculateTopPadding() + 12.dp, bottom = bars.calculateBottomPadding() + 16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            item { RoleHeader(data?.optString("name")?.ifEmpty { null } ?: "Your shop", data?.optString("shop") ?: "Merchant", onLogout) }
            item {
                Column(Modifier.fillMaxWidth().clip(CARD_SHAPE).background(BrandBrush).padding(20.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Received", color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp)
                    Text(rupees(data?.optDouble("received_total", 0.0) ?: 0.0), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 40.sp)
                    Text("Trust this list, not the customer's screen.", color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp)
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Tile("Payments received", (data?.optInt("received") ?: 0).toString(), TextMain, Modifier.weight(1f))
                    Tile("Not received", (data?.optInt("not_received") ?: 0).toString(), RiskHold, Modifier.weight(1f))
                }
            }
            item {
                SecondaryButton("A customer pays (simulated)", icon = R.drawable.ic_ui_qr) {
                    Thread {
                        val err = runCatching { SatarkClient.customerPays(store.serverUrl, data?.optString("shop") ?: "") }.exceptionOrNull()
                        (context as? ComponentActivity)?.runOnUiThread { if (err != null) problem = err.message ?: "Could not do that." else refresh += 1 }
                    }.start()
                }
            }
            if (problem.isNotEmpty()) item { Text(problem, color = RiskWarn, fontSize = 14.sp) }
            item { Text("Incoming payments", fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = TextMain) }
            if (rows.isEmpty()) item { Text("Waiting for customers.", color = TextSoft, fontSize = 14.sp) }
            items(rows, key = { it.optString("txn_id") }) { row ->
                val got = row.optString("status") == "moved"
                Panel(padding = 14.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        IconDot(if (got) R.drawable.ic_ui_check else R.drawable.ic_ui_warning, if (got) RiskSafe else RiskHold)
                        Column(Modifier.weight(1f)) {
                            Text(rupees(row.optDouble("amount")), fontWeight = FontWeight.Bold, fontSize = 18.sp, color = TextMain)
                            Text(if (got) "Received" else "Not received", color = if (got) RiskSafe else RiskHold, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                        }
                        Text(row.optString("time"), fontSize = 12.sp, color = TextSoft)
                    }
                }
            }
        }
        Box(Modifier.fillMaxWidth().height(bars.calculateTopPadding()).background(Ink))
    }
}

/** The analyst's view: live numbers, attacks to launch, and alerts to review. */
@Composable
fun AdminHome(store: Store, onLogout: () -> Unit, onLoggedOut: () -> Unit) {
    val context = LocalContext.current
    var kpis by remember { mutableStateOf<JSONObject?>(null) }
    var alerts by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var problem by remember { mutableStateOf("") }
    var refresh by remember { mutableIntStateOf(0) }
    LaunchedEffect(refresh) {
        while (true) {
            load(onLoggedOut, { problem = it }) { SatarkClient.kpis(store.serverUrl) to SatarkClient.alerts(store.serverUrl) }?.let { (k, a) ->
                kpis = k
                alerts = (0 until a.length()).map { a.getJSONObject(it) }
            }
            delay(REFRESH_MS)
        }
    }
    fun act(block: () -> Unit) {
        Thread {
            val err = runCatching(block).exceptionOrNull()
            (context as? ComponentActivity)?.runOnUiThread { if (err != null) problem = err.message ?: "Could not do that." else { problem = ""; refresh += 1 } }
        }.start()
    }
    val bars = WindowInsets.safeDrawing.asPaddingValues()
    val running = kpis?.optBoolean("running") == true
    Box(Modifier.fillMaxSize()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = bars.calculateTopPadding() + 12.dp, bottom = bars.calculateBottomPadding() + 16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            item { RoleHeader("Fraud analyst", if (running) "Live: payments are flowing" else "Paused", onLogout) }
            item {
                Column(Modifier.fillMaxWidth().clip(CARD_SHAPE).background(BrandBrush).padding(20.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Money stopped before it left", color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp)
                    Text(rupees(kpis?.optJSONObject("rupees")?.optDouble("stopped", 0.0) ?: 0.0), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 40.sp)
                    Text("Simulated payments", color = Color.White.copy(alpha = 0.9f), fontSize = 13.sp)
                }
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Tile("Scored", "%,d".format(kpis?.optInt("scored") ?: 0), TextMain, Modifier.weight(1f))
                    Tile("Alerts", "%,d".format(kpis?.optInt("alerts") ?: 0), RiskHold, Modifier.weight(1f))
                    Tile("Stopped", "%,d".format(kpis?.optInt("stopped") ?: 0), RiskBlock, Modifier.weight(1f))
                }
            }
            item {
                SecondaryButton(if (running) "Pause the stream" else "Start the stream") { act { SatarkClient.simRun(store.serverUrl, !running) } }
            }
            item { Text("Launch an attack", fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = TextMain) }
            ATTACKS.chunked(2).forEach { pair ->
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        pair.forEach { (id, label) -> SecondaryButton(label, Modifier.weight(1f)) { act { SatarkClient.attack(store.serverUrl, id) } } }
                        if (pair.size == 1) Spacer(Modifier.weight(1f))
                    }
                }
            }
            if (problem.isNotEmpty()) item { Text(problem, color = RiskWarn, fontSize = 14.sp) }
            item { Text("Alerts", fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = TextMain) }
            if (alerts.isEmpty()) item { Text("Nothing yet. Launch an attack above.", color = TextSoft, fontSize = 14.sp) }
            items(alerts, key = { it.optInt("id") }) { alert ->
                val color = actionColor(alert.optString("action"))
                val status = alert.optString("status")
                Panel(padding = 14.dp) {
                    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Box(Modifier.size(46.dp).clip(CircleShape).background(color), contentAlignment = Alignment.Center) {
                                Text(alert.optInt("score").toString(), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                            }
                            Column(Modifier.weight(1f)) {
                                Text(rupees(alert.optDouble("amount")) + " · " + alert.optString("action"), fontWeight = FontWeight.Bold, fontSize = 16.sp, color = TextMain)
                                Text(alert.optString("payee"), fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = TextSoft, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                        when (status) {
                            "confirmed_fraud" -> Text("Confirmed scam", color = RiskBlock, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            "false_alarm" -> Text("Marked as a false alarm", color = TextSoft, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                            else -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                SecondaryButton("Confirm scam", Modifier.weight(1f)) { act { SatarkClient.labelAlert(store.serverUrl, alert.optInt("id"), "confirmed_fraud") } }
                                SecondaryButton("False alarm", Modifier.weight(1f)) { act { SatarkClient.labelAlert(store.serverUrl, alert.optInt("id"), "false_alarm") } }
                            }
                        }
                    }
                }
            }
        }
        Box(Modifier.fillMaxWidth().height(bars.calculateTopPadding()).background(Ink))
    }
}
