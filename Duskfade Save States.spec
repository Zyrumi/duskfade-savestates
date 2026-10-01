# PyInstaller spec: python -m PyInstaller "Duskfade Save States.spec"
a = Analysis(["savestate_app.py"], datas=[("savestates.ico", ".")])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Duskfade Save States",
          console=False, icon="savestates.ico", upx=False)
