from __future__ import annotations

import base64
import gzip
import hashlib
import html
import json
import re
import sqlite3
import zipfile
from collections import OrderedDict
from pathlib import Path

APKG = Path('source.apkg')
WORK = Path('.')
PACK_ID = 'qy-lsat-civil-law'
VERSION = '2026.08.03'
TITLE = 'QY 民法法硕 Anki 记忆卡片'
FIELD_SEP = '\x1f'

WORK.mkdir(parents=True, exist_ok=True)
EXTRACT = WORK / 'extract'
EXTRACT.mkdir(exist_ok=True)
with zipfile.ZipFile(APKG) as zf:
    collection_name = next((n for n in ('collection.anki21', 'collection.anki2', 'collection.anki21b') if n in zf.namelist()), None)
    if not collection_name:
        raise RuntimeError('APKG 中未找到 collection 数据库')
    db_path = EXTRACT / 'collection.anki2'
    db_path.write_bytes(zf.read(collection_name))
    media_map = json.loads(zf.read('media').decode('utf-8')) if 'media' in zf.namelist() else {}
    if media_map:
        raise RuntimeError('本转换器预期无媒体文件，但 APKG 中检测到媒体')

con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row
col = con.execute('SELECT decks, models FROM col LIMIT 1').fetchone()
decks_raw = json.loads(col['decks'])
models = json.loads(col['models'])
notes = {int(r['id']): r for r in con.execute('SELECT id, guid, mid, tags, flds, sfld FROM notes ORDER BY id')}
cards_raw = list(con.execute('SELECT id, nid, did, ord, reps, lapses, ivl, due FROM cards ORDER BY id'))


def strip_unsafe(value: str) -> str:
    value = str(value or '')
    value = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', value, flags=re.I)
    value = re.sub(r'<noscript\b[^>]*>[\s\S]*?</noscript>', '', value, flags=re.I)
    value = re.sub(r'\son[a-z]+\s*=\s*(["\']).*?\1', '', value, flags=re.I)
    value = re.sub(r'\son[a-z]+\s*=\s*[^\s>]+', '', value, flags=re.I)
    value = re.sub(r'javascript\s*:', '', value, flags=re.I)
    return value.strip()


def strip_html(value: str) -> str:
    value = re.sub(r'<br\s*/?>', '\n', str(value or ''), flags=re.I)
    value = re.sub(r'</(?:p|div|li|tr|h[1-6])>', '\n', value, flags=re.I)
    value = re.sub(r'<[^>]+>', ' ', value)
    value = html.unescape(value)
    value = re.sub(r'[ \t\f\v]+', ' ', value)
    value = re.sub(r' *\n *', '\n', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


def normalize_tags(note_tags: str, field_tag: str) -> list[str]:
    values = []
    for token in re.split(r'[\s·,，/]+', f'{note_tags or ""} {field_tag or ""}'):
        token = token.strip('_ -')
        if token and token not in values:
            values.append(token)
    return values[:24]


def field_map(note, model) -> dict[str, str]:
    vals = str(note['flds'] or '').split(FIELD_SEP)
    names = [str(f.get('name') or f'Field{i+1}') for i, f in enumerate(model.get('flds') or [])]
    return {name: vals[i] if i < len(vals) else '' for i, name in enumerate(names)}


def render_cloze(text: str, reveal: bool) -> str:
    pattern = re.compile(r'\{\{c\d+::(.*?)(?:::(.*?))?\}\}', re.S)
    def repl(m):
        answer = m.group(1)
        hint = m.group(2)
        if reveal:
            return f'<span class="cloze">{answer}</span>'
        marker = html.escape(hint or '…')
        return f'<span class="cloze">[{marker}]</span>'
    return pattern.sub(repl, str(text or ''))


def apply_conditionals(template: str, fields: dict[str, str]) -> str:
    pattern = re.compile(r'\{\{#([^}]+)\}\}([\s\S]*?)\{\{/\1\}\}')
    prev = None
    value = template
    while prev != value:
        prev = value
        value = pattern.sub(lambda m: m.group(2) if str(fields.get(m.group(1), '')).strip() else '', value)
    return value


def render_template(template: str, fields: dict[str, str], reveal_cloze: bool) -> str:
    value = apply_conditionals(str(template or ''), fields)
    value = re.sub(r'\{\{cloze:([^}]+)\}\}', lambda m: render_cloze(fields.get(m.group(1), ''), reveal_cloze), value)
    value = re.sub(r'\{\{([^}:]+)\}\}', lambda m: str(fields.get(m.group(1), '')), value)
    return strip_unsafe(value)


def stable_deck_record(did: int, name: str) -> dict:
    parts = [p.strip() for p in str(name or '法硕民法').split('::') if p.strip()]
    section = parts[0] if parts else '法硕民法'
    chapter = ' / '.join(parts[1:-1]) if len(parts) > 2 else ''
    deck_name = parts[-1] if len(parts) > 1 else (parts[0] if parts else '民法')
    return {
        'id': f'public-{PACK_ID}-deck-{did}',
        'name': deck_name,
        'description': f'原 Anki 卡组：{name}',
        'section': section,
        'chapter': chapter,
        'source': {'type': 'public-apkg', 'packId': PACK_ID, 'ankiDeckId': str(did), 'deckName': name, 'deckPath': parts},
    }

seen_note_payloads: set[tuple[int, str]] = set()
kept_note_ids: set[int] = set()
duplicate_note_ids: list[int] = []
for nid, note in notes.items():
    key = (int(note['mid']), str(note['flds']))
    if key in seen_note_payloads:
        duplicate_note_ids.append(nid)
        continue
    seen_note_payloads.add(key)
    kept_note_ids.add(nid)

used_dids: OrderedDict[int, None] = OrderedDict()
public_cards = []
map_records = []
model_counts: dict[str, int] = {}
book_counts: dict[str, int] = {}
for card in cards_raw:
    nid = int(card['nid'])
    if nid not in kept_note_ids:
        continue
    note = notes.get(nid)
    if not note:
        continue
    model = models.get(str(note['mid'])) or {}
    tmpls = model.get('tmpls') or []
    template = tmpls[int(card['ord'])] if int(card['ord']) < len(tmpls) else (tmpls[0] if tmpls else {})
    fields = field_map(note, model)
    model_name = str(model.get('name') or 'Anki 模板')
    template_name = str(template.get('name') or '卡片')
    front_html = render_template(template.get('qfmt', '{{Front}}'), fields, reveal_cloze=False)
    back_html = render_template(template.get('afmt', '{{Back}}'), fields, reveal_cloze=True)
    front_text = strip_html(front_html) or strip_html(note['sfld'])
    back_text = strip_html(back_html)
    if not front_text and not front_html:
        continue
    did = int(card['did'])
    used_dids[did] = None
    deck_name = str((decks_raw.get(str(did)) or {}).get('name') or '法硕民法')
    deck_path = [p.strip() for p in deck_name.split('::') if p.strip()]
    tags = normalize_tags(note['tags'], fields.get('Tag', ''))
    source_key = f'public:{PACK_ID}:{nid}:{int(card["id"])}:{int(card["ord"])}'
    card_id = f'public-{PACK_ID}-{int(card["id"])}'
    css = strip_unsafe(str(model.get('css') or '')).replace('@import', '/* import removed */')
    public_cards.append({
        'id': card_id, 'cardId': card_id, 'deckId': f'public-{PACK_ID}-deck-{did}',
        'front': front_text, 'back': back_text, 'rawFront': front_html, 'rawBack': back_html,
        'frontHtml': front_html, 'backHtml': back_html, 'cardCss': css,
        'template': 'qa', 'align': 'left', 'tags': tags, 'sourceKey': source_key,
        'source': {'type': 'public-apkg', 'packId': PACK_ID, 'ankiNoteId': str(nid), 'ankiCardId': str(card['id']), 'ankiDeckId': str(did), 'deckName': deck_name, 'deckPath': deck_path, 'modelName': model_name, 'templateName': template_name},
    })
    model_counts[model_name] = model_counts.get(model_name, 0) + 1
    major = deck_path[1] if len(deck_path) > 1 else '其他'
    book_counts[major] = book_counts.get(major, 0) + 1
    if '知识导图' in model_name:
        map_records.append({'title': fields.get('Front') or front_text, 'html': strip_unsafe(fields.get('Map', '')), 'tag': fields.get('Tag', ''), 'deckName': deck_name, 'noteId': str(nid)})

public_decks = [stable_deck_record(did, str((decks_raw.get(str(did)) or {}).get('name') or '法硕民法')) for did in used_dids]
if len({c['id'] for c in public_cards}) != len(public_cards): raise RuntimeError('卡片 ID 重复')
if len({c['sourceKey'] for c in public_cards}) != len(public_cards): raise RuntimeError('sourceKey 重复')
if len(public_cards) != 539: raise RuntimeError(f'去重后卡片数应为 539，实际 {len(public_cards)}')

PACK_DIR = WORK / 'public-resources' / PACK_ID
PACK_DIR.mkdir(parents=True, exist_ok=True)
bundle = {'data': {'decks': public_decks}, 'cards': public_cards}
raw_bundle = json.dumps(bundle, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
encoded_bundle = base64.b64encode(gzip.compress(raw_bundle, compresslevel=9, mtime=0)).decode('ascii')
(PACK_DIR / 'pack.json.gz.b64').write_text(encoded_bundle, encoding='ascii')

def map_order(item):
    title = item['title']
    if '总导图' in title: return 0
    m = re.search(r'第([一二三四五六])编', title)
    order = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6}
    return order.get(m.group(1), 99) if m else 99
map_records.sort(key=map_order)
if len(map_records) != 7: raise RuntimeError(f'唯一知识导图应为 7，实际 {len(map_records)}')

nav = ''.join(f'<a href="#map-{i}">{html.escape(item["title"])}</a>' for i, item in enumerate(map_records, 1))
sections = ''.join(f'<section class="map-card" id="map-{i}"><p class="kicker">知识导图</p><h2>{html.escape(item["title"])}</h2><div class="map-content">{item["html"]}</div></section>' for i, item in enumerate(map_records, 1))
source_sha = hashlib.sha256(APKG.read_bytes()).hexdigest()
knowledge_html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>QY 民法法硕知识导图</title><style>
:root{{--paper:#fdfbf7;--ink:#3d3530;--gold:#8b6914}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:#ebe7df;color:var(--ink);font-family:"Noto Serif CJK SC","Songti SC","SimSun",serif;line-height:1.75}}header{{padding:42px 24px 24px;text-align:center;background:#2d2925;color:#fff}}header h1{{margin:0 0 8px;font-size:clamp(24px,4vw,42px)}}header p{{margin:0;color:#d8cdbd}}nav{{position:sticky;top:0;z-index:10;display:flex;gap:8px;overflow:auto;padding:10px 16px;background:rgba(45,41,37,.96)}}nav a{{flex:0 0 auto;color:#f7ead0;text-decoration:none;border:1px solid #766b5f;border-radius:999px;padding:5px 11px;font-size:13px}}main{{width:min(1180px,calc(100% - 24px));margin:24px auto 50px;display:grid;gap:20px}}.map-card{{background:var(--paper);border:1px solid #d6c7ad;border-radius:14px;padding:24px;overflow:auto}}.kicker{{display:inline-block;margin:0 0 10px;color:var(--gold);font-weight:700;font-size:12px}}h2{{margin:0 0 18px;padding-bottom:10px;border-bottom:2px solid #b8941a}}.map-content{{font-size:14px;line-height:1.8;min-width:max-content}}.map-content .node{{display:inline-block;padding:2px 8px;margin:2px;border:1px solid #c9b99a;border-radius:3px;background:#f8f2e8;font-size:13px}}.map-content .node.root{{background:#8b6914;color:#fff;font-weight:bold}}.map-content .node.branch{{color:#8b6914;font-weight:bold}}.map-content ul{{list-style:none;margin:0;padding-left:24px;position:relative}}.map-content li{{margin:3px 0;position:relative}}footer{{text-align:center;color:#766b5f;font-size:12px;padding:0 20px 30px}}@media(max-width:640px){{nav{{position:static}}.map-card{{padding:16px}}}}
</style></head><body><header><h1>QY 民法法硕知识导图</h1><p>2027 法硕民法复习脉络</p></header><nav>{nav}</nav><main>{sections}</main><footer>来源 APKG SHA-256：{source_sha}</footer></body></html>'''
(PACK_DIR / 'knowledge-map.html').write_text(knowledge_html, encoding='utf-8')

manifest = {'schemaVersion': 1, 'id': PACK_ID, 'packId': PACK_ID, 'title': TITLE, 'description': '面向 2027 法硕备考，按民法六编整理的问答、填空与知识导图记忆卡片。', 'subject': '法硕民法', 'type': 'cards', 'version': VERSION, 'cardCount': len(public_cards), 'deckCount': len(public_decks), 'noteCount': len(public_cards), 'mapCount': len(map_records), 'duplicateCountRemoved': len(duplicate_note_ids), 'license': '仅供个人学习', 'author': 'QY', 'maintainer': 'Miki 站点', 'files': {'bundle': 'pack.json.gz.b64', 'knowledgeMap': 'knowledge-map.html', 'attribution': 'ATTRIBUTION.md'}, 'models': [{'name': name, 'cardCount': count} for name, count in sorted(model_counts.items())]}
(PACK_DIR / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
(PACK_DIR / 'ATTRIBUTION.md').write_text(f'# Attribution\n\n- 作者：QY\n- 内容：面向 2027 法硕备考的民法 Anki 记忆卡片。\n- 原始文件：`QY民法法硕Anki记忆卡片.apkg`\n- 原始文件 SHA-256：`{source_sha}`\n- 使用范围：仅供个人学习。\n\n转换时移除了 6 张完全重复的知识导图卡，正文内容未写入 Firebase 或 CloudBase。\n', encoding='utf-8')
(PACK_DIR / 'README.md').write_text(f'# {TITLE}\n\n- 卡片：{len(public_cards)} 张（已移除 {len(duplicate_note_ids)} 张完全重复卡）\n- 卡组：{len(public_decks)} 个\n- 知识导图：{len(map_records)} 张\n- 范围：总则、人格权、物权、合同、婚姻家庭与继承、侵权责任\n', encoding='utf-8')

print(json.dumps({'sourceSha256': source_sha, 'rawCards': len(cards_raw), 'cards': len(public_cards), 'duplicatesRemoved': len(duplicate_note_ids), 'decks': len(public_decks), 'maps': len(map_records), 'bundleBytes': len(encoded_bundle)}, ensure_ascii=False, indent=2))
