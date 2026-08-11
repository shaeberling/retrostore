"""Read-only administration projection of the validated catalog mirror."""

from dataclasses import dataclass
from typing import Protocol

from retrostore.canonical_catalog import CanonicalCatalogRepository
from retrostore.mirror import (
    CatalogMirror,
    NormalizedApp,
    NormalizedMedia,
    NormalizedScreenshot,
)


@dataclass(frozen=True, slots=True)
class AdminCatalogDetail:
    app: NormalizedApp
    media: tuple[NormalizedMedia, ...]
    screenshots: tuple[NormalizedScreenshot, ...]


class AdminCatalog(Protocol):
    def list_apps(self) -> tuple[NormalizedApp, ...]: ...

    def get_app(self, app_id: str) -> AdminCatalogDetail | None: ...


class MirrorAdminCatalog:
    """Expose normalized metadata without adding an independent storage model."""

    def __init__(self, mirror: CatalogMirror) -> None:
        self._apps = {app.id: app for app in mirror.apps}
        self._media = mirror.media
        self._screenshots = mirror.screenshots

    def list_apps(self) -> tuple[NormalizedApp, ...]:
        return tuple(
            sorted(
                self._apps.values(),
                key=lambda app: (app.name.casefold(), app.id),
            )
        )

    def get_app(self, app_id: str) -> AdminCatalogDetail | None:
        app = self._apps.get(app_id)
        if app is None:
            return None
        media = tuple(
            self._media[media_id]
            for _, media_id in app.media_slot_ids()
            if media_id is not None
        )
        screenshots = tuple(self._screenshots[item_id] for item_id in app.screenshot_ids)
        return AdminCatalogDetail(app=app, media=media, screenshots=screenshots)


class FirestoreAdminCatalog:
    """Read published applications directly from the canonical collections."""

    def __init__(self, repository: CanonicalCatalogRepository) -> None:
        self._repository = repository

    def list_apps(self) -> tuple[NormalizedApp, ...]:
        return tuple(
            sorted(
                self._repository.list_apps(),
                key=lambda app: (app.name.casefold(), app.id),
            )
        )

    def get_app(self, app_id: str) -> AdminCatalogDetail | None:
        app = self._repository.get_app(app_id)
        if app is None:
            return None
        media_ids = tuple(
            media_id for _, media_id in app.media_slot_ids() if media_id is not None
        )
        media = self._repository.get_media(media_ids, app_id=app.id)
        screenshots = self._repository.get_screenshots(
            app.screenshot_ids, app_id=app.id
        )
        return AdminCatalogDetail(
            app=app,
            media=tuple(media[media_id] for media_id in media_ids),
            screenshots=tuple(
                screenshots[screenshot_id] for screenshot_id in app.screenshot_ids
            ),
        )
