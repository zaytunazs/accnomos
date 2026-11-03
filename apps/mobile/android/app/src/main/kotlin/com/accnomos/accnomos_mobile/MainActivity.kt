package com.accnomos.accnomos_mobile

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Build
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
        private const val DEVICE_CHANNEL = "accnomos/device"
        private const val HMRC_CHANNEL = "accnomos/hmrc"
        private const val PICK_CONTACT = 4711
        private const val READ_CONTACTS_REQUEST = 4712
        private const val MAX_PHONE_CONTACTS = 3000
    }

    /** Shared files staged into our cache dir, waiting for Dart to collect. */
    private val pending = mutableListOf<String>()

    /** HMRC's answer handed back by accnomos.com/auth/hmrc-app.html (com.accnomos.app://hmrc/callback?...), until
     *  Dart takes it (once). It holds a one-time PKCE code that is useless without the verifier the app keeps. */
    private var hmrcCallback: String? = null

    /** `accnomos/files`: the document picker for statement CSVs and the invoice logo (FilePickerBridge.kt). */
    private val filePicker by lazy { FilePickerBridge(this) }

    /** The Dart call waiting for the system contact picker, if any. */
    private var pickResult: MethodChannel.Result? = null

    /** The Dart call waiting for the Contacts permission answer (Import contacts › Phone), if any. */
    private var listResult: MethodChannel.Result? = null

    /**
     * The system contact picker (ACTION_PICK on Contacts). It returns the contact's URI with a one-time read grant,
     * so picking one needs no `READ_CONTACTS` permission (Import contacts › Phone, which lists them all, does ask for
     * it then). FlutterActivity is not a
     * ComponentActivity, so this uses startActivityForResult rather than registerForActivityResult.
     */
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (filePicker.onResult(requestCode, resultCode, data)) return
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

    /** The hands-free assistant's voice (SpeechChannel.kt). */
    private var speech: SpeechChannel? = null

    override fun onDestroy() {
        speech?.shutdown()
        speech = null
        super.onDestroy()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        speech = SpeechChannel(this, flutterEngine.dartExecutor.binaryMessenger)
        filePicker.register(flutterEngine.dartExecutor.binaryMessenger)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "getSharedFiles") {
                    result.success(ArrayList(pending))
                    pending.clear()
                } else if (call.method == "shareText") {
                    // The system share sheet with plain text (a CSV export, say): no file provider, no permission.
                    val send = Intent(Intent.ACTION_SEND).apply {
                        type = call.argument<String>("mime") ?: "text/plain"
                        putExtra(Intent.EXTRA_TEXT, call.argument<String>("text") ?: "")
                        call.argument<String>("subject")?.let { putExtra(Intent.EXTRA_SUBJECT, it) }
                    }
                    try {
                        startActivity(Intent.createChooser(send, call.argument<String>("subject") ?: "Share"))
                        result.success(true)
                    } catch (_: Exception) {
                        result.success(false)
                    }
                } else {
                    result.notImplemented()
                }
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CONTACTS_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "listContacts") {
                    listContacts(result)
                } else if (call.method == "pickContact") {
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
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, DEVICE_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "facts") result.success(deviceFacts()) else result.notImplemented()
            }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, HMRC_CHANNEL)
            .setMethodCallHandler { call, result ->
                if (call.method == "takeCallback") {
                    result.success(hmrcCallback)
                    hmrcCallback = null
                } else {
                    result.notImplemented()
                }
            }
        handleIntent(intent)
    }

    /**
     * What the phone reports for HMRC's fraud-prevention headers (MOBILE_APP_VIA_SERVER: Gov-Client-User-Agent and
     * the colour depth in Gov-Client-Screens) and the app version for Gov-Vendor-Version. A value Android does not
     * give is left out, never guessed.
     */
    private fun deviceFacts(): Map<String, Any?> {
        val out = mutableMapOf<String, Any?>(
            "os_family" to "Android",
            "os_version" to Build.VERSION.RELEASE,
            "device_manufacturer" to Build.MANUFACTURER,
            "device_model" to Build.MODEL,
        )
        runCatching {
            @Suppress("DEPRECATION")
            val format = windowManager.defaultDisplay.pixelFormat
            // Colour bits only (no alpha), as a browser's screen.colorDepth reports them.
            val depth = when (format) {
                PixelFormat.RGBA_8888, PixelFormat.RGBX_8888, PixelFormat.RGB_888 -> 24
                PixelFormat.RGB_565 -> 16
                else -> PixelFormat().also { PixelFormat.getPixelFormatInfo(format, it) }.bitsPerPixel
            }
            if (depth > 0) out["colour_depth"] = depth
        }
        runCatching {
            @Suppress("DEPRECATION")
            val info = packageManager.getPackageInfo(packageName, 0)
            out["app_version"] = info.versionName
        }
        return out
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
     * Import contacts › Phone: every contact on the phone (name, company, emails, phones), read on the phone only.
     * Needs READ_CONTACTS, asked for at the moment the user opens the Phone list (never at start-up). Only the rows
     * the user then ticks are sent to their books; nothing is ever written to the phone.
     */
    private fun listContacts(result: MethodChannel.Result) {
        if (checkSelfPermission(Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED) {
            readAllContacts(result)
            return
        }
        if (listResult != null) {
            result.error("BUSY", "Already asking for the Contacts permission.", null)
            return
        }
        listResult = result
        requestPermissions(arrayOf(Manifest.permission.READ_CONTACTS), READ_CONTACTS_REQUEST)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != READ_CONTACTS_REQUEST) return
        val result = listResult ?: return
        listResult = null
        if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            readAllContacts(result)
        } else {
            result.error("DENIED", "Contacts permission was not given.", null)
        }
    }

    private fun readAllContacts(result: MethodChannel.Result) {
        Thread {
            try {
                val out = allContacts()
                runOnUiThread { result.success(out) }
            } catch (_: Exception) {
                runOnUiThread { result.error("READ_FAILED", "Could not read the phone's contacts.", null) }
            }
        }.start()
    }

    private fun allContacts(): List<Map<String, Any?>> {
        data class Row(val name: String, val emails: MutableList<String>, val phones: MutableList<String>, var company: String?)
        val rows = linkedMapOf<String, Row>()
        contentResolver.query(
            ContactsContract.Contacts.CONTENT_URI,
            arrayOf(ContactsContract.Contacts._ID, ContactsContract.Contacts.DISPLAY_NAME),
            null, null, "${ContactsContract.Contacts.DISPLAY_NAME} COLLATE NOCASE ASC",
        )?.use { c ->
            while (c.moveToNext() && rows.size < MAX_PHONE_CONTACTS) {
                val id = c.getString(0) ?: continue
                val name = c.getString(1)?.trim().orEmpty()
                if (name.isNotEmpty()) rows[id] = Row(name, mutableListOf(), mutableListOf(), null)
            }
        }
        contentResolver.query(
            ContactsContract.Data.CONTENT_URI,
            arrayOf(
                ContactsContract.Data.CONTACT_ID,
                ContactsContract.Data.MIMETYPE,
                ContactsContract.Data.DATA1,
            ),
            "${ContactsContract.Data.MIMETYPE} IN (?, ?, ?)",
            arrayOf(
                ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE,
                ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE,
                ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE,
            ),
            null,
        )?.use { c ->
            while (c.moveToNext()) {
                val row = rows[c.getString(0) ?: continue] ?: continue
                val value = c.getString(2)?.trim().orEmpty()
                if (value.isEmpty()) continue
                when (c.getString(1)) {
                    ContactsContract.CommonDataKinds.Email.CONTENT_ITEM_TYPE ->
                        if (row.emails.size < 5 && value !in row.emails) row.emails.add(value)
                    ContactsContract.CommonDataKinds.Phone.CONTENT_ITEM_TYPE ->
                        if (row.phones.size < 5 && value !in row.phones) row.phones.add(value)
                    ContactsContract.CommonDataKinds.Organization.CONTENT_ITEM_TYPE ->
                        if (row.company == null) row.company = value
                }
            }
        }
        return rows.values.map {
            mapOf("name" to it.name, "emails" to it.emails, "phones" to it.phones, "company" to it.company)
        }
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
        if (intent.action == Intent.ACTION_VIEW) {
            val data = intent.data
            if (data != null && data.scheme == "com.accnomos.app" && data.host == "hmrc") {
                hmrcCallback = data.toString()
                intent.data = null // taken: a later configuration change must not hand it over again
            }
            return
        }
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
