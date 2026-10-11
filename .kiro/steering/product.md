# QueryPilot Product Principles

## Problem
Business users (ops, sales, finance) need answers from a relational database but cannot write SQL. Analysts become bottlenecks for ad-hoc questions like "Top 5 customers by revenue in 2025 vs 2024."

A single LLM call fails because models:
- Hallucinate schema (invent columns that don't exist)
- Produce incorrect joins causing double-counting
- Generate invalid SQL with syntax errors
- Have no safety guardrails (can execute DROP TABLE)
- Can't handle ambiguity ("revenue" = gross, net, or paid-only?)
- Lack memory across multi-turn conversations

## Solution
A **stateful text-to-SQL agent** built on LangGraph that:
- Breaks questions into steps via a planner
- Retrieves only relevant schema
- Generates SQL with schema context and history
- **Validates using deterministic Python code (sqlglot), not LLM judgment**
- Executes read-only against a separate target database
- Recovers from errors via fix/retry or replanning
- Remembers context across conversation turns
- Explains results and flags anomalies

## Goals
- Turn natural-language questions into safe, validated, correct SQL
- Execute read-only and recover from generation errors
- Maintain conversation context across multiple turns
- Provide measurable accuracy and traceability
- Defend against destructive SQL and schema hallucination

## Non-Goals
- Write operations (INSERT, UPDATE, DELETE)
- General BI/dashboarding tool
- Multi-database federation
- Real-time query optimization

## Core Principle
**Everything that must be deterministic—safety, validation, execution limits—lives in plain Python code outside the LLM.**

- Schema validation uses sqlglot AST parsing, not regex
- SQL allowlist and table checks are enforced before execution
- Row limits and timeouts are set at the connection and query level
- Read-only is guaranteed by the database role, not LLM compliance

This separation means the agent can iterate fast on LLM prompts without compromising safety.

## Key Metrics
- Execution accuracy (result set correctness against gold SQL)
- Unsafe query block rate (should be 100%)
- Schema retrieval recall (fetched needed tables)
- Retry success rate and iteration budget usage
- p50/p95 latency and token cost
- Clarification precision (questions asked vs. guesses made)
