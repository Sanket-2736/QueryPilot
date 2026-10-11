"""Evaluation metrics computation."""

import json
import logging
import statistics
from dataclasses import dataclass, asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """Metrics for a single evaluation run."""

    # Accuracy metrics
    execution_accuracy: float  # Percentage of queries that executed successfully
    answer_accuracy: float  # Percentage of results matching expected output
    schema_retrieval_recall: float  # Percentage of needed tables retrieved
    retry_success_rate: float  # Percentage of fixed queries that succeeded
    clarification_precision: float  # Percentage of clarifications that were correct

    # Performance metrics
    avg_iterations: float  # Average number of nodes executed per query
    p50_latency_ms: float  # Median query latency in milliseconds
    p95_latency_ms: float  # 95th percentile query latency
    avg_tokens_per_query: float  # Average LLM tokens per query
    total_tokens: int  # Total tokens used
    avg_cost_cents: float  # Average cost per query in cents
    total_cost_cents: float  # Total cost in cents

    # Safety metrics
    unsafe_query_block_rate: float  # Percentage of unsafe queries correctly blocked
    total_queries: int  # Total queries evaluated

    # Additional
    failed_queries: int  # Number of queries that failed
    retried_queries: int  # Number of queries that needed retries

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def to_markdown_table(self) -> str:
        """Format as markdown table row."""
        return (
            f"| Execution Accuracy | {self.execution_accuracy:.1%} |\n"
            f"| Answer Accuracy | {self.answer_accuracy:.1%} |\n"
            f"| Schema Recall | {self.schema_retrieval_recall:.1%} |\n"
            f"| Retry Success Rate | {self.retry_success_rate:.1%} |\n"
            f"| Clarification Precision | {self.clarification_precision:.1%} |\n"
            f"| Avg Iterations | {self.avg_iterations:.2f} |\n"
            f"| p50 Latency (ms) | {self.p50_latency_ms:.0f} |\n"
            f"| p95 Latency (ms) | {self.p95_latency_ms:.0f} |\n"
            f"| Avg Tokens/Query | {self.avg_tokens_per_query:.0f} |\n"
            f"| Total Tokens | {self.total_tokens:,} |\n"
            f"| Avg Cost (¢) | {self.avg_cost_cents:.4f} |\n"
            f"| Total Cost (¢) | {self.total_cost_cents:.2f} |\n"
            f"| Safety Block Rate | {self.unsafe_query_block_rate:.1%} |\n"
            f"| Total Queries | {self.total_queries} |\n"
            f"| Failed Queries | {self.failed_queries} |\n"
            f"| Retried Queries | {self.retried_queries} |"
        )


def compute_metrics(results: list[dict[str, Any]]) -> ExecutionMetrics:
    """Compute metrics from evaluation results.

    Args:
        results: List of evaluation result dicts with keys:
            - success: bool
            - answer_correct: bool
            - schema_tables_found: list
            - schema_tables_needed: list
            - iterations: int
            - retries: int
            - retries_succeeded: bool
            - latency_ms: float
            - tokens: int
            - cost_cents: float
            - is_unsafe: bool
            - unsafe_correctly_blocked: bool
            - clarification_correct: bool (if clarified)

    Returns:
        ExecutionMetrics object.
    """
    if not results:
        raise ValueError("No results to compute metrics from")

    total = len(results)

    # Accuracy metrics
    successful = sum(1 for r in results if r.get("success", False))
    execution_accuracy = successful / total if total > 0 else 0.0

    correct_answers = sum(1 for r in results if r.get("answer_correct", False))
    answer_accuracy = correct_answers / total if total > 0 else 0.0

    # Schema retrieval recall
    schema_recalls = []
    for r in results:
        found = len(set(r.get("schema_tables_found", [])))
        needed = len(set(r.get("schema_tables_needed", [])))
        if needed > 0:
            schema_recalls.append(found / needed)
    schema_retrieval_recall = sum(schema_recalls) / len(schema_recalls) if schema_recalls else 0.0

    # Retry metrics
    retried = [r for r in results if r.get("retries", 0) > 0]
    retries_succeeded = sum(1 for r in retried if r.get("retries_succeeded", False))
    retry_success_rate = retries_succeeded / len(retried) if retried else 0.0

    # Clarification metrics
    clarifications = [r for r in results if r.get("clarified", False)]
    clarifications_correct = sum(1 for r in clarifications if r.get("clarification_correct", False))
    clarification_precision = (
        clarifications_correct / len(clarifications) if clarifications else 0.0
    )

    # Performance metrics
    iterations = [r.get("iterations", 0) for r in results if r.get("iterations")]
    avg_iterations = sum(iterations) / len(iterations) if iterations else 0.0

    latencies = [r.get("latency_ms", 0) for r in results if r.get("latency_ms")]
    p50_latency_ms = statistics.median(latencies) if latencies else 0.0
    p95_latency_ms = (
        sorted(latencies)[int(len(latencies) * 0.95)] if len(latencies) > 20 else max(latencies)
    )

    tokens = [r.get("tokens", 0) for r in results if r.get("tokens")]
    avg_tokens_per_query = sum(tokens) / len(tokens) if tokens else 0.0
    total_tokens = sum(tokens)

    costs = [r.get("cost_cents", 0) for r in results if r.get("cost_cents")]
    avg_cost_cents = sum(costs) / len(costs) if costs else 0.0
    total_cost_cents = sum(costs)

    # Safety metrics
    unsafe_queries = [r for r in results if r.get("is_unsafe", False)]
    unsafe_correctly_blocked = sum(1 for r in unsafe_queries if r.get("unsafe_correctly_blocked", False))
    unsafe_query_block_rate = (
        unsafe_correctly_blocked / len(unsafe_queries) if unsafe_queries else 0.0
    )

    # Failure tracking
    failed_queries = total - successful
    retried_queries = len(retried)

    return ExecutionMetrics(
        execution_accuracy=execution_accuracy,
        answer_accuracy=answer_accuracy,
        schema_retrieval_recall=schema_retrieval_recall,
        retry_success_rate=retry_success_rate,
        clarification_precision=clarification_precision,
        avg_iterations=avg_iterations,
        p50_latency_ms=p50_latency_ms,
        p95_latency_ms=p95_latency_ms,
        avg_tokens_per_query=avg_tokens_per_query,
        total_tokens=total_tokens,
        avg_cost_cents=avg_cost_cents,
        total_cost_cents=total_cost_cents,
        unsafe_query_block_rate=unsafe_query_block_rate,
        total_queries=total,
        failed_queries=failed_queries,
        retried_queries=retried_queries,
    )


def compare_result_sets(
    gold_rows: list[dict[str, Any]],
    generated_rows: list[dict[str, Any]],
    gold_sql: str,
    float_tolerance: float = 1e-6,
) -> tuple[bool, str]:
    """Compare two result sets for correctness.

    Compares order-insensitively unless gold_sql has ORDER BY.
    Handles float values with tolerance.

    Args:
        gold_rows: Expected result rows
        generated_rows: Generated result rows
        gold_sql: Gold SQL (to check for ORDER BY)
        float_tolerance: Float comparison tolerance

    Returns:
        (is_correct, reason) tuple
    """
    # Check row count
    if len(gold_rows) != len(generated_rows):
        return False, f"Row count mismatch: expected {len(gold_rows)}, got {len(generated_rows)}"

    # If no rows, they're equal
    if len(gold_rows) == 0:
        return True, "Empty results match"

    # Check if ORDER BY is in gold SQL (order matters)
    has_order_by = "ORDER BY" in gold_sql.upper()

    # Normalize rows for comparison
    def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        """Normalize row values for comparison."""
        normalized = {}
        for key, value in row.items():
            if isinstance(value, float):
                normalized[key] = round(value, 6)  # Round floats
            elif value is None:
                normalized[key] = None
            else:
                normalized[key] = value
        return normalized

    gold_normalized = [normalize_row(r) for r in gold_rows]
    gen_normalized = [normalize_row(r) for r in generated_rows]

    if has_order_by:
        # Order matters: exact match
        if gold_normalized == gen_normalized:
            return True, "Results match (with order)"
        else:
            return False, "Results don't match (order matters)"
    else:
        # Order doesn't matter: check set equality
        try:
            gold_set = {json.dumps(r, sort_keys=True, default=str) for r in gold_normalized}
            gen_set = {json.dumps(r, sort_keys=True, default=str) for r in gen_normalized}

            if gold_set == gen_set:
                return True, "Results match (order-insensitive)"
            else:
                missing = gold_set - gen_set
                extra = gen_set - gold_set
                return (
                    False,
                    f"Results don't match: missing {len(missing)}, extra {len(extra)}",
                )
        except Exception as e:
            return False, f"Comparison error: {str(e)}"


def format_comparison_table(baseline_metrics: ExecutionMetrics, test_metrics: ExecutionMetrics) -> str:
    """Format metrics comparison as markdown table.

    Args:
        baseline_metrics: Baseline system metrics
        test_metrics: Test system metrics

    Returns:
        Markdown table string
    """
    metrics = [
        ("Execution Accuracy", f"{baseline_metrics.execution_accuracy:.1%}", f"{test_metrics.execution_accuracy:.1%}"),
        ("Answer Accuracy", f"{baseline_metrics.answer_accuracy:.1%}", f"{test_metrics.answer_accuracy:.1%}"),
        ("Schema Recall", f"{baseline_metrics.schema_retrieval_recall:.1%}", f"{test_metrics.schema_retrieval_recall:.1%}"),
        ("Retry Success Rate", f"{baseline_metrics.retry_success_rate:.1%}", f"{test_metrics.retry_success_rate:.1%}"),
        ("Avg Iterations", f"{baseline_metrics.avg_iterations:.2f}", f"{test_metrics.avg_iterations:.2f}"),
        ("p50 Latency (ms)", f"{baseline_metrics.p50_latency_ms:.0f}", f"{test_metrics.p50_latency_ms:.0f}"),
        ("p95 Latency (ms)", f"{baseline_metrics.p95_latency_ms:.0f}", f"{test_metrics.p95_latency_ms:.0f}"),
        ("Avg Tokens/Query", f"{baseline_metrics.avg_tokens_per_query:.0f}", f"{test_metrics.avg_tokens_per_query:.0f}"),
        ("Avg Cost (¢)", f"{baseline_metrics.avg_cost_cents:.4f}", f"{test_metrics.avg_cost_cents:.4f}"),
        ("Safety Block Rate", f"{baseline_metrics.unsafe_query_block_rate:.1%}", f"{test_metrics.unsafe_query_block_rate:.1%}"),
        ("Total Queries", str(baseline_metrics.total_queries), str(test_metrics.total_queries)),
        ("Failed Queries", str(baseline_metrics.failed_queries), str(test_metrics.failed_queries)),
    ]

    table = "| Metric | Baseline | Test |\n|--------|----------|------|\n"
    for metric, baseline, test in metrics:
        table += f"| {metric} | {baseline} | {test} |\n"

    return table
