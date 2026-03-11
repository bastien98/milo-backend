import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.lottery_repo import LotteryRepository
from app.db.repositories.cashback_repo import CashbackRepository
from app.models.lottery import LotteryDrawing, LotteryEntry
from app.models.receipt import Receipt
from app.models.user import User
from app.models.user_profile import UserProfile
from app.models.enums import ReceiptStatus
from app.services.gold_tier_service import check_gold_tier


class LotteryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.lottery_repo = LotteryRepository(db)
        self.cashback_repo = CashbackRepository(db)

    async def get_user_lottery_status(self, user_id: str, firebase_uid: str) -> dict:
        """Get the current month's lottery status for a user."""
        now = datetime.now(timezone.utc)
        current_month = f"{now.year}-{now.month:02d}"

        drawing = await self.lottery_repo.get_or_create_drawing(current_month)

        # Check if user has instagram handle
        profile_result = await self.db.execute(
            select(UserProfile).where(UserProfile.user_id == firebase_uid)
        )
        profile = profile_result.scalar_one_or_none()
        has_instagram = bool(profile and profile.instagram_handle)

        # Check if user has receipt activity this month
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        receipt_result = await self.db.execute(
            select(func.count()).select_from(Receipt).where(
                Receipt.user_id == user_id,
                Receipt.status == ReceiptStatus.COMPLETED,
                Receipt.created_at >= month_start,
            )
        )
        has_receipt = (receipt_result.scalar() or 0) > 0

        # Check if user's entry has instagram share recorded
        entry_result = await self.db.execute(
            select(LotteryEntry).where(
                LotteryEntry.drawing_id == drawing.id,
                LotteryEntry.user_id == user_id,
            )
        )
        entry = entry_result.scalar_one_or_none()
        proof_status = entry.proof_status if entry else None
        has_share = bool(entry and entry.has_instagram_share and proof_status == "approved")

        eligible = has_instagram and has_receipt and has_share

        # Get last month's winner
        last_month = now.month - 1 if now.month > 1 else 12
        last_year = now.year if now.month > 1 else now.year - 1
        last_month_str = f"{last_year}-{last_month:02d}"
        last_drawing = await self.lottery_repo.get_drawing_by_month(last_month_str)

        last_winner = None
        if last_drawing and last_drawing.winner_name:
            last_winner = {
                "name": last_drawing.winner_name,
                "instagram_handle": last_drawing.winner_instagram_handle or "",
                "month": last_month_str,
            }

        return {
            "eligible": eligible,
            "has_instagram": has_instagram,
            "has_receipt": has_receipt,
            "has_share": has_share,
            "proof_status": proof_status,
            "current_month": current_month,
            "prize_amount": drawing.prize_amount_cents / 100,
            "drawing_status": drawing.status,
            "last_winner": last_winner,
        }

    async def refresh_entries(self, month: str) -> list:
        """Populate/refresh lottery entries from all Gold Tier users with IG handles.

        Called when admin views the participants panel so entries are up-to-date.
        Does NOT modify entries if drawing is already locked.
        """
        drawing = await self.lottery_repo.get_or_create_drawing(month)

        if drawing.status != "pending":
            # Already locked — just return existing entries
            return await self.lottery_repo.get_entries_for_drawing(drawing.id)

        # Parse month for receipt check
        year, mo = map(int, month.split("-"))
        month_start = datetime(year, mo, 1, tzinfo=timezone.utc)
        if mo == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(year, mo + 1, 1, tzinfo=timezone.utc)

        # Get all users with profiles (show all Gold Tier users, even without IG handle)
        users_result = await self.db.execute(
            select(User, UserProfile)
            .join(UserProfile, User.firebase_uid == UserProfile.user_id, isouter=True)
        )
        users_with_profiles = users_result.all()

        for user, profile in users_with_profiles:
            if not profile:
                continue

            # Check gold tier
            is_gold = await check_gold_tier(self.db, user.id)
            if not is_gold:
                continue

            # Check receipt activity this month
            receipt_count = await self.db.execute(
                select(func.count()).select_from(Receipt).where(
                    Receipt.user_id == user.id,
                    Receipt.status == ReceiptStatus.COMPLETED,
                    Receipt.created_at >= month_start,
                    Receipt.created_at < month_end,
                )
            )
            has_receipt = (receipt_count.scalar() or 0) > 0

            display_name = profile.nickname or profile.first_name or "User"

            # Preserve existing share status
            entry_result = await self.db.execute(
                select(LotteryEntry).where(
                    LotteryEntry.drawing_id == drawing.id,
                    LotteryEntry.user_id == user.id,
                )
            )
            existing_entry = entry_result.scalar_one_or_none()
            has_share = bool(existing_entry and existing_entry.has_instagram_share)

            await self.lottery_repo.upsert_entry(
                drawing_id=drawing.id,
                user_id=user.id,
                instagram_handle=profile.instagram_handle,
                display_name=display_name,
                has_receipt_activity=has_receipt,
                has_instagram_share=has_share,
            )

        await self.db.commit()
        return await self.lottery_repo.get_entries_for_drawing(drawing.id)

    async def lock_participants(self, month: str) -> LotteryDrawing:
        """Lock participants for a month's drawing."""
        drawing = await self.lottery_repo.get_or_create_drawing(month)

        if drawing.status != "pending":
            raise ValueError(f"Drawing is already {drawing.status}")

        # Get all Gold Tier users with instagram handles
        users_result = await self.db.execute(
            select(User, UserProfile)
            .join(UserProfile, User.firebase_uid == UserProfile.user_id, isouter=True)
            .where(UserProfile.instagram_handle.isnot(None))
        )
        users_with_profiles = users_result.all()

        # Parse month for receipt check
        year, mo = map(int, month.split("-"))
        month_start = datetime(year, mo, 1, tzinfo=timezone.utc)
        if mo == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(year, mo + 1, 1, tzinfo=timezone.utc)

        # Check each user's eligibility
        for user, profile in users_with_profiles:
            # Check gold tier
            is_gold = await check_gold_tier(self.db, user.id)
            if not is_gold:
                continue

            # Check receipt activity
            receipt_count = await self.db.execute(
                select(func.count()).select_from(Receipt).where(
                    Receipt.user_id == user.id,
                    Receipt.status == ReceiptStatus.COMPLETED,
                    Receipt.created_at >= month_start,
                    Receipt.created_at < month_end,
                )
            )
            has_receipt = (receipt_count.scalar() or 0) > 0

            display_name = profile.nickname or profile.first_name or "User"

            # Get existing entry to preserve share status
            entry_result = await self.db.execute(
                select(LotteryEntry).where(
                    LotteryEntry.drawing_id == drawing.id,
                    LotteryEntry.user_id == user.id,
                )
            )
            existing_entry = entry_result.scalar_one_or_none()
            has_share = bool(existing_entry and existing_entry.has_instagram_share)

            await self.lottery_repo.upsert_entry(
                drawing_id=drawing.id,
                user_id=user.id,
                instagram_handle=profile.instagram_handle,
                display_name=display_name,
                has_receipt_activity=has_receipt,
                has_instagram_share=has_share,
            )

        # Assign sequential entry numbers to eligible entries
        eligible_entries = await self.lottery_repo.get_eligible_entries(drawing.id)
        for i, entry in enumerate(eligible_entries):
            entry.entry_number = i
        await self.db.flush()

        # Update drawing
        drawing = await self.lottery_repo.update_drawing(
            drawing,
            status="participants_locked",
            participant_count=len(eligible_entries),
        )

        return drawing

    async def draw_winner(self, month: str) -> LotteryDrawing:
        """Draw a winner using cryptographic randomness."""
        drawing = await self.lottery_repo.get_drawing_by_month(month)
        if not drawing:
            raise ValueError(f"No drawing found for {month}")
        if drawing.status != "participants_locked":
            raise ValueError(f"Drawing status must be participants_locked, got {drawing.status}")
        if drawing.participant_count == 0:
            raise ValueError("No eligible participants")

        # Generate cryptographic seed
        seed = secrets.token_hex(32)
        seed_hash = hashlib.sha256(seed.encode()).hexdigest()

        # Determine winner index
        winner_index = int(seed, 16) % drawing.participant_count
        winner_entry = await self.lottery_repo.get_entry_by_number(drawing.id, winner_index)

        if not winner_entry:
            raise ValueError(f"Could not find entry with number {winner_index}")

        # Credit prize to winner's wallet
        prize_euros = drawing.prize_amount_cents / 100.0
        await self.cashback_repo.upsert_balance_increment(
            user_id=winner_entry.user_id,
            cashback_amount=prize_euros,
        )

        # Update drawing with winner info
        drawing = await self.lottery_repo.update_drawing(
            drawing,
            status="drawn",
            seed=seed,
            seed_hash=seed_hash,
            winner_user_id=winner_entry.user_id,
            winner_name=winner_entry.display_name,
            winner_instagram_handle=winner_entry.instagram_handle,
            drawn_at=datetime.now(timezone.utc),
        )

        return drawing

    async def get_video_props(self, month: str) -> dict:
        """Get props for the Remotion video composition."""
        drawing = await self.lottery_repo.get_drawing_by_month(month)
        if not drawing or drawing.status not in ("drawn", "published"):
            raise ValueError("Drawing must be in drawn state")

        eligible_entries = await self.lottery_repo.get_eligible_entries(drawing.id)

        # Select 6-8 participants including the winner for the video
        import random
        winner_entry = next((e for e in eligible_entries if e.user_id == drawing.winner_user_id), None)
        non_winners = [e for e in eligible_entries if e.user_id != drawing.winner_user_id]

        # Pick up to 5-7 non-winners for the video display
        display_count = min(7, len(non_winners))
        random.seed(drawing.seed)
        selected_non_winners = random.sample(non_winners, display_count) if non_winners else []

        # Build participant list with winner inserted
        participants = []
        for entry in selected_non_winners:
            participants.append({
                "name": entry.display_name or "Participant",
                "instagramHandle": entry.instagram_handle or "user",
            })

        # Insert winner at a random position
        winner_index = random.randint(0, len(participants))
        participants.insert(winner_index, {
            "name": winner_entry.display_name if winner_entry else drawing.winner_name or "Winner",
            "instagramHandle": winner_entry.instagram_handle if winner_entry else drawing.winner_instagram_handle or "winner",
        })

        # Format month label
        year, mo = map(int, month.split("-"))
        month_names = ["", "January", "February", "March", "April", "May", "June",
                       "July", "August", "September", "October", "November", "December"]
        month_label = f"{month_names[mo]} {year}"

        return {
            "participants": participants,
            "winnerIndex": winner_index,
            "monthLabel": month_label,
            "prizeAmount": f"\u20AC{drawing.prize_amount_cents // 100}",
            "fairnessHash": drawing.seed_hash or "",
        }

    async def publish_drawing(self, month: str, video_url: str) -> LotteryDrawing:
        """Mark a drawing as published."""
        drawing = await self.lottery_repo.get_drawing_by_month(month)
        if not drawing:
            raise ValueError(f"No drawing found for {month}")

        return await self.lottery_repo.update_drawing(
            drawing,
            status="published",
            video_url=video_url,
            published_at=datetime.now(timezone.utc),
        )
