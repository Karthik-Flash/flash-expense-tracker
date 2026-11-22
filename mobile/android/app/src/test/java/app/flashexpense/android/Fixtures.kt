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

    /** JSON string escapes: \n \t \r \" \\ and \uXXXX (5B-2: body_normalise.json). */
    private fun unescape(s: String): String {
        val out = StringBuilder()
        var i = 0
        while (i < s.length) {
            val c = s[i]
            if (c != '\\' || i + 1 >= s.length) {
                out.append(c)
                i++
                continue
            }
            when (val e = s[i + 1]) {
                'n' -> out.append('\n')
                't' -> out.append('\t')
                'r' -> out.append('\r')
                'u' -> {
                    out.append(s.substring(i + 2, i + 6).toInt(16).toChar())
                    i += 4
                }
                else -> out.append(e)
            }
            i += 2
        }
        return out.toString()
    }
}
