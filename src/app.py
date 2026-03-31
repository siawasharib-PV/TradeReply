"""
TradeReply FastAPI Application
Main webhook endpoint and API for the review response system
"""

import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, Response
import os
from config import Config, get_config, ConfigError
from pydantic import BaseModel
import uvicorn

from config import Config, get_config
from db_helper import DatabaseHelper
from ai_integration import AIHandler
from sms_handler import SMSHandler
from prompts import build_sms_approval_message, build_sms_confirmation_message
from models import (
    Business,
    Review,
    DraftResponse,
    PendingApproval,
    StarRating,
    ApprovalStatus,
)

# Configuration
config = get_config()
config.validate()

# Logging setup
logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Initialize components
db = DatabaseHelper(config.DATABASE_PATH)
ai_handler = AIHandler(dry_run=config.DRY_RUN_AI)
sms_handler = SMSHandler(
    account_sid=config.TWILIO_ACCOUNT_SID,
    auth_token=config.TWILIO_AUTH_TOKEN,
    from_number=config.TWILIO_FROM_NUMBER,
    dry_run=config.DRY_RUN_SMS,
)

# FastAPI app
app = FastAPI(title="TradeReply", version="0.1.0")


# ==================== PYDANTIC MODELS ====================


class ReviewRequest(BaseModel):
    """Incoming webhook request for a new review"""

    business_id: str
    reviewer_name: str
    rating: int  # 1-5
    review_text: str
    reviewer_email: Optional[str] = None


class ApprovalResponse(BaseModel):
    """Response to an approval request"""

    approval_id: str
    approved: bool


class ManualPostAction(BaseModel):
    """Manual-assisted posting action for pilot workflow"""

    action: str  # posted | post_failed


class GoogleConnectRequest(BaseModel):
    """Request to connect Google Business Profile"""

    client_id: str
    client_secret: str
    business_id: Optional[str] = None  # If None, create new business


# ==================== LIFECYCLE ====================


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    try:
        # Set ENVIRONMENT to "production" for Railway deployment
        os.environ["ENVIRONMENT"] = "production"
        config = get_config()
        config.validate() # This will raise ConfigError if production requirements aren't met

        db.connect()
        db.init_schema()
        logger.info("Database initialized successfully")
    except ConfigError as e:
        logger.error(f"Configuration Error: {e}")
        # In production, we should gracefully exit if config is bad
        raise RuntimeError(f"Production configuration error: {e}") from e
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown"""
    try:
        db.disconnect()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database: {str(e)}")


# ==================== HEALTH CHECK ====================


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


# ==================== BUSINESS ENDPOINTS ====================


@app.post("/businesses")
async def create_business(
    name: str,
    phone: str,
    sms_recipient: str,
    description: Optional[str] = None,
    google_location_id: Optional[str] = None,
    google_account_id: Optional[str] = None,
    response_tone: Optional[str] = None,
):
    """Create a new business profile"""
    business_id = str(uuid.uuid4())
    business = Business(
        id=business_id,
        name=name,
        phone=phone,
        sms_recipient=sms_recipient,
        description=description,
        google_location_id=google_location_id,
        google_account_id=google_account_id,
        response_tone=response_tone,
    )

    if db.create_business(business):
        logger.info(f"Created business: {business_id}")
        return {"business_id": business_id, "name": name}
    else:
        raise HTTPException(status_code=400, detail="Failed to create business")


@app.get("/businesses/{business_id}")
async def get_business(business_id: str):
    """Get business details"""
    business = db.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return {
        "id": business.id,
        "name": business.name,
        "phone": business.phone,
        "sms_recipient": business.sms_recipient,
        "description": business.description,
        "google_location_id": business.google_location_id,
        "google_account_id": business.google_account_id,
        "response_tone": business.response_tone,
        "created_at": business.created_at.isoformat(),
    }


@app.get("/businesses")
async def list_businesses():
    """List all businesses"""
    businesses = db.list_businesses()
    return [
        {
            "id": b.id,
            "name": b.name,
            "phone": b.phone,
            "sms_recipient": b.sms_recipient,
            "google_location_id": b.google_location_id,
            "google_account_id": b.google_account_id,
            "response_tone": b.response_tone,
        }
        for b in businesses
    ]


# ==================== REVIEW ENDPOINTS ====================


@app.post("/reviews")
async def submit_review(review_request: ReviewRequest):
    """
    Webhook endpoint for new review submissions.
    Triggers AI draft generation and SMS approval flow.
    """
    try:
        # Validate business exists
        business = db.get_business(review_request.business_id)
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")

        # Create review record
        review_id = str(uuid.uuid4())
        review = Review(
            id=review_id,
            business_id=review_request.business_id,
            reviewer_name=review_request.reviewer_name,
            rating=StarRating(review_request.rating),
            review_text=review_request.review_text,
            reviewer_email=review_request.reviewer_email,
        )

        if not db.create_review(review):
            raise HTTPException(status_code=400, detail="Failed to create review")

        db.create_audit_event(
            event_type="review_received",
            business_id=review_request.business_id,
            review_id=review_id,
            message="Review received",
            payload={
                "reviewer_name": review_request.reviewer_name,
                "rating": review_request.rating,
            },
        )

        logger.info(f"Created review: {review_id} for business {review_request.business_id}")

        # Generate AI draft response
        draft_text = ai_handler.generate_response(review, business)
        logger.info(f"Generated draft for review {review_id}")

        # Store draft in database
        draft_id = str(uuid.uuid4())
        draft = DraftResponse(
            id=draft_id,
            review_id=review_id,
            business_id=review_request.business_id,
            draft_text=draft_text,
            status="drafted",
        )

        if not db.create_draft_response(draft):
            logger.error(f"Failed to store draft for review {review_id}")
            raise HTTPException(status_code=400, detail="Failed to store draft")

        db.create_audit_event(
            event_type="draft_created",
            business_id=review_request.business_id,
            review_id=review_id,
            draft_id=draft_id,
            message="AI draft created",
        )

        # Build and send SMS approval request
        sms_message = build_sms_approval_message(
            review_request.reviewer_name,
            StarRating(review_request.rating),
            review_request.review_text,
            draft_text,
        )

        sms_result = sms_handler.send_approval_request(
            business.sms_recipient,
            sms_message,
        )

        if not sms_result["success"]:
            logger.error(f"Failed to send SMS for review {review_id}")
            raise HTTPException(status_code=400, detail="Failed to send SMS")

        # Create pending approval record
        approval_id = str(uuid.uuid4())
        approval = PendingApproval(
            id=approval_id,
            draft_response_id=draft_id,
            business_id=review_request.business_id,
            sms_sent_at=datetime.utcnow(),
            status=ApprovalStatus.PENDING,
            sms_message=sms_message,
        )

        if not db.create_pending_approval(approval):
            logger.error(f"Failed to create approval record for review {review_id}")
            raise HTTPException(status_code=400, detail="Failed to create approval")

        db.update_draft_status(draft_id, "awaiting_approval")
        db.create_audit_event(
            event_type="sms_approval_sent",
            business_id=review_request.business_id,
            review_id=review_id,
            draft_id=draft_id,
            approval_id=approval_id,
            message="SMS approval request sent",
            payload={"sms_recipient": business.sms_recipient},
        )

        logger.info(
            f"SMS approval request sent for review {review_id} to {business.sms_recipient}"
        )

        return {
            "review_id": review_id,
            "draft_id": draft_id,
            "approval_id": approval_id,
            "status": "awaiting_approval",
            "draft": draft_text,
            "sms_sent_to": business.sms_recipient,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing review: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/reviews/{review_id}")
async def get_review(review_id: str):
    """Get review details with context"""
    context = db.get_full_review_context(review_id)
    if not context:
        raise HTTPException(status_code=404, detail="Review not found")

    review = context["review"]
    draft = context["draft"]

    return {
        "review_id": review.id,
        "reviewer_name": review.reviewer_name,
        "rating": review.rating.value,
        "review_text": review.review_text,
        "draft": {
            "id": draft.id if draft else None,
            "text": draft.draft_text if draft else None,
            "status": draft.status if draft else None,
        },
        "created_at": review.created_at.isoformat(),
    }


# ==================== APPROVAL ENDPOINTS ====================


@app.post("/approvals/{approval_id}")
async def process_approval(approval_id: str, response: ApprovalResponse):
    """
    Process an SMS approval response.
    In production, this would be triggered by webhook from Twilio.
    """
    try:
        approval = db.get_pending_approval(approval_id)
        if not approval:
            raise HTTPException(status_code=404, detail="Approval not found")

        # Update approval status
        new_status = (
            ApprovalStatus.APPROVED
            if response.approved
            else ApprovalStatus.REJECTED
        )
        db.update_approval_status(
            approval_id,
            new_status,
            datetime.utcnow(),
        )
        db.update_draft_status(
            approval.draft_response_id,
            "approved" if response.approved else "rejected",
        )
        db.create_audit_event(
            event_type="approval_processed",
            business_id=approval.business_id,
            draft_id=approval.draft_response_id,
            approval_id=approval_id,
            message=f"Approval marked {new_status.value}",
            payload={"approved": response.approved},
        )

        logger.info(f"Approval {approval_id} marked as {new_status.value}")

        return {
            "approval_id": approval_id,
            "status": new_status.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing approval: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/businesses/{business_id}/approvals")
async def get_pending_approvals(business_id: str):
    """Get pending approvals for a business"""
    business = db.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    approvals = db.get_pending_approvals_by_business(business_id)
    return [
        {
            "approval_id": a.id,
            "draft_id": a.draft_response_id,
            "status": a.status.value,
            "sms_sent_at": a.sms_sent_at.isoformat(),
            "sms_message": a.sms_message,
        }
        for a in approvals
    ]


@app.post("/businesses/{business_id}/mapping")
async def update_business_mapping(
    business_id: str,
    google_location_id: Optional[str] = None,
    google_account_id: Optional[str] = None,
    response_tone: Optional[str] = None,
):
    """Update pilot mapping fields for a business."""
    business = db.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    ok = db.update_business_mapping(
        business_id,
        google_location_id=google_location_id,
        google_account_id=google_account_id,
        response_tone=response_tone,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to update business mapping")

    updated = db.get_business(business_id)
    return {
        "business_id": updated.id,
        "google_location_id": updated.google_location_id,
        "google_account_id": updated.google_account_id,
        "response_tone": updated.response_tone,
    }


@app.get("/businesses/{business_id}/ready-to-post")
async def get_ready_to_post(business_id: str):
    """List approved responses that are ready for manual posting in the pilot flow."""
    business = db.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    drafts = db.list_drafts_by_status("approved", business_id=business_id)
    results = []
    for draft in drafts:
        review = db.get_review(draft.review_id)
        results.append(
            {
                "draft_id": draft.id,
                "review_id": draft.review_id,
                "business_id": draft.business_id,
                "status": draft.status,
                "draft_text": draft.draft_text,
                "reviewer_name": review.reviewer_name if review else None,
                "rating": review.rating.value if review else None,
                "review_text": review.review_text if review else None,
            }
        )
    return results


@app.post("/drafts/{draft_id}/manual-post")
async def manual_post_action(draft_id: str, action: ManualPostAction):
    """Manual-assisted pilot action to mark a draft as posted or post_failed."""
    draft = db.get_draft_response(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    if action.action not in {"posted", "post_failed"}:
        raise HTTPException(status_code=400, detail="action must be 'posted' or 'post_failed'")

    db.update_draft_status(draft_id, action.action)

    if action.action == "posted":
        response = Response(
            id=str(uuid.uuid4()),
            review_id=draft.review_id,
            business_id=draft.business_id,
            response_text=draft.draft_text,
            posted_at=datetime.utcnow(),
        )
        db.create_response(response)

    db.create_audit_event(
        event_type="manual_post_action",
        business_id=draft.business_id,
        review_id=draft.review_id,
        draft_id=draft_id,
        message=f"Draft manually marked {action.action}",
        payload={"action": action.action},
    )

    logger.info(f"Draft {draft_id} manually marked as {action.action}")
    return {"draft_id": draft_id, "status": action.action}


@app.post("/webhooks/twilio/inbound", response_class=PlainTextResponse)
async def twilio_inbound_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: Optional[str] = Form(None),
):
    """Handle inbound YES/NO SMS replies from Twilio for approval requests."""
    try:
        normalized_phone = From.strip()
        response_text = Body.strip()
        logger.info(
            f"Inbound Twilio SMS from {normalized_phone} sid={MessageSid or 'n/a'} body={response_text!r}"
        )

        approval = db.get_latest_pending_approval_by_phone(normalized_phone)
        if not approval:
            db.create_audit_event(
                event_type="inbound_sms_unmatched",
                message="Inbound SMS received with no matching pending approval",
                payload={"from": normalized_phone, "body": response_text, "message_sid": MessageSid},
            )
            logger.warning(f"No pending approval found for inbound SMS from {normalized_phone}")
            return "No pending approval found for this number."

        parsed = sms_handler.parse_approval_response(response_text)
        timestamp = datetime.utcnow()

        if parsed is None:
            db.update_approval_status(
                approval.id,
                ApprovalStatus.INVALID_RESPONSE,
                timestamp,
            )
            db.update_draft_status(approval.draft_response_id, "invalid_response")
            db.create_audit_event(
                event_type="inbound_sms_invalid",
                business_id=approval.business_id,
                draft_id=approval.draft_response_id,
                approval_id=approval.id,
                message="Inbound SMS reply not understood",
                payload={"from": normalized_phone, "body": response_text, "message_sid": MessageSid},
            )
            logger.info(f"Approval {approval.id} marked invalid_response from inbound SMS")
            return "Reply not understood. Please reply YES to approve or NO to reject."

        new_status = ApprovalStatus.APPROVED if parsed else ApprovalStatus.REJECTED
        db.update_approval_status(approval.id, new_status, timestamp)
        db.update_draft_status(
            approval.draft_response_id,
            "approved" if parsed else "rejected",
        )
        db.create_audit_event(
            event_type="inbound_sms_processed",
            business_id=approval.business_id,
            draft_id=approval.draft_response_id,
            approval_id=approval.id,
            message=f"Inbound SMS processed as {new_status.value}",
            payload={"from": normalized_phone, "body": response_text, "message_sid": MessageSid},
        )
        logger.info(f"Approval {approval.id} updated to {new_status.value} via inbound Twilio SMS")

        # Send confirmation SMS to business owner
        try:
            draft = db.get_draft_response(approval.draft_response_id)
            if draft:
                review = db.get_review(draft.review_id)
                if review:
                    confirmation_message = build_sms_confirmation_message(
                        approved=parsed,
                        reviewer_name=review.reviewer_name,
                        rating=review.rating,
                    )
                    sms_handler.send_sms(
                        recipient_phone=normalized_phone,
                        message=confirmation_message,
                    )
                    logger.info(f"Confirmation SMS sent to {normalized_phone}")
        except Exception as confirm_error:
            logger.warning(f"Failed to send confirmation SMS: {confirm_error}")

        if parsed:
            return "Approved. TradeReply recorded your YES response."
        return "Rejected. TradeReply recorded your NO response."

    except Exception as e:
        logger.error(f"Error handling inbound Twilio webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== GOOGLE OAUTH ENDPOINTS ====================


@app.get("/google/auth")
async def google_auth(business_id: Optional[str] = None):
    """Start Google OAuth flow"""
    try:
        from google_client import GoogleBusinessClient
        
        # Use platform credentials if available, otherwise need business-specific
        if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
            raise HTTPException(
                status_code=400,
                detail="Google OAuth not configured. Please provide client_id and client_secret via /google/connect"
            )
        
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
        )
        
        # Include business_id in state if provided
        state = f"business_id={business_id}" if business_id else None
        
        auth_url = client.get_auth_url(state=state)
        
        db.create_audit_event(
            event_type="google_oauth_started",
            business_id=business_id,
            message="Google OAuth flow initiated",
        )
        
        return {"auth_url": auth_url}
        
    except Exception as e:
        logger.error(f"Failed to start Google OAuth: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/google/connect")
async def google_connect(request: GoogleConnectRequest):
    """Connect Google Business Profile with provided credentials"""
    try:
        from google_client import GoogleBusinessClient
        
        client = GoogleBusinessClient(
            client_id=request.client_id,
            client_secret=request.client_secret,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
        )
        
        auth_url = client.get_auth_url(state=f"business_id={request.business_id}" if request.business_id else None)
        
        db.create_audit_event(
            event_type="google_connect_initiated",
            business_id=request.business_id,
            message="Google connection initiated with custom credentials",
        )
        
        return {"auth_url": auth_url, "status": "redirect_to_google"}
        
    except Exception as e:
        logger.error(f"Failed to connect Google: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/google/callback")
async def google_callback(code: str, state: Optional[str] = None, error: Optional[str] = None):
    """Handle Google OAuth callback"""
    try:
        from google_client import GoogleBusinessClient
        
        if error:
            logger.error(f"Google OAuth error: {error}")
            return HTMLResponse(
                content=f"<html><body><h1>Authorization Failed</h1><p>Error: {error}</p></body></html>",
                status_code=400
            )
        
        # Parse business_id from state
        business_id = None
        if state and state.startswith("business_id="):
            business_id = state.split("=")[1]
        
        # Exchange code for tokens
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
        )
        
        tokens = client.exchange_code(code)
        
        # Store refresh token in business record
        if business_id:
            business = db.get_business(business_id)
            if business:
                db.update_business_mapping(
                    business_id,
                    google_refresh_token=tokens["refresh_token"],
                )
                logger.info(f"Stored Google refresh token for business {business_id}")
        
        db.create_audit_event(
            event_type="google_oauth_completed",
            business_id=business_id,
            message="Google OAuth completed successfully",
            payload={"has_refresh_token": bool(tokens.get("refresh_token"))},
        )
        
        # Show success page
        return HTMLResponse(
            content="""
            <html>
            <head>
                <title>TradeReply - Google Connected</title>
                <style>
                    body { font-family: -apple-system, sans-serif; background: #0f172a; color: white; text-align: center; padding: 60px; }
                    .card { background: #1e293b; padding: 40px; border-radius: 12px; max-width: 500px; margin: 0 auto; }
                    h1 { color: #22c55e; }
                    .muted { color: #94a3b8; }
                </style>
            </head>
            <body>
                <div class="card">
                    <h1>✅ Connected!</h1>
                    <p>Your Google Business Profile is now connected to TradeReply.</p>
                    <p class="muted">You can close this window and return to TradeReply.</p>
                </div>
            </body>
            </html>
            """
        )
        
    except Exception as e:
        logger.error(f"Failed to handle Google callback: {e}")
        return HTMLResponse(
            content=f"<html><body><h1>Error</h1><p>{str(e)}</p></body></html>",
            status_code=500
        )


@app.post("/businesses/{business_id}/sync-reviews")
async def sync_google_reviews(business_id: str):
    """Sync reviews from Google Business Profile for a business"""
    try:
        from google_client import GoogleBusinessClient, parse_google_review
        
        business = db.get_business(business_id)
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
        
        if not business.google_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Google not connected. Complete OAuth flow first."
            )
        
        if not business.google_location_id:
            raise HTTPException(
                status_code=400,
                detail="Google location ID not set. Please configure location."
            )
        
        # Initialize Google client with stored refresh token
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
            refresh_token=business.google_refresh_token,
        )
        
        # Fetch reviews
        result = client.get_reviews(business.google_location_id)
        reviews = result.get("reviews", [])
        
        new_reviews = []
        for google_review in reviews:
            parsed = parse_google_review(google_review)
            
            # Check if we already have this review
            existing = db.get_review_by_google_id(parsed["google_review_id"])
            if existing:
                continue
            
            # Create new review record
            review_id = str(uuid.uuid4())
            review = Review(
                id=review_id,
                business_id=business_id,
                reviewer_name=parsed["reviewer_name"],
                rating=StarRating(parsed["rating"]),
                review_text=parsed["review_text"],
                google_review_id=parsed["google_review_id"],
                google_review_name=parsed["google_review_name"],
            )
            
            if db.create_review(review):
                new_reviews.append(parsed)
                
                # Generate AI draft and send SMS approval
                draft_text = ai_handler.generate_response(review, business)
                
                draft_id = str(uuid.uuid4())
                draft = DraftResponse(
                    id=draft_id,
                    review_id=review_id,
                    business_id=business_id,
                    draft_text=draft_text,
                    status="drafted",
                )
                db.create_draft_response(draft)
                
                # Send SMS for approval
                sms_message = build_sms_approval_message(
                    parsed["reviewer_name"],
                    StarRating(parsed["rating"]),
                    parsed["review_text"],
                    draft_text,
                )
                
                sms_handler.send_approval_request(business.sms_recipient, sms_message)
                
                # Create pending approval
                approval_id = str(uuid.uuid4())
                approval = PendingApproval(
                    id=approval_id,
                    draft_response_id=draft_id,
                    business_id=business_id,
                    sms_sent_at=datetime.utcnow(),
                    status=ApprovalStatus.PENDING,
                    sms_message=sms_message,
                )
                db.create_pending_approval(approval)
        
        db.create_audit_event(
            event_type="google_reviews_synced",
            business_id=business_id,
            message=f"Synced {len(new_reviews)} new reviews from Google",
            payload={"total_reviews": len(reviews), "new_reviews": len(new_reviews)},
        )
        
        return {
            "status": "synced",
            "total_reviews": len(reviews),
            "new_reviews": len(new_reviews),
            "reviews": new_reviews,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync Google reviews: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== DEBUG ENDPOINTS ====================


@app.get("/audit-events")
async def get_audit_events(limit: int = 100, business_id: Optional[str] = None):
    """List recent audit events for traceability."""
    return db.list_audit_events(limit=limit, business_id=business_id)


@app.get("/ops/dashboard", response_class=HTMLResponse)
async def ops_dashboard():
    """Minimal operator dashboard for pilot operations."""
    businesses = db.list_businesses()
    pending = []
    ready = []
    posted = []
    failed = []

    for business in businesses:
        pending.extend([
            {"business": business.name, "approval_id": a.id, "sms_sent_at": a.sms_sent_at.isoformat(), "status": a.status.value}
            for a in db.get_pending_approvals_by_business(business.id)
        ])
        ready.extend([
            {"business": business.name, "draft_id": d.id, "review_id": d.review_id, "status": d.status, "text": d.draft_text}
            for d in db.list_drafts_by_status("approved", business_id=business.id)
        ])
        failed.extend([
            {"business": business.name, "draft_id": d.id, "review_id": d.review_id, "status": d.status, "text": d.draft_text}
            for d in db.list_drafts_by_status("post_failed", business_id=business.id)
        ])
        posted.extend([
            {"business": business.name, "review_id": r.review_id, "posted_at": r.posted_at.isoformat(), "text": r.response_text}
            for r in db.get_responses_by_business(business.id)
        ])

    def render_list(items, kind):
        if not items:
            return '<div class="muted">None</div>'
        rows=[]
        for x in items:
            if kind=='pending':
                rows.append(f"<li><strong>{x['business']}</strong> • approval {x['approval_id']} • {x['sms_sent_at']}</li>")
            elif kind=='ready':
                rows.append(f"<li><strong>{x['business']}</strong> • draft {x['draft_id']}<br><span class='muted'>{x['text']}</span></li>")
            elif kind=='posted':
                rows.append(f"<li><strong>{x['business']}</strong> • {x['posted_at']}</li>")
            elif kind=='failed':
                rows.append(f"<li><strong>{x['business']}</strong> • draft {x['draft_id']}<br><span class='muted'>{x['text']}</span></li>")
        return '<ul>' + ''.join(rows) + '</ul>'

    html = f"""
    <html>
    <head>
      <title>TradeReply Ops Dashboard</title>
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background:#0f172a; color:#e2e8f0; margin:0; padding:24px; }}
        .grid {{ display:grid; gap:16px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); margin-bottom:20px; }}
        .card {{ background:#111827; border:1px solid #334155; border-radius:12px; padding:16px; }}
        h1,h2,h3 {{ margin-top:0; }}
        .muted {{ color:#94a3b8; }}
        ul {{ padding-left:18px; }}
        code {{ color:#93c5fd; }}
      </style>
    </head>
    <body>
      <h1>TradeReply Ops Dashboard</h1>
      <div class='muted'>Pilot operations view for pending approvals, ready-to-post replies, posted responses, and failures.</div>
      <div class='grid'>
        <div class='card'><h3>Businesses</h3><div>{len(businesses)}</div></div>
        <div class='card'><h3>Pending approvals</h3><div>{len(pending)}</div></div>
        <div class='card'><h3>Ready to post</h3><div>{len(ready)}</div></div>
        <div class='card'><h3>Post failed</h3><div>{len(failed)}</div></div>
      </div>
      <div class='grid'>
        <div class='card'><h3>Pending approvals</h3>{render_list(pending, 'pending')}</div>
        <div class='card'><h3>Ready to post</h3>{render_list(ready, 'ready')}</div>
      </div>
      <div class='grid'>
        <div class='card'><h3>Posted responses</h3>{render_list(posted, 'posted')}</div>
        <div class='card'><h3>Failed posts</h3>{render_list(failed, 'failed')}</div>
      </div>
      <div class='card'>
        <h3>Useful endpoints</h3>
        <ul>
          <li><code>GET /businesses/{{business_id}}/ready-to-post</code></li>
          <li><code>POST /drafts/{{draft_id}}/manual-post</code> with <code>{{"action":"posted"}}</code></li>
          <li><code>POST /drafts/{{draft_id}}/manual-post</code> with <code>{{"action":"post_failed"}}</code></li>
        </ul>
      </div>
    </body>
    </html>
    """
    return html


@app.get("/debug/reviews/{business_id}")
async def debug_business_reviews(business_id: str):
    """Debug endpoint: Get all reviews for a business"""
    reviews = db.get_reviews_by_business(business_id)
    return [
        {
            "id": r.id,
            "reviewer_name": r.reviewer_name,
            "rating": r.rating.value,
            "text": r.review_text[:100] + ("..." if len(r.review_text) > 100 else ""),
            "created_at": r.created_at.isoformat(),
        }
        for r in reviews
    ]


@app.get("/debug/database")
async def debug_database_status():
    """Debug endpoint: Database status"""
    try:
        businesses = db.list_businesses()
        return {
            "database": config.DATABASE_PATH,
            "connected": True,
            "business_count": len(businesses),
            "businesses": [b.name for b in businesses],
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def main():
    """Run the FastAPI application"""
    logger.info(
        f"Starting TradeReply API (debug={config.DEBUG}, dry_run_sms={config.DRY_RUN_SMS})"
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT, reload=config.DEBUG)


if __name__ == "__main__":
    main()
