import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import specbench


class ScoringTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def artifact(self, name, data):
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")
        return name

    def manifest(self, *rows):
        path = self.root / "runs.jsonl"
        path.write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")
        return path

    def test_pooled_hp_and_per_instance_means(self):
        first = {
            "status": "scored",
            "test_metrics": {"HP": 1, "F2P": 1, "EC": 0.4, "CFG": 0.2, "Num": 1},
            "testcase_results": {"a": {"fixed_exit": 0}},
        }
        second = {
            "status": "scored",
            "test_metrics": {"HP": 1 / 3, "F2P": 0, "EC": 0.6, "CFG": 0.8, "Num": 3},
            "testcase_results": {str(i): {"fixed_exit": i} for i in range(3)},
        }
        manifest = self.manifest(
            {"instance_id": "first", "task": "task1", "artifact": self.artifact("first.json", first)},
            {"instance_id": "second", "task": "task1", "artifact": self.artifact("second.json", second)},
        )
        self.assertEqual(
            specbench.score(manifest)["task1"], {"instances": 2, "HP": 0.5, "F2P": 0.5, "EC": 0.5, "CFG": 0.5, "Num": 2}
        )

    def test_empty_registered_suite(self):
        metrics = {
            "test_metrics": {"HP": 0, "F2P": 0, "EC": 0, "CFG": 0, "Num": 0},
            "testcase_results": {},
        }
        self.assertEqual(specbench.summarize_tests([metrics])["HP"], 0)

    def test_hunk_is_named_line_in_verifier_output(self):
        metrics = dict.fromkeys(specbench.LOCALIZATION_METRICS, 0.25)
        metrics["LR_line"] = 0.75
        self.assertEqual(
            specbench.summarize_reports([{"localization_metrics": metrics}])["hunk"], {"LR": 0.75, "LP": 0.25}
        )

    def test_invalid_metric(self):
        for value in ("1", True, -0.01, float("nan"), 1.01):
            with self.subTest(value=value), self.assertRaises(ValueError):
                specbench.fraction(value)

    def test_duplicate_instance_and_task_rejected(self):
        artifact = self.artifact("run.json", {})
        row = {"instance_id": "example", "task": "task1", "artifact": artifact}
        with self.assertRaisesRegex(ValueError, "duplicate result"):
            specbench.load_runs(self.manifest(row, row))

    def test_failed_environment_rejected(self):
        artifact = self.artifact("failed.json", {"status": "invalid_environment"})
        manifest = self.manifest({"instance_id": "example", "task": "task1", "artifact": artifact})
        with self.assertRaisesRegex(ValueError, "invalid_environment"):
            specbench.score(manifest)

    def test_missing_result_file_has_manifest_context(self):
        manifest = self.manifest({"instance_id": "example", "task": "task1", "artifact": "missing.json"})
        with self.assertRaisesRegex(ValueError, "runs.jsonl:1"):
            specbench.score(manifest)

    def test_unknown_instance_rejected_against_dataset_catalog(self):
        self.artifact("catalog.json", {"episodes": [{"id": "project/episode-0001"}]})
        artifact = self.artifact("run.json", {})
        manifest = self.manifest({"instance_id": "wrong", "task": "task2", "artifact": artifact})
        with self.assertRaisesRegex(ValueError, "absent from the dataset manifest"):
            specbench.score(manifest, self.root / "catalog.json")

    @patch("huggingface_hub.hf_hub_download", return_value="output/data.tar.gz")
    def test_download_targets_dataset_and_revision(self, download):
        self.assertEqual(specbench.download(Path("output"), "release-sha"), "output/data.tar.gz")
        download.assert_called_once_with(
            "Tokenwave-AI/SpecEngineeringBench",
            "data.tar.gz",
            repo_type="dataset",
            revision="release-sha",
            local_dir=Path("output"),
        )


if __name__ == "__main__":
    unittest.main()
