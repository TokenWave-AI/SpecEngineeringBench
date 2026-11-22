<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo-dark.png">
    <img src="logo.png" width="660" alt="SpecEngineeringBench">
  </picture>
</p>
<h1 align="center">SpecEngineeringBench</h1>
<p align="center">Evaluating Coding Agents as Autonomous Software Test Engineers</p>
<p align="center">
  <a href="https://tokenwave-ai.github.io/SpecEngineeringBench-Page/">Project page</a> ·
  <a href="https://tokenwave-ai.github.io/SpecEngineeringBench-Page/assets/paper.pdf">Paper</a> ·
  <a href="https://huggingface.co/datasets/Tokenwave-AI/SpecEngineeringBench">Dataset</a>
</p>

**SpecEngineeringBench** asks whether a coding agent can turn product requirements into tests that reveal defects in a prerelease repository. Each instance supplies an English product requirements document, a Python repository snapshot, and a configured execution environment, without an issue report or a location hint.

| | |
| --- | --- |
| Instances | 100 across 78 open-source Python repositories |
| Application categories | 16 |
| Recorded defect occurrences | 531, with 4–15 per instance |
| Task 1 | Write and register executable tests derived from the requirements |
| Task 2 | Report defects with execution evidence and file, function, and hunk locations |

## Quickstart

Install the evaluation toolkit with Python 3.10 or newer. The GitHub and Hugging Face repositories require their respective access permissions.

```bash
git clone https://github.com/TokenWave-AI/SpecEngineeringBench.git
cd SpecEngineeringBench
python -m venv .venv
source .venv/bin/activate
pip install .
hf auth login
specbench download ./dataset
tar -xzf ./dataset/data.tar.gz -C ./dataset
```

The archive contains `portable/manifest.json`, the instance directories and the Harbor task packages. Use `specbench download ./dataset --revision <commit>` to pin the Hub revision. The packaged verifier expects Linux x86-64, Python 3.12, Docker Engine with Compose v2 and BuildKit, and Harbor 0.23.0. The data card describes the release layout and evaluation inputs. [Hugging Face data card](https://huggingface.co/datasets/Tokenwave-AI/SpecEngineeringBench)

## Score a run

`specbench score` reads saved verifier outputs. Use one JSON object per line in a manifest, with one result per instance and task. Take the exact `instance_id` from `episodes[].id` in `portable/manifest.json`. Artifact paths are relative to the JSONL file.

```jsonl
{"instance_id":"pallets_flask/episode-0001","task":"task1","artifact":"results/flask/task1-metrics.json"}
{"instance_id":"pallets_flask/episode-0001","task":"task2","artifact":"results/flask/task2-metrics.json"}
```

```bash
specbench score runs.jsonl --catalog dataset/portable/manifest.json
```

Use Task 1 artifacts containing `test_metrics` and `testcase_results`, and Task 2 artifacts containing all six `localization_metrics`. The CLI summarizes the instances supplied and reports their count for each task. For a full benchmark comparison, include one successful verifier artifact for each instance in the release manifest for the selected task.

## Metrics

- **Task 1.** Head Pass Rate (HP) pools registered tests across scored instances. Fail-to-Pass Rate (F2P), Entry Coverage (EC), Change-focused Coverage (CFG), and the number of tests (Num) are averaged per instance. F2P counts tests that fail on the defective snapshot and pass on the repaired snapshot.
- **Task 2.** Localization recall (LR) and precision (LP) are averaged per instance at file, function, and hunk granularity. The verifier records hunk scores as `LR_line` and `LP_line`. The paper's hunk criterion uses a three-line tolerance in defective-snapshot coordinates.

Rates in the CLI output are fractions from 0 to 1. The paper reports them as percentages.

## Citation

```bibtex
@misc{wang2026specengineeringbench,
  title = {SpecEngineeringBench: Evaluating Coding Agents as Autonomous Software Test Engineers},
  author = {Wang, Xingjian and Wang, Shijian and Liu, Minghao and Zou, Ji and Yang, Zetao
            and Lei, Xinping and Liang, Yiming and Yan, Shen and Zhao, Enduo and Shen, Xiaoyang
            and Xuan, Weihao and Liu, Jiaheng and Zhang, Ge},
  year = {2026},
  url = {https://tokenwave-ai.github.io/SpecEngineeringBench-Page/}
}
```
