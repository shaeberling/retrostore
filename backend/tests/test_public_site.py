from datetime import UTC, datetime
from pathlib import Path

import pytest

from retrostore.public_site import build_public_site


def test_static_public_site_build_is_closed_and_rewrites_catalog_fetch(
    tmp_path: Path,
) -> None:
    output = tmp_path / "site"

    report = build_public_site(
        output, generated_at=datetime(2026, 8, 10, tzinfo=UTC)
    )

    assert report["production_changed"] is False
    assert report["result"]["file_count"] > 20
    assert report["result"]["missing_static_reference_count"] == 0
    apps = (output / "apps.html").read_text()
    assert '/public/apps.json' in apps
    assert '/rpc?m=pubapplist' not in apps
    assert '/public/lightbox2/' not in apps
    assert (output / "favicon/favicon-32x32.png").is_file()
    assert (output / "gfx/discord.svg").is_file()
    assert not (output / "contact.html").read_text().count("contact_me.js")


def test_static_public_site_build_is_create_only(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()

    with pytest.raises(FileExistsError):
        build_public_site(output)
