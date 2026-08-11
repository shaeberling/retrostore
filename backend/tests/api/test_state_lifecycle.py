from concurrent.futures import ThreadPoolExecutor

import pytest

from retrostore.api.service import RetroStoreApi
from retrostore.api.storage import InMemoryApiDataStore
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_in_memory_state_round_trip_preserves_lengths_and_overlap_behavior() -> None:
    api = RetroStoreApi(InMemoryApiDataStore())
    upload = api_pb.UploadSystemStateParams()
    upload.state.model = api_pb.MODEL_I
    upload.state.registers.pc = 0x1234
    upload.state.memoryRegions.add(start=100, length=99, data=b"abcd")
    upload.state.memoryRegions.add(start=102, length=99, data=b"XY")

    upload_response = api_pb.ApiResponseUploadSystemState.FromString(
        api.upload_state(upload.SerializeToString()).data
    )
    assert upload_response.success is True
    assert upload_response.token == 100

    download = api_pb.DownloadSystemStateParams(token=upload_response.token)
    download_response = api_pb.ApiResponseDownloadSystemState.FromString(
        api.download_state(download.SerializeToString()).data
    )
    assert download_response.success is True
    assert download_response.systemState.registers.pc == 0x1234
    assert [region.length for region in download_response.systemState.memoryRegions] == [4, 2]
    assert [region.data for region in download_response.systemState.memoryRegions] == [
        b"abcd",
        b"XY",
    ]

    region = api_pb.DownloadSystemStateMemoryRegionParams(
        token=upload_response.token,
        start=100,
        length=4,
    )
    assert api.download_state_memory_region(region.SerializeToString()).data == b"abXY"


def test_download_can_exclude_state_memory_bytes_without_losing_lengths() -> None:
    state = api_pb.SystemState()
    state.memoryRegions.add(start=100, length=3, data=b"abc")
    storage = InMemoryApiDataStore(states={123: state})
    api = RetroStoreApi(storage)
    request = api_pb.DownloadSystemStateParams(
        token=123,
        exclude_memory_region_data=True,
    )

    response = api_pb.ApiResponseDownloadSystemState.FromString(
        api.download_state(request.SerializeToString()).data
    )

    assert response.success is True
    assert response.systemState.memoryRegions[0].length == 3
    assert response.systemState.memoryRegions[0].data == b""


def test_memory_region_download_zero_fills_gaps_and_applies_later_overlaps() -> None:
    state = api_pb.SystemState(model=api_pb.MODEL_III)
    state.memoryRegions.add(start=100, length=999, data=b"abcd")
    state.memoryRegions.add(start=102, length=-1, data=b"XY")
    state.memoryRegions.add(start=107, length=1, data=b"z")
    api = RetroStoreApi(InMemoryApiDataStore(states={321: state}))
    request = api_pb.DownloadSystemStateMemoryRegionParams(token=321, start=99, length=10)

    response = api.download_state_memory_region(request.SerializeToString())

    assert response.data == b"\x00abXY\x00\x00\x00z\x00"


@pytest.mark.parametrize(
    ("start", "length", "data", "success"),
    (
        (999_999, 999_999, b"", True),
        (0, -1, b"", True),
        (1_000_000, 0, b"", False),
        (-1, 0, b"", False),
        (0, 1_000_000, b"", False),
        (0, 0, b"x" * 1_000_000, False),
    ),
)
def test_upload_state_matches_legacy_region_validation_boundaries(
    start: int,
    length: int,
    data: bytes,
    success: bool,
) -> None:
    api = RetroStoreApi(InMemoryApiDataStore())
    request = api_pb.UploadSystemStateParams()
    request.state.memoryRegions.add(start=start, length=length, data=data)

    response = api_pb.ApiResponseUploadSystemState.FromString(
        api.upload_state(request.SerializeToString()).data
    )

    assert response.success is success
    assert (response.token > 0) is success


def test_upload_state_accepts_aggregate_larger_than_one_firestore_document() -> None:
    data = b"x" * 999_999
    request = api_pb.UploadSystemStateParams()
    request.state.memoryRegions.add(start=0, length=len(data), data=data)
    request.state.memoryRegions.add(start=1, length=len(data), data=data)
    serialized = request.SerializeToString()
    assert len(serialized) == 2_000_028
    assert len(serialized) > 1_048_576

    api = RetroStoreApi(InMemoryApiDataStore())
    response = api_pb.ApiResponseUploadSystemState.FromString(api.upload_state(serialized).data)

    assert response.success is True
    assert response.token > 0


def test_state_storage_allocates_unique_legacy_range_tokens_under_concurrency() -> None:
    storage = InMemoryApiDataStore(
        states={100: api_pb.SystemState(), 102: api_pb.SystemState()},
        first_state_token=100,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        tokens = list(executor.map(storage.save_state, [api_pb.SystemState()] * 50))

    assert len(set(tokens)) == 50
    assert 100 not in tokens
    assert 102 not in tokens
    assert all(100 <= token <= 999 for token in tokens)


def test_state_storage_wraps_and_fails_when_all_legacy_tokens_are_occupied() -> None:
    state = api_pb.SystemState()
    storage = InMemoryApiDataStore(
        states={token: state for token in range(100, 999)},
        first_state_token=999,
    )

    assert storage.save_state(state) == 999
    with pytest.raises(RuntimeError, match="No state token is available"):
        storage.save_state(state)


def test_state_storage_clones_inputs_and_results() -> None:
    state = api_pb.SystemState(model=api_pb.MODEL_I)
    state.memoryRegions.add(start=100, data=b"original")
    storage = InMemoryApiDataStore()

    token = storage.save_state(state)
    state.memoryRegions[0].data = b"mutated input"
    first_read = storage.get_state(token)
    assert first_read is not None
    assert first_read.memoryRegions[0].data == b"original"

    first_read.memoryRegions[0].data = b"mutated result"
    second_read = storage.get_state(token)
    assert second_read is not None
    assert second_read.memoryRegions[0].data == b"original"
