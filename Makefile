# Makefile for Railway deployment

# Default environment (can be overridden: make deploy ENV=production)
ENV ?= non-prod

# Railway service name
SERVICE = scandalicious-api

.PHONY: help
help:
	@echo "Railway Deployment Commands:"
	@echo "  make deploy [ENV=production|non-prod]  - Deploy to specified environment (default: non-prod)"
	@echo "  make logs [ENV=production|non-prod]    - View logs for specified environment"
	@echo "  make status [ENV=production|non-prod]  - Show status for specified environment"
	@echo "  make link [ENV=production|non-prod]    - Link to specified environment"
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
	@railway environment link $(ENV) > /dev/null
	@echo "Starting deployment..."
	@railway up --service $(SERVICE)

.PHONY: logs
logs:
	@echo "Fetching logs from $(ENV) environment..."
	@railway environment link $(ENV) > /dev/null
	@railway logs --service $(SERVICE)

.PHONY: status
status:
	@echo "Checking status for $(ENV) environment..."
	@railway environment link $(ENV) > /dev/null
	@railway status

.PHONY: link
link:
	@echo "Linking to $(ENV) environment..."
	@railway environment link $(ENV)
	@railway status

.PHONY: domain
domain:
	@echo "Getting domain for $(ENV) environment..."
	@railway environment link $(ENV) > /dev/null
	@railway domain --service $(SERVICE)

.PHONY: variables
variables:
	@echo "Listing variables for $(ENV) environment..."
	@railway environment link $(ENV) > /dev/null
	@railway variables
