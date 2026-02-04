"""
Split-aware calculation utilities for budget and analytics.

This module provides functions to calculate user's actual spending
by accounting for expense splits where the user only pays their portion.
"""
from typing import Dict, List, Set, Optional
from collections import defaultdict

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.expense_split import ExpenseSplit, SplitParticipant, SplitAssignment
from app.models.transaction import Transaction



class SplitAwareCalculation:
    """
    Utility class for calculating split-adjusted transaction amounts.

    When a transaction is part of a split:
    - Find the participant marked as is_me=True
    - Calculate user's share: item_price / num_participants_in_assignment

    When a transaction is NOT split:
    - Use the full item_price
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_share_for_transactions(
        self,
        user_id: str,
        transaction_ids: List[str],
    ) -> Dict[str, float]:
        """
        Calculate the user's share for a list of transactions.

        Returns a dict mapping transaction_id -> user's adjusted amount.
        Transactions not in splits return their full item_price.

        Args:
            user_id: The user's ID
            transaction_ids: List of transaction IDs to calculate shares for

        Returns:
            Dict mapping transaction_id to user's share amount
        """
        if not transaction_ids:
            return {}

        # Get all split assignments for these transactions
        # We need to join through ExpenseSplit to filter by user_id
        result = await self.db.execute(
            select(SplitAssignment, ExpenseSplit, SplitParticipant)
            .join(ExpenseSplit, SplitAssignment.split_id == ExpenseSplit.id)
            .join(SplitParticipant, and_(
                SplitParticipant.split_id == ExpenseSplit.id,
                SplitParticipant.is_me == True
            ))
            .where(
                ExpenseSplit.user_id == user_id,
                SplitAssignment.transaction_id.in_(transaction_ids),
            )
        )
        rows = result.all()

        # Build a map of transaction_id -> (assignment, me_participant_id)
        transaction_splits: Dict[str, tuple] = {}
        for assignment, split, me_participant in rows:
            transaction_splits[assignment.transaction_id] = (
                assignment.participant_ids,
                me_participant.id,
            )

        # Get transaction amounts for all requested transactions
        tx_result = await self.db.execute(
            select(Transaction.id, Transaction.item_price)
            .where(Transaction.id.in_(transaction_ids))
        )
        tx_amounts = {row.id: row.item_price for row in tx_result.all()}

        # Calculate user shares
        shares: Dict[str, float] = {}
        for tx_id, item_price in tx_amounts.items():
            if tx_id in transaction_splits:
                participant_ids, me_id = transaction_splits[tx_id]

                # Check if "Me" is in this assignment
                if me_id in participant_ids:
                    # User's share = item_price / number of participants
                    num_participants = len(participant_ids)
                    shares[tx_id] = round(item_price / num_participants, 2)
                else:
                    # "Me" not assigned to this item - user pays nothing
                    shares[tx_id] = 0.0
            else:
                # No split - user pays full amount
                shares[tx_id] = item_price

        return shares

    async def calculate_split_adjusted_spend(
        self,
        user_id: str,
        transactions: List[Transaction],
    ) -> float:
        """
        Calculate total spending with split adjustments.

        For transactions that are part of splits, only the user's portion is counted.
        For transactions not in splits, the full amount is counted.

        Args:
            user_id: The user's ID
            transactions: List of Transaction objects

        Returns:
            Total spend amount (split-adjusted)
        """
        if not transactions:
            return 0.0

        tx_ids = [t.id for t in transactions]
        shares = await self.get_user_share_for_transactions(user_id, tx_ids)

        return sum(shares.values())

    async def calculate_split_adjusted_spend_by_category(
        self,
        user_id: str,
        transactions: List[Transaction],
    ) -> Dict[str, float]:
        """
        Calculate spending by category with split adjustments.

        Args:
            user_id: The user's ID
            transactions: List of Transaction objects

        Returns:
            Dict mapping category_name -> total_spend (split-adjusted)
        """
        if not transactions:
            return {}

        tx_ids = [t.id for t in transactions]
        shares = await self.get_user_share_for_transactions(user_id, tx_ids)

        # Group by category
        category_spend: Dict[str, float] = defaultdict(float)
        for t in transactions:
            amount = shares.get(t.id, t.item_price)
            category_spend[t.category.value] += amount

        # Round all values
        return {cat: round(spend, 2) for cat, spend in category_spend.items()}

    async def calculate_split_adjusted_spend_by_store(
        self,
        user_id: str,
        transactions: List[Transaction],
    ) -> Dict[str, float]:
        """
        Calculate spending by store with split adjustments.

        Args:
            user_id: The user's ID
            transactions: List of Transaction objects

        Returns:
            Dict mapping store_name -> total_spend (split-adjusted)
        """
        if not transactions:
            return {}

        tx_ids = [t.id for t in transactions]
        shares = await self.get_user_share_for_transactions(user_id, tx_ids)

        # Group by store
        store_spend: Dict[str, float] = defaultdict(float)
        for t in transactions:
            amount = shares.get(t.id, t.item_price)
            store_spend[t.store_name] += amount

        # Round all values
        return {store: round(spend, 2) for store, spend in store_spend.items()}

    async def get_transaction_user_amounts(
        self,
        user_id: str,
        transactions: List[Transaction],
    ) -> List[tuple]:
        """
        Get a list of (transaction, user_amount) tuples.

        Useful for iterating over transactions with their adjusted amounts.

        Args:
            user_id: The user's ID
            transactions: List of Transaction objects

        Returns:
            List of (Transaction, user_share_amount) tuples
        """
        if not transactions:
            return []

        tx_ids = [t.id for t in transactions]
        shares = await self.get_user_share_for_transactions(user_id, tx_ids)

        return [(t, shares.get(t.id, t.item_price)) for t in transactions]
