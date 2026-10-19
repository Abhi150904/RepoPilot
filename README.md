# RepoPilot

RepoPilot is an agentic software engineering system that will eventually take a GitHub issue, inspect the repository, plan and apply a fix, run tests in isolation, review the result, pause for human approval, and open a pull request.

This repository currently implements **Pre-Phase 5**: a small LangGraph workflow that can fetch a real GitHub issue, retrieve repository context, generate a structured implementation plan, load full target-file contents, produce validated structured code changes, optionally apply those changes to an explicit local workspace, optionally run tests in a Docker sandbox, analyze the test outcome, decide whether a repair pass is appropriate, perform a bounded repair retry, pass failure context into repair attempts, and produce a final run summary.

## Version 0 Workflow

```text
START -> issue_analyzer -> planner -> END
```

## Version 1 Workflow

```text
START -> fetch_github_issue -> issue_analyzer -> repo_explorer -> planner -> END
```

## Version 2.1 Retrieval

```text
GitHub repository files
  -> candidate file ranking
  -> code-aware-ish chunking
  -> keyword chunk scoring
  -> repository context for planning
```

## Version 2.2 Vector Retrieval

```text
code chunks
  -> deterministic local embeddings
  -> in-memory cosine search
  -> vector-ranked chunks
```

The vector retriever is intentionally local and deterministic for now. A real embedding provider and external vector database can be added after the baseline behavior is testable.

## Version 2.3 BM25 Retrieval

```text
code chunks
  -> tokenized sparse index
  -> BM25 scoring
  -> ranked chunks
```

BM25 gives the project a stronger lexical baseline than simple keyword scoring by accounting for term rarity, term frequency, and chunk length.

## Version 2.4 Hybrid Retrieval

```text
code chunks
  -> keyword retrieval
  -> vector retrieval
  -> BM25 retrieval
  -> normalized weighted merge
  -> ranked hybrid chunks
```

Repo exploration now uses the hybrid retriever.

## Version 2.5 Reciprocal Rank Fusion

```text
keyword ranked chunks
BM25 ranked chunks
vector ranked chunks
  -> reciprocal rank fusion
  -> ranked hybrid chunks
```

RRF combines retrievers by rank instead of raw score, which is more stable because keyword, BM25, and vector scores have different meanings.

## Version 2.6 Reranker Interface

```text
hybrid RRF chunks
  -> reranker
  -> final ranked chunks
```

The reranker layer is model-provider agnostic. This version includes a no-op reranker and a deterministic heuristic reranker that boosts exact path, symbol, and early-content matches while slightly downranking test files unless the query asks for tests.

## Version 3 Code Writer

```text
GitHub issue
  -> analysis
  -> retrieval
  -> implementation plan
  -> code writer
  -> structured change proposal
  -> unified diff
```

The code writer is intentionally controlled. It proposes patch placeholders for retrieved target files and renders a diff. Structured changes can be applied only when explicitly enabled with a local workspace path.

```text
code writer
  -> optional apply_code_changes
  -> modified files
  -> actual diff
```

## Version 4.1 Sandbox Test Runner

```text
code writer
  -> optional apply_code_changes
  -> optional run_tests
  -> test result
```

The sandbox runner executes an explicit command inside Docker with no network access, CPU and memory limits, a timeout, and capped output. It is opt-in and requires a local workspace path.

## Version 4.2 Test Result Analysis

```text
run_tests
  -> analyze_tests
  -> test analysis
```

Raw sandbox output is converted into a compact workflow decision: passed, failed, timed out, or command error. This gives later review and retry steps a stable signal instead of requiring them to parse stdout and stderr directly.

## Version 4.3 Repair Decision

```text
analyze_tests
  -> decide_repair
  -> repair decision
```

The repair decider turns test analysis into the next workflow action: ready for review, attempt a repair, rerun tests, or stop for human inspection.

## Version 4.4 Bounded Repair Loop

```text
decide_repair
  -> optional prepare_repair
  -> code_writer
  -> apply_code_changes
  -> run_tests
```

The workflow can now perform a bounded automated repair retry when tests fail with useful failure output. Repair attempts are counted in graph state and limited by `max_repair_attempts`, which defaults to one.

## Version 4.5 Repair Context Injection

```text
prepare_repair
  -> repair context
  -> code_writer
```

Repair retries now receive structured context from the failed test run, including the attempt number, test status, summary, failure reason, and previous diff. The controlled code writer includes that context in the repair patch proposal so retries are guided by the failure instead of being blind repeats.

## Version 4.6 Final Run Summary

```text
workflow result
  -> summarize_run
  -> run summary
```

Every workflow path now ends with a compact final verdict such as `planned_only`, `changes_proposed`, `ready_for_review`, `repair_failed`, or `needs_human`. This gives CLI users and future API/UI layers one stable object to inspect before digging into intermediate state.

## Pre-Phase 5 Real Code Generation

```text
retrieved files
  -> full target-file loading
  -> structured code generation
  -> validation
  -> deterministic application
```

RepoPilot now separates retrieval previews from editable source. Retrieval selects likely target files, then the workflow loads complete file contents from the explicit workspace or GitHub before calling the code writer. The writer uses the LLM abstraction to return structured `FileChange` objects, while RepoPilot validates paths, actions, and content before applying changes and rendering diffs.

The CLI uses a hard-coded issue:

```text
Login endpoint returns 500 when email is missing.
```

It prints:

- structured issue analysis
- structured implementation plan

## Project Structure

```text
backend/
  app/
    agents/
      analyzer.py
      coder.py
      planner.py
      repair_decider.py
      repo_explorer.py
      run_summarizer.py
      test_analyzer.py
    core/
      config.py
      llm.py
    graph/
      state.py
      workflow.py
    retrieval/
      bm25.py
      chunker.py
      embeddings.py
      fusion.py
      hybrid.py
      keyword.py
      reranker.py
      vector.py
    schemas/
      code_change.py
      execution.py
      issue.py
      plan.py
      repository.py
    tools/
      filesystem.py
      git.py
      github.py
      patch.py
      sandbox.py
  tests/
main.py
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Create or edit `.env` in the project root if you want to override configuration. The default provider is `mock`, so no LLM API key is required.

Useful environment variables:

```text
REPO_PILOT_LLM_PROVIDER=openai
REPO_PILOT_LLM_MODEL=gpt-5.4-mini
OPENAI_API_KEY=...
REPO_PILOT_LLM_MAX_OUTPUT_TOKENS=8192
REPO_PILOT_LLM_MAX_PROMPT_CHARS=60000
REPO_PILOT_LLM_MAX_RETRIES=2
REPOPILOT_LLM_BUDGET_USD=5
REPOPILOT_LLM_RUN_BUDGET_USD=0.50
REPOPILOT_LLM_BUDGET_PATH=.repopilot/openai-budget.sqlite
GITHUB_TOKEN=...
REPO_PILOT_DEFAULT_TEST_COMMAND=python -m pytest
```

Set `GITHUB_TOKEN` when you want higher rate limits, need access to private repositories, or want RepoPilot to push branches and open pull requests.

Only `openai` and `mock` model providers are supported. OpenAI uses the Responses API
with strict JSON schemas. The default model is `gpt-5.4-mini`; per-role model
overrides remain available, but the spending guard rejects models without a
verified entry in `backend/app/core/pricing.py`.

The local spending ledger reserves a conservative input estimate plus the maximum
output cost before every API attempt, then replaces that reservation with reported
usage cost. Output usage includes reasoning tokens. Requests that time out or lack
usage retain their reservation. Failed attempts are included in usage records;
unknown usage remains unknown rather than becoming zero. Rate-limit and transient
server errors retry with bounded waits; quota errors, refusals, and incomplete
responses stop safely.

The default limits are $5 total per API key and $0.50 per run, across local processes
sharing the same ledger file. This is a conservative RepoPilot guard, not an OpenAI
billing limit: it cannot see usage from another app or another machine, and deleting
the ledger resets its history. Keep the ledger outside source repositories and use
the same absolute path across workers. Unknown network outcomes can consume the
local allowance even if no charge occurred. No live API calls are needed for tests.

Source files are never silently truncated before whole-file replacement. Oversized
prompts stop before making a paid request; narrow the selected files or deliberately
increase the prompt limit.

## CLI Usage

For restricted Phase 20 staging deployment, see [deploy/STAGING.md](deploy/STAGING.md).

For the Vercel frontend and separate AWS execution-host deployment, see
[deploy/AWS.md](deploy/AWS.md). Cloud resources are not provisioned by these files.

For Azure on-demand runner startup/idle deallocation and a credit-budget worksheet,
see [deploy/AZURE.md](deploy/AZURE.md). Automation is opt-in and requires a
VM-scoped app-host managed identity, a prepared runner, and live isolation checks.
It includes the Docker Compose topology, GitHub tester allowlist, shared workspace
requirements, rollback guidance, and live acceptance checks. It is not a public
multi-tenant deployment or a completed cloud provisioning step.

### Hosted demo scope

The public web app includes Command Center, Runs, Repositories, and Settings.
Evaluations are CLI-only; `/evaluations/*` API endpoints and the frontend page
are not exposed. Existing evaluation records are preserved in storage, and
private evaluation workers can finish jobs already queued there.

Hosted run creation is limited per authenticated GitHub user, across all
repositories: `REPOPILOT_USER_MAX_ACTIVE_RUNS=1` queued/running job and
`REPOPILOT_USER_MAX_DAILY_RUNS=5` new runs in a rolling 24-hour window.
All admitted runs count toward the window, including failures. Replays with the
same Idempotency-Key and payload return the original run without consuming
another slot. Limits are checked transactionally in PostgreSQL or SQLite;
they do not apply to local CLI runs. The existing global and per-run LLM budget
caps remain in effect. These controls are not payment credits.

Run benchmarks privately with `repopilot eval retrieval` or
`repopilot eval workflow`; append `--json` for machine-readable results.

The product CLI is:

```bash
python main.py run
```

After installing the package, the same command is available as:

```bash
repopilot run
```

Use `--help` to see all flags and examples:

```bash
python main.py run --help
```

Plan from plain issue text:

```bash
python main.py run --issue-text "Login endpoint returns 500 when email is missing"
```

Run against a GitHub issue:

```bash
python main.py run --repo owner/name --issue 123
```

Apply changes in a workspace:

```bash
python main.py run --repo owner/name --issue 123 --apply
```

Apply changes and run tests. If `--test-command` is omitted, RepoPilot uses `REPO_PILOT_DEFAULT_TEST_COMMAND`, which defaults to `python -m pytest`.

```bash
python main.py run --repo owner/name --issue 123 --apply --test
```

Run a custom test command:

```bash
python main.py run --repo owner/name --issue 123 --apply --test --test-command pytest -q
```

Approve a reviewed run and validate publication without Git or GitHub side effects:

```bash
python main.py run --repo owner/name --issue 123 --apply --test --approve --dry-run
```

Publish a pull request after approval:

```bash
python main.py run --repo owner/name --issue 123 --apply --test --approve --publish pr
```

Print the full workflow result as JSON:

```bash
python main.py run --repo owner/name --issue 123 --json
```

Print detailed human-readable sections instead of the compact summary:

```bash
python main.py run --repo owner/name --issue 123 --verbose
```

## Test

```bash
pytest
```

## Technical Decisions

- **LangGraph** is used from the start so stateful orchestration is part of the core design, not something bolted on later.
- **Pydantic schemas** keep agent outputs explicit and easy to validate.
- **Typed graph state** makes the data passed between nodes visible and beginner-friendly.
- **LLM provider abstraction** keeps the workflow from being tied to a single model provider.
- **Mock provider by default** makes Version 0 runnable without accounts, API keys, network calls, or hidden infrastructure.
- **GitHub tools are deterministic functions** rather than extra agents, keeping reasoning separate from API access.
- **Basic repository exploration comes before RAG**, so the project can prove the simple path before adding embeddings or vector infrastructure.
- **Keyword retrieval is the Version 2.1 baseline** so later vector, BM25, hybrid, fusion, and reranking work can be compared against a deterministic starting point.
- **Vector retrieval starts in memory** so the architecture is visible before adding Qdrant or provider-specific embedding APIs.
- **BM25 adds a stronger sparse baseline** before combining retrievers in the hybrid retrieval phase.
- **Hybrid retrieval uses reciprocal rank fusion** so chunks found by multiple retrievers rise without comparing incompatible raw scores.
- **Reranking is explicit and replaceable** so a model-backed reranker can be added later without changing graph orchestration.
- **Code writing is controlled in Version 3** so the system can expose structured proposed changes and diffs before executing tests or mutating real repositories.
- **Applying changes is opt-in** and requires an explicit workspace path, so normal GitHub issue runs do not write files.
- **Sandbox testing is opt-in** and runs explicit command tokens in a restricted Docker container instead of passing user input through a shell.
- **Repair attempts are bounded** so automated retry behavior is explicit and cannot loop forever.
- **Repair context is structured** so future model-backed repair can use failure details without scraping raw test output.
- **Run summaries are final workflow outputs** so users can read one verdict before inspecting detailed agent state.
- **Full-file source is separate from retrieval context** so generated edits are based on complete editable files, not truncated previews.
- **Structured code changes are validated before application** so unsafe paths, empty content, and unrelated files fail cleanly.

## Not Implemented Yet

This version intentionally does not include Qdrant, model-backed reranking, automatic dependency installation inside sandbox images, FastAPI, a frontend, databases, pull request creation, or human approval.
