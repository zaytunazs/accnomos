package com.accnomos.accnomos_mobile

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodChannel
import java.util.Locale
import java.util.UUID

/**
 * "accnomos/tts": the hands-free assistant reads answers aloud with the phone's own TextToSpeech (British English
 * where installed). `speak` returns when the utterance has finished (or failed), so Dart can listen again after it;
 * `stop` cuts it short. Nothing is sent anywhere.
 */
class SpeechChannel(context: Context, messenger: BinaryMessenger) {
    private val main = Handler(Looper.getMainLooper())
    private var ready = false
    private var failed = false
    private val waiting = mutableMapOf<String, MethodChannel.Result>()
    private val queued = mutableListOf<Pair<String, MethodChannel.Result>>()
    private val tts: TextToSpeech = TextToSpeech(context.applicationContext) { status ->
        main.post {
            if (status == TextToSpeech.SUCCESS) {
                val uk = tts.isLanguageAvailable(Locale.UK) >= TextToSpeech.LANG_AVAILABLE
                tts.language = if (uk) Locale.UK else Locale.getDefault()
                ready = true
                queued.forEach { (text, result) -> say(text, result) }
            } else {
                failed = true
                queued.forEach { (_, result) -> result.success(null) }
            }
            queued.clear()
        }
    }

    init {
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) = finish(utteranceId)
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finish(utteranceId)
            override fun onStop(utteranceId: String?, interrupted: Boolean) = finish(utteranceId)
        })
        MethodChannel(messenger, "accnomos/tts").setMethodCallHandler { call, result ->
            when (call.method) {
                "speak" -> {
                    val text = call.argument<String>("text") ?: ""
                    when {
                        text.isBlank() || failed -> result.success(null)
                        ready -> say(text, result)
                        else -> queued.add(text to result)
                    }
                }
                "stop" -> {
                    if (ready) tts.stop()
                    finishAll()
                    result.success(null)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun say(text: String, result: MethodChannel.Result) {
        val id = UUID.randomUUID().toString()
        waiting[id] = result
        if (tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS) finish(id)
    }

    private fun finish(id: String?) {
        main.post { id?.let { waiting.remove(it)?.success(null) } }
    }

    private fun finishAll() {
        val all = waiting.values.toList()
        waiting.clear()
        all.forEach { it.success(null) }
    }

    fun shutdown() {
        finishAll()
        tts.shutdown()
    }
}
