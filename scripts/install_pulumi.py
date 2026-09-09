"""Install the pinned official CLI archive after verifying its published SHA256."""

import argparse
import hashlib
import platform
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.261.0"


def install(directory: Path) -> None:
    operating_system = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(
        platform.system()
    )
    architecture = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(
        platform.machine()
    )
    if not operating_system or not architecture:
        raise SystemExit("Unsupported operating system or architecture")
    suffix = "zip" if operating_system == "windows" else "tar.gz"
    filename = f"pulumi-v{VERSION}-{operating_system}-{architecture}.{suffix}"
    base_url = "https://get.pulumi.com/releases/sdk/"
    with urllib.request.urlopen(f"{base_url}pulumi-{VERSION}-checksums.txt", timeout=30) as source:
        checksums = source.read().decode()
    expected = next(
        line.split()[0]
        for line in checksums.splitlines()
        if line.split()[-1].lstrip("*") == filename
    )
    with tempfile.TemporaryDirectory(prefix="olixops-pulumi-install-") as temporary:
        archive = Path(temporary) / filename
        with urllib.request.urlopen(base_url + filename, timeout=120) as source:
            with archive.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
        with archive.open("rb") as downloaded:
            actual = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if actual != expected:
            raise SystemExit("Pulumi archive checksum mismatch")
        directory.mkdir(parents=True, exist_ok=True)
        if suffix == "zip":
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(directory)
        else:
            with tarfile.open(archive) as tar:
                tar.extractall(directory, filter="data")
    print(f"Installed verified Pulumi {VERSION} in {directory / 'pulumi'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("runtime/tools"))
    install(parser.parse_args().directory)
