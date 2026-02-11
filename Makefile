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

.PHONY: help
help:
	@echo "Railway Deployment Commands:"
	@echo "  make deploy [ENV=production|non-prod]     - Deploy to specified environment (default: non-prod)"
	@echo "  make logs [ENV=production|non-prod]       - View logs for specified environment"
	@echo "  make status [ENV=production|non-prod]     - Show project status"
	@echo "  make variables [ENV=production|non-prod]  - List variables for specified environment"
	@echo "  make domain [ENV=production|non-prod]     - Get domain for specified environment"
	@echo ""
	@echo "Deploy examples:"
	@echo "  make deploy                # Deploy to non-prod"
	@echo "  make deploy ENV=production # Deploy to production"
	@echo "  make logs ENV=production   # View production logs"

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
