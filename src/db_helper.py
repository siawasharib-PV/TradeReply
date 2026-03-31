"""
Additional database helper methods for TradeReply Phase 2
"""

from .typing import Optional, List

from models import (
    Business,
    Review,
    DraftResponse,
    PendingApproval,
    Response,
    StarRating,
    ApprovalStatus,
)
from db_helper import DatabaseHelper


from models import Business, Review, DraftResponse, PendingApproval, Response, StarRating, ApprovalStatus


class DatabaseHelper:
    """Additional methods for Phase 2"""
    
    def __init__(self, db_helper: DatabaseHelper):
        self.db_helper = db_helper
    
        
    def get_review_by_google_id(self, google_review_id: str) -> Optional[Review]:
            """Get review by Google review ID"""
            self.cursor.execute(
                "SELECT * FROM reviews WHERE google_review_id = ?",
                (google_review_id,)
            )
            row = self.cursor.fetchone()
            if row:
                return Review(
                    id=row['id'],
                    business_id=row['business_id'],
                    reviewer_name=row['reviewer_name'],
                    rating=StarRating(row['rating']),
                    review_text=row['review_text'],
                    reviewer_email=row['reviewer_email'],
                    google_review_id=row['google_review_id'],
                    google_review_name=row['google_review_name'],
                    created_at=datetime.fromisoformat(row['created_at'])
                )
            return None
