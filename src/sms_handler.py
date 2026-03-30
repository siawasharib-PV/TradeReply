"""
SMS handler for TradeReply
Manages sending approval requests via Twilio and processing responses
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SMSHandler:
    """Handle SMS operations with Twilio"""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: str = "+61468155994",
        dry_run: bool = False,
    ):
        """
        Initialize SMS handler.
        
        Args:
            account_sid: Twilio account SID
            auth_token: Twilio auth token
            from_number: Twilio phone number to send from
            dry_run: If True, log instead of actually sending SMS
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.dry_run = dry_run
        self.client = None

        if not dry_run and account_sid and auth_token:
            try:
                from twilio.rest import Client

                self.client = Client(account_sid, auth_token)
                logger.info("Twilio client initialized")
            except ImportError:
                logger.warning("twilio package not installed, running in dry-run mode")
                self.dry_run = True

    def send_approval_request(
        self,
        recipient_phone: str,
        message: str,
    ) -> dict:
        """
        Send SMS approval request to business owner.
        
        Args:
            recipient_phone: Phone number to send to (e.g., "+61402707102")
            message: SMS message body
            
        Returns:
            Dict with 'success', 'message_sid' (if sent), and 'log' entry
        """
        timestamp = datetime.utcnow().isoformat()

        if self.dry_run or not self.client:
            log_entry = {
                "timestamp": timestamp,
                "to": recipient_phone,
                "from": self.from_number,
                "body": message,
                "mode": "dry_run",
                "status": "logged",
            }
            logger.info(f"[DRY RUN] SMS to {recipient_phone}: {message[:100]}...")
            return {
                "success": True,
                "message_sid": f"dry_run_{timestamp}",
                "log": log_entry,
            }

        try:
            sms = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=recipient_phone,
            )
            log_entry = {
                "timestamp": timestamp,
                "to": recipient_phone,
                "from": self.from_number,
                "body": message,
                "message_sid": sms.sid,
                "status": sms.status,
            }
            logger.info(f"SMS sent to {recipient_phone} (SID: {sms.sid})")
            return {
                "success": True,
                "message_sid": sms.sid,
                "log": log_entry,
            }
        except Exception as e:
            logger.error(f"Failed to send SMS to {recipient_phone}: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "log": {
                    "timestamp": timestamp,
                    "to": recipient_phone,
                    "status": "failed",
                    "error": str(e),
                },
            }

    def parse_approval_response(self, response_text: str) -> Optional[bool]:
        """
        Parse YES/NO response from SMS.
        
        Args:
            response_text: The SMS response text
            
        Returns:
            True if YES, False if NO, None if unclear
        """
        normalized = response_text.strip().upper()

        if normalized in ["YES", "Y", "APPROVE", "APPROVED", "CONFIRM"]:
            return True
        elif normalized in ["NO", "N", "REJECT", "REJECTED", "DECLINE"]:
            return False
        else:
            return None

    def log_sms_interaction(
        self,
        direction: str,  # "outbound" or "inbound"
        phone: str,
        message: str,
        message_sid: str,
        timestamp: datetime,
    ) -> dict:
        """
        Log an SMS interaction for audit trail.
        
        Args:
            direction: "outbound" or "inbound"
            phone: Phone number involved
            message: Message text
            message_sid: Unique message ID
            timestamp: When interaction occurred
            
        Returns:
            Log entry dict
        """
        log_entry = {
            "direction": direction,
            "phone": phone,
            "message": message,
            "message_sid": message_sid,
            "timestamp": timestamp.isoformat(),
        }
        logger.info(f"[{direction.upper()}] {phone}: {message[:80]}...")
        return log_entry
