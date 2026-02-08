#!/bin/bash
# Railway logs helper for milo-backend
# Usage: ./scripts/railway-logs.sh [prod|non-prod]

set -e

ENV="${1:-non-prod}"

if [ "$ENV" = "prod" ] || [ "$ENV" = "production" ]; then
  RAILWAY_TOKEN=a5fd4542-cbf4-405d-9df2-9a1abf680ad3 railway logs --service scandalicious-api
elif [ "$ENV" = "non-prod" ] || [ "$ENV" = "nonprod" ]; then
  RAILWAY_TOKEN=2f4b2fe6-4d49-4588-a77f-e679f78861ca railway logs --service scandalicious-api
else
  echo "Unknown environment: $ENV (use 'prod' or 'non-prod')"
  exit 1
fi
