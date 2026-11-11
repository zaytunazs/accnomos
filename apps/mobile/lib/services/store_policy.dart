import 'package:flutter/foundation.dart';

/// What the app store a build ships through allows the app to say about
/// paying for Accnomos (docs/IOS_APP_STORE.md, "Payments").
///
/// On iOS the app is a companion to an account set up on the web: it must not
/// sell anything, show a price, or link or point to a purchase outside the app
/// (App Store Review Guidelines 3.1.1 and 3.1.3; the UK storefront has no
/// link-out exception as of November 2026). So any "Plan & billing", pricing
/// or upgrade entry checks [purchaseLinksAllowed] and, when false, shows the
/// plan's status only: no price, no button, no link, no "visit our website to
/// upgrade".
class StorePolicy {
  StorePolicy._();

  /// False on iOS; true elsewhere, so Android's behaviour is unchanged.
  static bool purchaseLinksAllowedOn(TargetPlatform platform) =>
      platform != TargetPlatform.iOS;

  /// [purchaseLinksAllowedOn] for this device.
  static bool get purchaseLinksAllowed =>
      purchaseLinksAllowedOn(defaultTargetPlatform);
}
