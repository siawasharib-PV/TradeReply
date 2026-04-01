"""
AI prompt engineering for TradeReply
Generates polite, specific review responses using Gemini or OpenClaw API
"""

from models import Review, Business, StarRating


SYSTEM_PROMPT = """You are a professional business response writer for Google Business Profile reviews.
Your job is to draft polite, professional, and specific responses to customer reviews.

KEY REQUIREMENTS:
1. Keep responses concise (100-150 words max)
2. Address the reviewer by name when possible
3. For positive reviews (4-5 stars): Thank them warmly, highlight specific feedback they mentioned
4. For neutral reviews (3 stars): Acknowledge their feedback, offer to improve
5. For negative reviews (1-2 stars): Apologize sincerely, acknowledge their concerns, offer a solution
6. Never be generic - reference specific details from their review
7. Always maintain a professional, warm tone
8. Do NOT make promises about free meals, discounts, or compensation (unless instructed)
9. End with an invitation to discuss further if appropriate

TONE: Professional, warm, genuine. Sound like a real business owner/manager who cares.
"""


def get_system_prompt() -> str:
    """Return the system prompt for review responses"""
    return SYSTEM_PROMPT


def build_review_response_prompt(
    review: Review,
    business: Business,
) -> str:
    """
    Build the prompt for AI to draft a response to a review.
    
    Args:
        review: The customer review
        business: The business profile
        
    Returns:
        Formatted prompt string
    """
    
    star_label = {
        StarRating.ONE: "1 star (very negative)",
        StarRating.TWO: "2 stars (negative)",
        StarRating.THREE: "3 stars (neutral)",
        StarRating.FOUR: "4 stars (positive)",
        StarRating.FIVE: "5 stars (very positive)",
    }
    
    prompt = f"""Draft a response to this review for {business.name}.

BUSINESS CONTEXT:
- Name: {business.name}
- Description: {business.description or "N/A"}

REVIEW DETAILS:
- From: {review.reviewer_name}
- Rating: {star_label.get(review.rating, "Unknown")}
- Review Text: "{review.review_text}"

Please write a professional response that:
1. Addresses the specific points in their review
2. Maintains a warm, genuine tone
3. Is appropriate for the star rating they gave
4. Invites further dialogue if appropriate
5. Stays under 150 words

Begin your response directly without any preamble or explanation."""
    
    return prompt


def build_sms_approval_message(
    reviewer_name: str,
    rating: StarRating,
    review_text: str,
    draft_response: str,
    approval_id: str = None,
) -> str:
    """
    Build the SMS message to send to the business owner for approval.
    Short SMS with link to view full details on dashboard.
    """
    
    stars = "⭐" * rating.value
    
    # Very short preview
    review_preview = review_text[:60] + "..." if len(review_text) > 60 else review_text
    draft_preview = draft_response[:80] + "..." if len(draft_response) > 80 else draft_response
    
    message = f"""📝 New {rating.value}-star review {stars}

From: {reviewer_name}
"{review_preview}"

Draft reply:
"{draft_preview}"

✅ Reply YES to approve
❌ Reply NO to skip

View dashboard: web-production-e56a13.up.railway.app/ops/dashboard"""
    
    return message


def build_sms_confirmation_message(
    approved: bool,
    reviewer_name: str,
    rating: StarRating,
) -> str:
    """
    Build confirmation SMS to send to business owner after they approve/reject.
    
    Args:
        approved: True if approved, False if rejected
        reviewer_name: Name of the reviewer
        rating: Star rating of the review
        
    Returns:
        SMS confirmation message
    """
    stars = "⭐" * rating.value
    
    if approved:
        message = f"""✅ Approved! Your reply to {reviewer_name}'s {rating.value}-star review is ready.

Copy it from the dashboard:
web-production-e56a13.up.railway.app/ops/dashboard"""
    else:
        message = f"""👋 Skipped! Reply to {reviewer_name}'s {rating.value}-star review has been discarded.

You can always respond manually later."""
    
    return message
