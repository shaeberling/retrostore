from types import MappingProxyType

from retrostore.admin.catalog import MirrorAdminCatalog
from retrostore.mirror import (
    CatalogMirror,
    NormalizedApp,
    NormalizedMedia,
    NormalizedScreenshot,
)
from retrostore.mirror.catalog import ObjectDescriptor


def _app(app_id: str, name: str, media_id: str | None = None) -> NormalizedApp:
    return NormalizedApp(
        id=app_id,
        name=name,
        version="1",
        description="",
        release_year=1980,
        platform="TRS80",
        model="MODEL_I",
        categories=(),
        author_id=None,
        author_name="",
        publisher_email="",
        first_published_at_ms=0,
        updated_at_ms=0,
        disk_media_ids=(media_id, None, None, None),
        cassette_media_id=None,
        command_media_id=None,
        basic_media_id=None,
        screenshot_ids=("shot-1",) if media_id else (),
    )


def test_mirror_admin_catalog_sorts_apps_and_projects_related_metadata() -> None:
    descriptor = ObjectDescriptor("objects/value", 1, "a" * 64)
    media = NormalizedMedia("media-1", "app-z", "DISK", "disk.dmk", "", 0, descriptor)
    screenshot = NormalizedScreenshot(
        "shot-1", "app-z", "screen.png", "image/png", 0, None, descriptor
    )
    mirror = CatalogMirror(
        source_project_id="trs-80",
        exported_at="2026-08-07T00:00:00Z",
        high_water_mark="2026-08-07T00:00:00Z",
        apps=(_app("app-z", "Zulu", "media-1"), _app("app-a", "alpha")),
        media=MappingProxyType({"media-1": media}),
        screenshots=MappingProxyType({"shot-1": screenshot}),
        object_bytes=MappingProxyType({"objects/value": b"x"}),
    )
    catalog = MirrorAdminCatalog(mirror)

    assert [app.id for app in catalog.list_apps()] == ["app-a", "app-z"]
    detail = catalog.get_app("app-z")
    assert detail is not None
    assert detail.media == (media,)
    assert detail.screenshots == (screenshot,)
    assert catalog.get_app("missing") is None
