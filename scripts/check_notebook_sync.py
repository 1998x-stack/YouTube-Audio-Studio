"""Check all embedded Colab Notebook sources against the tracked project."""
from __future__ import annotations
import base64
import io
import json
import re
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
notebook = json.loads((ROOT / "YouTube_Audio_Studio_Colab.ipynb").read_text("utf-8"))
source = "".join(notebook["cells"][6]["source"])
match = re.search(r'SOURCE_ARCHIVE_B64 = """([A-Za-z0-9+/=]+)"""', source)
if match is None:
    raise SystemExit("Missing embedded SOURCE_ARCHIVE_B64")
with ZipFile(io.BytesIO(base64.b64decode(match.group(1)))) as archive:
    names = set(archive.namelist())
    for rel in names:
        actual = (ROOT / rel).read_bytes()
        embedded = archive.read(rel)
        if actual != embedded:
            raise SystemExit(f"Notebook embedded source is stale: {rel}")
    expected = {
        f.relative_to(ROOT).as_posix() for f in ROOT.rglob("*")
        if f.is_file() and f.name != "YouTube_Audio_Studio_Colab.ipynb"
        and not any(x in f.parts for x in (".git", "__pycache__", ".pytest_cache", ".venv"))
        and f.suffix != ".pyc"
    }
    if names != expected:
        raise SystemExit(f"Notebook source list mismatch: missing={expected-names}; excess={names-expected}")
print(f"Notebook embedded project is in sync ({len(names)} files)")
