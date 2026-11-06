import base64
import gzip
import hashlib
import json
from pathlib import Path


def read_release(path):
    manifest = json.loads((path / 'manifest.json').read_bytes())
    bundle = (path / manifest['files']['bundle']).read_bytes()
    cards = json.loads(gzip.decompress(base64.b64decode(bundle)))['cards']
    assert len(cards) == manifest['cardCount'] == len({card['id'] for card in cards})
    return manifest, bundle, {card['id']: card for card in cards}


root = Path(__file__).resolve().parents[1] / 'public-resources/politics-2027/releases'
_, base_bundle, original = read_release(root / '2026.08.22.1')
release = root / '2026.11.07.1'
manifest, bundle, current = read_release(release)
metadata = manifest['release']
evidence = json.loads((release / 'release-evidence.json').read_bytes())
assert evidence['manifest'] == metadata
assert metadata['inputBundleSha256'] == hashlib.sha256(base_bundle).hexdigest()
assert metadata['bundleSha256'] == hashlib.sha256(bundle).hexdigest()
assert metadata['bundleSizeBytes'] == len(bundle)
parents = {group['oldCardId'] for group in evidence['splitMappings']}
assert len(parents) == 16
for card_id, old in original.items():
    expected = {**old, 'source': {**old['source'], 'nonReviewable': True}} if card_id in parents else old
    assert current[card_id] == expected, card_id
units = [unit for group in evidence['splitMappings'] for unit in group['units']]
assert len(units) == len(set(units)) == 63
assert set(units) <= current.keys() and not (set(units) & parents)
choices = [card for card_id, card in current.items() if card_id.startswith('public-politics-choice-')]
assert len(choices) == 53 and len(set(current) - set(original) - {card['id'] for card in choices}) == 7
for card in choices:
    choice = card['choice']
    assert [item['key'] for item in choice['options']] == list('ABCD')
    answers = choice['answerKeys']
    assert answers and len(set(answers)) == len(answers) and set(answers) <= set('ABCD')
    assert (len(answers) > 1) == (choice['type'] == 'multiple')
    assert card['rawFront'].count('class="miki-tpl-key"') == 4
    assert 'miki-tpl-answer' not in card['rawFront'] and 'miki-tpl-answer' in card['rawBack']
print(f"Verified {len(current)} cards, {len(units)} split targets, {len(choices)} choices")
