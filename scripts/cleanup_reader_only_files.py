from pathlib import Path
import shutil

root = Path.cwd()
ielts_dir = root / 'public-resources' / 'ielts-vocabulary'
if ielts_dir.exists():
    shutil.rmtree(ielts_dir)

build_script = root / 'scripts' / 'build-cloudbase-v2.cjs'
if build_script.exists():
    build_script.unlink()

audit_path = root / 'MIGRATION_AUDIT.md'
text = audit_path.read_text(encoding='utf-8')
text = text.replace('Resource files copied: **64**', 'Resource files retained: **62**')
text = text.replace('Support files copied: **5**', 'Support files retained: **4**')
text = '\n'.join(
    line for line in text.splitlines()
    if 'scripts/build-cloudbase-v2.cjs' not in line
    and 'public-resources/ielts-vocabulary/' not in line
)
marker = '- Excluded private/fallback pack: `dyl-exam-public-backup`'
note = '- Removed after ownership audit: reader-only `public-resources/ielts-vocabulary/` and `scripts/build-cloudbase-v2.cjs`'
if note not in text:
    text = text.replace(marker, f'{marker}\n{note}')
audit_path.write_text(text.rstrip() + '\n', encoding='utf-8')
