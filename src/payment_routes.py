"""
Payment and subscription endpoints for TradeReply
"""

import logging
import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from stripe_handler import StripeHandler, PRICING_PLANS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])

# Initialize Stripe
stripe_api_key = os.getenv("STRIPE_API_KEY")
stripe_handler = StripeHandler(stripe_api_key) if stripe_api_key else None


class SubscriptionRequest(BaseModel):
    business_id: str
    business_name: str
    email: str
    plan: str  # "solo", "business", or "multi"


class SubscriptionResponse(BaseModel):
    success: bool
    client_secret: str = None
    error: str = None


@router.post("/create-subscription")
async def create_subscription(request: SubscriptionRequest) -> SubscriptionResponse:
    """Create a subscription for a business"""
    if not stripe_handler:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    try:
        # Get price ID for plan
        plan_config = PRICING_PLANS.get(request.plan)
        if not plan_config:
            raise HTTPException(status_code=400, detail="Invalid plan")
        
        price_id = plan_config["stripe_price_id"]
        
        # Create Stripe customer
        customer_result = stripe_handler.create_customer(
            request.business_id,
            request.business_name,
            request.email
        )
        
        if not customer_result["success"]:
            raise HTTPException(status_code=400, detail=customer_result["error"])
        
        customer_id = customer_result["customer_id"]
        
        # Create subscription
        subscription_result = stripe_handler.create_subscription(
            customer_id,
            price_id,
            request.business_id
        )
        
        if not subscription_result["success"]:
            raise HTTPException(status_code=400, detail=subscription_result["error"])
        
        return SubscriptionResponse(
            success=True,
            client_secret=subscription_result.get("client_secret")
        )
        
    except Exception as e:
        logger.error(f"Failed to create subscription: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events"""
    if not stripe_handler:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    try:
        payload = await request.body()
        signature = request.headers.get("stripe-signature")
        
        result = stripe_handler.handle_webhook(payload, signature)
        
        if result["success"]:
            logger.info(f"Webhook processed: {result.get('event_type')}")
            return {"status": "received"}
        else:
            raise HTTPException(status_code=400, detail=result.get("error"))
            
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
