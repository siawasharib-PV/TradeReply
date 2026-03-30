"""
Testing harness for TradeReply
Simulates complete flow: review submission → draft generation → SMS approval → response posting
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import logging
import uuid
from datetime import datetime
from models import Business, Review, StarRating, ApprovalStatus
from db_helper import DatabaseHelper
from ai_integration import AIHandler
from sms_handler import SMSHandler
from prompts import build_sms_approval_message

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def test_scenario_1_positive_review():
    """Test: 5-star positive review"""
    logger.info("=" * 60)
    logger.info("TEST 1: 5-Star Positive Review")
    logger.info("=" * 60)

    # Initialize components
    db = DatabaseHelper(":memory:")
    db.connect()
    db.init_schema()

    ai_handler = AIHandler(dry_run=True)
    sms_handler = SMSHandler(dry_run=True)

    # Create business
    business = Business(
        id="padaspizzeria",
        name="Pada's Pizzeria",
        phone="(02) 9999-0000",
        sms_recipient="+61402707102",
        description="Award-winning pizzeria in Sydney CBD. Authentic Italian recipes since 2010.",
    )
    db.create_business(business)
    logger.info(f"✅ Created business: {business.name}")

    # Create a 5-star review
    review = Review(
        id=str(uuid.uuid4()),
        business_id=business.id,
        reviewer_name="Marco Giuseppe",
        rating=StarRating.FIVE,
        review_text="Absolutely fantastic! The margherita pizza was perfection - crispy crust, fresh mozzarella, amazing basil. Marco truly knows his craft. Will definitely be back!",
        reviewer_email="marco@email.com",
    )
    db.create_review(review)
    logger.info(f"✅ Created review from {review.reviewer_name}: {review.rating.value}⭐")

    # Generate AI draft response
    draft_text = ai_handler.generate_response(review, business)
    logger.info(f"✅ AI Draft Response:\n  {draft_text}\n")

    # Build SMS message
    sms_message = build_sms_approval_message(
        review.reviewer_name,
        review.rating,
        review.review_text,
        draft_text,
    )
    logger.info(f"✅ SMS Message:\n  {sms_message}\n")

    # Send approval SMS
    sms_result = sms_handler.send_approval_request(
        business.sms_recipient,
        sms_message,
    )
    logger.info(f"✅ SMS {'sent' if sms_result['success'] else 'failed'}")

    logger.info("✅ Test 1 passed!\n")


def test_scenario_2_negative_review():
    """Test: 1-star negative review"""
    logger.info("=" * 60)
    logger.info("TEST 2: 1-Star Negative Review")
    logger.info("=" * 60)

    db = DatabaseHelper(":memory:")
    db.connect()
    db.init_schema()

    ai_handler = AIHandler(dry_run=True)
    sms_handler = SMSHandler(dry_run=True)

    # Create business
    business = Business(
        id="padaspizzeria2",
        name="Pada's Pizzeria",
        phone="(02) 9999-0000",
        sms_recipient="+61402707102",
        description="Award-winning pizzeria in Sydney CBD.",
    )
    db.create_business(business)
    logger.info(f"✅ Created business: {business.name}")

    # Create a 1-star review
    review = Review(
        id=str(uuid.uuid4()),
        business_id=business.id,
        reviewer_name="Unhappy Customer",
        rating=StarRating.ONE,
        review_text="Terrible experience. Waited 45 minutes for a pizza that arrived cold. The staff was rude and dismissive when we complained. Not coming back.",
        reviewer_email="upset@email.com",
    )
    db.create_review(review)
    logger.info(f"✅ Created review from {review.reviewer_name}: {review.rating.value}⭐")

    # Generate AI draft
    draft_text = ai_handler.generate_response(review, business)
    logger.info(f"✅ AI Draft Response:\n  {draft_text}\n")

    # Build SMS
    sms_message = build_sms_approval_message(
        review.reviewer_name,
        review.rating,
        review.review_text,
        draft_text,
    )
    logger.info(f"✅ SMS Message:\n  {sms_message}\n")

    # Send SMS
    sms_result = sms_handler.send_approval_request(
        business.sms_recipient,
        sms_message,
    )
    logger.info(f"✅ SMS {'sent' if sms_result['success'] else 'failed'}")

    logger.info("✅ Test 2 passed!\n")


def test_scenario_3_neutral_review():
    """Test: 3-star neutral review"""
    logger.info("=" * 60)
    logger.info("TEST 3: 3-Star Neutral Review")
    logger.info("=" * 60)

    db = DatabaseHelper(":memory:")
    db.connect()
    db.init_schema()

    ai_handler = AIHandler(dry_run=True)
    sms_handler = SMSHandler(dry_run=True)

    # Create business
    business = Business(
        id="padaspizzeria3",
        name="Pada's Pizzeria",
        phone="(02) 9999-0000",
        sms_recipient="+61402707102",
        description="Pizzeria in Sydney CBD.",
    )
    db.create_business(business)
    logger.info(f"✅ Created business: {business.name}")

    # Create a 3-star review
    review = Review(
        id=str(uuid.uuid4()),
        business_id=business.id,
        reviewer_name="Sarah Thompson",
        rating=StarRating.THREE,
        review_text="Good pizza but service could be better. Waited 20 minutes at the counter to order. Place gets crowded quickly.",
        reviewer_email="sarah@email.com",
    )
    db.create_review(review)
    logger.info(f"✅ Created review from {review.reviewer_name}: {review.rating.value}⭐")

    # Generate AI draft
    draft_text = ai_handler.generate_response(review, business)
    logger.info(f"✅ AI Draft Response:\n  {draft_text}\n")

    # Build SMS
    sms_message = build_sms_approval_message(
        review.reviewer_name,
        review.rating,
        review.review_text,
        draft_text,
    )
    logger.info(f"✅ SMS Message:\n  {sms_message}\n")

    # Send SMS
    sms_result = sms_handler.send_approval_request(
        business.sms_recipient,
        sms_message,
    )
    logger.info(f"✅ SMS {'sent' if sms_result['success'] else 'failed'}")

    logger.info("✅ Test 3 passed!\n")


def test_database_operations():
    """Test: Database CRUD operations"""
    logger.info("=" * 60)
    logger.info("TEST 4: Database Operations")
    logger.info("=" * 60)

    db = DatabaseHelper(":memory:")
    db.connect()
    db.init_schema()

    # Test business creation and retrieval
    business = Business(
        id="test-biz",
        name="Test Business",
        phone="555-0000",
        sms_recipient="+61402707102",
    )
    assert db.create_business(business), "Failed to create business"
    retrieved = db.get_business("test-biz")
    assert retrieved is not None, "Failed to retrieve business"
    logger.info("✅ Business CRUD works")

    # Test review creation and retrieval
    review = Review(
        id="test-review",
        business_id="test-biz",
        reviewer_name="Test User",
        rating=StarRating.FOUR,
        review_text="Test review text",
    )
    assert db.create_review(review), "Failed to create review"
    retrieved = db.get_review("test-review")
    assert retrieved is not None, "Failed to retrieve review"
    logger.info("✅ Review CRUD works")

    # Test business review listing
    reviews = db.get_reviews_by_business("test-biz")
    assert len(reviews) == 1, "Failed to list reviews"
    logger.info("✅ Business review listing works")

    logger.info("✅ Test 4 passed!\n")


def test_approval_workflow():
    """Test: Approval workflow"""
    logger.info("=" * 60)
    logger.info("TEST 5: Approval Workflow")
    logger.info("=" * 60)

    db = DatabaseHelper(":memory:")
    db.connect()
    db.init_schema()

    # Setup
    from models import DraftResponse, PendingApproval

    business_id = "test-biz"
    review_id = "test-review"
    draft_id = "test-draft"
    approval_id = "test-approval"

    # Create business and review
    business = Business(
        id=business_id,
        name="Test Biz",
        phone="555-0000",
        sms_recipient="+61402707102",
    )
    db.create_business(business)

    review = Review(
        id=review_id,
        business_id=business_id,
        reviewer_name="John",
        rating=StarRating.FOUR,
        review_text="Good!",
    )
    db.create_review(review)

    # Create draft
    draft = DraftResponse(
        id=draft_id,
        review_id=review_id,
        business_id=business_id,
        draft_text="Thank you John!",
    )
    db.create_draft_response(draft)
    logger.info("✅ Created draft response")

    # Create pending approval
    approval = PendingApproval(
        id=approval_id,
        draft_response_id=draft_id,
        business_id=business_id,
        sms_sent_at=datetime.utcnow(),
        status=ApprovalStatus.PENDING,
        sms_message="Test SMS",
    )
    db.create_pending_approval(approval)
    retrieved = db.get_pending_approval(approval_id)
    assert retrieved is not None, "Failed to create approval"
    assert retrieved.status == ApprovalStatus.PENDING, "Approval status incorrect"
    logger.info("✅ Created pending approval")

    # Update approval status
    db.update_approval_status(
        approval_id, ApprovalStatus.APPROVED, datetime.utcnow()
    )
    updated = db.get_pending_approval(approval_id)
    assert updated.status == ApprovalStatus.APPROVED, "Failed to update approval"
    logger.info("✅ Updated approval status to APPROVED")

    logger.info("✅ Test 5 passed!\n")


def main():
    """Run all tests"""
    logger.info("\n🧪 TradeReply Test Harness\n")

    try:
        test_database_operations()
        test_scenario_1_positive_review()
        test_scenario_2_negative_review()
        test_scenario_3_neutral_review()
        test_approval_workflow()

        logger.info("=" * 60)
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("=" * 60)

    except AssertionError as e:
        logger.error(f"❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
