package app.flashexpense.android

import java.io.File

/** The repository's shared files (the Gradle test task passes -Dflash.repo). */
object Fixtures {
    private val repo = File(System.getProperty("flash.repo") ?: "../../..")

    fun text(path: String): String = File(repo, path).readText(Charsets.UTF_8)

    /** A JSON array of flat objects of strings and booleans (the server's test fixtures). */
    fun objects(path: String): List<Map<String, Any>> {
        val field = Regex("\"(\\w+)\"\\s*:\\s*(\"((?:[^\"\\\\]|\\\\.)*)\"|true|false)")
        return Regex("\\{[^{}]*\\}").findAll(text(path)).map { obj ->
            field.findAll(obj.value).associate { m ->
                val value: Any = when (m.groupValues[2]) {
                    "true" -> true
                    "false" -> false
                    else -> unescape(m.groupValues[3])
                }
                m.groupValues[1] to value
            }
        }.toList()
    }

    private fun unescape(s: String): String =
        s.replace("\\n", "\n").replace("\\\"", "\"").replace("\\\\", "\\")
}
