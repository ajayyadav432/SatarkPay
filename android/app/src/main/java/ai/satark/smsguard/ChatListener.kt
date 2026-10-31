package ai.satark.smsguard

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat

/**
 * RCS chats and WhatsApp never reach SmsReceiver, because Android has no broadcast for them. With the person's
 * permission this reads their notifications. Every other app's notifications are ignored without being opened.
 */
class ChatListener : NotificationListenerService() {
    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val channel = APPS[sbn.packageName] ?: return
        val (sender, text) = read(sbn.notification) ?: return
        val context = applicationContext
        Thread { Incoming.check(context, sender, text, channel, sbn.postTime) }.start()
    }

    companion object {
        /** The only apps read, and the channel the server is told. */
        val APPS = mapOf(
            "com.google.android.apps.messaging" to "sms",
            "com.samsung.android.messaging" to "sms",
            "com.whatsapp" to "social",
            "com.whatsapp.w4b" to "social",
        )
        private val NOT_A_MESSAGE = Regex("""^\d+ (new )?messages?\b.*|^checking for new messages.*""", RegexOption.IGNORE_CASE)

        /** The sender and text of the newest message, or null when this is not a message from someone else. */
        fun read(n: Notification): Pair<String, String>? {
            if (n.flags and (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT) != 0) return null
            val title = n.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
            val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(n)
            val found = if (style != null) {
                val last = style.messages.lastOrNull() ?: return null
                val person = last.person ?: return null   // no person: the phone's owner sent it
                (person.name?.toString() ?: title) to last.text?.toString().orEmpty()
            } else {
                title to (n.extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: n.extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
            }
            if (found.second.isBlank() || NOT_A_MESSAGE.matches(found.second.trim())) return null
            return found.first.ifBlank { "Unknown sender" } to found.second
        }
    }
}
