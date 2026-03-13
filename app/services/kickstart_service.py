"""
Kickstart service for the Milo Points cashback system.

New users go through a 3-ticket kickstart phase before entering the regular system:
  Ticket 1: 500 fixed pts + 1 Premium Spin  (total EV: ~700 pts)
  Ticket 2: 500 fixed pts                   (total: 500 pts)
  Ticket 3: 500 fixed pts                   (total: 500 pts, marks kickstart complete)

Total Kickstart CAC: ~1,700 pts = €1.70

Existing users (migrated) have kickstart_completed = True and skip this phase.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app.models.cashback import CashbackBalance
from app.models.enums import SpinType

logger = logging.getLogger(__name__)

KICKSTART_FIXED_POINTS = 500
KICKSTART_TOTAL_TICKETS = 3


@dataclass
class KickstartReward:
    fixed_points: int
    spin_type: Optional[SpinType]
    ticket_number: int       # 1, 2, or 3
    is_final_ticket: bool    # True when kickstart_tickets reaches 3


def is_kickstart_active(balance: CashbackBalance) -> bool:
    """Return True if the user is still in the kickstart phase."""
    return not balance.kickstart_completed


def get_kickstart_progress(balance: CashbackBalance) -> dict:
    """Return kickstart progress info for the API/frontend."""
    return {
        "tickets_completed": balance.kickstart_tickets,
        "total_tickets": KICKSTART_TOTAL_TICKETS,
        "is_completed": balance.kickstart_completed,
    }


def compute_kickstart_reward(ticket_number: int) -> KickstartReward:
    """
    Compute the kickstart reward for a given ticket number (1, 2, or 3).

    Ticket 1: 500 pts + 1 Premium Spin
    Ticket 2: 500 pts
    Ticket 3: 500 pts → kickstart complete
    """
    is_final = ticket_number >= KICKSTART_TOTAL_TICKETS
    spin_type = SpinType.PREMIUM if ticket_number == 1 else None

    return KickstartReward(
        fixed_points=KICKSTART_FIXED_POINTS,
        spin_type=spin_type,
        ticket_number=ticket_number,
        is_final_ticket=is_final,
    )


def advance_kickstart(balance: CashbackBalance) -> KickstartReward:
    """
    Advance the kickstart counter and return the reward for this ticket.
    Mutates the balance object (caller must flush/commit).
    """
    balance.kickstart_tickets += 1
    ticket_number = balance.kickstart_tickets

    reward = compute_kickstart_reward(ticket_number)

    if reward.is_final_ticket:
        balance.kickstart_completed = True
        logger.info(f"Kickstart completed for user {balance.user_id}")
    else:
        logger.info(
            f"Kickstart ticket {ticket_number}/{KICKSTART_TOTAL_TICKETS} "
            f"for user {balance.user_id}"
        )

    return reward
