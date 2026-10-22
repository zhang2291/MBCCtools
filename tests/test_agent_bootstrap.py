"""Check DLL selection without loading native libraries or connecting a device."""
import ast
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class AgentBootstrapTests(unittest.TestCase):
    def run_bootstrap(self, platform, existing=None, packaged=True, client="MPE"):
        source = Path(__file__).resolve().parents[1] / "agent" / "main.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        # Execute only the bootstrap before the first maa import.
        prefix = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module.startswith("maa"):
                break
            prefix.append(node)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "tools" / "MaaPipelineEditor" / "runtime" / "maafw" / "bin"
            if packaged:
                native.mkdir(parents=True)
                (native / "MaaAgentServer.dll").touch()
            environment = {} if existing is None else {"MAAFW_BINARY_PATH": existing}
            environment["PI_CLIENT_NAME"] = client
            with patch.dict(os.environ, environment, clear=True), patch("sys.platform", platform):
                exec(compile(ast.Module(body=prefix, type_ignores=[]), str(source), "exec"),
                     {"__file__": str(root / "agent" / "main.py")})
                return os.environ.get("MAAFW_BINARY_PATH"), str(native)

    def test_windows_uses_packaged_dlls(self):
        actual, expected = self.run_bootstrap("win32")
        self.assertEqual(actual, expected)

    def test_explicit_path_is_preserved(self):
        self.assertEqual(self.run_bootstrap("win32", existing="explicit")[0], "explicit")

    def test_desktop_keeps_original_dlls(self):
        self.assertIsNone(self.run_bootstrap("win32", client="MFA")[0])

    def test_android_keeps_wheel_default(self):
        self.assertIsNone(self.run_bootstrap("linux")[0])

    def test_source_without_native_bundle_keeps_default(self):
        self.assertIsNone(self.run_bootstrap("win32", packaged=False)[0])


if __name__ == "__main__":
    unittest.main()
