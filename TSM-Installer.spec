# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the TSM Installer GUI.
# Bundles payload/ directory (TireStorageManager.exe, nssm.exe, seed db).
#
# Build:
#   1. First build the app:  pyinstaller TireStorageManager.spec
#   2. Copy dist/TireStorageManager.exe → payload/TireStorageManager.exe
#   3. Then build installer:  pyinstaller TSM-Installer.spec

a = Analysis(
    ['TSMInstaller.py'],
    pathex=[],
    binaries=[],
    datas=[('payload', 'payload'), ('assets/installer.ico', 'assets')],
    hiddenimports=['installer_logic'],
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
    icon='assets/installer.ico',
)
