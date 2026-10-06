"""Check the proposed Git index, not the ignored local business workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = {
    'docs/media/01-prepare-task-redacted.png': '1ecdf95a65922cbb26a44c22d36eb88172c48e190a9f6ad0344bba387307541a',
    'docs/media/02-feedback-redacted.png': 'cab0f1903696bb7dc3067677c8ae1abb906fb231a3c75cea9753347f624149a1',
    # User-approved architecture illustration; no business images or private IDs.
    'docs/media/03-architecture-flow.jpg': '119eb28f5cbb46c8f0392f27eb1e259ca7588c66dcb4aa94c356ad07d498bc8d',
}
PATTERNS = {
    'secret': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'),
    'feishu_url': re.compile(r'https://[^\s"<>]+\.(?:feishu|larksuite)\.[^\s/]+/[^\s"<>]+'),
    'resource_id': re.compile(r'\b(?:rec|tbl|vew|cli_|ou_|app_)[A-Za-z0-9]{8,}\b'),
    'absolute_path': re.compile(r'/(?:Users|home)/[^\s"<>]+'),
}


def scan():
    # Also reject bare live tokens/attachment IDs when this machine has private data.
    private_markers = set()
    def collect(value, key=''):
        if isinstance(value, dict):
            for child_key, child in value.items():
                collect(child, child_key)
        elif isinstance(value, list):
            for child in value:
                collect(child, key)
        elif key in {'id', 'view_id', 'record_id', 'base_token', 'folder_token', 'file_token', 'app_id'}:
            if isinstance(value, str) and len(value) >= 8:
                private_markers.add(value)
    for config in (ROOT / 'private').glob('*.local.json'):
        collect(json.loads(config.read_text()))
    raw = subprocess.check_output(['git', 'ls-files', '-s', '-z'], cwd=ROOT)
    entries = [entry.decode().split('\t', 1) for entry in raw.split(b'\0') if entry]
    findings = []
    total_bytes = 0
    manifest = []
    for metadata, name in entries:
        mode, object_id, stage = metadata.split()
        data = subprocess.check_output(['git', 'cat-file', 'blob', object_id], cwd=ROOT)
        total_bytes += len(data)
        path = Path(name)
        if mode == '120000' or stage != '0':
            findings.append({'path': name, 'risk': 'symlink_or_unmerged'})
        if (name.startswith(('private/', 'out/', '.local/', 'docs/internal/', 'data/staging/'))
                or name.startswith('Image-Factory-V2-') or path.suffix == '.zip'
                or path.name.startswith('.env') or path.name.endswith('.local.json')
                or name == 'config/base.json'):
            findings.append({'path': name, 'risk': 'private_or_handoff_file'})
        if len(data) > 1024 * 1024:
            findings.append({'path': name, 'risk': 'large_file_over_1MiB'})
        if path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.pdf'}:
            if name not in SCREENSHOTS or hashlib.sha256(data).hexdigest() != SCREENSHOTS[name]:
                findings.append({'path': name, 'risk': 'unapproved_media'})
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError:
            if name not in SCREENSHOTS:
                findings.append({'path': name, 'risk': 'unreviewed_binary'})
            text = ''
        for risk, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append({'path': name, 'risk': risk})
        if any(marker in text for marker in private_markers):
            findings.append({'path': name, 'risk': 'live_private_resource_value'})
        manifest.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    # Required copies and public paths must exist in the proposed release tree.
    names = {name for _, name in entries}
    for name in ['docs/第三方许可/MIT-Buluu.txt', 'docs/第三方许可/yang0-LICENSE.txt',
                 'docs/第三方许可/CC0来源说明.md', *SCREENSHOTS]:
        if name not in names:
            findings.append({'path': name, 'risk': 'required_attribution_or_media_missing'})
    hashes = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'result': 'PASS' if not findings else 'FAIL', 'high_risk_count': len(findings),
            'file_count': len(entries), 'content_bytes': total_bytes,
            'manifest_sha256': hashes, 'findings': findings,
            'scope': 'Git index bytes; ignored local files are not publish candidates',
            'approved_media': list(SCREENSHOTS)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Save evidence to an ignored/local destination')
    args = parser.parse_args()
    result = scan()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['result'] == 'PASS' else 1)
