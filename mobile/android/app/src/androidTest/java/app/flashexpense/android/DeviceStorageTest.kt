package app.flashexpense.android

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * On a phone or emulator only (`gradlew connectedDebugAndroidTest`): the SQLite queue and the
 * Keystore-sealed token. The JVM tests cover the logic; these cover the platform parts.
 */
@RunWith(AndroidJUnit4::class)
class DeviceStorageTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Before
    fun clean() {
        SmsQueue(context).clear()
        Store(context).wipe()
    }

    @Test
    fun theQueueKeepsOneRowPerInboxIdUntilTheServerAnswers() {
        val queue = SmsQueue(context)
        val a = InboxRow("1", "VM-HDFCBK-S", "Sent Rs.1", 2_000L)
        val b = InboxRow("2", "VM-HDFCBK-S", "Sent Rs.2", 1_000L)
        queue.addReady(listOf(a, b))
        queue.addReady(listOf(a)) // the next scan sees it again: still one row
        assertEquals(2 to 0, queue.counts())
        assertEquals(listOf(b, a), queue.nextBatch()) // oldest first
        queue.remove(listOf(b))
        assertEquals(listOf(a), queue.nextBatch())
        queue.addAwaiting("VM-HDFCBK-S", "Sent Rs.3", 3_000L)
        val waiting = queue.awaiting()
        assertEquals(1, waiting.size)
        queue.dropAwaiting(waiting.map { it.id })
        queue.clear()
        assertEquals(0 to 0, queue.counts())
    }

    @Test
    fun theTokenIsSealedAndWipedOnSignOut() {
        val store = Store(context)
        val id = store.deviceId
        store.saveToken("TEST-TOKEN-0123456789", "https://api.example.invalid", "test-user")
        assertEquals("TEST-TOKEN-0123456789", store.token())
        assertTrue(store.connected)
        val raw = context.getSharedPreferences("flash", 0).getString("token_sealed", "")!!
        assertTrue("TEST-TOKEN" !in raw)
        store.wipe()
        assertNull(store.token())
        assertEquals(id, store.deviceId) // the same phone connects again under its id
    }
}
