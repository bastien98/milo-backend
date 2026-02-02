import logging
import math
from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status

logger = logging.getLogger(__name__)
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_db_user
from app.config import get_settings
from app.models.user import User
from app.models.bank_connection import BankConnectionStatus, CallbackType
from app.models.bank_transaction import BankTransactionStatus
from app.models.enums import Category
from app.db.repositories.bank_connection_repo import BankConnectionRepository
from app.db.repositories.bank_account_repo import BankAccountRepository
from app.db.repositories.bank_transaction_repo import BankTransactionRepository
from app.db.repositories.transaction_repo import TransactionRepository
from app.db.repositories.receipt_repo import ReceiptRepository
from app.services.enablebanking_service import EnableBankingService
from app.services.bank_categorization_service import BankCategorizationService
from app.core.exceptions import EnableBankingAPIError
from app.schemas.banking import (
    BankInfo,
    BankListResponse,
    BankConnectionCreate,
    BankConnectionResponse,
    BankConnectionAuthResponse,
    BankConnectionListResponse,
    BankAccountResponse,
    BankAccountListResponse,
    BankAccountSyncResponse,
    BankTransactionResponse,
    BankTransactionListResponse,
    TransactionImportRequest,
    TransactionImportResponse,
    TransactionImportResult,
    TransactionIgnoreRequest,
    TransactionIgnoreResponse,
    PendingTransactionsCountResponse,
    BankConnectionStatusEnum,
    BankTransactionStatusEnum,
    CallbackTypeEnum,
)

router = APIRouter()
settings = get_settings()


# =============================================================================
# Bank Discovery
# =============================================================================


@router.get(
    "/banks",
    response_model=BankListResponse,
    summary="List available banks",
    description="Get list of banks available for connection in a specific country.",
)
async def list_banks(
    country: str = Query(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code (e.g., BE, NL, DE)",
    ),
    current_user: User = Depends(get_current_db_user),
):
    """List available banks for a country."""
    try:
        service = EnableBankingService()
        banks = await service.list_banks(country.upper())

        return BankListResponse(
            banks=[
                BankInfo(
                    name=b.name,
                    country=b.country,
                    bic=b.bic,
                    logo_url=b.logo_url,
                    max_consent_days=b.max_consent_days,
                )
                for b in banks
            ],
            country=country.upper(),
        )

    except EnableBankingAPIError as e:
        logger.error(f"EnableBanking API error listing banks: {e.message}, details: {e.details}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "banking_service_error",
                "message": e.message,
                "code": e.details.get("error_type", "unknown"),
                "details": e.details if settings.DEBUG else None,
            },
        )


# =============================================================================
# Bank Connections
# =============================================================================


@router.post(
    "/bank-connections",
    response_model=BankConnectionAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start bank connection",
    description="Initiate OAuth flow to connect a bank account.",
)
async def create_bank_connection(
    data: BankConnectionCreate,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Start bank authorization flow."""
    try:
        service = EnableBankingService()

        # Start authorization with EnableBanking
        auth_result = await service.start_authorization(
            aspsp_name=data.bank_name,
            aspsp_country=data.country.upper(),
        )

        # Map callback type
        callback_type = (
            CallbackType.MOBILE
            if data.callback_type == CallbackTypeEnum.MOBILE
            else CallbackType.WEB
        )

        # Create pending connection in database
        repo = BankConnectionRepository(db)
        connection = await repo.create(
            user_id=current_user.id,
            aspsp_name=data.bank_name,
            aspsp_country=data.country.upper(),
            auth_state=auth_result.state,
            callback_type=callback_type,
        )

        return BankConnectionAuthResponse(
            connection_id=connection.id,
            redirect_url=auth_result.url,
        )

    except EnableBankingAPIError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "banking_service_error",
                "message": e.message,
                "code": e.details.get("error_type", "unknown"),
            },
        )


@router.get(
    "/bank-connections/callback",
    summary="OAuth callback",
    description="Handle OAuth callback from bank. This endpoint is called by the bank after user authorization.",
)
async def bank_connection_callback(
    code: str = Query(..., description="Authorization code from bank"),
    state: str = Query(..., description="State parameter for verification"),
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback from bank."""
    # Find pending connection by state
    conn_repo = BankConnectionRepository(db)
    connection = await conn_repo.get_by_auth_state(state)

    if not connection:
        # Redirect to error page
        error_params = urlencode({"error": "invalid_state", "message": "Invalid or expired authorization"})
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/banking/error?{error_params}",
            status_code=status.HTTP_302_FOUND,
        )

    try:
        service = EnableBankingService()

        # Exchange code for session
        session_result = await service.create_session(code)

        # Log the raw accounts data to debug account_uid extraction
        logger.info(f"EnableBanking session created: session_id={session_result.session_id}")
        logger.info(f"EnableBanking accounts count: {len(session_result.accounts)}")
        for i, acc in enumerate(session_result.accounts):
            logger.info(f"Account {i} raw data keys: {list(acc.keys())}")
            logger.info(f"Account {i} raw data: {acc}")

        # Activate connection
        connection = await conn_repo.activate(
            connection=connection,
            session_id=session_result.session_id,
            valid_until=session_result.valid_until,
            raw_response={"accounts": session_result.accounts},
        )

        # Clean up old connections to the same bank (prevents stale accounts)
        # This ensures after reconnection, only the new connection/accounts are returned
        old_connections = await conn_repo.get_by_user_and_bank(
            user_id=connection.user_id,
            aspsp_name=connection.aspsp_name,
            exclude_id=connection.id,
        )
        for old_conn in old_connections:
            logger.info(
                f"Cleaning up old connection {old_conn.id} to {old_conn.aspsp_name} "
                f"(status={old_conn.status}) after reconnection"
            )
            # Try to revoke the old session with EnableBanking
            if old_conn.session_id:
                try:
                    await service.delete_session(old_conn.session_id)
                except EnableBankingAPIError:
                    pass  # Ignore errors - session may already be expired
            # Delete old connection (cascades to accounts and transactions)
            await conn_repo.delete(old_conn.id)
            logger.info(f"Deleted old connection {old_conn.id} and its accounts")

        # Create accounts from session response
        account_repo = BankAccountRepository(db)
        for account_data in session_result.accounts:
            # Extract account_uid - EnableBanking uses "uid" field (UUID string)
            # Note: "account_id" is an OBJECT containing iban, NOT a string ID
            account_uid = account_data.get("uid", "")

            if not account_uid:
                logger.error(f"No 'uid' field in account data! Keys: {list(account_data.keys())}")
                logger.error(f"Full account data: {account_data}")
                # Skip accounts without uid - they can't be used for API calls
                continue

            logger.info(f"Extracted account_uid: {account_uid} from account data")

            account, created = await account_repo.get_or_create(
                connection_id=connection.id,
                account_uid=account_uid,
                iban=account_data.get("iban"),
                account_name=account_data.get("name"),
                holder_name=account_data.get("owner_name"),
                currency=account_data.get("currency", "EUR"),
                resource_id=account_data.get("resource_id"),
            )
            logger.info(f"Account {'created' if created else 'found'}: id={account.id}, account_uid={account.account_uid}")

        # Build redirect URL based on callback type
        success_params = urlencode({
            "connection_id": connection.id,
            "status": "success",
            "accounts": len(session_result.accounts),
        })

        if connection.callback_type == CallbackType.MOBILE:
            # Mobile deep link
            redirect_url = f"{settings.MOBILE_DEEP_LINK_SCHEME}://banking/callback?{success_params}"
        else:
            # Web redirect
            redirect_url = f"{settings.FRONTEND_URL}/banking/success?{success_params}"

        return RedirectResponse(
            url=redirect_url,
            status_code=status.HTTP_302_FOUND,
        )

    except EnableBankingAPIError as e:
        # Mark connection as error
        await conn_repo.update_status(
            connection=connection,
            status=BankConnectionStatus.ERROR,
            error_message=e.message,
        )

        error_params = urlencode({
            "error": "authorization_failed",
            "message": e.message,
        })

        if connection.callback_type == CallbackType.MOBILE:
            redirect_url = f"{settings.MOBILE_DEEP_LINK_SCHEME}://banking/error?{error_params}"
        else:
            redirect_url = f"{settings.FRONTEND_URL}/banking/error?{error_params}"

        return RedirectResponse(
            url=redirect_url,
            status_code=status.HTTP_302_FOUND,
        )


@router.get(
    "/bank-connections",
    response_model=BankConnectionListResponse,
    summary="List bank connections",
)
async def list_bank_connections(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all bank connections for the current user."""
    repo = BankConnectionRepository(db)
    connections = await repo.get_by_user(current_user.id, include_accounts=True)

    return BankConnectionListResponse(
        connections=[
            BankConnectionResponse(
                id=c.id,
                aspsp_name=c.aspsp_name,
                aspsp_country=c.aspsp_country,
                status=BankConnectionStatusEnum(c.status.value if hasattr(c.status, 'value') else c.status),
                valid_until=c.valid_until,
                error_message=c.error_message,
                created_at=c.created_at,
                updated_at=c.updated_at,
                accounts_count=len(c.accounts) if c.accounts else 0,
            )
            for c in connections
        ]
    )


@router.delete(
    "/bank-connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke bank connection",
)
async def delete_bank_connection(
    connection_id: str,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke and delete a bank connection."""
    repo = BankConnectionRepository(db)
    connection = await repo.get_by_id_and_user(connection_id, current_user.id)

    if not connection:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Connection not found"},
        )

    # Revoke session with EnableBanking if active
    if connection.session_id and connection.status == BankConnectionStatus.ACTIVE:
        try:
            service = EnableBankingService()
            await service.delete_session(connection.session_id)
        except EnableBankingAPIError:
            pass  # Ignore errors during revocation

    # Delete from database (cascades to accounts and transactions)
    await repo.delete(connection_id)

    return None


# =============================================================================
# Bank Accounts
# =============================================================================


@router.get(
    "/bank-accounts",
    response_model=BankAccountListResponse,
    summary="List bank accounts",
)
async def list_bank_accounts(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all linked bank accounts for the current user.

    Only returns accounts from ACTIVE connections.
    Accounts from expired/revoked connections are filtered out.
    """
    account_repo = BankAccountRepository(db)
    conn_repo = BankConnectionRepository(db)

    # Debug: Get all accounts (including inactive) to log the filtering
    all_accounts = await account_repo.get_by_user(current_user.id, active_only=False)
    active_accounts = await account_repo.get_by_user(current_user.id, active_only=True)

    logger.info(f"GET /bank-accounts: user={current_user.id}, total={len(all_accounts)}, active={len(active_accounts)}")

    # Log details about each account for debugging
    for acc in all_accounts:
        conn = await conn_repo.get_by_id(acc.connection_id)
        conn_status = conn.status.value if conn and hasattr(conn.status, 'value') else (conn.status if conn else "no_connection")
        is_returned = any(a.id == acc.id for a in active_accounts)
        logger.info(
            f"  Account {acc.id[:8]}...: iban={acc.iban}, "
            f"conn_status={conn_status}, acc_is_active={acc.is_active}, "
            f"returned={is_returned}"
        )

    return BankAccountListResponse(
        accounts=[
            BankAccountResponse(
                id=a.id,
                connection_id=a.connection_id,
                account_uid=a.account_uid,
                iban=a.iban,
                account_name=a.account_name,
                holder_name=a.holder_name,
                currency=a.currency,
                balance=a.balance,
                balance_type=a.balance_type,
                is_active=a.is_active,
                last_synced_at=a.last_synced_at,
                created_at=a.created_at,
            )
            for a in active_accounts
        ]
    )


@router.post(
    "/bank-accounts/{account_id}/sync",
    response_model=BankAccountSyncResponse,
    summary="Sync bank account",
)
async def sync_bank_account(
    account_id: str,
    days_back: int = Query(default=30, ge=1, le=90, description="Days of history to fetch"),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch latest transactions for a bank account."""
    account_repo = BankAccountRepository(db)
    account = await account_repo.get_by_id_and_user(account_id, current_user.id)

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": "Account not found"},
        )

    # Get connection for session ID
    conn_repo = BankConnectionRepository(db)
    connection = await conn_repo.get_by_id(account.connection_id)

    if not connection or connection.status != BankConnectionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "connection_inactive", "message": "Bank connection is not active"},
        )

    try:
        service = EnableBankingService()

        logger.info(f"Syncing account: id={account.id}, account_uid={account.account_uid}")
        logger.info(f"Using session_id: {connection.session_id}")

        # Fetch balance
        balances = await service.get_account_balances(
            connection.session_id, account.account_uid
        )

        balance = None
        balance_type = None
        for b in balances:
            if b.balance_type in ["closingBooked", "interimBooked"]:
                balance = b.balance_amount
                balance_type = b.balance_type
                break
        if balance is None and balances:
            balance = balances[0].balance_amount
            balance_type = balances[0].balance_type

        # Update account balance
        if balance is not None:
            await account_repo.update_balance(account, balance, balance_type)

        # Fetch transactions
        date_from = date.today() - timedelta(days=days_back)
        transactions = await service.get_transactions(
            connection.session_id,
            account.account_uid,
            date_from=date_from,
            date_to=date.today(),
        )

        # Store new transactions with AI category suggestions
        txn_repo = BankTransactionRepository(db)
        new_count = 0
        new_transactions = []

        for txn in transactions:
            # Skip if already exists
            if await txn_repo.exists(account.id, txn.transaction_id):
                continue

            new_transactions.append(txn)

        # Get AI category suggestions for new transactions in bulk
        if new_transactions:
            try:
                cat_service = BankCategorizationService()
                suggestions = await cat_service.suggest_categories_bulk([
                    {
                        "merchant_name": t.creditor_name or t.debtor_name,
                        "description": t.description,
                    }
                    for t in new_transactions
                ])
            except Exception:
                # If categorization fails, continue without suggestions
                suggestions = [None] * len(new_transactions)

            for i, txn in enumerate(new_transactions):
                suggestion = suggestions[i] if i < len(suggestions) else None

                await txn_repo.create(
                    account_id=account.id,
                    transaction_id=txn.transaction_id,
                    amount=txn.amount,
                    booking_date=txn.booking_date,
                    currency=txn.currency,
                    creditor_name=txn.creditor_name,
                    creditor_iban=txn.creditor_iban,
                    debtor_name=txn.debtor_name,
                    debtor_iban=txn.debtor_iban,
                    value_date=txn.value_date,
                    description=txn.description,
                    remittance_info=txn.remittance_info,
                    entry_reference=txn.entry_reference,
                    raw_response=txn.raw,
                    suggested_category=suggestion.category.value if suggestion else None,
                    category_confidence=suggestion.confidence if suggestion else None,
                )
                new_count += 1

        # Update sync time
        await account_repo.update_sync_time(account)

        return BankAccountSyncResponse(
            account_id=account.id,
            balance=balance,
            transactions_fetched=len(transactions),
            new_transactions=new_count,
            message=f"Synced {new_count} new transactions",
        )

    except EnableBankingAPIError as e:
        # Check if session expired (404 = not found means session/consent expired)
        if e.details.get("error_type") == "not_found":
            logger.error(
                f"EnableBanking 404 error during sync: "
                f"account_id={account.id}, account_uid={account.account_uid}, "
                f"session_id={connection.session_id}, connection_id={connection.id}, "
                f"endpoint={e.details.get('endpoint', 'unknown')}"
            )
            # Mark connection as expired
            await conn_repo.update_status(
                connection,
                BankConnectionStatus.EXPIRED,
                error_message="Bank session expired. Please reconnect your bank account.",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error": "session_expired",
                    "message": "Bank connection has expired. Please reconnect your bank account.",
                    "requires_reauth": True,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "sync_failed",
                "message": e.message,
            },
        )


# =============================================================================
# Bank Transactions
# =============================================================================


@router.get(
    "/bank-transactions",
    response_model=BankTransactionListResponse,
    summary="List bank transactions",
)
async def list_bank_transactions(
    transaction_status: Optional[BankTransactionStatusEnum] = Query(
        default=BankTransactionStatusEnum.PENDING,
        alias="status",
        description="Filter by status",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get bank transactions for the current user."""
    repo = BankTransactionRepository(db)

    transactions, total = await repo.get_pending_by_user(
        current_user.id, page=page, page_size=page_size
    )

    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return BankTransactionListResponse(
        transactions=[
            BankTransactionResponse(
                id=t.id,
                account_id=t.account_id,
                transaction_id=t.transaction_id,
                amount=t.amount,
                currency=t.currency,
                creditor_name=t.creditor_name,
                debtor_name=t.debtor_name,
                booking_date=t.booking_date,
                value_date=t.value_date,
                description=t.description,
                status=BankTransactionStatusEnum(t.status.value if hasattr(t.status, 'value') else t.status),
                imported_transaction_id=t.imported_transaction_id,
                suggested_category=t.suggested_category,
                category_confidence=t.category_confidence,
                created_at=t.created_at,
            )
            for t in transactions
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post(
    "/bank-transactions/import",
    response_model=TransactionImportResponse,
    summary="Import bank transactions",
)
async def import_bank_transactions(
    data: TransactionImportRequest,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Import selected bank transactions to main transaction table.

    Creates a Receipt record for each imported transaction so that:
    - Imported transactions appear in the receipts list
    - Store visits are counted correctly in analytics
    - All existing analytics work without modification
    """
    bank_txn_repo = BankTransactionRepository(db)
    txn_repo = TransactionRepository(db)
    receipt_repo = ReceiptRepository(db)

    results = []
    imported_count = 0
    failed_count = 0

    # Validate category mapping
    category_map = {cat.value: cat for cat in Category}

    for item in data.transactions:
        # Get bank transaction
        bank_txn = await bank_txn_repo.get_by_id_and_user(
            item.bank_transaction_id, current_user.id
        )

        if not bank_txn:
            results.append(
                TransactionImportResult(
                    bank_transaction_id=item.bank_transaction_id,
                    success=False,
                    error="Transaction not found",
                )
            )
            failed_count += 1
            continue

        if bank_txn.status != BankTransactionStatus.PENDING:
            results.append(
                TransactionImportResult(
                    bank_transaction_id=item.bank_transaction_id,
                    success=False,
                    error=f"Transaction already {bank_txn.status.value if hasattr(bank_txn.status, 'value') else bank_txn.status}",
                )
            )
            failed_count += 1
            continue

        # Validate category
        category = category_map.get(item.category)
        if not category:
            results.append(
                TransactionImportResult(
                    bank_transaction_id=item.bank_transaction_id,
                    success=False,
                    error=f"Invalid category: {item.category}",
                )
            )
            failed_count += 1
            continue

        # Determine store name and item name
        store_name = item.store_name
        if not store_name:
            # Use creditor or debtor name as store
            store_name = bank_txn.creditor_name or bank_txn.debtor_name or "Unknown"

        item_name = item.item_name
        if not item_name:
            # Fall back to bank transaction description, then remittance info
            item_name = bank_txn.description or bank_txn.remittance_info
            if not item_name:
                # Final fallback: use a descriptive default
                item_name = f"Bank transaction from {store_name}"

        # Use absolute value for item_price (expenses are negative in bank data)
        transaction_amount = abs(bank_txn.amount)

        try:
            # Create a Receipt record for the bank import
            # This ensures the transaction appears in analytics and receipts list
            receipt = await receipt_repo.create_from_bank_import(
                user_id=current_user.id,
                store_name=store_name,
                receipt_date=bank_txn.booking_date,
                total_amount=transaction_amount,
            )

            # Create main transaction linked to the receipt
            transaction = await txn_repo.create(
                user_id=current_user.id,
                receipt_id=receipt.id,
                store_name=store_name,
                item_name=item_name,
                item_price=transaction_amount,
                category=category,
                date=bank_txn.booking_date,
                quantity=1,
            )

            # Mark bank transaction as imported
            await bank_txn_repo.update_status(
                bank_txn,
                BankTransactionStatus.IMPORTED,
                imported_transaction_id=transaction.id,
            )

            results.append(
                TransactionImportResult(
                    bank_transaction_id=item.bank_transaction_id,
                    imported_transaction_id=transaction.id,
                    success=True,
                )
            )
            imported_count += 1

        except Exception as e:
            results.append(
                TransactionImportResult(
                    bank_transaction_id=item.bank_transaction_id,
                    success=False,
                    error=str(e),
                )
            )
            failed_count += 1

    return TransactionImportResponse(
        imported_count=imported_count,
        failed_count=failed_count,
        results=results,
    )


@router.post(
    "/bank-transactions/ignore",
    response_model=TransactionIgnoreResponse,
    summary="Ignore bank transactions",
)
async def ignore_bank_transactions(
    data: TransactionIgnoreRequest,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark bank transactions as ignored."""
    repo = BankTransactionRepository(db)

    # Verify all transactions belong to user and are pending
    valid_ids = []
    for txn_id in data.transaction_ids:
        txn = await repo.get_by_id_and_user(txn_id, current_user.id)
        if txn and txn.status == BankTransactionStatus.PENDING:
            valid_ids.append(txn_id)

    # Bulk update
    ignored_count = 0
    if valid_ids:
        ignored_count = await repo.bulk_update_status(
            valid_ids, BankTransactionStatus.IGNORED
        )

    return TransactionIgnoreResponse(ignored_count=ignored_count)


@router.get(
    "/bank-transactions/pending/count",
    response_model=PendingTransactionsCountResponse,
    summary="Get pending transactions count",
)
async def get_pending_transactions_count(
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the count of pending bank transactions awaiting import.

    This endpoint is useful for displaying notification badges
    in the app to indicate pending transactions.
    """
    repo = BankTransactionRepository(db)
    count = await repo.get_pending_count_by_user(current_user.id)
    return PendingTransactionsCountResponse(count=count)
