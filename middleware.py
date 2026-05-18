"""
Production Middleware for CIRO Backend
======================================

Includes rate limiting, request caching, comprehensive error handling,
and request/response logging.
"""

import time
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Any
from collections import defaultdict
from functools import wraps

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import settings
from utils.logger import AgentLogger


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST CACHING
# ─────────────────────────────────────────────────────────────────────────────

class RequestCache:
    """Simple in-memory cache for request responses."""

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache with TTL."""
        self.ttl = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}

    def _get_key(self, method: str, path: str, body: str) -> str:
        """Generate cache key from request."""
        combined = f"{method}:{path}:{body}"
        return hashlib.md5(combined.encode()).hexdigest()

    def get(self, method: str, path: str, body: str) -> Any:
        """Get cached response if valid."""
        if not settings.cache_enabled:
            return None

        key = self._get_key(method, path, body)
        if key in self.cache:
            entry = self.cache[key]
            if datetime.now(timezone.utc) < entry["expires"]:
                return entry["response"]
            else:
                del self.cache[key]
        return None

    def set(self, method: str, path: str, body: str, response: Any):
        """Cache response with TTL."""
        if not settings.cache_enabled:
            return

        key = self._get_key(method, path, body)
        self.cache[key] = {
            "response": response,
            "expires": datetime.now(timezone.utc) + timedelta(seconds=self.ttl),
        }

    def clear(self):
        """Clear cache."""
        self.cache.clear()


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING
# ─────────────────────────────────────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, requests_per_minute: int = 60):
        """Initialize rate limiter."""
        self.rpm = requests_per_minute
        self.bucket: Dict[str, list] = defaultdict(list)

    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed."""
        if not settings.rate_limit_enabled:
            return True

        now = datetime.now(timezone.utc)
        # Remove old entries outside 1-minute window
        cutoff = now - timedelta(minutes=1)
        self.bucket[client_id] = [t for t in self.bucket[client_id] if t > cutoff]

        if len(self.bucket[client_id]) < self.rpm:
            self.bucket[client_id].append(now)
            return True
        return False

    def get_retry_after(self, client_id: str) -> int:
        """Get seconds until next allowed request."""
        if not self.bucket[client_id]:
            return 0
        oldest = self.bucket[client_id][0]
        retry_after = (oldest + timedelta(minutes=1) - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(retry_after) + 1)


# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────────────────────────────────────

class CIROMiddleware(BaseHTTPMiddleware):
    """Main middleware combining rate limiting, caching, and logging."""

    def __init__(self, app, rate_limiter: RateLimiter, cache: RequestCache):
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.cache = cache

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with middleware stack."""

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Skip middleware for health check endpoints
        if request.url.path in ["/health", "/docs", "/openapi.json"]:
            return await call_next(request)

        # ─────────────────────────────────────────────────────────────────
        # Request Size Validation (CRITICAL for DoS prevention)
        # ─────────────────────────────────────────────────────────────────
        if settings.enable_request_validation:
            content_length = request.headers.get("content-length")
            if content_length:
                max_size_bytes = settings.max_request_size_mb * 1024 * 1024
                try:
                    if int(content_length) > max_size_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "error": "Payload Too Large",
                                "message": f"Request size exceeds {settings.max_request_size_mb}MB limit",
                                "max_size_mb": settings.max_request_size_mb,
                            },
                        )
                except (ValueError, TypeError):
                    pass

        # ─────────────────────────────────────────────────────────────────
        # Rate Limiting
        # ─────────────────────────────────────────────────────────────────
        if not self.rate_limiter.is_allowed(client_ip):
            retry_after = self.rate_limiter.get_retry_after(client_ip)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "message": f"Rate limit exceeded. Retry after {retry_after} seconds.",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # ─────────────────────────────────────────────────────────────────
        # Cache Invalidation for State-Changing Requests (CRITICAL)
        # ─────────────────────────────────────────────────────────────────
        if settings.enable_cache_invalidation and request.method in ["POST", "PUT", "DELETE", "PATCH"]:
            self.cache.clear()

        # ─────────────────────────────────────────────────────────────────
        # Skip static files and /docs from caching & monitoring
        # ─────────────────────────────────────────────────────────────────
        skip_caching = request.url.path.startswith("/static") or request.url.path.startswith("/docs") or request.url.path.startswith("/redoc") or request.url.path == "/"

        # Request Caching (only for GET requests, JSON endpoints)
        request_body = ""
        if request.method == "GET" and not skip_caching:
            cached_response = self.cache.get(request.method, request.url.path, "")
            if cached_response:
                return JSONResponse(
                    content=cached_response,
                    headers={"X-Cache": "HIT", "X-Cache-TTL": str(settings.cache_ttl_seconds)},
                )

        # ─────────────────────────────────────────────────────────────────
        # Request Logging & Timing
        # ─────────────────────────────────────────────────────────────────
        start_time = time.time()
        request_timestamp = datetime.now(timezone.utc).isoformat()

        try:
            response = await call_next(request)
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Alert if processing time exceeds threshold
            if processing_time_ms > settings.alert_threshold_ms:
                print(
                    f"[ALERT] Slow request: {request.method} {request.url.path} "
                    f"took {processing_time_ms}ms (threshold: {settings.alert_threshold_ms}ms)"
                )

            # Add headers (but not to static files)
            if not skip_caching:
                response.headers["X-Request-ID"] = f"{client_ip}-{int(start_time * 1000)}"
                response.headers["X-Processing-Time-MS"] = str(processing_time_ms)
                response.headers["X-Timestamp"] = request_timestamp

            # Cache GET responses (JSON only, skip static files)
            if request.method == "GET" and response.status_code == 200 and not skip_caching:
                try:
                    body = b""
                    async for chunk in response.body_iterator:
                        body += chunk
                    response_content = json.loads(body)
                    self.cache.set(request.method, request.url.path, "", response_content)
                    # Wrap response to preserve body
                    return Response(
                        content=body,
                        status_code=response.status_code,
                        headers=dict(response.headers),
                        media_type=response.media_type,
                    )
                except (json.JSONDecodeError, AttributeError):
                    pass  # Can't cache non-JSON responses

            return response

        except Exception as e:
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Log error
            print(
                f"[ERROR] {request.method} {request.url.path} - "
                f"{type(e).__name__}: {str(e)[:100]} "
                f"({processing_time_ms}ms)"
            )

            # Return error response
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "message": str(e)[:200],
                    "timestamp": request_timestamp,
                    "path": request.url.path,
                },
                headers={
                    "X-Request-ID": f"{client_ip}-{int(start_time * 1000)}",
                    "X-Processing-Time-MS": str(processing_time_ms),
                },
            )


# ─────────────────────────────────────────────────────────────────────────────
# MONITORING UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceMonitor:
    """Track application performance metrics."""

    def __init__(self):
        self.total_requests = 0
        self.total_errors = 0
        self.total_processing_time_ms = 0
        self.endpoint_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "total_time": 0, "errors": 0}
        )

    def record_request(self, endpoint: str, processing_time_ms: int, success: bool = True):
        """Record request statistics."""
        self.total_requests += 1
        self.total_processing_time_ms += processing_time_ms

        stats = self.endpoint_stats[endpoint]
        stats["count"] += 1
        stats["total_time"] += processing_time_ms

        if not success:
            self.total_errors += 1
            stats["errors"] += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics."""
        avg_time = (
            self.total_processing_time_ms / self.total_requests if self.total_requests > 0 else 0
        )

        endpoint_summaries = {
            path: {
                "requests": stats["count"],
                "avg_time_ms": int(stats["total_time"] / stats["count"]) if stats["count"] > 0 else 0,
                "errors": stats["errors"],
                "error_rate": f"{(stats['errors'] / stats['count'] * 100):.1f}%" if stats["count"] > 0 else "0%",
            }
            for path, stats in self.endpoint_stats.items()
        }

        return {
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "error_rate": f"{(self.total_errors / self.total_requests * 100):.1f}%" if self.total_requests > 0 else "0%",
            "avg_response_time_ms": int(avg_time),
            "endpoints": endpoint_summaries,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Global instances
request_cache = RequestCache(settings.cache_ttl_seconds)
rate_limiter = RateLimiter(settings.rate_limit_per_minute)
performance_monitor = PerformanceMonitor()
