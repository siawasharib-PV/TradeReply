import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock
import importlib
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from db_helper import DatabaseHelper
from google_client import GoogleBusinessClient
from models import ApprovalStatus, Business, DraftResponse, PendingApproval, Response, Review, StarRating
from prompts import build_sms_approval_message


def import_app_with_stubs():
    from fastapi import APIRouter

    fake_stripe_handler = types.ModuleType("stripe_handler")

    class FakeStripeHandler:
        pass

    fake_stripe_handler.StripeHandler = FakeStripeHandler
    fake_stripe_handler.PRICING_PLANS = {}

    fake_payment_routes = types.ModuleType("payment_routes")
    fake_payment_routes.router = APIRouter()

    with mock.patch.dict(
        sys.modules,
        {
            "stripe_handler": fake_stripe_handler,
            "payment_routes": fake_payment_routes,
        },
    ), mock.patch("logging.FileHandler", side_effect=lambda *args, **kwargs: logging.NullHandler()):
        if "app" in sys.modules:
            del sys.modules["app"]
        return importlib.import_module("app")


class Phase1AutomationTests(unittest.TestCase):
    def test_get_review_preserves_google_identifiers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tradereply.db"
            db = DatabaseHelper(str(db_path))
            db.connect()
            db.init_schema()

            business = Business(
                id="biz-1",
                name="Trade Reply Test",
                phone="+61400000000",
                sms_recipient="+61400000000",
            )
            self.assertTrue(db.create_business(business))

            review = Review(
                id="review-1",
                business_id=business.id,
                reviewer_name="Jane",
                rating=StarRating.FIVE,
                review_text="Great service",
                google_review_id="abc123",
                google_review_name="accounts/1/locations/2/reviews/abc123",
            )
            self.assertTrue(db.create_review(review))

            stored = db.get_review(review.id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.google_review_id, "abc123")
            self.assertEqual(
                stored.google_review_name,
                "accounts/1/locations/2/reviews/abc123",
            )

            db.disconnect()

    def test_google_client_post_reply_initializes_credentials_from_refresh_token(self):
        build_calls = {}

        class FakeCredentials:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeReplyRequest:
            def execute(self):
                return {"status": "ok"}

        class FakeReviewsResource:
            def reply(self, name, body):
                build_calls["reply_name"] = name
                build_calls["reply_body"] = body
                return FakeReplyRequest()

        class FakeLocationsResource:
            def reviews(self):
                return FakeReviewsResource()

        class FakeAccountsResource:
            def locations(self):
                return FakeLocationsResource()

        class FakeService:
            def accounts(self):
                return FakeAccountsResource()

        def fake_build(api_name, version, credentials=None, discoveryServiceUrl=None):
            build_calls["api_name"] = api_name
            build_calls["version"] = version
            build_calls["credentials"] = credentials
            build_calls["discoveryServiceUrl"] = discoveryServiceUrl
            return FakeService()

        client = GoogleBusinessClient(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="https://example.com/callback",
            refresh_token="refresh-token",
        )

        fake_googleapiclient = types.ModuleType("googleapiclient")
        fake_googleapiclient_discovery = types.ModuleType("googleapiclient.discovery")
        fake_googleapiclient_discovery.build = fake_build
        fake_google = types.ModuleType("google")
        fake_google_oauth2 = types.ModuleType("google.oauth2")
        fake_google_oauth2_credentials = types.ModuleType("google.oauth2.credentials")
        fake_google_oauth2_credentials.Credentials = FakeCredentials

        with mock.patch.dict(
            sys.modules,
            {
                "googleapiclient": fake_googleapiclient,
                "googleapiclient.discovery": fake_googleapiclient_discovery,
                "google": fake_google,
                "google.oauth2": fake_google_oauth2,
                "google.oauth2.credentials": fake_google_oauth2_credentials,
            },
        ):
            result = client.post_reply(
                "accounts/1/locations/2/reviews/3",
                "Thanks for the review!",
            )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(build_calls["api_name"], "mybusiness")
        self.assertEqual(build_calls["version"], "v4")
        self.assertIsNotNone(build_calls["credentials"])
        self.assertEqual(
            build_calls["reply_name"],
            "accounts/1/locations/2/reviews/3",
        )
        self.assertEqual(
            build_calls["reply_body"],
            {"comment": "Thanks for the review!"},
        )

    def test_business_metrics_include_posted_and_pending_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "tradereply.db"
            db = DatabaseHelper(str(db_path))
            db.connect()
            db.init_schema()

            business = Business(
                id="biz-2",
                name="Metrics Test",
                phone="+61400000001",
                sms_recipient="+61400000001",
            )
            self.assertTrue(db.create_business(business))

            review = Review(
                id="review-2",
                business_id=business.id,
                reviewer_name="Chris",
                rating=StarRating.FOUR,
                review_text="Solid work",
                google_review_id="def456",
                google_review_name="accounts/1/locations/2/reviews/def456",
            )
            self.assertTrue(db.create_review(review))

            draft = DraftResponse(
                id="draft-2",
                review_id=review.id,
                business_id=business.id,
                draft_text="Thanks Chris",
                status="posted",
            )
            self.assertTrue(db.create_draft_response(draft))

            approval = PendingApproval(
                id="approval-2",
                draft_response_id=draft.id,
                business_id=business.id,
                sms_sent_at=draft.created_at,
                status=ApprovalStatus.POSTED,
            )
            self.assertTrue(db.create_pending_approval(approval))

            response = Response(
                id="response-2",
                review_id=review.id,
                business_id=business.id,
                response_text="Thanks Chris",
            )
            self.assertTrue(db.create_response(response))

            metrics = db.get_business_metrics(business.id)
            self.assertEqual(metrics["reviews_received"], 1)
            self.assertEqual(metrics["drafts_generated"], 1)
            self.assertEqual(metrics["posted"], 1)
            self.assertEqual(metrics["awaiting_approval"], 0)
            self.assertGreaterEqual(metrics["approval_rate"], 1.0)

            db.disconnect()

    def test_sms_approval_message_includes_edit_link_when_provided(self):
        message = build_sms_approval_message(
            reviewer_name="Sam",
            rating=StarRating.FIVE,
            review_text="Fantastic experience",
            draft_response="Thanks so much for the kind words!",
            approval_id="approval-123",
            edit_url="https://tradereply.example/approvals/approval-123/edit",
        )
        self.assertIn("Reply YES to approve", message)
        self.assertIn("Reply NO to skip", message)
        self.assertIn("Edit before posting", message)
        self.assertIn("https://tradereply.example/approvals/approval-123/edit", message)

    def test_signed_approval_token_round_trip(self):
        app_module = import_app_with_stubs()
        token = app_module._generate_approval_token("approval-xyz")
        approval_id = app_module._verify_approval_token(token)
        self.assertEqual(approval_id, "approval-xyz")
        self.assertIn("/approvals/edit?token=", app_module._approval_edit_url("approval-xyz"))

    def test_tampered_approval_token_is_rejected(self):
        app_module = import_app_with_stubs()
        token = app_module._generate_approval_token("approval-xyz")
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with self.assertRaises(Exception):
            app_module._verify_approval_token(tampered)


if __name__ == "__main__":
    unittest.main()
