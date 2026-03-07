import logging
import os
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

WISE_API_TOKEN = os.getenv("WISE_API_TOKEN", "")
WISE_PROFILE_ID = os.getenv("WISE_PROFILE_ID", "")
WISE_TEST_MODE = os.getenv("WISE_TEST_MODE", "true").lower() == "true"

WISE_BASE_URL = (
    "https://api.sandbox.transferwise.tech"
    if WISE_TEST_MODE
    else "https://api.wise.com"
)


class WiseService:
    """Wise Business API integration for SEPA payouts.

    When WISE_TEST_MODE is true or credentials are missing, simulates payouts
    with fake transfer IDs so the full withdrawal flow can be tested.
    """

    def __init__(self):
        self.test_mode = WISE_TEST_MODE or not WISE_API_TOKEN or not WISE_PROFILE_ID

    async def create_payout(
        self,
        iban: str,
        amount: float,
        reference: str,
        recipient_name: str = "Milo User",
    ) -> str:
        """Create a SEPA payout to the given IBAN.

        Returns the Wise transfer ID (or a fake one in test mode).
        """
        if self.test_mode:
            fake_id = f"test-{uuid.uuid4().hex[:12]}"
            logger.info(
                f"[WISE TEST MODE] Simulated payout: {amount} EUR to {iban[-4:]}, "
                f"ref={reference}, fake_transfer_id={fake_id}"
            )
            return fake_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {
                    "Authorization": f"Bearer {WISE_API_TOKEN}",
                    "Content-Type": "application/json",
                }

                # Step 1: Create quote
                quote_resp = await client.post(
                    f"{WISE_BASE_URL}/v3/profiles/{WISE_PROFILE_ID}/quotes",
                    headers=headers,
                    json={
                        "sourceCurrency": "EUR",
                        "targetCurrency": "EUR",
                        "sourceAmount": amount,
                        "targetAmount": None,
                        "payOut": "BANK_TRANSFER",
                    },
                )
                quote_resp.raise_for_status()
                quote_id = quote_resp.json()["id"]

                # Step 2: Create recipient
                recipient_resp = await client.post(
                    f"{WISE_BASE_URL}/v1/accounts",
                    headers=headers,
                    json={
                        "currency": "EUR",
                        "type": "iban",
                        "profile": int(WISE_PROFILE_ID),
                        "accountHolderName": recipient_name,
                        "details": {"IBAN": iban},
                    },
                )
                recipient_resp.raise_for_status()
                recipient_id = recipient_resp.json()["id"]

                # Step 3: Create transfer
                transfer_resp = await client.post(
                    f"{WISE_BASE_URL}/v1/transfers",
                    headers=headers,
                    json={
                        "targetAccount": recipient_id,
                        "quoteUuid": quote_id,
                        "customerTransactionId": str(uuid.uuid4()),
                        "details": {"reference": reference},
                    },
                )
                transfer_resp.raise_for_status()
                transfer_id = transfer_resp.json()["id"]

                # Step 4: Fund transfer
                fund_resp = await client.post(
                    f"{WISE_BASE_URL}/v3/profiles/{WISE_PROFILE_ID}/transfers/{transfer_id}/payments",
                    headers=headers,
                    json={"type": "BALANCE"},
                )
                fund_resp.raise_for_status()

                logger.info(
                    f"[WISE] Payout created: {amount} EUR to ****{iban[-4:]}, "
                    f"transfer_id={transfer_id}"
                )
                return str(transfer_id)

        except httpx.HTTPStatusError as e:
            logger.error(f"[WISE] API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"[WISE] Payout failed: {e}")
            raise
