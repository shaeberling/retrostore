"""Local Flask API factories used by tests and migration verification."""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from flask import Flask

from retrostore.api.storage import DownloadApp, DownloadMedia, PublicScreenshot
from retrostore.migration.catalog_mirror import (
    CatalogMirror,
    MirrorApiDataStore,
    load_catalog_mirror_archive,
)
from retrostore.testing.api import representative_storage
from services.api.app import create_app


def create_representative_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create a local API backed by the reviewed representative fixture."""

    app_config = {"RETROSTORE_API_STORAGE": representative_storage()}
    if config:
        app_config.update(config)
    return create_app(app_config)


def create_archive_app(archive_path: str | Path, config: Mapping[str, Any] | None = None) -> Flask:
    """Create a local API from a verified migration archive."""

    app_config: dict[str, Any] = {"RETROSTORE_PUBLIC_ORIGIN": "https://retrostore.org"}
    if config:
        app_config.update(config)
    public_origin = _public_origin(app_config["RETROSTORE_PUBLIC_ORIGIN"])
    mirror = load_catalog_mirror_archive(Path(archive_path))
    app_config.update(
        {
            "RETROSTORE_API_STORAGE": MirrorApiDataStore(
                mirror,
                screenshot_url=_screenshot_url_resolver(public_origin),
            ),
            "RETROSTORE_DOWNLOADS": _downloads(mirror),
            "RETROSTORE_PUBLIC_WEBSITE_APPS": _public_website_apps(mirror, public_origin),
            "RETROSTORE_SCREENSHOTS": _public_screenshots(mirror),
        }
    )
    return create_app(app_config)


def _screenshot_url_resolver(public_origin: str) -> Callable[[Any], str]:
    def resolve(screenshot: Any) -> str:
        return screenshot.legacy_serving_url or (
            f"{public_origin}/s/{quote(screenshot.id, safe='')}"
        )

    return resolve


def _public_origin(value: object) -> str:
    if not isinstance(value, str):
        raise RuntimeError("RetroStore public origin must be an absolute HTTP(S) URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("RetroStore public origin must be an absolute HTTP(S) origin")
    return f"{parsed.scheme}://{parsed.netloc}"


def _public_screenshots(mirror: CatalogMirror) -> Mapping[str, PublicScreenshot]:
    return {
        screenshot.id: PublicScreenshot(
            filename=screenshot.filename,
            content_type=screenshot.content_type or "application/octet-stream",
            sha256=screenshot.object.sha256,
            body=mirror.object_bytes[screenshot.object.path],
        )
        for screenshot in mirror.screenshots.values()
    }


def _downloads(mirror: CatalogMirror) -> Mapping[str, DownloadApp]:
    media_by_app: dict[str, list[DownloadMedia]] = {}
    for media in mirror.media.values():
        _validate_zip_filename(media.filename)
        media_by_app.setdefault(media.app_id, []).append(
            DownloadMedia(
                id=media.id,
                filename=media.filename,
                body=mirror.object_bytes[media.object.path],
            )
        )
    result = {}
    for app in mirror.apps:
        _download_filename(app.name)
        result[app.id] = DownloadApp(
            name=app.name,
            media=tuple(sorted(media_by_app.get(app.id, ()), key=_media_sort_key)),
        )
    return result


def _public_website_apps(
    mirror: CatalogMirror, public_origin: str
) -> tuple[dict[str, object], ...]:
    media_by_app: dict[str, list[str]] = {}
    for media in mirror.media.values():
        media_by_app.setdefault(media.app_id, []).append(media.filename)

    result: list[dict[str, object]] = []
    for app in mirror.apps:
        item: dict[str, object] = {
            "name": app.name,
            "version": app.version,
            "author": app.author_name if app.author_id is not None else "Unknown author",
            "description": app.description,
            "screenshots": [
                screenshot.legacy_serving_url
                or f"{public_origin}/s/{quote(screenshot.id, safe='')}"
                for screenshot_id in app.screenshot_ids
                for screenshot in (mirror.screenshots[screenshot_id],)
            ],
            "reportUrl": f"/reportapp?appId={app.id}",
            "downloadUrl": f"/downloadapp?appId={app.id}",
        }
        if any(filename.casefold().endswith(".dmk") for filename in media_by_app.get(app.id, ())):
            item["emulatorAppId"] = app.id
        result.append(item)
    return tuple(sorted(result, key=lambda item: str(item["name"])))


def _download_filename(app_name: str) -> str:
    value = app_name.replace(" ", "_").replace(".", "_").replace(",", "_")
    if not value or any(character in value for character in ('"', "\r", "\n")):
        raise ValueError("App name cannot be represented as a download filename")
    return value


def _validate_zip_filename(filename: str) -> None:
    parts = filename.split("/")
    if (
        not filename
        or filename.startswith("/")
        or "\\" in filename
        or "\0" in filename
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("Media filename is unsafe for a download archive")


def _media_sort_key(media: DownloadMedia) -> tuple[int, int | str]:
    try:
        return (0, int(media.id))
    except ValueError:
        return (1, media.id)
