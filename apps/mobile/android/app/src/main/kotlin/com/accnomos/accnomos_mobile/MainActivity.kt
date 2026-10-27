package com.accnomos.accnomos_mobile

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.ContactsContract
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

class MainActivity : FlutterActivity() {
    companion object {
        private const val CHANNEL = "accnomos/share"
        private const val CONTACTS_CHANNEL = "accnomos/phone-contacts"
        private const val PICK_CONTACT = 4711
    }

    /** Shared files staged into our cache dir, waiting for Dart to collect. */
    private val pending = mutableListOf<String>()

    /** The Dart call waiting for the system contact picker, if any. */
    private var pickResult: MethodChannel.Result? = null

    /**
     * The system contact picker (ACTION_PICK on Contacts). It returns the contact's URI with a one-time read grant,
     * so the app needs no `READ_CONTACTS` permission (nothing is added to the manifest). FlutterActivity is not a
     * ComponentActivity, so this uses startActivityForResult rather than registerForActivityResult.
     */
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != PICK_CONTACT) return
        val result = pickResult
        pickResult = null
        if (result == null) return
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) {
            result.success(null) // the user backed out of the picker
            return
        }
        try {
            result.success(readContact(uri))
        } catch (_: Exception) {
            result.error("READ_FAILED", "Could not read that contact.", null)
        }
    }

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
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CONTACTS_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "pickContact") {
                    if (pickResult != null) {
                        result.error("BUSY", "A contact pick is already open.", null)
                    } else {
                        pickResult = result
                        @Suppress("DEPRECATION")
                        startActivityForResult(
                            Intent(Intent.ACTION_PICK, ContactsContract.Contacts.CONTENT_URI),
                            PICK_CONTACT,
                        )
                    }
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

    /**
     * Name, emails, phones and the first postal address for the picked
     * contact URI only. Every query is scoped to this one contact.
     */
    private fun readContact(uri: Uri): Map<String, Any?> {
        var contactId = ""
        var name = ""
        contentResolver.query(
            uri,
            arrayOf(
                ContactsContract.Contacts._ID,
                ContactsContract.Contacts.DISPLAY_NAME,
            ),
            null, null, null,
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                contactId = cursor.getString(0) ?: ""
                name = cursor.getString(1) ?: ""
            }
        }
        if (contactId.isBlank()) return mapOf("name" to name)
        // Emails, phones and the address are best-effort: the picker's grant may cover only the contact's own URI,
        // in which case Android refuses these queries and the import keeps the name alone.
        val emails = mutableListOf<String>()
        runCatching { contentResolver.query(
            ContactsContract.CommonDataKinds.Email.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.Email.ADDRESS),
            "${ContactsContract.CommonDataKinds.Email.CONTACT_ID} = ?",
            arrayOf(contactId), null,
        )?.use { cursor ->
            while (cursor.moveToNext() && emails.size < 5) {
                cursor.getString(0)?.takeIf { it.isNotBlank() }?.let { emails.add(it) }
            }
        } }
        val phones = mutableListOf<String>()
        runCatching { contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER),
            "${ContactsContract.CommonDataKinds.Phone.CONTACT_ID} = ?",
            arrayOf(contactId), null,
        )?.use { cursor ->
            while (cursor.moveToNext() && phones.size < 5) {
                cursor.getString(0)?.takeIf { it.isNotBlank() }?.let { phones.add(it) }
            }
        } }
        var address: String? = null
        runCatching { contentResolver.query(
            ContactsContract.CommonDataKinds.StructuredPostal.CONTENT_URI,
            arrayOf(ContactsContract.CommonDataKinds.StructuredPostal.FORMATTED_ADDRESS),
            "${ContactsContract.CommonDataKinds.StructuredPostal.CONTACT_ID} = ?",
            arrayOf(contactId), null,
        )?.use { cursor ->
            while (cursor.moveToNext()) {
                val value = cursor.getString(0)?.trim()?.takeIf { it.isNotBlank() }
                if (value != null) {
                    address = value
                    break
                }
            }
        } }
        return mapOf(
            "name" to name,
            "emails" to emails,
            "phones" to phones,
            "address" to address,
        )
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
