package ai.satark.smsguard

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Talks to the SatarkPay app on the laptop. Runs on a background thread, never on the UI thread. */
object SatarkClient {
    private const val TIMEOUT_MS = 8000

    /** The login ended, for example because the laptop's server restarted. */
    class LoginNeeded(message: String) : IllegalStateException(message)

    /** The session token. It goes only to the address the person set. */
    @Volatile var token: String? = null

    /** Checks the password on the laptop. Returns the role, name and session token. */
    fun login(server: String, role: String, username: String, password: String): JSONObject {
        val body = JSONObject().put("role", role).put("username", username).put("password", password)
        return request("$server/api/v1/auth/login", "POST", null, body.toString())
    }

    /** Creates a user or merchant account. Returns the same as login. */
    fun signUp(server: String, role: String, username: String, password: String, name: String): JSONObject {
        val body = JSONObject().put("role", role).put("username", username).put("password", password).put("name", name)
        return request("$server/api/v1/auth/signup", "POST", null, body.toString())
    }

    /** One tap into a portal's shared demo account, for judges. */
    fun testLogin(server: String, role: String): JSONObject =
        request("$server/api/v1/auth/test-login", "POST", null, JSONObject().put("role", role).toString())

    fun logout(server: String) { request("$server/api/v1/auth/logout", "POST", null, "{}") }

    /** Still logged in? Throws LoginNeeded if not. */
    fun me(server: String): JSONObject = request("$server/api/v1/auth/me", "GET", null, null)

    fun merchantPayments(server: String): JSONObject = request("$server/api/v1/merchant/payments", "GET", null, null)

    /** A simulated customer pays this shop, for the demo. */
    fun customerPays(server: String, shop: String) {
        val me = request("$server/api/v1/demo?persona=rahul", "GET", null, null).getJSONObject("me")
        val body = JSONObject().put("payer", me.getString("vpa")).put("payee", shop).put("amount", (40..500).random()).put("kind", "QR")
            .put("device", me.getString("device")).put("city", me.getInt("city")).put("balance", me.getDouble("balance")).put("record", true)
        request("$server/api/v1/score", "POST", null, body.toString())
    }

    fun kpis(server: String): JSONObject = request("$server/api/v1/kpis", "GET", null, null)

    fun alerts(server: String) = request("$server/api/v1/alerts?limit=30", "GET", null, null).getJSONArray("alerts")

    fun labelAlert(server: String, id: Int, status: String) {
        request("$server/api/v1/alerts/$id", "POST", null, JSONObject().put("status", status).toString())
    }

    fun attack(server: String, name: String) { request("$server/api/v1/sim/attack/$name", "POST", null, "{}") }

    fun simRun(server: String, start: Boolean) { request("$server/api/v1/sim/" + if (start) "start" else "stop", "POST", null, "{}") }

    /** Sends one SMS to /api/ingest and returns the engine's verdict. Throws on network or server errors. */
    fun checkSms(server: String, code: String, sender: String, text: String, ref: String): JSONObject {
        val body = JSONObject()
            .put("text", text.take(20000)).put("channel", "sms").put("sender", sender.take(320))
            .put("source", "sms-app").put("ref", ref.take(300))
        return request("$server/api/ingest", "POST", code, body.toString())
    }

    /** True when the laptop answers. Used by the "Test connection" button. */
    fun health(server: String): Boolean =
        request("$server/api/health", "GET", null, null).optString("status") == "ok"

    /** The simulated account that is paying, with its usual phone and city, so that it looks like its owner to the model. */
    private fun demoAccount(server: String): JSONObject = request("$server/api/v1/demo", "GET", null, null).getJSONObject("me")

    /** Scores one payment before it goes through. */
    fun scorePayment(server: String, payee: String, amount: Double, kind: String, note: String): JSONObject {
        val me = demoAccount(server)
        val body = JSONObject().put("payer", me.getString("vpa")).put("payee", payee).put("amount", amount).put("kind", kind)
            .put("device", me.getString("device")).put("city", me.getInt("city")).put("balance", me.getDouble("balance")).put("note", note)
        return request("$server/api/v1/score", "POST", null, body.toString())
    }

    /** What the person did after seeing the result. */
    fun outcome(server: String, txnId: String, token: String, decision: String): JSONObject {
        val body = JSONObject().put("txn_id", txnId).put("token", token).put("decision", decision)
        return request("$server/api/v1/outcome", "POST", null, body.toString())
    }

    /** Checks a web link. */
    fun checkUrl(server: String, url: String): JSONObject =
        request("$server/api/check-url?u=" + URLEncoder.encode(url, "UTF-8"), "GET", null, null)

    fun posts(server: String): JSONObject = request("$server/api/v1/posts?limit=50", "GET", null, null)

    fun addPost(server: String, payee: String, category: String, body: String) {
        request("$server/api/v1/posts", "POST", null, JSONObject().put("payee", payee).put("category", category).put("body", body).toString())
    }

    fun vote(server: String, id: Int, value: Int) {
        request("$server/api/v1/posts/$id/vote", "POST", null, JSONObject().put("value", value).toString())
    }

    fun comments(server: String, id: Int): JSONObject = request("$server/api/v1/posts/$id/comments", "GET", null, null)

    fun addComment(server: String, id: Int, body: String) {
        request("$server/api/v1/posts/$id/comments", "POST", null, JSONObject().put("body", body).toString())
    }

    fun history(server: String, q: String, kind: String = ""): JSONObject =
        request("$server/api/v1/history?limit=1000&q=" + URLEncoder.encode(q, "UTF-8") + "&kind=" + kind, "GET", null, null)

    fun clearHistory(server: String) { request("$server/api/v1/history", "DELETE", null, null) }

    /** The downloaded file as text: CSV, or a JSON list. */
    fun exportHistory(server: String, format: String, q: String): String =
        requestText("$server/api/v1/history/export.$format?q=" + URLEncoder.encode(q, "UTF-8"), "GET", null, null)

    private fun request(url: String, method: String, code: String?, body: String?): JSONObject = JSONObject(requestText(url, method, code, body))

    private fun requestText(url: String, method: String, code: String?, body: String?): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = method
            conn.connectTimeout = TIMEOUT_MS
            conn.readTimeout = TIMEOUT_MS
            if (code != null) conn.setRequestProperty("X-Satark-Token", code)
            token?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (status !in 200..299) {
                val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                if (status == 401 && detail == "Please log in.") throw LoginNeeded(detail)
                throw IllegalStateException(detail?.ifEmpty { null } ?: "SatarkPay answered $status")
            }
            return text
        } finally {
            conn.disconnect()
        }
    }
}
