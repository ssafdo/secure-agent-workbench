from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_workbench.server import create_server
from agent_workbench.workspace import WorkspaceManager
from scripts.run_project_demo import run_demo


class ProjectDemoTests(unittest.TestCase):
    def test_fixed_demo_scenarios_pass(self) -> None:
        with TemporaryDirectory() as directory:
            server = create_server(
                WorkspaceManager(Path(directory), b"i" * 32), "127.0.0.1", 0
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address[:2]
                result = run_demo(f"http://{host}:{port}")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["scenarios"]["retrievalCitation"]["citations"])
        self.assertEqual(
            result["scenarios"]["supervisorRouting"]["retrieval"]["specialist"],
            "retrieval",
        )
        self.assertEqual(
            result["scenarios"]["supervisorRouting"]["synthesis"]["specialist"],
            "synthesis",
        )
        self.assertEqual(
            result["scenarios"]["offlineReAct"]["actions"],
            ["list_files", "read_text", "read_text", "write_text"],
        )


if __name__ == "__main__":
    unittest.main()
