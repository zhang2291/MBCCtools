import os
from pathlib import Path
import sys

version = os.environ.get("PI_CLIENT_MAAFW_VERSION", "")
native_dir = (Path.home() / "AppData/Roaming/Code/User/globalStorage/nekosu.maa-support"
              / "native/install" / version / "node_modules/@maaxyz/maa-node-win32-x64")
if native_dir.is_dir() and not os.environ.get("MAAFW_BINARY_PATH"):
    os.environ["MAAFW_BINARY_PATH"] = str(native_dir)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main

main.main()
