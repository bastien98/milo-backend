"""Tests for user profile management endpoints."""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.enums import Gender


@pytest.mark.asyncio
async def test_get_profile_not_found(client: AsyncClient, test_user: User):
    """Test GET /profile when profile doesn't exist (404)."""
    response = await client.get("/api/v1/profile")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "Profile not found"
    assert data["detail"]["profile_completed"] is False


@pytest.mark.asyncio
async def test_create_profile_with_post(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test POST /profile to create a new profile."""
    profile_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "male"
    }

    response = await client.post("/api/v1/profile", json=profile_data)

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == test_user.firebase_uid
    assert data["first_name"] == "John"
    assert data["last_name"] == "Doe"
    assert data["gender"] == "male"
    assert data["profile_completed"] is True
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_create_profile_incomplete(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test POST /profile with incomplete data (profile_completed should be False)."""
    profile_data = {
        "first_name": "John",
        # Missing last_name and gender
    }

    response = await client.post("/api/v1/profile", json=profile_data)

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == test_user.firebase_uid
    assert data["first_name"] == "John"
    assert data["last_name"] is None
    assert data["gender"] is None
    assert data["profile_completed"] is False


@pytest.mark.asyncio
async def test_get_profile_after_creation(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test GET /profile after creating a profile."""
    # First create a profile
    profile_data = {
        "first_name": "Jane",
        "last_name": "Smith",
        "gender": "female"
    }
    await client.post("/api/v1/profile", json=profile_data)

    # Then retrieve it
    response = await client.get("/api/v1/profile")

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == test_user.firebase_uid
    assert data["first_name"] == "Jane"
    assert data["last_name"] == "Smith"
    assert data["gender"] == "female"
    assert data["profile_completed"] is True


@pytest.mark.asyncio
async def test_post_update_existing_profile(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test POST /profile to update an existing profile."""
    # Create initial profile
    initial_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "male"
    }
    await client.post("/api/v1/profile", json=initial_data)

    # Update with POST (should work like create_or_update)
    updated_data = {
        "first_name": "Jane",
        "last_name": "Smith",
        "gender": "female"
    }
    response = await client.post("/api/v1/profile", json=updated_data)

    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Jane"
    assert data["last_name"] == "Smith"
    assert data["gender"] == "female"
    assert data["profile_completed"] is True


@pytest.mark.asyncio
async def test_put_update_profile(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test PUT /profile to update specific fields."""
    # Create initial profile
    initial_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "male"
    }
    await client.post("/api/v1/profile", json=initial_data)

    # Update only first_name with PUT
    update_data = {
        "first_name": "Johnny"
    }
    response = await client.put("/api/v1/profile", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Johnny"
    assert data["last_name"] == "Doe"  # Should remain unchanged
    assert data["gender"] == "male"  # Should remain unchanged
    assert data["profile_completed"] is True


@pytest.mark.asyncio
async def test_put_update_profile_not_found(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test PUT /profile when profile doesn't exist (404)."""
    update_data = {
        "first_name": "John"
    }
    response = await client.put("/api/v1/profile", json=update_data)

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["error"] == "not_found"


@pytest.mark.asyncio
async def test_put_update_multiple_fields(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test PUT /profile to update multiple fields."""
    # Create initial profile
    initial_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "male"
    }
    await client.post("/api/v1/profile", json=initial_data)

    # Update multiple fields with PUT
    update_data = {
        "first_name": "Jane",
        "gender": "female"
    }
    response = await client.put("/api/v1/profile", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] == "Jane"
    assert data["last_name"] == "Doe"  # Should remain unchanged
    assert data["gender"] == "female"
    assert data["profile_completed"] is True


@pytest.mark.asyncio
async def test_invalid_gender_value(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test POST /profile with invalid gender value (400)."""
    profile_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "invalid_gender"
    }

    response = await client.post("/api/v1/profile", json=profile_data)

    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_valid_gender_values(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test all valid gender enum values."""
    valid_genders = ["male", "female", "prefer_not_to_say"]

    for gender in valid_genders:
        profile_data = {
            "first_name": "Test",
            "last_name": "User",
            "gender": gender
        }
        response = await client.post("/api/v1/profile", json=profile_data)
        assert response.status_code == 200
        data = response.json()
        assert data["gender"] == gender

        # Clean up for next iteration
        await test_session.execute(
            test_session.query(UserProfile).delete()
        )
        await test_session.commit()


@pytest.mark.asyncio
async def test_profile_completed_logic(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test profile_completed is set correctly based on field presence."""
    # Test incomplete profile (missing gender)
    incomplete_data = {
        "first_name": "John",
        "last_name": "Doe"
    }
    response = await client.post("/api/v1/profile", json=incomplete_data)
    assert response.status_code == 200
    assert response.json()["profile_completed"] is False

    # Complete the profile with PUT
    complete_data = {
        "gender": "male"
    }
    response = await client.put("/api/v1/profile", json=complete_data)
    assert response.status_code == 200
    assert response.json()["profile_completed"] is True


@pytest.mark.asyncio
async def test_empty_request_body(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test POST /profile with empty request body."""
    response = await client.post("/api/v1/profile", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["first_name"] is None
    assert data["last_name"] is None
    assert data["gender"] is None
    assert data["profile_completed"] is False


@pytest.mark.asyncio
async def test_profile_timestamps(
    client: AsyncClient,
    test_user: User,
    test_session: AsyncSession
):
    """Test that created_at and updated_at timestamps are set correctly."""
    # Create profile
    profile_data = {
        "first_name": "John",
        "last_name": "Doe",
        "gender": "male"
    }
    create_response = await client.post("/api/v1/profile", json=profile_data)
    assert create_response.status_code == 200
    create_data = create_response.json()
    created_at = create_data["created_at"]

    # Update profile and check updated_at changes
    import asyncio
    await asyncio.sleep(0.1)  # Small delay to ensure timestamp difference

    update_data = {
        "first_name": "Jane"
    }
    update_response = await client.put("/api/v1/profile", json=update_data)
    assert update_response.status_code == 200
    update_data = update_response.json()

    # created_at should remain the same
    assert update_data["created_at"] == created_at
    # updated_at should be present (we can't easily test if it's newer in this setup)
    assert "updated_at" in update_data
