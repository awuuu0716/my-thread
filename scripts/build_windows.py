"""Build an unsigned, self-contained Windows x64 folder and zip.

Run with a clean build venv: python -m pip install '.[bundle]'.
Does not read/copy account profiles or modify global browser installations.
"""
from datetime import datetime
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None, cwd=ROOT):
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def notices(target):
    """Include installed runtime dependencies' license files and version inventory."""
    pending, visited, inventory = [('mythread-terminal', frozenset())], set(), []
    copied = set()
    while pending:
        name, extras = pending.pop()
        dist = metadata.distribution(name)
        name = dist.metadata['Name']
        key = (name.lower(), extras)
        if key in visited:
            continue
        visited.add(key)
        for dependency in dist.requires or []:
            req = Requirement(dependency)
            if req.marker is None or any(
                req.marker.evaluate({'extra': extra}) for extra in ('', *extras)
            ):
                pending.append((req.name, frozenset(req.extras)))
        if name.lower() in copied:
            continue
        copied.add(name.lower())
        destination = target / name
        destination.mkdir(parents=True)
        (destination / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
        for entry in dist.files or []:
            if any(word in entry.name.lower() for word in ('license', 'copying', 'notice', 'copyright')):
                path = Path(dist.locate_file(entry))
                if path.is_file():
                    # Preserve relative paths to avoid overwriting multiple LICENSE files.
                    parts = [p for p in entry.parts if p not in ('.', '..')]
                    output = destination.joinpath(*parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, output)
        inventory.append({'name': name, 'version': dist.version})
    # Python runtime is redistributed by PyInstaller.
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.exists():
        shutil.copy2(python_license, target / 'PYTHON-LICENSE.txt')
    (target / 'versions.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')


def main():
    if sys.platform != 'win32' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise SystemExit('Build this Windows x64 artifact on Windows x64.')
    version = metadata.version('mythread-terminal')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    release = ROOT / 'dist' / f'mythread-{version}-windows-x64-{stamp}'
    release.mkdir(parents=True, exist_ok=False)
    cache = ROOT / '.tools' / 'playwright-bundle-cache'
    env = os.environ.copy()
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(cache)
    run(sys.executable, '-m', 'playwright', 'install', '--no-shell', 'chromium', env=env)
    work_root = ROOT / 'build'
    work_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='portable-', dir=work_root) as work:
        run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
            '--console', '--noupx', '--name', 'mythread',
            '--distpath', release, '--workpath', Path(work) / 'work', '--specpath', work,
            '--paths', ROOT / 'src',
            '--collect-all', 'textual', '--collect-all', 'playwright',
            '--recursive-copy-metadata', 'mythread-terminal',
            '--exclude-module', 'httpx', '--exclude-module', 'keyring',
            ROOT / 'scripts' / 'portable_entry.py')
    folder = release / 'mythread'
    shutil.copytree(cache, folder / 'browsers', ignore=shutil.ignore_patterns('.links'))
    for filename in ('LICENSE', 'README.md'):
        shutil.copy2(ROOT / filename, folder / filename)
    shutil.copy2(ROOT / 'docs' / 'portable.md', folder / 'START-HERE.md')
    notices(folder / 'THIRD-PARTY-NOTICES')
    # Empty cache override must not affect frozen resolution. No user Python or
    # browser cache is required to run this synthetic test.
    smoke_env = os.environ.copy()
    smoke_env.pop('PYTHONPATH', None)
    smoke_env.pop('PYTHONHOME', None)
    smoke_env['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    smoke_env['PLAYWRIGHT_BROWSERS_PATH'] = str(release / 'nonexistent-cache')
    with tempfile.TemporaryDirectory(prefix='mythread-cwd-') as elsewhere:
        run(folder / 'mythread.exe', '--self-test', env=smoke_env, cwd=elsewhere)
    archive = Path(shutil.make_archive(str(release), 'zip', root_dir=release))
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='ascii')
    print(f'Portable executable: {folder / "mythread.exe"}')
    print(f'Archive: {archive}')
    print(f'SHA256: {digest}')


if __name__ == '__main__':
    main()
