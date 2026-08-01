from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.v249.generation_runtime import GenerationLoadError
from scripts.v249.replay_runner import load_replay_manifest


REPO = Path(__file__).resolve().parents[2]
REPLAY_PATH = Path("references/legacy-replay/manifest.json")
HAS_REPLAY_SUPPLEMENT = (REPO / REPLAY_PATH).is_file()


class TestV249ReplayBinding(unittest.TestCase):
    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional Replay supplement is not installed")
    def test_repository_replay_manifest_is_bound_by_active_generation(self) -> None:
        manifest = load_replay_manifest(REPO)

        self.assertEqual("GT-LEGACY-REPLAY-001", manifest["manifest_id"])

    @unittest.skipUnless(HAS_REPLAY_SUPPLEMENT, "optional Replay supplement is not installed")
    def test_replay_manifest_and_allowlist_cannot_be_rewritten_without_active_update(self) -> None:
        original = (REPO / REPLAY_PATH).read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / REPLAY_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = json.loads(original.decode("utf-8"))
            payload["manifest_id"] = "GT-LEGACY-REPLAY-TAMPERED"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            active_binding = {
                "activation_manifest": {
                    "legacy_classification": {
                        "replay_manifest_sha256": hashlib.sha256(original).hexdigest()
                    }
                },
                "optional_replay_allowlist_digest": payload[
                    "optional_replay_allowlist_digest"
                ],
            }
            with mock.patch(
                "scripts.v249.replay_runner.load_generation", return_value=active_binding
            ):
                with self.assertRaises(GenerationLoadError) as caught:
                    load_replay_manifest(root)

            self.assertEqual("E_V249_REPLAY_ACTIVE_BINDING", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
