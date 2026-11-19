from __future__ import annotations
import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path
from .config import resolve_paths


def check_environment() -> list[tuple[str, str]]:
    rows = [("Python", sys.version.split()[0])]
    for package in ("yt-dlp", "yt-dlp-ejs", "gradio", "faster-whisper", "av", "openai"):
        try:
            rows.append((package, importlib.metadata.version(package)))
        except importlib.metadata.PackageNotFoundError:
            rows.append((package, "MISSING"))
    for binary in ("ffmpeg", "ffprobe", "deno"):
        exe = shutil.which(binary)
        if not exe:
            rows.append((binary, "MISSING"))
        else:
            try:
                result = subprocess.run([binary, "--version"], text=True, capture_output=True, timeout=15)
                rows.append((binary, result.stdout.splitlines()[0] if result.stdout else exe))
            except Exception:
                rows.append((binary, exe))
    try:
        import ctranslate2
        rows.append(("CUDA devices", str(ctranslate2.get_cuda_device_count())))
    except Exception as ex:
        rows.append(("CUDA devices", "unknown: " + str(ex)[:90]))
    root, scratch = resolve_paths()
    rows.extend([("ROOT", str(root)), ("SCRATCH", str(scratch))])
    return rows


def main():
    for name, status in check_environment():
        print(f"{name:17} {status}")
    try:
        import av
        fw = importlib.metadata.version("faster-whisper")
        if fw == "1.2.1" and int(av.__version__.split(".")[0]) >= 19:
            print("ERROR: faster-whisper 1.2.1 incompatible with av>=19; pip install av==18.0.0")
            sys.exit(2)
    except (ImportError, importlib.metadata.PackageNotFoundError):
        pass

if __name__ == "__main__":
    main()
