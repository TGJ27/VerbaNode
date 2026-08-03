from __future__ import annotations

import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models" / "kokoro"
ARCHIVE_NAME = "kokoro-int8-multi-lang-v1_1.tar.bz2"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{ARCHIVE_NAME}"
EXPECTED_DIR = "kokoro-int8-multi-lang-v1_1"
DESTINATION = MODELS_DIR / EXPECTED_DIR


def report(block_count: int, block_size: int, total_size: int) -> None:
    downloaded = min(block_count * block_size, total_size)
    if total_size > 0:
        percent = downloaded * 100 / total_size
        print(f"\rDownloading Kokoro: {percent:5.1f}%", end="", flush=True)


def safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if destination not in target.parents and target != destination:
            raise RuntimeError(f"Unsafe archive entry: {member.name}")
    archive.extractall(destination)


def main() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if (DESTINATION / "model.int8.onnx").exists() and (DESTINATION / "voices.bin").exists():
        print(f"Kokoro is already installed at {DESTINATION}")
        return
    with tempfile.TemporaryDirectory() as temp_name:
        temp = Path(temp_name)
        archive_path = temp / ARCHIVE_NAME
        print(f"Downloading official sherpa-onnx model:\n{URL}")
        urllib.request.urlretrieve(URL, archive_path, reporthook=report)
        print("\nExtracting model…")
        with tarfile.open(archive_path, "r:bz2") as archive:
            safe_extract(archive, temp)
        extracted = temp / EXPECTED_DIR
        if not extracted.exists():
            candidates = [path for path in temp.iterdir() if path.is_dir()]
            if len(candidates) != 1:
                raise RuntimeError("Could not identify the extracted model directory")
            extracted = candidates[0]
        if DESTINATION.exists():
            shutil.rmtree(DESTINATION)
        shutil.move(str(extracted), str(DESTINATION))
    print(f"Kokoro installed at: {DESTINATION}")
    print("Restart VerbaNode if it is currently running.")


if __name__ == "__main__":
    main()
