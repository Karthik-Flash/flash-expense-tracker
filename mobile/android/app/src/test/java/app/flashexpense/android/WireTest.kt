package app.flashexpense.android

import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The queue's cursor and pages, the upload body, what an answer means, the token's seal. */
class WireTest {
    private fun row(id: Int, ms: Long) = InboxRow(id.toString(), "VM-HDFCBK-S", "Sent Rs.$id", ms)

    @Test
    fun theUploadBodyAsTheServerReadsIt() {
        val json = Wire.batchJson(listOf(InboxRow("42", "VM-HDFCBK-S", "Sent \"Rs.33\"\nTo TEST\\X\t\u0001", 1_773_122_400_123L)))
        assertEquals(
            "{\"messages\":[{\"sender\":\"VM-HDFCBK-S\",\"body\":\"Sent \\\"Rs.33\\\"\\nTo TEST\\\\X\\t\\u0001\"," +
                "\"received_at_utc\":\"2026-03-10T06:00:00.123Z\",\"device_msg_id\":\"42\"}]}",
            json,
        )
        assertEquals("\"₹ 33\"", Wire.quote("₹ 33")) // non-ASCII stays as it is (UTF-8)
    }

    @Test
    fun theInboxDateIsSentToTheMillisecond() {
        assertEquals("2026-03-10T06:00:00.123Z", Wire.isoUtc(1_773_122_400_123L))
        assertEquals("2026-03-10T06:00:00Z", Wire.isoUtc(1_773_122_400_000L))
    }

    @Test
    fun aRunRescansTenMinutesBeforeTheCursor() {
        assertEquals(1_000_000L - 600_000L, Wire.scanFrom(1_000_000L))
        assertEquals(0L, Wire.scanFrom(5_000L))
    }

    @Test
    fun pagesNeverSplitOneMillisecond() {
        val rows = (1..6).map { row(it, if (it in 3..5) 300L else it * 100L) }
        assertEquals(listOf("1", "2"), Wire.page(rows.asSequence(), limit = 2).map { it.msgId })
        // The limit falls inside three rows of the same date: the page takes all three.
        assertEquals(listOf("1", "2", "3", "4", "5"), Wire.page(rows.asSequence(), limit = 3).map { it.msgId })
        assertEquals(6, Wire.page(rows.asSequence(), limit = 500).size)
        assertTrue(Wire.page(emptySequence()).isEmpty())
        assertEquals(500, Wire.page((1..1200).map { row(it, it.toLong()) }.asSequence()).size)
    }

    @Test
    fun aLiveMessageWaitsADayForItsInboxRow() {
        assertFalse(Wire.expired(0L, Wire.AWAIT_MS))
        assertTrue(Wire.expired(0L, Wire.AWAIT_MS + 1))
    }

    @Test
    fun whatAnAnswerMeans() {
        assertEquals(Wire.Outcome.STORED, Wire.outcome(200, null))
        assertEquals(Wire.Outcome.REVOKED, Wire.outcome(401, "device_revoked"))
        assertEquals(Wire.Outcome.SIGNED_OUT, Wire.outcome(401, "invalid device token"))
        assertEquals(Wire.Outcome.SIGNED_OUT, Wire.outcome(403, null))
        assertEquals(Wire.Outcome.OFFLINE, Wire.outcome(0, null))
        for (status in listOf(500, 502, 503, 408, 429)) assertEquals(Wire.Outcome.SERVER, Wire.outcome(status, null))
        assertEquals(Wire.Outcome.REJECTED, Wire.outcome(422, null))
        assertEquals("revoked", Wire.Outcome.REVOKED.code)
    }

    @Test
    fun readsTheServersAnswer() {
        val answer = "{\"results\":[{\"device_msg_id\":\"1\",\"status\":\"stored\"}]," +
            "\"counts\":{\"duplicate\":3,\"refused_filtered\":0,\"refused_not_bank\":0,\"stored\":2}}"
        assertEquals(2, Wire.storedCount(answer))
        assertEquals(0, Wire.storedCount(null))
        assertEquals("device_revoked", Wire.detail("{\"detail\":\"device_revoked\"}"))
        assertEquals(null, Wire.detail("{\"detail\":[{\"loc\":[\"body\"]}]}"))
    }

    @Test
    fun theTokenSealOpensOnlyWithItsKey() {
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val token = "f".repeat(43).toByteArray()
        val one = Gcm.seal(key, token)
        val two = Gcm.seal(key, token)
        assertArrayEquals(token, Gcm.open(key, one))
        assertNotEquals(one.toList(), two.toList()) // a fresh IV every time
        assertFalse(String(one, Charsets.ISO_8859_1).contains("fffff"))
        val tampered = one.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 1).toByte() }
        assertThrowsBadTag { Gcm.open(key, tampered) }
        val other = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        assertThrowsBadTag { Gcm.open(other, one) }
    }

    private fun assertThrowsBadTag(block: () -> Unit) {
        try {
            block()
        } catch (e: AEADBadTagException) {
            return
        }
        throw AssertionError("expected AEADBadTagException")
    }
}
