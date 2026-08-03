"""
Pytest configuration and fixtures for Glimmora Backend tests.
Provides database sessions, test client, and mock services.
"""
import pytest
import asyncio
from typing import AsyncGenerator, Generator
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import json

from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel, create_engine, Session
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.session import get_session


# Test database URL - using SQLite in-memory for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create a test async engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
async def async_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test async session."""
    async_session_maker = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


@pytest.fixture(scope="function")
async def client(async_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test client with overridden database session."""

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield async_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ==================== SAMPLE DATA FIXTURES ====================

@pytest.fixture
def sample_room_type_data() -> dict:
    """Sample room type data for tests."""
    return {
        "id": 1,
        "name": "Deluxe Suite",
        "code": "DLX",
        "base_price": Decimal("7500.00"),
        "max_occupancy": 3,
        "description": "Luxury room with city view",
        "amenities": ["WiFi", "AC", "TV", "Minibar"],
        "status": "active"
    }


@pytest.fixture
def sample_room_data() -> dict:
    """Sample room data for tests."""
    return {
        "id": 1,
        "room_number": "101",
        "room_type_id": 1,
        "floor": 1,
        "status": "available",
        "is_clean": True,
    }


@pytest.fixture
def sample_reservation_data() -> dict:
    """Sample reservation data for tests."""
    today = date.today()
    return {
        "id": 1,
        "guest_id": 1,
        "room_id": 1,
        "room_type_id": 1,
        "arrival_date": today + timedelta(days=3),
        "departure_date": today + timedelta(days=5),
        "status": "confirmed",
        "total_amount": Decimal("15000.00"),
        "source": "direct",
        "adults": 2,
        "children": 0,
    }


@pytest.fixture
def sample_booking_data() -> dict:
    """Sample booking data for tests."""
    today = date.today()
    return {
        "id": 1,
        "guest_id": 1,
        "room_id": 1,
        "room_type_id": 1,
        "arrival_date": today + timedelta(days=3),
        "departure_date": today + timedelta(days=5),
        "status": "confirmed",
        "total_price": Decimal("15000.00"),
        "net_revenue": Decimal("13500.00"),
        "source": "direct",
        "adults": 2,
        "children": 0,
    }


@pytest.fixture
def sample_competitor_data() -> dict:
    """Sample competitor data for tests."""
    return {
        "id": 1,
        "name": "Grand Hyatt Hotel",
        "address": "123 Main Street",
        "star_rating": 4.5,
        "room_count": 150,
        "distance_km": 2.5,
        "is_active": True,
    }


@pytest.fixture
def sample_pricing_rule_data() -> dict:
    """Sample pricing rule data for tests."""
    return {
        "rule_name": "Weekend High Demand",
        "description": "Increase rates on weekends during high occupancy",
        "priority": 2,
        "conditions": [
            {"type": "day_of_week", "operator": "in", "value": [5, 6]},
            {"type": "occupancy", "operator": "gte", "value": 80}
        ],
        "actions": [
            {"type": "adjust_percent", "value": 15}
        ],
        "is_active": True,
    }


@pytest.fixture
def sample_event_data() -> dict:
    """Sample event data for tests."""
    today = date.today()
    return {
        "event_name": "Tech Conference 2025",
        "event_type": "conference",
        "start_date": today + timedelta(days=30),
        "end_date": today + timedelta(days=32),
        "impact_multiplier": 1.5,
        "is_recurring": False,
        "notes": "Annual tech conference expected to bring 5000 attendees",
    }


@pytest.fixture
def sample_kpi_response() -> dict:
    """Sample KPI response for tests."""
    today = date.today()
    return {
        "total_revenue": 125000.00,
        "revenue_trend": 12.5,
        "occupancy": 78.5,
        "occupancy_trend": 5.2,
        "adr": 6500.00,
        "adr_trend": 3.1,
        "revpar": 5102.50,
        "revpar_trend": 8.3,
        "total_bookings": 45,
        "available_room_nights": 700,
        "occupied_room_nights": 550,
        "period": {
            "start": today.isoformat(),
            "end": today.isoformat(),
            "days": 1
        }
    }


@pytest.fixture
def sample_forecast_data() -> list:
    """Sample forecast data for tests."""
    today = date.today()
    return [
        {
            "date": (today + timedelta(days=i)).isoformat(),
            "forecasted_demand": 65 + (i % 10) * 3,
            "forecasted_occupancy": 70 + (i % 10) * 2.5,
            "confidence_level": 85 + (i % 5),
            "day_of_week": (today + timedelta(days=i)).strftime("%A"),
            "is_weekend": (today + timedelta(days=i)).weekday() >= 5,
            "demand_level": "moderate" if i % 3 == 0 else "high" if i % 3 == 1 else "low"
        }
        for i in range(14)
    ]


@pytest.fixture
def sample_recommendation_data() -> list:
    """Sample pricing recommendation data for tests."""
    today = date.today()
    return [
        {
            "date": (today + timedelta(days=i)).isoformat(),
            "room_type_id": 1,
            "room_type_name": "Deluxe Suite",
            "current_rate": 7500.00,
            "recommended_rate": 7500.00 * (1.1 + i * 0.02),
            "change_percent": 10 + i * 2,
            "demand_level": "high",
            "forecasted_occupancy": 85 + i,
            "competitor_avg": 7200.00,
            "confidence": 88.5,
            "reasoning": "High demand expected; competitor rates increasing",
            "priority": "high" if i < 3 else "medium"
        }
        for i in range(5)
    ]


# ==================== MOCK FIXTURES ====================

@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for AI service tests."""
    with patch('openai.AsyncOpenAI') as mock:
        mock_instance = AsyncMock()
        mock.return_value = mock_instance

        # Mock chat completion
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="AI generated insight response"))
        ]
        mock_instance.chat.completions.create = AsyncMock(return_value=mock_response)

        yield mock_instance


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for caching tests."""
    with patch('redis.asyncio.Redis') as mock:
        mock_instance = AsyncMock()
        mock.return_value = mock_instance

        mock_instance.get = AsyncMock(return_value=None)
        mock_instance.set = AsyncMock(return_value=True)
        mock_instance.delete = AsyncMock(return_value=1)
        mock_instance.exists = AsyncMock(return_value=0)

        yield mock_instance


# ==================== UTILITY FIXTURES ====================

@pytest.fixture
def auth_headers() -> dict:
    """Sample authentication headers for protected endpoint tests."""
    # In real tests, you would generate a valid JWT token
    return {
        "Authorization": "Bearer test_token_12345",
        "Content-Type": "application/json"
    }


@pytest.fixture
def date_range() -> tuple:
    """Return a standard date range for testing."""
    today = date.today()
    return (today, today + timedelta(days=30))


# ==================== ASYNC UTILITIES ====================

@pytest.fixture
def run_async():
    """Helper to run async functions in sync tests."""
    def _run_async(coro):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)
    return _run_async
