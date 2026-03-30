"""
SQLite database helper for TradeReply
Handles all CRUD operations for businesses, reviews, drafts, approvals, and responses
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from models import (
    Business,
    Review,
    DraftResponse,
    PendingApproval,
    Response,
    StarRating,
    ApprovalStatus,
)


class DatabaseHelper:
    """SQLite database handler"""

    def __init__(self, db_path: str = "tradereply.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = None
        self.cursor = None

    def connect(self):
        """Open database connection"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

    def disconnect(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def init_schema(self):
        """Create all tables"""
        if not self.conn:
            self.connect()

        schema = """
        -- Businesses table
        CREATE TABLE IF NOT EXISTS businesses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            sms_recipient TEXT NOT NULL,
            description TEXT,
            google_location_id TEXT,
            google_account_id TEXT,
            response_tone TEXT,
            created_at TEXT NOT NULL
        );

        -- Reviews table
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL,
            reviewer_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            review_text TEXT NOT NULL,
            reviewer_email TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        -- Draft responses table
        CREATE TABLE IF NOT EXISTS draft_responses (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            draft_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'drafted',
            created_at TEXT NOT NULL,
            FOREIGN KEY (review_id) REFERENCES reviews(id),
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        -- Pending approvals table
        CREATE TABLE IF NOT EXISTS pending_approvals (
            id TEXT PRIMARY KEY,
            draft_response_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            sms_sent_at TEXT NOT NULL,
            status TEXT NOT NULL,
            sms_message TEXT,
            approval_timestamp TEXT,
            FOREIGN KEY (draft_response_id) REFERENCES draft_responses(id),
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        -- Responses table
        CREATE TABLE IF NOT EXISTS responses (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL,
            business_id TEXT NOT NULL,
            response_text TEXT NOT NULL,
            posted_at TEXT NOT NULL,
            FOREIGN KEY (review_id) REFERENCES reviews(id),
            FOREIGN KEY (business_id) REFERENCES businesses(id)
        );

        -- Audit events table
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            business_id TEXT,
            review_id TEXT,
            draft_id TEXT,
            approval_id TEXT,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        );

        -- Indices for common queries
        CREATE INDEX IF NOT EXISTS idx_reviews_business ON reviews(business_id);
        CREATE INDEX IF NOT EXISTS idx_draft_responses_review ON draft_responses(review_id);
        CREATE INDEX IF NOT EXISTS idx_pending_approvals_business ON pending_approvals(business_id);
        CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);
        CREATE INDEX IF NOT EXISTS idx_responses_review ON responses(review_id);
        CREATE INDEX IF NOT EXISTS idx_audit_events_business ON audit_events(business_id);
        CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit_events(event_type);
        """

        for statement in schema.split(";"):
            statement = statement.strip()
            if statement:
                self.cursor.execute(statement)

        # Lightweight migrations for older local DBs
        self.cursor.execute("PRAGMA table_info(draft_responses)")
        draft_cols = {row[1] for row in self.cursor.fetchall()}
        if "status" not in draft_cols:
            self.cursor.execute(
                "ALTER TABLE draft_responses ADD COLUMN status TEXT NOT NULL DEFAULT 'drafted'"
            )

        self.cursor.execute("PRAGMA table_info(businesses)")
        business_cols = {row[1] for row in self.cursor.fetchall()}
        if "google_location_id" not in business_cols:
            self.cursor.execute("ALTER TABLE businesses ADD COLUMN google_location_id TEXT")
        if "google_account_id" not in business_cols:
            self.cursor.execute("ALTER TABLE businesses ADD COLUMN google_account_id TEXT")
        if "response_tone" not in business_cols:
            self.cursor.execute("ALTER TABLE businesses ADD COLUMN response_tone TEXT")

        self.conn.commit()

    # ==================== BUSINESS OPERATIONS ====================

    def create_business(self, business: Business) -> bool:
        """Create a new business"""
        try:
            self.cursor.execute(
                """
                INSERT INTO businesses (id, name, phone, sms_recipient, description, google_location_id, google_account_id, response_tone, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    business.id,
                    business.name,
                    business.phone,
                    business.sms_recipient,
                    business.description,
                    business.google_location_id,
                    business.google_account_id,
                    business.response_tone,
                    business.created_at.isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_business(self, business_id: str) -> Optional[Business]:
        """Retrieve a business by ID"""
        self.cursor.execute("SELECT * FROM businesses WHERE id = ?", (business_id,))
        row = self.cursor.fetchone()
        if row:
            return Business(
                id=row["id"],
                name=row["name"],
                phone=row["phone"],
                sms_recipient=row["sms_recipient"],
                description=row["description"],
                google_location_id=row["google_location_id"] if "google_location_id" in row.keys() else None,
                google_account_id=row["google_account_id"] if "google_account_id" in row.keys() else None,
                response_tone=row["response_tone"] if "response_tone" in row.keys() else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        return None

    def list_businesses(self) -> List[Business]:
        """List all businesses"""
        self.cursor.execute("SELECT * FROM businesses ORDER BY created_at DESC")
        return [
            Business(
                id=row["id"],
                name=row["name"],
                phone=row["phone"],
                sms_recipient=row["sms_recipient"],
                description=row["description"],
                google_location_id=row["google_location_id"] if "google_location_id" in row.keys() else None,
                google_account_id=row["google_account_id"] if "google_account_id" in row.keys() else None,
                response_tone=row["response_tone"] if "response_tone" in row.keys() else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in self.cursor.fetchall()
        ]

    # ==================== REVIEW OPERATIONS ====================

    def create_review(self, review: Review) -> bool:
        """Create a new review"""
        try:
            self.cursor.execute(
                """
                INSERT INTO reviews (id, business_id, reviewer_name, rating, review_text, reviewer_email, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.id,
                    review.business_id,
                    review.reviewer_name,
                    review.rating.value,
                    review.review_text,
                    review.reviewer_email,
                    review.created_at.isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_review(self, review_id: str) -> Optional[Review]:
        """Retrieve a review by ID"""
        self.cursor.execute("SELECT * FROM reviews WHERE id = ?", (review_id,))
        row = self.cursor.fetchone()
        if row:
            return Review(
                id=row["id"],
                business_id=row["business_id"],
                reviewer_name=row["reviewer_name"],
                rating=StarRating(row["rating"]),
                review_text=row["review_text"],
                reviewer_email=row["reviewer_email"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        return None

    def get_reviews_by_business(self, business_id: str) -> List[Review]:
        """Get all reviews for a business"""
        self.cursor.execute(
            "SELECT * FROM reviews WHERE business_id = ? ORDER BY created_at DESC",
            (business_id,),
        )
        return [
            Review(
                id=row["id"],
                business_id=row["business_id"],
                reviewer_name=row["reviewer_name"],
                rating=StarRating(row["rating"]),
                review_text=row["review_text"],
                reviewer_email=row["reviewer_email"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in self.cursor.fetchall()
        ]

    # ==================== DRAFT RESPONSE OPERATIONS ====================

    def create_draft_response(self, draft: DraftResponse) -> bool:
        """Create a new draft response"""
        try:
            self.cursor.execute(
                """
                INSERT INTO draft_responses (id, review_id, business_id, draft_text, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.id,
                    draft.review_id,
                    draft.business_id,
                    draft.draft_text,
                    draft.status,
                    draft.created_at.isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_draft_response(self, draft_id: str) -> Optional[DraftResponse]:
        """Retrieve a draft response by ID"""
        self.cursor.execute(
            "SELECT * FROM draft_responses WHERE id = ?", (draft_id,)
        )
        row = self.cursor.fetchone()
        if row:
            return DraftResponse(
                id=row["id"],
                review_id=row["review_id"],
                business_id=row["business_id"],
                draft_text=row["draft_text"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        return None

    def get_draft_by_review(self, review_id: str) -> Optional[DraftResponse]:
        """Get draft response for a specific review"""
        self.cursor.execute(
            "SELECT * FROM draft_responses WHERE review_id = ?", (review_id,)
        )
        row = self.cursor.fetchone()
        if row:
            return DraftResponse(
                id=row["id"],
                review_id=row["review_id"],
                business_id=row["business_id"],
                draft_text=row["draft_text"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        return None

    def update_draft_status(self, draft_id: str, status: str) -> bool:
        """Update lifecycle status for a draft response."""
        try:
            self.cursor.execute(
                "UPDATE draft_responses SET status = ? WHERE id = ?",
                (status, draft_id),
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    # ==================== PENDING APPROVAL OPERATIONS ====================

    def create_pending_approval(self, approval: PendingApproval) -> bool:
        """Create a new pending approval request"""
        try:
            self.cursor.execute(
                """
                INSERT INTO pending_approvals 
                (id, draft_response_id, business_id, sms_sent_at, status, sms_message, approval_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.draft_response_id,
                    approval.business_id,
                    approval.sms_sent_at.isoformat(),
                    approval.status.value,
                    approval.sms_message,
                    approval.approval_timestamp.isoformat()
                    if approval.approval_timestamp
                    else None,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_pending_approval(self, approval_id: str) -> Optional[PendingApproval]:
        """Retrieve a pending approval by ID"""
        self.cursor.execute(
            "SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)
        )
        row = self.cursor.fetchone()
        if row:
            return PendingApproval(
                id=row["id"],
                draft_response_id=row["draft_response_id"],
                business_id=row["business_id"],
                sms_sent_at=datetime.fromisoformat(row["sms_sent_at"]),
                status=ApprovalStatus(row["status"]),
                sms_message=row["sms_message"],
                approval_timestamp=datetime.fromisoformat(row["approval_timestamp"])
                if row["approval_timestamp"]
                else None,
            )
        return None

    def get_pending_approvals_by_business(
        self, business_id: str
    ) -> List[PendingApproval]:
        """Get all pending approvals for a business"""
        self.cursor.execute(
            "SELECT * FROM pending_approvals WHERE business_id = ? AND status = ? ORDER BY sms_sent_at DESC",
            (business_id, ApprovalStatus.PENDING.value),
        )
        return [
            PendingApproval(
                id=row["id"],
                draft_response_id=row["draft_response_id"],
                business_id=row["business_id"],
                sms_sent_at=datetime.fromisoformat(row["sms_sent_at"]),
                status=ApprovalStatus(row["status"]),
                sms_message=row["sms_message"],
                approval_timestamp=datetime.fromisoformat(row["approval_timestamp"])
                if row["approval_timestamp"]
                else None,
            )
            for row in self.cursor.fetchall()
        ]

    def get_business_by_sms_recipient(self, sms_recipient: str) -> Optional[Business]:
        """Find business by SMS recipient phone number."""
        self.cursor.execute(
            "SELECT * FROM businesses WHERE sms_recipient = ? LIMIT 1",
            (sms_recipient,),
        )
        row = self.cursor.fetchone()
        if row:
            return Business(
                id=row["id"],
                name=row["name"],
                phone=row["phone"],
                sms_recipient=row["sms_recipient"],
                description=row["description"],
                google_location_id=row["google_location_id"] if "google_location_id" in row.keys() else None,
                google_account_id=row["google_account_id"] if "google_account_id" in row.keys() else None,
                response_tone=row["response_tone"] if "response_tone" in row.keys() else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            )
        return None

    def get_latest_pending_approval_by_phone(self, sms_recipient: str) -> Optional[PendingApproval]:
        """Get the most recent pending approval for a business tied to an SMS recipient."""
        business = self.get_business_by_sms_recipient(sms_recipient)
        if not business:
            return None
        approvals = self.get_pending_approvals_by_business(business.id)
        return approvals[0] if approvals else None

    def update_business_mapping(
        self,
        business_id: str,
        google_location_id: Optional[str] = None,
        google_account_id: Optional[str] = None,
        response_tone: Optional[str] = None,
    ) -> bool:
        """Update pilot mapping fields for a business."""
        try:
            self.cursor.execute(
                """
                UPDATE businesses
                SET google_location_id = COALESCE(?, google_location_id),
                    google_account_id = COALESCE(?, google_account_id),
                    response_tone = COALESCE(?, response_tone)
                WHERE id = ?
                """,
                (google_location_id, google_account_id, response_tone, business_id),
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    def update_approval_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
        approval_timestamp: Optional[datetime] = None,
    ) -> bool:
        """Update the status of a pending approval"""
        try:
            if approval_timestamp:
                self.cursor.execute(
                    """
                    UPDATE pending_approvals
                    SET status = ?, approval_timestamp = ?
                    WHERE id = ?
                    """,
                    (
                        status.value,
                        approval_timestamp.isoformat(),
                        approval_id,
                    ),
                )
            else:
                self.cursor.execute(
                    "UPDATE pending_approvals SET status = ? WHERE id = ?",
                    (status.value, approval_id),
                )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    # ==================== RESPONSE OPERATIONS ====================

    def create_response(self, response: Response) -> bool:
        """Create a new posted response"""
        try:
            self.cursor.execute(
                """
                INSERT INTO responses (id, review_id, business_id, response_text, posted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    response.id,
                    response.review_id,
                    response.business_id,
                    response.response_text,
                    response.posted_at.isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_responses_by_business(self, business_id: str) -> List[Response]:
        """Get all posted responses for a business"""
        self.cursor.execute(
            "SELECT * FROM responses WHERE business_id = ? ORDER BY posted_at DESC",
            (business_id,),
        )
        return [
            Response(
                id=row["id"],
                review_id=row["review_id"],
                business_id=row["business_id"],
                response_text=row["response_text"],
                posted_at=datetime.fromisoformat(row["posted_at"]),
            )
            for row in self.cursor.fetchall()
        ]

    def list_drafts_by_status(self, status: str, business_id: Optional[str] = None) -> List[DraftResponse]:
        """List draft responses by lifecycle status, optionally filtered by business."""
        if business_id:
            self.cursor.execute(
                "SELECT * FROM draft_responses WHERE status = ? AND business_id = ? ORDER BY created_at DESC",
                (status, business_id),
            )
        else:
            self.cursor.execute(
                "SELECT * FROM draft_responses WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        rows = self.cursor.fetchall()
        return [
            DraftResponse(
                id=row["id"],
                review_id=row["review_id"],
                business_id=row["business_id"],
                draft_text=row["draft_text"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    # ==================== AUDIT EVENT OPERATIONS ====================

    def create_audit_event(
        self,
        event_type: str,
        business_id: Optional[str] = None,
        review_id: Optional[str] = None,
        draft_id: Optional[str] = None,
        approval_id: Optional[str] = None,
        message: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> bool:
        """Persist an audit event for pilot traceability."""
        try:
            self.cursor.execute(
                """
                INSERT INTO audit_events (id, event_type, business_id, review_id, draft_id, approval_id, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(__import__('uuid').uuid4()),
                    event_type,
                    business_id,
                    review_id,
                    draft_id,
                    approval_id,
                    message,
                    json.dumps(payload or {}),
                    datetime.utcnow().isoformat(),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.Error:
            return False

    def list_audit_events(self, limit: int = 100, business_id: Optional[str] = None) -> List[dict]:
        """List recent audit events, optionally scoped to one business."""
        if business_id:
            self.cursor.execute(
                "SELECT * FROM audit_events WHERE business_id = ? ORDER BY created_at DESC LIMIT ?",
                (business_id, limit),
            )
        else:
            self.cursor.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = self.cursor.fetchall()
        return [
            {
                'id': row['id'],
                'event_type': row['event_type'],
                'business_id': row['business_id'],
                'review_id': row['review_id'],
                'draft_id': row['draft_id'],
                'approval_id': row['approval_id'],
                'message': row['message'],
                'payload': json.loads(row['payload_json']) if row['payload_json'] else {},
                'created_at': row['created_at'],
            }
            for row in rows
        ]

    # ==================== UTILITY ====================

    def get_full_review_context(self, review_id: str) -> Optional[dict]:
        """Get complete context for a review (review + business + draft)"""
        review = self.get_review(review_id)
        if not review:
            return None

        business = self.get_business(review.business_id)
        draft = self.get_draft_by_review(review_id)

        return {
            "review": review,
            "business": business,
            "draft": draft,
        }
