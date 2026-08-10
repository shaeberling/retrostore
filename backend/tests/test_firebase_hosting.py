import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
FIREBASE_CONFIG = REPOSITORY_ROOT / "firebase.json"
FIREBASE_TARGETS = REPOSITORY_ROOT / ".firebaserc"


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_public_hosting_target_is_separate_from_existing_kmp_site() -> None:
    targets = _json(FIREBASE_TARGETS)["targets"]
    assert targets == {
        "trs-80": {
            "hosting": {"retrostore-public": ["retrostore-public"]},
        }
    }

    hosting = _public_hosting_config()
    assert hosting["target"] == "retrostore-public"
    assert hosting["public"] == "infra/public-site/dist"


def test_public_hosting_is_a_static_only_worker_origin() -> None:
    hosting = _public_hosting_config()
    assert "rewrites" not in hosting
    assert "redirects" not in hosting


def test_public_hosting_preserves_candidate_static_headers() -> None:
    headers = _public_hosting_config()["headers"]
    assert headers == [
        {
            "source": "**",
            "headers": [
                {"key": "Cache-Control", "value": "no-store"},
                {"key": "Access-Control-Allow-Origin", "value": "*"},
            ],
        }
    ]


def _public_hosting_config() -> dict[str, object]:
    hosting = _json(FIREBASE_CONFIG)["hosting"]
    return next(item for item in hosting if item["target"] == "retrostore-public")
