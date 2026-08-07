"""Run real public clients over HTTP against the representative Flask candidate."""

import argparse
import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.serving import make_server

from services.api_compat.app import create_representative_app

TRS80_REVISION = "79a8e5869aa1de2bfd896182abdf09fb557a261b"
TRS80_CLIENT_FILES = {
    "shared/src/commonMain/kotlin/org/retrostore/RetrostoreClient.kt": (
        "97e3fc33179a4e2ad27216ebfcd02188db93c76b9462aa71ed748c93d3fd9f9c"
    ),
    "shared/src/commonMain/kotlin/org/retrostore/ApiException.kt": (
        "6b3f7955683a4a4559051286fede8ca97e495bdd01a88cca1752617048c544c5"
    ),
    "app/src/main/c/retrostore/backend.cpp": (
        "f75d6b0b901c6cf9d678ecdf2b0f85577e178983c029ff36ea919c6b1922f455"
    ),
    "app/src/main/c/retrostore/include/utils.h": (
        "cec9d86bd39a47ab20cb9bb947304ae932451f1626585ff2aa0cfa7a5528bb0b"
    ),
    "app/src/main/c/retrostore/ApiProtos.pb.c": (
        "a137df01f697587dd200d6e73ea2887bb9227f9e31f12e641df7cf36d80fdc05"
    ),
    "app/src/main/c/retrostore/include/ApiProtos.pb.h": (
        "68a443d7bdb8f9ec01fa2ffe742b16e4c6149cec85db379f3390d97b1087c5fb"
    ),
}


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


def run(checkout: Path) -> int:
    checkout = checkout.resolve()
    validate_trs80_client(checkout)

    backend_directory = Path(__file__).resolve().parents[2]
    repository_directory = backend_directory.parent
    server = make_server("127.0.0.1", 0, create_representative_app())
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    candidate_url = f"http://127.0.0.1:{server.server_port}"

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
    args = parser.parse_args()
    raise SystemExit(run(args.trs80_checkout))


if __name__ == "__main__":
    main()
