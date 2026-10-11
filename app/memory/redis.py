"""Redis integration for LangGraph checkpointing and schema caching."""

import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from app.config import get_config

logger = logging.getLogger(__name__)


async def get_redis_client() -> Optional[redis.Redis]:
    """Get async Redis client."""
    config = get_config()
    if not config.redis_url:
        logger.warning("Redis URL not configured; checkpointing disabled")
        return None

    try:
        client = await redis.from_url(config.redis_url, decode_responses=True)
        await client.ping()
        logger.info("Connected to Redis")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return None


async def save_checkpoint(
    thread_id: str,
    checkpoint_data: dict[str, Any],
    ttl_seconds: int = 86400,  # 24 hours
) -> bool:
    """Save LangGraph checkpoint to Redis.

    Args:
        thread_id: Unique identifier for this execution thread (conversation_id)
        checkpoint_data: State dict to persist
        ttl_seconds: Time to live for the checkpoint

    Returns:
        True if saved successfully, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False

    try:
        key = f"langgraph:checkpoint:{thread_id}"
        await client.setex(
            key,
            ttl_seconds,
            json.dumps(checkpoint_data),
        )
        logger.info(f"Saved checkpoint for thread {thread_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save checkpoint: {e}")
        return False
    finally:
        await client.close()


async def load_checkpoint(thread_id: str) -> Optional[dict[str, Any]]:
    """Load LangGraph checkpoint from Redis.

    Args:
        thread_id: Unique identifier for this execution thread

    Returns:
        State dict if found, None otherwise
    """
    client = await get_redis_client()
    if not client:
        return None

    try:
        key = f"langgraph:checkpoint:{thread_id}"
        data = await client.get(key)
        if data:
            logger.info(f"Loaded checkpoint for thread {thread_id}")
            return json.loads(data)
        else:
            logger.info(f"No checkpoint found for thread {thread_id}")
            return None
    except Exception as e:
        logger.error(f"Failed to load checkpoint: {e}")
        return None
    finally:
        await client.close()


async def cache_schema(
    db_name: str,
    schema_data: dict[str, Any],
    ttl_seconds: int = 3600,  # 1 hour
) -> bool:
    """Cache database schema in Redis.

    Args:
        db_name: Database identifier
        schema_data: Schema dict to cache
        ttl_seconds: Time to live for the cache

    Returns:
        True if cached successfully, False otherwise
    """
    client = await get_redis_client()
    if not client:
        return False

    try:
        key = f"schema:cache:{db_name}"
        await client.setex(
            key,
            ttl_seconds,
            json.dumps(schema_data),
        )
        logger.info(f"Cached schema for {db_name}")
        return True
    except Exception as e:
        logger.error(f"Failed to cache schema: {e}")
        return False
    finally:
        await client.close()


async def get_cached_schema(db_name: str) -> Optional[dict[str, Any]]:
    """Get cached schema from Redis.

    Args:
        db_name: Database identifier

    Returns:
        Schema dict if found, None otherwise
    """
    client = await get_redis_client()
    if not client:
        return None

    try:
        key = f"schema:cache:{db_name}"
        data = await client.get(key)
        if data:
            logger.info(f"Retrieved cached schema for {db_name}")
            return json.loads(data)
        else:
            logger.debug(f"No cached schema found for {db_name}")
            return None
    except Exception as e:
        logger.error(f"Failed to get cached schema: {e}")
        return None
    finally:
        await client.close()


async def increment_rate_limit(
    user_id: str,
    limit_per_hour: int = 100,
) -> tuple[int, bool]:
    """Increment rate limit counter for a user.

    Args:
        user_id: User identifier
        limit_per_hour: Maximum requests per hour

    Returns:
        Tuple of (current_count, is_allowed)
    """
    client = await get_redis_client()
    if not client:
        # If Redis unavailable, allow requests
        return (0, True)

    try:
        key = f"rate_limit:{user_id}"
        current = await client.incr(key)
        
        # Set expiry on first request
        if current == 1:
            await client.expire(key, 3600)  # 1 hour

        is_allowed = current <= limit_per_hour
        logger.info(f"Rate limit for {user_id}: {current}/{limit_per_hour}")
        return (current, is_allowed)

    except Exception as e:
        logger.error(f"Failed to check rate limit: {e}")
        return (0, True)  # Allow on error
    finally:
        await client.close()
