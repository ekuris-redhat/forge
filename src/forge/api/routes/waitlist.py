"""Waitlist API router and endpoints."""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from forge.config import Settings, get_settings
from forge.models.waitlist import WaitlistDatabase, WaitlistRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["waitlist"])


class WaitlistResponse(BaseModel):
    """Pydantic model for waitlist registration response."""

    id: int
    name: str
    business_email: str
    company_size: str
    role: str
    timestamp: str


async def get_waitlist_db(settings: Settings = Depends(get_settings)) -> WaitlistDatabase:
    """Dependency for obtaining a WaitlistDatabase instance."""
    db = WaitlistDatabase(settings.waitlist_db_path)
    await db.initialize()
    return db


@router.post(
    "/waitlist",
    response_model=WaitlistResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Successfully registered for the waitlist"},
        400: {"description": "Bad Request - Invalid payload or email domain"},
        422: {"description": "Unprocessable Entity - Input validation failed"},
        409: {"description": "Conflict - Email already registered"},
    },
)
async def register_waitlist(
    payload: WaitlistRequest,
    db: WaitlistDatabase = Depends(get_waitlist_db),
) -> WaitlistResponse:
    """Register a new user to the early access waitlist.

    Validates format, checks for business email domains, and enforces
    uniqueness of business email address.
    """
    logger.info(f"Received waitlist registration request for {payload.business_email}")
    try:
        # Check if email is already in the database
        existing = await db.get_entry_by_email(payload.business_email)
        if existing:
            logger.warning(f"Registration conflict: {payload.business_email} already exists")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email address is already registered on the waitlist.",
            )

        # Attempt to insert new entry
        entry = await db.add_entry(
            name=payload.name,
            business_email=payload.business_email,
            company_size=payload.company_size,
            role=payload.role,
        )
        logger.info(
            f"Successfully registered {payload.business_email} to waitlist (ID: {entry['id']})"
        )
        return WaitlistResponse(**entry)

    except aiosqlite.IntegrityError as e:
        logger.warning(
            f"Database integrity error during registration for {payload.business_email}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email address is already registered on the waitlist.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during waitlist registration: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later.",
        )
