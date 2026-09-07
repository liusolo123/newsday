"""Resolve Vite development URLs or production manifest assets for Jinja."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from app.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "app" / "static" / "dist" / ".vite" / "manifest.json"
ENTRYPOINT = "frontend/main.js"


class ViteAssetError(RuntimeError):
    """Raised when production assets are missing or unsafe."""


@dataclass(frozen=True)
class ViteAssets:
    development: bool
    legacy: bool
    stylesheets: tuple[str, ...] = ()
    module_preloads: tuple[str, ...] = ()
    entry_script: str | None = None
    dev_client: str | None = None


def _safe_static_url(asset: object) -> str:
    if not isinstance(asset, str) or not asset:
        raise ViteAssetError("Vite manifest contains an invalid asset path")
    path = PurePosixPath(asset)
    if path.is_absolute() or ".." in path.parts:
        raise ViteAssetError("Vite manifest contains an unsafe asset path")
    return "/static/dist/" + quote(path.as_posix(), safe="/-._~")


def _development_server(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ViteAssetError("VITE_DEV_SERVER_URL must use a local http origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ViteAssetError("VITE_DEV_SERVER_URL must be an origin without a path")
    return url.rstrip("/")


def _read_manifest(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ViteAssetError("Vite production manifest is missing; run npm run build") from error
    except json.JSONDecodeError as error:
        raise ViteAssetError("Vite production manifest is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ViteAssetError("Vite production manifest must be an object")
    return payload


def _production_assets(manifest: dict[str, dict[str, object]]) -> ViteAssets:
    if ENTRYPOINT not in manifest or not isinstance(manifest[ENTRYPOINT], dict):
        raise ViteAssetError(f"Vite production manifest has no {ENTRYPOINT} entry")

    stylesheets: list[str] = []
    preloads: list[str] = []
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        visited.add(key)
        entry = manifest.get(key)
        if not isinstance(entry, dict):
            raise ViteAssetError(f"Vite production manifest import is missing: {key}")
        for stylesheet in entry.get("css", []):
            url = _safe_static_url(stylesheet)
            if url not in stylesheets:
                stylesheets.append(url)
        for imported_key in entry.get("imports", []):
            if not isinstance(imported_key, str):
                raise ViteAssetError("Vite production manifest contains an invalid import")
            imported = manifest.get(imported_key)
            if not isinstance(imported, dict):
                raise ViteAssetError(f"Vite production manifest import is missing: {imported_key}")
            imported_file = _safe_static_url(imported.get("file"))
            if imported_file not in preloads:
                preloads.append(imported_file)
            visit(imported_key)

    visit(ENTRYPOINT)
    entry_script = _safe_static_url(manifest[ENTRYPOINT].get("file"))
    return ViteAssets(
        development=False,
        legacy=False,
        stylesheets=tuple(stylesheets),
        module_preloads=tuple(preloads),
        entry_script=entry_script,
    )


def vite_assets(settings: Settings) -> ViteAssets:
    """Return asset URLs without ever leaking a local development URL in production."""
    if settings.environment == "production" and settings.frontend_dev_mode:
        raise ViteAssetError("FRONTEND_DEV_MODE cannot be enabled in production")
    if settings.frontend_dev_mode:
        origin = _development_server(settings.vite_dev_server_url)
        return ViteAssets(
            development=True,
            legacy=False,
            entry_script=f"{origin}/{ENTRYPOINT}",
            dev_client=f"{origin}/@vite/client",
        )
    if MANIFEST_PATH.exists():
        return _production_assets(_read_manifest(MANIFEST_PATH))
    if settings.environment == "production":
        raise ViteAssetError("Vite production manifest is missing; run npm run build")
    return ViteAssets(
        development=False,
        legacy=True,
        stylesheets=("/static/styles/site.css",),
    )
