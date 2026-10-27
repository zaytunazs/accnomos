package com.accnomos.accnomos_mobile

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    companion object {
        private const val CHANNEL = "accnomos/share"
    }

    /** Shared files staged into our cache dir, waiting for Dart to collect. */
    private val pending = mutableListOf<String>()

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "getSharedFiles") {
                    result.success(ArrayList(pending))
                    pending.clear()
                } else {
                    result.notImplemented()
                }
            }
        handleIntent(intent)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent == null) return
        when (intent.action) {
            Intent.ACTION_SEND -> {
                val uri = intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
                    ?: return
                stage(uri)?.let { pending.add(it) }
            }
            Intent.ACTION_SEND_MULTIPLE -> {
                val uris = intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)
                    ?: return
                for (uri in uris) {
                    stage(uri)?.let { pending.add(it) }
                }
            }
        }
    }

    /** Copies shared content into our own cache dir and returns the path. */
    private fun stage(uri: Uri): String? {
        return try {
            val dir = File(cacheDir, "accnomos_share").apply { mkdirs() }
            val name = uri.lastPathSegment
                ?.substringAfterLast('/')
                ?.takeIf { it.isNotBlank() }
                ?: "shared-${System.currentTimeMillis()}"
            // Keep a file extension when the share names one, so Dart can
            // tell images from PDFs.
            val safe = if (name.contains('.')) name else "$name.jpg"
            val out = File(dir, "${System.currentTimeMillis()}-$safe")
            contentResolver.openInputStream(uri)?.use { input ->
                out.outputStream().use { output -> input.copyTo(output) }
            }
            out.absolutePath
        } catch (_: Exception) {
            null
        }
    }
}
