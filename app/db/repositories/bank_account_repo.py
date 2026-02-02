from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_account import BankAccount
from app.models.bank_connection import BankConnection, BankConnectionStatus


class BankAccountRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, account_id: str) -> Optional[BankAccount]:
        """Get account by ID."""
        result = await self.db.execute(
            select(BankAccount).where(BankAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, account_id: str, user_id: str, active_only: bool = True
    ) -> Optional[BankAccount]:
        """Get account by ID, verifying user ownership via connection.

        Args:
            account_id: The account's ID
            user_id: The user's ID
            active_only: If True, only returns account if connection is ACTIVE
        """
        query = (
            select(BankAccount)
            .join(BankConnection)
            .where(
                BankAccount.id == account_id,
                BankConnection.user_id == user_id,
            )
        )

        if active_only:
            # Only allow access to accounts from active connections
            query = query.where(BankConnection.status == "active")

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_by_connection(self, connection_id: str) -> List[BankAccount]:
        """Get all accounts for a connection."""
        result = await self.db.execute(
            select(BankAccount)
            .where(BankAccount.connection_id == connection_id)
            .order_by(BankAccount.created_at)
        )
        return list(result.scalars().all())

    async def get_by_user(
        self, user_id: str, active_only: bool = True
    ) -> List[BankAccount]:
        """Get all accounts for a user across all connections.

        Args:
            user_id: The user's ID
            active_only: If True, only returns accounts from ACTIVE connections
                        where the account itself is also active
        """
        query = (
            select(BankAccount)
            .join(BankConnection)
            .where(BankConnection.user_id == user_id)
        )

        if active_only:
            # Use explicit string comparison since status is stored as String
            query = query.where(
                BankConnection.status == "active",  # BankConnectionStatus.ACTIVE.value
                BankAccount.is_active == True,
            )

        query = query.order_by(BankAccount.created_at)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_or_create(
        self,
        connection_id: str,
        account_uid: str,
        iban: Optional[str] = None,
        account_name: Optional[str] = None,
        holder_name: Optional[str] = None,
        currency: str = "EUR",
        resource_id: Optional[str] = None,
    ) -> Tuple[BankAccount, bool]:
        """Get existing account or create new one. Returns (account, created)."""
        result = await self.db.execute(
            select(BankAccount).where(
                BankAccount.connection_id == connection_id,
                BankAccount.account_uid == account_uid,
            )
        )
        account = result.scalar_one_or_none()

        if account:
            return account, False

        account = BankAccount(
            connection_id=connection_id,
            account_uid=account_uid,
            iban=iban,
            account_name=account_name,
            holder_name=holder_name,
            currency=currency,
            resource_id=resource_id,
        )
        self.db.add(account)
        await self.db.flush()
        await self.db.refresh(account)
        return account, True

    async def update_balance(
        self,
        account: BankAccount,
        balance: float,
        balance_type: Optional[str] = None,
    ) -> BankAccount:
        """Update account balance."""
        account.balance = balance
        account.balance_type = balance_type
        account.last_synced_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(account)
        return account

    async def update_sync_time(self, account: BankAccount) -> BankAccount:
        """Update last sync time."""
        account.last_synced_at = datetime.utcnow()

        await self.db.flush()
        await self.db.refresh(account)
        return account

    async def deactivate(self, account: BankAccount) -> BankAccount:
        """Deactivate an account."""
        account.is_active = False

        await self.db.flush()
        await self.db.refresh(account)
        return account
