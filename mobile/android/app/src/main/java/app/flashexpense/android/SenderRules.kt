package app.flashexpense.android

/**
 * Which SMS may leave the phone (D-123): a bank sender, not promotional, not an OTP, at most
 * 2 KB. The same rules as the server (backend/app/engine/senders.py, filters.py); the tests
 * run them on the server's own fixtures (sender_ids.json, otp_cases.json) and read the one
 * sender list, backend/app/engine/shared/bank_senders.json, which is packed into the APK.
 * Pure Kotlin: no Android classes, so it runs in JVM unit tests.
 */
object SenderRules {
    private val TRAI_SUFFIXES = setOf("S", "T", "P", "G")

    private fun String.alnum() = isNotEmpty() && all { it.isLetterOrDigit() }
    private fun String.digits() = isNotEmpty() && all { it.isDigit() }
    private fun String.alpha() = isNotEmpty() && all { it.isLetter() }

    /** Sender ID -> (core, TRAI suffix), exactly as senders.parse_sender. */
    fun parseSender(address: String): Pair<String, String> {
        val sid = address.uppercase().replace(" ", "")
        if ('-' in sid && sid.replace("-", "").alnum()) {
            var parts = sid.split("-").filter { it.isNotEmpty() }
            var suffix = ""
            if (parts.size > 1 && parts.last() in TRAI_SUFFIXES) {
                suffix = parts.last()
                parts = parts.dropLast(1)
            }
            if (parts.size > 1 && parts[0].length == 2 && parts[0].alpha()) parts = parts.drop(1)
            return parts.joinToString("") to suffix
        }
        val head = sid.take(2)
        if (sid.drop(2).digits() && (head.alpha() || head.digits())) {
            return (if (head.alpha()) sid.drop(2) else sid) to ""
        }
        if (!sid.alnum()) return sid to ""
        if (sid.length == 9 && head.alpha() && sid.takeLast(1) in TRAI_SUFFIXES) {
            return sid.substring(2, 8) to sid.takeLast(1)
        }
        if (sid.length == 8 && head.alpha()) return sid.drop(2) to ""
        if (sid.length == 7 && sid.takeLast(1) in TRAI_SUFFIXES) return sid.dropLast(1) to sid.takeLast(1)
        return sid to ""
    }

    // filters.py: "never share your OTP" warnings inside real alerts are removed first.
    private val OTP_WARNING = Regex(
        "(?:(?:never|do\\s*not|don'?t|not\\s+to)\\s+share|never\\s+asks?\\s+for)\\s+" +
            "(?:your\\s+|the\\s+|this\\s+)?(?:otp|one[\\s-]?time[\\s-]?password|pin|cvv)",
        RegexOption.IGNORE_CASE,
    )
    private val OTP = Regex(
        "\\b(?:otp|one[\\s-]?time[\\s-]?password|verification\\s+code)\\b",
        RegexOption.IGNORE_CASE,
    )

    fun isOtp(body: String): Boolean = OTP.containsMatchIn(OTP_WARNING.replace(body, ""))
}

const val MAX_BODY_BYTES = 2048

/** The shared sender list: core -> bank, and the registered senders that are not banks. */
class BankSenders(private val banks: Map<String, String>, private val notBanks: Set<String>) {
    /** Sender cores of banks, for the inbox query (address LIKE '%core%'). */
    val cores: List<String> = banks.filterValues { it !in notBanks }.keys.sorted()

    fun bankOf(address: String): String? {
        val core = SenderRules.parseSender(address).first
        if (core.isEmpty() || !core.all { it.isLetterOrDigit() }) return null
        return banks[core]?.takeIf { it !in notBanks }
    }

    /** May this message leave the phone? Only a bank's, never promotional or an OTP. */
    fun accepts(address: String, body: String): Boolean =
        bankOf(address) != null &&
            SenderRules.parseSender(address).second != "P" &&
            !SenderRules.isOtp(body) &&
            body.isNotEmpty() && body.toByteArray(Charsets.UTF_8).size <= MAX_BODY_BYTES

    companion object {
        private val PAIR = Regex("\"([A-Z0-9]+)\"\\s*:\\s*\"([A-Z_]+)\"")
        private val ITEM = Regex("\"([A-Z_]+)\"")

        /** Reads bank_senders.json: a flat "senders" object and a "not_banks" list. */
        fun parse(json: String): BankSenders {
            val senders = json.substringAfter("\"senders\"").substringAfter('{').substringBefore('}')
            val notBanks = json.substringAfter("\"not_banks\"").substringAfter('[').substringBefore(']')
            return BankSenders(
                PAIR.findAll(senders).associate { it.groupValues[1] to it.groupValues[2] },
                ITEM.findAll(notBanks).map { it.groupValues[1] }.toSet(),
            )
        }
    }
}
