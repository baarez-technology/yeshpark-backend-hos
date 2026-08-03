"""
Redis-based Distributed Lock Manager for Room Assignments

Provides atomic room locking to prevent race conditions during:
- Pre-checkin room selection
- Smart room assignment
- Manual room assignment by staff

Uses Redis SET NX with TTL for atomic operations.
"""

import redis.asyncio as aioredis
from typing import Optional, Tuple, List, Dict, Any
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class RedisLockManager:
    """
    Manages distributed locks for room assignments using Redis.

    Lock Key Format: room:lock:{room_id}
    Lock Value: JSON with booking_id, acquired_at, ttl
    """

    LOCK_PREFIX = "room:lock:"
    DEFAULT_TTL = 900  # 15 minutes in seconds
    EXTEND_TTL = 300   # 5 minutes extension

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None

    async def get_client(self) -> aioredis.Redis:
        """Get or create async Redis client."""
        if self._client is None:
            self._client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        return self._client

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None

    def _get_lock_key(self, room_id: int) -> str:
        """Generate lock key for a room."""
        return f"{self.LOCK_PREFIX}{room_id}"

    async def acquire_room_lock(
        self,
        room_id: int,
        booking_id: int,
        ttl: int = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Acquire a lock on a room for a specific booking.

        Uses Redis SET NX (SET if Not eXists) for atomic lock acquisition.

        Args:
            room_id: The room to lock
            booking_id: The booking requesting the lock
            ttl: Time-to-live in seconds (default 15 minutes)

        Returns:
            Tuple of (success: bool, lock_token: Optional[str])
        """
        if ttl is None:
            ttl = self.DEFAULT_TTL

        client = await self.get_client()
        lock_key = self._get_lock_key(room_id)

        lock_data = json.dumps({
            "booking_id": booking_id,
            "acquired_at": datetime.utcnow().isoformat(),
            "ttl": ttl
        })

        # SET NX - only set if key doesn't exist
        acquired = await client.set(
            lock_key,
            lock_data,
            nx=True,  # Only set if not exists
            ex=ttl    # Expire after TTL seconds
        )

        if acquired:
            logger.info(f"Lock acquired: room={room_id}, booking={booking_id}, ttl={ttl}s")
            return True, lock_data
        else:
            # Check if we already hold the lock
            existing = await client.get(lock_key)
            if existing:
                try:
                    existing_data = json.loads(existing)
                    if existing_data.get("booking_id") == booking_id:
                        # We already hold this lock - extend it
                        await self.extend_lock(room_id, booking_id, ttl)
                        return True, existing
                except json.JSONDecodeError:
                    pass

            logger.warning(f"Lock denied: room={room_id}, booking={booking_id}, existing={existing}")
            return False, None

    async def release_room_lock(
        self,
        room_id: int,
        booking_id: int
    ) -> bool:
        """
        Release a lock on a room.

        Only releases if the lock is held by the specified booking_id.
        Uses Lua script for atomic check-and-delete.

        Args:
            room_id: The room to unlock
            booking_id: The booking that should hold the lock

        Returns:
            True if lock was released, False otherwise
        """
        client = await self.get_client()
        lock_key = self._get_lock_key(room_id)

        # Lua script for atomic check-and-delete
        lua_script = """
        local current = redis.call('GET', KEYS[1])
        if current then
            local data = cjson.decode(current)
            if data.booking_id == tonumber(ARGV[1]) then
                return redis.call('DEL', KEYS[1])
            end
        end
        return 0
        """

        try:
            result = await client.eval(lua_script, 1, lock_key, str(booking_id))

            if result:
                logger.info(f"Lock released: room={room_id}, booking={booking_id}")
                return True
            else:
                logger.warning(f"Lock release failed: room={room_id}, booking={booking_id}")
                return False
        except Exception as e:
            # Fallback to simple delete if Lua fails (e.g., no cjson)
            logger.warning(f"Lua script failed, using fallback: {e}")
            existing = await client.get(lock_key)
            if existing:
                try:
                    existing_data = json.loads(existing)
                    if existing_data.get("booking_id") == booking_id:
                        await client.delete(lock_key)
                        logger.info(f"Lock released (fallback): room={room_id}, booking={booking_id}")
                        return True
                except json.JSONDecodeError:
                    pass
            return False

    async def extend_lock(
        self,
        room_id: int,
        booking_id: int,
        ttl: int = None
    ) -> bool:
        """
        Extend an existing lock's TTL.

        Only extends if the lock is held by the specified booking_id.

        Args:
            room_id: The room with the lock
            booking_id: The booking that should hold the lock
            ttl: New TTL in seconds

        Returns:
            True if lock was extended, False otherwise
        """
        if ttl is None:
            ttl = self.EXTEND_TTL

        client = await self.get_client()
        lock_key = self._get_lock_key(room_id)

        # Get current lock data
        existing = await client.get(lock_key)
        if not existing:
            return False

        try:
            existing_data = json.loads(existing)
            if existing_data.get("booking_id") != booking_id:
                return False

            # Update lock data with new TTL
            existing_data["ttl"] = ttl
            existing_data["extended_at"] = datetime.utcnow().isoformat()

            # Set with new TTL
            await client.set(lock_key, json.dumps(existing_data), ex=ttl)
            logger.info(f"Lock extended: room={room_id}, booking={booking_id}, new_ttl={ttl}s")
            return True

        except json.JSONDecodeError:
            return False

    async def is_room_locked(self, room_id: int) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if a room is currently locked.

        Args:
            room_id: The room to check

        Returns:
            Tuple of (is_locked: bool, lock_data: Optional[dict])
        """
        client = await self.get_client()
        lock_key = self._get_lock_key(room_id)

        data = await client.get(lock_key)
        if data:
            try:
                lock_info = json.loads(data)
                return True, lock_info
            except json.JSONDecodeError:
                return True, None
        return False, None

    async def get_lock_holder(self, room_id: int) -> Optional[int]:
        """
        Get the booking_id that holds a lock on a room.

        Args:
            room_id: The room to check

        Returns:
            booking_id if locked, None otherwise
        """
        is_locked, lock_data = await self.is_room_locked(room_id)
        if is_locked and lock_data:
            return lock_data.get("booking_id")
        return None

    async def get_all_active_locks(self) -> List[Tuple[int, Dict[str, Any]]]:
        """
        Get all currently active room locks.
        Used for monitoring and debugging.

        Returns:
            List of (room_id, lock_data) tuples
        """
        client = await self.get_client()
        pattern = f"{self.LOCK_PREFIX}*"

        locks = []
        async for key in client.scan_iter(match=pattern):
            room_id = int(key.replace(self.LOCK_PREFIX, ""))
            data = await client.get(key)
            if data:
                try:
                    lock_info = json.loads(data)
                    locks.append((room_id, lock_info))
                except json.JSONDecodeError:
                    locks.append((room_id, {"raw": data}))

        return locks

    async def cleanup_stale_locks(self) -> int:
        """
        Clean up any stale locks (should not exist with TTL, but safety check).

        Returns:
            Number of stale locks cleaned up
        """
        # With Redis TTL, locks auto-expire. This is for safety.
        # Could be used to force-release locks older than a threshold.
        client = await self.get_client()
        pattern = f"{self.LOCK_PREFIX}*"

        cleaned = 0
        async for key in client.scan_iter(match=pattern):
            ttl = await client.ttl(key)
            if ttl == -1:  # No expiry set (shouldn't happen)
                await client.delete(key)
                cleaned += 1
                logger.warning(f"Cleaned stale lock without TTL: {key}")

        return cleaned

    async def force_release_lock(self, room_id: int) -> bool:
        """
        Force release a lock regardless of who holds it.
        Use with caution - for admin/emergency use only.

        Args:
            room_id: The room to unlock

        Returns:
            True if lock was released
        """
        client = await self.get_client()
        lock_key = self._get_lock_key(room_id)
        result = await client.delete(lock_key)
        if result:
            logger.warning(f"Lock force-released: room={room_id}")
        return bool(result)


# Global instance
_lock_manager: Optional[RedisLockManager] = None


def get_lock_manager() -> RedisLockManager:
    """Get the global lock manager instance."""
    if _lock_manager is None:
        raise RuntimeError("Lock manager not initialized. Call init_lock_manager() first.")
    return _lock_manager


async def init_lock_manager(redis_url: str) -> RedisLockManager:
    """Initialize the global lock manager."""
    global _lock_manager
    _lock_manager = RedisLockManager(redis_url)
    # Test connection
    await _lock_manager.get_client()
    logger.info(f"Redis Lock Manager initialized: {redis_url}")
    return _lock_manager


async def close_lock_manager():
    """Close the global lock manager."""
    global _lock_manager
    if _lock_manager:
        await _lock_manager.close()
        _lock_manager = None
        logger.info("Redis Lock Manager closed")
