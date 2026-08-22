#!/usr/bin/env python3
from pathlib import Path
import base64
import gzip
import importlib.util
import json
import sys
import tempfile


SCRIPTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_ROOT))
spec = importlib.util.spec_from_file_location('build_politics_pack', SCRIPTS_ROOT / 'build-politics-pack.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def main():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source_root = root / 'source'
        output_root = root / 'public-resources' / publisher.PACK_ID
        note = '#标签\n\n## 核心考点\n' + ('安全静态内容用于验证发布器样式契约。' * 8)
        for subject in publisher.SUBJECT_ORDER:
            subject_root = source_root / subject
            subject_root.mkdir(parents=True)
            (subject_root / 'contract.md').write_text(note, encoding='utf-8')

        publisher.build(source_root, output_root)
        manifest = json.loads((output_root / 'manifest.json').read_text(encoding='utf-8'))
        encoded = (output_root / 'pack.json.gz.b64').read_bytes()
        bundle = json.loads(gzip.decompress(base64.b64decode(encoded)).decode('utf-8'))

        assert manifest['version'] == publisher.POLITICS_PACK_VERSION
        assert bundle['cardCss'] == publisher.POLITICS_STATIC_STYLESHEET
        assert bundle['cards']
        assert all('cardCss' not in card for card in bundle['cards'])
        print(json.dumps({
            'version': manifest['version'],
            'cards': len(bundle['cards']),
            'stylesheetBytes': len(bundle['cardCss'].encode('utf-8')),
        }, ensure_ascii=False))


if __name__ == '__main__':
    main()
