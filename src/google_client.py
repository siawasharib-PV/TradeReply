"""
Google Business Profile API Client for TradeReply
Handles OAuth2 authentication and review/reply operations
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
import json

logger = logging.getLogger(__name__)


class GoogleBusinessClient:
    """Client for Google Business Profile API with OAuth2 support"""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        refresh_token: Optional[str] = None,
    ):
        """
        Initialize Google Business Profile client.
        
        Args:
            client_id: OAuth2 client ID from Google Cloud Console
            client_secret: OAuth2 client secret from Google Cloud Console
            redirect_uri: OAuth2 redirect URI (must match Google Cloud Console)
            refresh_token: Optional refresh token for existing connections
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.refresh_token = refresh_token
        self.credentials = None
        self.service = None

    def get_auth_url(self, state: Optional[str] = None) -> str:
        """
        Generate OAuth2 authorization URL for user to visit.
        
        Args:
            state: Optional state parameter for CSRF protection
            
        Returns:
            URL string for user to visit in browser
        """
        from google_auth_oauthlib.flow import Flow
        
        scopes = [
            "https://www.googleapis.com/auth/business.manage",
        ]
        
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=scopes,
            redirect_uri=self.redirect_uri,
        )
        
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",  # Always get refresh token
            state=state,
        )
        
        logger.info("Generated OAuth authorization URL")
        return auth_url

    def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token and refresh token.
        
        Args:
            code: Authorization code from OAuth callback
            
        Returns:
            Dict with access_token, refresh_token, and expiry
        """
        from google_auth_oauthlib.flow import Flow
        
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri],
                }
            },
            scopes=["https://www.googleapis.com/auth/business.manage"],
            redirect_uri=self.redirect_uri,
        )
        
        flow.fetch_token(code=code)
        credentials = flow.credentials
        
        self.refresh_token = credentials.refresh_token
        self.credentials = credentials
        
        logger.info("Successfully exchanged authorization code for tokens")
        
        return {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_at": credentials.expiry.isoformat() if credentials.expiry else None,
        }

    def _get_service(self):
        """Get or create Google Business Profile API service."""
        if self.service:
            return self.service

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            if not self.credentials and self.refresh_token:
                # Create credentials from refresh token
                self.credentials = Credentials(
                    token=None,
                    refresh_token=self.refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.client_id,
                    client_secret=self.client_secret,
                    scopes=["https://www.googleapis.com/auth/business.manage"],
                )
            
            if not self.credentials:
                raise ValueError("No credentials available. Run OAuth flow first.")
            
            # Build the service
            # Note: Using mybusinessaccountmanagement and mybusinessbusinessinformation APIs
            # The classic "mybusiness" API is deprecated
            self.service = build(
                "mybusinessbusinessinformation",
                "v1",
                credentials=self.credentials,
            )
            
            logger.info("Google Business Profile API service initialized")
            return self.service
            
        except Exception as e:
            logger.error(f"Failed to initialize Google API service: {e}")
            raise

    def get_accounts(self) -> List[Dict[str, Any]]:
        """
        List all Google Business Profile accounts accessible by the user.
        
        Returns:
            List of account dicts with name, accountName, etc.
        """
        try:
            # Note: This uses the Business Profile API v1
            # Documentation: https://developers.google.com/my-business/reference/businessinformation/rest/v1/accounts
            from googleapiclient.discovery import build
            
            # Need to use mybusinessaccountmanagement for accounts
            account_service = build(
                "mybusinessaccountmanagement",
                "v1",
                credentials=self.credentials,
            )
            
            accounts = account_service.accounts().list().execute()
            logger.info(f"Found {len(accounts.get('accounts', []))} Business Profile accounts")
            return accounts.get("accounts", [])
            
        except Exception as e:
            logger.error(f"Failed to fetch accounts: {e}")
            raise

    def get_locations(self, account_name: str) -> List[Dict[str, Any]]:
        """
        List all locations for a given Business Profile account.
        
        Args:
            account_name: Account resource name (e.g., "accounts/123456")
            
        Returns:
            List of location dicts
        """
        try:
            service = self._get_service()
            
            locations = (
                service.accounts()
                .locations()
                .list(parent=account_name, readMask="name,title,storefrontAddress,metadata")
                .execute()
            )
            
            logger.info(f"Found {len(locations.get('locations', []))} locations for {account_name}")
            return locations.get("locations", [])
            
        except Exception as e:
            logger.error(f"Failed to fetch locations: {e}")
            raise

    def get_reviews(
        self,
        location_name: str,
        page_size: int = 50,
        page_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch reviews for a location.
        
        Args:
            location_name: Location resource name (e.g., "accounts/123/locations/456")
            page_size: Number of reviews per page (max 200)
            page_token: Token for pagination
            
        Returns:
            Dict with reviews and nextPageToken
        """
        try:
            from googleapiclient.discovery import build
            
            # Reviews use the classic mybusiness API (still available)
            reviews_service = build(
                "mybusiness",
                "v4",
                credentials=self.credentials,
                discoveryServiceUrl="https://developers.google.com/my-business/samples/mybusiness_google_rest_v4p9.json",
            )
            
            request_params = {
                "parent": location_name,
                "pageSize": page_size,
            }
            
            if page_token:
                request_params["pageToken"] = page_token
            
            result = (
                reviews_service.accounts()
                .locations()
                .reviews()
                .list(**request_params)
                .execute()
            )
            
            reviews = result.get("reviews", [])
            logger.info(f"Fetched {len(reviews)} reviews from {location_name}")
            
            return {
                "reviews": reviews,
                "next_page_token": result.get("nextPageToken"),
                "total_review_count": result.get("totalReviewCount", len(reviews)),
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch reviews: {e}")
            raise

    def post_reply(
        self,
        review_name: str,
        reply_text: str,
    ) -> Dict[str, Any]:
        """
        Post a reply to a review.
        
        Args:
            review_name: Review resource name (e.g., "accounts/123/locations/456/reviews/789")
            reply_text: The reply text to post
            
        Returns:
            Dict with reply details
        """
        try:
            from googleapiclient.discovery import build
            
            # Reviews use the classic mybusiness API
            reviews_service = build(
                "mybusiness",
                "v4",
                credentials=self.credentials,
                discoveryServiceUrl="https://developers.google.com/my-business/samples/mybusiness_google_rest_v4p9.json",
            )
            
            reply_body = {
                "comment": reply_text,
            }
            
            result = (
                reviews_service.accounts()
                .locations()
                .reviews()
                .reply(name=review_name, body=reply_body)
                .execute()
            )
            
            logger.info(f"Posted reply to review {review_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to post reply: {e}")
            raise

    def get_review(self, review_name: str) -> Dict[str, Any]:
        """
        Get details of a specific review.
        
        Args:
            review_name: Review resource name
            
        Returns:
            Review dict with all details
        """
        try:
            from googleapiclient.discovery import build
            
            reviews_service = build(
                "mybusiness",
                "v4",
                credentials=self.credentials,
                discoveryServiceUrl="https://developers.google.com/my-business/samples/mybusiness_google_rest_v4p9.json",
            )
            
            result = (
                reviews_service.accounts()
                .locations()
                .reviews()
                .get(name=review_name)
                .execute()
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to get review: {e}")
            raise


def parse_google_review(review: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a Google review dict into TradeReply format.
    
    Args:
        review: Raw review dict from Google API
        
    Returns:
        Normalized review dict for TradeReply
    """
    # Extract star rating from review
    star_rating = review.get("starRating", "FIVE").upper()
    rating_map = {
        "ONE": 1,
        "TWO": 2,
        "THREE": 3,
        "FOUR": 4,
        "FIVE": 5,
    }
    
    return {
        "google_review_id": review.get("name", "").split("/")[-1],
        "google_review_name": review.get("name"),
        "reviewer_name": review.get("reviewer", {}).get("displayName", "Anonymous"),
        "rating": rating_map.get(star_rating, 5),
        "review_text": review.get("comment", ""),
        "created_at": review.get("createTime"),
        "updated_at": review.get("updateTime"),
        "has_reply": "reviewReply" in review,
        "reply_text": review.get("reviewReply", {}).get("comment") if "reviewReply" in review else None,
        "reply_time": review.get("reviewReply", {}).get("updateTime") if "reviewReply" in review else None,
    }
