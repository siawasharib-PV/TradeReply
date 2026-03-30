import os
from twilio.rest import Client

def send_sms(to_number, review_text, reply_text, business_name='Pada\'s Pizzeria', star_rating='5-star'):
    """
    Sends an SMS message using Twilio.
    Twilio Account SID, Auth Token, and Phone Number are read from environment variables.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_PHONE_NUMBER")

    if not all([account_sid, auth_token, from_number]):
        return {"status": "error", "message": "Missing Twilio environment variables (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)."}

    body_text = f"""New {star_rating} review for '{business_name}':

CUSTOMER REVIEW:
"{review_text}"

PROPOSED REPLY:
"{reply_text}"

ACTIONS:
Reply 'APPROVE' to publish.
Reply 'REJECT' to discard.
Reply 'EDIT' to modify."""

    try:
        client = Client(account_sid, auth_token)
        message = client.messages.create(
            to=to_number,
            from_=from_number,
            body=body_text
        )
        return {"status": "success", "sid": message.sid, "to": message.to, "from": message.from_}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import sys
    if len(sys.argv) == 4:
        to_number = sys.argv[1]
        review = sys.argv[2]
        reply = sys.argv[3]
        result = send_sms(to_number, review, reply)
        print(result)
    else:
        print("Usage: python3 send_sms.py <to_number> <customer_review> <proposed_reply>")