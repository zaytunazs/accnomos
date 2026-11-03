package com.accnomos.accnomos_mobile

import android.app.Activity
import android.content.Intent
import android.provider.OpenableColumns
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel

/**
 * `accnomos/files`: the system document picker (ACTION_OPEN_DOCUMENT) for one file, read once into memory and handed
 * to Dart as `{name, bytes}`. Used for bank statement CSVs and the invoice logo. The picker grants a one-time read of
 * the chosen document only, so the app needs no storage permission. Files over [MAX_BYTES] are refused.
 */
class FilePickerBridge(private val activity: Activity) {
    companion object {
        const val CHANNEL = "accnomos/files"
        const val PICK_FILE = 4712
        const val MAX_BYTES = 6 * 1024 * 1024
    }

    private var pending: MethodChannel.Result? = null

    fun register(messenger: BinaryMessenger) {
        MethodChannel(messenger, CHANNEL).setMethodCallHandler { call, result ->
            if (call.method != "pickFile") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            if (pending != null) {
                result.error("BUSY", "A file picker is already open.", null)
                return@setMethodCallHandler
            }
            @Suppress("UNCHECKED_CAST")
            val types = (call.argument<List<String>>("mimeTypes") ?: listOf("*/*")).toTypedArray()
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = if (types.size == 1) types[0] else "*/*"
                if (types.size > 1) putExtra(Intent.EXTRA_MIME_TYPES, types)
            }
            pending = result
            try {
                @Suppress("DEPRECATION")
                activity.startActivityForResult(intent, PICK_FILE)
            } catch (_: Exception) {
                pending = null
                result.error("NO_PICKER", "This phone has no file picker.", null)
            }
        }
    }

    /** True when the result was ours (consumed). */
    fun onResult(requestCode: Int, resultCode: Int, data: Intent?): Boolean {
        if (requestCode != PICK_FILE) return false
        val result = pending ?: return true
        pending = null
        val uri = data?.data
        if (resultCode != Activity.RESULT_OK || uri == null) {
            result.success(null)
            return true
        }
        try {
            var name = "statement.csv"
            activity.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0)?.takeIf { it.isNotBlank() }?.let { name = it }
            }
            val bytes = activity.contentResolver.openInputStream(uri)?.use { input ->
                val buffer = java.io.ByteArrayOutputStream()
                val chunk = ByteArray(64 * 1024)
                var total = 0
                while (true) {
                    val n = input.read(chunk)
                    if (n < 0) break
                    total += n
                    if (total > MAX_BYTES) throw IllegalStateException("too big")
                    buffer.write(chunk, 0, n)
                }
                buffer.toByteArray()
            }
            if (bytes == null) {
                result.error("READ_FAILED", "Could not read that file.", null)
            } else {
                result.success(mapOf("name" to name, "bytes" to bytes))
            }
        } catch (e: IllegalStateException) {
            result.error("TOO_BIG", "That file is over 6 MB.", null)
        } catch (_: Exception) {
            result.error("READ_FAILED", "Could not read that file.", null)
        }
        return true
    }
}
