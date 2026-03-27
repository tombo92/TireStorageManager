# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the TSM Installer GUI.
# Bundles payload/ directory (TireStorageManager.exe, nssm.exe, seed db).
#
# Build (from repo root):
#   1. First build the app:  pyinstaller TireStorageManager.spec
#   2. Copy dist/TireStorageManager.exe → payload/TireStorageManager.exe
#   3. Then build installer:  pyinstaller installer/TSM-Installer.spec
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPECPATH if 'SPECPATH' not in dir() else '.')))
# SPECPATH is set by PyInstaller to the directory containing this .spec file.
# We go one level up to reach the repo root.
REPO_ROOT = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(SPECPATH, 'TSMInstaller.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[
        (os.path.join(REPO_ROOT, 'payload'), 'payload'),
        (os.path.join(REPO_ROOT, 'assets', 'installer.ico'), 'assets'),
        (os.path.join(REPO_ROOT, 'assets', 'dev.png'), 'assets'),
    ],
    hiddenimports=['installer.installer_logic'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='TSM-Installer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(REPO_ROOT, 'assets', 'installer.ico'),
)
