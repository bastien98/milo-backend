"""
In-memory caching module for analytics and budget data.

Uses TTLCache for automatic expiration. Cache is invalidated when user data changes
(receipt upload, delete, bank sync, etc.) through the invalidate_user() function.

Note: This is an in-memory cache that doesn't persist across server restarts
and doesn't sync across multiple instances. For single-instance deployments
this provides significant performance benefits with minimal complexity.
"""

import logging
from datetime import date
from functools import wraps
from typing import Callable, Any

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# Main cache: 10,000 entries max, 5 minute default TTL
_cache: TTLCache = TTLCache(maxsize=10000, ttl=300)

# Track cache statistics for monitoring
_cache_stats = {"hits": 0, "misses": 0}


def _build_cache_key(
    func_name: str,
    user_id: str,
    include_month: bool = False,
    **params: Any,
) -> str:
    """Build a cache key from function name, user_id, and parameters.

    Args:
        func_name: Name of the cached function
        user_id: User ID for cache isolation
        include_month: If True, include current month in key (for time-sensitive data)
        **params: Additional parameters to include in the key
    """
    if include_month:
        params["_month"] = date.today().strftime("%Y-%m")

    # Sort params for consistent key generation
    param_str = ":".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
    return f"{func_name}:{user_id}:{param_str}"


def cached(include_month: bool = False):
    """Decorator to cache async function results.

    Args:
        include_month: If True, cache key includes current month.
                      Use for functions that return "current month" data
                      to auto-invalidate at month boundaries.

    Usage:
        @cached()
        async def get_pie_chart_summary(self, user_id: str, month: int, year: int):
            ...

        @cached(include_month=True)
        async def get_current_month_spend(self, user_id: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            global _cache_stats

            # Extract user_id from args or kwargs
            # Typically: self, user_id, ... or self, db, user_id, ...
            user_id = kwargs.get("user_id")
            if user_id is None:
                # Try to find user_id in positional args (skip self)
                for arg in args[1:]:
                    if isinstance(arg, str) and len(arg) > 10:  # Likely a user_id
                        user_id = arg
                        break

            if user_id is None:
                # Can't cache without user_id, just execute
                logger.warning(f"Cache: No user_id found for {func.__name__}, skipping cache")
                return await func(*args, **kwargs)

            # Build cache key from all kwargs except 'db' (session objects aren't hashable)
            cache_params = {k: v for k, v in kwargs.items() if k not in ("db", "user_id")}

            # Also include relevant positional args (skip self and user_id)
            # This handles cases like get_pie_chart_summary(self, user_id, month, year)
            arg_names = func.__code__.co_varnames[1:]  # Skip 'self'
            for i, (name, value) in enumerate(zip(arg_names, args[1:])):
                if name not in ("db", "user_id") and name not in cache_params:
                    # Only include hashable values
                    if isinstance(value, (str, int, float, bool, type(None), date)):
                        cache_params[name] = value

            cache_key = _build_cache_key(
                func.__name__,
                user_id,
                include_month=include_month,
                **cache_params,
            )

            # Check cache
            if cache_key in _cache:
                _cache_stats["hits"] += 1
                logger.debug(f"Cache HIT: {cache_key}")
                return _cache[cache_key]

            # Cache miss - execute function
            _cache_stats["misses"] += 1
            logger.debug(f"Cache MISS: {cache_key}")

            result = await func(*args, **kwargs)

            # Store in cache
            _cache[cache_key] = result

            return result

        return wrapper
    return decorator


def invalidate_user(user_id: str) -> int:
    """Invalidate all cached data for a specific user.

    Call this when user data changes:
    - Receipt uploaded
    - Receipt deleted
    - Line item deleted
    - Bank transactions synced
    - Budget updated

    Args:
        user_id: The user whose cache should be invalidated

    Returns:
        Number of cache entries invalidated
    """
    keys_to_delete = [k for k in list(_cache.keys()) if f":{user_id}:" in k]

    for key in keys_to_delete:
        del _cache[key]

    if keys_to_delete:
        logger.info(f"Cache invalidated for user {user_id}: {len(keys_to_delete)} entries cleared")

    return len(keys_to_delete)


def get_cache_stats() -> dict:
    """Get cache statistics for monitoring.

    Returns:
        Dict with hits, misses, hit_rate, and current_size
    """
    total = _cache_stats["hits"] + _cache_stats["misses"]
    hit_rate = (_cache_stats["hits"] / total * 100) if total > 0 else 0

    return {
        "hits": _cache_stats["hits"],
        "misses": _cache_stats["misses"],
        "hit_rate": round(hit_rate, 1),
        "current_size": len(_cache),
        "max_size": _cache.maxsize,
        "ttl_seconds": _cache.ttl,
    }


def clear_all() -> int:
    """Clear the entire cache. Use sparingly (e.g., for testing).

    Returns:
        Number of entries cleared
    """
    count = len(_cache)
    _cache.clear()
    logger.info(f"Cache cleared: {count} entries removed")
    return count
