"""
Stripe payment integration for TradeReply subscriptions
"""

import logging
import stripe
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class StripeHandler:
    """Handle Stripe payment processing"""

    def __init__(self, api_key: str):
        """Initialize Stripe handler"""
        stripe.api_key = api_key
        self.api_key = api_key
        logger.info("Stripe handler initialized")

    def create_customer(self, business_id: str, business_name: str, email: str) -> Dict[str, Any]:
        """Create a Stripe customer"""
        try:
            customer = stripe.Customer.create(
                email=email,
                name=business_name,
                metadata={"business_id": business_id},
            )
            logger.info(f"Created Stripe customer {customer.id} for {business_name}")
            return {
                "success": True,
                "customer_id": customer.id,
                "email": customer.email,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            return {"success": False, "error": str(e)}

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        business_id: str,
    ) -> Dict[str, Any]:
        """Create a subscription for a customer"""
        try:
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{"price": price_id}],
                metadata={"business_id": business_id},
                payment_behavior="default_incomplete",
                expand=["latest_invoice.payment_intent"],
            )
            logger.info(f"Created subscription {subscription.id} for customer {customer_id}")
            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "client_secret": subscription.latest_invoice.payment_intent.client_secret,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create subscription: {e}")
            return {"success": False, "error": str(e)}

    def cancel_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Cancel a subscription"""
        try:
            subscription = stripe.Subscription.delete(subscription_id)
            logger.info(f"Cancelled subscription {subscription_id}")
            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Failed to cancel subscription: {e}")
            return {"success": False, "error": str(e)}

    def get_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Get subscription details"""
        try:
            subscription = stripe.Subscription.retrieve(subscription_id)
            return {
                "success": True,
                "subscription_id": subscription.id,
                "status": subscription.status,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
        except stripe.error.StripeError as e:
            logger.error(f"Failed to get subscription: {e}")
            return {"success": False, "error": str(e)}

    def handle_webhook(self, payload: bytes, signature: str) -> Dict[str, Any]:
        """Handle Stripe webhook events"""
        try:
            event = stripe.Webhook.construct_event(
                payload, signature, self.api_key
            )
            
            if event["type"] == "customer.subscription.updated":
                logger.info(f"Subscription updated: {event['data']['object']['id']}")
                return {"success": True, "event_type": "subscription_updated"}
            
            elif event["type"] == "customer.subscription.deleted":
                logger.info(f"Subscription cancelled: {event['data']['object']['id']}")
                return {"success": True, "event_type": "subscription_cancelled"}
            
            elif event["type"] == "invoice.payment_succeeded":
                logger.info(f"Payment succeeded: {event['data']['object']['id']}")
                return {"success": True, "event_type": "payment_succeeded"}
            
            elif event["type"] == "invoice.payment_failed":
                logger.error(f"Payment failed: {event['data']['object']['id']}")
                return {"success": True, "event_type": "payment_failed"}
            
            return {"success": True, "event_type": "unknown"}
            
        except ValueError as e:
            logger.error(f"Invalid webhook payload: {e}")
            return {"success": False, "error": "Invalid payload"}
        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return {"success": False, "error": "Invalid signature"}


# Pricing tiers (update these with your actual Stripe price IDs)
PRICING_PLANS = {
    "solo": {
        "name": "Solo",
        "price": 2900,  # $29.00 in cents
        "currency": "aud",
        "reviews_per_month": 20,
        "stripe_price_id": "price_solo_aud",  # Replace with actual Stripe price ID
    },
    "business": {
        "name": "Business",
        "price": 5900,  # $59.00 in cents
        "currency": "aud",
        "reviews_per_month": 50,
        "stripe_price_id": "price_business_aud",  # Replace with actual Stripe price ID
    },
    "multi": {
        "name": "Multi-Location",
        "price": 14900,  # $149.00 in cents
        "currency": "aud",
        "reviews_per_month": float("inf"),
        "stripe_price_id": "price_multi_aud",  # Replace with actual Stripe price ID
    },
}
