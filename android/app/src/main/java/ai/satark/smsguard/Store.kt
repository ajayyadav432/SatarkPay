package ai.satark.smsguard

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Settings and the list of recently checked SMS, kept on the phone. */
class Store(context: Context) {
    private val prefs = context.getSharedPreferences("satark", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString("server", DEFAULT_SERVER) ?: DEFAULT_SERVER
        set(v) = prefs.edit().putString("server", v.trim().trimEnd('/')).apply()

    var language: String
        get() = prefs.getString("language", "en") ?: "en"
        set(v) = prefs.edit().putString("language", v).apply()

    var theme: String
        get() = prefs.getString("theme", "system") ?: "system"
        set(v) = prefs.edit().putString("theme", v).apply()

    var pairingCode: String
        get() = prefs.getString("code", "") ?: ""
        set(v) = prefs.edit().putString("code", v.trim()).apply()

    val sessionToken: String? get() = prefs.getString("session_token", null)
    val sessionRole: String? get() = prefs.getString("session_role", null)
    val sessionName: String get() = prefs.getString("session_name", "") ?: ""

    fun saveSession(token: String, role: String, name: String) =
        prefs.edit().putString("session_token", token).putString("session_role", role).putString("session_name", name).apply()

    fun clearSession() = prefs.edit().remove("session_token").remove("session_role").remove("session_name").apply()

    fun recent(): List<Checked> {
        val arr = JSONArray(prefs.getString("recent", "[]"))
        return (0 until arr.length()).map { Checked.fromJson(arr.getJSONObject(it)) }
    }

    @Synchronized
    fun add(item: Checked) {
        val list = listOf(item) + recent().take(MAX_RECENT - 1)
        prefs.edit().putString("recent", JSONArray(list.map { it.toJson() }).toString()).apply()
    }

    fun clearRecent() = prefs.edit().putString("recent", "[]").apply()

    /** Replace one stored item (same time, sender and text) with an updated one. */
    @Synchronized
    fun replace(old: Checked, new: Checked) {
        val list = recent().map { if (it.time == old.time && it.sender == old.sender && it.text == old.text) new else it }
        prefs.edit().putString("recent", JSONArray(list.map { it.toJson() }).toString()).apply()
    }

    companion object {
        // The laptop over USB, with ./run.sh phone running. Over Wi-Fi use the laptop's address. On the emulator use http://10.0.2.2:8000.
        const val ONLINE_SERVER = "https://satarkpay.vercel.app"
        const val USB_SERVER = "http://127.0.0.1:8000"
        const val DEFAULT_SERVER = ONLINE_SERVER
        const val MAX_RECENT = 30
    }
}

/** One checked SMS. level is null when SatarkPay could not be reached.
 *  ownLevel / ownScore: the message's own result, set only when the sender's earlier messages raised the score. */
data class Checked(
    val time: Long, val sender: String, val text: String,
    val level: String?, val score: Int?, val category: String?, val reason: String?, val error: String?,
    val ownLevel: String? = null, val ownScore: Int? = null,
) {
    fun toJson(): JSONObject = JSONObject().put("time", time).put("sender", sender).put("text", text)
        .put("level", level).put("score", score).put("category", category).put("reason", reason).put("error", error)
        .put("ownLevel", ownLevel).put("ownScore", ownScore)

    companion object {
        fun fromJson(o: JSONObject) = Checked(
            o.optLong("time"), o.optString("sender"), o.optString("text"),
            o.optString("level").ifEmpty { null }, if (o.has("score") && !o.isNull("score")) o.getInt("score") else null,
            o.optString("category").ifEmpty { null }, o.optString("reason").ifEmpty { null }, o.optString("error").ifEmpty { null },
            o.optString("ownLevel").ifEmpty { null }, if (o.has("ownScore") && !o.isNull("ownScore")) o.getInt("ownScore") else null,
        )

        /** From the server's answer to /api/ingest. */
        fun fromResponse(sender: String, text: String, r: JSONObject): Checked {
            val reasons = r.optJSONArray("reasons")
            val raised = r.optBoolean("history_raised")
            return Checked(System.currentTimeMillis(), sender, text, r.optString("level"), r.optInt("score"),
                r.optString("category"), if (reasons != null && reasons.length() > 0) reasons.getString(0) else null, null,
                if (raised) r.optString("own_level") else null, if (raised) r.optInt("own_score") else null)
        }
    }
}
