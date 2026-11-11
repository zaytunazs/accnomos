"""Relay configuration, read from the process environment only (no .env file)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["sandbox", "production"]
SANDBOX_BASE = "https://test-api.service.hmrc.gov.uk"
SANDBOX_AUTH_BASE = "https://test-www.tax.service.gov.uk"
PRODUCTION_BASE = "https://api.service.hmrc.gov.uk"
PRODUCTION_AUTH_BASE = "https://www.tax.service.gov.uk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # HMRC_ENV picks where real users' VAT calls go: "sandbox" (the default) or "production". Production uses its
    # own credentials (HMRC_PROD_CLIENT_ID / HMRC_PROD_CLIENT_SECRET) and HMRC's live hosts; the sandbox ones below
    # stay in use for the demo (requests marked X-HMRC-Environment: sandbox) and for the sandbox-only tools.
    hmrc_env: Environment = "sandbox"
    hmrc_client_id: str = ""  # the sandbox application's
    hmrc_client_secret: SecretStr = SecretStr("")
    hmrc_prod_client_id: str = ""
    hmrc_prod_client_secret: SecretStr = SecretStr("")
    hmrc_base: str = SANDBOX_BASE  # sandbox API host (overridable for tests); production is always PRODUCTION_BASE
    hmrc_auth_base: str = SANDBOX_AUTH_BASE
    hmrc_redirect_uri: str = ""
    hmrc_vendor_product_name: str = "Accnomos"
    hmrc_vendor_version: str = "0.1.0"
    relay_public_ip: str = ""
    relay_licence_hash: str = ""
    # Origins (scheme://host[:port]) the OAuth callback may redirect tokens to. http://localhost and
    # http://127.0.0.1 (any port) are always allowed for development.
    relay_allowed_redirects: str = ""
    # Requests per minute per client IP (in memory, per process); 0 turns the limit off.
    rate_limit_per_min: int = 60
    # Kept so an old .env still parses; no longer honoured. MTD Income Tax (relay/itsa.py, relay/itsa_property.py) is
    # sandbox only whatever this says: HMRC is not issuing production credentials for new 2026-27 quarterly-update
    # products (Developer Hub notice, 15 Sep 2026).
    relay_itsa_production: bool = False

    @property
    def sandbox(self) -> bool:
        return self.hmrc_base.startswith("https://test-")

    @property
    def production(self) -> bool:
        return self.hmrc_env == "production"

    def for_environment(self, env: Environment) -> Settings:
        """The settings one HMRC environment is called with: production gets HMRC's live hosts and the production
        credentials; sandbox the sandbox ones (HMRC_BASE / HMRC_AUTH_BASE, which must then be test hosts)."""
        if env == "production":
            return self.model_copy(
                update={
                    "hmrc_env": "production",
                    "hmrc_base": PRODUCTION_BASE,
                    "hmrc_auth_base": PRODUCTION_AUTH_BASE,
                    "hmrc_client_id": self.hmrc_prod_client_id,
                    "hmrc_client_secret": self.hmrc_prod_client_secret,
                }
            )
        return self.model_copy(update={"hmrc_env": "sandbox"})

    @property
    def configured(self) -> bool:
        return bool(self.hmrc_client_id and self.hmrc_client_secret.get_secret_value())

    @property
    def token_url(self) -> str:
        return f"{self.hmrc_base.rstrip('/')}/oauth/token"

    @property
    def authorize_url(self) -> str:
        return f"{self.hmrc_auth_base.rstrip('/')}/oauth/authorize"

    @property
    def vendor_product_key(self) -> str:
        """Product name as used on the left of `key=value` vendor headers."""
        return self.hmrc_vendor_product_name.lower().replace(" ", "-")

    @property
    def allowed_origins(self) -> set[str]:
        return {o.strip().rstrip("/").lower() for o in self.relay_allowed_redirects.split(",") if o.strip()}

    def redirect_allowed(self, url: str) -> bool:
        # urlsplit silently drops tabs/newlines and leaves backslashes in the host, while the URL we redirect
        # to keeps them; refuse such URLs outright rather than compare a cleaned-up copy.
        if any(c.isspace() or ord(c) < 0x20 or ord(c) == 0x7F or c == "\\" for c in url):
            return False
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc or parts.username is not None or parts.password is not None:
            return False
        if parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}:
            return True
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        return origin in self.allowed_origins


@lru_cache
def get_settings() -> Settings:
    return Settings()
