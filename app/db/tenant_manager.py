"""
Multi-tenant database manager for Glimmora Hotel Management System.

Manages database connections for multiple hotel tenants using the
"Single PostgreSQL Instance, Multiple Databases" architecture.

Each hotel has its own isolated database while sharing a single PostgreSQL server.
"""
from typing import Dict, Optional, AsyncGenerator, List
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel, select
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class TenantDatabaseManager:
    """Manages database connections for multiple hotel tenants"""

    def __init__(self):
        self._engines: Dict[str, AsyncEngine] = {}
        self._session_makers: Dict[str, async_sessionmaker] = {}
        self._hotel_db_map: Dict[str, str] = {}  # hotel_code -> db_name cache

        # Master database engine (lazy initialization)
        self._master_engine: Optional[AsyncEngine] = None
        self._master_session_maker: Optional[async_sessionmaker] = None

    @property
    def master_engine(self) -> AsyncEngine:
        """Get or create master database engine"""
        if self._master_engine is None:
            self._master_engine = create_async_engine(
                settings.master_database_url,
                pool_size=5,
                max_overflow=10,
                echo=False
            )
        return self._master_engine

    @property
    def master_session_maker(self) -> async_sessionmaker:
        """Get or create master session maker"""
        if self._master_session_maker is None:
            self._master_session_maker = async_sessionmaker(
                self.master_engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
        return self._master_session_maker

    async def get_hotel_db_name(self, hotel_code: str) -> str:
        """Get database name for hotel code (cached)"""
        if hotel_code in self._hotel_db_map:
            return self._hotel_db_map[hotel_code]

        # Query master database
        from app.db.master_models import Hotel
        async with self.master_session_maker() as session:
            result = await session.exec(
                select(Hotel).where(Hotel.code == hotel_code, Hotel.is_active == True)
            )
            hotel = result.first()
            if not hotel:
                raise ValueError(f"Hotel not found or inactive: {hotel_code}")

            self._hotel_db_map[hotel_code] = hotel.db_name
            return hotel.db_name

    async def get_engine(self, hotel_code: str) -> AsyncEngine:
        """Get or create engine for hotel"""
        if hotel_code not in self._engines:
            db_name = await self.get_hotel_db_name(hotel_code)
            db_url = settings.hotel_database_template.format(db_name=db_name)

            self._engines[hotel_code] = create_async_engine(
                db_url,
                pool_size=5,
                max_overflow=10,
                echo=False
            )
            self._session_makers[hotel_code] = async_sessionmaker(
                self._engines[hotel_code],
                class_=AsyncSession,
                expire_on_commit=False
            )
            logger.debug(f"Created database connection for hotel: {hotel_code}")

        return self._engines[hotel_code]

    async def get_session(self, hotel_code: str) -> AsyncGenerator[AsyncSession, None]:
        """Get session for hotel"""
        await self.get_engine(hotel_code)  # Ensure engine exists
        async with self._session_makers[hotel_code]() as session:
            yield session

    async def get_all_active_hotels(self) -> List:
        """Get all active hotels for background jobs"""
        from app.db.master_models import Hotel
        async with self.master_session_maker() as session:
            result = await session.exec(select(Hotel).where(Hotel.is_active == True))
            return result.all()

    def invalidate_hotel_cache(self, hotel_code: str) -> None:
        """Invalidate cache for a specific hotel (e.g., when hotel is deactivated)"""
        self._hotel_db_map.pop(hotel_code, None)

    def invalidate_all_cache(self) -> None:
        """Invalidate all hotel caches"""
        self._hotel_db_map.clear()

    async def close_hotel_connection(self, hotel_code: str) -> None:
        """Close connection for a specific hotel"""
        if hotel_code in self._engines:
            await self._engines[hotel_code].dispose()
            del self._engines[hotel_code]
            del self._session_makers[hotel_code]
            self._hotel_db_map.pop(hotel_code, None)
            logger.info(f"Closed database connection for hotel: {hotel_code}")

    async def close_all(self) -> None:
        """Close all engines on shutdown"""
        for hotel_code, engine in list(self._engines.items()):
            await engine.dispose()
            logger.debug(f"Closed connection for hotel: {hotel_code}")

        self._engines.clear()
        self._session_makers.clear()
        self._hotel_db_map.clear()

        if self._master_engine:
            await self._master_engine.dispose()
            self._master_engine = None
            self._master_session_maker = None

        logger.info("All tenant database connections closed")


# Global singleton instance
tenant_manager = TenantDatabaseManager()
