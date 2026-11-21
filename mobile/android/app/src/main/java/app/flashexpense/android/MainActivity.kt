package app.flashexpense.android

import android.os.Bundle
import com.getcapacitor.BridgeActivity

/** The Capacitor shell: the bundled web app, and the bank SMS plugin. */
class MainActivity : BridgeActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        registerPlugin(FlashSmsPlugin::class.java)
        super.onCreate(savedInstanceState)
    }
}
