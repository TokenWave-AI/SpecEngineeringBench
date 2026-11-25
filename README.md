<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo-dark.png">
    <img src="logo.png" width="660" alt="SpecEngineeringBench">
  </picture>
</p>
<h1 align="center">SpecEngineeringBench</h1>
<p align="center">Evaluating Coding Agents as Autonomous Specification Engineers</p>
<p align="center">
  <a href="https://tokenwave-ai.github.io/SpecEngineeringBench-Page/">Project page</a> ·
  <a href="https://arxiv.org/abs/2611.32973">Paper</a> ·
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

Install the evaluation toolkit with Python 3.10 or newer. It lives in the `eval/` package and installs the `specbench` command (`download`, `collect`, `score`); `tests/` holds its unit tests. The GitHub and Hugging Face repositories require their respective access permissions.

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

The archive contains `portable/manifest.json`, the instance directories and the Harbor task packages. Use `specbench download ./dataset --revision <commit>` to pin the Hub revision. The paper's experiments used revision `059688e`; later revisions fix two packaging defects, listed on the data card, without changing scoring code or task inputs. The data card describes the release layout and evaluation inputs. [Hugging Face data card](https://huggingface.co/datasets/Tokenwave-AI/SpecEngineeringBench)

## Run an agent

Each instance has two Harbor task packages, `<repository>/<episode>/task1` and `.../task2`. Run them with Harbor 0.23.0 on Linux x86-64 with Docker Engine, Compose v2 and BuildKit. Every task builds its agent image and a separate verifier image from source, so both need internet access during the build.

```bash
pip install "harbor==0.23.0"
cd dataset/portable
harbor run --path pallets_flask/episode-0001/task1 --agent codex --model openai/gpt-5.6-sol --jobs-dir ../../jobs
harbor run --path pallets_flask/episode-0001/task2 --agent codex --model openai/gpt-5.6-sol --jobs-dir ../../jobs
```

`portable/run_common.sh <task path>` wraps the same command with the settings used for the paper (one attempt, five-fold agent and verifier timeouts); `HARBOR_AGENT`, `HARBOR_MODEL` and `HARBOR_JOBS_DIR` override them.

Eleven instances ship their own launcher, `task<N>/tests/build/run_harbor.py`, which runs Harbor with the bundled environment provider the verifier expects. Use it for those instances, with Python 3.12 and the packages in `tests/build/runtime-requirements.txt`:

```bash
python boto_boto3/episode-0001/task1/tests/build/run_harbor.py --agent codex --model openai/gpt-5.6-sol --jobs-dir ../../jobs
```

The instances are boto3, cherrypy, django-haystack, encode/httpcore, flask-restx, jupyter_client, nbconvert, oauthlib, parso, peewee and xlrd; `ls */*/task1/tests/build/run_harbor.py` lists them.

Agents run with `network_mode = "no-network"`, which Harbor's Docker environment enforces with nftables, so the host kernel needs nftables support; the bundled launchers require it as well. Harnesses that call a model API from inside the task container, such as Codex and Claude Code, need an egress exception for the API host only. Harbor's `--allow-agent-host` provides one. The paper instead ran each instance in its own E2B sandbox, whose kernel lacks nftables: Harbor kept the container network public, E2B limited sandbox egress to the model API during the agent phase, and the agent container was detached before the separate verifier started.

## Score a run

Collect the results, then score them. `specbench collect` finds every trial under a Harbor jobs directory, picks the record the verifier wrote, and writes the manifest that `specbench score` reads:

```bash
specbench collect jobs -o runs.jsonl --catalog dataset/portable/manifest.json
specbench score runs.jsonl --catalog dataset/portable/manifest.json --require-complete
```

`collect` exits non-zero and names the trial when a trial crashed before the verifier wrote a record, or when the same instance and task was run twice. Rerun the crashed trial, or pass `--latest` to keep the newest of repeated runs.

The manifest has one JSON object per line, with one result per instance and task, if you prefer to write it yourself. Take the exact `instance_id` from `episodes[].id` in `portable/manifest.json`. Artifact paths are relative to the JSONL file.

```jsonl
{"instance_id":"pallets_flask/episode-0001","task":"task1","artifact":"jobs/flask-t1/task1__a1b2c3/verifier/artifacts/task1-metrics.json"}
{"instance_id":"pallets_flask/episode-0001","task":"task2","artifact":"jobs/flask-t2/task2__d4e5f6/verifier/artifacts/task2-metrics.json"}
```

A scored trial writes `task1-metrics.json` or `task2-metrics.json` under the trial directory. When the agent submits nothing, the verifier assigns a reward of zero and writes one of three records, depending on the instance package:

| Record | Contents |
| --- | --- |
| `artifacts/task<N>-metrics.json` | `"status": "no_submission"` with all metrics set to zero |
| `artifacts/task<N>-submission-status.json` | `"status": "no_submission"`, without metrics |
| `verifier/empty-submission.json` | `"reason": "required submission absent"`, without metrics |

`specbench score` counts all three as zero on every metric and reports them as `no_submission`, matching the paper, which averages over all 100 instances. A missing submission adds no tests to the pooled HP denominator. Any other non-`scored` status means the evaluation itself failed, and the CLI asks you to rerun it.

`--require-complete` fails unless every task in the manifest has a result for each instance in the catalog, and lists the missing IDs. Without it, the CLI summarizes only the instances supplied, so dropping a trial would inflate the averages.

## Metrics

- **Task 1.** Head Pass Rate (HP) pools registered tests across scored instances. Fail-to-Pass Rate (F2P), Entry Coverage (EC), Change-focused Coverage (CFG), and the number of tests (Num) are averaged per instance. F2P counts tests that fail on the defective snapshot and pass on the repaired snapshot.
- **Task 2.** Localization recall (LR) and precision (LP) are averaged per instance at file, function, and hunk granularity. The verifier records hunk scores as `LR_line` and `LP_line`. The paper's hunk criterion uses a three-line tolerance in defective-snapshot coordinates.

Rates in the CLI output are fractions from 0 to 1. The paper reports them as percentages.

## Citation

```bibtex
@misc{wang2026specengineeringbench,
  title = {SpecEngineeringBench: Evaluating Coding Agents as Autonomous Specification Engineers},
  author = {Wang, Xingjian and Wang, Shijian and Liu, Minghao and Zou, Ji and Yang, Zetao
            and Lei, Xinping and Liang, Yiming and Yan, Shen and Zhao, Enduo and Shen, Xiaoyang
            and Xuan, Weihao and Liu, Jiaheng and Zhang, Ge},
  year = {2026},
  eprint = {2611.32973},
  archivePrefix = {arXiv},
  primaryClass = {cs.SE},
  url = {https://arxiv.org/abs/2611.32973}
}
```
