"""
TradeReply FastAPI Application
Main webhook endpoint and API for the review response system
"""

import logging
import uuid
import json
import base64
import hmac
import hashlib
import time
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import PlainTextResponse, HTMLResponse, Response, RedirectResponse
import os
from config import Config, get_config
from config import ConfigError
from pydantic import BaseModel
import uvicorn

from db_helper import DatabaseHelper
from ai_integration import AIHandler
from sms_handler import SMSHandler
from stripe_handler import StripeHandler, PRICING_PLANS
from payment_routes import router as payment_router
from prompts import build_sms_approval_message, build_sms_confirmation_message
from models import (
    Business,
    Review,
    DraftResponse,
    PendingApproval,
    Response as StoredResponse,
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


def _approval_edit_url(approval_id: str) -> str:
    token = _generate_approval_token(approval_id)
    return f"{config.public_base_url()}/approvals/edit?token={token}"


def _urlsafe_b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _urlsafe_b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _generate_approval_token(approval_id: str) -> str:
    expires_at = int(time.time()) + (config.EDIT_LINK_TTL_HOURS * 3600)
    payload = {"approval_id": approval_id, "exp": expires_at}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64 = _urlsafe_b64encode(payload_bytes)
    signature = hmac.new(
        config.edit_link_signing_secret().encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_urlsafe_b64encode(signature)}"


def _verify_approval_token(token: str) -> str:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid approval token")

    expected_signature = hmac.new(
        config.edit_link_signing_secret().encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).digest()
    provided_signature = _urlsafe_b64decode(signature_b64)
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=400, detail="Approval token signature is invalid")

    try:
        payload = json.loads(_urlsafe_b64decode(payload_b64).decode())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Approval token payload is invalid") from exc

    approval_id = payload.get("approval_id")
    expires_at = payload.get("exp")
    if not approval_id or not isinstance(expires_at, int):
        raise HTTPException(status_code=400, detail="Approval token payload is incomplete")
    if expires_at < int(time.time()):
        raise HTTPException(status_code=400, detail="Approval token has expired")
    return approval_id


# ==================== LIFECYCLE ====================


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup and start background review sync"""
    try:
        db.connect()
        db.init_schema()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
    
    # Start background review sync every 5 minutes
    import asyncio
    async def periodic_sync():
        await asyncio.sleep(60)  # Wait 1 min for app to fully start
        while True:
            try:
                businesses = db.list_businesses()
                google_businesses = [b for b in businesses if b.google_refresh_token]
                if google_businesses:
                    logger.info(f"[SYNC] Checking {len(google_businesses)} connected businesses...")
                    # Sync inline to avoid HTTP self-call issues
                    for business in google_businesses:
                        try:
                            from google_client import GoogleBusinessClient, parse_google_review
                            client = GoogleBusinessClient(
                                client_id=config.GOOGLE_CLIENT_ID,
                                client_secret=config.GOOGLE_CLIENT_SECRET,
                                redirect_uri=config.GOOGLE_REDIRECT_URI,
                                refresh_token=business.google_refresh_token,
                            )
                            location_id = business.google_location_id
                            if not location_id:
                                try:
                                    accounts = client.get_accounts()
                                    if accounts:
                                        locations = client.get_locations(accounts[0].get("name", ""))
                                        if locations:
                                            location_id = locations[0].get("name")
                                            db.update_business_mapping(business.id, google_location_id=location_id)
                                except Exception:
                                    pass
                            if not location_id:
                                continue
                            result = client.get_reviews(location_id)
                            for gr in result.get("reviews", []):
                                parsed = parse_google_review(gr)
                                if parsed.get("has_reply") or db.get_review_by_google_id(parsed["google_review_id"]):
                                    continue
                                rid = str(uuid.uuid4())
                                rev = Review(id=rid, business_id=business.id,
                                    reviewer_name=parsed["reviewer_name"],
                                    rating=StarRating(parsed["rating"]),
                                    review_text=parsed["review_text"],
                                    google_review_id=parsed["google_review_id"],
                                    google_review_name=parsed["google_review_name"])
                                db.create_review(rev)
                                try:
                                    _create_draft_and_send_approval(rev, business)
                                except HTTPException as flow_error:
                                    logger.error(
                                        f"[SYNC] Failed to process review {rev.id} for {business.name}: "
                                        f"{flow_error.detail}"
                                    )
                                logger.info(f"[SYNC] New review: {parsed['reviewer_name']} for {business.name}")
                        except Exception as biz_err:
                            logger.error(f"[SYNC] Error syncing {business.name}: {biz_err}")
                else:
                    logger.debug("[SYNC] No Google-connected businesses")
            except Exception as e:
                logger.error(f"[SYNC] Periodic sync error: {e}")
            await asyncio.sleep(300)  # Every 5 minutes
    
    asyncio.create_task(periodic_sync())


def _create_draft_and_send_approval(review: Review, business: Business) -> dict:
    """Generate an AI draft, send the SMS approval request, and persist tracking records."""
    draft_text = ai_handler.generate_response(review, business)
    logger.info(f"Generated draft for review {review.id}")

    draft_id = str(uuid.uuid4())
    draft = DraftResponse(
        id=draft_id,
        review_id=review.id,
        business_id=business.id,
        draft_text=draft_text,
        status="drafted",
    )

    if not db.create_draft_response(draft):
        logger.error(f"Failed to store draft for review {review.id}")
        raise HTTPException(status_code=400, detail="Failed to store draft")

    db.create_audit_event(
        event_type="draft_created",
        business_id=business.id,
        review_id=review.id,
        draft_id=draft_id,
        message="AI draft created",
    )

    approval_id = str(uuid.uuid4())

    sms_message = build_sms_approval_message(
        review.reviewer_name,
        review.rating,
        review.review_text,
        draft_text,
        approval_id=approval_id,
        edit_url=_approval_edit_url(approval_id),
    )

    sms_result = sms_handler.send_approval_request(
        business.sms_recipient,
        sms_message,
    )

    if not sms_result["success"]:
        db.update_draft_status(draft_id, "sms_failed")
        db.create_audit_event(
            event_type="sms_approval_failed",
            business_id=business.id,
            review_id=review.id,
            draft_id=draft_id,
            message="Failed to send SMS approval request",
            payload=sms_result,
        )
        logger.error(f"Failed to send SMS for review {review.id}")
        raise HTTPException(status_code=502, detail="Failed to send SMS")

    approval = PendingApproval(
        id=approval_id,
        draft_response_id=draft_id,
        business_id=business.id,
        sms_sent_at=datetime.utcnow(),
        status=ApprovalStatus.PENDING,
        sms_message=sms_message,
    )

    if not db.create_pending_approval(approval):
        logger.error(f"Failed to create approval record for review {review.id}")
        raise HTTPException(status_code=400, detail="Failed to create approval")

    db.update_draft_status(draft_id, "awaiting_approval")
    db.create_audit_event(
        event_type="sms_approval_sent",
        business_id=business.id,
        review_id=review.id,
        draft_id=draft_id,
        approval_id=approval_id,
        message="SMS approval request sent",
        payload={"sms_recipient": business.sms_recipient},
    )

    logger.info(
        f"SMS approval request sent for review {review.id} to {business.sms_recipient}"
    )

    return {
        "draft_id": draft_id,
        "approval_id": approval_id,
        "draft_text": draft_text,
        "sms_sent_to": business.sms_recipient,
    }


def _attempt_auto_post_for_approval(approval: PendingApproval) -> dict:
    """Attempt to post an approved draft directly to Google and persist result."""
    draft = db.get_draft_response(approval.draft_response_id)
    review = db.get_review(draft.review_id) if draft else None
    business = db.get_business(approval.business_id) if approval.business_id else None

    missing = []
    if not draft:
        missing.append("draft")
    if not review:
        missing.append("review")
    if not business:
        missing.append("business")
    if review and not review.google_review_name:
        missing.append("google_review_name")
    if business and not business.google_refresh_token:
        missing.append("google_refresh_token")

    if missing:
        logger.info(f"Skipping auto-post for approval {approval.id}: missing {', '.join(missing)}")
        return {"success": False, "reason": "missing_prerequisites", "missing": missing}

    try:
        from google_client import GoogleBusinessClient

        google_client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
            refresh_token=business.google_refresh_token,
        )

        result = google_client.post_reply(
            review_name=review.google_review_name,
            reply_text=draft.draft_text,
        )

        db.update_draft_status(draft.id, "posted")
        db.update_approval_status(approval.id, ApprovalStatus.POSTED, datetime.utcnow())
        db.create_response(
            StoredResponse(
                id=str(uuid.uuid4()),
                review_id=draft.review_id,
                business_id=draft.business_id,
                response_text=draft.draft_text,
                posted_at=datetime.utcnow(),
            )
        )
        db.create_audit_event(
            event_type="google_reply_posted",
            business_id=approval.business_id,
            review_id=draft.review_id,
            draft_id=draft.id,
            approval_id=approval.id,
            message="Reply auto-posted to Google Business Profile",
            payload={"review_name": review.google_review_name, "result": result},
        )
        logger.info(f"Auto-posted reply to Google for review {review.google_review_name}")
        return {"success": True, "result": result}
    except Exception as post_error:
        db.update_draft_status(draft.id, "post_failed")
        db.update_approval_status(approval.id, ApprovalStatus.POST_FAILED, datetime.utcnow())
        db.create_audit_event(
            event_type="google_reply_post_failed",
            business_id=approval.business_id,
            review_id=draft.review_id if draft else None,
            draft_id=draft.id if draft else None,
            approval_id=approval.id,
            message="Failed to auto-post reply to Google Business Profile",
            payload={"error": str(post_error)},
        )
        logger.error(f"Failed to auto-post to Google: {post_error}")
        return {"success": False, "reason": "post_failed", "error": str(post_error)}


def _build_business_summary(business: Business) -> dict:
    metrics = db.get_business_metrics(business.id)
    return {
        "business_id": business.id,
        "name": business.name,
        "phone": business.phone,
        "sms_recipient": business.sms_recipient,
        "google_connected": bool(business.google_refresh_token),
        "google_location_id": business.google_location_id,
        "google_account_id": business.google_account_id,
        "response_tone": business.response_tone,
        "metrics": metrics,
    }


def _load_approval_context_or_404(approval_id: str) -> tuple[PendingApproval, DraftResponse, Review, Business]:
    approval = db.get_pending_approval(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    draft = db.get_draft_response(approval.draft_response_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    review = db.get_review(draft.review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    business = db.get_business(approval.business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    return approval, draft, review, business


def _render_edit_approval_page(
    approval: PendingApproval,
    draft: DraftResponse,
    review: Review,
    business: Business,
    *,
    token: str,
    flash_message: str = "",
    error_message: str = "",
) -> HTMLResponse:
    is_pending = approval.status == ApprovalStatus.PENDING
    button_disabled = "" if is_pending else "disabled"
    readonly = "" if is_pending else "readonly"
    status_label = approval.status.value.replace("_", " ").title()
    google_state = (
        "Connected and ready to post automatically"
        if business.google_refresh_token and review.google_review_name
        else "Not fully connected for auto-post yet"
    )
    flash_html = f'<div class="flash success">{flash_message}</div>' if flash_message else ""
    error_html = f'<div class="flash error">{error_message}</div>' if error_message else ""

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>TradeReply - Edit Reply</title>
      <style>
        * {{ box-sizing: border-box; }}
        body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:linear-gradient(135deg,#1e3a8a 0%,#3b82f6 100%); min-height:100vh; padding:24px; }}
        .container {{ max-width:820px; margin:0 auto; }}
        .card {{ background:white; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(0,0,0,0.12); margin-bottom:18px; }}
        h1 {{ margin:0 0 8px; color:#1e3a8a; }}
        h2 {{ margin:0 0 12px; color:#0f172a; font-size:1.1rem; }}
        p {{ color:#475569; line-height:1.5; }}
        .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-top:16px; }}
        .meta-item {{ background:#f8fafc; padding:12px 14px; border-radius:12px; }}
        .meta-item strong {{ display:block; color:#1e3a8a; margin-bottom:4px; font-size:0.92rem; }}
        .review-box {{ background:#f8fafc; border-radius:14px; padding:18px; border-left:4px solid #06b6d4; }}
        textarea {{ width:100%; min-height:220px; border-radius:14px; border:1px solid #cbd5e1; padding:16px; font:inherit; line-height:1.5; resize:vertical; }}
        .actions {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:16px; }}
        button {{ border:none; border-radius:12px; padding:14px 18px; font-weight:700; cursor:pointer; }}
        button.primary {{ background:#06b6d4; color:white; }}
        button.secondary {{ background:#e2e8f0; color:#0f172a; }}
        button.reject {{ background:#fee2e2; color:#b91c1c; }}
        button[disabled] {{ opacity:0.55; cursor:not-allowed; }}
        .flash {{ border-radius:12px; padding:14px 16px; margin-bottom:16px; font-weight:600; }}
        .flash.success {{ background:#ecfdf5; color:#166534; border:1px solid #bbf7d0; }}
        .flash.error {{ background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }}
        .status-pill {{ display:inline-block; padding:8px 12px; border-radius:999px; background:#e0f2fe; color:#075985; font-weight:700; font-size:0.85rem; }}
      </style>
    </head>
    <body>
      <div class="container">
        {flash_html}
        {error_html}
        <div class="card">
          <h1>Edit Reply</h1>
          <p>Review the AI draft for <strong>{business.name}</strong>, make any changes you want, then approve and post when you're happy.</p>
          <div class="meta">
            <div class="meta-item"><strong>Status</strong><span class="status-pill">{status_label}</span></div>
            <div class="meta-item"><strong>Reviewer</strong>{review.reviewer_name}</div>
            <div class="meta-item"><strong>Rating</strong>{review.rating.value} star</div>
            <div class="meta-item"><strong>Google</strong>{google_state}</div>
          </div>
        </div>

        <div class="card">
          <h2>Original review</h2>
          <div class="review-box">
            <p>{review.review_text or "No review text was supplied."}</p>
          </div>
        </div>

        <div class="card">
          <h2>Your draft reply</h2>
          <form method="post" action="/approvals/edit">
            <input type="hidden" name="token" value="{token}">
            <textarea name="draft_text" {readonly}>{draft.draft_text}</textarea>
            <div class="actions">
              <button class="secondary" type="submit" name="action" value="save" {button_disabled}>Save draft</button>
              <button class="primary" type="submit" name="action" value="approve" {button_disabled}>Approve &amp; post</button>
              <button class="reject" type="submit" name="action" value="reject" {button_disabled}>Reject</button>
            </div>
          </form>
        </div>
      </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown"""
    try:
        db.disconnect()
        logger.info("Database connection closed")
    except Exception as e:
        logger.error(f"Error closing database: {str(e)}")


# ==================== LANDING PAGE ====================


@app.get("/")
async def landing_page():
    """Serve landing page"""
    try:
        with open(os.path.join(os.path.dirname(__file__), "landing.html"), "r") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        logger.error(f"Failed to load landing page: {e}")
        return HTMLResponse(content="<h1>TradeReply</h1><p>AI-powered Google Business Profile review responses</p><a href='/onboard'>Get Started</a><p><a href='/health'>Health Check</a></p>")


# ==================== HEALTH CHECK ====================


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "0.1.0"}


# ==================== BUSINESS ENDPOINTS ====================


@app.post("/businesses")
async def create_business(
    request: Request,
):
    """Create a new business profile (JSON body)"""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    name = body.get("name")
    phone = body.get("phone")
    if not name or not phone:
        raise HTTPException(status_code=400, detail="name and phone are required")

    business_id = str(uuid.uuid4())
    business = Business(
        id=business_id,
        name=name,
        phone=phone,
        sms_recipient=body.get("sms_recipient", phone),
        description=body.get("description"),
        google_location_id=body.get("google_location_id"),
        google_account_id=body.get("google_account_id"),
        response_tone=body.get("response_tone"),
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
        "google_connected": bool(business.google_refresh_token),
        "response_tone": business.response_tone,
        "metrics": db.get_business_metrics(business.id),
        "created_at": business.created_at.isoformat(),
    }


@app.get("/api/businesses")
async def list_businesses_api():
    """List all businesses (API)"""
    businesses = db.list_businesses()
    return [
        {
            "id": b.id,
            **_build_business_summary(b),
        }
        for b in businesses
    ]


@app.get("/businesses/{business_id}/metrics")
async def get_business_metrics_api(business_id: str):
    """Get operational metrics for a single business."""
    business = db.get_business(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")
    return {
        "business_id": business.id,
        "name": business.name,
        "metrics": db.get_business_metrics(business.id),
    }


@app.get("/businesses", response_class=HTMLResponse)
async def list_businesses_html():
    """List all businesses (UI)"""
    businesses = db.list_businesses()
    count = len(businesses)
    cards = ""
    for b in businesses:
        summary = _build_business_summary(b)
        metrics = summary["metrics"]
        cards += f"""
        <div class="card">
          <h3>{b.name}</h3>
          <p><strong>Phone:</strong> {b.phone or "N/A"}</p>
          <p><strong>SMS:</strong> {b.sms_recipient or "N/A"}</p>
          <p><strong>Google:</strong> {"Connected" if summary["google_connected"] else "Not connected"}</p>
          <div class="mini-stats">
            <span>Reviews: {metrics['reviews_received']}</span>
            <span>Drafts: {metrics['drafts_generated']}</span>
            <span>Approved: {metrics['approved'] + metrics['posted']}</span>
            <span>Posted: {metrics['posted']}</span>
          </div>
        </div>
        """
    if not cards:
        cards = '<p class="empty">No businesses yet. <a href="/onboard">Add one</a></p>'
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>TradeReply - Businesses</title>
<style>
* {{margin:0;padding:0;box-sizing:border-box}}
body {{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#1e3a8a,#3b82f6);min-height:100vh;padding:20px}}
.container {{max-width:800px;margin:0 auto}}
.header {{text-align:center;color:white;margin-bottom:30px}}
.header h1 {{font-size:2.5em}}
.nav {{background:white;border-radius:12px;padding:15px;margin-bottom:20px;display:flex;gap:20px;justify-content:center}}
.nav a {{color:#1e3a8a;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600}}
.nav a:hover {{background:#e0f2fe}}
.nav a.active {{background:#06b6d4;color:white}}
.section {{background:white;border-radius:12px;padding:25px;box-shadow:0 4px 6px rgba(0,0,0,0.1)}}
.section h2 {{color:#1e3a8a;margin-bottom:15px}}
.card {{background:#f8fafc;padding:15px;border-radius:8px;margin-bottom:10px;border-left:4px solid #06b6d4}}
.card h3 {{color:#1e3a8a;margin:0 0 5px 0}}
.card p {{color:#64748b;font-size:0.9em;margin:3px 0}}
.mini-stats {{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}}
.mini-stats span {{background:white;padding:8px 10px;border-radius:8px;color:#1e3a8a;font-weight:600;font-size:0.85em}}
.empty {{color:#94a3b8;text-align:center;padding:20px}}
.empty a {{color:#06b6d4}}
</style>
</head><body><div class="container">
<div class="header"><h1>🦞 TradeReply</h1><p>Your connected businesses</p></div>
<div class="nav"><a href="/ops/dashboard">Dashboard</a><a href="/submit-review">Submit Review</a><a href="/businesses" class="active">Businesses</a><a href="/onboard">Add Business</a></div>
<div class="section"><h2>📍 Businesses ({count})</h2>{cards}</div>
</div></body></html>"""
    return HTMLResponse(content=html)


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

        flow = _create_draft_and_send_approval(review, business)

        return {
            "review_id": review_id,
            "draft_id": flow["draft_id"],
            "approval_id": flow["approval_id"],
            "status": "awaiting_approval",
            "draft": flow["draft_text"],
            "sms_sent_to": flow["sms_sent_to"],
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
        result = {
            "approval_id": approval_id,
            "status": new_status.value,
            "timestamp": datetime.utcnow().isoformat(),
        }

        if response.approved:
            auto_post_result = _attempt_auto_post_for_approval(approval)
            result["auto_post"] = auto_post_result

        return result

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


@app.get("/approvals/edit", response_class=HTMLResponse)
async def edit_approval_page(token: str):
    """Render a simple owner-facing page to edit the draft before posting."""
    approval_id = _verify_approval_token(token)
    approval, draft, review, business = _load_approval_context_or_404(approval_id)
    return _render_edit_approval_page(approval, draft, review, business, token=token)


@app.post("/approvals/edit", response_class=HTMLResponse)
async def update_approval_from_edit_page(
    token: str = Form(...),
    action: str = Form(...),
    draft_text: str = Form(""),
):
    """Handle save / approve / reject actions from the owner edit page."""
    approval_id = _verify_approval_token(token)
    approval, draft, review, business = _load_approval_context_or_404(approval_id)

    if approval.status != ApprovalStatus.PENDING:
        return _render_edit_approval_page(
            approval,
            draft,
            review,
            business,
            token=token,
            error_message="This approval is no longer pending, so it can’t be changed here.",
        )

    cleaned_draft = draft_text.strip()
    if not cleaned_draft:
        return _render_edit_approval_page(
            approval,
            draft,
            review,
            business,
            token=token,
            error_message="Reply text cannot be empty.",
        )

    if cleaned_draft != draft.draft_text:
        db.update_draft_text(draft.id, cleaned_draft)
        db.create_audit_event(
            event_type="draft_edited",
            business_id=business.id,
            review_id=review.id,
            draft_id=draft.id,
            approval_id=approval.id,
            message="Draft edited from approval page",
        )
        draft = db.get_draft_response(draft.id) or draft

    if action == "save":
        return _render_edit_approval_page(
            approval,
            draft,
            review,
            business,
            token=token,
            flash_message="Draft saved. You can still approve or reject it from this page.",
        )

    if action == "reject":
        db.update_approval_status(approval.id, ApprovalStatus.REJECTED, datetime.utcnow())
        db.update_draft_status(draft.id, "rejected")
        db.create_audit_event(
            event_type="approval_rejected_from_edit_page",
            business_id=business.id,
            review_id=review.id,
            draft_id=draft.id,
            approval_id=approval.id,
            message="Draft rejected from edit page",
        )
        approval = db.get_pending_approval(approval.id) or approval
        return _render_edit_approval_page(
            approval,
            draft,
            review,
            business,
            token=token,
            flash_message="Reply rejected. TradeReply recorded that decision.",
        )

    if action == "approve":
        db.update_approval_status(approval.id, ApprovalStatus.APPROVED, datetime.utcnow())
        db.update_draft_status(draft.id, "approved")
        db.create_audit_event(
            event_type="approval_approved_from_edit_page",
            business_id=business.id,
            review_id=review.id,
            draft_id=draft.id,
            approval_id=approval.id,
            message="Draft approved from edit page",
        )
        approval = db.get_pending_approval(approval.id) or approval
        auto_post_result = _attempt_auto_post_for_approval(approval)
        if auto_post_result["success"]:
            approval = db.get_pending_approval(approval.id) or approval
            draft = db.get_draft_response(draft.id) or draft
            return _render_edit_approval_page(
                approval,
                draft,
                review,
                business,
                token=token,
                flash_message="Reply approved and posted to Google successfully.",
            )

        message = (
            "Reply approved, but Google is not fully connected for this business yet."
            if auto_post_result.get("reason") == "missing_prerequisites"
            else "Reply approved, but the Google post failed and needs follow-up."
        )
        approval = db.get_pending_approval(approval.id) or approval
        draft = db.get_draft_response(draft.id) or draft
        return _render_edit_approval_page(
            approval,
            draft,
            review,
            business,
            token=token,
            flash_message=message,
        )

    return _render_edit_approval_page(
        approval,
        draft,
        review,
        business,
        token=token,
        error_message="Unknown action. Please try again.",
    )


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
        response = StoredResponse(
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
        # Normalize phone number (handle +61, 0, etc)
        normalized_phone = From.strip()
        if normalized_phone.startswith('+61'):
            # Keep +61 format
            pass
        elif normalized_phone.startswith('61'):
            # Convert 61 → +61
            normalized_phone = '+' + normalized_phone
        elif normalized_phone.startswith('0'):
            # Convert 0402... → +61402...
            normalized_phone = '+61' + normalized_phone[1:]
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
            return ""  # Silent — don't confuse customers with error texts

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
                        draft_response=draft.draft_text,
                    )
                    sms_handler.send_sms(
                        recipient_phone=normalized_phone,
                        message=confirmation_message,
                    )
                    logger.info(f"Confirmation SMS sent to {normalized_phone}")
        except Exception as confirm_error:
            logger.warning(f"Failed to send confirmation SMS: {confirm_error}")

        # If approved, auto-post to Google Business Profile when possible
        if parsed:
            auto_post_result = _attempt_auto_post_for_approval(approval)
            if auto_post_result["success"]:
                return "Approved and posted. TradeReply published your reply to Google."

            if auto_post_result.get("reason") == "missing_prerequisites":
                return "Approved. TradeReply recorded your YES response, but this business still needs Google connection details before auto-posting."

            return "Approved. TradeReply recorded your YES response, but the Google post failed and has been flagged for follow-up."

        return "Rejected. TradeReply recorded your NO response."

    except Exception as e:
        logger.error(f"Error handling inbound Twilio webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== GOOGLE OAUTH ENDPOINTS ====================


@app.get("/google/auth")
async def google_auth(state: Optional[str] = None):
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
        
        # Pass through state as-is (contains name, phone, and optional business_id)
        auth_url = client.get_auth_url(state=state)
        
        db.create_audit_event(
            event_type="google_oauth_started",
            message="Google OAuth flow initiated",
        )
        
        return RedirectResponse(url=auth_url)
        
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
    """Handle Google OAuth callback - auto-discovers locations for one-step setup"""
    try:
        from google_client import GoogleBusinessClient, parse_google_review
        
        if error:
            logger.error(f"Google OAuth error: {error}")
            return HTMLResponse(
                content=f"<html><body><h1>Authorization Failed</h1><p>Error: {error}</p></body></html>",
                status_code=400
            )
        
        # Parse business_id from state (optional - we can create one if missing)
        import urllib.parse
        business_id = None
        business_name = "My Business"
        sms_recipient = None
        location_id = None
        if state:
            # Parse state params like "business_id=xxx&name=MyBiz&phone=+61...&location_id=accounts/..."
            params = {}
            for pair in state.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = urllib.parse.unquote(v)  # Decode URL encoding
            business_id = params.get("business_id")
            business_name = params.get("name", "My Business")
            sms_recipient = params.get("phone")
            location_id = params.get("location_id")
        
        # Exchange code for tokens
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
        )
        
        tokens = client.exchange_code(code)
        
        # Auto-discover accounts and locations (try, but prefer manual entry)
        discovered_location = location_id  # Start with manual entry if provided
        discovered_location_name = None
        if not discovered_location:
            try:
                accounts = client.get_accounts()
                if accounts:
                    first_account = accounts[0]
                    account_name = first_account.get("name", "")  # e.g., "accounts/123456"
                    locations = client.get_locations(account_name)
                    if locations:
                        first_location = locations[0]
                        discovered_location = first_location.get("name")  # e.g., "accounts/123/locations/456"
                        discovered_location_name = first_location.get("title", "Unknown Location")
                        logger.info(f"Auto-discovered location: {discovered_location} ({discovered_location_name})")
            except Exception as discovery_error:
                logger.warning(f"Could not auto-discover locations: {discovery_error}")
        
        # Create business if needed
        if not business_id:
            business_id = str(uuid.uuid4())
            business = Business(
                id=business_id,
                name=business_name,
                phone=sms_recipient or "+61000000000",
                sms_recipient=sms_recipient or "+61000000000",
                google_location_id=discovered_location,
                google_refresh_token=tokens["refresh_token"],
            )
            db.create_business(business)
            logger.info(f"Created new business {business_id} with Google connection")
        else:
            # Update existing business
            db.update_business_mapping(
                business_id,
                google_refresh_token=tokens["refresh_token"],
                google_location_id=discovered_location,
            )
            logger.info(f"Updated business {business_id} with Google connection")
        
        db.create_audit_event(
            event_type="google_oauth_completed",
            business_id=business_id,
            message="Google OAuth completed successfully",
            payload={
                "has_refresh_token": bool(tokens.get("refresh_token")),
                "google_location_id": discovered_location,
                "location_name": discovered_location_name,
                "manual_location_provided": bool(location_id),
            },
        )
        
        # Show success page with location info
        location_display = discovered_location_name or ("" if not discovered_location else "Location configured")
        import urllib.parse
        callback_params = urllib.parse.urlencode({
            "connected": "1",
            "name": business_name,
            "phone": sms_recipient or "",
            "location": location_display,
        })
        return RedirectResponse(url=f"/onboard?{callback_params}")
        
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
        
        # Auto-discover location if not set
        if not business.google_location_id:
            try:
                client_for_discovery = GoogleBusinessClient(
                    client_id=config.GOOGLE_CLIENT_ID,
                    client_secret=config.GOOGLE_CLIENT_SECRET,
                    redirect_uri=config.GOOGLE_REDIRECT_URI,
                    refresh_token=business.google_refresh_token,
                )
                accounts = client_for_discovery.get_accounts()
                if accounts:
                    account_name = accounts[0].get("name", "")
                    locations = client_for_discovery.get_locations(account_name)
                    if locations:
                        first_location = locations[0]
                        discovered_id = first_location.get("name")
                        db.update_business_mapping(business_id, google_location_id=discovered_id)
                        business = db.get_business(business_id)  # refresh
                        logger.info(f"Auto-discovered location for business {business_id}: {discovered_id}")
            except Exception as discovery_err:
                logger.warning(f"Could not auto-discover location: {discovery_err}")
            
            if not business.google_location_id:
                raise HTTPException(
                    status_code=400,
                    detail="Google location ID not set and auto-discovery failed. Please configure location."
                )
        
        # Initialize Google client with stored refresh token
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
            refresh_token=business.google_refresh_token,
        )
        
        # Build full location path if needed
        location_id = business.google_location_id
        if location_id and not location_id.startswith("accounts/"):
            # Need to discover account ID to build full path
            try:
                accounts = client.get_accounts()
                if accounts:
                    account_name = accounts[0].get("name", "")  # e.g., "accounts/123456"
                    if account_name:
                        location_id = f"{account_name}/{location_id}"
                        logger.info(f"Built full location path: {location_id}")
            except Exception as acc_err:
                logger.warning(f"Could not auto-discover account for location: {acc_err}")
        
        # Fetch reviews
        result = client.get_reviews(location_id)
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
                try:
                    _create_draft_and_send_approval(review, business)
                except HTTPException as flow_error:
                    logger.error(
                        f"Failed to create/send approval for synced review {review_id}: {flow_error.detail}"
                    )
        
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
    business_cards = []
    pending = []
    ready = []
    posted = []
    failed = []

    for business in businesses:
        summary = _build_business_summary(business)
        metrics = summary["metrics"]
        business_cards.append(
            {
                "name": business.name,
                "google_connected": summary["google_connected"],
                "reviews_received": metrics["reviews_received"],
                "drafts_generated": metrics["drafts_generated"],
                "awaiting_approval": metrics["awaiting_approval"],
                "posted": metrics["posted"],
                "post_failed": metrics["post_failed"],
            }
        )
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

    business_summary_html = ''.join(
        [
            f"""
            <div class="biz-card">
              <h3>{card['name']}</h3>
              <p class="muted">{'Google connected' if card['google_connected'] else 'Google not connected'}</p>
              <div class="biz-metrics">
                <span>Reviews {card['reviews_received']}</span>
                <span>Drafts {card['drafts_generated']}</span>
                <span>Pending {card['awaiting_approval']}</span>
                <span>Posted {card['posted']}</span>
              </div>
            </div>
            """
            for card in business_cards
        ]
    ) or '<div class="empty">No connected businesses yet</div>'

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>TradeReply Dashboard</title>
      <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%); min-height: 100vh; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ text-align: center; color: white; margin-bottom: 30px; }}
        .header h1 {{ font-size: 2.5em; margin-bottom: 10px; }}
        .header p {{ opacity: 0.9; }}
        .nav {{ background: white; border-radius: 12px; padding: 15px 20px; margin-bottom: 20px; display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; }}
        .nav a {{ color: #1e3a8a; text-decoration: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; }}
        .nav a:hover {{ background: #e0f2fe; }}
        .nav a.active {{ background: #06b6d4; color: white; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat-card {{ background: white; border-radius: 12px; padding: 25px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .stat-card .number {{ font-size: 3em; font-weight: bold; color: #1e3a8a; }}
        .stat-card .label {{ color: #64748b; margin-top: 5px; }}
        .section {{ background: white; border-radius: 12px; padding: 25px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        .section h2 {{ color: #1e3a8a; margin-bottom: 15px; font-size: 1.5em; }}
        .item {{ background: #f8fafc; padding: 15px; border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #06b6d4; }}
        .item strong {{ color: #1e3a8a; }}
        .item .muted {{ color: #64748b; font-size: 0.9em; }}
        .empty {{ color: #94a3b8; text-align: center; padding: 20px; }}
        .workflow {{ background: #f0f9ff; border-radius: 12px; padding: 20px; margin-bottom: 30px; }}
        .workflow h2 {{ color: #1e3a8a; margin-bottom: 15px; }}
        .workflow-steps {{ display: flex; gap: 15px; flex-wrap: wrap; }}
        .workflow-step {{ background: white; padding: 15px 20px; border-radius: 8px; flex: 1; min-width: 150px; }}
        .workflow-step .step-num {{ background: #06b6d4; color: white; width: 30px; height: 30px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: bold; margin-bottom: 8px; }}
        .workflow-step .step-text {{ color: #1e3a8a; font-weight: 600; }}
        .biz-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; }}
        .biz-card {{ background:#f8fafc; border-radius:10px; padding:16px; border-left:4px solid #06b6d4; }}
        .biz-card h3 {{ color:#1e3a8a; margin-bottom:6px; }}
        .biz-metrics {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-top:12px; }}
        .biz-metrics span {{ background:white; padding:8px 10px; border-radius:8px; color:#1e3a8a; font-weight:600; font-size:0.9em; }}
        .alert {{ background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .alert strong {{ color: #92400e; }}
        ul {{ padding-left: 20px; }}
        li {{ margin-bottom: 8px; list-style: none; }}
        .muted {{ color: #64748b; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>🦞 TradeReply Dashboard</h1>
          <p>Manage review responses for your business</p>
        </div>
        
        <div class="nav">
          <a href="/ops/dashboard" class="active">Dashboard</a>
          <a href="/submit-review">Submit Review</a>
          <a href="/businesses">Businesses</a>
          <a href="/onboard">Add Business</a>
        </div>
        
        <div class="alert">
          <strong>📋 Automated Workflow:</strong> TradeReply checks connected Google Business Profiles → drafts a reply → sends an SMS approval → posts to Google automatically after YES
        </div>
        
        <div class="stats">
          <div class="stat-card">
            <div class="number">{len(businesses)}</div>
            <div class="label">Businesses</div>
          </div>
          <div class="stat-card">
            <div class="number">{len(pending)}</div>
            <div class="label">Pending Approvals</div>
          </div>
          <div class="stat-card">
            <div class="number">{len(ready)}</div>
            <div class="label">Ready to Post</div>
          </div>
          <div class="stat-card">
            <div class="number">{len(posted)}</div>
            <div class="label">Responses Posted</div>
          </div>
        </div>
        
        <div class="workflow">
          <h2>How It Works</h2>
          <div class="workflow-steps">
            <div class="workflow-step">
              <div class="step-num">1</div>
              <div class="step-text">New Google review detected</div>
            </div>
            <div class="workflow-step">
              <div class="step-num">2</div>
              <div class="step-text">AI drafts a reply</div>
            </div>
            <div class="workflow-step">
              <div class="step-num">3</div>
              <div class="step-text">Owner receives SMS</div>
            </div>
            <div class="workflow-step">
              <div class="step-num">4</div>
              <div class="step-text">Reply YES or NO</div>
            </div>
            <div class="workflow-step">
              <div class="step-num">5</div>
              <div class="step-text">Approved replies post automatically</div>
            </div>
          </div>
        </div>

        <div class="section">
          <h2>🏢 Business Overview</h2>
          <div class="biz-grid">{business_summary_html}</div>
        </div>
        
        <div class="section">
          <h2>⏳ Pending Approvals ({len(pending)})</h2>
          {render_list(pending, 'pending') if pending else '<div class="empty">No pending approvals</div>'}
        </div>
        
        <div class="section">
          <h2>✅ Ready to Post ({len(ready)})</h2>
          {render_list(ready, 'ready') if ready else '<div class="empty">No responses ready to post</div>'}
        </div>
        
        <div class="section">
          <h2>📤 Posted Responses ({len(posted)})</h2>
          {render_list(posted, 'posted') if posted else '<div class="empty">No responses posted yet</div>'}
        </div>
        
        {f'<div class="section"><h2>❌ Failed Posts ({len(failed)})</h2>{render_list(failed, "failed")}</div>' if failed else ''}
      </div>
    </body>
    </html>
    """
    return html


@app.get("/businesses/{business_id}/debug-google")
async def debug_google_api(business_id: str):
    """Debug endpoint: Test Google API access and list available accounts/locations"""
    try:
        from google_client import GoogleBusinessClient
        
        business = db.get_business(business_id)
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
        
        if not business.google_refresh_token:
            raise HTTPException(
                status_code=400,
                detail="Google not connected. Complete OAuth flow first."
            )
        
        client = GoogleBusinessClient(
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            redirect_uri=config.GOOGLE_REDIRECT_URI,
            refresh_token=business.google_refresh_token,
        )
        
        result = {
            "business_id": business_id,
            "has_refresh_token": bool(business.google_refresh_token),
            "google_location_id": business.google_location_id,
            "accounts": [],
            "locations": [],
            "errors": [],
        }
        
        # Try to get accounts
        try:
            accounts = client.get_accounts()
            result["accounts"] = [
                {"name": a.get("name"), "accountName": a.get("accountName")}
                for a in accounts
            ]
            
            # Try to get locations for first account
            if accounts:
                try:
                    locations = client.get_locations(accounts[0]["name"])
                    result["locations"] = [
                        {
                            "name": loc.get("name"),
                            "title": loc.get("title"),
                        }
                        for loc in locations
                    ]
                except Exception as loc_err:
                    result["errors"].append(f"get_locations: {str(loc_err)}")
                    
        except Exception as acc_err:
            result["errors"].append(f"get_accounts: {str(acc_err)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Debug Google API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/config")
async def debug_config():
    """Debug endpoint: Show configuration status (without revealing secrets)"""
    return {
        "gemini_api_key_set": bool(config.GEMINI_API_KEY),
        "twilio_configured": bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN),
        "google_oauth_configured": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
        "dry_run_ai": config.DRY_RUN_AI,
        "dry_run_sms": config.DRY_RUN_SMS,
    }


@app.get("/debug/config")
async def debug_config():
    """Debug endpoint: Check configuration status"""
    return {
        "has_gemini_key": bool(config.GEMINI_API_KEY),
        "has_twilio_credentials": bool(config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN),
        "has_google_oauth": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
        "dry_run_ai": config.DRY_RUN_AI,
        "dry_run_sms": config.DRY_RUN_SMS,
    }


@app.get("/debug/ai-test")
async def debug_ai_test():
    """Debug endpoint: Test AI response generation"""
    try:
        from ai_integration import AIHandler
        from models import Review, Business, StarRating
        
        # Create test review
        test_review = Review(
            id="test-123",
            business_id="test-biz",
            reviewer_name="Test Customer",
            rating=StarRating(4),
            review_text="Great coffee but the music was too loud. Staff were friendly!",
            created_at=datetime.utcnow(),
        )
        
        test_business = Business(
            id="test-biz",
            name="Test Cafe",
            phone="+61000000000",
            sms_recipient="+61000000000",
        )
        
        ai = AIHandler()
        
        return {
            "dry_run": ai.dry_run,
            "has_client": ai.client is not None,
            "api_key_set": bool(ai.api_key),
            "response": ai.generate_response(test_review, test_business),
        }
    except Exception as e:
        return {"error": str(e), "traceback": str(e.__traceback__)}


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


@app.get("/mobile")
async def mobile_app():
    """Mobile-friendly web app for generating review responses"""
    from fastapi.responses import FileResponse
    import os
    
    mobile_path = os.path.join(os.path.dirname(__file__), "static", "mobile.html")
    if os.path.exists(mobile_path):
        return FileResponse(mobile_path, media_type="text/html")
    else:
        raise HTTPException(status_code=404, detail="Mobile app not found")


@app.get("/submit-review", response_class=HTMLResponse)
async def submit_review_page():
    """Simple form to submit a review manually with Dashboard styling"""
    html = """
    <!DOCTYPE html>
    <html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeReply - Submit Review</title><style>
    *{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#1e3a8a,#3b82f6);min-height:100vh;padding:20px}
    .container{max-width:800px;margin:0 auto}.header{text-align:center;color:white;margin-bottom:30px}.header h1{font-size:2.5em}
    .nav{background:white;border-radius:12px;padding:15px;margin-bottom:20px;display:flex;gap:20px;justify-content:center}
    .nav a{color:#1e3a8a;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600}.nav a:hover{background:#e0f2fe}
    .nav a.active{background:#06b6d4;color:white}.card{background:white;border-radius:12px;padding:30px;box-shadow:0 4px 6px rgba(0,0,0,0.1)}
    h2{color:#1e3a8a;margin-bottom:20px;font-size:1.5em}.form-group{margin-bottom:20px}
    label{display:block;color:#1e3a8a;font-size:14px;margin-bottom:8px;font-weight:600}
    input,textarea,select{width:100%;padding:14px 16px;font-size:16px;border:2px solid #e2e8f0;border-radius:8px;background:#f8fafc;color:#1e3a8a}
    textarea{min-height:120px;resize:vertical}input:focus,textarea:focus,select:focus{outline:0;border-color:#06b6d4;background:white}
    .btn{width:100%;background:#06b6d4;color:white;border:0;padding:16px;font-size:18px;font-weight:600;border-radius:8px;cursor:pointer}
    .btn:hover{background:#0891b2}.btn:disabled{background:#94a3b8;cursor:not-allowed}
    .success{background:#d1fae5;border:2px solid #10b981;border-radius:8px;padding:20px;margin-bottom:20px;display:none}
    .success h3{color:#065f46;margin:0 0 8px 0}.success p{color:#047857;margin:0}
    .stars{display:flex;gap:8px;margin-bottom:8px}.star{font-size:32px;cursor:pointer;color:#cbd5e1}.star.active{color:#fbbf24}
    </style></head><body><div class="container">
    <div class="header"><h1>🦞 TradeReply</h1><p>Submit a review for AI-powered response</p></div>
    <div class="nav"><a href="/ops/dashboard">Dashboard</a><a href="/submit-review" class="active">Submit Review</a><a href="/businesses">Businesses</a><a href="/onboard">Add Business</a></div>
    <div class="card"><h2>📝 Submit a Review</h2>
    <div id="successBox" class="success"><h3>✅ Review Submitted!</h3><p>Check your phone for the approval SMS.</p></div>
    <form id="reviewForm">
    <div class="form-group"><label for="businessId">Business</label><select id="businessId" required><option value="">Loading...</option></select></div>
    <div class="form-group"><label>Rating</label><div class="stars" id="stars"><span class="star" data-rating="1">★</span><span class="star" data-rating="2">★</span><span class="star" data-rating="3">★</span><span class="star" data-rating="4">★</span><span class="star active" data-rating="5">★</span></div><input type="hidden" id="rating" value="5"></div>
    <div class="form-group"><label for="reviewerName">Reviewer Name</label><input type="text" id="reviewerName" placeholder="e.g. John Smith" required></div>
    <div class="form-group"><label for="reviewText">Review Text</label><textarea id="reviewText" placeholder="Paste the review here..." required></textarea></div>
    <button type="submit" class="btn" id="submitBtn">Generate AI Response</button></form></div></div>
    <script>
    fetch('/api/businesses').then(r=>r.json()).then(b=>{const s=document.getElementById('businessId');s.innerHTML=b.length===0?'<option value="">No businesses - add one first</option>':b.map(x=>'<option value="'+x.id+'">'+x.name+'</option>').join('')});
    let r=5;document.querySelectorAll('.star').forEach(s=>{s.addEventListener('click',function(){r=parseInt(this.dataset.rating);document.getElementById('rating').value=r;document.querySelectorAll('.star').forEach((x,i)=>x.classList.toggle('active',i<r))})});
    document.getElementById('reviewForm').addEventListener('submit',async function(e){e.preventDefault();const b=document.getElementById('submitBtn');b.disabled=true;b.textContent='Generating...';try{const res=await fetch('/reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({business_id:document.getElementById('businessId').value,reviewer_name:document.getElementById('reviewerName').value,rating:parseInt(document.getElementById('rating').value),review_text:document.getElementById('reviewText').value})});if(res.ok){document.getElementById('successBox').style.display='block';this.reset();document.querySelectorAll('.star').forEach((x,i)=>x.classList.toggle('active',i<5));document.getElementById('rating').value=5;r=5}else{const err=await res.json();alert('Error: '+(err.detail||JSON.stringify(err)))}}catch(err){alert('Error: '+err.message)}finally{b.disabled=false;b.textContent='Generate AI Response'}});
    </script></body></html>
    """
    return HTMLResponse(content=html)

@app.get("/onboard", response_class=HTMLResponse)
async def onboard_page():
    """3-Step onboarding wizard: Business details → Google Connect → Done"""
    html = """
    <!DOCTYPE html>
    <html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TradeReply - Get Started</title><style>
    *{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#1e3a8a,#3b82f6);min-height:100vh;padding:20px}
    .container{max-width:600px;margin:0 auto}
    .header{text-align:center;color:white;margin-bottom:30px}
    .header h1{font-size:2.5em;margin-bottom:4px}
    .header p{opacity:0.9;font-size:18px}
    .nav{background:white;border-radius:12px;padding:15px;margin-bottom:20px;display:flex;gap:20px;justify-content:center}
    .nav a{color:#1e3a8a;text-decoration:none;padding:10px 20px;border-radius:8px;font-weight:600}
    .nav a:hover{background:#e0f2fe}
    .nav a.active{background:#06b6d4;color:white}
    .card{background:white;border-radius:16px;padding:40px;box-shadow:0 8px 30px rgba(0,0,0,0.12);text-align:center}
    /* Progress bar */
    .steps{display:flex;justify-content:center;gap:0;margin-bottom:30px}
    .step{display:flex;align-items:center;gap:0}
    .step-circle{width:36px;height:36px;border-radius:50%;background:#e2e8f0;color:#94a3b8;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px}
    .step-circle.active{background:#06b6d4;color:white}
    .step-circle.done{background:#10b981;color:white}
    .step-line{width:40px;height:3px;background:#e2e8f0;margin:0 4px}
    .step-line.done{background:#10b981}
    /* Sections */
    .step-content{display:none}
    .step-content.active{display:block}
    h2{color:#1e3a8a;font-size:1.5em;margin-bottom:8px}
    .subtitle{color:#64748b;font-size:16px;line-height:1.6;margin-bottom:24px}
    .form-group{margin-bottom:20px;text-align:left}
    label{display:block;color:#1e3a8a;font-size:14px;margin-bottom:8px;font-weight:600}
    input{width:100%;padding:14px 16px;font-size:16px;border:2px solid #e2e8f0;border-radius:10px;background:#f8fafc;color:#1e3a8a}
    input:focus{outline:0;border-color:#06b6d4;background:white}
    input::placeholder{color:#94a3b8}
    .btn{width:100%;color:white;border:0;padding:16px;font-size:18px;font-weight:600;border-radius:10px;cursor:pointer;transition:all 0.2s}
    .btn:hover{transform:translateY(-1px)}
    .btn:disabled{opacity:0.6;cursor:not-allowed;transform:none}
    .btn-primary{background:#06b6d4}.btn-primary:hover:not(:disabled){background:#0891b2}
    .btn-google{background:#1e3a8a;display:flex;align-items:center;justify-content:center;gap:10px}
    .btn-google:hover:not(:disabled){background:#1e40af}
    .btn-skip{background:transparent;color:#94a3b8;border:2px solid #e2e8f0;margin-top:12px;font-size:16px}
    .btn-skip:hover{color:#1e3a8a;border-color:#1e3a8a;background:#f8fafc}
    .google-icon{width:24px;height:24px}
    .features{margin-top:24px;padding-top:20px;border-top:1px solid #e2e8f0;text-align:left}
    .feature{display:flex;align-items:center;gap:12px;padding:6px 0;color:#475569;font-size:14px}
    .check{color:#10b981;font-size:18px}
    .info-box{background:#f0f9ff;border:1px solid #bae6fd;border-radius:10px;padding:16px;text-align:left;margin-bottom:20px}
    .info-box p{color:#0369a1;font-size:14px;margin:0}
    .done-icon{font-size:64px;margin-bottom:16px}
    .done-title{color:#065f46;font-size:24px;font-weight:700;margin-bottom:8px}
    .done-subtitle{color:#047857;font-size:16px;margin-bottom:20px}
    .done-details{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:16px;text-align:left;margin-bottom:20px}
    .done-details p{color:#166534;font-size:14px;margin:4px 0}
    .done-details strong{color:#14532d}
    .error-msg{background:#fef2f2;border:1px solid #fecaca;color:#dc2626;border-radius:8px;padding:12px;margin-bottom:16px;display:none;font-size:14px}
    </style></head><body><div class="container">
    <div class="header"><h1>🦞 TradeReply</h1><p>Get started in 2 minutes</p></div>
    <div class="nav"><a href="/ops/dashboard">Dashboard</a><a href="/businesses">Businesses</a><a href="/onboard" class="active">Setup</a></div>

    <div class="card">
    <!-- Progress -->
    <div class="steps">
      <div class="step"><div class="step-circle active" id="sc1">1</div></div>
      <div class="step-line" id="sl1"></div>
      <div class="step"><div class="step-circle" id="sc2">2</div></div>
      <div class="step-line" id="sl2"></div>
      <div class="step"><div class="step-circle" id="sc3">✓</div></div>
    </div>

    <!-- STEP 1: Business Details -->
    <div class="step-content active" id="step1">
      <h2>📝 Your Business Details</h2>
      <p class="subtitle">We just need the basics to get started.</p>
      <div id="error1" class="error-msg"></div>
      <form id="form1">
        <div class="form-group">
          <label for="name">Business Name</label>
          <input type="text" id="name" placeholder="e.g. Smith's Plumbing" required>
        </div>
        <div class="form-group">
          <label for="phone">Mobile Number</label>
          <input type="tel" id="phone" placeholder="+61 400 123 456" required>
          <small style="color:#94a3b8;font-size:12px;margin-top:4px;display:block">We'll send SMS approvals to this number</small>
        </div>
        <button type="submit" class="btn btn-primary" id="btn1">Continue →</button>
      </form>
      <div class="features">
        <div class="feature"><span class="check">✓</span> AI writes professional review responses</div>
        <div class="feature"><span class="check">✓</span> Approve via SMS — no app needed</div>
        <div class="feature"><span class="check">✓</span> Auto-post to Google (with connection)</div>
      </div>
    </div>

    <!-- STEP 2: Google Connect -->
    <div class="step-content" id="step2">
      <h2>🔗 Connect Google Business</h2>
      <p class="subtitle">Link your Google Business Profile so TradeReply can fetch reviews and post responses automatically.</p>
      <div class="info-box">
        <p>🔒 <strong>Secure:</strong> We only access reviews and replies. We never see or change anything else on your account.</p>
      </div>
      <button class="btn btn-google" id="btnGoogle" onclick="connectGoogle()">
        <svg class="google-icon" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
        Connect Google Business Profile
      </button>
      <button class="btn btn-skip" onclick="skipGoogle()">Skip for now — I'll connect later</button>
    </div>

    <!-- STEP 3: Done -->
    <div class="step-content" id="step3">
      <div class="done-icon">🎉</div>
      <div class="done-title">You're all set!</div>
      <div class="done-subtitle" id="doneSubtitle">TradeReply is now watching your reviews.</div>
      <div class="done-details" id="doneDetails">
        <p><strong>Business:</strong> <span id="doneName">—</span></p>
        <p><strong>SMS:</strong> <span id="donePhone">—</span></p>
        <p><strong>Google:</strong> <span id="doneGoogle">Not connected</span></p>
      </div>
      <p class="subtitle" style="margin-top:16px">When a new review comes in, you'll get an SMS with the AI-written response. Just reply YES to approve or NO to reject.</p>
      <a href="/ops/dashboard" class="btn btn-primary" style="display:block;text-decoration:none;margin-top:16px">Go to Dashboard →</a>
    </div>
    </div></div>

    <script>
    let businessId = null;
    let businessName = '';
    let businessPhone = '';

    function goStep(n) {
      document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
      document.getElementById('step' + n).classList.add('active');
      for (let i = 1; i <= 3; i++) {
        const sc = document.getElementById('sc' + i);
        sc.classList.remove('active', 'done');
        if (i < n) sc.classList.add('done');
        else if (i === n) sc.classList.add('active');
      }
      for (let i = 1; i <= 2; i++) {
        const sl = document.getElementById('sl' + i);
        sl.classList.toggle('done', i < n);
      }
    }

    document.getElementById('form1').addEventListener('submit', async function(e) {
      e.preventDefault();
      const btn = document.getElementById('btn1');
      const errEl = document.getElementById('error1');
      errEl.style.display = 'none';
      btn.disabled = true;
      btn.textContent = 'Saving...';
      try {
        businessName = document.getElementById('name').value.trim();
        businessPhone = document.getElementById('phone').value.trim();
        const res = await fetch('/businesses', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: businessName, phone: businessPhone})
        });
        if (!res.ok) {
          let errMsg = 'Failed to create business';
          try {
            const err = await res.json();
            if (typeof err.detail === 'string') errMsg = err.detail;
            else if (Array.isArray(err.detail)) errMsg = err.detail.map(e => e.msg || e.message || JSON.stringify(e)).join(', ');
            else errMsg = JSON.stringify(err);
          } catch(_) {}
          throw new Error(errMsg);
        }
        const data = await res.json();
        businessId = data.business_id;
        goStep(2);
      } catch(err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
      } finally {
        btn.disabled = false;
        btn.textContent = 'Continue →';
      }
    });

    function connectGoogle() {
      if (!businessId) return alert('Please complete step 1 first');
      const state = encodeURIComponent('business_id=' + businessId + '&name=' + encodeURIComponent(businessName) + '&phone=' + encodeURIComponent(businessPhone));
      window.location.href = '/google/auth?state=' + state;
    }

    function skipGoogle() {
      document.getElementById('doneName').textContent = businessName;
      document.getElementById('donePhone').textContent = businessPhone;
      document.getElementById('doneGoogle').textContent = 'Not connected (connect anytime from Settings)';
      goStep(3);
    }

    // Check if we're returning from Google OAuth
    const params = new URLSearchParams(window.location.search);
    if (params.get('connected') === '1') {
      const name = params.get('name') || 'Your Business';
      const phone = params.get('phone') || '';
      const location = params.get('location') || '';
      document.getElementById('doneName').textContent = name;
      document.getElementById('donePhone').textContent = phone;
      document.getElementById('doneGoogle').textContent = location ? '✅ ' + location : '✅ Connected';
      goStep(3);
    }
    </script>
    </body></html>
    """
    return HTMLResponse(content=html)

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


@app.get("/debug/schema")
async def debug_database_schema():
    """Debug endpoint: Check database schema"""
    try:
        import sqlite3
        conn = sqlite3.connect(config.DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(businesses)")
        columns = cursor.fetchall()
        cursor.execute("SELECT * FROM businesses LIMIT 1")
        sample = cursor.fetchone()
        conn.close()
        
        return {
            "database_path": config.DATABASE_PATH,
            "businesses_columns": columns,
            "sample_record": sample,
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__class__.__name__}


# ==================== SCHEDULED SYNC ====================


@app.post("/cron/sync-all-reviews")
async def cron_sync_all_reviews():
    """
    Scheduled endpoint to sync reviews for all businesses with Google connected.
    Call this from a cron job (e.g. every 5 minutes).
    """
    try:
        businesses = db.list_businesses()
        results = []
        
        for business in businesses:
            if not business.google_refresh_token:
                continue
            
            try:
                from google_client import GoogleBusinessClient, parse_google_review
                
                client = GoogleBusinessClient(
                    client_id=config.GOOGLE_CLIENT_ID,
                    client_secret=config.GOOGLE_CLIENT_SECRET,
                    redirect_uri=config.GOOGLE_REDIRECT_URI,
                    refresh_token=business.google_refresh_token,
                )
                
                # Auto-discover location if needed
                location_id = business.google_location_id
                if not location_id:
                    try:
                        accounts = client.get_accounts()
                        if accounts:
                            account_name = accounts[0].get("name", "")
                            locations = client.get_locations(account_name)
                            if locations:
                                location_id = locations[0].get("name")
                                db.update_business_mapping(business.id, google_location_id=location_id)
                                logger.info(f"[CRON] Auto-discovered location for {business.name}: {location_id}")
                    except Exception as e:
                        logger.warning(f"[CRON] Location discovery failed for {business.name}: {e}")
                        results.append({"business": business.name, "status": "no_location"})
                        continue
                
                if not location_id:
                    results.append({"business": business.name, "status": "no_location"})
                    continue
                
                # Fetch reviews
                result = client.get_reviews(location_id)
                reviews = result.get("reviews", [])
                
                new_count = 0
                for google_review in reviews:
                    parsed = parse_google_review(google_review)
                    
                    # Skip if already has a reply
                    if parsed.get("has_reply"):
                        continue
                    
                    # Skip if we already processed this review
                    existing = db.get_review_by_google_id(parsed["google_review_id"])
                    if existing:
                        continue
                    
                    # Create review record
                    review_id = str(uuid.uuid4())
                    review = Review(
                        id=review_id,
                        business_id=business.id,
                        reviewer_name=parsed["reviewer_name"],
                        rating=StarRating(parsed["rating"]),
                        review_text=parsed["review_text"],
                        google_review_id=parsed["google_review_id"],
                        google_review_name=parsed["google_review_name"],
                    )
                    db.create_review(review)
                    
                    # Generate AI response
                    draft_text = ai_handler.generate_response(review, business)
                    draft_id = str(uuid.uuid4())
                    draft = DraftResponse(
                        id=draft_id,
                        review_id=review_id,
                        business_id=business.id,
                        draft_text=draft_text,
                        status="drafted",
                    )
                    db.create_draft_response(draft)
                    
                    # Send SMS approval
                    sms_message = build_sms_approval_message(
                        parsed["reviewer_name"],
                        StarRating(parsed["rating"]),
                        parsed["review_text"],
                        draft_text,
                    )
                    sms_handler.send_approval_request(business.sms_recipient, sms_message)
                    
                    # Create pending approval
                    approval = PendingApproval(
                        id=str(uuid.uuid4()),
                        draft_response_id=draft_id,
                        business_id=business.id,
                        sms_sent_at=datetime.utcnow(),
                        status=ApprovalStatus.PENDING,
                        sms_message=sms_message,
                    )
                    db.create_pending_approval(approval)
                    new_count += 1
                    
                    db.create_audit_event(
                        event_type="cron_review_detected",
                        business_id=business.id,
                        review_id=review_id,
                        message=f"[CRON] New review detected from {parsed['reviewer_name']}",
                        payload={"rating": parsed["rating"]},
                    )
                
                results.append({"business": business.name, "total": len(reviews), "new": new_count, "status": "synced"})
                logger.info(f"[CRON] Synced {business.name}: {new_count} new reviews out of {len(reviews)}")
                
            except Exception as e:
                logger.error(f"[CRON] Failed to sync {business.name}: {e}")
                results.append({"business": business.name, "status": "error", "error": str(e)})
        
        return {"synced_at": datetime.utcnow().isoformat(), "results": results}
        
    except Exception as e:
        logger.error(f"[CRON] Sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Include payment routes
app.include_router(payment_router)


def main():
    """Run the FastAPI application"""
    logger.info(
        f"Starting TradeReply API (debug={config.DEBUG}, dry_run_sms={config.DRY_RUN_SMS})"
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT, reload=config.DEBUG)


if __name__ == "__main__":
    main()
