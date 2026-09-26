# RepoPilot

RepoPilot is an agentic software engineering system that will eventually take a GitHub issue, inspect the repository, plan and apply a fix, run tests in isolation, review the result, pause for human approval, and open a pull request.

This repository currently implements **Version 2.2**: a small LangGraph workflow that can fetch a real GitHub issue, explore repository files, chunk candidate code, use keyword retrieval as the first baseline, and expose an in-memory vector retrieval component for the next hybrid step.

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
      planner.py
      repo_explorer.py
    core/
      config.py
      llm.py
    graph/
      state.py
      workflow.py
    retrieval/
      chunker.py
      embeddings.py
      keyword.py
      vector.py
    schemas/
      issue.py
      plan.py
      repository.py
    tools/
      github.py
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

## Not Implemented Yet

This version intentionally does not include Qdrant, BM25, hybrid retrieval, reranking, Docker sandboxing, code editing, test execution, FastAPI, a frontend, databases, pull request creation, or human approval.
