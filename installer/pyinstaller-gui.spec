import os
import sys

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files

REPO_ROOT = os.path.dirname(os.path.abspath(SPECPATH))
ENTRY_DIR = os.path.join(REPO_ROOT, 'build', 'entry')
os.makedirs(ENTRY_DIR, exist_ok=True)

ENTRY = os.path.join(ENTRY_DIR, 'netbreak_gui.py')
with open(ENTRY, 'w', encoding='utf-8', newline='\n') as stream:
    stream.write('from netbreak.desktop.app import main\n\nraise SystemExit(main())\n')

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CONF['distpath'] = os.path.join(REPO_ROOT, 'dist')

datas = collect_data_files('netbreak')

a = Analysis(
    [ENTRY],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'netbreak',
        'netbreak.desktop',
        'netbreak.desktop.app',
        'netbreak.ports',
        'netbreak.targets',
        'netbreak.timing',
        'netbreak.output',
        'netbreak.core',
        'netbreak.core.backends',
        'netbreak.core.engine',
        'netbreak.core.events',
        'netbreak.core.models',
        'netbreak.core.versions',
        'netbreak.core.osdetect',
        'netbreak.core.discovery',
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['textual'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='netbreak-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
