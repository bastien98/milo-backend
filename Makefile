# Makefile for Railway deployment
# Uses token-based auth — no `railway login` or `railway link` needed.

# Default environment (can be overridden: make deploy ENV=production)
ENV ?= non-prod

# Railway service name
SERVICE = scandalicious-api

# Railway tokens and environment names per environment
ifeq ($(ENV),production)
  RAILWAY_ENV = production
  RAILWAY_TOKEN = a5fd4542-cbf4-405d-9df2-9a1abf680ad3
else
  RAILWAY_ENV = non-prod
  RAILWAY_TOKEN = 2f4b2fe6-4d49-4588-a77f-e679f78861ca
endif

export RAILWAY_TOKEN

# Database URLs per environment (asyncpg driver)
ifeq ($(ENV),production)
  DATABASE_URL = postgresql+asyncpg://postgres:hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx@switchback.proxy.rlwy.net:45896/railway
else
  DATABASE_URL = postgresql+asyncpg://postgres:tBKODGAPzROEyTeTYDKVjtbdhBhEwkgc@shortline.proxy.rlwy.net:33385/railway
endif

# Python interpreter (use backend venv)
PYTHON = .venv/bin/python3

.PHONY: help
help:
	@echo "Railway Deployment Commands:"
	@echo "  make deploy [ENV=production|non-prod]     - Deploy to specified environment (default: non-prod)"
	@echo "  make logs [ENV=production|non-prod]       - View logs for specified environment"
	@echo "  make status [ENV=production|non-prod]     - Show project status"
	@echo "  make variables [ENV=production|non-prod]  - List variables for specified environment"
	@echo "  make domain [ENV=production|non-prod]     - Get domain for specified environment"
	@echo ""
	@echo "Script Commands:"
	@echo "  make rebuild-profiles [ENV=production|non-prod]    - Rebuild enriched user profiles"
	@echo "  make generate-promos [ENV=production|non-prod]     - Generate promo candidates"
	@echo "  make cleanup-promos-dry [ENV=...]                  - Preview promo R2+DB wipe counts"
	@echo "  make cleanup-promos [ENV=...]                      - Wipe promo R2 objects + promo_items rows (destructive)"
	@echo ""
	@echo "Deploy examples:"
	@echo "  make deploy                # Deploy to non-prod"
	@echo "  make deploy ENV=production # Deploy to production"
	@echo "  make logs ENV=production   # View production logs"

.PHONY: deploy
deploy:
	@echo "Deploying to $(RAILWAY_ENV)..."
	@railway up --service $(SERVICE) --environment $(RAILWAY_ENV)

.PHONY: logs
logs:
	@echo "Fetching logs from $(RAILWAY_ENV) environment..."
	@railway logs --service $(SERVICE) --environment $(RAILWAY_ENV)

.PHONY: status
status:
	@echo "Checking project status..."
	@railway status

.PHONY: domain
domain:
	@echo "Getting domain for $(RAILWAY_ENV) environment..."
	@railway domain --service $(SERVICE)

.PHONY: variables
variables:
	@echo "Listing variables for $(RAILWAY_ENV) environment..."
	@railway variable --service $(SERVICE) --environment $(RAILWAY_ENV)

# --- Scripts ---

.PHONY: rebuild-profiles
rebuild-profiles:
	@echo "Rebuilding enriched profiles on $(RAILWAY_ENV)..."
	DATABASE_URL=$(DATABASE_URL) $(PYTHON) -m scripts.rebuild_profiles

.PHONY: cleanup-promos-dry
cleanup-promos-dry:
	@echo "[DRY RUN] Counting promo data on $(RAILWAY_ENV)..."
	set -a; . ./.env; set +a; DATABASE_URL=$(DATABASE_URL) $(PYTHON) -m scripts.cleanup_promos --dry-run

.PHONY: cleanup-promos
cleanup-promos:
	@echo "[DELETE] Wiping promo data on $(RAILWAY_ENV)..."
	set -a; . ./.env; set +a; DATABASE_URL=$(DATABASE_URL) $(PYTHON) -m scripts.cleanup_promos --yes
