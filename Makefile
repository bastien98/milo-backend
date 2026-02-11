# Makefile for Railway deployment
# Uses `railway login` session auth (no tokens needed).
# Run `make login` once, then `make link` to connect to the project.

# Default environment (can be overridden: make deploy ENV=production)
ENV ?= non-prod

# Railway service name
SERVICE = scandalicious-api

# Railway environment names (must match what's in the Railway dashboard)
ifeq ($(ENV),production)
  RAILWAY_ENV = production
else
  RAILWAY_ENV = non-prod
endif

.PHONY: help
help:
	@echo "Railway Deployment Commands:"
	@echo "  make login                               - Authenticate with Railway (browser OAuth)"
	@echo "  make link                                - Link to the Railway project (interactive, one-time)"
	@echo "  make deploy [ENV=production|non-prod]     - Deploy to specified environment (default: non-prod)"
	@echo "  make logs [ENV=production|non-prod]       - View logs for specified environment"
	@echo "  make status                               - Show project status"
	@echo "  make variables [ENV=production|non-prod]  - List variables for specified environment"
	@echo "  make domain [ENV=production|non-prod]     - Get domain for specified environment"
	@echo ""
	@echo "First-time setup:"
	@echo "  make login   # Authenticate via browser"
	@echo "  make link    # Select project (one-time)"
	@echo ""
	@echo "Deploy examples:"
	@echo "  make deploy                # Deploy to non-prod"
	@echo "  make deploy ENV=production # Deploy to production"
	@echo "  make logs ENV=production   # View production logs"

.PHONY: login
login:
	@echo "Authenticating with Railway..."
	@railway login

.PHONY: link
link:
	@echo "Linking to Railway project..."
	@railway link

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
