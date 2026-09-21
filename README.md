# RepoPilot

RepoPilot is an agentic software engineering system that will eventually take a GitHub issue, inspect the repository, plan and apply a fix, run tests in isolation, review the result, pause for human approval, and open a pull request.

This repository currently implements **Version 0 only**: a small LangGraph workflow with an issue analyzer and planner.

## Version 0 Workflow

```text
START -> issue_analyzer -> planner -> END
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
    core/
      config.py
      llm.py
    graph/
      state.py
      workflow.py
    schemas/
      issue.py
      plan.py
  tests/
main.py
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to override configuration. The default provider is `mock`, so no API key is required.

## Run

```bash
python main.py
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

## Not Implemented Yet

Version 0 intentionally does not include GitHub integration, repository reading, RAG, embeddings, Docker sandboxing, FastAPI, a frontend, databases, pull request creation, or human approval.

