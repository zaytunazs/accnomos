import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.accnomos.accnomos_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.accnomos.app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // MSAL signature hash for the redirect URI
        // (msauth://com.accnomos.app/<hash>). It differs per signing key, so
        // pass release keys with -PmsalSignatureHash=... ; without it the
        // debug key hash below is used. The same value must reach Dart via
        // --dart-define=MSAL_SIG_HASH=... (see lib/services/auth.dart).
        val msalSigHash: String =
            (project.findProperty("msalSignatureHash") as String?)
                ?: "3NuO8lO3x1Q9/IdBwhH5qMZmiIU="
        manifestPlaceholders["msalSignatureHash"] = msalSigHash
    }

    // Upload-key signing. android/key.properties is git-ignored and created by the owner
    // with tools/make_upload_key.ps1 (used by tools/build_release.ps1). A release build
    // without it fails below instead of silently falling back to the debug key.
    val keyProps = Properties()
    val keyPropsFile = rootProject.file("key.properties")
    if (keyPropsFile.exists()) {
        keyPropsFile.inputStream().use { keyProps.load(it) }
    }
    signingConfigs {
        create("upload") {
            if (keyPropsFile.exists()) {
                keyAlias = keyProps["keyAlias"] as String
                keyPassword = keyProps["keyPassword"] as String
                storeFile = rootProject.file(keyProps["storeFile"] as String)  // relative to android/
                storePassword = keyProps["storePassword"] as String
            }
        }
    }

    buildTypes {
        release {
            if (keyPropsFile.exists()) {
                signingConfig = signingConfigs.getByName("upload")
            } else {
                // Fail only when a release artifact is actually requested, so debug
                // builds, `flutter test` and `flutter analyze` keep working without
                // android/key.properties. This block is evaluated at configuration
                // time for every Gradle invocation, hence the task-name check.
                val tasks = gradle.startParameter.taskNames
                val wantsRelease = tasks.any {
                    it.contains("Release", ignoreCase = true) ||
                        it.contains("Bundle", ignoreCase = true)
                } || tasks.any {
                    it.equals("build", ignoreCase = true) || it.endsWith(":build") ||
                        it.equals("assemble") || it.endsWith(":assemble")
                }
                if (wantsRelease) {
                    throw GradleException("Release build needs android/key.properties; see tools/build_release.ps1")
                }
                signingConfig = signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
