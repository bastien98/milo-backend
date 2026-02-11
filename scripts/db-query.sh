#!/bin/bash
# Database query helper for milo-backend
# Usage: ./scripts/db-query.sh [prod|non-prod] "SQL QUERY"

set -e

ENV="${1:-non-prod}"
QUERY="$2"

if [ -z "$QUERY" ]; then
  echo "Usage: $0 [prod|non-prod] \"SQL QUERY\""
  exit 1
fi

PSQL="/opt/homebrew/opt/libpq/bin/psql"

if [ "$ENV" = "prod" ] || [ "$ENV" = "production" ]; then
  DB_URL="postgresql://postgres:hrGaUOZtYDDNPUDPmXlzpnVAReIgxlkx@switchback.proxy.rlwy.net:45896/railway"
elif [ "$ENV" = "non-prod" ] || [ "$ENV" = "nonprod" ]; then
  DB_URL="postgresql://postgres:tBKODGAPzROEyTeTYDKVjtbdhBhEwkgc@shortline.proxy.rlwy.net:33385/railway"
else
  echo "Unknown environment: $ENV (use 'prod' or 'non-prod')"
  exit 1
fi

$PSQL "$DB_URL" -c "$QUERY"
