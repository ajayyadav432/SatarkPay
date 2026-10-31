package ai.satark.smsguard

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony

/**
 * Called by Android for every incoming SMS. The text is sent to SatarkPay on the laptop and the
 * verdict is shown as a notification. Nothing is sent anywhere else. See [Incoming].
 */
class SmsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return
        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        // A long SMS arrives in several parts; join them per sender.
        val bySender = parts.filterNotNull().groupBy { it.displayOriginatingAddress ?: "unknown" }
        val pending = goAsync()   // keep the receiver alive while the network call runs
        Thread {
            try {
                var answered = false
                for ((sender, msgs) in bySender) {
                    val text = msgs.joinToString("") { it.displayMessageBody ?: "" }
                    val item = Incoming.check(context, sender, text, "sms", msgs.first().timestampMillis)
                    if (item?.level != null) answered = true
                }
                // The laptop answered, so also send any SMS that could not be checked earlier.
                if (answered) Retry.unchecked(context)
            } finally {
                pending.finish()
            }
        }.start()
    }

    companion object {
        const val TAG = "SatarkSms"
        const val ACTION_UPDATED = "ai.satark.smsguard.UPDATED"
    }
}
