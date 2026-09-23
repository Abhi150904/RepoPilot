# RepoPilot

RepoPilot is an agentic software engineering system that will eventually take a GitHub issue, inspect the repository, plan and apply a fix, run tests in isolation, review the result, pause for human approval, and open a pull request.

This repository currently implements **Version 1**: a small LangGraph workflow that can either run a local demo issue or fetch a real GitHub issue and gather basic repository context.

## Version 0 Workflow

```text
START -> issue_analyzer -> planner -> END
```

## Version 1 Workflow

```text
START -> fetch_github_issue -> issue_analyzer -> repo_explorer -> planner -> END
```

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

## Not Implemented Yet

This version intentionally does not include RAG, embeddings, Docker sandboxing, code editing, test execution, FastAPI, a frontend, databases, pull request creation, or human approval.
