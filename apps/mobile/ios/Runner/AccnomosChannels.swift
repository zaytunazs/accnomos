import AVFoundation
import Contacts
import Flutter
import UIKit
import UniformTypeIdentifiers

/// The iOS side of the app's own platform channels, the twin of Android's MainActivity.kt,
/// FilePickerBridge.kt and SpeechChannel.kt. Method names and result shapes match Android's so the
/// Dart services (lib/services/*.dart) need no iOS branches:
///
/// * `accnomos/hmrc`   takeCallback: HMRC's `com.accnomos.app://hmrc/callback?...` URL, taken once.
/// * `accnomos/device` facts: HMRC fraud-prevention facts (lib/services/device_facts.dart).
/// * `accnomos/tts`    speak / stop: AVSpeechSynthesizer in British English; speak completes when said.
/// * `accnomos/share`  shareText: the system share sheet; getSharedFiles: always empty (no share
///                     extension on iOS yet).
/// * `accnomos/files`  pickFile: the system document picker, one file, at most 6 MB.
/// * `accnomos/phone-contacts` listContacts: every contact, read-only, after the Contacts prompt.
///
/// Registered from AppDelegate.didInitializeImplicitFlutterEngine. It also receives scene and
/// application URL callbacks, and claims only the HMRC callback URL so MSAL and Google still get theirs.
final class AccnomosChannels: NSObject, FlutterPlugin, FlutterSceneLifeCycleDelegate,
  AVSpeechSynthesizerDelegate, UIDocumentPickerDelegate
{
  private static let hmrcScheme = "com.accnomos.app"
  private static let maxFileBytes = 6 * 1024 * 1024

  private weak var registrar: FlutterPluginRegistrar?
  private var hmrcCallback: String?
  private let synthesizer = AVSpeechSynthesizer()
  private var speaking: FlutterResult?
  private var picking: FlutterResult?

  init(registrar: FlutterPluginRegistrar) {
    self.registrar = registrar
    super.init()
    synthesizer.delegate = self
  }

  static func register(with registrar: FlutterPluginRegistrar) {
    let instance = AccnomosChannels(registrar: registrar)
    let messenger = registrar.messenger()
    let names = [
      "accnomos/hmrc", "accnomos/device", "accnomos/tts", "accnomos/share", "accnomos/files",
      "accnomos/phone-contacts",
    ]
    for name in names {
      let channel = FlutterMethodChannel(name: name, binaryMessenger: messenger)
      // Method names are unique across these channels, so one handler serves them all.
      registrar.addMethodCallDelegate(instance, channel: channel)
    }
    registrar.addApplicationDelegate(instance)
    registrar.addSceneDelegate(instance)
  }

  func handle(_ call: FlutterMethodCall, result: @escaping FlutterResult) {
    let args = call.arguments as? [String: Any] ?? [:]
    switch call.method {
    case "takeCallback":
      result(hmrcCallback)
      hmrcCallback = nil
    case "facts":
      result(deviceFacts())
    case "speak":
      speak(args["text"] as? String ?? "", result: result)
    case "stop":
      finishSpeaking()
      synthesizer.stopSpeaking(at: .immediate)
      result(nil)
    case "shareText":
      shareText(args, result: result)
    case "getSharedFiles":
      result([String]())
    case "pickFile":
      pickFile(args["mimeTypes"] as? [String] ?? ["*/*"], result: result)
    case "listContacts":
      listContacts(result: result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  // MARK: - HMRC callback URL

  @objc(scene:willConnectToSession:options:)
  func scene(
    _ scene: UIScene, willConnectTo session: UISceneSession,
    options connectionOptions: UIScene.ConnectionOptions?
  ) -> Bool {
    // A cold start from the callback: keep it, but let other plugins see the launch too.
    if let contexts = connectionOptions?.urlContexts {
      _ = take(contexts.map { $0.url })
    }
    return false
  }

  @objc(scene:openURLContexts:)
  func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) -> Bool {
    return take(URLContexts.map { $0.url })
  }

  @objc(application:openURL:options:)
  func application(
    _ application: UIApplication, open url: URL,
    options: [UIApplication.OpenURLOptionsKey: Any] = [:]
  ) -> Bool {
    return take([url])
  }

  /// True only for HMRC's callback, so MSAL's and Google's redirects carry on to their plugins.
  private func take(_ urls: [URL]) -> Bool {
    for url in urls where url.scheme == Self.hmrcScheme && url.host == "hmrc" {
      hmrcCallback = url.absoluteString
      return true
    }
    return false
  }

  // MARK: - Device facts (HMRC fraud-prevention headers)

  /// Values iOS does not give are left out, never guessed. Colour depth is 24: every iPhone panel is
  /// 8 bits per channel, and it is what Safari reports as screen.colorDepth on iPhone.
  private func deviceFacts() -> [String: Any] {
    var facts: [String: Any] = [
      "os_family": "iOS",
      "os_version": UIDevice.current.systemVersion,
      "device_manufacturer": "Apple",
      "colour_depth": 24,
    ]
    let model = Self.modelIdentifier()
    if !model.isEmpty { facts["device_model"] = model }
    if let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String {
      facts["app_version"] = version
    }
    return facts
  }

  /// The hardware model, e.g. `iPhone16,2` (a simulator reports its host architecture).
  private static func modelIdentifier() -> String {
    var info = utsname()
    uname(&info)
    let bytes = Mirror(reflecting: info.machine).children.compactMap { $0.value as? Int8 }
    let chars = bytes.prefix(while: { $0 != 0 }).map { Character(UnicodeScalar(UInt8(bitPattern: $0))) }
    return String(chars)
  }

  // MARK: - Speech

  private func speak(_ text: String, result: @escaping FlutterResult) {
    finishSpeaking()
    if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      result(nil)
      return
    }
    if synthesizer.isSpeaking {
      synthesizer.stopSpeaking(at: .immediate)
    }
    let utterance = AVSpeechUtterance(string: text)
    utterance.voice = AVSpeechSynthesisVoice(language: "en-GB")
    speaking = result
    synthesizer.speak(utterance)
  }

  private func finishSpeaking() {
    let pending = speaking
    speaking = nil
    pending?(nil)
  }

  func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance)
  {
    finishSpeaking()
  }

  func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance)
  {
    finishSpeaking()
  }

  // MARK: - Share sheet

  private func shareText(_ args: [String: Any], result: @escaping FlutterResult) {
    guard let presenter = topViewController() else {
      result(false)
      return
    }
    let sheet = UIActivityViewController(
      activityItems: [args["text"] as? String ?? ""], applicationActivities: nil)
    if let subject = args["subject"] as? String {
      sheet.setValue(subject, forKey: "subject")
    }
    anchor(sheet, in: presenter)
    presenter.present(sheet, animated: true)
    result(true)
  }

  // MARK: - Document picker

  private func pickFile(_ mimeTypes: [String], result: @escaping FlutterResult) {
    if picking != nil {
      result(FlutterError(code: "BUSY", message: "A file picker is already open.", details: nil))
      return
    }
    guard let presenter = topViewController() else {
      result(FlutterError(code: "NO_PICKER", message: "Could not open the file picker.", details: nil))
      return
    }
    var types: [UTType] = []
    for mime in mimeTypes where mime != "*/*" {
      if let type = UTType(mimeType: mime), !types.contains(type) { types.append(type) }
    }
    if types.isEmpty { types = [.item] }
    let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
    picker.allowsMultipleSelection = false
    picker.delegate = self
    picking = result
    presenter.present(picker, animated: true)
  }

  func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
    guard let result = picking else { return }
    picking = nil
    guard let url = urls.first else {
      result(nil)
      return
    }
    do {
      let size = (try url.resourceValues(forKeys: [.fileSizeKey])).fileSize ?? 0
      if size > Self.maxFileBytes {
        result(FlutterError(code: "TOO_BIG", message: "That file is over 6 MB.", details: nil))
        return
      }
      let data = try Data(contentsOf: url)
      if data.count > Self.maxFileBytes {
        result(FlutterError(code: "TOO_BIG", message: "That file is over 6 MB.", details: nil))
        return
      }
      result(["name": url.lastPathComponent, "bytes": FlutterStandardTypedData(bytes: data)])
    } catch {
      result(FlutterError(code: "READ_FAILED", message: "Could not read that file.", details: nil))
    }
  }

  func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
    let result = picking
    picking = nil
    result?(nil)
  }

  // MARK: - Contacts (Import contacts › Phone)

  private func listContacts(result: @escaping FlutterResult) {
    let store = CNContactStore()
    store.requestAccess(for: .contacts) { granted, _ in
      guard granted else {
        DispatchQueue.main.async {
          result(
            FlutterError(code: "DENIED", message: "Contacts permission was not given.", details: nil))
        }
        return
      }
      DispatchQueue.global(qos: .userInitiated).async {
        let keys: [CNKeyDescriptor] = [
          CNContactFormatter.descriptorForRequiredKeys(for: .fullName),
          CNContactOrganizationNameKey as CNKeyDescriptor,
          CNContactEmailAddressesKey as CNKeyDescriptor,
          CNContactPhoneNumbersKey as CNKeyDescriptor,
        ]
        let request = CNContactFetchRequest(keysToFetch: keys)
        request.sortOrder = .userDefault
        var rows: [[String: Any]] = []
        do {
          try store.enumerateContacts(with: request) { contact, _ in
            let company = contact.organizationName
            let name = CNContactFormatter.string(from: contact, style: .fullName) ?? company
            if name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return }
            rows.append([
              "name": name,
              "company": company,
              "emails": contact.emailAddresses.map { $0.value as String },
              "phones": contact.phoneNumbers.map { $0.value.stringValue },
            ])
          }
          DispatchQueue.main.async { result(rows) }
        } catch {
          DispatchQueue.main.async {
            result(
              FlutterError(
                code: "READ_FAILED", message: "Could not read the phone's contacts.", details: nil))
          }
        }
      }
    }
  }

  // MARK: - Presenting

  private func topViewController() -> UIViewController? {
    var root = registrar?.viewController
    if root == nil {
      let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
      root = scenes.flatMap { $0.windows }.first { $0.isKeyWindow }?.rootViewController
    }
    var top = root
    while let presented = top?.presentedViewController {
      top = presented
    }
    return top
  }

  /// iPad presents activity sheets as popovers, which need an anchor.
  private func anchor(_ controller: UIViewController, in presenter: UIViewController) {
    if let popover = controller.popoverPresentationController {
      popover.sourceView = presenter.view
      popover.sourceRect = CGRect(
        x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 0, height: 0)
      popover.permittedArrowDirections = []
    }
  }
}
