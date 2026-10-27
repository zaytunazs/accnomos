import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:shared_preferences/shared_preferences.dart';

/// Release builds talk to the hosted runtime over HTTPS; debug builds default to
/// the emulator's alias for the dev PC (10.0.2.2) so a local runtime is reachable.
const String kDefaultRuntimeUrl =
    kReleaseMode ? 'https://api.accnomos.com' : 'http://10.0.2.2:8780';

/// Runtime + AI settings, persisted on-device.
///
/// `apiKey` is stored with shared_preferences for now.
/// TODO: move apiKey to flutter_secure_storage before any real user data.
class AppSettings {
  AppSettings({
    this.runtimeUrl = kDefaultRuntimeUrl,
    this.aiMode = 'local',
    this.aiBaseUrl = 'http://192.168.1.176:11434',
    this.aiModel = 'muse-glimmer:30b',
    this.apiKey,
    this.userEmail,
    this.businessName,
  });

  /// Address of the reader service. The default is the Android emulator's
  /// alias for the dev PC (10.0.2.2), so the emulator reaches a runtime
  /// running on your own computer.
  final String runtimeUrl;

  /// 'local' reads on your machine, 'key' reads with Muse Spark via API key.
  final String aiMode;

  /// Address of the on-machine model (Ollama).
  final String aiBaseUrl;

  /// On-machine model name.
  final String aiModel;

  /// Muse API key, only used when [aiMode] is 'key'.
  /// TODO: move to flutter_secure_storage.
  final String? apiKey;

  final String? userEmail;

  /// Business name sent as `X-Business-Name` so the reader attributes
  /// sales correctly (mirrors the web's `accnomos.business` value).
  final String? businessName;

  static const _kRuntimeUrl = 'accnomos.runtimeUrl';
  static const _kAiMode = 'accnomos.aiMode';
  static const _kAiBaseUrl = 'accnomos.aiBaseUrl';
  static const _kAiModel = 'accnomos.aiModel';
  static const _kApiKey = 'accnomos.apiKey';
  static const _kUserEmail = 'accnomos.userEmail';
  static const _kBusinessName = 'accnomos.businessName';

  /// Load saved settings, falling back to defaults for anything missing.
  static Future<AppSettings> load() async {
    final prefs = await SharedPreferences.getInstance();
    return AppSettings(
      runtimeUrl: prefs.getString(_kRuntimeUrl) ?? kDefaultRuntimeUrl,
      aiMode: prefs.getString(_kAiMode) ?? 'local',
      aiBaseUrl: prefs.getString(_kAiBaseUrl) ?? 'http://192.168.1.176:11434',
      aiModel: prefs.getString(_kAiModel) ?? 'muse-glimmer:30b',
      apiKey: prefs.getString(_kApiKey),
      userEmail: prefs.getString(_kUserEmail),
      businessName: prefs.getString(_kBusinessName),
    );
  }

  /// Persist the current values.
  Future<void> save() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kRuntimeUrl, runtimeUrl);
    await prefs.setString(_kAiMode, aiMode);
    await prefs.setString(_kAiBaseUrl, aiBaseUrl);
    await prefs.setString(_kAiModel, aiModel);
    if (apiKey == null || apiKey!.isEmpty) {
      await prefs.remove(_kApiKey);
    } else {
      await prefs.setString(_kApiKey, apiKey!);
    }
    if (userEmail == null || userEmail!.isEmpty) {
      await prefs.remove(_kUserEmail);
    } else {
      await prefs.setString(_kUserEmail, userEmail!);
    }
    if (businessName == null || businessName!.isEmpty) {
      await prefs.remove(_kBusinessName);
    } else {
      await prefs.setString(_kBusinessName, businessName!);
    }
  }
}
