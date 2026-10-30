package ai.satark.smsguard

import java.net.URLDecoder

/** What a scanned QR code turned out to be. */
sealed class Scanned {
    /** A UPI payment. Everything in it was typed by whoever made the QR, so none of it is proof of anything. */
    data class Upi(val payee: String, val name: String?, val amount: Double?, val note: String?) : Scanned()
    data class Link(val url: String) : Scanned()
    data class Other(val text: String) : Scanned()
}

/** Reads the text inside a QR code. Plain Kotlin, so it can be tested without a phone. */
object UpiQr {
    // The same check as the server's, so that a bad ID gets a clear message here.
    private val VPA = Regex("^[\\w.\\-]{1,100}@[A-Za-z0-9.\\-]{1,30}$")
    private const val MAX_AMOUNT = 10_000_000.0
    private const val MAX_NOTE = 200
    private const val MAX_NAME = 100

    fun isUpiId(text: String) = VPA.matches(text.trim())

    fun parse(raw: String): Scanned {
        val text = raw.trim()
        val lower = text.lowercase()
        if (lower.startsWith("upi://")) return parseUpi(text) ?: Scanned.Other(text)
        if (lower.startsWith("http://") || lower.startsWith("https://")) return Scanned.Link(text)
        return Scanned.Other(text)
    }

    private fun parseUpi(text: String): Scanned.Upi? {
        val query = text.substringAfter('?', "")
        val params = HashMap<String, String>()
        for (part in query.split('&')) {
            val key = part.substringBefore('=').lowercase()
            val value = part.substringAfter('=', "")
            if (key.isNotEmpty() && key !in params) params[key] = decode(value)     // the first one counts, as a payment app would read it
        }
        val payee = params["pa"]?.trim()?.lowercase()?.takeIf { isUpiId(it) } ?: return null
        val amount = params["am"]?.toDoubleOrNull()?.takeIf { it > 0 && it <= MAX_AMOUNT }
        return Scanned.Upi(payee, params["pn"]?.trim()?.take(MAX_NAME)?.ifEmpty { null }, amount, params["tn"]?.trim()?.take(MAX_NOTE)?.ifEmpty { null })
    }

    private fun decode(value: String): String =
        try { URLDecoder.decode(value, "UTF-8") } catch (e: IllegalArgumentException) { value }
}
