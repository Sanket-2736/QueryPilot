# Evaluation Harness for QueryPilot

This directory contains the evaluation framework for testing QueryPilot's accuracy, safety, and performance.

## Quick Start

### Run Baseline Evaluation
Execute gold SQL queries to establish a performance baseline:

```bash
python -m eval.run_eval --system baseline
```

This runs all 60+ test queries using gold SQL directly against the target database.

### Run Agent Evaluation
Evaluate the QueryPilot agent against the same dataset:

```bash
python -m eval.run_eval --system agent
```

The agent generates SQL for each question and compares results with gold SQL.

### A/B Testing

Compare agent performance with different configurations:

```bash
# Agent with all features
python -m eval.run_eval --system agent

# Agent without semantic layer
python -m eval.run_eval --system agent --semantic-layer off

# Agent without retries
python -m eval.run_eval --system agent --retries off

# Agent without memory
python -m eval.run_eval --system agent --memory off

# Agent with failure injection (tests robustness)
python -m eval.run_eval --system agent --failures on
```

## Dataset Structure

`dataset.jsonl` contains 60+ test cases with fields:

```json
{
  "question": "What are the top 5 customers by revenue?",
  "gold_sql": "SELECT c.id, SUM(o.total) FROM customers c JOIN orders o ...",
  "expected_tables": ["customers", "orders"],
  "category": "joins",
  "expected_row_count": 5,
  "prior_turn": {
    "question": "Who are the top customers?",
    "sql": "SELECT * FROM customers ...",
    "answer": "Top 10 customers: Alice, Bob, ..."
  },
  "should_reject": false,
  "clarification": "By revenue or by order count?"
}
```

### Categories

- **simple_aggregation** (9 items): COUNT, SUM, AVG, GROUP BY, DISTINCT
- **joins** (15 items): INNER/LEFT/RIGHT joins, multi-table queries, fan-out detection
- **time_comparison** (8 items): Year-over-year, quarter-over-quarter, trending
- **follow_up** (4 items): Multi-turn conversations with context from prior turns
- **ambiguous** (4 items): Questions requiring clarification (metric, time period, etc.)
- **adversarial** (7 items): DROP, DELETE, UPDATE, INSERT, system catalog, dangerous functions

## Metrics

### Accuracy Metrics

| Metric | Definition |
|--------|-----------|
| **Execution Accuracy** | Percentage of queries that executed without error |
| **Answer Accuracy** | Percentage of results matching expected output (order-insensitive unless ORDER BY present) |
| **Schema Retrieval Recall** | Percentage of needed tables retrieved for generation |
| **Retry Success Rate** | Percentage of failed queries that were fixed on retry |
| **Clarification Precision** | Percentage of clarifications that were correct |

### Performance Metrics

| Metric | Definition |
|--------|-----------|
| **Avg Iterations** | Average number of nodes executed per query (target: <8) |
| **p50 Latency** | Median query latency in milliseconds |
| **p95 Latency** | 95th percentile query latency |
| **Avg Tokens/Query** | Average LLM tokens used per query |
| **Total Tokens** | Total tokens consumed across all queries |
| **Avg Cost** | Average cost per query in cents (OpenAI pricing) |
| **Total Cost** | Total cost across all queries |

### Safety Metrics

| Metric | Definition |
|--------|-----------|
| **Unsafe Query Block Rate** | Percentage of destructive queries (DROP, DELETE, UPDATE, INSERT) correctly blocked |
| **Total Queries Evaluated** | Count of test items run |
| **Failed Queries** | Count of queries that did not execute |
| **Retried Queries** | Count of queries that required fix_sql |

## Failure Injection

Failure injection tests the agent's robustness under adverse conditions. When enabled (`--failures on`), 20% of queries are injected with one of 6 failure modes:

### Failure Modes

1. **wrong_table** – Schema retrieval returns irrelevant tables
   - Tests: Agent detects schema is wrong, requests refresh
   - Mitigation: Schema validation, multiple retrieval attempts

2. **fan_out_join** – Missing junction table in schema
   - Tests: Agent detects cardinality issues (fan-out)
   - Mitigation: Cardinality analysis, ask for clarification

3. **invalid_sql** – LLM generates syntactically invalid SQL
   - Tests: Validator catches syntax errors
   - Mitigation: fix_sql attempts to repair, raises error after retries

4. **destructive_sql** – LLM attempts DROP/DELETE/UPDATE/INSERT
   - Tests: Validator blocks 100% of destructive operations
   - Mitigation: Pre-execution validation with sqlglot AST parsing

5. **ambiguous_question** – Natural language lacks specificity
   - Tests: Agent detects ambiguity, asks for clarification
   - Mitigation: Planner flags ambiguity; final_answer provides options

6. **missing_schema** – Required tables not returned by schema retrieval
   - Tests: Agent fails or requests clarification
   - Mitigation: Error recovery, retry with broader schema

## Running Evaluations

### Example: Full A/B Test

```bash
#!/bin/bash

# Run baseline
echo "=== Baseline (Gold SQL) ==="
python -m eval.run_eval --system baseline

# Run agent with all features
echo "=== Agent (Full Features) ==="
python -m eval.run_eval --system agent

# Run agent without semantic layer
echo "=== Agent (No Semantic Layer) ==="
python -m eval.run_eval --system agent --semantic-layer off

# Run agent with failure injection
echo "=== Agent (With Failure Injection) ==="
python -m eval.run_eval --system agent --failures on

# Compare reports
ls -lh eval/reports/
```

### Interpreting Results

Reports are saved to `eval/reports/<timestamp>.md` with:

1. **Summary** – Total queries, pass rate, configuration
2. **Key Metrics Table** – Accuracy, performance, safety metrics
3. **Results by Category** – Breakdown by query type (joins, aggregation, etc.)
4. **Failed Queries** – Details of the top 10 failures
5. **Error Analysis** – Common failure patterns

### Example Report

```markdown
# QueryPilot Evaluation Report

**System**: agent  
**Timestamp**: 2024-10-11T15:30:00  
**Semantic Layer**: True  
**Retries Enabled**: True  
**Memory Enabled**: True  
**Failure Injection**: off  

## Summary

**Total Queries Evaluated**: 60  
**Successful**: 57  
**Failed**: 3  

## Key Metrics

| Metric | Value |
|--------|-------|
| Execution Accuracy | 95.0% |
| Answer Accuracy | 91.7% |
| Schema Retrieval Recall | 88.5% |
| Retry Success Rate | 80.0% |
| Avg Iterations | 5.2 |
| p50 Latency (ms) | 1240 |
| p95 Latency (ms) | 3100 |
| Avg Tokens/Query | 285 |
| Total Tokens | 17100 |
| Avg Cost (¢) | 0.0142 |
| Total Cost (¢) | 0.85 |
| Safety Block Rate | 100% |

## Results by Category

### simple_aggregation
- Total: 9
- Successful: 9/9 (100%)
- Avg Latency: 850ms

### joins
- Total: 15
- Successful: 14/15 (93.3%)
- Avg Latency: 1200ms

### time_comparison
- Total: 8
- Successful: 8/8 (100%)
- Avg Latency: 920ms

...
```

## Dataset Extension

To add more test cases to `eval/dataset.jsonl`:

```python
import json

new_item = {
    "question": "Top 10 products by revenue in Q4 2024?",
    "gold_sql": "SELECT p.id, p.name, SUM(oi.quantity * oi.unit_price) FROM products p JOIN order_items oi ON p.id = oi.product_id JOIN orders o ON oi.order_id = o.id WHERE EXTRACT(QUARTER FROM o.date) = 4 AND EXTRACT(YEAR FROM o.date) = 2024 GROUP BY p.id, p.name ORDER BY SUM DESC LIMIT 10;",
    "expected_tables": ["products", "order_items", "orders"],
    "category": "joins",
    "expected_row_count": null,
}

with open("eval/dataset.jsonl", "a") as f:
    f.write(json.dumps(new_item) + "\n")
```

## Metrics Computation

The `eval/metrics.py` module computes aggregated metrics:

```python
from eval.metrics import compute_metrics, ExecutionMetrics

results = [...]  # List of evaluation results

metrics = compute_metrics(results)
print(f"Accuracy: {metrics.execution_accuracy:.1%}")
print(f"Avg Latency: {metrics.p50_latency_ms:.0f}ms")
print(f"Safety Block Rate: {metrics.unsafe_query_block_rate:.1%}")
```

### Result Format

Each result dict has:
- `success` (bool): Query executed without error
- `answer_correct` (bool): Result matches expected output
- `schema_tables_found` (list[str]): Tables retrieved
- `schema_tables_needed` (list[str]): Tables required
- `iterations` (int): Number of nodes executed
- `retries` (int): Number of fix_sql attempts
- `retries_succeeded` (bool): At least one retry succeeded
- `latency_ms` (float): Query execution time
- `tokens` (int): LLM tokens used
- `cost_cents` (float): Cost in cents
- `is_unsafe` (bool): True if query should be blocked
- `unsafe_correctly_blocked` (bool): Unsafe query was blocked

## Failure Injection Functions

`eval/failure_injection.py` provides 6 failure injection functions:

```python
from eval.failure_injection import inject_wrong_table_error, FAILURE_MODES

# Inject a specific failure
state_copy = inject_wrong_table_error(agent_state)

# Get all available failure modes
for mode_name in FAILURE_MODES:
    inject_fn = FAILURE_MODES[mode_name]
    modified_state = inject_fn(agent_state)
```

Each function takes an `AgentState` dict and returns a modified copy with the failure injected.

## CI/CD Integration

To integrate evaluations into CI/CD pipeline:

```yaml
# .github/workflows/eval.yml
name: Evaluation

on: [push, pull_request]

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: docker-compose up -d
      - run: alembic upgrade head
      - run: python -m eval.run_eval --system baseline
      - run: python -m eval.run_eval --system agent
      - uses: actions/upload-artifact@v3
        with:
          name: eval-reports
          path: eval/reports/
```

## Troubleshooting

### Dataset Not Found
```
FileNotFoundError: eval/dataset.jsonl
```

Ensure dataset exists and is valid JSONL:
```bash
cat eval/dataset.jsonl | head -1 | python -m json.tool
```

### Database Connection Error
```
MemoryConnectionError: Database connection failed
```

Check database URLs and ensure PostgreSQL is running:
```bash
docker-compose up -d
alembic upgrade head
```

### Out of Memory
If evaluation crashes with OOM:
- Reduce batch size in `run_eval.py`
- Run one category at a time
- Use `--system baseline` first (lower memory usage)

## Performance Optimization

### Parallel Evaluation

To evaluate multiple configurations in parallel:

```bash
python -m eval.run_eval --system baseline &
python -m eval.run_eval --system agent &
python -m eval.run_eval --system agent --semantic-layer off &
wait
```

### Caching

Schema cache (Redis):
- Enabled by default with `redis_url` configured
- Speeds up subsequent schema retrievals
- TTL: 1 hour (configurable in `app/config.py`)

### Sampling

To evaluate a subset of queries (for quick testing):

```bash
# Edit eval/run_eval.py to sample 10% of dataset
import random
items = load_dataset(...)
items = random.sample(items, len(items) // 10)
```

## Next Steps

1. **Run baseline evaluation**: `python -m eval.run_eval --system baseline`
2. **Run agent evaluation**: `python -m eval.run_eval --system agent`
3. **Analyze reports**: Compare `eval/reports/` markdown files
4. **Iterate**: If accuracy < 85%, review failed queries and improve prompts/logic
5. **A/B test features**: Run with `--semantic-layer off`, `--retries off`, etc.
6. **Update README**: Copy metrics table to main README.md

