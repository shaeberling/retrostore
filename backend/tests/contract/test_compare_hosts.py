from retrostore.contract.compare_hosts import compare_captures


def _capture(base_url: str, message: str) -> dict[str, object]:
    return {
        "base_url": base_url,
        "observations": [
            {
                "scenario": "scenario",
                "method": "getApp",
                "request_format": "protobuf",
                "status_code": 200,
                "content_type": "application/octet-stream",
                "access_control_allow_origin": "*",
                "body_length": len(message),
                "body_sha256": "not-used-for-protobuf",
                "body_base64": "",
                "semantic_body": {"message": message},
            }
        ],
    }


def test_compare_captures_reports_matching_semantic_responses() -> None:
    report = compare_captures(_capture("https://old", "same"), _capture("https://new", "same"))

    assert report["summary"] == {"total": 1, "matching": 1, "different": 0}
    assert report["results"] == [{"scenario": "scenario", "differences": {}}]


def test_compare_captures_reports_differences() -> None:
    report = compare_captures(
        _capture("https://old", "old"), _capture("https://new", "different")
    )

    assert report["summary"] == {"total": 1, "matching": 0, "different": 1}
    assert set(report["results"][0]["differences"]) == {"body_length", "semantic_body"}
