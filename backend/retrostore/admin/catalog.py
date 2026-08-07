"""Read-only administration projection of the validated catalog mirror."""

from dataclasses import dataclass
from typing import Protocol

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
