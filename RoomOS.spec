# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
room_os_assets = [
    "assets/room_os.ico",
    "assets/room_os_logo.png",
    "assets/room_os_tray.png",
    "assets/fonts/InterVariable.ttf",
    "assets/fonts/LICENSE-Inter.txt",
]
datas += [(asset, str(__import__("pathlib").Path(asset).parent)) for asset in room_os_assets]
for package in ("mediapipe", "cv2", "google.genai"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Room OS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/room_os.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Room OS",
)
