# Makefile for Railway deployment

# Default environment (can be overridden: make deploy ENV=production)
ENV ?= non-prod

# Railway service name
SERVICE = scandalicious-api

# Load Railway tokens from gitignored .env.railway file
# Expected vars: RAILWAY_TOKEN_PRODUCTION, RAILWAY_TOKEN_NONPROD
-include .env.railway

# Select token based on environment
ifeq ($(ENV),production)
  RAILWAY_TOKEN := $(RAILWAY_TOKEN_PRODUCTION)
else
  RAILWAY_TOKEN := $(RAILWAY_TOKEN_NONPROD)
endif

.PHONY: help
help:
	@echo "Railway Deployment Commands:"
	@echo "  make deploy [ENV=production|non-prod]  - Deploy to specified environment (default: non-prod)"
	@echo "  make logs [ENV=production|non-prod]    - View logs for specified environment"
	@echo "  make status [ENV=production|non-prod]  - Show status for specified environment"
	@echo "  make variables [ENV=production|non-prod] - List variables for specified environment"
	@echo "  make domain [ENV=production|non-prod]  - Get domain for specified environment"
	@echo ""
	@echo "Examples:"
	@echo "  make deploy              # Deploy to non-prod"
	@echo "  make deploy ENV=production  # Deploy to production"
	@echo "  make logs ENV=production    # View production logs"

.PHONY: deploy
deploy:
ifeq ($(ENV),production)
	@echo "⚠️  WARNING: You are about to deploy to PRODUCTION!"
	@echo "This action should only be done manually by authorized personnel."
	@echo ""
	@read -p "Type 'yes' to confirm production deployment: " confirm; \
	if [ "$$confirm" != "yes" ]; then \
		echo "❌ Production deployment cancelled."; \
		exit 1; \
	fi
endif
	@echo "Deploying to $(ENV) environment..."
	@echo "Starting deployment..."
	@RAILWAY_TOKEN=$(RAILWAY_TOKEN) railway up --service $(SERVICE)

.PHONY: logs
logs:
	@echo "Fetching logs from $(ENV) environment..."
	@RAILWAY_TOKEN=$(RAILWAY_TOKEN) railway logs --service $(SERVICE)

.PHONY: status
status:
	@echo "Checking status for $(ENV) environment..."
	@RAILWAY_TOKEN=$(RAILWAY_TOKEN) railway status

.PHONY: domain
domain:
	@echo "Getting domain for $(ENV) environment..."
	@RAILWAY_TOKEN=$(RAILWAY_TOKEN) railway domain --service $(SERVICE)

.PHONY: variables
variables:
	@echo "Listing variables for $(ENV) environment..."
	@RAILWAY_TOKEN=$(RAILWAY_TOKEN) railway variables --service $(SERVICE)
