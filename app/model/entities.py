from dataclasses import dataclass
from typing import Optional
from enum import Enum

class Season(str, Enum):
    """Valid tire seasons."""
    WINTER = "winter"
    SUMMER = "summer"
    ALLSEASON = "allseason"

@dataclass
class WheelRecord:
    """Represents a stored wheel set for a customer."""
    id: Optional[int]        # Primary key in DB (None for new records)
    customer_name: str       # Name of the customer
    location: str            # Storage location (shelf, position, etc.)
    season: Season           # Tire season (Winter/Summer/Allseason)