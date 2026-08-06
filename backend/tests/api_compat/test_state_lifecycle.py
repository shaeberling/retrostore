from retrostore.api_compat.service import CompatibilityApi
from retrostore.api_compat.storage import InMemoryCompatibilityStorage
from retrostore.generated import ApiProtos_pb2 as api_pb


def test_in_memory_state_round_trip_preserves_lengths_and_overlap_behavior() -> None:
    api = CompatibilityApi(InMemoryCompatibilityStorage())
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
    storage = InMemoryCompatibilityStorage(states={123: state})
    api = CompatibilityApi(storage)
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
