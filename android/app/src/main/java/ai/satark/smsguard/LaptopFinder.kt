package ai.satark.smsguard

import android.content.Context
import java.net.Inet4Address
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.URL
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.concurrent.Callable
import java.util.concurrent.ExecutorCompletionService
import java.util.concurrent.Executors
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * The laptop's address changes with every Wi-Fi or hotspot, so the phone looks for it on its own network.
 * Real messages go to whoever answers, so an answer only counts if it proves it knows the pairing code.
 */
object LaptopFinder {
    private const val PORT = 8000
    private const val PROBE_MS = 500
    private val MOBILE_DATA = listOf("rmnet", "ccmni", "v4-", "dummy", "tun", "ppp")

    /** The other addresses on this phone's Wi-Fi or hotspot. Mobile data is never scanned. */
    fun neighbours(): List<String> {
        val out = linkedSetOf<String>()
        for (nic in NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()) {
            if (!nic.isUp || nic.isLoopback || MOBILE_DATA.any { nic.name.startsWith(it) }) continue
            for (a in nic.inetAddresses.toList().filterIsInstance<Inet4Address>().filter { it.isSiteLocalAddress }) {
                val own = a.hostAddress ?: continue
                val prefix = own.substringBeforeLast('.')
                (1..254).map { "$prefix.$it" }.filterTo(out) { it != own }
            }
        }
        return out.toList()
    }

    /** The server signs a fresh number and the address the phone used, so a device in the middle cannot pass on its answer. */
    fun proves(base: String, code: String): Boolean = runCatching {
        val nonce = ByteArray(16).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val mac = Mac.getInstance("HmacSHA256").apply { init(SecretKeySpec(code.toByteArray(), "HmacSHA256")) }
        val want = mac.doFinal("$nonce:${URL(base).host}".toByteArray()).joinToString("") { "%02x".format(it) }
        MessageDigest.isEqual(want.toByteArray(), SatarkClient.laptopProof(base, nonce).toByteArray())
    }.getOrDefault(false)

    private fun answers(ip: String) = runCatching {
        Socket().use { it.connect(InetSocketAddress(ip, PORT), PROBE_MS) }
        true
    }.getOrDefault(false)

    /** The laptop's address, or null. Takes a few seconds, so it runs on a background thread. */
    fun find(code: String): String? {
        if (code.isBlank()) return null
        val hosts = neighbours()
        if (hosts.isEmpty()) return null
        val pool = Executors.newFixedThreadPool(48)
        try {
            val done = ExecutorCompletionService<String?>(pool)
            hosts.forEach { ip -> done.submit(Callable { "http://$ip:$PORT".takeIf { answers(ip) && proves(it, code) } }) }
            repeat(hosts.size) { done.take().get()?.let { return it } }
            return null
        } finally {
            pool.shutdownNow()
        }
    }

    /** After a failed connection: looks for the laptop and saves its address. Never used in online mode. */
    @Synchronized
    fun reconnect(context: Context): Boolean {
        val store = Store(context)
        if (store.serverUrl.startsWith("https://")) return false
        val found = find(store.pairingCode) ?: return false
        store.serverUrl = found
        return true
    }
}
