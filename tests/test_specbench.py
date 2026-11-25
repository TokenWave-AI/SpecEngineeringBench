import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval import specbench


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
            specbench.score(manifest)["task1"],
            {"instances": 2, "HP": 0.5, "F2P": 0.5, "EC": 0.5, "CFG": 0.5, "Num": 2, "no_submission": 0},
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

    def test_release_no_submission_records_score_zero(self):
        # The three records written by the release verifiers when an agent submits nothing.
        metrics_file = {"status": "no_submission", "test_metrics": dict.fromkeys(specbench.TEST_METRICS, 0.0)}
        status_file = {"status": "no_submission", "reason": "absent_or_empty_submission", "task": "1"}
        empty_file = {"status": "scored", "reason": "required submission absent", "task": "task1"}
        scored = {
            "status": "scored",
            "test_metrics": {"HP": 1, "F2P": 1, "EC": 0.8, "CFG": 0.4, "Num": 2},
            "testcase_results": {"a": {"fixed_exit": 0}, "b": {"fixed_exit": 0}},
        }
        manifest = self.manifest(
            *(
                {"instance_id": name, "task": "task1", "artifact": self.artifact(f"{name}.json", data)}
                for name, data in (
                    ("metrics", metrics_file),
                    ("status", status_file),
                    ("empty", empty_file),
                    ("scored", scored),
                )
            )
        )
        self.assertEqual(
            specbench.score(manifest)["task1"],
            {"instances": 4, "HP": 1.0, "F2P": 0.25, "EC": 0.2, "CFG": 0.1, "Num": 0.5, "no_submission": 3},
        )

    def test_task2_no_submission_scores_zero(self):
        status_file = {"status": "no_submission", "reason": "absent_or_empty_submission", "task": "2"}
        metrics = dict.fromkeys(specbench.LOCALIZATION_METRICS, 1.0)
        manifest = self.manifest(
            {"instance_id": "absent", "task": "task2", "artifact": self.artifact("absent.json", status_file)},
            {
                "instance_id": "found",
                "task": "task2",
                "artifact": self.artifact("found.json", {"status": "scored", "localization_metrics": metrics}),
            },
        )
        result = specbench.score(manifest)["task2"]
        self.assertEqual((result["file"], result["no_submission"]), ({"LR": 0.5, "LP": 0.5}, 1))

    def test_no_submission_record_for_other_task_rejected(self):
        status_file = {"status": "no_submission", "task": "2"}
        manifest = self.manifest(
            {"instance_id": "x", "task": "task1", "artifact": self.artifact("s.json", status_file)}
        )
        with self.assertRaisesRegex(ValueError, "not task1"):
            specbench.score(manifest)

    def test_require_complete_lists_missing_instances(self):
        self.artifact("catalog.json", {"episodes": [{"id": "a/episode-0001"}, {"id": "b/episode-0001"}]})
        artifact = self.artifact("run.json", {"status": "no_submission"})
        manifest = self.manifest({"instance_id": "a/episode-0001", "task": "task1", "artifact": artifact})
        catalog = self.root / "catalog.json"
        self.assertEqual(specbench.score(manifest, catalog)["task1"]["instances"], 1)
        with self.assertRaisesRegex(ValueError, "task1 lacks 1 of 2: b/episode-0001"):
            specbench.score(manifest, catalog, require_complete=True)

    def test_require_complete_needs_catalog(self):
        manifest = self.manifest({"instance_id": "a", "task": "task1", "artifact": self.artifact("r.json", {})})
        with self.assertRaisesRegex(ValueError, "needs --catalog"):
            specbench.score(manifest, require_complete=True)

    def trial(self, job, name, task_path, files, finished="2026-11-25T10:00:00", exception=None):
        trial = self.root / "jobs" / job / name
        trial.mkdir(parents=True)
        result = {"task_id": {"path": task_path}, "trial_name": name, "finished_at": finished}
        if exception:
            result["exception_info"] = {"exception_type": exception}
        (trial / "result.json").write_text(json.dumps(result), encoding="utf-8")
        for relative, data in files.items():
            (trial / relative).parent.mkdir(parents=True, exist_ok=True)
            (trial / relative).write_text(json.dumps(data), encoding="utf-8")
        return trial

    def test_collect_builds_manifest_from_harbor_jobs(self):
        scored = {"status": "scored", "localization_metrics": dict.fromkeys(specbench.LOCALIZATION_METRICS, 0.5)}
        self.trial(
            "run",
            "task2__a",
            "/data/portable/pallets_flask/episode-0001/task2",
            {"artifacts/task2-metrics.json": scored},
        )
        self.trial(
            "run",
            "task1__b",
            "pallets_flask/episode-0001/task1",
            {"verifier/empty-submission.json": {"reason": "required submission absent", "task": "task1"}},
        )
        self.trial(
            "run",
            "task1__c",
            "boto_boto3/episode-0001/task1",
            {"artifacts/task1-submission-status.json": {"status": "no_submission", "task": "1"}},
        )
        (self.root / "jobs/run/result.json").write_text(json.dumps({"n_total_trials": 3}), encoding="utf-8")
        output = self.root / "out/runs.jsonl"
        output.parent.mkdir()
        self.assertEqual(specbench.collect(self.root / "jobs", output), [])
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        self.assertEqual(
            [(row["instance_id"], row["task"], Path(row["artifact"]).name) for row in rows],
            [
                ("boto_boto3/episode-0001", "task1", "task1-submission-status.json"),
                ("pallets_flask/episode-0001", "task1", "empty-submission.json"),
                ("pallets_flask/episode-0001", "task2", "task2-metrics.json"),
            ],
        )
        self.assertEqual(specbench.score(output)["task2"]["file"], {"LR": 0.5, "LP": 0.5})

    def test_collect_reports_crashed_and_duplicate_trials(self):
        self.trial("a", "task1__x", "nltk/episode-0001/task1", {}, exception="RuntimeError")
        status = {"artifacts/task1-submission-status.json": {"status": "no_submission", "task": "1"}}
        self.trial("a", "task1__y", "pydantic/episode-0001/task1", status, finished="2026-11-25T09:00:00")
        newer = self.trial("b", "task1__z", "pydantic/episode-0001/task1", status, finished="2026-11-25T11:00:00")
        output = self.root / "runs.jsonl"
        problems = specbench.collect(self.root / "jobs", output)
        self.assertEqual(len(problems), 2)
        self.assertIn("nltk/episode-0001 (task1) has no verifier record (RuntimeError)", problems[0])
        self.assertIn("second result for pydantic/episode-0001", problems[1])
        self.assertEqual(specbench.collect(self.root / "jobs", output, latest=True)[1:], [])
        self.assertIn(str(newer.relative_to(self.root)), output.read_text())

    def test_collect_ignores_agent_written_metrics(self):
        fake = {"agent/task1-metrics.json": {"status": "scored"}}
        self.trial("a", "task1__x", "nltk/episode-0001/task1", fake, exception="AgentTimeoutError")
        problems = specbench.collect(self.root / "jobs", self.root / "runs.jsonl")
        self.assertIn("no verifier record", problems[0])

    def test_reward_json_is_scored_when_no_metrics_file_was_copied(self):
        # Real verifier/reward.json files from the Harbor end-to-end run (flask Task 1, textual Task 2, xlrd nop).
        task1 = {"HP": 0.9545454545454546, "F2P": 0.5, "EC": 0.9081632653061225, "CFG": 0.9423076923076923, "Num": 22}
        task2 = dict.fromkeys(specbench.LOCALIZATION_METRICS, 0.25)
        manifest = self.manifest(
            {"instance_id": "a", "task": "task1", "artifact": self.artifact("a.json", {**task1, "reward": 0.83})},
            {"instance_id": "b", "task": "task1", "artifact": self.artifact("b.json", {"reward": 0.0})},
            {"instance_id": "a", "task": "task2", "artifact": self.artifact("c.json", {"reward": 0.25, **task2})},
        )
        result = specbench.score(manifest)
        self.assertEqual((result["task1"]["HP"], result["task1"]["Num"]), (21 / 22, 11))
        self.assertEqual((result["task1"]["F2P"], result["task1"]["no_submission"]), (0.25, 1))
        self.assertEqual(result["task2"]["hunk"], {"LR": 0.25, "LP": 0.25})

    def test_reward_json_without_metrics_is_rejected_unless_zero(self):
        for reward, message in (({"reward": 0.4}, "no task1 metrics"), ({"reward": 0.4, "HP": 1.0}, "lacks")):
            manifest = self.manifest({"instance_id": "a", "task": "task1", "artifact": self.artifact("r.json", reward)})
            with self.subTest(reward=reward), self.assertRaisesRegex(ValueError, message):
                specbench.score(manifest)

    def test_collect_prefers_metrics_over_reward_json(self):
        metrics = {"status": "scored", "localization_metrics": dict.fromkeys(specbench.LOCALIZATION_METRICS, 0.5)}
        files = {"verifier/artifacts/task2-metrics.json": metrics, "verifier/reward.json": {"reward": 0.5}}
        self.trial("a", "task2__x", "textual/episode-0001/task2", files)
        self.trial("a", "task1__y", "boto_boto3/episode-0001/task1", {"verifier/reward.json": {"reward": 0.0}})
        output = self.root / "runs.jsonl"
        self.assertEqual(specbench.collect(self.root / "jobs", output), [])
        names = [Path(json.loads(line)["artifact"]).name for line in output.read_text().splitlines()]
        self.assertEqual(names, ["reward.json", "task2-metrics.json"])

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
