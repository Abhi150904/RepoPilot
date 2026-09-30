# RepoPilot

RepoPilot is an agentic software engineering system that will eventually take a GitHub issue, inspect the repository, plan and apply a fix, run tests in isolation, review the result, pause for human approval, and open a pull request.

This repository currently implements **Version 4.3**: a small LangGraph workflow that can fetch a real GitHub issue, retrieve repository context, generate a structured implementation plan, produce a controlled code-change proposal, optionally apply structured changes to an explicit local workspace, optionally run tests in a Docker sandbox, analyze the test outcome, and decide whether a repair pass is appropriate.

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

The repair decider turns test analysis into the next workflow action: ready for review, attempt a repair, rerun tests, or stop for human inspection. This version records the decision but does not loop back into code writing yet.

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
```

Create or edit `.env` in the project root if you want to override configuration. The default provider is `mock`, so no LLM API key is required.

For GitHub mode, set `GITHUB_TOKEN` in `.env` when you want higher rate limits or need access to private repositories.

## Run

```bash
python main.py
```

To run against a GitHub issue:

```bash
python main.py --repo owner/name --issue 123
```

To explicitly apply structured changes to a local workspace:

```bash
python main.py --apply-changes --workspace path/to/workspace
```

To run tests in a Docker sandbox for a local workspace:

```bash
python main.py --run-tests --workspace path/to/workspace
```

To apply changes first and then run a custom test command:

```bash
python main.py --apply-changes --run-tests --workspace path/to/workspace --test-command python -m pytest
```

`--workspace` is only accepted with `--apply-changes` or `--run-tests`.

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
- **Repair decisions are separate from repair execution** so the workflow can expose why it would retry before adding graph loops.

## Not Implemented Yet

This version intentionally does not include Qdrant, model-backed reranking, automatic dependency installation inside sandbox images, FastAPI, a frontend, databases, pull request creation, or human approval.
