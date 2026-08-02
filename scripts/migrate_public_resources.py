from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

SOURCE_REPOSITORY = "mirrorlious/-"
SOURCE_REPOSITORY_URL = "https://github.com/mirrorlious/-.git"
TARGET_REPOSITORY = "mirrorlious/miki-public-resources"
EXCLUDED_PACK_ID = "dyl-exam-public-backup"
EXCLUDED_RESOURCE_DIR = Path(EXCLUDED_PACK_ID)

OLD_RAW_BASES = (
    "https://raw.githubusercontent.com/mirrorlious/-/main/public-resources/",
    "https://raw.githubusercontent.com/mirrorlious/-/master/public-resources/",
)
OLD_CDN_BASES = (
    "https://cdn.jsdelivr.net/gh/mirrorlious/-@main/public-resources/",
    "https://cdn.jsdelivr.net/gh/mirrorlious/-@master/public-resources/",
)
NEW_RAW_BASE = "https://raw.githubusercontent.com/mirrorlious/miki-public-resources/main/public-resources/"
NEW_CDN_BASE = "https://cdn.jsdelivr.net/gh/mirrorlious/miki-public-resources@main/public-resources/"

PUBLIC_PACK_MARKERS = (
    "politics-2027",
    "pharmacology-xmind-anki",
    "pharmacology/",
    "jlpt-eggrolls",
    "kaoyan-english-one-papers",
    "kaoyan-english-two-papers",
    "kaoyan-english-2027-vocabulary",
)
PRIVATE_PACK_MARKERS = (
    EXCLUDED_PACK_ID,
    "/bundles/dyl-exam",
    "zh2000",
)


def rewrite_catalog_urls(value: str) -> str:
    result = value
    for old_base in OLD_RAW_BASES:
        result = result.replace(old_base, NEW_RAW_BASE)
    for old_base in OLD_CDN_BASES:
        result = result.replace(old_base, NEW_CDN_BASE)
    return result


def resource_relative_path(value: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.startswith(NEW_RAW_BASE):
        return Path(text.removeprefix(NEW_RAW_BASE))
    if text.startswith(NEW_CDN_BASE):
        return Path(text.removeprefix(NEW_CDN_BASE))
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        return None
    return Path(text)


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path.as_posix()}")
    if path.stat().st_size == 0:
        raise SystemExit(f"empty {label}: {path.as_posix()}")


def copy_public_resources(source_resources: Path, target_resources: Path) -> None:
    if target_resources.exists():
        shutil.rmtree(target_resources)
    target_resources.mkdir(parents=True)

    for source_path in sorted(path for path in source_resources.rglob("*") if path.is_file()):
        relative = source_path.relative_to(source_resources)
        if relative == Path("manifest.json"):
            continue
        if relative == EXCLUDED_RESOURCE_DIR or EXCLUDED_RESOURCE_DIR in relative.parents:
            continue
        destination = target_resources / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)


def write_public_catalog(source_resources: Path, target_resources: Path) -> list[dict]:
    source_manifest_path = source_resources / "manifest.json"
    source_catalog = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_packs = source_catalog.get("packs") if isinstance(source_catalog, dict) else None
    if not isinstance(source_packs, list):
        raise SystemExit("source catalog packs is missing")

    public_packs = [
        pack
        for pack in source_packs
        if str(pack.get("id") or pack.get("packId") or "") != EXCLUDED_PACK_ID
    ]
    if len(public_packs) != len(source_packs) - 1:
        raise SystemExit("expected exactly one DYL fallback entry to be excluded")

    catalog = {**source_catalog, "packs": public_packs}
    serialized = rewrite_catalog_urls(json.dumps(catalog, ensure_ascii=False, indent=2))
    (target_resources / "manifest.json").write_text(serialized + "\n", encoding="utf-8")
    return public_packs


def copy_support_files(source: Path, target: Path) -> list[str]:
    copied: list[str] = []
    for root_name in ("scripts", "tools"):
        root = source / root_name
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            relative = path.relative_to(source)
            haystack = f"{relative.as_posix()}\n{text}".lower()
            if any(marker.lower() in haystack for marker in PRIVATE_PACK_MARKERS):
                continue
            if not any(marker.lower() in haystack for marker in PUBLIC_PACK_MARKERS):
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied.append(relative.as_posix())
    return copied


def validate_catalog(target_resources: Path, packs: list[dict]) -> set[Path]:
    manifest_path = target_resources / "manifest.json"
    require_file(manifest_path, "catalog")

    if not packs:
        raise SystemExit("target catalog has no public packs")
    if any(str(pack.get("id") or pack.get("packId") or "") == EXCLUDED_PACK_ID for pack in packs):
        raise SystemExit("DYL fallback remains in target catalog")
    if (target_resources / EXCLUDED_RESOURCE_DIR).exists():
        raise SystemExit("DYL fallback directory was copied to target")

    checked_paths: set[Path] = {manifest_path}
    for pack in packs:
        pack_id = str(pack.get("id") or pack.get("packId") or "pack")
        for field in ("manifestUrl", "dataUrl", "sourceUrl"):
            value = pack.get(field)
            if not isinstance(value, str) or not value:
                continue
            if EXCLUDED_PACK_ID in value:
                raise SystemExit(f"DYL fallback reference remains in {pack_id} {field}")
            relative = resource_relative_path(rewrite_catalog_urls(value))
            if relative is None:
                continue
            path = target_resources / relative
            require_file(path, f"{pack_id} {field}")
            checked_paths.add(path)

        manifest_value = pack.get("manifestUrl")
        if not isinstance(manifest_value, str) or not manifest_value:
            continue
        relative_manifest = resource_relative_path(rewrite_catalog_urls(manifest_value))
        if relative_manifest is None:
            continue
        pack_manifest_path = target_resources / relative_manifest
        require_file(pack_manifest_path, f"{pack_id} manifest")
        checked_paths.add(pack_manifest_path)

        pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
        base = pack_manifest_path.parent
        files = pack_manifest.get("files") or {}
        for key in ("bundle", "data", "attribution"):
            value = files.get(key)
            if isinstance(value, str) and value:
                path = base / value
                require_file(path, f"{pack_id} {key}")
                checked_paths.add(path)
        for key in ("bundleParts", "cards"):
            values = files.get(key)
            if isinstance(values, list):
                for value in values:
                    path = base / value
                    require_file(path, f"{pack_id} {key}")
                    checked_paths.add(path)

    return checked_paths


def validate_file_copy(source_resources: Path, target_resources: Path) -> list[Path]:
    target_files = sorted(path for path in target_resources.rglob("*") if path.is_file())
    expected_source_files: list[Path] = []
    for path in source_resources.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_resources)
        if relative == EXCLUDED_RESOURCE_DIR or EXCLUDED_RESOURCE_DIR in relative.parents:
            continue
        expected_source_files.append(path)
    expected_source_files.sort()

    if len(target_files) != len(expected_source_files):
        raise SystemExit(
            f"public resource file count mismatch: source={len(expected_source_files)} "
            f"target={len(target_files)}"
        )

    for source_path in expected_source_files:
        relative = source_path.relative_to(source_resources)
        if relative == Path("manifest.json"):
            continue
        target_path = target_resources / relative
        require_file(target_path, f"copied resource {relative.as_posix()}")
        source_digest = hashlib.sha256(source_path.read_bytes()).digest()
        target_digest = hashlib.sha256(target_path.read_bytes()).digest()
        if source_digest != target_digest:
            raise SystemExit(f"copied resource checksum mismatch: {relative.as_posix()}")

    for path in target_files:
        relative = path.relative_to(target_resources).as_posix()
        if EXCLUDED_PACK_ID in relative:
            raise SystemExit(f"DYL path remains in target resources: {relative}")

    return target_files


def write_audit(
    target: Path,
    source_commit: str,
    packs: list[dict],
    target_files: list[Path],
    copied_support_files: list[str],
    checked_paths: set[Path],
) -> None:
    digest_rows = [
        (
            path.relative_to(target).as_posix(),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in target_files
    ]
    lines = [
        "# Public resource migration audit",
        "",
        f"- Source repository: `{SOURCE_REPOSITORY}`",
        f"- Source commit: `{source_commit}`",
        f"- Target repository: `{TARGET_REPOSITORY}`",
        f"- Public catalog entries: **{len(packs)}**",
        f"- Resource files copied: **{len(target_files)}**",
        f"- Support files copied: **{len(copied_support_files)}**",
        f"- Referenced files validated: **{len(checked_paths)}**",
        f"- Excluded private/fallback pack: `{EXCLUDED_PACK_ID}`",
        "",
        "## Copied support files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in copied_support_files)
    lines.extend(
        [
            "",
            "## Resource checksums",
            "",
            "| File | Bytes | SHA-256 |",
            "|---|---:|---|",
        ]
    )
    lines.extend(f"| `{path}` | {size} | `{digest}` |" for path, size, digest in digest_rows)
    (target / "MIGRATION_AUDIT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_agents(target: Path) -> None:
    content = """# Miki public-resource repository rules

- This repository contains only publicly distributable resources and their build tools for 【杨】Miki.
- Keep runtime catalog files under `public-resources/`.
- Preserve attribution, license and source-commit information for every imported pack.
- Never store user data, credentials, tokens, Firebase service accounts, CloudBase SecretId/SecretKey, or private asset packs here.
- Do not store DYL, DYL fallback, or ZH2000 card bodies, chunks, media, manifests, or access credentials in this repository.
- DYL and ZH2000 remain on the existing private Tencent CloudBase/COS asset-pack path.
- Changes to public pack paths or IDs must remain backward compatible with installed Miki profiles.
"""
    (target / "AGENTS.md").write_text(content, encoding="utf-8")


def main() -> None:
    target = Path.cwd()
    source = Path("/tmp/miki-reader-source")
    if source.exists():
        shutil.rmtree(source)
    subprocess.run(["git", "clone", "--depth=1", SOURCE_REPOSITORY_URL, str(source)], check=True)

    source_resources = source / "public-resources"
    target_resources = target / "public-resources"
    if not source_resources.is_dir():
        raise SystemExit("source public-resources directory is missing")

    copy_public_resources(source_resources, target_resources)
    packs = write_public_catalog(source_resources, target_resources)
    copied_support_files = copy_support_files(source, target)
    checked_paths = validate_catalog(target_resources, packs)
    target_files = validate_file_copy(source_resources, target_resources)
    source_commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    write_audit(target, source_commit, packs, target_files, copied_support_files, checked_paths)
    write_agents(target)


if __name__ == "__main__":
    main()
