import hashlib
import json
from pathlib import Path

from retrostore.migration.catalog_mirror import CatalogMirror, load_catalog_mirror_archive
from retrostore.migration.catalog_mirror.plan_legacy_reverse_sync import (
    build_legacy_reverse_plan,
    main,
)
from tests.migration.catalog_mirror.test_archive import _write_archive
from tests.migration.catalog_mirror.test_catalog import _manifest, _reader, _reconciliation


def test_cli_builds_a_deterministic_value_free_reverse_plan(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.zip"
    candidate_path = tmp_path / "candidate.zip"
    output = tmp_path / "plan.json"
    _write_archive(baseline_path)
    manifest = _manifest()
    manifest["apps"][0]["name"] = "Private changed title"  # type: ignore[index]
    _write_archive(candidate_path, manifest=manifest)

    assert (
        main(
            [
                "--baseline-archive",
                str(baseline_path),
                "--candidate-archive",
                str(candidate_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    plan = json.loads(output.read_text())
    assert plan["read_only"] is True
    assert plan["apply_available"] is False
    assert plan["legacy_operations"]["apps"]["upsert_ids"] == ["app-1"]
    assert plan["legacy_operations"]["search"]["upsert_document_ids"] == ["app-1"]
    assert plan["blockers_before_apply_can_exist"] == ["legacy_importer_is_not_enabled"]
    assert "Private changed title" not in output.read_text()
    assert "publisher@example.test" not in output.read_text()
    digest = plan.pop("plan_sha256")
    canonical = json.dumps(plan, separators=(",", ":"), sort_keys=True).encode()
    assert digest == hashlib.sha256(canonical).hexdigest()


def test_plan_identifies_legacy_numeric_author_allocation_requirement(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.zip"
    _write_archive(baseline_path)
    baseline = load_catalog_mirror_archive(baseline_path)
    manifest = _manifest()
    manifest["apps"][0]["author_id"] = "author-uuid"  # type: ignore[index]
    manifest["reconciliation"] = _reconciliation(dict(_reader().objects))
    candidate = CatalogMirror.from_dict(manifest, _reader())

    plan = build_legacy_reverse_plan(
        baseline,
        candidate,
        baseline_archive_sha256="1" * 64,
        candidate_archive_sha256="2" * 64,
    )

    assert plan["legacy_requirements"]["author_ids_requiring_allocation"] == ["author-uuid"]
    assert "legacy_author_id_allocation_map_required" in plan["blockers_before_apply_can_exist"]
