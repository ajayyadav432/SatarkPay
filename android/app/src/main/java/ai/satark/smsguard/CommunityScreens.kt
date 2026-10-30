package ai.satark.smsguard

import ai.satark.smsguard.theme.AppTheme
import ai.satark.smsguard.theme.Blue
import ai.satark.smsguard.theme.Sky
import ai.satark.smsguard.theme.Line
import ai.satark.smsguard.theme.PanelRaised
import ai.satark.smsguard.theme.RiskBlock
import ai.satark.smsguard.theme.RiskHold
import ai.satark.smsguard.theme.RiskSafe
import ai.satark.smsguard.theme.RiskUnknown
import ai.satark.smsguard.theme.RiskWarn
import ai.satark.smsguard.theme.TextMain
import ai.satark.smsguard.theme.TextSoft
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Drawable
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.painter.BitmapPainter
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import kotlinx.coroutines.delay
import org.json.JSONObject

@Composable
fun ThemeChip(store: Store) {
    val label = if (AppTheme.dark) "Switch to light mode" else "Switch to dark mode"
    Box(Modifier.size(36.dp).clip(PILL_SHAPE).background(PanelRaised).clickable { AppTheme.mode = if (AppTheme.dark) "light" else "dark"; store.theme = AppTheme.mode }
        .semantics { contentDescription = label }, contentAlignment = Alignment.Center) {
        Text(if (AppTheme.dark) "☀" else "☾", color = TextMain, fontSize = 16.sp)
    }
}

@Composable
fun LanguageRow(store: Store) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        ThemeChip(store)
        AppLang.ALL.forEach { (code, label) ->
            val on = AppLang.code == code
            Box(Modifier.clip(PILL_SHAPE).background(if (on) Blue else PanelRaised).clickable { AppLang.code = code; store.language = code }.padding(horizontal = 12.dp, vertical = 8.dp)) {
                Text(label, color = if (on) Color.White else TextMain, fontSize = 13.sp, fontWeight = FontWeight.Medium)
            }
        }
    }
}

/** The check has already finished. This shows what each step really found, slowly enough to read, and can be skipped. */
@Composable
fun StageView(result: JSONObject, onDone: () -> Unit) {
    val stages = result.optJSONArray("stages")?.let { a -> (0 until a.length()).map { a.getJSONObject(it) } }.orEmpty()
    var step by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) {
        while (step < stages.size) { delay(STAGE_MS); step += 1 }
        delay(STAGE_MS)
        onDone()
    }
    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text(tr("checking"), fontWeight = FontWeight.Bold, fontSize = 22.sp, color = TextMain)
        Box(Modifier.fillMaxWidth().height(8.dp).clip(PILL_SHAPE).background(PanelRaised)) {
            Box(Modifier.fillMaxWidth(if (stages.isEmpty()) 1f else step.toFloat() / stages.size).height(8.dp).clip(PILL_SHAPE).background(Blue))
        }
        stages.forEachIndexed { i, stage ->
            val done = i < step
            val warn = stage.optBoolean("warn")
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(28.dp).clip(PILL_SHAPE).background(if (!done) PanelRaised else if (warn) RiskWarn else RiskSafe), contentAlignment = Alignment.Center) {
                    Text(if (!done) "" else if (warn) "!" else "✓", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                }
                Column {
                    Text(tr("stage_" + stage.optString("id")), color = if (done) TextMain else TextSoft, fontSize = 15.sp)
                    if (done) Text(tr(if (warn) "stage_warn" else "stage_ok"), color = TextSoft, fontSize = 12.sp)
                }
            }
        }
        Text("${result.optDouble("latency_ms", 0.0).toInt().coerceAtLeast(1)} ms", color = TextSoft, fontSize = 13.sp)
        SecondaryButton(tr("skip"), onClick = onDone)
    }
}

data class UpiApp(val pkg: String, val label: String, val icon: Drawable)

/** The UPI apps really installed on this phone. Nothing is listed that the phone does not have. */
fun installedUpiApps(context: Context): List<UpiApp> {
    val pm = context.packageManager
    val probe = Intent(Intent.ACTION_VIEW, Uri.parse("upi://pay"))
    return pm.queryIntentActivities(probe, 0).filter { it.activityInfo.packageName != context.packageName }
        .distinctBy { it.activityInfo.packageName }
        .map { UpiApp(it.activityInfo.packageName, it.loadLabel(pm).toString(), it.loadIcon(pm)) }
        .sortedBy { it.label.lowercase() }
}

@Composable
fun UpiAppRow(enabled: Boolean, onPick: (UpiApp) -> Unit) {
    val context = LocalContext.current
    val apps = remember { installedUpiApps(context) }
    if (apps.isEmpty()) return
    Text(tr("your_apps"), fontWeight = FontWeight.SemiBold, fontSize = 15.sp, color = TextMain)
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        apps.forEach { app ->
            Column(Modifier.clip(CARD_SHAPE).background(PanelRaised).clickable(enabled = enabled) { onPick(app) }.padding(10.dp).size(width = 76.dp, height = 76.dp),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(4.dp)) {
                val painter = remember(app.pkg) { BitmapPainter(app.icon.toBitmap(96, 96).asImageBitmap()) }
                Image(painter, contentDescription = app.label, alpha = if (enabled) 1f else 0.4f, modifier = Modifier.size(40.dp))
                Text(app.label, color = if (enabled) TextMain else TextSoft, fontSize = 11.sp, maxLines = 2)
            }
        }
    }
}

@Composable
fun FeedScreen(store: Store, onBack: () -> Unit) {
    val context = LocalContext.current
    var posts by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var categories by remember { mutableStateOf(listOf("Other")) }
    var problem by remember { mutableStateOf("") }
    var writing by remember { mutableStateOf(false) }
    var payee by remember { mutableStateOf("") }
    var body by remember { mutableStateOf("") }
    var category by remember { mutableStateOf("Other") }

    fun work(job: () -> Unit) = Thread {
        val err = try { job(); null } catch (e: Exception) { e.message ?: e.javaClass.simpleName }
        (context as? ComponentActivity)?.runOnUiThread { problem = err ?: "" }
    }.start()
    fun load() = work {
        val data = SatarkClient.posts(store.serverUrl)
        val list = data.getJSONArray("posts").let { a -> (0 until a.length()).map { a.getJSONObject(it) } }
        val kinds = data.getJSONArray("categories").let { a -> (0 until a.length()).map { a.getString(it) } }
        (context as? ComponentActivity)?.runOnUiThread { posts = list; categories = kinds }
    }
    LaunchedEffect(Unit) { load() }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenTitle(tr("feed"), onBack)
        LanguageRow(store)
        Text(tr("feed_intro"), color = TextSoft, fontSize = 13.sp)
        if (!writing) PrimaryButton(tr("share"), icon = R.drawable.ic_ui_flag) { writing = true }
        else Panel {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(value = payee, onValueChange = { payee = it.take(100) }, singleLine = true, label = { Text(tr("upi_opt")) }, modifier = Modifier.fillMaxWidth())
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    categories.forEach { c ->
                        Box(Modifier.clip(PILL_SHAPE).background(if (c == category) Blue else PanelRaised).clickable { category = c }.padding(horizontal = 12.dp, vertical = 8.dp)) {
                            Text(c, color = if (c == category) Color.White else TextMain, fontSize = 13.sp)
                        }
                    }
                }
                OutlinedTextField(value = body, onValueChange = { body = it.take(1000) }, label = { Text(tr("what")) }, minLines = 3, modifier = Modifier.fillMaxWidth())
                PrimaryButton(tr("post"), enabled = body.trim().length >= 10) {
                    val p = payee.trim().lowercase(); val b = body.trim(); val c = category
                    work { SatarkClient.addPost(store.serverUrl, p, c, b); load() }
                    payee = ""; body = ""; writing = false
                }
            }
        }
        if (problem.isNotEmpty()) Text(problem, color = RiskBlock, fontSize = 14.sp)
        if (posts.isEmpty()) Text(tr("empty"), color = TextSoft, fontSize = 14.sp)
        posts.forEach { post -> PostCard(post, store, ::work, ::load) }
    }
}

@Composable
private fun PostCard(post: JSONObject, store: Store, work: (() -> Unit) -> Unit, reload: () -> Unit) {
    val context = LocalContext.current
    val id = post.getInt("id")
    val mine = post.optInt("my_vote")
    var open by remember(id) { mutableStateOf(false) }
    var comments by remember(id) { mutableStateOf<List<JSONObject>>(emptyList()) }
    var text by remember(id) { mutableStateOf("") }
    fun loadComments() = work {
        val a = SatarkClient.comments(store.serverUrl, id).getJSONArray("comments")
        val list = (0 until a.length()).map { a.getJSONObject(it) }
        (context as? ComponentActivity)?.runOnUiThread { comments = list }
    }
    Panel(padding = 14.dp) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                VoteButton("▲", mine == 1) { work { SatarkClient.vote(store.serverUrl, id, if (mine == 1) 0 else 1); reload() } }
                Text(post.optInt("votes").toString(), color = TextMain, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                VoteButton("▼", mine == -1) { work { SatarkClient.vote(store.serverUrl, id, if (mine == -1) 0 else -1); reload() } }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(post.optString("category") + " · " + post.optString("author"), color = TextSoft, fontSize = 12.sp)
                val payee = post.optString("payee")
                if (payee.isNotEmpty()) Text(payee, fontFamily = FontFamily.Monospace, color = TextMain, fontSize = 13.sp)
                if (post.optBoolean("blocked")) Tag(tr("blocked"), RiskBlock)
                else if (post.optInt("reports") > 0) Tag(post.optInt("reports").toString() + " " + tr("reports"), RiskHold)
                Text(post.optString("body"), color = TextMain, fontSize = 14.sp)
                Text("${tr("comments")} (${post.optInt("comments")})", color = Sky, fontSize = 13.sp, fontWeight = FontWeight.Medium,
                    modifier = Modifier.clickable { open = !open; if (open) loadComments() })
                if (open) {
                    comments.forEach { Text(it.optString("author") + ": " + it.optString("body"), color = TextMain, fontSize = 13.sp) }
                    OutlinedTextField(value = text, onValueChange = { text = it.take(500) }, label = { Text(tr("add_comment")) }, modifier = Modifier.fillMaxWidth())
                    if (text.isNotBlank()) SecondaryButton(tr("send")) {
                        val t = text.trim(); text = ""
                        work { SatarkClient.addComment(store.serverUrl, id, t); loadComments(); reload() }
                    }
                }
            }
        }
    }
}

@Composable
private fun VoteButton(mark: String, on: Boolean, onClick: () -> Unit) {
    Box(Modifier.size(36.dp).clip(PILL_SHAPE).clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        Text(mark, color = if (on) Sky else TextSoft, fontSize = 15.sp)
    }
}

@Composable
private fun Tag(text: String, color: Color) {
    Box(Modifier.clip(PILL_SHAPE).background(color.copy(alpha = 0.18f)).border(1.dp, Line, PILL_SHAPE).padding(horizontal = 10.dp, vertical = 3.dp)) {
        Text(text, color = TextMain, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
fun HistoryScreen(store: Store, onBack: () -> Unit) {
    val context = LocalContext.current
    var rows by remember { mutableStateOf<List<JSONObject>>(emptyList()) }
    var query by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    var format by remember { mutableStateOf("csv") }
    var kind by remember { mutableStateOf("") }

    fun load() = Thread {
        val result = runCatching { SatarkClient.history(store.serverUrl, query.trim(), kind).getJSONArray("checks") }
        (context as? ComponentActivity)?.runOnUiThread {
            result.onSuccess { a -> rows = (0 until a.length()).map { a.getJSONObject(it) } }
            result.onFailure { message = it.message ?: it.javaClass.simpleName }
        }
    }.start()
    LaunchedEffect(query, kind) { delay(250); load() }

    // The person chooses where the file goes, so the app needs no storage permission.
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri: Uri? ->
        if (uri != null) Thread {
            val outcome = runCatching {
                val text = SatarkClient.exportHistory(store.serverUrl, format, query.trim())
                context.contentResolver.openOutputStream(uri)!!.use { it.write(text.toByteArray(Charsets.UTF_8)) }
            }
            (context as? ComponentActivity)?.runOnUiThread { message = outcome.fold({ tr("saved") }, { it.message ?: it.javaClass.simpleName }) }
        }.start()
    }

    Column(Modifier.fillMaxSize().safeDrawingPadding().padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ScreenTitle(tr("history"), onBack)
        LanguageRow(store)
        Text(tr("history_intro"), color = TextSoft, fontSize = 13.sp)
        OutlinedTextField(value = query, onValueChange = { query = it.take(100) }, singleLine = true, label = { Text(tr("search")) }, modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("" to "kind_all", "payment" to "kind_payment", "sms" to "kind_sms", "email" to "kind_email", "link" to "kind_link").forEach { (key, label) ->
                Box(Modifier.clip(PILL_SHAPE).background(if (kind == key) Blue else PanelRaised).clickable { kind = key }.padding(horizontal = 12.dp, vertical = 8.dp)) {
                    Text(tr(label), color = if (kind == key) Color.White else TextMain, fontSize = 13.sp)
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            SecondaryButton(tr("save_csv"), Modifier.weight(1f)) { format = "csv"; save.launch("satarkpay-history.csv") }
            SecondaryButton(tr("save_json"), Modifier.weight(1f)) { format = "json"; save.launch("satarkpay-history.json") }
        }
        if (message.isNotEmpty()) Text(message, color = TextMain, fontSize = 14.sp)
        if (rows.isEmpty()) Text(tr("empty"), color = TextSoft, fontSize = 14.sp)
        rows.forEach { row ->
            val color = when (row.optString("action")) { "ALLOW" -> RiskUnknown; "WARN" -> RiskWarn; "HOLD" -> RiskHold; "BLOCK" -> RiskBlock; else -> RiskUnknown }
            Panel(padding = 14.dp) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(44.dp).clip(PILL_SHAPE).background(color), contentAlignment = Alignment.Center) {
                        Text(row.optInt("score").toString(), color = Color.White, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    }
                    Column(Modifier.weight(1f)) {
                        Text(row.optString("subject"), color = TextMain, fontFamily = FontFamily.Monospace, fontSize = 13.sp, maxLines = 2)
                        Text(row.optString("when") + " · " + row.optString("kind") + " · " + row.optString("action") + row.optString("outcome").let { if (it.isEmpty()) "" else " · $it" }, color = TextSoft, fontSize = 12.sp)
                    }
                }
            }
        }
        if (rows.isNotEmpty()) SecondaryButton(tr("clear")) {
            Thread {
                val outcome = runCatching { SatarkClient.clearHistory(store.serverUrl) }
                (context as? ComponentActivity)?.runOnUiThread { outcome.onSuccess { rows = emptyList() }; outcome.onFailure { message = it.message ?: it.javaClass.simpleName } }
            }.start()
        }
    }
}

private const val STAGE_MS = 280L
