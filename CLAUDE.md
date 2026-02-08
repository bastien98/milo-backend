# Milo Backend (Scandalicious)

## Project Overview
FastAPI backend for a receipt scanning and expense tracking app. Python 3.11, PostgreSQL, deployed on Railway.

## Tech Stack
- **Framework**: FastAPI 0.109.0 with async support
- **Database**: PostgreSQL 17 via SQLAlchemy 2.0 (asyncpg driver)
- **Migrations**: Alembic
- **Auth**: Firebase Admin SDK
- **AI**: Google Gemini (categorization, chat, budget insights)
- **OCR**: Veryfi API
- **Deployment**: Railway (production + non-prod environments)

## Infrastructure Access

### Railway Logs
```bash
# Production logs
RAILWAY_TOKEN=a5fd4542-cbf4-405d-9df2-9a1abf680ad3 railway logs --service scandalicious-api

# Non-prod logs
RAILWAY_TOKEN=2f4b2fe6-4d49-4588-a77f-e679f78861ca railway logs --service scandalicious-api
```

### Railway Variables / Status
```bash
# Production
RAILWAY_TOKEN=a5fd4542-cbf4-405d-9df2-9a1abf680ad3 railway variables --service scandalicious-api
RAILWAY_TOKEN=a5fd4542-cbf4-405d-9df2-9a1abf680ad3 railway status

# Non-prod
RAILWAY_TOKEN=2f4b2fe6-4d49-4588-a77f-e679f78861ca railway variables --service scandalicious-api
RAILWAY_TOKEN=2f4b2fe6-4d49-4588-a77f-e679f78861ca railway status
```

### Database Queries (via psql)
```bash
# Production DB
/opt/homebrew/opt/libpq/bin/psql "postgresql://postgres:hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx@switchback.proxy.rlwy.net:45896/railway"

# Non-prod DB
/opt/homebrew/opt/libpq/bin/psql "postgresql://postgres:tBKODGAPzROEyTeTYDKVjtbdhBhEwkgc@shortline.proxy.rlwy.net:33385/railway"
```

Use `-c "SQL"` flag for one-off queries.

## Key Directories
- `app/api/v2/` - Current API endpoints
- `app/api/v1/` - Legacy API endpoints
- `app/services/` - Business logic services
- `app/models/` - SQLAlchemy models
- `app/db/repositories/` - Data access layer
- `app/core/` - Auth, exceptions, middleware
- `migrations/versions/` - Alembic migrations

## Railway Environments
- **Production**: `scandalicious-api-production.up.railway.app`
- **Non-prod**: `scandalicious-api-non-prod.up.railway.app`

## Common Commands
```bash
# Run locally
uvicorn app.main:app --reload --port 8000

# Run migrations
alembic upgrade head

# Deploy (via Makefile)
make deploy              # non-prod
make deploy ENV=production  # production
```
