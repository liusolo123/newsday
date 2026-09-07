"""Runtime configuration that keeps deployment secrets outside source control."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_session_secret: str
    invite_lookup_key: str
    webhook_encryption_key: str
    environment: str = "development"
    deepseek_api_key: str = ""
    admin_usernames: str = ""
    frontend_dev_mode: bool = False
    vite_dev_server_url: str = "http://127.0.0.1:5173"

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            app_session_secret=os.getenv("APP_SESSION_SECRET", ""),
            invite_lookup_key=os.getenv("INVITE_LOOKUP_KEY", ""),
            webhook_encryption_key=os.getenv("WEBHOOK_ENCRYPTION_KEY", ""),
            environment=os.getenv("APP_ENV", "development"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            admin_usernames=os.getenv("ADMIN_USERNAMES", ""),
            frontend_dev_mode=os.getenv("FRONTEND_DEV_MODE", "").strip().lower()
            in {"1", "true", "yes", "on"},
            vite_dev_server_url=os.getenv("VITE_DEV_SERVER_URL", "http://127.0.0.1:5173"),
        )

    def missing_required_values(self) -> tuple[str, ...]:
        values = {
            "DATABASE_URL": self.database_url,
            "APP_SESSION_SECRET": self.app_session_secret,
            "INVITE_LOOKUP_KEY": self.invite_lookup_key,
            "WEBHOOK_ENCRYPTION_KEY": self.webhook_encryption_key,
        }
        return tuple(name for name, value in values.items() if not value)

    @property
    def cookie_secure(self) -> bool:
        return self.environment == "production"

    def is_admin(self, username: str) -> bool:
        return username.casefold() in {item.strip().casefold() for item in self.admin_usernames.split(",") if item.strip()}
