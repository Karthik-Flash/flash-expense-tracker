package app.flashexpense.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 5B-2 (D-139, D-142): what is retried or dropped, who is notified and how, the cursor's
 *  pages, and the body rule both copies of an SMS share with the server. Pure, FAKE values. */
class PhoneLogicTest {
    private val now = 1_773_122_400_000L
    private fun row(id: String, ms: Long = now, origin: String = "inbox", notify: Boolean = true) =
        InboxRow(id, "VM-HDFCBK-S", "Sent Rs.1", ms, origin, notify)

    @Test
    fun aMessageIsDroppedOnlyWhenTheServerRefusedIt() {
        assertEquals(Wire.Next.CLEAR, Wire.next(Wire.outcome(200, null), 500)) // final answers
        assertEquals(Wire.Next.SPLIT, Wire.next(Wire.outcome(422, null), 500)) // find the one
        assertEquals(Wire.Next.DROP_ONE, Wire.next(Wire.outcome(422, null), 1))
        assertEquals(Wire.Next.DROP_ONE, Wire.next(Wire.outcome(413, null), 1))
        for (status in listOf(0, 500, 502, 503, 408, 429, 404, 400)) {
            assertEquals("$status", Wire.Next.RETRY, Wire.next(Wire.outcome(status, null), 1)) // kept
        }
        // 401 and 403: the queue stays for Reconnect ("Phone disconnected").
        assertEquals(Wire.Next.STOP, Wire.next(Wire.outcome(401, "device_revoked"), 9))
        assertEquals(Wire.Next.STOP, Wire.next(Wire.outcome(403, null), 9))
    }

    @Test
    fun whatTheServerWouldRefuseIsNeverQueued() {
        assertTrue(Wire.sendable("VM-HDFCBK-S", "Sent Rs.1"))
        assertFalse(Wire.sendable("VM-HDFCBK-S", "x".repeat(2049)))
        assertTrue(Wire.sendable("VM-HDFCBK-S", "₹".repeat(682))) // 2046 bytes in UTF-8
        assertFalse(Wire.sendable("VM-HDFCBK-S", "₹".repeat(683)))
        assertFalse(Wire.sendable("", "Sent Rs.1"))
        assertFalse(Wire.sendable("V".repeat(65), "Sent Rs.1"))
    }

    @Test
    fun onlyALiveSmsOrARecentInboxRowNotifies() {
        assertTrue(Wire.mayNotify(row("live-1", now - 9 * 3_600_000L, origin = "live"), now))
        assertTrue(Wire.mayNotify(row("1", now - 2 * 3_600_000L), now)) // 2 h: still recent
        assertFalse(Wire.mayNotify(row("2", now - 2 * 3_600_000L - 1), now))
        assertFalse(Wire.mayNotify(row("3", notify = false), now)) // read in a history scan
    }

    private fun payment(direction: String, amount: Long, name: String? = "Test Cafe", cat: String? = "Food & Drinks", ask: Boolean = false) =
        NewPayment("1", 7, direction, amount, name, cat, "spend", ask)

    @Test
    fun theNotificationText() {
        assertEquals("Paid ₹1,234 to Test Cafe · Food & Drinks", Wire.notificationText(payment("debit", 123_400)))
        assertEquals("Paid ₹1,23,456.50 to Test Cafe · Food & Drinks", Wire.notificationText(payment("debit", 12_345_650)))
        assertEquals("Paid ₹1", Wire.notificationText(payment("debit", 100, name = null, cat = null)))
        assertEquals("Received ₹500 from Test Friend", Wire.notificationText(payment("credit", 50_000, "Test Friend")))
        assertEquals("Received ₹500 from Test Friend · Paid back?", Wire.notificationText(payment("credit", 50_000, "Test Friend", ask = true)))
        assertEquals("₹0.05", Wire.rupees(5))
        assertEquals("₹10,00,000", Wire.rupees(100_000_000))
        assertEquals("₹999", Wire.rupees(99_900))
    }

    @Test
    fun theAnswersNewPayments() {
        val answer = "{\"results\":[],\"counts\":{\"stored\":1},\"new_transactions\":[{\"device_msg_id\":\"live-3\"," +
            "\"id\":42,\"direction\":\"debit\",\"amount_paise\":3300,\"display_name\":\"Test \\\"Kiosk\\\" \\u20b9\"," +
            "\"category\":\"uncategorised\",\"category_name\":\"Uncategorised\",\"role\":\"spend\",\"paid_back_question\":false}," +
            "{\"device_msg_id\":\"9\",\"id\":43,\"direction\":\"credit\",\"amount_paise\":500,\"display_name\":null," +
            "\"category\":null,\"category_name\":null,\"role\":null,\"paid_back_question\":true}]}"
        val made = Wire.newPayments(answer)
        assertEquals(2, made.size)
        assertEquals(NewPayment("live-3", 42, "debit", 3300, "Test \"Kiosk\" ₹", "Uncategorised", "spend", false, "uncategorised"), made[0])
        assertEquals(null, made[1].name)
        assertTrue(made[1].paidBackQuestion)
        assertEquals(emptyList<NewPayment>(), Wire.newPayments("{\"results\":[]}")) // a server before 5B-2
        assertEquals(emptyList<NewPayment>(), Wire.newPayments("not json"))
        assertEquals(emptyList<NewPayment>(), Wire.newPayments(null))
    }

    @Test
    fun theCursorPageNeverSplitsOneMillisecond() {
        val rows = (1..6).map { row("$it", now + (if (it <= 4) 0 else it)) } // four in one ms
        val first = Wire.page(rows.asSequence(), limit = 2)
        assertEquals(listOf("1", "2", "3", "4"), first.map { it.msgId }) // the cursor moves past all four
        assertEquals(now, first.last().receivedMs)
        assertEquals(now - Wire.OVERLAP_MS, Wire.scanFrom(now))
    }

    @Test
    fun bothCopiesOfAnSmsNormaliseAsTheServerDoes() {
        val cases = Fixtures.objects("backend/tests/fixtures/body_normalise.json")
        assertTrue(cases.size >= 6)
        for (case in cases) assertEquals(case["name"] as String, case["out"], Wire.normalBody(case["in"] as String))
    }

    @Test
    fun aNotificationCarriesThePaymentsBasics() {
        val p = NewPayment("1", 42, "debit", 3300, "Test \"Kiosk\"", "Food & Drinks", "spend", false, "food_drinks", "2026-11-20T06:00:00Z")
        val item = MiniJson.parse(Wire.openItem(p)!!) as Map<*, *>
        assertEquals(42L, (item["id"] as Number).toLong())
        assertEquals("Test \"Kiosk\"", item["display_name"])
        assertEquals("food_drinks", item["category"])
        assertEquals("2026-11-20T06:00:00Z", item["time_utc"])
        assertEquals(3300L, (item["amount_paise"] as Number).toLong())
        // An older server sends no time: no item, the sheet waits for the download as before.
        assertEquals(null, Wire.openItem(p.copy(timeUtc = null)))
        val bare = MiniJson.parse(Wire.openItem(p.copy(name = null, category = null, categoryName = null, role = null, direction = "credit"))!!) as Map<*, *>
        assertEquals(null, bare["display_name"])
        assertEquals("uncategorised", bare["category"])
        assertEquals("uncertain", bare["role"])
    }
}
