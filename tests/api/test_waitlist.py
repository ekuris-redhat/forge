"""Unit and integration tests for the waitlist form API endpoint."""

import os
import tempfile
from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from forge.api.routes.waitlist import get_waitlist_db
from forge.main import app
from forge.models.waitlist import WaitlistDatabase


@pytest.fixture
def temp_db_path() -> Generator[str, None, None]:
    """Create a temporary directory and return a path for a test database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "test_waitlist.db")
        yield db_file


@pytest_asyncio.fixture
async def test_db(temp_db_path: str) -> AsyncGenerator[WaitlistDatabase, None]:
    """Create and initialize an isolated test database."""
    db = WaitlistDatabase(temp_db_path)
    await db.initialize()
    yield db


@pytest_asyncio.fixture
async def client_with_override(
    test_db: WaitlistDatabase,
) -> AsyncGenerator[AsyncClient, None]:
    """Create an async client with the waitlist database dependency overridden."""

    async def override_get_waitlist_db() -> WaitlistDatabase:
        return test_db

    app.dependency_overrides[get_waitlist_db] = override_get_waitlist_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_waitlist_db, None)


@pytest.mark.asyncio
class TestWaitlistAPI:
    """Test suite for the /api/v1/waitlist registration endpoint."""

    async def test_successful_registration(
        self, client_with_override: AsyncClient, test_db: WaitlistDatabase
    ) -> None:
        """Verify successful registration on the waitlist with persistent storage."""
        payload = {
            "name": "Alex Johnson",
            "business_email": "alex@acme.co",
            "company_size": "51-200",
            "role": "Engineering Manager",
        }

        response = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["id"] is not None
        assert data["name"] == "Alex Johnson"
        assert data["business_email"] == "alex@acme.co"
        assert data["company_size"] == "51-200"
        assert data["role"] == "Engineering Manager"
        assert "timestamp" in data

        # Verify persistence in the test database
        persisted = await test_db.get_entry_by_email("alex@acme.co")
        assert persisted is not None
        assert persisted["name"] == "Alex Johnson"
        assert persisted["company_size"] == "51-200"
        assert persisted["role"] == "Engineering Manager"

    async def test_invalid_email_format(self, client_with_override: AsyncClient) -> None:
        """Verify that poorly formatted email addresses are rejected."""
        payload = {
            "name": "Alex Johnson",
            "business_email": "not-an-email",
            "company_size": "51-200",
            "role": "Engineering Manager",
        }

        response = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "personal_email",
        [
            "alex@gmail.com",
            "john.doe@yahoo.com",
            "test@hotmail.com",
            "user@outlook.com",
            "dev@proton.me",
            "lead@icloud.com",
        ],
    )
    async def test_personal_email_domain_rejected(
        self, client_with_override: AsyncClient, personal_email: str
    ) -> None:
        """Verify that registration with personal/generic email domains is rejected."""
        payload = {
            "name": "Alex Johnson",
            "business_email": personal_email,
            "company_size": "51-200",
            "role": "Engineering Manager",
        }

        response = await client_with_override.post("/api/v1/waitlist", json=payload)
        # Should be rejected with 422 Unprocessable Entity due to validation error
        assert response.status_code == 422
        assert "Personal email domains are not allowed" in response.text

    async def test_duplicate_registration_rejected(
        self, client_with_override: AsyncClient, test_db: WaitlistDatabase
    ) -> None:
        """Verify duplicate registrations for the same email return 409 Conflict."""
        payload = {
            "name": "Alex Johnson",
            "business_email": "duplicate@acme.co",
            "company_size": "51-200",
            "role": "Engineering Manager",
        }

        # First registration (Success)
        response1 = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response1.status_code == 201

        # Verify it was persisted
        persisted = await test_db.get_entry_by_email("duplicate@acme.co")
        assert persisted is not None

        # Second registration with same email (Conflict)
        response2 = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response2.status_code == 409
        assert "already registered" in response2.json()["detail"]

    @pytest.mark.parametrize(
        "missing_field",
        ["name", "business_email", "company_size", "role"],
    )
    async def test_missing_required_fields(
        self, client_with_override: AsyncClient, missing_field: str
    ) -> None:
        """Verify validation errors when required fields are missing."""
        payload = {
            "name": "Alex Johnson",
            "business_email": "alex@acme.co",
            "company_size": "51-200",
            "role": "Engineering Manager",
        }
        payload.pop(missing_field)

        response = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "field_name,empty_value",
        [
            ("name", ""),
            ("name", "   "),
            ("company_size", ""),
            ("company_size", "   "),
            ("role", ""),
            ("role", "   "),
        ],
    )
    async def test_empty_string_fields(
        self, client_with_override: AsyncClient, field_name: str, empty_value: str
    ) -> None:
        """Verify validation errors when string fields are empty or whitespace."""
        payload = {
            "name": "Alex Johnson",
            "business_email": "alex@acme.co",
            "company_size": "51-200",
            "role": "Engineering Manager",
        }
        payload[field_name] = empty_value

        response = await client_with_override.post("/api/v1/waitlist", json=payload)
        assert response.status_code == 422
