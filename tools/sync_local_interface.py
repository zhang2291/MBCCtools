"""Sync source interface into a desktop package without losing its Python runtime.

Usage: python tools/sync_local_interface.py build-local-final
Resource files are synced separately. This command never touches user configuration.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    package = parser.parse_args().package.resolve()
    destination = package / 'interface.json'
    if package == ROOT or not (package / 'MFAAvalonia.exe').is_file():
        parser.error('Target must be a packaged desktop directory, not the source tree.')
    source = json.loads((ROOT / 'interface.json').read_text(encoding='utf-8-sig'))
    previous = json.loads(destination.read_text(encoding='utf-8-sig'))
    if 'agent' in source:
        # A source PI uses system Python; the desktop delivery has its own dependencies.
        if (package / 'agent/python/python.exe').is_file():
            source['agent']['child_exec'] = './agent/python/python.exe'
        elif previous.get('agent', {}).get('child_exec'):
            source['agent']['child_exec'] = previous['agent']['child_exec']
        else:
            parser.error('No packaged Agent runtime configured; refusing an unsafe overwrite.')
    backup = package / 'backup' / ('interface-sync-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(parents=True)
    shutil.copy2(destination, backup / destination.name)
    destination.write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Synced {destination}; backup: {backup}')


if __name__ == '__main__':
    main()
