# QueryPilot Docker Setup

This document describes the Docker Compose setup for QueryPilot local development and deployment.

## Services

### 1. **app_db** (PostgreSQL 16)
- **Container:** `querypilot_app_db`
- **Port:** 5432
- **Database:** `querypilot_app`
- **User:** `app_user` / `app_password`
- **Purpose:** Stores conversations, query logs, eval results, and all QueryPilot metadata
- **Init Script:** `seed/init_app_db.sh` creates schema on first run
- **Statement Timeout:** 30s (default for app operations)

### 2. **target_db** (PostgreSQL 16)
- **Container:** `querypilot_target_db`
- **Port:** 5433
- **Database:** `querypilot_target`
- **Users:**
  - `analytics_user` (admin, for initialization)
  - `querypilot_ro` (read-only, for agent queries)
- **Purpose:** The e-commerce analytics database the agent queries
- **Init Script:** `seed/schema.sql` creates schema (customers, products, orders, etc.) on first run
- **Statement Timeout:** 5s (strict limit for agent queries)
- **Role:** `querypilot_ro` has SELECT-only, enforced both at role and transaction level

### 3. **redis** (Redis 7)
- **Container:** `querypilot_redis`
- **Port:** 6379
- **Purpose:** Cache, checkpoints for in-flight LangGraph runs, rate limits
- **No persistence by default** (fine for dev/test)

### 4. **langfuse_db** (PostgreSQL 16)
- **Container:** `querypilot_langfuse_db`
- **Port:** Not exposed (internal)
- **Database:** `langfuse`
- **User:** `langfuse_user` / `langfuse_password`
- **Purpose:** Backend database for Langfuse observability service

### 5. **langfuse** (Langfuse UI)
- **Container:** `querypilot_langfuse`
- **Port:** 3000
- **URL:** http://localhost:3000
- **Purpose:** Trace collection, LLM call inspection, cost/latency analysis
- **Depends on:** `langfuse_db`

### 6. **api** (QueryPilot FastAPI)
- **Container:** `querypilot_api`
- **Port:** 8000
- **URL:** http://localhost:8000
- **Purpose:** Main REST API (chat, conversations, eval)
- **Environment variables:**
  - `DEBUG`: Set to `true` for development
  - `LLM_PROVIDER`: `openai`, `anthropic`, or `bedrock`
  - `LLM_MODEL`: Model identifier (e.g., `gpt-4-turbo`, `claude-3-sonnet`)
  - `LANGCHAIN_API_KEY`: LLM provider API key
  - `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`: Optional, for tracing
- **Depends on:** app_db, target_db, redis (all healthy)

## Quick Start

### 1. Build and start all services

```bash
# Copy the example env file
cp .env.example .env

# Edit .env with your credentials
# Minimally add: LANGCHAIN_API_KEY, LLM_PROVIDER, LLM_MODEL

# Build and start
docker compose up -d
```

### 2. Wait for all services to be healthy

```bash
docker compose ps

# Expected output:
# NAME                      STATUS              PORTS
# querypilot_app_db         healthy             5432/tcp
# querypilot_target_db      healthy             5433/tcp
# querypilot_redis          healthy             6379/tcp
# querypilot_langfuse_db    healthy             5432/tcp
# querypilot_langfuse       healthy             3000/tcp
# querypilot_api            healthy             8000/tcp
```

### 3. Verify databases

```bash
# Verify target DB schema
docker exec querypilot_target_db psql -U analytics_user -d querypilot_target -c "\dt"

# Test read-only role
docker exec querypilot_target_db psql -U querypilot_ro -d querypilot_target \
  -c "SELECT COUNT(*) FROM customers;"  # Should work
```

### 4. Test the API

```bash
curl http://localhost:8000/health

# Should return: {"status": "ok", "timestamp": "2025-10-04T..."}
```

### 5. View traces in Langfuse

```
http://localhost:3000
```

## Environment Variables

All services read from `.env` (Docker Compose file):

```bash
# Debug and API
DEBUG=false
API_PORT=8000

# LLM Provider Configuration
LLM_PROVIDER=openai                    # or anthropic, bedrock
LLM_MODEL=gpt-4-turbo
LANGCHAIN_API_KEY=sk-...               # Your API key

# Observability (optional)
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...

# Langfuse UI Secret (default is OK for dev)
LANGFUSE_NEXTAUTH_SECRET=supersecret-change-in-production
```

## Common Tasks

### Seed the target DB with synthetic data

```bash
# Run from your local machine (not in container)
python -m seed.generator

# Or from inside the container
docker exec querypilot_api python -m seed.generator
```

### Verify target DB integrity

```bash
docker exec querypilot_api python -m seed.verify
```

### View app_db schema

```bash
docker exec querypilot_app_db psql -U app_user -d querypilot_app -c "\dt+"
```

### Run tests inside container

```bash
docker exec querypilot_api pytest tests/ -v
```

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api
docker compose logs -f target_db
```

### Stop and clean up

```bash
# Stop all services (preserve data)
docker compose down

# Stop and remove volumes (dangerous!)
docker compose down -v
```

### Rebuild the API image

```bash
docker compose up -d --build api
```

## Performance & Limits

- **target_db statement_timeout:** 5s (agent queries)
- **app_db statement_timeout:** 30s (app metadata queries)
- **API start_period:** 15s (allows FastAPI startup + health check)
- **Service health checks:** Every 10s, 3 retries

## Production Considerations

1. **Persist Redis:** Add a volume to `redis` service for checkpoint recovery
2. **Langfuse:** Configure `NEXTAUTH_SECRET` to a strong random value
3. **Database passwords:** Use strong, randomly generated passwords (not `app_password`)
4. **Network:** Consider using a dedicated network or reverse proxy (nginx)
5. **Resource limits:** Add `deploy.resources.limits` to each service
6. **Backup strategy:** Ensure `app_db_data` and `target_db_data` volumes are backed up regularly

## Troubleshooting

### API container exits immediately
- Check logs: `docker compose logs api`
- Verify databases are healthy: `docker compose ps`
- Ensure all env vars are set in `.env`

### Can't connect to target_db as `querypilot_ro`
- Verify role exists: `docker exec querypilot_target_db psql -U analytics_user -d querypilot_target -c "\\du"`
- Check role permissions: `docker exec querypilot_target_db psql -U analytics_user -d querypilot_target -c "SELECT * FROM information_schema.role_table_grants WHERE grantee = 'querypilot_ro';"`

### Langfuse container keeps restarting
- Check if langfuse_db is healthy: `docker compose ps langfuse_db`
- Verify database URL is correct: `docker compose logs langfuse | grep DATABASE_URL`

### API health check fails
- Check if FastAPI app is running: `docker exec querypilot_api curl -f http://localhost:8000/health`
- Check app.main for `/health` endpoint implementation

## References

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [PostgreSQL Official Docker Image](https://hub.docker.com/_/postgres)
- [Redis Official Docker Image](https://hub.docker.com/_/redis)
- [Langfuse Docker Guide](https://langfuse.com/docs/deployment)
