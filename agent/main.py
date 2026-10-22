import os
import sys
from pathlib import Path

# FlowScope ships its own MaaFramework. Its Agent must use the same protocol,
# while normal desktop runs retain their existing DLLs and explicit overrides.
if (sys.platform == "win32" and os.environ.get("PI_CLIENT_NAME") == "MPE"
        and not os.environ.get("MAAFW_BINARY_PATH")):
    native_dir = (Path(__file__).resolve().parent.parent / "tools"
                  / "MaaPipelineEditor" / "runtime" / "maafw" / "bin")
    if (native_dir / "MaaAgentServer.dll").is_file():
        os.environ["MAAFW_BINARY_PATH"] = str(native_dir)

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

from custom import action
from custom import reco

import gacha  # Registers the gacha-only Custom nodes.
import inventory  # Registers read-only inventory scanning and export actions.


def main():
    Toolkit.init_option("./")

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
