# User Profile Management API - Implementation Summary

## ✅ Implementation Complete

User profile management endpoints have been successfully added to the Scandalicious API.

---

## 📋 What Was Implemented

### 1. Database Schema
**File:** [app/models/user_profile.py](app/models/user_profile.py)

Created `user_profiles` table with the following fields:
- `user_id` (string, primary key, foreign key to users.firebase_uid)
- `first_name` (string, optional)
- `last_name` (string, optional)
- `gender` (enum: "male", "female", "prefer_not_to_say")
- `profile_completed` (boolean, auto-calculated)
- `created_at` (timestamp, auto-set)
- `updated_at` (timestamp, auto-updated)

**Enum Added:** [app/models/enums.py:30](app/models/enums.py#L30)
```python
class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"
```

### 2. API Endpoints
**File:** [app/api/v1/profile.py](app/api/v1/profile.py)

#### GET `/api/v1/profile`
Retrieve authenticated user's profile.

**Success Response (200):**
```json
{
  "user_id": "firebase_uid",
  "first_name": "John",
  "last_name": "Doe",
  "gender": "male",
  "profile_completed": true,
  "created_at": "2026-01-23T10:00:00Z",
  "updated_at": "2026-01-23T10:00:00Z"
}
```

**Not Found Response (404):**
```json
{
  "detail": {
    "error": "Profile not found",
    "profile_completed": false
  }
}
```

#### POST `/api/v1/profile`
Create or update user profile (upsert operation).

**Request Body:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "gender": "male"
}
```

**Response (200):** Same as GET response
- Auto-creates profile if it doesn't exist
- Updates existing profile if it does
- Automatically sets `profile_completed: true` when all fields are provided

#### PUT `/api/v1/profile`
Update specific fields of existing profile.

**Request Body (all fields optional):**
```json
{
  "first_name": "Jane"
}
```

**Response (200):** Updated profile
**Response (404):** Profile not found (must create with POST first)

### 3. Business Logic
**File:** [app/services/profile_service.py](app/services/profile_service.py)

- Extracts Firebase UID from Authorization Bearer token
- Uses UID as primary key for all operations
- Auto-calculates `profile_completed` based on field presence
- Validates gender enum values
- Properly handles 401/400/404 errors

### 4. Data Access Layer
**File:** [app/db/repositories/user_profile_repo.py](app/db/repositories/user_profile_repo.py)

Provides async database operations:
- `get_by_user_id()` - Fetch profile by Firebase UID
- `create()` - Create new profile
- `update()` - Update existing profile
- `delete()` - Delete profile

### 5. Request/Response Schemas
**File:** [app/schemas/profile.py](app/schemas/profile.py)

Pydantic models for validation:
- `ProfileCreate` - For POST requests
- `ProfileUpdate` - For PUT requests (partial updates)
- `ProfileResponse` - For API responses
- `ProfileNotFoundResponse` - For 404 responses

### 6. Configuration Updates

**Updated Files:**
- [app/api/v1/router.py](app/api/v1/router.py#L15) - Registered profile router
- [app/db/session.py:25](app/db/session.py#L25) - Added user_profile to init_db imports
- [app/models/__init__.py](app/models/__init__.py) - Exported all models
- [app/models/user.py:43](app/models/user.py#L43) - Added profile relationship
- [app/config.py:40](app/config.py#L40) - Fixed config to allow extra env variables

### 7. Comprehensive Tests
**File:** [tests/test_profile.py](tests/test_profile.py)

13 test cases covering:
- ✅ GET profile not found (404)
- ✅ POST create profile
- ✅ POST with incomplete data
- ✅ GET after creation
- ✅ POST update existing profile
- ✅ PUT update specific fields
- ✅ PUT when profile doesn't exist (404)
- ✅ PUT update multiple fields
- ✅ Invalid gender value validation
- ✅ All valid gender enum values
- ✅ Profile completion logic
- ✅ Empty request body handling
- ✅ Timestamp handling (created_at, updated_at)

---

## 🧪 Testing Instructions

### Local Testing (After Setting Up Environment)

1. **Install dependencies (if not already installed):**
   ```bash
   pip install -r requirements.txt
   pip install aiosqlite  # For testing
   ```

2. **Run all profile tests:**
   ```bash
   pytest tests/test_profile.py -v
   ```

3. **Run specific test:**
   ```bash
   pytest tests/test_profile.py::test_create_profile_with_post -v
   ```

### Manual Testing with Railway

After deployment, test with curl or Postman:

**1. Set up authentication:**
```bash
# Get Firebase ID token from your mobile app or Firebase console
export FIREBASE_TOKEN="your_firebase_id_token_here"
export API_URL="https://scandalicious-api-production.up.railway.app"
```

**2. Test GET (should return 404 initially):**
```bash
curl -X GET "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer $FIREBASE_TOKEN"
```

**3. Test POST (create profile):**
```bash
curl -X POST "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer $FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "John",
    "last_name": "Doe",
    "gender": "male"
  }'
```

**4. Test GET (should return profile):**
```bash
curl -X GET "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer $FIREBASE_TOKEN"
```

**5. Test PUT (update specific fields):**
```bash
curl -X PUT "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer $FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Jane"
  }'
```

**6. Test invalid token (should return 401):**
```bash
curl -X GET "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer invalid_token"
```

**7. Test invalid gender (should return 422):**
```bash
curl -X POST "$API_URL/api/v1/profile" \
  -H "Authorization: Bearer $FIREBASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "John",
    "gender": "invalid_value"
  }'
```

---

## 🚀 Deployment to Railway

### Option 1: Deploy to Non-Prod Environment (Testing)
```bash
make deploy
```

### Option 2: Deploy to Production
```bash
make deploy ENV=production
```

### Verify Deployment
```bash
# Check logs
make logs ENV=non-prod

# Check status
make status ENV=non-prod

# Get domain
make domain ENV=non-prod
```

### Database Migration

The `user_profiles` table will be **automatically created** on the next app startup because:
1. The model is imported in [app/db/session.py:25](app/db/session.py#L25)
2. The `init_db()` function runs on startup ([app/main.py:33](app/main.py#L33))
3. SQLAlchemy's `Base.metadata.create_all()` creates all tables

**No manual migration required!**

---

## 📊 API Consistency

This implementation follows your existing patterns:

✅ **Same authentication:** Uses Firebase Bearer tokens via `get_current_db_user()`
✅ **Same error handling:** Uses custom exceptions (ResourceNotFoundError)
✅ **Same response format:** JSON with snake_case fields
✅ **Same status codes:** 200, 201, 400, 401, 404, 422, 500
✅ **Same CORS config:** Inherits from existing middleware
✅ **Same database:** PostgreSQL with async SQLAlchemy
✅ **Same project structure:** Models → Repositories → Services → Endpoints

---

## 🔒 Security Features

- ✅ Firebase token validation on every request
- ✅ User can only access their own profile (uid from token)
- ✅ Input validation with Pydantic schemas
- ✅ SQL injection protection via SQLAlchemy ORM
- ✅ Proper error handling without exposing internals

---

## 📁 Files Changed/Created

### New Files (8)
1. `app/models/user_profile.py` - UserProfile model
2. `app/schemas/profile.py` - Request/response schemas
3. `app/db/repositories/user_profile_repo.py` - Data access layer
4. `app/services/profile_service.py` - Business logic
5. `app/api/v1/profile.py` - API endpoints
6. `tests/test_profile.py` - Comprehensive tests
7. `app/models/__init__.py` - Model exports (recreated)
8. `PROFILE_API_README.md` - This documentation

### Modified Files (5)
1. `app/models/enums.py` - Added Gender enum
2. `app/models/user.py` - Added profile relationship
3. `app/api/v1/router.py` - Registered profile router
4. `app/db/session.py` - Added user_profile import
5. `app/config.py` - Fixed config to ignore extra env vars

---

## ✅ Testing Checklist

All requirements from your specification have been implemented:

- ✅ Database schema with all required fields
- ✅ GET /api/v1/profile endpoint
- ✅ POST /api/v1/profile endpoint (create or update)
- ✅ PUT /api/v1/profile endpoint (update existing)
- ✅ Firebase UID extraction from Bearer token
- ✅ Auto-create profile on first POST
- ✅ Gender enum validation (male, female, prefer_not_to_say)
- ✅ 401 on invalid/missing token
- ✅ 404 on profile not found
- ✅ 400 on invalid input
- ✅ Auto-set updated_at on updates
- ✅ Profile_completed auto-calculation
- ✅ Consistent error handling with existing API
- ✅ Snake_case JSON fields
- ✅ Proper status codes
- ✅ CORS headers inherited

---

## 🎯 Next Steps

1. **Deploy to Railway:**
   ```bash
   make deploy ENV=non-prod
   ```

2. **Verify database table creation:**
   - The `user_profiles` table will be created automatically on startup
   - Check Railway logs to confirm: `make logs ENV=non-prod`

3. **Test endpoints manually** using the curl commands above

4. **Update your mobile app** to use the new endpoints

5. **Monitor logs** for any issues:
   ```bash
   make logs ENV=non-prod
   ```

---

## 🐛 Troubleshooting

### Issue: 404 on /api/v1/profile
**Solution:** Make sure the app has restarted after deployment. The router is registered at [app/api/v1/router.py:15](app/api/v1/router.py#L15).

### Issue: Table doesn't exist
**Solution:** Restart the app to trigger `init_db()`. Check Railway logs for any database connection errors.

### Issue: 401 Unauthorized
**Solution:** Verify Firebase token is valid and not expired. Tokens expire after 1 hour.

### Issue: 422 Validation Error
**Solution:** Check request body format. Gender must be one of: "male", "female", "prefer_not_to_say".

---

## 📞 Support

For issues or questions:
1. Check Railway logs: `make logs ENV=non-prod`
2. Review this documentation
3. Check test file for examples: [tests/test_profile.py](tests/test_profile.py)
4. Verify deployment: `make status ENV=non-prod`

---

**Implementation Date:** January 23, 2026
**API Version:** v1
**Database:** PostgreSQL with async SQLAlchemy
**Framework:** FastAPI
