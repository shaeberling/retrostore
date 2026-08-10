"""Run real public clients over HTTP against the representative Flask candidate."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.serving import make_server

from retrostore.contracts import PUBLIC_API_METHODS
from services.api_compat.app import create_representative_app

TRS80_REVISION = "aecbddcc7f5515fb844bb7a1fc350d8ffaaf5ce5"
TRS80_KMP_METHODS = frozenset(
    {"getApp", "listApps", "fetchMediaImages", "uploadState", "downloadState"}
)
TRS80_EMBEDDED_C_METHODS = frozenset({"getApp", "listApps", "fetchMediaImages"})
TRS80_CLIENT_FILES = {
    "shared/src/commonMain/kotlin/org/retrostore/RetrostoreClient.kt": (
        "97e3fc33179a4e2ad27216ebfcd02188db93c76b9462aa71ed748c93d3fd9f9c"
    ),
    "shared/src/commonMain/kotlin/org/retrostore/ApiException.kt": (
        "6b3f7955683a4a4559051286fede8ca97e495bdd01a88cca1752617048c544c5"
    ),
    "shared/src/commonMain/proto/org/retrostore/client/common/proto/ApiProtos.proto": (
        "d8921090ba2851ab1c102a447aa60066695bdf43c4d5808ff31cd090d7f5c70d"
    ),
    "shared/src/commonMain/kotlin/org/puder/trs80/shared/io/HttpGet.kt": (
        "8127ebd5e5cb246c6beb2c363899873f2f7e45ae8e3d142ea8818043bcb3b975"
    ),
    "shared/src/commonMain/kotlin/org/puder/trs80/shared/store/RetroStore.kt": (
        "edb83ad16ae1d2fcc5207031c25de5d250003cbc2821b21642c3edfcd7c4f019"
    ),
    "shared/src/androidMain/kotlin/org/puder/trs80/shared/io/HttpGet.android.kt": (
        "39aa6e16c7168efcc713a7f1609df6cb229737bdeae86f4ac680dca7a62bfabd"
    ),
    "shared/src/iosMain/kotlin/org/puder/trs80/shared/io/HttpGet.ios.kt": (
        "e0388a49734804358ba68aa5722d716da15bb2c66c6d85f181283579042b380b"
    ),
    "shared/src/wasmJsMain/kotlin/org/puder/trs80/shared/io/HttpGet.wasmJs.kt": (
        "0a479e0d2194a6cb238a7b0e1b3fe4b8c46792fc491bf5aafeffbcfb1284dd1c"
    ),
    "app/src/main/c/retrostore/backend.cpp": (
        "f75d6b0b901c6cf9d678ecdf2b0f85577e178983c029ff36ea919c6b1922f455"
    ),
    "app/src/main/c/retrostore/include/utils.h": (
        "cec9d86bd39a47ab20cb9bb947304ae932451f1626585ff2aa0cfa7a5528bb0b"
    ),
    "app/src/main/c/retrostore/include/retrostore.h": (
        "95187f7e476a2ec3624b9d04bfd16023f5c7c5b40ecfd590cd844ce56fe946e5"
    ),
    "app/src/main/c/retrostore/include/defs.h": (
        "5f5d9d6e688e27b21d66be081f3806862fcb8364ab69ede3cb28163e1263a297"
    ),
    "app/src/main/c/retrostore/ApiProtos.pb.c": (
        "a137df01f697587dd200d6e73ea2887bb9227f9e31f12e641df7cf36d80fdc05"
    ),
    "app/src/main/c/retrostore/include/ApiProtos.pb.h": (
        "68a443d7bdb8f9ec01fa2ffe742b16e4c6149cec85db379f3390d97b1087c5fb"
    ),
    "app/src/main/c/retrostore/pb_common.cpp": (
        "6aea3a943f2666460bc649331e2115b00c929b3781ce60e66ee224d9681880b1"
    ),
    "app/src/main/c/retrostore/pb_decode.cpp": (
        "5feece706eb0436d1b17b54a6dc2a5bfb386b6e7a66f99cd86170a1c1a6e4fe7"
    ),
    "app/src/main/c/retrostore/cJSON.cpp": (
        "b72bade720884d04ba9373d5aff6e1510f64dbeb0eba21ad8c9e1e5116c3517a"
    ),
    "app/src/main/c/retrostore/include/backend.h": (
        "a66fdab0ec17525c0eb31f3d40ded66f63a396b1fcf7f519bb72d402eb4cd040"
    ),
    "app/src/main/c/retrostore/include/pb.h": (
        "2af2a74a759bea16836988701aeedde5c7d25b309cae4e385a3d8f374e2aba12"
    ),
    "app/src/main/c/retrostore/include/pb_common.h": (
        "3ed0e7518cd2c604f2631f38ba8d3119daaeeb3c5b39cb6db968ca54032d7541"
    ),
    "app/src/main/c/retrostore/include/pb_decode.h": (
        "212da3877a0b3926d3170c0495b3ae840699187932b273db57126c631d9e55fe"
    ),
    "app/src/main/c/retrostore/include/cJSON.h": (
        "9ac55e0231128972c5713d63fff408bb9c98d187d44c21cb0581cbbd4c746d23"
    ),
}


def validate_trs80_revision(
    checkout: Path, expected_revision: str = TRS80_REVISION
) -> None:
    """Require the exact application revision reviewed for this compatibility gate."""

    completed = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    actual_revision = completed.stdout.strip()
    if completed.returncode or actual_revision != expected_revision:
        detail = actual_revision or completed.stderr.strip() or "unknown revision"
        raise ValueError(
            f"TRS-80 checkout must be reviewed revision {expected_revision}, found {detail}"
        )


def validate_trs80_client(
    checkout: Path, expected_files: Mapping[str, str] = TRS80_CLIENT_FILES
) -> None:
    """Reject a checkout whose consumer source differs from the reviewed revision."""

    failures: list[str] = []
    for name, expected_digest in expected_files.items():
        path = checkout / name
        if not path.is_file():
            failures.append(f"{path}: missing")
            continue
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            failures.append(f"{path}: expected {expected_digest}, found {actual_digest}")
    if failures:
        joined = "\n".join(failures)
        raise ValueError(
            f"TRS-80 client source does not match reviewed revision {TRS80_REVISION}:\n{joined}"
        )


def run_embedded_c_client(checkout: Path, candidate_url: str, build_directory: Path) -> int:
    """Compile the reviewed embedded client with only its socket transport replaced."""

    compiler = shutil.which("c++")
    c_compiler = shutil.which("cc")
    if compiler is None or c_compiler is None:
        raise RuntimeError("C and C++ compilers are required for embedded client tests")

    endpoint = urlsplit(candidate_url)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port is None:
        raise ValueError("The embedded client test requires an HTTP loopback candidate URL")

    repository_directory = Path(__file__).resolve().parents[3]
    fixture_directory = repository_directory / "backend/consumer-tests/c-client"
    source_directory = checkout / "app/src/main/c/retrostore"
    executable = build_directory / "embedded-client-test"
    generated_proto_object = build_directory / "ApiProtos.pb.o"
    c_compile_result = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-O2",
            "-DPB_NO_PACKED_STRUCTS",
            "-I",
            str(source_directory / "include"),
            "-c",
            str(source_directory / "ApiProtos.pb.c"),
            "-o",
            str(generated_proto_object),
        ],
        cwd=repository_directory,
        check=False,
    )
    if c_compile_result.returncode:
        return c_compile_result.returncode

    compile_result = subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-O2",
            "-DPB_NO_PACKED_STRUCTS",
            "-I",
            str(source_directory / "include"),
            str(fixture_directory / "embedded_client_test.cpp"),
            str(fixture_directory / "loopback_transport.cpp"),
            str(source_directory / "backend.cpp"),
            str(source_directory / "pb_common.cpp"),
            str(source_directory / "pb_decode.cpp"),
            str(source_directory / "cJSON.cpp"),
            str(generated_proto_object),
            "-o",
            str(executable),
        ],
        cwd=repository_directory,
        check=False,
    )
    if compile_result.returncode:
        return compile_result.returncode

    environment = os.environ.copy()
    environment["RETROSTORE_CANDIDATE_PORT"] = str(endpoint.port)
    completed = subprocess.run(
        [str(executable)],
        cwd=repository_directory,
        env=environment,
        check=False,
    )
    return completed.returncode


def validate_loopback_candidate_url(candidate_url: str) -> str:
    endpoint = urlsplit(candidate_url)
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or endpoint.port is None
        or endpoint.username is not None
        or endpoint.password is not None
        or endpoint.path not in {"", "/"}
        or endpoint.query
        or endpoint.fragment
    ):
        raise ValueError("External client tests require an HTTP 127.0.0.1 proxy origin")
    return f"http://127.0.0.1:{endpoint.port}"


def run(checkout: Path, candidate_url: str | None = None) -> int:
    checkout = checkout.resolve()
    validate_trs80_revision(checkout)
    validate_trs80_client(checkout)

    backend_directory = Path(__file__).resolve().parents[2]
    repository_directory = backend_directory.parent
    server = None
    server_thread = None
    if candidate_url is None:
        server = make_server("127.0.0.1", 0, create_representative_app())
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        candidate_url = f"http://127.0.0.1:{server.server_port}"
    else:
        candidate_url = validate_loopback_candidate_url(candidate_url)

    try:
        with tempfile.TemporaryDirectory(prefix="retrostore-c-client-") as temporary_directory:
            c_result = run_embedded_c_client(
                checkout,
                candidate_url,
                Path(temporary_directory),
            )
        if c_result:
            return c_result

        completed = subprocess.run(
            [
                str(repository_directory / "gradlew"),
                "--no-daemon",
                "--console=plain",
                "-p",
                str(backend_directory / "consumer-tests"),
                "clean",
                "test",
                f"-PcandidateUrl={candidate_url}",
                f"-Ptrs80Checkout={checkout}",
            ],
            cwd=repository_directory,
            check=False,
        )
        return completed.returncode
    finally:
        if server is not None and server_thread is not None:
            server.shutdown()
            server_thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--trs80-checkout",
        type=Path,
        required=True,
        help=f"TRS-80 checkout at reviewed revision {TRS80_REVISION}",
    )
    parser.add_argument("--candidate-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-candidate-url")
    args = parser.parse_args()
    external = args.candidate_url is not None
    if external:
        candidate_url = validate_loopback_candidate_url(args.candidate_url)
        if not args.apply or args.confirm_candidate_url != candidate_url:
            raise ValueError(
                "External client tests require --apply and the exact loopback "
                "--confirm-candidate-url"
            )
        if args.output is None:
            raise ValueError("External client tests require --output")
    elif args.apply or args.confirm_candidate_url is not None or args.output is not None:
        raise ValueError("External-only options require --candidate-url")

    result = run(args.trs80_checkout, args.candidate_url)
    if external:
        report = {
            "schema_version": 1,
            "operation": "deployed_private_consumer_client_gate",
            "applied": True,
            "candidate_transport": "authenticated_loopback_proxy",
            "reviewed_trs80_revision": TRS80_REVISION,
            "clients": {
                "published_jvm_sdk_methods": sorted(PUBLIC_API_METHODS),
                "trs80_kmp_methods": sorted(TRS80_KMP_METHODS),
                "trs80_embedded_c_methods": sorted(TRS80_EMBEDDED_C_METHODS),
            },
            "result": {"passes": result == 0},
            "safety": {
                "contains_state_tokens": False,
                "contains_response_payloads": False,
                "contains_credentials": False,
                "synthetic_state_only": True,
                "production_host_rejected": True,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    raise SystemExit(result)


if __name__ == "__main__":
    main()
