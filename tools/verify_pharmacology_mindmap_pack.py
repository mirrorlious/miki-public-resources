#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public-resources"
CATALOG = PUBLIC / "manifest.json"
PACK_ROOT = PUBLIC / "pharmacology"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    catalog = read_json(CATALOG)
    entry = next(pack for pack in catalog["packs"] if pack.get("packId") == "pharmacology-xmind-anki")
    assert re.fullmatch(r"pharmacology/releases/[^/]+/manifest\.json", entry["manifestUrl"])
    release_manifest_path = PUBLIC / entry["manifestUrl"]
    manifest = read_json(release_manifest_path)
    release_dir = release_manifest_path.parent
    assert manifest["immutable"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", manifest["sourceCommit"])
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["sourceSha256"])
    assert manifest["sourceSizeBytes"] > 0
    assert manifest["files"]["mediaBase"] == "media/"

    encoded = "".join((release_dir / part).read_text(encoding="utf-8").strip() for part in manifest["files"]["bundleParts"])
    bundle = json.loads(gzip.decompress(base64.b64decode(encoded)).decode("utf-8"))
    cards = bundle["cards"]
    card_ids = {card["id"] for card in cards}
    mindmap_cards = [card for card in cards if card.get("mindmapDocument")]
    anki_cards = [card for card in cards if not card.get("mindmapDocument")]
    assert len(cards) == manifest["cardCount"] == 257
    assert len(mindmap_cards) == manifest["conversion"]["xmind"]["mindMapDocumentCount"] == 55
    assert len(anki_cards) == manifest["conversion"]["anki"]["convertedCardCount"] == 202

    total_nodes = 0
    navigable_nodes = 0
    for card in mindmap_cards:
        document = card["mindmapDocument"]
        nodes = document["nodes"]
        node_ids = {node["id"] for node in nodes}
        total_nodes += len(nodes)
        navigable_nodes += sum(bool(node.get("targetCardId")) for node in nodes)
        assert card["template"] == "mindmap"
        assert card["mindmap"]["preferredView"] == "mindmap"
        assert document["rootId"] in node_ids
        assert len(node_ids) == len(nodes)
        assert card.get("backHtml") and card.get("cardCss")
        assert not card.get("cardJs")
        for node in nodes:
            if node.get("parentId"):
                assert node["parentId"] in node_ids
            if node.get("targetCardId"):
                assert node["targetCardId"] in card_ids

    assert total_nodes == manifest["conversion"]["xmind"]["mindMapNodeCount"]
    assert navigable_nodes == manifest["conversion"]["xmind"]["navigableNodeCount"]
    fixture = next(card for card in mindmap_cards if card["front"] == "抗精神分裂症药物+精神分裂症")
    assert len(fixture["mindmapDocument"]["nodes"]) >= 70
    assert fixture["mindmapDocument"]["nodes"][0]["targetCardId"] == fixture["id"]

    for relative_path, expected in manifest["integrity"].items():
        path = release_dir / relative_path
        payload = path.read_bytes()
        assert len(payload) == expected["sizeBytes"]
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    compatibility = read_json(PACK_ROOT / "manifest.json")
    assert compatibility["version"] == manifest["version"]
    assert all(part.startswith(f"releases/{manifest['version']}/") for part in compatibility["files"]["bundleParts"])
    print(json.dumps({
        "version": manifest["version"],
        "cards": len(cards),
        "mindMapDocuments": len(mindmap_cards),
        "mindMapNodes": total_nodes,
        "navigableNodes": navigable_nodes,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
