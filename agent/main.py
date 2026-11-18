import os
from pathlib import Path
import sys

# 当由 VSCode Maa Support 插件启动时，匹配其内置的 native runtime 动态库
if (sys.platform == "win32" and os.environ.get("PI_CLIENT_MAAFW_VERSION")
        and not os.environ.get("MAAFW_BINARY_PATH")):
    version = os.environ.get("PI_CLIENT_MAAFW_VERSION", "")
    native_dir = (Path.home() / "AppData/Roaming/Code/User/globalStorage/nekosu.maa-support"
                  / "native/install" / version / "node_modules/@maaxyz/maa-node-win32-x64")
    if (native_dir / "MaaAgentServer.dll").is_file():
        os.environ["MAAFW_BINARY_PATH"] = str(native_dir)

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

from custom import action
from custom import reco

import gacha  # Registers the gacha-only Custom nodes.
import inventory  # Registers read-only inventory scanning and export actions.
import survey  # Registers universal in-game H5 survey auto-fill action.


def main():
    Toolkit.init_option("./")

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
