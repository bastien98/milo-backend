import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List

import httpx
import jwt

from app.config import get_settings
from app.core.exceptions import EnableBankingAPIError

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass
class BankInfo:
    """Information about an available bank."""

    name: str
    country: str
    bic: Optional[str]
    logo_url: Optional[str]
    max_consent_days: int


@dataclass
class AuthorizationResult:
    """Result of starting authorization."""

    url: str  # Redirect URL for user
    state: str  # State parameter for callback verification


@dataclass
class SessionResult:
    """Result of creating a session."""

    session_id: str
    valid_until: Optional[datetime]
    accounts: List[dict]  # Raw account data from EnableBanking


@dataclass
class AccountBalance:
    """Account balance information."""

    balance_amount: float
    balance_type: str  # e.g., "closingBooked", "expected"
    currency: str
    reference_date: Optional[date]


@dataclass
class TransactionData:
    """Parsed transaction data from EnableBanking."""

    transaction_id: str
    amount: float
    currency: str
    booking_date: date
    value_date: Optional[date]
    creditor_name: Optional[str]
    creditor_iban: Optional[str]
    debtor_name: Optional[str]
    debtor_iban: Optional[str]
    description: Optional[str]
    remittance_info: Optional[str]
    entry_reference: Optional[str]
    raw: dict


class EnableBankingService:
    """Service for interacting with EnableBanking Open Banking API.

    Note: EnableBanking uses the same API URL for both sandbox and production.
    The sandbox mode is determined by the app credentials, not the URL.
    """

    BASE_URL = "https://api.enablebanking.com"

    def __init__(
        self,
        app_id: Optional[str] = None,
        private_key: Optional[str] = None,
        redirect_url: Optional[str] = None,
        sandbox: Optional[bool] = None,
    ):
        self.app_id = app_id or settings.ENABLEBANKING_APP_ID
        self.private_key = private_key or self._load_private_key()
        self.redirect_url = redirect_url or settings.ENABLEBANKING_REDIRECT_URL
        self.sandbox = sandbox if sandbox is not None else settings.ENABLEBANKING_SANDBOX

        if not all([self.app_id, self.private_key, self.redirect_url]):
            missing = []
            if not self.app_id:
                missing.append("ENABLEBANKING_APP_ID")
            if not self.private_key:
                missing.append("ENABLEBANKING_PRIVATE_KEY or ENABLEBANKING_PRIVATE_KEY_PATH")
            if not self.redirect_url:
                missing.append("ENABLEBANKING_REDIRECT_URL")
            raise EnableBankingAPIError(
                "EnableBanking credentials not configured",
                details={"error_type": "configuration", "missing": missing},
            )

        self.base_url = self.BASE_URL
        logger.info(f"EnableBanking service initialized: sandbox={self.sandbox}, base_url={self.base_url}")

    def _load_private_key(self) -> str:
        """Load private key from settings or file.

        Handles escaped newlines (\\n) in environment variables,
        which is common when storing PEM files as env vars.
        """
        if settings.ENABLEBANKING_PRIVATE_KEY:
            key = settings.ENABLEBANKING_PRIVATE_KEY
            logger.debug(f"Raw private key length: {len(key)}, starts_with_begin: {key.startswith('-----BEGIN')}")
            has_literal_backslash_n = "\\n" in repr(key)
            logger.debug(f"Contains literal backslash-n: {has_literal_backslash_n}")

            # Convert escaped newlines to actual newlines
            # This handles PEM keys stored as env vars with \n as literal characters
            if "\\n" in key:
                key = key.replace("\\n", "\n")
                logger.debug("Replaced \\\\n with actual newlines")

            # Validate key structure
            if not key.startswith("-----BEGIN"):
                logger.error(f"Private key doesn't start with -----BEGIN. First 50 chars: {key[:50]}")
            if "-----END" not in key:
                logger.error("Private key doesn't contain -----END marker")

            logger.debug(f"Processed key length: {len(key)}, line_count: {key.count(chr(10))}")
            return key

        if settings.ENABLEBANKING_PRIVATE_KEY_PATH:
            try:
                with open(settings.ENABLEBANKING_PRIVATE_KEY_PATH, "r") as f:
                    return f.read()
            except FileNotFoundError:
                raise EnableBankingAPIError(
                    f"EnableBanking private key file not found: {settings.ENABLEBANKING_PRIVATE_KEY_PATH}",
                    details={"error_type": "configuration"},
                )

        return ""

    def _generate_jwt(self) -> str:
        """Generate JWT token for API authentication."""
        now = int(time.time())

        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,  # 1 hour expiry
        }

        headers = {
            "kid": self.app_id,
            "alg": "RS256",
        }

        try:
            token = jwt.encode(
                payload,
                self.private_key,
                algorithm="RS256",
                headers=headers,
            )
            logger.debug(f"Generated JWT token (first 50 chars): {token[:50]}...")
            logger.debug(f"JWT kid (app_id): {self.app_id}")
            return token
        except Exception as e:
            logger.error(f"Failed to generate JWT: {e}")
            logger.error(f"Private key first 100 chars: {self.private_key[:100] if self.private_key else 'EMPTY'}")
            raise EnableBankingAPIError(
                "Failed to generate authentication token. Check private key format.",
                details={"error_type": "authentication", "error": str(e)},
            )

    def _get_headers(self) -> dict:
        """Get authentication headers for API requests."""
        return {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make authenticated request to EnableBanking API."""
        url = f"{self.base_url}{endpoint}"
        logger.debug(f"EnableBanking API request: {method} {url} params={params}")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=self._get_headers(),
                    json=json,
                    params=params,
                )

                if response.status_code == 401:
                    logger.error(f"EnableBanking API authentication failed. Response: {response.text[:500]}")
                    raise EnableBankingAPIError(
                        "EnableBanking API authentication failed",
                        details={"error_type": "authentication"},
                    )
                elif response.status_code == 404:
                    logger.warning(f"EnableBanking resource not found: {endpoint}")
                    raise EnableBankingAPIError(
                        "Resource not found",
                        details={"error_type": "not_found", "endpoint": endpoint},
                    )
                elif response.status_code == 429:
                    logger.warning("EnableBanking API rate limit exceeded")
                    raise EnableBankingAPIError(
                        "EnableBanking API rate limit exceeded",
                        details={"error_type": "rate_limit"},
                    )
                elif response.status_code >= 400:
                    logger.error(
                        f"EnableBanking API error: {response.status_code} - {response.text}"
                    )
                    raise EnableBankingAPIError(
                        f"EnableBanking API error (status {response.status_code})",
                        details={
                            "error_type": "api_error",
                            "status_code": response.status_code,
                            "response": response.text[:500],
                        },
                    )

                if response.status_code == 204:
                    return {}

                return response.json()

        except httpx.TimeoutException as e:
            logger.error(f"EnableBanking API timeout: {e}")
            raise EnableBankingAPIError(
                "EnableBanking API request timed out",
                details={"error_type": "timeout"},
            )
        except httpx.RequestError as e:
            logger.error(f"EnableBanking API connection error: {e}")
            raise EnableBankingAPIError(
                "Failed to connect to EnableBanking API",
                details={"error_type": "connection", "error": str(e)},
            )
        except EnableBankingAPIError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error during EnableBanking request: {e}")
            raise EnableBankingAPIError(
                f"EnableBanking request failed: {str(e)}",
                details={"error_type": "unexpected", "error": str(e)},
            )

    # =========================================================================
    # Bank Discovery
    # =========================================================================

    async def list_banks(self, country: str) -> List[BankInfo]:
        """
        List available banks for a country.

        Args:
            country: ISO 3166-1 alpha-2 country code (e.g., "BE", "NL", "DE")

        Returns:
            List of available banks
        """
        data = await self._request("GET", "/aspsps", params={"country": country.upper()})

        banks = []
        for aspsp in data.get("aspsps", []):
            banks.append(
                BankInfo(
                    name=aspsp.get("name", "Unknown"),
                    country=aspsp.get("country", country),
                    bic=aspsp.get("bic"),
                    logo_url=aspsp.get("logo"),
                    max_consent_days=aspsp.get("maximum_consent_validity", 90),
                )
            )

        return banks

    # =========================================================================
    # Authorization Flow
    # =========================================================================

    async def start_authorization(
        self,
        aspsp_name: str,
        aspsp_country: str,
        psu_type: str = "personal",
        consent_days: int = 90,
    ) -> AuthorizationResult:
        """
        Start bank authorization flow.

        Args:
            aspsp_name: Bank name from list_banks
            aspsp_country: Country code
            psu_type: "personal" or "business"
            consent_days: Number of days the consent should be valid

        Returns:
            AuthorizationResult with redirect URL and state
        """
        state = secrets.token_urlsafe(32)

        valid_until = datetime.now(timezone.utc) + timedelta(days=consent_days)

        payload = {
            "aspsp": {
                "name": aspsp_name,
                "country": aspsp_country.upper(),
            },
            "state": state,
            "redirect_url": self.redirect_url,
            "psu_type": psu_type,
            "access": {
                "valid_until": valid_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        }

        logger.info(f"=== EnableBanking /auth request ===")
        logger.info(f"ASPSP name: '{aspsp_name}'")
        logger.info(f"ASPSP country: '{aspsp_country.upper()}'")
        logger.info(f"Full payload: {payload}")

        data = await self._request("POST", "/auth", json=payload)

        return AuthorizationResult(
            url=data.get("url", ""),
            state=state,
        )

    async def create_session(self, code: str) -> SessionResult:
        """
        Exchange authorization code for session.

        Args:
            code: Authorization code from callback

        Returns:
            SessionResult with session ID and accounts
        """
        payload = {"code": code}
        data = await self._request("POST", "/sessions", json=payload)

        # Log the full raw response for debugging
        logger.info(f"=== EnableBanking /sessions response ===")
        logger.info(f"Full response keys: {list(data.keys())}")
        logger.info(f"Session ID: {data.get('session_id')}")
        logger.info(f"Accounts count: {len(data.get('accounts', []))}")
        for i, acc in enumerate(data.get("accounts", [])):
            logger.info(f"Account {i}: {acc}")

        valid_until = None
        if data.get("access", {}).get("valid_until"):
            try:
                valid_until_str = data["access"]["valid_until"]
                # Handle both formats: with and without Z suffix
                if valid_until_str.endswith("Z"):
                    valid_until_str = valid_until_str[:-1] + "+00:00"
                valid_until = datetime.fromisoformat(valid_until_str)
            except (ValueError, KeyError):
                logger.warning("Failed to parse valid_until date from EnableBanking")

        return SessionResult(
            session_id=data.get("session_id", ""),
            valid_until=valid_until,
            accounts=data.get("accounts", []),
        )

    async def delete_session(self, session_id: str) -> bool:
        """
        Revoke a session (delete consent).

        Args:
            session_id: EnableBanking session ID

        Returns:
            True if successful
        """
        try:
            await self._request("DELETE", f"/sessions/{session_id}")
            return True
        except EnableBankingAPIError as e:
            if e.details.get("error_type") == "not_found":
                return True  # Already deleted
            raise

    # =========================================================================
    # Data Fetching
    # =========================================================================

    async def get_account_balances(
        self, session_id: str, account_id: str
    ) -> List[AccountBalance]:
        """
        Get balances for an account.

        Args:
            session_id: EnableBanking session ID
            account_id: Account UID from session

        Returns:
            List of account balances
        """
        # Note: EnableBanking API uses /accounts/{account_id}/balances (not /sessions/.../accounts/...)
        # The session context is provided via the JWT authentication
        data = await self._request(
            "GET", f"/accounts/{account_id}/balances"
        )

        balances = []
        for balance in data.get("balances", []):
            amount = balance.get("balance_amount", {})
            ref_date = None
            if balance.get("reference_date"):
                try:
                    ref_date = date.fromisoformat(balance["reference_date"])
                except ValueError:
                    pass

            balances.append(
                AccountBalance(
                    balance_amount=float(amount.get("amount", 0)),
                    balance_type=balance.get("balance_type", "unknown"),
                    currency=amount.get("currency", "EUR"),
                    reference_date=ref_date,
                )
            )

        return balances

    async def get_transactions(
        self,
        session_id: str,
        account_id: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[TransactionData]:
        """
        Get transactions for an account.

        Args:
            session_id: EnableBanking session ID
            account_id: Account UID from session
            date_from: Start date (default: 90 days ago)
            date_to: End date (default: today)

        Returns:
            List of transactions
        """
        params = {}
        if date_from:
            params["date_from"] = date_from.isoformat()
        if date_to:
            params["date_to"] = date_to.isoformat()

        # Note: EnableBanking API uses /accounts/{account_id}/transactions (not /sessions/.../accounts/...)
        # The session context is provided via the JWT authentication
        data = await self._request(
            "GET",
            f"/accounts/{account_id}/transactions",
            params=params if params else None,
        )

        transactions = []
        for txn in data.get("transactions", []):
            # Parse amount
            amount_data = txn.get("transaction_amount", {})
            amount = float(amount_data.get("amount", 0))
            currency = amount_data.get("currency", "EUR")

            # Parse dates
            booking_date = None
            value_date = None
            if txn.get("booking_date"):
                try:
                    booking_date = date.fromisoformat(txn["booking_date"])
                except ValueError:
                    booking_date = date.today()
            else:
                booking_date = date.today()

            if txn.get("value_date"):
                try:
                    value_date = date.fromisoformat(txn["value_date"])
                except ValueError:
                    pass

            # Parse creditor/debtor (handle null values from API)
            creditor = txn.get("creditor") or {}
            debtor = txn.get("debtor") or {}

            # Get IBAN from nested account structure
            creditor_iban = None
            if creditor and creditor.get("account"):
                creditor_iban = creditor["account"].get("iban")

            debtor_iban = None
            if debtor and debtor.get("account"):
                debtor_iban = debtor["account"].get("iban")

            # Build transaction ID - prefer transaction_id, fall back to entry_reference
            transaction_id = txn.get("transaction_id") or txn.get("entry_reference", "")
            if not transaction_id:
                # Generate a fallback ID if none provided
                transaction_id = f"{booking_date.isoformat()}_{amount}_{currency}"

            transactions.append(
                TransactionData(
                    transaction_id=transaction_id,
                    amount=amount,
                    currency=currency,
                    booking_date=booking_date,
                    value_date=value_date,
                    creditor_name=creditor.get("name"),
                    creditor_iban=creditor_iban,
                    debtor_name=debtor.get("name"),
                    debtor_iban=debtor_iban,
                    description=txn.get("remittance_information_unstructured"),
                    remittance_info=txn.get("remittance_information_structured"),
                    entry_reference=txn.get("entry_reference"),
                    raw=txn,
                )
            )

        return transactions
