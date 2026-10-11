#!/usr/bin/env python
"""CLI script to ask a question and get an answer from the LangGraph agent."""

import json
import sys
import uuid
from typing import Any

from app.agent.graph import compile_graph
from app.agent.state import AgentState


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/ask.py '<question>'")
        print("Example: python scripts/ask.py 'What are the top 5 customers by spending?'")
        sys.exit(1)

    question = sys.argv[1]

    # Initialize state
    initial_state: AgentState = {
        "conversation_id": str(uuid.uuid4()),
        "user_id": "user-123",
        "question": question,
        "history": [],
        "few_shot_examples": [],
        "plan": [],
        "needs_schema": False,
        "schema_context": "",
        "sql": None,
        "validation": None,
        "result": None,
        "error": None,
        "retries": 0,
        "iterations": 0,
        "status": "running",
        "answer": None,
        "_execution_time_ms": None,
        "_tokens_used": None,
        "_cost_usd": None,
    }

    print("\n" + "=" * 80)
    print(f"Question: {question}")
    print("=" * 80)

    # Compile and run graph
    try:
        agent = compile_graph()
        final_state = agent.invoke(initial_state)

        # Print results
        print(f"\n[PLAN]")
        for i, step in enumerate(final_state["plan"], 1):
            print(f"  {i}. {step}")

        if final_state.get("sql"):
            print(f"\n[SQL]")
            print(final_state["sql"])

        if final_state.get("result"):
            print(f"\n[RESULT]")
            result = final_state["result"]
            if result.get("ok"):
                print(f"  Rows: {result.get('row_count', 0)}")
                if result.get("rows"):
                    print(f"  First row: {result['rows'][0]}")
            else:
                print(f"  Error: {result.get('error', 'Unknown')}")

        print(f"\n[ANSWER]")
        print(final_state.get("answer", "No answer"))

        print(f"\n[STATUS]")
        print(f"  Status: {final_state['status']}")
        print(f"  Iterations: {final_state['iterations']}")
        print(f"  Retries: {final_state['retries']}")

        if final_state.get("error"):
            print(f"  Error: {final_state['error']}")

        print("=" * 80 + "\n")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
