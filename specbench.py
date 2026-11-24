"""Download benchmark data and aggregate saved verifier results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import fmean
from typing import Any

DATASET = "Tokenwave-AI/SpecEngineeringBench"
ARCHIVE = "data.tar.gz"
TEST_METRICS = ("HP", "F2P", "EC", "CFG", "Num")
LOCALIZATION_METRICS = ("LR", "LP", "LR_function", "LP_function", "LR_line", "LP_line")
TASKS = ("task1", "task2")


def as_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def read_json(path: Path) -> dict[str, Any]:
    return as_object(json.loads(path.read_text(encoding="utf-8")))


def fraction(value: Any) -> float:
    if type(value) not in (int, float) or not 0 <= value <= 1:
        raise ValueError(f"expected a metric from 0 to 1, got {value!r}")
    return float(value)


def test_counts(artifact: dict[str, Any]) -> tuple[int, int]:
    metrics = as_object(artifact["test_metrics"])
    count = metrics["Num"]
    results = as_object(artifact["testcase_results"])
    if type(count) is not int or count < 0 or len(results) != count:
        raise ValueError("Num must equal the number of registered testcase results")
    passed = sum(as_object(result)["fixed_exit"] == 0 for result in results.values())
    if abs(fraction(metrics["HP"]) * count - passed) > 1e-8:
        raise ValueError("HP disagrees with repaired-snapshot test outcomes")
    return passed, count


def is_absent_submission(artifact: dict[str, Any], task: str) -> bool:
    """Recognize the three zero-score records that release verifiers write when nothing was submitted."""
    if artifact.get("status") == "no_submission":
        # task<N>-metrics.json carries zeroed metrics; task<N>-submission-status.json names the task as "1" or "2".
        recorded = artifact.get("task", task)
        if recorded not in (task, task.removeprefix("task")):
            raise ValueError(f"submission status is for task {recorded!r}, not {task}")
        return True
    if artifact.get("reason") == "required submission absent":
        # verifier/empty-submission.json
        if artifact.get("task", task) != task:
            raise ValueError(f"empty-submission record is for {artifact['task']!r}, not {task}")
        return True
    return False


def zero_submission(task: str) -> dict[str, Any]:
    if task == "task1":
        return {"test_metrics": dict.fromkeys(TEST_METRICS, 0), "testcase_results": {}}
    return {"localization_metrics": dict.fromkeys(LOCALIZATION_METRICS, 0.0)}


def summarize_tests(artifacts: list[dict[str, Any]]) -> dict[str, float | int]:
    passed, count = map(sum, zip(*(test_counts(artifact) for artifact in artifacts)))
    per_instance = [as_object(artifact["test_metrics"]) for artifact in artifacts]
    return {
        "instances": len(artifacts),
        "HP": passed / count if count else 0.0,
        **{name: fmean(fraction(row[name]) for row in per_instance) for name in ("F2P", "EC", "CFG")},
        "Num": count / len(artifacts),
    }


def summarize_reports(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    per_instance = [as_object(artifact["localization_metrics"]) for artifact in artifacts]
    values = {metric: fmean(fraction(row[metric]) for row in per_instance) for metric in LOCALIZATION_METRICS}
    return {
        "instances": len(artifacts),
        "file": {"LR": values["LR"], "LP": values["LP"]},
        "function": {"LR": values["LR_function"], "LP": values["LP_function"]},
        "hunk": {"LR": values["LR_line"], "LP": values["LP_line"]},
    }


def read_artifact(row: dict[str, Any], manifest: Path) -> tuple[str, str, dict[str, Any]]:
    instance = row["instance_id"]
    task = row["task"]
    if not isinstance(instance, str) or not instance.strip() or task not in ("task1", "task2"):
        raise ValueError("expected an instance_id and task1 or task2")
    artifact = read_json(manifest.parent / row["artifact"])
    if is_absent_submission(artifact, task):
        return instance, task, {**zero_submission(task), "no_submission": True}
    if artifact.get("status", "scored") != "scored":
        raise ValueError(f"verifier status for {instance} is {artifact['status']!r}; rerun its evaluation")
    return instance, task, artifact


def load_runs(manifest: Path, instance_ids: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {"task1": [], "task2": []}
    seen: set[tuple[str, str]] = set()
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            instance, task, artifact = read_artifact(as_object(json.loads(line)), manifest)
            key = (instance, task)
            if instance_ids is not None and instance not in instance_ids:
                raise ValueError(f"{instance!r} is absent from the dataset manifest")
            if key in seen:
                raise ValueError(f"duplicate result for {instance} ({task})")
        except (KeyError, OSError, TypeError, ValueError) as error:
            raise ValueError(f"{manifest}:{line_number}: {error}") from error
        seen.add(key)
        runs[task].append(artifact)
    if not seen:
        raise ValueError(f"{manifest}: no results")
    return runs


def missing_instances(manifest: Path, instance_ids: set[str]) -> dict[str, list[str]]:
    seen: dict[str, set[str]] = {task: set() for task in TASKS}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            seen[row["task"]].add(row["instance_id"])
    return {task: sorted(instance_ids - ids) for task, ids in seen.items() if ids and instance_ids - ids}


def score(manifest: Path, catalog: Path | None = None, require_complete: bool = False) -> dict[str, Any]:
    if require_complete and catalog is None:
        raise ValueError("--require-complete needs --catalog")
    instance_ids = {episode["id"] for episode in read_json(catalog)["episodes"]} if catalog else None
    results = load_runs(manifest, instance_ids)
    if require_complete and instance_ids is not None:
        missing = missing_instances(manifest, instance_ids)
        if missing:
            details = "; ".join(
                f"{task} lacks {len(ids)} of {len(instance_ids)}: {', '.join(ids[:5])}{' ...' if len(ids) > 5 else ''}"
                for task, ids in missing.items()
            )
            raise ValueError(f"incomplete run ({details})")
    summaries = {"task1": summarize_tests, "task2": summarize_reports}
    return {
        task: {**summaries[task](artifacts), "no_submission": sum(bool(a.get("no_submission")) for a in artifacts)}
        for task, artifacts in results.items()
        if artifacts
    }


def download(output: Path, revision: str) -> str:
    from huggingface_hub import hf_hub_download

    return hf_hub_download(DATASET, ARCHIVE, repo_type="dataset", revision=revision, local_dir=output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download", help="download the dataset archive")
    fetch.add_argument("output", type=Path)
    fetch.add_argument("--revision", default="main", help="Hugging Face commit, tag, or branch")
    summarize = commands.add_parser("score", help="summarize a JSONL manifest of verifier results")
    summarize.add_argument("manifest", type=Path)
    summarize.add_argument("--catalog", type=Path, help="portable/manifest.json for validating instance IDs")
    summarize.add_argument(
        "--require-complete",
        action="store_true",
        help="fail unless every scored task has a result for each catalog instance",
    )
    arguments = parser.parse_args()
    if arguments.command == "download":
        print(download(arguments.output, arguments.revision))
        return
    try:
        result = score(arguments.manifest, arguments.catalog, arguments.require_complete)
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(2, f"specbench: {error}\n")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
