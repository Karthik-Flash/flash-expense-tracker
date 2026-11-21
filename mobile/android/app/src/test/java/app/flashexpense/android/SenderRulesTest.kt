package app.flashexpense.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phone's filter equals the server's: the same fixtures, the same sender list (D-123). */
class SenderRulesTest {
    private val senders = BankSenders.parse(Fixtures.text("backend/app/engine/shared/bank_senders.json"))

    @Test
    fun senderIdsAsTheServerNormalisesThem() {
        val cases = Fixtures.objects("backend/tests/fixtures/sender_ids.json")
        assertEquals(19, cases.size)
        for (case in cases) {
            val address = case["address"] as String
            assertEquals(address, case["core"] to case["suffix"], SenderRules.parseSender(address))
        }
    }

    @Test
    fun otpAsTheServerFindsIt() {
        val cases = Fixtures.objects("backend/tests/fixtures/otp_cases.json")
        assertEquals(10, cases.size)
        for (case in cases) assertEquals(case["body"] as String, case["otp"], SenderRules.isOtp(case["body"] as String))
    }

    @Test
    fun theSharedListOfBanks() {
        assertEquals("HDFC", senders.bankOf("VM-HDFCBK-S"))
        assertEquals("SBI", senders.bankOf("JD-SBIUPI-T"))
        assertEquals(null, senders.bankOf("VM-PHONPE-S")) // a payments app, not a bank
        assertEquals(null, senders.bankOf("+919000000001"))
        assertEquals(null, senders.bankOf("ABC123@RBM.GOOG"))
        assertTrue("HDFCBK" in senders.cores && "PHONPE" !in senders.cores)
        assertEquals(13, senders.cores.size) // 14 registered senders, one of them an app
    }

    @Test
    fun onlyBankMessagesLeaveThePhone() {
        val alert = "Sent Rs.33.00\nFrom HDFC Bank A/C *0001\nTo TEST\nOn 05/01/26\nRef 000000000001"
        assertTrue(senders.accepts("VM-HDFCBK-S", alert))
        assertFalse(senders.accepts("AB-TESTCO-S", alert)) // not a bank
        assertFalse(senders.accepts("VM-HDFCBK-P", alert)) // promotional
        assertFalse(senders.accepts("VM-HDFCBK-S", "123456 is your OTP for txn of Rs 33 at TEST"))
        assertTrue(senders.accepts("VM-HDFCBK-S", "Rs 500 debited from A/c XX1234. Never share your OTP with anyone."))
        assertFalse(senders.accepts("VM-HDFCBK-S", "x".repeat(MAX_BODY_BYTES + 1)))
        assertFalse(senders.accepts("VM-HDFCBK-S", "₹".repeat(700))) // 700 characters, 2100 bytes
        assertTrue(senders.accepts("VM-HDFCBK-S", "x".repeat(MAX_BODY_BYTES)))
        assertFalse(senders.accepts("VM-HDFCBK-S", ""))
    }
}
