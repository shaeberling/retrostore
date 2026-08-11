"""Request-driven API and website projections of the catalog."""

from collections.abc import Callable, Mapping, Sequence
from urllib.parse import quote

from retrostore.api.storage import (
    CatalogEntry,
    DownloadApp,
    DownloadMedia,
    MediaSlot,
    PublicScreenshot,
    StateStorage,
)
from retrostore.catalog import (
    CatalogApp,
    CatalogScreenshot,
    CloudObjectReader,
    FirestoreCatalogRepository,
    ObjectMetadata,
)
from retrostore.generated import ApiProtos_pb2 as api_pb

_MEDIA_TYPES = {
    "DISK": api_pb.DISK,
    "CASSETTE": api_pb.CASSETTE,
    "COMMAND": api_pb.COMMAND,
    "BASIC": api_pb.BASIC,
}
_MODELS = {
    "UNKNOWN_MODEL": api_pb.UNKNOWN_MODEL,
    "MODEL_I": api_pb.MODEL_I,
    "MODEL_III": api_pb.MODEL_III,
    "MODEL_4": api_pb.MODEL_4,
    "MODEL_4P": api_pb.MODEL_4P,
}


class GoogleCloudApiDataStore:
    """Serve catalog metadata and lazily read only requested binary objects."""

    def __init__(
        self,
        repository: FirestoreCatalogRepository,
        object_reader: CloudObjectReader,
        state_storage: StateStorage,
        *,
        public_origin: str,
    ) -> None:
        self._repository = repository
        self._object_reader = object_reader
        self._state_storage = state_storage
        self._public_origin = public_origin.rstrip("/")

    def get_catalog_entry(self, app_id: str) -> CatalogEntry | None:
        app = self._repository.get_app(app_id)
        if app is None:
            return None
        screenshots = self._repository.get_screenshots(app.screenshot_ids, app_id=app.id)
        return self._catalog_entry(app, screenshots)

    def list_catalog_entries(self) -> Sequence[CatalogEntry]:
        apps = self._repository.list_apps()
        screenshots = self._repository.list_screenshots()
        return tuple(self._catalog_entry(app, screenshots) for app in apps)

    def search_app_ids(self, query: str) -> set[str]:
        needle = query.casefold()
        return {
            app.id
            for app in self._repository.list_apps()
            if needle in app.name.casefold() or needle in app.description.casefold()
        }

    def get_media_slots(self, app_id: str) -> Sequence[MediaSlot] | None:
        app = self._repository.get_app(app_id)
        if app is None:
            return None
        media_ids = tuple(media_id for _, media_id in app.media_slots() if media_id is not None)
        media = self._repository.get_media(media_ids, app_id=app.id)
        result = []
        for media_type_name, media_id in app.media_slots():
            media_type = _MEDIA_TYPES[media_type_name]
            image = api_pb.MediaImage()
            if media_id is None:
                result.append(MediaSlot(media_type, image))
                continue
            value = media[media_id]
            if _MEDIA_TYPES[value.media_type] != media_type:
                raise ValueError("Catalog media is referenced from the wrong slot")
            image.type = media_type
            image.filename = value.filename
            image.uploadTime = value.upload_time_ms
            image.description = value.description
            result.append(
                MediaSlot(
                    media_type,
                    image,
                    size=value.object.size,
                    body_reader=self._reader(value.object),
                )
            )
        return tuple(result)

    def save_state(self, state: api_pb.SystemState) -> int:
        return self._state_storage.save_state(state)

    def get_state(self, token: int) -> api_pb.SystemState | None:
        return self._state_storage.get_state(token)

    def get_screenshot(self, screenshot_id: str) -> PublicScreenshot | None:
        value = self._repository.get_screenshot(screenshot_id)
        if value is None:
            return None
        app = self._repository.get_app(value.app_id)
        if app is None or screenshot_id not in app.screenshot_ids:
            return None
        return PublicScreenshot(
            filename=value.filename,
            content_type=value.content_type,
            sha256=value.object.sha256,
            body_reader=self._reader(value.object),
        )

    def get_download(self, app_id: str) -> DownloadApp | None:
        app = self._repository.get_app(app_id)
        if app is None:
            return None
        media_ids = tuple(media_id for _, media_id in app.media_slots() if media_id is not None)
        media = self._repository.get_media(media_ids, app_id=app.id)
        values = tuple(
            DownloadMedia(
                id=item.id,
                filename=item.filename,
                body_reader=self._reader(item.object),
            )
            for item in sorted(media.values(), key=lambda item: _media_sort_key(item.id))
        )
        return DownloadApp(name=app.name, media=values)

    def list_website_apps(self) -> Sequence[Mapping[str, object]]:
        apps = self._repository.list_apps()
        screenshots = self._repository.list_screenshots()
        media = self._repository.list_media()
        media_by_app: dict[str, list[str]] = {}
        for value in media.values():
            media_by_app.setdefault(value.app_id, []).append(value.filename)

        result = []
        for app in apps:
            item: dict[str, object] = {
                "name": app.name,
                "version": app.version,
                "author": app.author_name if app.author_id is not None else "Unknown author",
                "description": app.description,
                "screenshots": [
                    self._screenshot_url(screenshots[screenshot_id])
                    for screenshot_id in app.screenshot_ids
                ],
                "reportUrl": f"/reportapp?appId={app.id}",
                "downloadUrl": f"/downloadapp?appId={app.id}",
            }
            if any(
                filename.casefold().endswith(".dmk") for filename in media_by_app.get(app.id, ())
            ):
                item["emulatorAppId"] = app.id
            result.append(item)
        return tuple(sorted(result, key=lambda item: str(item["name"])))

    def _catalog_entry(
        self,
        app: CatalogApp,
        screenshots: Mapping[str, CatalogScreenshot],
    ) -> CatalogEntry:
        proto = api_pb.App(
            id=app.id,
            name=app.name,
            version=app.version,
            description=app.description,
            release_year=app.release_year,
            author=app.author_name,
        )
        proto.ext_trs80.model = _MODELS[app.model]
        proto.screenshot_url.extend(
            self._screenshot_url(screenshots[screenshot_id]) for screenshot_id in app.screenshot_ids
        )
        media_types = frozenset(
            _MEDIA_TYPES[media_type]
            for media_type, media_id in app.media_slots()
            if media_id is not None
        )
        return CatalogEntry(proto, media_types)

    def _screenshot_url(self, screenshot: CatalogScreenshot) -> str:
        return screenshot.legacy_serving_url or (
            f"{self._public_origin}/s/{quote(screenshot.id, safe='')}"
        )

    def _reader(self, descriptor: ObjectMetadata) -> Callable[[int, int | None], bytes]:
        return lambda start, length: self._object_reader.read(
            descriptor, start=start, length=length
        )


def _media_sort_key(media_id: str) -> tuple[int, int | str]:
    try:
        return (0, int(media_id))
    except ValueError:
        return (1, media_id)
