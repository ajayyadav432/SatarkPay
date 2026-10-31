package ai.satark.smsguard

import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import ai.satark.smsguard.theme.SatarkPayTheme
import androidx.compose.ui.graphics.Color
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Runs on a real phone against the real laptop server (./run.sh, with adb reverse tcp:8000 tcp:8000). Everything except the camera lens. */
class PayFlowTest {
    @get:Rule val rule = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val app = instrumentation.targetContext
    private val store = Store(app)

    // These tests must not leave anything in the person's own history.
    private val prefs = app.getSharedPreferences("satark", android.content.Context.MODE_PRIVATE)
    private val savedRecent = prefs.getString("recent", "[]")
    @org.junit.After fun restoreHistory() { prefs.edit().putString("recent", savedRecent).apply() }

    @Composable private fun Themed(content: @Composable () -> Unit) {
        SatarkPayTheme { Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) { content() } }
    }

    @org.junit.Before fun logIn() { logInAs("user") }
    @org.junit.After fun endLogin() { SatarkClient.token = null; AppLang.code = "en"; store.language = "en" }

    private fun logInAs(role: String) {
        store.serverUrl = Store.USB_SERVER
        SatarkClient.token = null
        SatarkClient.token = SatarkClient.testLogin(store.serverUrl, role).getString("token")
    }

    private fun readAsset(name: String): String? {
        val file = File(app.cacheDir, name)
        instrumentation.context.assets.open(name).use { input -> file.outputStream().use { input.copyTo(it) } }
        val latch = CountDownLatch(1)
        var text: String? = null
        readQrFromImage(app, Uri.fromFile(file)) { text = it; latch.countDown() }
        assertTrue("the reader did not answer", latch.await(30, TimeUnit.SECONDS))
        return text
    }

    private fun screenshot(name: String) {
        rule.mainClock.advanceTimeBy(1200)   // let the dial finish
        Thread.sleep(600)                    // the system allows only so many screenshots a second
        val bitmap = instrumentation.uiAutomation.takeScreenshot() ?: return
        File(app.getExternalFilesDir(null), "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    /** The picture, the review screen and the result, as a person meets them. */
    private fun scanAndCheck(picture: String) {
        val qr = UpiQr.parse(readAsset(picture)!!) as Scanned.Upi
        rule.setContent {
            var check by remember { mutableStateOf<PayCheck?>(null) }
            val c = check
            Themed { if (c == null) ReviewScreen(qr, store, {}) { check = it } else ResultScreen(c, store) {} }
        }
        screenshot("review_" + picture.substringAfterLast('_').substringBefore('.'))
        rule.onNodeWithText("Check before paying").performClick()
        rule.waitUntil(15000) { rule.onAllNodesWithText("Risk ", substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    @Test fun aScamQrIsReadFromAPictureAndHasTheRightContents() {
        val qr = UpiQr.parse(readAsset("satarkpay_qr_scam.png")!!) as Scanned.Upi
        assertEquals("olx.buyer.help77@simybl", qr.payee)
        assertEquals("scan to receive", qr.note)
        assertEquals(12000.0, qr.amount!!, 0.01)
    }

    @Test fun aLinkQrIsReadAsALink() {
        assertTrue(UpiQr.parse(readAsset("satarkpay_qr_link.png")!!) is Scanned.Link)
    }

    @Test fun aScamQrIsHeldAndCannotBePaidStraightAway() {
        scanAndCheck("satarkpay_qr_scam.png")
        rule.onNodeWithText("On hold", substring = true).assertExists()
        screenshot("result_scam")
        rule.onNodeWithText("Report this scam").performScrollTo().assertExists()
        rule.onAllNodesWithText("Simulate payment").assertCountEquals(0)
        rule.onAllNodesWithText("Open payment app", substring = true).assertCountEquals(0)
        rule.onNodeWithText("Pay anyway (wait", substring = true).performScrollTo().assertIsNotEnabled()
        rule.onNodeWithText("हिंदी").performClick()
        rule.onNodeWithText("रोक", substring = true).assertExists()
        screenshot("result_scam_hindi")
    }

    @Test fun theLocalShopGoesThroughAndReachesTheServer() {
        scanAndCheck("satarkpay_qr_shop.png")
        rule.onNodeWithText("Looks fine").assertExists()
        screenshot("result_shop")
        rule.onNodeWithText("Simulate payment").performScrollTo().performClick()
        rule.waitUntil(10000) { rule.onAllNodes(hasText("Simulated payment sent", substring = true)).fetchSemanticsNodes().isNotEmpty() }
    }

    @Test fun aRealUpiIdIsNeverCalledSafeAndCannotBePaidHere() {
        scanAndCheck("satarkpay_qr_real.png")
        rule.onAllNodesWithText("Looks fine").assertCountEquals(0)
        rule.onAllNodesWithText("Safe", substring = true).assertCountEquals(0)
        rule.onNodeWithText("This is a real UPI ID", substring = true).performScrollTo().assertExists()
        rule.onAllNodesWithText("Simulate payment").assertCountEquals(0)
        rule.onAllNodesWithText("1 day old", substring = true).assertCountEquals(0)
        rule.onNodeWithText("Open payment app", substring = true).performScrollTo().assertExists()
        screenshot("result_real")
    }

    @Test fun theScannerFrameIsDrawn() {
        rule.mainClock.autoAdvance = false     // its line moves for ever
        rule.setContent { androidx.compose.foundation.layout.Box(Modifier.fillMaxSize().background(Color(0xFF3B4A5A))) { ScanOverlay(Modifier.fillMaxSize()); ScanChrome({}, {}, "") } }
        rule.mainClock.advanceTimeBy(600)
        rule.onNodeWithText("Scan a UPI QR").assertExists()
        Thread.sleep(600)
        instrumentation.uiAutomation.takeScreenshot()?.let { b -> File(app.getExternalFilesDir(null), "scan_frame.png").outputStream().use { b.compress(Bitmap.CompressFormat.PNG, 100, it) } }
    }

    @Test fun theLoginScreenOffersThreeRolesAndRefusesAWrongPassword() {
        rule.setContent { Themed { LoginScreen(store, {}) {} } }
        listOf("User", "Merchant", "Admin").forEach { rule.onNodeWithText(it).assertExists() }
        rule.onNodeWithText("Merchant").performClick()
        rule.onNodeWithText("See what really reached your shop.").assertExists()
        rule.onNodeWithText("Username").performTextInput("ramesh")
        rule.onNodeWithText("Password").performTextInput("definitely-wrong")
        screenshot("login")
        var message = ""
        try { SatarkClient.login(store.serverUrl, "merchant", "ramesh", "definitely-wrong") } catch (e: IllegalStateException) { message = e.message!! }
        assertEquals("Wrong username or password.", message)
    }

    @Test fun aMerchantSeesItsOwnPaymentsAndNotTheAdminData() {
        logInAs("merchant")
        var refused = false
        try { SatarkClient.kpis(store.serverUrl) } catch (e: IllegalStateException) { refused = e.message!!.contains("cannot do that") }
        assertTrue("a merchant must not read admin numbers", refused)
        rule.setContent { Themed { MerchantHome(store, {}, {}) } }
        rule.waitUntil(10000) { rule.onAllNodes(hasText("Ramesh Kirana Store")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("A customer pays (simulated)").performClick()
        rule.waitUntil(15000) { rule.onAllNodes(hasText("Received")).fetchSemanticsNodes().size > 1 }
        screenshot("merchant")
    }

    @Test fun anAdminSeesTheNumbersAndCanLaunchAnAttack() {
        logInAs("admin")
        rule.setContent { Themed { AdminHome(store, {}, {}) } }
        rule.waitUntil(10000) { rule.onAllNodes(hasText("Scored")).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("Mule ring").performScrollTo().performClick()
        rule.waitUntil(30000) { rule.onAllNodes(hasText("Confirm scam")).fetchSemanticsNodes().isNotEmpty() }
        screenshot("admin")
    }

    @Test fun aPastedScamMessageIsFlagged() {
        rule.setContent { Themed { MessageScreen(store) {} } }
        rule.onNodeWithText("Message").performTextInput("Dear customer, your SBI account will be blocked today. Update your KYC immediately: http://sbi-kyc-update.xyz/login")
        rule.onNodeWithText("Check this message").performClick()
        rule.waitUntil(15000) { rule.onAllNodes(hasText("Do not reply", substring = true)).fetchSemanticsNodes().isNotEmpty() }
        screenshot("message")
    }

    @Test fun aSignUpWorksAndGivesAUsersRights() {
        SatarkClient.token = null
        val name = "phone" + System.currentTimeMillis()
        val me = SatarkClient.signUp(store.serverUrl, "user", name, "long-enough-pass", "Phone Tester")
        assertEquals("user", me.getString("role"))
        SatarkClient.token = me.getString("token")
        assertEquals("Phone Tester", SatarkClient.me(store.serverUrl).getString("name"))
    }

    @Test fun nobodyCanSignUpAsAdmin() {
        var message = ""
        try { SatarkClient.signUp(store.serverUrl, "admin", "phone.admin", "long-enough-pass", "Nope") } catch (e: IllegalStateException) { message = e.message!! }
        assertTrue(message, message.contains("cannot be created"))
    }

    @Test fun eachPortalHasATestLogin() {
        for ((role, label) in listOf("user" to "User", "merchant" to "Merchant", "admin" to "Admin")) {
            SatarkClient.token = null
            assertEquals(role, SatarkClient.testLogin(store.serverUrl, role).getString("role"))
        }
    }

    @Test fun aUserCannotReadAdminNumbers() {
        var refused = false
        try { SatarkClient.alerts(store.serverUrl) } catch (e: IllegalStateException) { refused = e.message!!.contains("cannot do that") }
        assertTrue(refused)
    }

    @Test fun aLinkQrIsCheckedAsAPage() {
        val url = (UpiQr.parse(readAsset("satarkpay_qr_link.png")!!) as Scanned.Link).url
        rule.setContent { Themed { LinkScreen(url, store) {} } }
        rule.waitUntil(15000) { rule.onAllNodesWithText("Do not open or pay", substring = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("State Bank of India", substring = true).assertExists()
        screenshot("result_link")
    }

    @Test fun aCheckShowsItsStepsAndCanBeSkipped() {
        val result = SatarkClient.scorePayment(store.serverUrl, "refund.helpdesk@simbank", 2999.0, "PAY", "Refund")
        rule.setContent { Themed { ResultScreen(PayCheck("refund.helpdesk@simbank", 2999.0, result, null), store) {} } }
        rule.onNodeWithText("Checking this payment").assertExists()
        rule.onNodeWithText("Skip to the result").performClick()
        rule.waitUntil(5000) { rule.onAllNodesWithText("Risk ", substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    @Test fun aDecisionReadsInTamil() {
        val result = SatarkClient.scorePayment(store.serverUrl, "refund.helpdesk@simbank", 2999.0, "PAY", "Refund")
        AppLang.code = "ta"
        rule.setContent { Themed { ResultScreen(PayCheck("refund.helpdesk@simbank", 2999.0, result, null), store) {} } }
        rule.waitUntil(15000) { rule.onAllNodesWithText("ஆபத்து", substring = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("இந்த மோசடியைப் புகார் செய்").performScrollTo().assertExists()
    }

    @Test fun theFeedShowsPostsWithRealDetailsHidden() {
        SatarkClient.addPost(store.serverUrl, "", "Other", "Phone test post, call 9876543210 about this.")
        rule.setContent { Themed { FeedScreen(store) {} } }
        rule.waitUntil(10000) { rule.onAllNodesWithText("Phone test post", substring = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onAllNodesWithText("9876543210", substring = true).assertCountEquals(0)
    }

    @Test fun historyListsAChecksAndExports() {
        SatarkClient.scorePayment(store.serverUrl, "history.check@simbank", 10.0, "PAY", "")
        rule.setContent { Themed { HistoryScreen(store) {} } }
        rule.waitUntil(10000) { rule.onAllNodesWithText("history.check@simbank", substring = true).fetchSemanticsNodes().isNotEmpty() }
        assert(SatarkClient.exportHistory(store.serverUrl, "csv", "history.check").contains("history.check@simbank"))
        assert(org.json.JSONArray(SatarkClient.exportHistory(store.serverUrl, "json", "history.check")).length() > 0)
    }

    @Test fun lightAndDarkCanBeSwitchedAndAreKept() {
        ai.satark.smsguard.theme.AppTheme.mode = "dark"
        rule.setContent { Themed { LanguageRow(store) } }
        rule.onNodeWithContentDescription("Switch to light mode").performClick()
        rule.onNodeWithContentDescription("Switch to dark mode").assertExists()
        assert(store.theme == "light")
        store.theme = "system"
        ai.satark.smsguard.theme.AppTheme.mode = "system"
    }

    // --- messages that arrive as a notification ---------------------------------------------------------------

    private val scamChat = "URGENT your SBI account is blocked. Update KYC now at http://sbi-kyc-update.xyz/login or lose your money"

    private fun chat(build: androidx.core.app.NotificationCompat.Builder.() -> Unit) =
        androidx.core.app.NotificationCompat.Builder(app, "risk").setSmallIcon(R.drawable.ic_stat_satark).apply(build).build()

    @Test fun anRcsChatIsReadFromItsNotification() {
        val person = androidx.core.app.Person.Builder().setName("VK-SBIBNK").build()
        val n = chat { setStyle(androidx.core.app.NotificationCompat.MessagingStyle(person).addMessage("old message", 1L, person).addMessage(scamChat, 2L, person)) }
        assertEquals("VK-SBIBNK" to scamChat, ChatListener.read(n))
    }

    @Test fun theOwnersMessageASummaryAndAStatusAreNotRead() {
        val me = androidx.core.app.Person.Builder().setName("Me").build()
        val own = chat { setStyle(androidx.core.app.NotificationCompat.MessagingStyle(me).addMessage(scamChat, 2L, null as androidx.core.app.Person?)) }
        assertEquals(null, ChatListener.read(own))
        assertEquals(null, ChatListener.read(chat { setContentTitle("WhatsApp"); setContentText("3 new messages") }))
        assertEquals(null, ChatListener.read(chat { setContentTitle("WhatsApp"); setContentText(scamChat); setGroup("g"); setGroupSummary(true) }))
        assertEquals("Rahul" to "see you at 5", ChatListener.read(chat { setContentTitle("Rahul"); setContentText("see you at 5") }))
    }

    @Test fun onlyMessagingAppsAreRead() {
        assertEquals(setOf("com.google.android.apps.messaging", "com.samsung.android.messaging", "com.whatsapp", "com.whatsapp.w4b"), ChatListener.APPS.keys)
    }

    @Test fun anSmsAndItsNotificationCountAsOneMessage() {
        assertTrue(Incoming.sameMessage(scamChat, "  " + scamChat.take(60).uppercase() + " "))
        assertTrue(!Incoming.sameMessage("ok thanks", "ok thanks a lot for the money"))
        val text = "${System.nanoTime()} $scamChat"
        val first = Incoming.check(app, "VK-SBIBNK", text, "sms", 1L)
        assertTrue("laptop answered: ${first?.error}", first?.level in setOf("Medium", "High", "Critical"))
        assertTrue((first?.score ?: 0) in 0..100)
        assertEquals(null, Incoming.check(app, "Contact name", text, "sms", 2L))
    }

    @Test fun aRealMessageIsNeverSentToTheOnlineCopyAndIsNotLost() {
        store.serverUrl = Store.ONLINE_SERVER
        try {
            val item = Incoming.check(app, "Someone", "${System.nanoTime()} $scamChat", "sms", 1L)
            assertEquals(null, item?.level)
            assertTrue(item?.error.orEmpty().contains("Not checked"))
            assertEquals(item?.text, store.recent().first().text)
            assertEquals(0, Retry.unchecked(app))
        } finally { store.serverUrl = Store.USB_SERVER }
    }

    @Test fun aWhatsAppScamIsCheckedAsASocialMessage() {
        val item = Incoming.check(app, "Unknown", "${System.nanoTime()} $scamChat", "social", 1L)
        assertEquals("social", item?.channel)
        assertTrue(item?.level in setOf("Medium", "High", "Critical"))
        assertEquals("social", store.recent().first().channel)
    }
}
