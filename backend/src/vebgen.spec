# vebgen.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['backend\\src\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('backend\\src', 'backend\\src')
    ],
    hiddenimports=[
        'keyring.backends.win32', # For Windows secure storage
        'pkg_resources.py2_warn',
        'src.plugins.django.prompts', # For dynamically loaded Django prompts
    ],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Vebgen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # This is the option to hide the command prompt for a GUI application.
    console=False,
    disable_windowed_traceback=False,
    # This sets the icon for your .exe file.
    icon='backend\\src\\ui\\assets\\vebgen_logo.ico',
)