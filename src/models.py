"""
Data models and schema for TradeReply
"""

from datetime import datetime
from typing import Optional, List
from enum import Enum


class StarRating(int, Enum):
    """Review star ratings"""
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5


class ApprovalStatus(str, Enum):
    """Status of review response approval"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALID_RESPONSE = "invalid_response"
    POSTED = "posted"
    POST_FAILED = "post_failed"


class Business:
    """Business profile"""
    def __init__(
        self,
        id: str,
        name: str,
        phone: str,
        sms_recipient: str,
        description: Optional[str] = None,
        google_location_id: Optional[str] = None,
        google_account_id: Optional[str] = None,
        google_refresh_token: Optional[str] = None,
        response_tone: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.id = id
        self.name = name
        self.phone = phone
        self.sms_recipient = sms_recipient
        self.description = description
        self.google_location_id = google_location_id
        self.google_account_id = google_account_id
        self.google_refresh_token = google_refresh_token
        self.response_tone = response_tone
        self.created_at = created_at or datetime.utcnow()


class Review:
    """Google Business Profile review"""
    def __init__(
        self,
        id: str,
        business_id: str,
        reviewer_name: str,
        rating: StarRating,
        review_text: str,
        reviewer_email: Optional[str] = None,
        google_review_id: Optional[str] = None,
        google_review_name: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ):
        self.id = id
        self.business_id = business_id
        self.reviewer_name = reviewer_name
        self.rating = rating
        self.review_text = review_text
        self.reviewer_email = reviewer_email
        self.google_review_id = google_review_id
        self.google_review_name = google_review_name
        self.created_at = created_at or datetime.utcnow()


class DraftResponse:
    """AI-generated draft response to a review"""
    def __init__(
        self,
        id: str,
        review_id: str,
        business_id: str,
        draft_text: str,
        status: str = "drafted",
        created_at: Optional[datetime] = None,
    ):
        self.id = id
        self.review_id = review_id
        self.business_id = business_id
        self.draft_text = draft_text
        self.status = status
        self.created_at = created_at or datetime.utcnow()


class PendingApproval:
    """SMS approval request sent to business owner"""
    def __init__(
        self,
        id: str,
        draft_response_id: str,
        business_id: str,
        sms_sent_at: datetime,
        status: ApprovalStatus = ApprovalStatus.PENDING,
        sms_message: Optional[str] = None,
        approval_timestamp: Optional[datetime] = None,
    ):
        self.id = id
        self.draft_response_id = draft_response_id
        self.business_id = business_id
        self.sms_sent_at = sms_sent_at
        self.status = status
        self.sms_message = sms_message
        self.approval_timestamp = approval_timestamp


class Response:
    """Final posted response"""
    def __init__(
        self,
        id: str,
        review_id: str,
        business_id: str,
        response_text: str,
        posted_at: Optional[datetime] = None,
    ):
        self.id = id
        self.review_id = review_id
        self.business_id = business_id
        self.response_text = response_text
        self.posted_at = posted_at or datetime.utcnow()
