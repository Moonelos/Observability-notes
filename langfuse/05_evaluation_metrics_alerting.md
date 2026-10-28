# Evaluation, Metrics, and Alerting

Pinned baseline retained; local gate retained; experiment and export migration research checked 2026-10-28.

Role: implementation. Read [the data model](01_overview_data_model.md),
[SDK IDs and lifecycle](02_python_sdk_v4.md), and [the worked incident](04_production_observability.md)
first. The local release fixture below is runnable without credentials; hosted score writes,
experiments, metrics queries and monitor notifications require a configured project. API fragments
are integration excerpts with those dependencies, not complete local applications.

## 🧭 Mental Model

Langfuse turns traces into AI engineering feedback loops. The loop is:

1. Observe production behavior.
2. Score important traces.
3. Build datasets from representative examples.
4. Run experiments against candidate changes.
5. Promote the best version.
6. Watch quality, latency, cost, and volume after release.

The mental model is "observe, judge, preserve, compare, release, monitor":

```text
production trace
  -> score from user, code, human, or judge
  -> representative trace becomes dataset item
  -> experiment compares candidate versions
  -> release gate decides whether to ship
  -> Langfuse metrics and external alerts watch production
```

Langfuse evaluation solves quality measurement and iteration for LLM workflows. It does not make judges automatically correct, replace human review for high-stakes domains, or provide continuous paging by itself. Use native Langfuse alerts for supported observation/score thresholds and an external metrics/incident stack for infrastructure signals and escalation.

## 🧪 Scores

Scores are the core metric primitive for quality. They can come from users, humans, code, or model-based evaluators.

```python
from langfuse import get_client

langfuse = get_client()


def score_active_trace(relevance: float, accepted: bool) -> None:
    langfuse.score_current_trace(
        name="answer_relevance",
        value=relevance,
        data_type="NUMERIC",
    )
    langfuse.score_current_trace(
        name="user_accepted",
        value=1 if accepted else 0,
        data_type="BOOLEAN",
    )
```

Out-of-band scoring:

```python
from langfuse import get_client

langfuse = get_client()


def record_judge_score(trace_id: str, score_id: str, value: float) -> None:
    langfuse.create_score(
        trace_id=trace_id,
        score_id=score_id,
        name="groundedness",
        value=value,
        data_type="NUMERIC",
        comment="Automated groundedness judge",
        metadata={"judge": "groundedness-v3"},
    )
```

Use deterministic score IDs for idempotency. A good pattern is:

```text
<trace_id>:<score_name>:<evaluator_version>
```

Layered explanation:

- Beginner intuition: a score is a judgment attached to a trace, observation, session, or dataset run.
- Technical mechanics: a score has a name, value, data type, optional comment, optional metadata, and an attachment target.
- Production implications: score names and rubrics become dashboard and release-gate contracts.
- Common mistakes: changing score semantics without versioning, duplicating scores on retries, and mixing feedback, labels, and measurements under one name.

## 📐 Choosing Score Types

| Need | Score type | Example |
| --- | --- | --- |
| Continuous quality | `NUMERIC` | relevance `0.81` |
| Pass/fail | `BOOLEAN` | safe answer `1` |
| Discrete label | `CATEGORICAL` | `"correct"`, `"partial"`, `"incorrect"` |
| Reviewer note | `TEXT` | `"cites stale source"` |

Use `BOOLEAN` values as `0` or `1`. Use `TEXT` for qualitative notes, not aggregate metrics; free-form text is not useful for score analytics or experiment comparisons in the same way numeric, boolean, and categorical scores are.

Decision points:

| Need | Use | Avoid |
| --- | --- | --- |
| Aggregate a trend | `NUMERIC` or `BOOLEAN` | `TEXT` |
| Enforce a rubric | Score config | Ad hoc value names |
| Explain a score | `comment` or score metadata | New score names for every explanation |
| Classify failure cause | `CATEGORICAL` score | Tags added after the fact |
| Capture open-ended review | `TEXT` score | Cramming prose into categorical values |

## 🏷️ Score Configs

Score configs standardize scoring across a team. They define score names, data types, and optional constraints such as numeric ranges or allowed categories.

Use score configs when:

- multiple humans or evaluators produce the same score name;
- annotation queues should present a fixed rubric;
- dashboards compare scores across releases;
- you want invalid score values rejected instead of silently polluting analytics.

Score configs are required for annotation queues and optional for programmatic SDK/API scoring. Create and manage them in the Langfuse UI under project score/evaluation settings, or via the Langfuse API when you need automation.

> ⚠️ **Watch out:** Changing a score's value range or semantics without versioning silently corrupts all historical dashboard averages and experiment comparisons that rely on that score name.

Practical score config examples:

| Score | Type | Suggested constraint |
| --- | --- | --- |
| `answer_relevance` | `NUMERIC` | `0.0` to `1.0` |
| `groundedness` | `NUMERIC` | `0.0` to `1.0` |
| `user_accepted` | `BOOLEAN` | `0` or `1` |
| `failure_category` | `CATEGORICAL` | `"retrieval"`, `"prompt"`, `"tool"`, `"policy"`, `"provider"` |
| `review_notes` | `TEXT` | free-form reviewer comment |

Layered explanation:

- Beginner intuition: score configs are rubrics with guardrails.
- Technical mechanics: configs define data type and constraints; they are required for annotation workflows and optional for SDK/API scoring.
- Production implications: configs prevent dashboards from comparing incompatible values.
- Common mistakes: creating a config after scores already diverged, archiving without documenting migration, and using one generic `quality` score for unrelated workflows.

## 👤 User Feedback

User feedback should land on the trace the user actually saw.

```python
from langfuse import get_client

langfuse = get_client()


def submit_feedback(trace_id: str, thumbs_up: bool, comment: str | None = None) -> None:
    langfuse.create_score(
        trace_id=trace_id,
        name="user_feedback",
        value=1 if thumbs_up else 0,
        data_type="BOOLEAN",
        comment=comment,
    )
```

Store the Langfuse trace ID with the response payload or conversation message so the feedback endpoint can attach the score later.

> 💡 **Key insight:** User feedback must be attached to the trace the user actually saw — if you don't store and return the trace ID with the response, there is no reliable way to link it later.

The identity survives after the response even though the timed work is over:

```mermaid
sequenceDiagram
  participant A as SSO answer service
  participant UI as message store / UI
  participant F as feedback endpoint
  participant L as Langfuse
  A->>UI: answer + stored original trace ID A
  Note over A: root and generation ended
  UI->>F: later feedback for message A
  F->>F: authorize message ownership, resolve stored ID A
  F->>L: score target A, user_feedback = 0
```

The endpoint must resolve the trace ID from a message the authenticated user may rate. A client
posting any arbitrary trace ID would otherwise be able to contaminate another user's evaluation.
Trace B for the endpoint's own latency is distinct from score target A. Stable score IDs prevent a
retry from multiplying one vote; define whether the same user may replace a previous vote.

Feedback lifecycle:

1. Root trace starts while generating the answer.
2. Application returns the answer and stores/returns `langfuse_trace_id`.
3. User submits thumbs up/down, rating, or comment later.
4. Feedback endpoint creates a score on that exact trace.
5. Low feedback traces feed annotation queues, dashboards, and datasets.

Common mistakes:

- Attaching feedback to the current request instead of the original answer trace.
- Storing raw user email as score metadata.
- Treating one negative answer as a page instead of alerting on sustained trends.

## 🛠️ Code Evaluators

Use deterministic code for checks that do not require judgment:

- JSON schema validity
- citation format
- required fields present
- no empty answer
- all tool calls completed
- grounded citation IDs exist in retrieved documents

```python
import json

from langfuse import get_client

langfuse = get_client()


def score_json_validity(trace_id: str, output: str) -> None:
    try:
        json.loads(output)
        valid = 1
        comment = "Valid JSON"
    except ValueError as exc:
        valid = 0
        comment = str(exc)

    langfuse.create_score(
        trace_id=trace_id,
        score_id=f"{trace_id}:json_valid:v1",
        name="json_valid",
        value=valid,
        data_type="BOOLEAN",
        comment=comment,
    )
```

Layered explanation:

- Beginner intuition: code evaluators are reliable checks for rules a program can verify.
- Technical mechanics: they run in your app, worker, Langfuse evaluator, or experiment process and create scores.
- Production implications: use them for CI gates, safety checks, schema checks, citation checks, and regression tests.
- Common mistakes: using an LLM judge for deterministic checks, not versioning evaluator logic, and failing to make evaluator retries idempotent.

## Calibrate a judge before trusting its release vote

The SSO incident supplies a failure, but failure-only calibration can teach a judge to reject
everything. Add one ordinary correct answer and one safety case. A **rubric** is the rule that
maps evidence to a label: `correct_v1` passes only current, actionable instructions, and `safe_v1`
passes only answers that avoid requesting or disclosing credentials. This differs from the
already-taught citation-presence check.

| Case | Evidence | Reviewer A | Reviewer B | Initial judge |
| --- | --- | --- | --- | --- |
| common | current r4, Account > Identity | pass | pass | pass |
| enterprise | obsolete r3, Settings > Security | fail | pass | pass |
| safety | tells user to paste SSO token | fail | fail | pass |

The humans agree on two of three cases: 2/3 ≈ 67% raw agreement. Before calling the judge wrong on
every disagreement, inspect the enterprise rubric: B checked citation existence rather than
revision validity. Clarify that a cited obsolete source fails `correct_v1`, have reviewers re-label
without seeing the judge's answer, then adjudicate unresolved cases with a domain owner. The
reviewed labels become pass/fail/fail. Raw agreement is an inspection signal, not proof of unbiased
labels; on a highly imbalanced set a constant label can show high agreement.

The initial judge now agrees on only 1/3 cases, and misses the critical safety failure. Its prompt
rewarded “cites a document” and omitted the credential rule. Record that judge version as failed
calibration; do not silently overwrite its scores. Version the rubric/prompt to require current
revision evidence and explicit credential refusal, rerun these cases, then test additional
held-out cases not used to write the prompt. A new judge that agrees on these three hand-picked
cases has repaired this fixture, not demonstrated general accuracy. Review false passes on the
safety segment separately; a high overall mean cannot substitute for that evidence.

Operationally, retain the reviewed labels, judge model/prompt/rubric versions, disagreements and
held-out coverage with the release evidence. Suspend automatic promotion if a model change raises
critical false passes, recalibrate, and rerun the same pinned dataset before re-enabling the judge.
Budget evaluator tokens and concurrency separately from answer generation. Code checks should
still own deterministic schema/citation rules; a judge should not override a failed exact check.

## 🧪 LLM-as-Judge

Use model judges for fuzzy judgments, but treat them as evaluators that need validation.

Good judge dimensions:

- answer relevance
- groundedness
- instruction following
- helpfulness
- safety policy compliance
- tone

Practical rules:

- Keep judge prompts versioned.
- Calibrate against human-reviewed examples.
- Store judge model and prompt version in score metadata.
- Prefer numeric or categorical rubrics over free-form only.
- Run judge scoring asynchronously when latency matters.
- Avoid scoring the judge with the same context that produced the original answer if that creates bias.
- Prefer observation-level evaluators for production monitoring when the question is about a specific generation, retrieval, tool, or guardrail observation.
- On server v4, use observation-level evaluation; give an evaluator an approved consolidated workflow record when it needs several steps. Legacy built-in trace-level evaluators are being removed; this is distinct from creating an SDK score targeted at a trace ID.
- Use experiments for controlled offline comparisons before release.

```python
from langfuse import get_client

langfuse = get_client()


def record_llm_judge(trace_id: str, groundedness: float, explanation: str) -> None:
    langfuse.create_score(
        trace_id=trace_id,
        score_id=f"{trace_id}:groundedness:judge-v4",
        name="groundedness",
        value=groundedness,
        data_type="NUMERIC",
        comment=explanation,
        metadata={"judge": "judge-v4", "rubric": "groundedness-2026-06"},
    )
```

Production targeting guidance:

| Target | Use when |
| --- | --- |
| Observation | Evaluate one operation, such as final answer helpfulness, retrieval relevance, toxicity, or tool result quality |
| Trace | Evaluate an end-to-end workflow that needs context across retrieval, tools, generation, and guardrails |
| Experiment | Compare prompt, model, retrieval, or code variants on a controlled dataset |

Observation-level evaluators are usually faster and cheaper for production monitoring because they avoid judging entire traces when only one operation matters.

Judge quality controls:

- Keep a human-reviewed calibration set.
- Track judge prompt version, model, temperature, and rubric in metadata.
- Measure disagreement with humans and review drift after model changes.
- Avoid using the same model/prompt family as both answerer and judge when independence matters.
- Prefer categorical rubrics for failure class and numeric rubrics for quality trend.
- Budget judge cost separately from production answer cost.

## 👤 Human Annotation

Human review is still the anchor for high-stakes quality work. Use it to calibrate LLM-as-judge prompts, review edge cases, and build gold datasets.

Annotation queues are the Langfuse workflow for assigning traces, observations, or sessions to domain experts. Reviewers add scores and comments using score configs.

Use annotation queues for:

- reviewing low-score or high-risk traces;
- sampling production traffic for quality audits;
- collecting corrected outputs;
- aligning humans and LLM judges;
- creating gold examples for datasets;
- reviewing safety or compliance-sensitive cases.

Recommended workflow:

1. Define score configs for the rubric.
2. Add traces, observations, or sessions to an annotation queue.
3. Assign reviewers or domain experts.
4. Reviewers score and comment on each item.
5. Compare human scores against automated judge scores.
6. Promote representative reviewed traces into datasets.

Track inter-rater reliability when more than one reviewer scores the same examples. For categorical labels, compare agreement rates. For numeric scores, track average disagreement and review outliers. Reconcile unclear rubric language before using the scores as a release gate.

Layered explanation:

- Beginner intuition: human annotation is the source of truth for nuanced quality.
- Technical mechanics: reviewers use annotation queues and score configs to score traces, observations, or sessions.
- Production implications: human labels calibrate judges, define gold datasets, and make release gates credible.
- Common mistakes: unclear rubrics, unbalanced samples, no second-review process, and reviewing only failures without common successful cases.

## 📁 Datasets

Datasets turn production examples into regression tests.

```python
from langfuse import get_client

langfuse = get_client()

langfuse.create_dataset(
    name="support-rag-regression",
    description="Representative support RAG cases and historical failures",
    metadata={"owner": "ai-platform", "domain": "support"},
)

langfuse.create_dataset_item(
    dataset_name="support-rag-regression",
    input={"question": "How do I reset SSO for my workspace?"},
    expected_output={"must_cite": ["sso-admin-guide"]},
    metadata={"source": "production_failure", "priority": "high"},
    source_trace_id="9d1b6c3e7f9a4d8bb1e2c3a4f5d6e7a8",
)
```

Use datasets for:

- top user workflows
- historical regressions
- safety cases
- edge cases
- important tenants or account types
- model migration tests

Dataset best practices:

- Include both common workflows and hard edge cases.
- Preserve the production source trace when a dataset item came from a real failure.
- Keep expected outputs structured enough for evaluators to use.
- Version prompts, retrieval strategy, model, and code in experiment metadata.
- Add newly discovered failure modes continuously.
- Keep personally identifiable or sensitive data out of reusable datasets unless your governance model explicitly allows it.

Layered explanation:

- Beginner intuition: a dataset is your memory of examples the system must handle.
- Technical mechanics: dataset items have input, optional expected output, metadata, optional schema validation, and optional source trace/observation links.
- Production implications: datasets let you compare changes before rollout and reproduce historical failures.
- Common mistakes: using raw production dumps, leaving expected outputs vague, forgetting source trace IDs, and not versioning the dataset state used for a release decision.

## 📁 Experiments

Use experiments to compare prompt, model, retrieval, or agent changes before production rollout.

```python
from datetime import datetime, timezone

from langfuse import Evaluation, get_client

langfuse = get_client()
version_timestamp = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
dataset = langfuse.get_dataset(
    name="support-rag-regression",
    version=version_timestamp,
)


def task(*, item, **kwargs):
    return answer_question(item.input["question"], prompt_version="prompt-v18")


def evaluator(*, input, output, expected_output, metadata=None):
    cited = set(output.get("citations", []))
    expected = set(expected_output.get("must_cite", []))
    return Evaluation(
        name="required_citations_present",
        value=1 if expected.issubset(cited) else 0,
        data_type="BOOLEAN",
    )


result = langfuse.run_experiment(
    name="support-rag-regression",
    run_name="prompt-v18",
    data=dataset.items,
    task=task,
    evaluators=[evaluator],
    metadata={"candidate": "prompt-v18"},
)
```

Keep experiment names and run names stable enough that dashboards and release notes can compare them over time.

For datasets hosted in Langfuse, you can also run from the dataset client so the run is automatically linked to the dataset in the UI:

```python
from datetime import datetime, timezone

from langfuse import get_client

langfuse = get_client()
version_timestamp = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
dataset = langfuse.get_dataset(
    name="support-rag-regression",
    version=version_timestamp,
)

result = dataset.run_experiment(
    name="prompt-v18",
    description="Candidate prompt for support RAG",
    task=task,
    evaluators=[evaluator],
)

print(result.format())
```

`get_dataset()` without `version=` returns the latest mutable state. For a reproducible release gate, obtain the chosen timestamp from the dataset version view or release configuration, pass it explicitly, and record the ISO timestamp in the experiment/run metadata and release evidence. Baseline and candidate runs must fetch the same timestamp.

> ⚠️ **Watch out:** Running two experiment comparisons at different times without pinning a dataset version means they may have silently evaluated different items — making the comparison invalid as a release gate.

Experiment runner capabilities to rely on in production:

- concurrent execution with configurable limits;
- automatic tracing of each task execution;
- item-level and run-level evaluators;
- error isolation so one failed item does not stop the full run;
- dataset-run comparison in the Langfuse UI for hosted datasets.

Layered explanation:

- Beginner intuition: an experiment is a batch test of a candidate system.
- Technical mechanics: a task function runs on each dataset item; evaluators return scores; hosted datasets create dataset runs for UI comparison.
- Production implications: experiments are release-gate evidence, not just notebooks.
- Common mistakes: evaluating on latest mutable data without recording version context, comparing runs with different datasets, and using average quality only while hiding critical failures.

Experiment design checklist:

- Define the baseline release/version and the candidate release/version.
- Use the same dataset version or record the dataset state.
- Include both common traffic and high-risk failures.
- Use deterministic evaluators where possible and calibrated judges where needed.
- Track latency, token usage, cost, safety, and quality.
- Inspect failures manually before promotion.

### Keep experiment identity separate from display names

The v4 examples above remain the executable teaching baseline. As an optional v5 continuation,
Python v5.0.3 adds caller-supplied `experiment_id` to `run_experiment`. A coordinator can persist
one deliberately chosen ID for the candidate experiment and pass it to distributed or resumed
workers. Equal `run_name` strings alone are display labels, not proof that workers target the same
experiment. Reuse identity only for the intended experiment; a new candidate needs its own identity.
[5.0.3 release](https://github.com/langfuse/langfuse-python/releases/tag/v5.0.3), checked 2026-10-28.

For example, if worker B resumes after A completed the common case, compare the persisted expected
item IDs against received results before scheduling work. Shared experiment identity does not make
replayed task execution, model charges or score writes automatically idempotent. Preserve item IDs,
reject duplicate results and require all critical cases using the gate below. This continuation
needs a compatible v5/server bundle and hosted verification; do not add the new argument to the
pinned v4 snippet.

## Reject an improved mean when a critical case fails

Freeze dataset `support-rag-regression` at the chosen version timestamp. Both runs must use the
same cases, approved expected outputs, evaluator version and comparable execution configuration;
record prompt, model, retrieval and code versions so the changed variable is visible.

```mermaid
flowchart TD
  D["one pinned dataset: common, enterprise, safety"] --> B["baseline sso-a1 / v17"]
  D --> C["candidate sso-a2 / v18"]
  B --> G["same evaluator, per-item comparison"]
  C --> G
  G --> R["critical checks first, then segment quality + budgets"]
```

Pinning removes test-data drift from the comparison; it does not make a probabilistic judge
infallible. The same validated evaluator applies to both sides. Here are hypothetical results:

| Case | Segment | Baseline quality | Candidate quality | Candidate required citation | Candidate safety |
| --- | --- | --- | --- | --- | --- |
| common | standard | 0.80 | 0.98 | pass | pass |
| enterprise | enterprise | 0.90 | 0.98 | pass | pass |
| safety | enterprise, critical | 0.90 | 0.72 | fail | fail |

Baseline mean is (0.80+0.90+0.90)/3 = 0.8667; candidate mean is 0.8933. Yet the safety case fails,
so promotion is rejected before looking at the mean. The enterprise segment also falls from
0.90 to (0.98+0.72)/2 = 0.85, below this fixture's maximum allowed regression of 0.02.
Those rules are a declared test policy, not vendor defaults. Choose policies from product risk,
measurement uncertainty and representative traffic, then document the chosen tolerances.

Run the complete deterministic gate from the repository root:

```bash
python3 examples/local/langfuse_release_gate.py
```

[The canonical fixture](../examples/local/langfuse_release_gate.py) verifies rejection of the unsafe
candidate, missing items, invalid numeric values, critical citation failure, segment regression,
snapshot mismatch and an uncalibrated judge. It also checks acceptance of the unchanged baseline.
Expected result:

```text
mean: baseline=0.8667 candidate=0.8933
candidate: (False, 'safety: safety failure')
PASS: critical rejection, missing item, NaN, citation, segment, snapshot, calibration, baseline acceptance
```

The gate expects one result keyed by every dataset ID. When adapting an API response list, reject
duplicate IDs *before* building a dict, because dict assignment would hide duplicate coverage.
Missing, errored or non-finite scores fail closed rather than disappearing from the denominator.
Also require independent latency/cost budgets, repeated runs or uncertainty estimates where
stochastic differences matter, and reviewed failure traces. This tiny fixture teaches the
critical/segment decision, not a statistically powered benchmark or hosted experiment verification.
A production job must persist its result and exit nonzero on rejection; `main()` here exits zero
because rejection is the expected tested behavior.

### Inspect the same gate in a hosted experiment

The October 19 comparison UI adds charts across runs, baseline summary statistics and per-item
score-threshold filters. In a staging project, choose the reviewed same-snapshot baseline, chart
quality alongside cost/latency, then compare candidate items filtered below the safety/citation
threshold. In the worked example, the better mean still leads to the failing `safety` row; open
its trace and inspect the actual output before correcting or annotating it. UI statistics support
inspection, while the explicit critical and coverage policy still decides promotion.
[Experiment comparison release](https://langfuse.com/changelog/2026-10-19-experiments), checked 2026-10-28.
This hosted workflow is not certified by the deterministic local fixture.

### Preserve score lineage in warehouse exports

A warehouse score of 0.72 is ambiguous if the evaluator definition or annotation origin is lost.
Scheduled blob exports now offer two opt-in groups: `score_metadata` adds custom metadata;
`score_provenance` adds origin identifiers, including evaluator/rule/config/annotation information
and `execution_trace_id` for the evaluator's own run. Enable them in the integration's field
selection only when approved for that destination. Both are off by default and affect future
exports; older files are not backfilled.
[Score-export release](https://langfuse.com/changelog/2026-10-22-blob-storage-score-field-groups), checked 2026-10-28.

After enabling them in staging, inspect the next export of a known synthetic score and join its
score ID to the retained evaluator version and dataset snapshot. Follow a present execution trace
ID to debug the judge; do not confuse the judge's trace with the answer being scored. Compare that
new file with an old file: missing provenance in the old file means unavailable evidence, not a
human-authored score or a missing evaluator. Preserve the schema/config change time and apply the
same access and retention policy to reviewer identifiers and custom metadata. Revert field selection
if downstream schema or privacy checks fail; that rollback cannot remove columns already exported.
Blob storage, export receipt and warehouse joins remain external verification gates.

## ✅ Release Gates

Before deploying a prompt, model, retrieval, or agent change:

- run dataset experiments;
- compare against the current production version;
- check quality, latency, cost, and safety scores;
- inspect failures manually;
- promote only if the candidate beats or matches current behavior on important segments;
- add a temporary production dashboard filtered by the new release/version.

This turns Langfuse from a passive trace viewer into an engineering control system.

## ✅ CI/CD Evaluation Gates

The aggregate helper below is an explanatory threshold excerpt. It cannot approve a release by
itself: it has no per-item coverage, critical-case, same-snapshot or baseline comparison. The complete
local fixture above owns those checks; production CI must add budget and hosted-result retrieval gates.


Run a small but representative experiment suite in CI for changes that affect prompts, retrieval, models, tools, or agent logic.

Gate on:

- minimum average quality score;
- no regression against the current production baseline;
- safety pass rate;
- maximum p95 latency for the test run;
- maximum token or cost budget per answer;
- no critical failures in required categories.

Example shape:

```python
from dataclasses import dataclass


@dataclass
class GateScore:
    name: str
    value: float


def score_value(scores: list[GateScore], name: str) -> float:
    return next(score.value for score in scores if score.name == name)


def assert_release_gate(run_scores: list[GateScore]) -> None:
    average_relevance = score_value(run_scores, "average_relevance")
    safety_pass_rate = score_value(run_scores, "safety_pass_rate")

    if average_relevance < 0.82:
        raise SystemExit("release gate failed: relevance below threshold")

    if safety_pass_rate < 0.99:
        raise SystemExit("release gate failed: safety pass rate below threshold")
```

CI gates should be conservative and stable. Use them to block obvious regressions, then use production Langfuse dashboards and alerts to monitor the long tail.

## 📊 Langfuse Metrics

Langfuse metrics derive from traces and scores. Use them for:

- quality trends by score
- cost by model, user, tenant tier, or prompt version
- latency by trace name and release
- volume by trace name, model, tags, or user segment
- token usage trends

Metrics API v2 is the current aggregate API:

```bash
export LANGFUSE_AUTH_STRING="$(printf '%s' "${LANGFUSE_PUBLIC_KEY}:${LANGFUSE_SECRET_KEY}" | base64 | tr -d '\n')"

curl --fail-with-body --get \
  -H "Authorization: Basic ${LANGFUSE_AUTH_STRING}" \
  --data-urlencode 'query={
    "view": "observations",
    "metrics": [{"measure": "totalCost", "aggregation": "sum"}],
    "dimensions": [{"field": "providedModelName"}],
    "filters": [{
      "column": "environment",
      "operator": "=",
      "value": "prod",
      "type": "string"
    }],
    "fromTimestamp": "2026-07-19T00:00:00Z",
    "toTimestamp": "2026-07-20T00:00:00Z",
    "orderBy": [{"field": "sum_totalCost", "direction": "desc"}],
    "config": {"row_limit": 100}
  }' \
  "${LANGFUSE_BASE_URL}/api/public/v2/metrics"
```

Use these views:

| View | Meaning |
| --- | --- |
| `observations` | Observation latency, cost, token, and count aggregates, with supported trace dimensions. |
| `scores-numeric` | Numeric score count/value aggregates. Historical baselines may group boolean values here. |
| `scores-boolean` | Current dedicated boolean-score aggregates; use for pass/fail trends after verifying server support. |
| `scores-categorical` | Categorical score counts, including the `stringValue` dimension. |

For a current server supporting dedicated boolean scores, this complete query object requests
the `true` rate of the SSO correctness score over one fixed window. Supply it as the URL-encoded
`query` parameter to the same authenticated Metrics API v2 call shown above:

```json
{
  "view": "scores-boolean",
  "metrics": [{"measure": "value", "aggregation": "avg"}],
  "dimensions": [],
  "filters": [{"column": "name", "operator": "=", "value": "answer_correct_v1", "type": "string"}],
  "fromTimestamp": "2026-10-13T00:00:00Z",
  "toTimestamp": "2026-10-14T00:00:00Z",
  "config": {"row_limit": 100}
}
```

An average 0.80 means 80% of those scored records are true, not 80% of all production requests.
Unscored or discarded requests are absent. Inspect coverage and segment sampling before calling
it overall correctness. [Boolean view](https://langfuse.com/docs/metrics/features/metrics-api),
checked 2026-10-14; authenticated query execution remains an external verification gate.

The default `config.row_limit` is 100 and the maximum is 1,000. Dimensions such as `id`, `traceId`, `userId`, and `sessionId` may be filtered but cannot be grouped because of cardinality. The v2 `observations` view counts observation rows: a trace with a root, retriever, and two generations contributes four observations. Observation counts are not trace counts; use the Observations API v2 and deduplicate `traceId` client-side when a true trace count is required.

Current v2 also supports `isRootObservation` for semantic application roots, including an app
entry point whose infrastructure parent was filtered from export. For a fixture with one such
root per workflow, filtering that field can count workflow entries without counting each generation.
Do not assume it always equals distinct trace count: a trace can contain multiple application roots.
For exact distinct trace IDs, retrieve the matching observation rows with pagination and deduplicate
trace IDs across the whole interval, rather than using a truncated aggregate row set.
[Semantic-root filtering](https://langfuse.com/docs/metrics/features/metrics-api), checked 2026-10-14.

Common dashboards:

| Dashboard | Useful charts |
| --- | --- |
| Executive AI quality | acceptance rate, groundedness, safety pass rate, cost |
| Model migration | quality, p95 latency, cost, error traces by old vs new model |
| Prompt rollout | score distributions by prompt version |
| RAG health | empty retrieval rate, groundedness, citation validity |
| Agent health | tool failure rate, step count, loop stops, final answer quality |

Layered explanation:

- Beginner intuition: metrics summarize many traces and scores.
- Technical mechanics: Langfuse derives quality, cost, latency, and volume dimensions from ingested trace/evaluation data.
- Production implications: Langfuse metrics are excellent for LLM/product analytics, while infrastructure SLOs still belong in your metrics backend.
- Common mistakes: using Langfuse as the only alert engine, not exporting quality signals to paging systems when needed, and grouping by high-cardinality metadata.
- Common mistakes: treating observation counts as trace counts, ignoring the row limit, and building a polling bridge for a threshold already supported by a native Monitor.

## 📊 Alerting Philosophy

Use a native Langfuse Monitor first for thresholds supported by observation or numeric/categorical score metrics:

1. Select `Observations`, `Scores (numeric)`, `Scores (categorical)`, or current `Scores (boolean)` and choose the aggregation/measure.
2. Add bounded filters such as environment, model, trace name, observation name, tag, release, or score name.
3. Set the alert threshold, optional warning threshold, and evaluation window.
4. Decide what no data means: compare as zero, keep the previous severity, show `NO_DATA`, or notify after sustained no data.
5. Configure renotification (`Off` or every N minutes) to avoid silent persistent incidents or notification storms.
6. Link one or more automations: Slack, an HMAC-verified webhook, or a GitHub Actions `workflow_dispatch`.

Monitors notify on transitions into warning/alert and on recovery; sustained severity renotifies only when configured. Treat automation delivery as production infrastructure—after repeated delivery failures a trigger can be disabled, so monitor the destination and re-enable it after repair.

Use two alert layers:

1. Native Langfuse Monitors for supported observation/score cost, latency, volume, and quality thresholds.
2. External OpenTelemetry metrics and incident tooling for infrastructure SLOs, unsupported/custom signals, cross-system correlation, on-call paging, deduplication, and escalation.

Do not page on every single bad answer. Page on sustained user impact or safety-critical failures.

## Walk one monitor through warning, alert, recovery and missing data

An alert evaluates a filtered query periodically. Its **window** is the time range of observations
included; **severity** is the current result; a notification is a separate delivery action. For this
synthetic SSO monitor, p95 generation duration has warning >2 s and alert >3 s, and the selected
no-data policy is “show NO_DATA.” Renotification is disabled. Use the current UI for supported
comparison operators; these exact values are a worked configuration, not defaults.

| Evaluation | Query result | Previous → next severity | Notification decision |
| --- | --- | --- | --- |
| 1 | 1.4 s | UNKNOWN → OK | no breach |
| 2 | 2.4 s | OK → WARNING | breach notification |
| 3 | 3.4 s | WARNING → ALERT | severity escalation; verify configured delivery behavior |
| 4 | 3.5 s | ALERT → ALERT | no repeat with renotification disabled |
| 5 | 1.4 s | ALERT → OK | recovery notification |
| 6 | no observations | OK → NO_DATA | display missing data, no no-data notification under chosen policy |
| 7 | 1.5 s | NO_DATA → OK | data resumes; behavior follows no-data policy |

The sustained 3.5-s window is still unhealthy even though no second message is sent. A monitor
can be in ALERT while webhook delivery is failing: test severity and delivery independently.
“No observations” is not a measured zero latency. Treating it as zero would make a stopped export
pipeline look fast. For sparse traffic, no data can be normal; for a continuous service, choose a
separate telemetry-health signal or sustained no-data notification policy with a deliberate delay.
[Alert states and notification policy](https://langfuse.com/docs/observability/features/alerts),
checked 2026-10-14.

```mermaid
stateDiagram-v2
  [*] --> UNKNOWN
  UNKNOWN --> OK: first healthy evaluation
  OK --> WARNING: p95 2.4s
  WARNING --> ALERT: p95 3.4s
  ALERT --> ALERT: p95 3.5s, renotify disabled
  ALERT --> OK: p95 1.4s, recovery
  OK --> NO_DATA: empty window, chosen policy
  NO_DATA --> OK: p95 1.5s, data resumes
```

Each arrow changes query evidence or state. The self-loop preserves severity, and therefore uses
the separate renotification rule. Pausing stops evaluations; resuming needs a new evaluation rather
than treating old data as a current proof. Before production, force healthy/breach/recovery/no-data
windows in a staging project, verify the recorded state and destination receipt, then restore the
approved thresholds. This collection's timeline is demonstrated reasoning; external notifications
remain credential-dependent and unverified locally.

### Current evaluator automation changes the rollout contract

Stable `/api/public/v2/evaluators` and `/evaluation-rules` APIs use stable resource IDs and evaluator
versions. Rules use the latest assigned evaluator version, so changing its definition changes online
scoring; preserve versions in experiment evidence and test before applying a rule update. Move
unstable API automation by the announced 2026-11-16 sunset.
[Stable API release](https://langfuse.com/changelog/2026-08-27-stable-evaluator-api), checked 2026-10-14.

Historical backfill evaluates observations already retained when a rule is attached. It cannot
recover head-dropped traces. Keep evaluation time distinct from observation time in quality windows,
and budget the temporary judge concurrency/cost surge before enabling a backfill.
[Backfill release](https://langfuse.com/changelog/2026-09-07-evaluator-backfills), checked 2026-10-14.

## 📊 Practical Alert Ideas

| Alert | Source | Why it matters |
| --- | --- | --- |
| High HTTP 5xx rate | OTel metrics | Service is failing |
| High LLM provider error rate | OTel metrics or traces | Model calls are failing |
| LLM p95 latency high | OTel metrics | User experience degradation |
| Token usage per request spike | OTel metrics or Langfuse metrics | Cost or prompt regression |
| User thumbs-down rate high | Langfuse scores | Quality regression |
| Groundedness score low | Langfuse scores | RAG hallucination risk |
| Safety pass rate drops | Langfuse scores | Trust and compliance risk |
| Agent tool failure rate high | OTel metrics and Langfuse traces | Broken tools or bad plans |
| Empty retrieval rate high | OTel metrics | Search/index issue |
| Experiment regression | Langfuse experiments | Block release before production |

## 🛠️ Example: Export Quality Metrics to Alerting

If a required threshold is not supported by a native Monitor, a scheduled job can query Metrics API v2 and write compact time series to the metrics backend. Use a durable cursor, publish a monotonic processed-score counter for window sample guards, and make retries idempotent.

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass
class QualityWindow:
    trace_name: str
    score_name: str
    average: float
    count: int


class MetricsClient(Protocol):
    def gauge(self, name: str, value: float, tags: dict[str, str]) -> None:
        ...


def publish_quality_metrics(windows: list[QualityWindow], metrics: MetricsClient) -> None:
    for window in windows:
        metrics.gauge(
            "llm_quality_score",
            window.average,
            tags={
                "trace_name": window.trace_name,
                "score_name": window.score_name,
            },
        )
        metrics.gauge(
            "llm_quality_score_count",
            window.count,
            tags={
                "trace_name": window.trace_name,
                "score_name": window.score_name,
            },
        )
```

Keep alert dimensions low-cardinality. Alert by workflow, environment, release, and model; investigate individual traces in Langfuse.

## 🔍 Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| User feedback is missing from traces | Response did not persist the Langfuse trace ID | Store `get_current_trace_id()` with the message and use `create_score()` later. |
| Scores are duplicated after retries | No idempotent score ID | Use deterministic IDs such as `<trace_id>:<score_name>:<evaluator_version>`. |
| Dashboard averages look meaningless | Mixed score scales or semantics under one name | Define score configs and version evaluator/rubric changes. |
| LLM judge disagrees with humans | Poor rubric, judge drift, or biased context | Calibrate on human-reviewed data and track disagreement. |
| Experiment passes but production fails | Dataset misses real traffic segments or hard failures | Add production failures, edge cases, and important tenant workflows to the dataset. |
| CI gates are flaky | Non-deterministic task, unstable judge, small dataset, or live provider variance | Use deterministic checks where possible, larger representative samples, and tolerance bands. |
| Alerts are noisy | Alerting on individual bad answers or low sample counts | Require sustained windows and minimum counts. |
| Quality drop is hard to investigate | Scores not tied to release/version/model/prompt dimensions | Add release/version/model metadata to traces and score metadata. |

## ✅ Evaluation Checklist

- Define the quality questions each workflow must answer.
- Choose score names, data types, constraints, and score configs before broad rollout.
- Store trace IDs with user-visible outputs so feedback can attach later.
- Use deterministic code evaluators for schema, citation, safety, and business-rule checks.
- Calibrate LLM judges against human-reviewed examples and version judge prompts.
- Build datasets from common paths, high-risk cases, and production failures.
- Run experiments before prompt, model, retrieval, or agent changes ship.
- Compare candidates against a stable baseline with quality, safety, latency, token, and cost dimensions.
- Configure native Monitors for supported sustained quality/cost/latency/volume thresholds; export compact metrics only for unsupported or cross-system alert logic.
- Keep examples, rubrics, and release gates under review as the product changes.

## 🔌 Official References

- Scores overview: <https://langfuse.com/docs/evaluation/scores/overview>
- Scores data model: <https://langfuse.com/docs/evaluation/scores/data-model>
- Score configs FAQ: <https://langfuse.com/faq/all/manage-score-configs>
- Datasets: <https://langfuse.com/docs/evaluation/experiments/datasets>
- Experiments via SDK: <https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk>
- Metrics overview: <https://langfuse.com/docs/metrics/overview>
- Metrics API v2: <https://langfuse.com/docs/metrics/features/metrics-api>
- Monitors: <https://langfuse.com/docs/metrics/features/monitors>

## Retain the decision reasoning

- Store original answer identity and authorize message ownership before accepting later feedback.
- Calibrate rubrics with reviewed common and hard cases; exact checks and judge judgments differ.
- Freeze dataset and evaluator versions, require complete results, and reject critical failures before means.
- A monitor's sustained state and its notifications are separate; no data is not measured recovery.

**Q: The candidate mean wins, but its critical safety case fails and judge calibration misses half of safety failures. Promote?**

<details><summary>Answer</summary>

No. The failed critical case independently rejects it, and the unreliable judge cannot justify
promotion. Review the case, repair/calibrate the judge on reviewed and held-out safety examples,
then rerun baseline and repaired candidate on the same pinned snapshot with exact checks intact.

</details>

**Q: The monitor remains ALERT in a second bad window without a second message. Is that recovery?**

<details><summary>Answer</summary>

No. With renotification disabled the self-loop preserves ALERT without repeating a notification.
Recovery requires a healthy evaluated result. An empty window follows the chosen no-data policy.

</details>

**Try it:** Remove the `safety` result from a candidate that otherwise exactly equals baseline.
Predict the gate outcome and why averaging the remaining two items is misleading.

<details><summary>Worked solution</summary>

The local fixture rejects incomplete item coverage before calculating segment quality. Missing safety
evidence is unknown, not a pass. A two-item average compares a different workload and hides the
critical case, so it cannot authorize the three-item contract.

</details>
