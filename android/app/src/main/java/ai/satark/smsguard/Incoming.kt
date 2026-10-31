package ai.satark.smsguard

import android.content.Context
import android.content.Intent
import android.util.Log
import kotlin.math.abs

/** One path for every incoming message, whether it came as an SMS or through a notification. */
object Incoming {
    private const val TAG = "SatarkIncoming"
    private const val SAME_WINDOW_MS = 10 * 60 * 1000L
    private const val NOT_SENT = "Not checked: connect to the laptop. Real messages are never sent to the online copy."
    private val claimed = mutableListOf<Pair<Long, String>>()   // being checked now, not yet in the store

    private fun clean(s: String) = s.trim().replace(Regex("""\s+"""), " ").lowercase()

    /** An SMS also shows as a notification, sometimes cut short and under a contact's name, so only the text is compared. */
    fun sameMessage(a: String, b: String): Boolean {
        val x = clean(a); val y = clean(b)
        val n = minOf(x.length, y.length, 100)
        return if (n < 20) x == y else x.take(n) == y.take(n)
    }

    private fun claim(store: Store, text: String, now: Long): Boolean = synchronized(claimed) {
        claimed.removeAll { now - it.first > SAME_WINDOW_MS }
        if (claimed.any { sameMessage(it.second, text) }) return false
        if (store.recent().any { abs(now - it.time) < SAME_WINDOW_MS && sameMessage(it.text, text) }) return false
        claimed.add(now to text)
        true
    }

    /** Runs on a background thread. Returns the result, or null when this message was already seen. */
    fun check(context: Context, sender: String, text: String, channel: String, time: Long): Checked? {
        if (text.isBlank()) return null
        val store = Store(context)
        val now = System.currentTimeMillis()
        if (!claim(store, text, now)) return null
        val item = if (store.serverUrl.startsWith("https://")) {
            // Real messages hold OTPs and bank details. They are only ever sent to the team's own laptop, never to a public server.
            Checked(now, sender, text, null, null, null, null, NOT_SENT, channel = channel)
        } else try {
            val r = SatarkClient.checkSms(store.serverUrl, store.pairingCode, sender, text, "$sender-$time-${text.hashCode()}", channel)
            Notifier.maybeBlock(context, r)
            Checked.fromResponse(sender, text, r, channel)
        } catch (e: Exception) {
            Log.w(TAG, "check failed", e)
            Checked(now, sender, text, null, null, null, null, e.message ?: e.javaClass.simpleName, channel = channel)
        }
        store.add(item)
        Notifier.show(context, item)
        context.sendBroadcast(Intent(SmsReceiver.ACTION_UPDATED).setPackage(context.packageName))
        return item
    }
}
