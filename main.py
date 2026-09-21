from __future__ import annotations

import json
from pathlib import Path
import sys


BACKEND_PATH = Path(__file__).resolve().parent / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from app.graph.workflow import build_workflow


EXAMPLE_ISSUE = "Login endpoint returns 500 when email is missing."


def main() -> None:
    workflow = build_workflow()
    result = workflow.invoke({"issue": EXAMPLE_ISSUE})

    print("Issue:")
    print(result["issue"])
    print()

    print("Analysis:")
    print(json.dumps(result["analysis"], indent=2))
    print()

    print("Implementation Plan:")
    print(json.dumps(result["plan"], indent=2))


if __name__ == "__main__":
    main()

