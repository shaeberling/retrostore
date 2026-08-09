import json
from types import SimpleNamespace

import pytest

from retrostore.admin import activate_catalog_snapshot


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.validated: list[dict[str, str]] = []
        self.activated: list[dict[str, str]] = []

    def validate_guarded_activation(self, **kwargs):
        self.validated.append(kwargs)
        return SimpleNamespace(**kwargs)

    def activate_guarded(self, **kwargs):
        self.activated.append(kwargs)
        return SimpleNamespace(**kwargs)


def _arguments(tmp_path):
    return [
        "--project",
        "project-test",
        "--database",
        "retrostore",
        "--bucket",
        "catalog-test",
        "--operation",
        "activate",
        "--candidate-snapshot-id",
        f"catalog-{'1' * 64}",
        "--candidate-manifest-sha256",
        "2" * 64,
        "--expected-active-snapshot-id",
        f"catalog-{'3' * 64}",
        "--expected-active-manifest-sha256",
        "4" * 64,
        "--actor",
        "operator@example.test",
        "--output",
        str(tmp_path / "activation.json"),
        "--impersonate-service-account",
        "retrostore-migrator@project-test.iam.gserviceaccount.com",
    ]


def _configure(monkeypatch):
    store = FakeSnapshotStore()
    monkeypatch.setattr(
        activate_catalog_snapshot,
        "gcloud_impersonated_credentials",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        activate_catalog_snapshot,
        "google_catalog_stores",
        lambda **kwargs: (object(), store),
    )
    return store


def test_catalog_activation_is_a_validating_zero_write_dry_run(
    tmp_path, monkeypatch
) -> None:
    store = _configure(monkeypatch)

    assert activate_catalog_snapshot.main(_arguments(tmp_path)) == 0

    assert len(store.validated) == 1
    assert store.activated == []
    report = json.loads((tmp_path / "activation.json").read_text())
    assert report["validated"] is True
    assert report["applied"] is False


def test_catalog_activation_requires_four_exact_apply_confirmations(
    tmp_path, monkeypatch
) -> None:
    store = _configure(monkeypatch)
    arguments = [*_arguments(tmp_path), "--apply"]

    with pytest.raises(ValueError, match="--confirm-project"):
        activate_catalog_snapshot.main(arguments)
    assert store.validated == []
    assert store.activated == []


def test_catalog_activation_applies_only_after_exact_confirmation(
    tmp_path, monkeypatch
) -> None:
    store = _configure(monkeypatch)
    arguments = [
        *_arguments(tmp_path),
        "--apply",
        "--confirm-project",
        "project-test",
        "--confirm-operation",
        "activate",
        "--confirm-candidate-snapshot-id",
        f"catalog-{'1' * 64}",
        "--confirm-expected-active-snapshot-id",
        f"catalog-{'3' * 64}",
    ]

    assert activate_catalog_snapshot.main(arguments) == 0

    assert len(store.validated) == 1
    assert len(store.activated) == 1
    assert store.activated[0]["actor"] == "operator@example.test"
    report = json.loads((tmp_path / "activation.json").read_text())
    assert report["applied"] is True
