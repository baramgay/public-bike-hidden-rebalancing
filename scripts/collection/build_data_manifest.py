"""List raw-file snapshots and hashes; presence is not analytical approval."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[2]
    raw = root / 'data' / 'raw'
    entries = []
    for path in sorted(raw.rglob('*')):
        if not path.is_file():
            continue
        before = path.stat()
        partial = path.name.endswith('.partial')
        digest = None
        if not partial:
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
        after = path.stat()
        changed = (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        state = 'incomplete' if partial else ('changed_during_scan' if changed else 'present')
        entries.append({
            'path': path.relative_to(root).as_posix(),
            'bytes': after.st_size,
            'modified_utc': datetime.fromtimestamp(after.st_mtime, timezone.utc).isoformat(),
            'state': state,
            'sha256': None if changed else digest,
        })
    out = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'meaning': 'File snapshot only. Consult dataset metadata for integrity, coverage and permitted use. Incomplete files are excluded from usable-data counts.',
        'files': entries,
    }
    target = root / 'data' / 'metadata' / 'file_manifest.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)
    print(json.dumps({'files': len(entries), 'present': sum(x['state'] == 'present' for x in entries), 'incomplete': sum(x['state'] == 'incomplete' for x in entries)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
