from datetime import datetime
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bank_connection import BankConnection, BankConnectionStatus, CallbackType


class BankConnectionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, connection_id: str) -> Optional[BankConnection]:
        """Get connection by ID."""
        result = await self.db.execute(
            select(BankConnection).where(BankConnection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_and_user(
        self, connection_id: str, user_id: str
    ) -> Optional[BankConnection]:
        """Get connection by ID and user ID."""
        result = await self.db.execute(
            select(BankConnection).where(
                BankConnection.id == connection_id,
                BankConnection.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_session_id(self, session_id: str) -> Optional[BankConnection]:
        """Get connection by EnableBanking session ID."""
        result = await self.db.execute(
            select(BankConnection).where(BankConnection.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_by_auth_state(self, auth_state: str) -> Optional[BankConnection]:
        """Get pending connection by auth state (for OAuth callback)."""
        result = await self.db.execute(
            select(BankConnection).where(
                BankConnection.auth_state == auth_state,
                BankConnection.status == BankConnectionStatus.PENDING,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self, user_id: str, include_accounts: bool = False
    ) -> List[BankConnection]:
        """Get all connections for a user."""
        query = select(BankConnection).where(BankConnection.user_id == user_id)

        if include_accounts:
            query = query.options(selectinload(BankConnection.accounts))

        query = query.order_by(BankConnection.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_active_by_user(self, user_id: str) -> List[BankConnection]:
        """Get active connections for a user."""
        result = await self.db.execute(
            select(BankConnection)
            .where(
                BankConnection.user_id == user_id,
                BankConnection.status == BankConnectionStatus.ACTIVE,
            )
            .order_by(BankConnection.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_user_and_bank(
        self, user_id: str, aspsp_name: str, exclude_id: Optional[str] = None
    ) -> List[BankConnection]:
        """Get all connections for a user to a specific bank.

        Used to find existing connections when reconnecting to the same bank.
        """
        query = select(BankConnection).where(
            BankConnection.user_id == user_id,
            BankConnection.aspsp_name == aspsp_name,
        )
        if exclude_id:
            query = query.where(BankConnection.id != exclude_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        user_id: str,
        aspsp_name: str,
        aspsp_country: str,
        auth_state: str,
        callback_type: CallbackType = CallbackType.WEB,
    ) -> BankConnection:
        """Create a new pending bank connection."""
        connection = BankConnection(
            user_id=user_id,
            aspsp_name=aspsp_name,
            aspsp_country=aspsp_country,
            auth_state=auth_state,
            callback_type=callback_type,
            status=BankConnectionStatus.PENDING,
        )
        self.db.add(connection)
        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def activate(
        self,
        connection: BankConnection,
        session_id: str,
        valid_until: Optional[datetime] = None,
        raw_response: Optional[dict] = None,
    ) -> BankConnection:
        """Activate a connection after successful OAuth callback."""
        connection.session_id = session_id
        connection.status = BankConnectionStatus.ACTIVE
        connection.valid_until = valid_until
        connection.auth_state = None  # Clear auth state after use
        connection.raw_response = raw_response
        connection.error_message = None

        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def update_status(
        self,
        connection: BankConnection,
        status: BankConnectionStatus,
        error_message: Optional[str] = None,
    ) -> BankConnection:
        """Update connection status."""
        connection.status = status
        connection.error_message = error_message

        await self.db.flush()
        await self.db.refresh(connection)
        return connection

    async def delete(self, connection_id: str) -> bool:
        """Delete a connection."""
        connection = await self.get_by_id(connection_id)
        if not connection:
            return False

        await self.db.delete(connection)
        await self.db.flush()
        return True
