from retrostore.contracts import PUBLIC_API_METHODS, ResponseKind


def test_public_api_registry_is_frozen_to_nine_methods() -> None:
    assert tuple(PUBLIC_API_METHODS) == (
        "getApp",
        "listApps",
        "listAppsNano",
        "fetchMediaImages",
        "fetchMediaImageRefs",
        "fetchMediaImageRegion",
        "uploadState",
        "downloadState",
        "downloadStateMemoryRegion",
    )


def test_only_the_three_legacy_methods_accept_json() -> None:
    assert {
        name for name, contract in PUBLIC_API_METHODS.items() if contract.accepts_legacy_json
    } == {"getApp", "listApps", "fetchMediaImages"}


def test_raw_byte_methods_are_explicit() -> None:
    assert {
        name
        for name, contract in PUBLIC_API_METHODS.items()
        if contract.response_kind == ResponseKind.RAW_BYTES
    } == {"fetchMediaImageRegion", "downloadStateMemoryRegion"}


def test_upload_state_is_the_only_state_changing_method() -> None:
    assert {name for name, contract in PUBLIC_API_METHODS.items() if contract.writes_state} == {
        "uploadState"
    }
