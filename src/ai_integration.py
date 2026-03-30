"""
AI integration for TradeReply
Handles calls to Gemini or OpenClaw API for generating review responses
"""

import logging
from typing import Optional
from models import Review, Business
from prompts import get_system_prompt, build_review_response_prompt
from config import Config

logger = logging.getLogger(__name__)


class AIHandler:
    """Handle AI-powered response generation"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "gemini-2.0-flash",
        dry_run: bool = False,
    ):
        """
        Initialize AI handler.
        
        Args:
            api_key: Gemini API key
            model_name: Model to use (e.g., "gemini-2.0-flash")
            dry_run: If True, use mock responses
        """
        self.api_key = api_key or Config.GEMINI_API_KEY
        self.model_name = model_name
        self.dry_run = dry_run
        self.client = None

        if not dry_run and self.api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=self.api_key)
                self.client = genai
                logger.info(f"Gemini client initialized with model: {model_name}")
            except ImportError:
                logger.warning("google-generativeai package not installed, using dry-run")
                self.dry_run = True
        elif dry_run:
            logger.info("AI handler in DRY_RUN mode (mock responses)")

    def generate_response(
        self,
        review: Review,
        business: Business,
    ) -> str:
        """
        Generate a professional response to a review using AI.
        
        Args:
            review: The customer review
            business: The business profile
            
        Returns:
            AI-generated response text
        """
        if self.dry_run:
            return self._mock_response(review, business)

        if not self.client:
            logger.error("AI client not initialized")
            return self._mock_response(review, business)

        try:
            system_prompt = get_system_prompt()
            user_prompt = build_review_response_prompt(review, business)

            model = self.client.GenerativeModel(
                self.model_name,
                system_instruction=system_prompt,
            )

            response = model.generate_content(user_prompt)
            generated_text = response.text.strip()

            logger.info(f"Generated response for review {review.id}")
            return generated_text

        except Exception as e:
            logger.error(f"AI generation failed: {str(e)}")
            return self._mock_response(review, business)

    def _mock_response(self, review: Review, business: Business) -> str:
        """
        Generate a mock response for testing/dry-run.
        
        Args:
            review: The customer review
            business: The business profile
            
        Returns:
            A plausible mock response
        """
        if review.rating.value >= 4:
            template = f"Thank you {review.reviewer_name} for the kind words! We're thrilled you enjoyed your experience at {business.name}. We look forward to seeing you again soon!"
        elif review.rating.value == 3:
            template = f"Hi {review.reviewer_name}, thank you for taking the time to share your feedback with us. We appreciate your suggestions and will work to improve. We'd love to serve you better next time at {business.name}."
        else:
            template = f"Dear {review.reviewer_name}, we sincerely apologize that your experience at {business.name} didn't meet your expectations. Your feedback is important to us. Please contact us directly so we can make things right."

        return template
