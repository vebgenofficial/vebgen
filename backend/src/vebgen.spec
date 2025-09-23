# vebgen.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['backend\\src\\main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # This is the most important part for your project.
        # It bundles your entire 'src' directory, which includes the 'ui', 'core',
        # and 'plugins' packages. This ensures that your application can find
        # all its assets, prompts, and other data files at runtime.
        ('backend\\src', 'backend\\src')
    ],
    hiddenimports=[
        # Explicitly include modules that might be missed by static analysis.
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