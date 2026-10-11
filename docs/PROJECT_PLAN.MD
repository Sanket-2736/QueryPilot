# QueryPilot: Stateful Text-to-SQL Agent

> Save this file as `docs/PROJECT_PLAN.md`. Kiro specs and steering files reference it as the source of truth.

## 1. Problem definition

**Who has this problem:** Business users (ops, sales, finance) need answers from a relational database but can't write SQL. Analysts become a bottleneck for ad-hoc questions like *"Top 5 customers by revenue in 2025 vs 2024."*

**Why a single LLM call isn't enough:**

| Problem | Example |
|---|---|
| Schema hallucination | The model invents `customers.total_revenue` when revenue must be computed from `orders` |
| Wrong joins and filters | Double-counting revenue through a one-to-many join |
| Invalid SQL | Syntax errors, wrong dialect functions |
| Unsafe SQL | `DROP TABLE`, `UPDATE`, or unbounded `SELECT *` on huge tables |
| Ambiguity | "Revenue" could mean gross, net, or paid-only |
| Multi-step questions | Comparing 2025 vs 2024 may need one query or two |
| No memory | A follow-up like *"now only for Maharashtra"* fails without context |

**Goal:** Build an agent that turns natural-language questions into **safe, validated, correct** SQL. It executes the SQL read-only, recovers from its own errors, explains results, and remembers context across a conversation. It must also be measurable, with an evaluation harness that shows accuracy and where it fails.

**Non-goals:** Write operations, a general BI tool, or multi-database federation.

## 2. Solution overview

A **LangGraph state machine** where each node does one job and the edges encode control flow (retry, replan, reject). The LLM only generates and interprets. **Everything that must be deterministic, like safety, validation, and execution limits, lives in plain Python code outside the LLM.**

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Next.js UI  (chat, SQL viewer, result table, trace link)   │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST / SSE streaming
┌──────────────────────────▼──────────────────────────────────┐
│  FastAPI service                                            │
│   /chat  /conversations/{id}  /eval/run  /health            │
│   auth, rate limiting, request IDs                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  LangGraph Agent                                            │
│                                                             │
│  load_memory → planner ─┬─► retrieve_schema ─┐              │
│                         └────────────────────┤              │
│                                       generate_sql          │
│                                              │              │
│                                       validate_sql ──reject─┼─► final (refusal)
│                                              │ ok           │
│                                       execute_sql           │
│                                  ┌───────────┴──────────┐   │
│                              error                    success│
│                                  │                       │   │
│                      retries < N? ──► fix_sql         analyze │
│                      (or replan)        │                │   │
│                                         └─► validate     │   │
│                                                    final_answer
│                                                          │   │
│                                                   save_memory│
└───────┬──────────────────┬───────────────────┬──────────────┘
        │                  │                   │
┌───────▼──────┐  ┌────────▼───────┐  ┌────────▼────────────┐
│ Target DB    │  │ App DB (PG)    │  │ Redis               │
│ READ-ONLY    │  │ conversations, │  │ checkpoints, schema │
│ role         │  │ queries, evals │  │ cache, rate limits  │
└──────────────┘  └────────────────┘  └─────────────────────┘

        Langfuse / LangSmith  ◄── traces from every node + tool call
```

**Keep two separate databases/roles:**
- **Target DB**: the analytics data the agent queries. Connect with a role that has `SELECT` only.
- **App DB**: your own metadata (conversations, query logs, eval results), which the agent never queries.

## 4. Core components

### 4.1 Agent state

```python
from typing import TypedDict, Optional, Literal

class AgentState(TypedDict):
    conversation_id: str
    user_id: str
    question: str
    history: list[dict]            # previous Q/SQL/result summaries
    plan: list[str]                # ordered steps from planner
    needs_schema: bool
    schema_context: str            # only relevant tables/columns
    sql: Optional[str]
    validation: Optional[dict]     # {ok, reason, tables_used}
    result: Optional[dict]         # {columns, rows, row_count}
    error: Optional[str]
    retries: int
    iterations: int                # global step budget
    status: Literal["running", "answered", "rejected", "failed", "needs_clarification"]
    answer: Optional[str]
```

### 4.2 Nodes

| Node | Responsibility | LLM? |
|---|---|---|
| `load_memory` | Pull recent turns and successful queries for this conversation | No |
| `planner` | Break question into steps, decide if schema is needed, flag ambiguity (ask a clarifying question instead of guessing) | Yes |
| `retrieve_schema` | Return only relevant tables, columns, types, FKs, and sample values | No (embedding search if the schema is large) |
| `generate_sql` | Produce SQL from the plan, schema context, and history | Yes |
| `validate_sql` | Parse, check allowlist, enforce limits | **No** |
| `execute_sql` | Run on the read-only DB with timeout and row cap | **No** |
| `fix_sql` | Given SQL plus error plus schema, produce a corrected query | Yes |
| `analyze_result` | Summarize, compute YoY change, and flag suspicious results (empty, NULLs) | Yes |
| `save_memory` | Persist the turn to PostgreSQL | No |

### 4.3 Routing logic (the "planner loop")

```python
from langgraph.graph import StateGraph, END

MAX_RETRIES = 3
MAX_ITERATIONS = 10

def after_planner(s):
    if s["status"] == "needs_clarification": return "final"
    return "retrieve_schema" if s["needs_schema"] else "generate_sql"

def after_validation(s):
    if s["validation"]["ok"]: return "execute_sql"
    return "fix_sql" if s["retries"] < MAX_RETRIES else "final"

def after_execution(s):
    if s["iterations"] >= MAX_ITERATIONS: return "final"
    if s["error"]:
        # first retries: fix SQL; repeated failure: replan with fresh schema
        if s["retries"] >= 2 and s["retries"] < MAX_RETRIES: return "planner"
        return "fix_sql" if s["retries"] < MAX_RETRIES else "final"
    return "analyze_result"

g = StateGraph(AgentState)
# add_node(...) for each node above
g.add_conditional_edges("planner", after_planner)
g.add_conditional_edges("validate_sql", after_validation)
g.add_conditional_edges("execute_sql", after_execution)
```

> Implementation note: a validation rejection for a *destructive* statement should end as `rejected` (not retried through `fix_sql`). Only syntax or schema errors should be retried.

### 4.4 Deterministic SQL validator (most important safety piece)

Use **`sqlglot`** to parse instead of regex:

```python
import sqlglot
from sqlglot import exp

FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
             exp.Alter, exp.Command, exp.TruncateTable)

def validate_sql(sql: str, allowed_tables: set[str]) -> dict:
    try:
        trees = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as e:
        return {"ok": False, "reason": f"syntax: {e}"}

    if len(trees) != 1:
        return {"ok": False, "reason": "multiple statements not allowed"}
    tree = trees[0]
    if not isinstance(tree, exp.Select) and not tree.find(exp.Select):
        return {"ok": False, "reason": "only SELECT allowed"}
    if tree.find(*FORBIDDEN):
        return {"ok": False, "reason": "write/DDL operation detected"}

    used = {t.name for t in tree.find_all(exp.Table)}
    unknown = used - allowed_tables - {c.alias for c in tree.find_all(exp.CTE)}
    if unknown:
        return {"ok": False, "reason": f"unknown tables: {unknown}"}

    if not tree.args.get("limit"):
        tree = tree.limit(1000)           # enforce row cap
    return {"ok": True, "sql": tree.sql(dialect="postgres"), "tables_used": used}
```

> This is a starting sketch. The hardened version (UNION/CTE handling, clamping existing LIMITs above 1000, blocking dangerous functions such as `pg_sleep`, `pg_read_file`, `dblink`, `set_config`, and system catalogs) is specified in build step 2.

### 4.5 Defense in depth for execution

Don't rely on the validator alone. Layer these:

1. **Read-only DB role** (`GRANT SELECT` only, on specific tables or views)
2. **Read-only transaction**: `SET TRANSACTION READ ONLY`
3. **Timeout**: `SET statement_timeout = '5s'`
4. **Row cap** enforced both in SQL (`LIMIT`) and when fetching
5. **Optionally** expose only sanitized **views**, hiding PII columns

### 4.6 Schema retrieval

- **Small schema (under ~20 tables):** include the full schema in the prompt, with column descriptions.
- **Large schema:** embed each table's description (name, columns, business meaning) in **pgvector**, retrieve the top-k tables, and expand via foreign keys so join paths aren't lost.
- Store a **semantic layer** file (YAML) defining business terms, e.g. `revenue = SUM(order_items.quantity * unit_price) WHERE orders.status = 'paid'`. This solves the ambiguity problem far better than hoping the model guesses.

### 4.7 Memory and state

| Store | Contents | Why |
|---|---|---|
| **PostgreSQL (App DB)** | `conversations`, `messages`, `query_log` (sql, result summary, success/fail, latency, tokens), `eval_runs` | Durable and queryable history |
| **Redis** | LangGraph checkpoints for in-flight runs, schema cache, rate limits | Fast and resumable; if the process dies mid-run, resume from the last node |

- **Short-term memory:** last N turns passed into the prompt.
- **Long-term memory:** retrieve *successful* past queries for similar questions and use them as few-shot examples. This is a real, measurable improvement you can report in your evals.
- **Long conversations:** summarize old turns rather than replaying everything.

Use LangGraph's checkpointer with a `thread_id = conversation_id`.

## 5. Project structure

```
querypilot/
├── app/
│   ├── main.py                # FastAPI entry
│   ├── api/                   # routes: chat, conversations, eval
│   ├── agent/
│   │   ├── state.py
│   │   ├── graph.py           # LangGraph wiring + routing
│   │   ├── nodes/             # planner.py, generate_sql.py, fix_sql.py, ...
│   │   └── prompts/           # versioned prompt templates
│   ├── tools/
│   │   ├── schema.py          # get_schema, get_table_metadata
│   │   ├── validator.py       # validate_sql
│   │   ├── executor.py        # execute_sql
│   │   └── history.py         # get_previous_query
│   ├── memory/                # postgres.py, redis.py
│   ├── semantic_layer.yaml
│   ├── observability.py       # Langfuse setup
│   └── config.py              # pydantic-settings
├── eval/
│   ├── dataset.jsonl          # question, gold_sql, expected tables, category
│   ├── run_eval.py
│   ├── metrics.py
│   └── failure_injection.py
├── seed/                      # sample DB schema + data generator
├── tests/                     # unit tests for validator/executor
├── docker-compose.yml         # api, postgres(app), postgres(target), redis, langfuse
└── README.md
```

## 6. Evaluation harness

**Dataset (50-100 items):** each is `{question, gold_sql, expected_tables, category}`. Categories: simple aggregation, joins, time comparison, follow-up (needs memory), ambiguous, adversarial/destructive.

**Scoring SQL correctness by result, not text.** Run the gold SQL and the generated SQL, then compare result sets (order-insensitive unless there's an `ORDER BY`). Two different queries can both be right.

**Metrics:**
- Execution accuracy and answer accuracy
- Schema retrieval recall (did it fetch the needed tables?)
- Tool selection accuracy
- Retry success rate and average iterations
- p50/p95 latency, tokens, and cost per query
- Unsafe query block rate (should be 100%)

**Failure injection experiments:** run each failure mode and record before/after numbers.

| Failure | Mitigation | What to report |
|---|---|---|
| Wrong table/column | Schema retrieval + validator allowlist | Accuracy before vs. after |
| Incorrect JOIN (fan-out) | FK hints in the schema, semantic-layer metrics | Wrong-total rate |
| Invalid SQL | `fix_sql` retry loop | Retry recovery % |
| Destructive SQL | Parser check + read-only role | 100% blocked |
| Ambiguous question | Planner asks a clarification | Clarification precision |
| Missing schema info | Replan with re-retrieval | Recovery rate |

Log everything to a results table so you can say *"execution accuracy improved from X% to Y% after adding the semantic layer and retry loop."*

## 7. Build order

1. **Seed DB and baseline.** Create a synthetic e-commerce schema (customers, orders, order_items, products) and a single-prompt text-to-SQL baseline. Run the eval on it first so you have a "before" number.
2. **Tools.** Implement the validator and executor with unit tests (including destructive-SQL tests).
3. **Schema retrieval and semantic layer.**
4. **LangGraph loop.** Add planner → schema → generate → validate → execute → fix.
5. **Memory.** Add Postgres persistence, the Redis checkpointer, and follow-up handling.
6. **Eval and failure injection.** Compare against the baseline.
7. **FastAPI + Docker + Langfuse traces.**
8. **Next.js UI** (optional and last; a simple chat page is enough).

## 8. Progress checklist

Don't start a step until the previous one's tests pass.

- [ ] **Step 0:** Steering files (`product.md`, `tech.md`, `structure.md`) and scaffold
- [ ] **Step 1:** Seed DB, read-only role, baseline, 20-item dataset, baseline "before" number recorded
- [ ] **Step 2:** Validator (30+ tests) and executor (timeout and DB-level write-block tests)
- [ ] **Step 3:** Schema retrieval, FK expansion, semantic layer, recall metric
- [ ] **Step 4:** LangGraph loop, fake-LLM graph tests (happy, fix, reject, exhausted, clarify, budget)
- [ ] **Step 5:** Memory, follow-ups, long-term few-shot flag, Redis checkpoint resume
- [ ] **Step 6:** 60+ item eval, failure injection, before/after report, numbers in README
- [ ] **Step 7:** FastAPI, auth, rate limits, Langfuse, `docker compose up` works end to end
- [ ] **Step 8 (optional):** Next.js chat UI
- [ ] **Step 9:** Hooks and README polish

## 9. Mapping to the application form

- **Planner/reasoning loop:** planner decides schema retrieval, and the validate/execute failure paths trigger fix or replan under a step budget.
- **Tool use:** schema, validation, and execution tools where the *safety-critical ones are deterministic*.
- **Memory/state:** Postgres for durable history, Redis checkpoints for resumable runs.
- **Evaluation:** result-set-based execution accuracy against a gold dataset, with a before/after baseline.
- **Failure modes:** the table in section 6, each with a measured mitigation.
- **Production behavior:** read-only role, timeouts, bounded retries, tracing, and Dockerized deployment.

Only claim what you actually build and measure. If you skip Redis or the UI, say so, because a smaller project with real eval numbers beats a bigger one you can't defend.