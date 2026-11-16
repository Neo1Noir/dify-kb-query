"""Build a reproducible single-folder skill ZIP from the distributed template."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/dify-kb-query"


def package(destination=None):
    cfg = json.loads((SOURCE / "scripts/config.json").read_text(encoding="utf-8"))
    template = {"api_base_url": "https://dify.example.invalid/v1", "required_tags": [
        {"id": "00000000-0000-4000-8000-000000000001", "name": "Engineering"},
        {"id": "00000000-0000-4000-8000-000000000002", "name": "Sales"},
    ]}
    if cfg != template:
        raise ValueError("Refusing to package anything except the complete public configuration template")
    destination = Path(destination or ROOT / "dist/dify-kb-query.zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(SOURCE.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            relative = p.relative_to(SOURCE)
            if p.suffix not in {".md", ".py", ".json", ".yaml", ".txt"}:
                raise ValueError(f"Unexpected package file: {relative}")
            info = zipfile.ZipInfo("dify-kb-query/" + relative.as_posix(), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, p.read_bytes())
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    return destination


if __name__ == "__main__":
    print(package())
