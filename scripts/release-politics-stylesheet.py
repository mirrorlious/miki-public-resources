#!/usr/bin/env python3
from pathlib import Path
import base64
import gzip
import hashlib
import json
import shutil
import sys

from politics_pack_contract import POLITICS_PACK_VERSION, POLITICS_STATIC_STYLESHEET


PACK_ID = 'politics-2027'
INPUT_VERSION = '2026.07.10.2'
INPUT_BUNDLE_SHA256 = 'e0085641b637bd159b57a28f5456c780e6d5316c9dad58195acf4e20d848adc8'
SOURCE_REPOSITORY_COMMIT = '48dd325cb46bacee54ed25c358f3d8e31b14680a'


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def verify_release(repo_root):
    pack_root = repo_root / 'public-resources' / PACK_ID
    release_root = pack_root / 'releases' / POLITICS_PACK_VERSION
    manifest = json.loads((release_root / 'manifest.json').read_text(encoding='utf-8'))
    evidence = json.loads((release_root / 'release-evidence.json').read_text(encoding='utf-8'))
    bundle_bytes = (release_root / 'pack.json.gz.b64').read_bytes()
    bundle = json.loads(gzip.decompress(base64.b64decode(bundle_bytes)).decode('utf-8'))
    cards = bundle.get('cards')

    checks = {
        'releaseVersion': manifest.get('version') == POLITICS_PACK_VERSION,
        'cardCount': isinstance(cards, list) and len(cards) == manifest.get('cardCount') == 1513,
        'bundleStylesheet': bundle.get('cardCss') == POLITICS_STATIC_STYLESHEET,
        'bundleSize': len(bundle_bytes) == evidence.get('output', {}).get('bundleSizeBytes'),
        'bundleSha256': sha256_bytes(bundle_bytes) == evidence.get('output', {}).get('bundleSha256'),
        'cardPayloadSha256': sha256_bytes(canonical_json_bytes(cards)) == evidence.get('output', {}).get('cardPayloadSha256'),
        'stylesheetSha256': sha256_bytes(POLITICS_STATIC_STYLESHEET.encode('utf-8')) == evidence.get('output', {}).get('stylesheetSha256'),
    }
    root_manifest = json.loads((pack_root / 'manifest.json').read_text(encoding='utf-8'))
    checks['rootManifestRelease'] = root_manifest.get('files', {}).get('bundle') == (
        f'releases/{POLITICS_PACK_VERSION}/pack.json.gz.b64'
    )
    catalog = json.loads((repo_root / 'public-resources' / 'manifest.json').read_text(encoding='utf-8'))
    entry = next((item for item in catalog.get('packs', []) if item.get('packId') == PACK_ID), {})
    checks['catalogRelease'] = entry.get('manifestUrl') == (
        f'{PACK_ID}/releases/{POLITICS_PACK_VERSION}/manifest.json'
    )
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f'politics release verification failed: {", ".join(failed)}')
    result = {
        'packId': PACK_ID,
        'version': POLITICS_PACK_VERSION,
        'bundleSizeBytes': len(bundle_bytes),
        'bundleSha256': sha256_bytes(bundle_bytes),
        'cardPayloadSha256': sha256_bytes(canonical_json_bytes(cards)),
        'checks': checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(repo_root):
    pack_root = repo_root / 'public-resources' / PACK_ID
    input_bundle_path = pack_root / 'pack.json.gz.b64'
    input_manifest_path = pack_root / 'manifest.json'
    input_bundle_bytes = input_bundle_path.read_bytes()
    input_manifest = json.loads(input_manifest_path.read_text(encoding='utf-8'))

    if input_manifest.get('version') != INPUT_VERSION:
        raise RuntimeError(f'unexpected input version: {input_manifest.get("version")}')
    if sha256_bytes(input_bundle_bytes) != INPUT_BUNDLE_SHA256:
        raise RuntimeError('input bundle SHA-256 does not match the audited release')

    bundle = json.loads(gzip.decompress(base64.b64decode(input_bundle_bytes)).decode('utf-8'))
    cards = bundle.get('cards')
    if not isinstance(cards, list) or len(cards) != input_manifest.get('cardCount'):
        raise RuntimeError('input card count does not match manifest')
    if bundle.get('cardCss'):
        raise RuntimeError('input bundle already declares cardCss')

    card_payload_sha256 = sha256_bytes(canonical_json_bytes(cards))
    bundle['cardCss'] = POLITICS_STATIC_STYLESHEET
    if sha256_bytes(canonical_json_bytes(bundle.get('cards'))) != card_payload_sha256:
        raise RuntimeError('card payload changed during stylesheet canonicalization')

    raw_bundle = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    output_bundle_bytes = base64.b64encode(gzip.compress(raw_bundle, compresslevel=9, mtime=0))
    release_root = pack_root / 'releases' / POLITICS_PACK_VERSION
    if release_root.exists():
        raise RuntimeError(f'release already exists: {release_root}')
    release_root.mkdir(parents=True)
    (release_root / 'pack.json.gz.b64').write_bytes(output_bundle_bytes)
    shutil.copy2(pack_root / 'ATTRIBUTION.md', release_root / 'ATTRIBUTION.md')
    shutil.copy2(pack_root / 'README.md', release_root / 'README.md')

    release_manifest = {
        **input_manifest,
        'version': POLITICS_PACK_VERSION,
        'files': {
            'bundle': 'pack.json.gz.b64',
            'attribution': 'ATTRIBUTION.md',
        },
        'release': {
            'immutable': True,
            'inputVersion': INPUT_VERSION,
            'inputBundleSha256': INPUT_BUNDLE_SHA256,
            'cardPayloadSha256': card_payload_sha256,
            'stylesheetSha256': sha256_bytes(POLITICS_STATIC_STYLESHEET.encode('utf-8')),
        },
    }
    (release_root / 'manifest.json').write_text(
        json.dumps(release_manifest, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )

    root_manifest = {
        **release_manifest,
        'files': {
            'bundle': f'releases/{POLITICS_PACK_VERSION}/pack.json.gz.b64',
            'attribution': 'ATTRIBUTION.md',
        },
    }
    input_manifest_path.write_text(json.dumps(root_manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    catalog_path = repo_root / 'public-resources' / 'manifest.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    entry = next((item for item in catalog.get('packs', []) if item.get('packId') == PACK_ID), None)
    if not entry:
        raise RuntimeError('politics catalog entry not found')
    entry['version'] = POLITICS_PACK_VERSION
    entry['manifestUrl'] = f'{PACK_ID}/releases/{POLITICS_PACK_VERSION}/manifest.json'
    catalog['updatedAt'] = '2026-08-22'
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    evidence = {
        'packId': PACK_ID,
        'releaseVersion': POLITICS_PACK_VERSION,
        'sourceRepositoryCommit': SOURCE_REPOSITORY_COMMIT,
        'transformation': 'add bundle-level safe static cardCss; preserve cards byte-for-byte after JSON decode',
        'input': {
            'version': INPUT_VERSION,
            'bundleSizeBytes': len(input_bundle_bytes),
            'bundleSha256': INPUT_BUNDLE_SHA256,
            'cardPayloadSha256': card_payload_sha256,
        },
        'output': {
            'bundleSizeBytes': len(output_bundle_bytes),
            'bundleSha256': sha256_bytes(output_bundle_bytes),
            'cardPayloadSha256': card_payload_sha256,
            'stylesheetSha256': sha256_bytes(POLITICS_STATIC_STYLESHEET.encode('utf-8')),
        },
        'rollbackManifestUrl': (
            'https://raw.githubusercontent.com/mirrorlious/miki-public-resources/'
            f'{SOURCE_REPOSITORY_COMMIT}/public-resources/{PACK_ID}/manifest.json'
        ),
    }
    (release_root / 'release-evidence.json').write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    if sys.argv[1:] == ['--verify']:
        verify_release(root)
    elif sys.argv[1:]:
        raise SystemExit('usage: release-politics-stylesheet.py [--verify]')
    else:
        main(root)
