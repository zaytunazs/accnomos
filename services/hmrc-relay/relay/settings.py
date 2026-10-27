"""Relay configuration, read from the process environment only (no .env file)."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    hmrc_client_id: str = ""
    hmrc_client_secret: SecretStr = SecretStr("")
    hmrc_base: str = "https://test-api.service.hmrc.gov.uk"
    hmrc_auth_base: str = "https://test-www.tax.service.gov.uk"
    hmrc_redirect_uri: str = ""
    hmrc_vendor_product_name: str = "Accnomos"
    hmrc_vendor_version: str = "0.1.0"
    relay_public_ip: str = ""
    relay_licence_hash: str = ""
    # Origins (scheme://host[:port]) the OAuth callback may redirect tokens to. http://localhost and
    # http://127.0.0.1 (any port) are always allowed for development.
    relay_allowed_redirects: str = ""

    @property
    def sandbox(self) -> bool:
        return self.hmrc_base.startswith("https://test-")

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

    def redirect_allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return False
        if parts.scheme == "http" and parts.hostname in {"localhost", "127.0.0.1"}:
            return True
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        allowed = {o.strip().rstrip("/").lower() for o in self.relay_allowed_redirects.split(",") if o.strip()}
        return origin in allowed


@lru_cache
def get_settings() -> Settings:
    return Settings()
