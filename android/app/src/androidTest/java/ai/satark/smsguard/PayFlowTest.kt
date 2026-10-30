package ai.satark.smsguard

import android.graphics.Bitmap
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
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
        rule.waitForIdle()
        val bitmap = instrumentation.uiAutomation.takeScreenshot() ?: return
        File(app.getExternalFilesDir(null), "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    /** The picture, the review screen and the result, as a person meets them. */
    private fun scanAndCheck(picture: String) {
        val qr = UpiQr.parse(readAsset(picture)!!) as Scanned.Upi
        rule.setContent {
            var check by remember { mutableStateOf<PayCheck?>(null) }
            val c = check
            if (c == null) ReviewScreen(qr, store, {}) { check = it } else ResultScreen(c, store) {}
        }
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
        rule.onNodeWithText("Report this scam").performScrollTo().assertExists()
        rule.onAllNodesWithText("Simulate payment").assertCountEquals(0)
        rule.onNodeWithText("Pay anyway (wait", substring = true).performScrollTo().assertIsNotEnabled()
        screenshot("result_scam")
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
        rule.onNodeWithText("No warning signs found").assertExists()
        rule.onNodeWithText("This is a real UPI ID", substring = true).performScrollTo().assertExists()
        rule.onAllNodesWithText("Simulate payment").assertCountEquals(0)
        rule.onAllNodesWithText("1 day old", substring = true).assertCountEquals(0)
        screenshot("result_real")
    }

    @Test fun aLinkQrIsCheckedAsAPage() {
        val url = (UpiQr.parse(readAsset("satarkpay_qr_link.png")!!) as Scanned.Link).url
        rule.setContent { LinkScreen(url, store) {} }
        rule.waitUntil(15000) { rule.onAllNodesWithText("Do not open or pay", substring = true).fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithText("State Bank of India", substring = true).assertExists()
        screenshot("result_link")
    }
}
