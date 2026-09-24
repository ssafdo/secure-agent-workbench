from __future__ import annotations

import http.client
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path

from scripts.blind_routing_review import ReviewState, create_review_server


def _candidate(index: int, marker: str = "") -> dict[str, object]:
    return {
        "id": f"case-{index:03d}",
        "language": "en" if index % 2 else "zh",
        "task": (
            f"Find evidence about policy {marker}."
            if index % 2
            else f"总结所有资料 {marker}。"
        ),
        "deidentified": True,
        "reviewedByHuman": True,
    }


class BlindRoutingReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        private_root = Path("benchmarks/private")
        private_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=private_root)
        self.directory = Path(self.temp_dir.name)
        cases = [_candidate(index, "private-review-marker" if index == 1 else "") for index in range(1, 21)]
        self.candidates = self.directory / "candidates.jsonl"
        self.candidates.write_text(
            "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
            encoding="utf-8",
        )
        self.output = self.directory / "reviewer-a.json"
        self.state = ReviewState(self.candidates, self.output, "reviewer-a", 20)
        self.server = create_review_server(self.state, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def request(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        encoded = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {}
        if encoded is not None:
            headers["content-type"] = "application/json"
            headers["content-length"] = str(len(encoded))
        if token is not None:
            headers["x-review-token"] = token
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        headers_out = dict(response.getheaders())
        connection.close()
        parsed = (
            json.loads(raw.decode("utf-8"))
            if raw and headers_out.get("content-type", "").startswith("application/json")
            else raw.decode("utf-8")
        )
        return response.status, headers_out, parsed, raw

    def test_html_is_loopback_safe_and_api_requires_ephemeral_token(self) -> None:
        status, headers, body, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertIn("connect-src 'self'", headers["content-security-policy"])
        self.assertIn("自然任务独立标注", body)
        self.assertIn("evidence（定位/核实/引用）", body)
        self.assertIn("retrieval（检索与核实）", body)
        self.assertIn("5（严重）", body)

        status, _, payload, _ = self.request("GET", "/api/session")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "unauthorized")

        status, _, payload, _ = self.request("GET", "/api/session", token=self.server.token)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["cases"]), 20)
        self.assertNotIn("expectedSpecialist", payload["cases"][0])
        self.assertIn("private-review-marker", json.dumps(payload, ensure_ascii=False))

    def test_annotation_is_saved_atomically_and_finalized_only_when_complete(self) -> None:
        label = {
            "id": "case-001",
            "category": "evidence",
            "expectedSpecialist": "retrieval",
            "errorCost": 2,
        }
        status, _, payload, _ = self.request("POST", "/api/annotation", label, self.server.token)
        self.assertEqual(status, 200)
        self.assertFalse(payload["finalized"])
        self.assertTrue(self.state.draft_path.is_file())
        self.assertFalse(self.output.exists())

        for index in range(2, 21):
            item = _candidate(index)
            completed = {
                "id": item["id"],
                "category": "synthesis",
                "expectedSpecialist": "synthesis",
                "errorCost": 2,
            }
            status, _, payload, _ = self.request("POST", "/api/annotation", completed, self.server.token)
            self.assertEqual(status, 200)
        self.assertTrue(payload["finalized"])
        self.assertTrue(self.output.is_file())
        self.assertFalse(self.state.draft_path.exists())
        saved = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(saved["candidateSha256"], self.state.candidate_sha256)
        self.assertEqual(saved["kind"], "secure-agent-workbench/blind-routing-annotations")
        self.assertEqual(len(saved["labels"]), 20)

        status, _, payload, _ = self.request("POST", "/api/annotation", label, self.server.token)
        self.assertEqual(status, 400)
        self.assertIn("finalized", payload["message"])

    def test_invalid_annotation_does_not_change_draft(self) -> None:
        status, _, payload, _ = self.request(
            "POST",
            "/api/annotation",
            {"id": "case-001", "category": "not-a-category", "expectedSpecialist": "retrieval", "errorCost": 2},
            self.server.token,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "ValueError")
        self.assertFalse(self.state.draft_path.exists())

    def test_output_cannot_overwrite_candidates(self) -> None:
        with self.assertRaisesRegex(ValueError, "overwrite"):
            ReviewState(self.candidates, self.candidates, "reviewer-b", 20)

    def test_private_translations_are_exposed_as_review_aids_only(self) -> None:
        translations = self.directory / "translations.json"
        translations.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "secure-agent-workbench/blind-routing-translations",
                    "candidateSha256": hashlib.sha256(self.candidates.read_bytes()).hexdigest(),
                    "language": "zh-CN",
                    "translations": [{"id": "case-001", "text": "查找政策证据。"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state = ReviewState(
            self.candidates,
            self.directory / "reviewer-b.json",
            "reviewer-b",
            20,
            translations,
        )
        first = state.session()["cases"][0]
        self.assertEqual(first["translation"], "查找政策证据。")
        self.assertNotIn("translation", state.session()["cases"][1])

        label = {
            "id": "case-001",
            "category": "evidence",
            "expectedSpecialist": "retrieval",
            "errorCost": 2,
        }
        state.save(label)
        saved = json.loads(state.draft_path.read_text(encoding="utf-8"))
        self.assertNotIn("translation", json.dumps(saved, ensure_ascii=False))

    def test_translation_file_must_match_candidate_hash(self) -> None:
        translations = self.directory / "translations.json"
        translations.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "secure-agent-workbench/blind-routing-translations",
                    "candidateSha256": "0" * 64,
                    "language": "zh-CN",
                    "translations": [],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "metadata"):
            ReviewState(
                self.candidates,
                self.directory / "reviewer-b.json",
                "reviewer-b",
                20,
                translations,
            )

    def test_selected_cases_keep_full_candidate_hash_and_filter_translations(self) -> None:
        translations = self.directory / "translations.json"
        translations.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "secure-agent-workbench/blind-routing-translations",
                    "candidateSha256": hashlib.sha256(self.candidates.read_bytes()).hexdigest(),
                    "language": "zh-CN",
                    "translations": [
                        {"id": "case-001", "text": "第一条"},
                        {"id": "case-002", "text": "第二条"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        state = ReviewState(
            self.candidates,
            self.directory / "adjudicator.json",
            "adjudicator",
            20,
            translations,
            ["case-002", "case-001"],
        )
        session = state.session()
        self.assertEqual([case["id"] for case in session["cases"]], ["case-001", "case-002"])
        self.assertEqual([case["translation"] for case in session["cases"]], ["第一条", "第二条"])
        self.assertEqual(
            state.candidate_sha256,
            hashlib.sha256(self.candidates.read_bytes()).hexdigest(),
        )

    def test_selected_cases_reject_unknown_and_duplicate_ids(self) -> None:
        for selected, message in (
            (["missing-case"], "exist"),
            (["case-001", "case-001"], "unique"),
        ):
            with self.subTest(selected=selected):
                with self.assertRaisesRegex(ValueError, message):
                    ReviewState(
                        self.candidates,
                        self.directory / "adjudicator.json",
                        "adjudicator",
                        20,
                        None,
                        selected,
                    )


if __name__ == "__main__":
    unittest.main()
