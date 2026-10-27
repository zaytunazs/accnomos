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
    this.vatNumber,
    this.vatStagger,
    this.vatStartMonth,
    this.autopilotLevel = 'L1',
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

  /// UK VAT registration number (9 digits). Format-checked only; it is
  /// stored on-device and not sent anywhere yet.
  final String? vatNumber;

  /// HMRC VAT stagger group (1–3) for quarterly returns, mirroring the
  /// web's `accnomos.business` stagger. Null when never saved: calls then
  /// send no stagger and the runtime assumes calendar quarters
  /// (`assumed: true`).
  final int? vatStagger;

  /// Month (1–12) a custom quarter starts in. When set, the deadlines
  /// call sends `start_month=` instead of `stagger=`.
  final int? vatStartMonth;

  /// Autopilot level, like the web's `accnomos.autopilot`: L0 off, L1
  /// (default) rules wait for review, L2 posts matching rules on its own.
  final String autopilotLevel;

  static const _kRuntimeUrl = 'accnomos.runtimeUrl';
  static const _kAiMode = 'accnomos.aiMode';
  static const _kAiBaseUrl = 'accnomos.aiBaseUrl';
  static const _kAiModel = 'accnomos.aiModel';
  static const _kApiKey = 'accnomos.apiKey';
  static const _kUserEmail = 'accnomos.userEmail';
  static const _kBusinessName = 'accnomos.businessName';
  static const _kVatNumber = 'accnomos.vatNumber';
  static const _kVatStagger = 'accnomos.vatStagger';
  static const _kVatStartMonth = 'accnomos.vatStartMonth';
  static const _kAutopilot = 'accnomos.autopilot';

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
      vatNumber: prefs.getString(_kVatNumber),
      vatStagger: _clampStagger(prefs.getInt(_kVatStagger)),
      vatStartMonth: _clampMonth(prefs.getInt(_kVatStartMonth)),
      autopilotLevel: _clampLevel(prefs.getString(_kAutopilot)),
    );
  }

  static int? _clampStagger(int? value) =>
      value == null || value < 1 || value > 3 ? null : value;

  static int? _clampMonth(int? value) =>
      value == null || value < 1 || value > 12 ? null : value;

  static String _clampLevel(String? value) =>
      value == 'L0' || value == 'L2' ? value! : 'L1';

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
    if (vatNumber == null || vatNumber!.isEmpty) {
      await prefs.remove(_kVatNumber);
    } else {
      await prefs.setString(_kVatNumber, vatNumber!);
    }
    await prefs.setString(_kAutopilot, autopilotLevel);
    if (vatStagger == null) {
      await prefs.remove(_kVatStagger);
    } else {
      await prefs.setInt(_kVatStagger, vatStagger!);
    }
    if (vatStartMonth == null) {
      await prefs.remove(_kVatStartMonth);
    } else {
      await prefs.setInt(_kVatStartMonth, vatStartMonth!);
    }
  }
}
