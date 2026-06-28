"""Waitlist database model schema and Pydantic validation models."""

import logging
import re
from datetime import datetime

import aiosqlite
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Basic email validation regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Personal/generic email domains to block
BLOCKED_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "aol.com",
    "icloud.com",
    "mail.com",
    "zoho.com",
    "protonmail.com",
    "proton.me",
    "yandex.com",
    "gmx.com",
    "live.com",
}


class WaitlistRequest(BaseModel):
    """Pydantic model for validating incoming waitlist registration requests."""

    name: str = Field(..., min_length=1, description="Full Name of the registrant")
    business_email: str = Field(..., description="Business email of the registrant")
    company_size: str = Field(..., min_length=1, description="Size of the company")
    role: str = Field(..., min_length=1, description="Primary role of the registrant")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate that name is not just whitespace."""
        val = v.strip()
        if not val:
            raise ValueError("Name cannot be empty")
        return val

    @field_validator("business_email")
    @classmethod
    def validate_business_email(cls, v: str) -> str:
        """Validate business email format and block personal domains."""
        email = v.strip().lower()
        if not EMAIL_REGEX.match(email):
            raise ValueError("Invalid email format")

        parts = email.split("@")
        if len(parts) != 2:
            raise ValueError("Invalid email format")

        domain = parts[1]

        # Block known personal/generic domains
        for blocked in BLOCKED_DOMAINS:
            if domain == blocked or domain.endswith("." + blocked):
                raise ValueError(
                    "Personal email domains are not allowed. Please use a business email."
                )

        return email

    @field_validator("company_size")
    @classmethod
    def validate_company_size(cls, v: str) -> str:
        """Validate that company size is not empty."""
        val = v.strip()
        if not val:
            raise ValueError("Company size cannot be empty")
        return val

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Validate that role is not empty."""
        val = v.strip()
        if not val:
            raise ValueError("Role cannot be empty")
        return val


class WaitlistDatabase:
    """Manager for SQLite database persistence of waitlist entries."""

    def __init__(self, db_path: str = "waitlist.db"):
        self.db_path = db_path

    async def initialize(self) -> None:
        """Create waitlist table if it does not exist."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS waitlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    business_email TEXT NOT NULL UNIQUE,
                    company_size TEXT NOT NULL,
                    role TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            await db.commit()

    async def add_entry(self, name: str, business_email: str, company_size: str, role: str) -> dict:
        """Add an entry to the waitlist database.

        Raises:
            aiosqlite.IntegrityError: If business_email already exists in the waitlist.
        """
        timestamp = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO waitlist (name, business_email, company_size, role, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    name.strip(),
                    business_email.strip().lower(),
                    company_size.strip(),
                    role.strip(),
                    timestamp,
                ),
            )
            await db.commit()
            last_id = cursor.lastrowid
            return {
                "id": last_id,
                "name": name.strip(),
                "business_email": business_email.strip().lower(),
                "company_size": company_size.strip(),
                "role": role.strip(),
                "timestamp": timestamp,
            }

    async def get_entry_by_email(self, email: str) -> dict | None:
        """Retrieve a waitlist entry by its email address."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM waitlist WHERE business_email = ?", (email.strip().lower(),)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                return None
