# TradeReply Quick Start

Get up and running in 5 minutes.

## 1. Install Dependencies

```bash
cd /Users/macmini/.openclaw/workspace/tradereply
pip install -r requirements.txt
```

## 2. Run Tests (Verify Everything Works)

```bash
python tests/test_harness.py
```

You should see:
```
✅ Test 1: 5-Star Positive Review passed
✅ Test 2: 1-Star Negative Review passed
✅ Test 3: 3-Star Neutral Review passed
✅ Test 4: Database Operations passed
✅ Test 5: Approval Workflow passed

🎉 ALL TESTS PASSED!
```

## 3. Start the API Server

In one terminal:
```bash
cd src
python -m uvicorn app:app --reload
```

Output:
```
INFO:     Application startup complete
INFO:     Uvicorn running on http://0.0.0.0:8000
```

## 4. Test an Endpoint

In another terminal:

**Create a business:**
```bash
BUSINESS_ID=$(curl -s -X POST http://localhost:8000/businesses \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=Pada's Pizzeria&phone=(02) 9999-0000&sms_recipient=%2B61402707102&description=Award-winning pizzeria" | jq -r '.business_id')

echo "Business ID: $BUSINESS_ID"
```

**Submit a review (triggers full flow):**
```bash
curl -X POST http://localhost:8000/reviews \
  -H "Content-Type: application/json" \
  -d "{
    \"business_id\": \"$BUSINESS_ID\",
    \"reviewer_name\": \"Marco Giuseppe\",
    \"rating\": 5,
    \"review_text\": \"Amazing pizza! Crispy crust and fresh mozzarella. Will definitely be back!\",
    \"reviewer_email\": \"marco@email.com\"
  }" | jq .
```

Output example:
```json
{
  "review_id": "abc123...",
  "draft_id": "def456...",
  "approval_id": "ghi789...",
  "status": "awaiting_approval",
  "draft": "Thank you Marco Giuseppe for the wonderful feedback! We're thrilled you enjoyed the perfect balance of crispy crust and fresh mozzarella. Your appreciation for quality ingredients inspires us to keep delivering the best. We look forward to your next visit!",
  "sms_sent_to": "+61402707102"
}
```

**Check pending approvals:**
```bash
curl http://localhost:8000/businesses/$BUSINESS_ID/approvals | jq .
```

## 5. Understand the Flow

```
Review Submitted
    ↓
✅ Stored in database
    ↓
🤖 AI generates draft response
    ↓
✅ Draft stored in database
    ↓
📱 SMS sent to business owner (or logged in dry-run mode)
    ↓
✅ Approval request tracked in database
    ↓
👨‍💼 Business owner replies YES/NO (simulated via API)
    ↓
✅ Approval status updated
    ↓
✅ Ready to post (Phase 2: Google API)
```

## 6. Enable Real Gemini API (Optional)

If you have a Gemini API key:

```bash
export GEMINI_API_KEY=your_api_key_here
# Then restart the server
```

The AI will now generate real responses instead of mocks.

## 7. Explore the Code

- **`src/app.py`**: FastAPI endpoints and main logic
- **`src/models.py`**: Data structures (Business, Review, etc.)
- **`src/db_helper.py`**: Database operations
- **`src/ai_integration.py`**: Gemini AI integration
- **`src/sms_handler.py`**: SMS sending logic
- **`src/prompts.py`**: AI prompt engineering
- **`tests/test_harness.py`**: Complete test scenarios

## Next Steps

1. ✅ Review the code structure
2. ✅ Understand the database schema (see README.md)
3. ✅ Customize prompts in `src/prompts.py` for your brand
4. ⏭️ Phase 2: Integrate Google Business Profile API
5. ⏭️ Phase 2: Add Twilio webhook for live SMS responses

## Debug Commands

**Check database status:**
```bash
curl http://localhost:8000/debug/database | jq .
```

**Get all reviews for a business:**
```bash
curl http://localhost:8000/debug/reviews/$BUSINESS_ID | jq .
```

**View logs:**
```bash
tail -f tradereply.log
```

## Common Issues

**"ModuleNotFoundError: No module named 'fastapi'"**
→ Did you run `pip install -r requirements.txt`?

**"Port 8000 already in use"**
```bash
lsof -i :8000
kill -9 <PID>
```

**"GEMINI_API_KEY not set"**
→ In development, mock responses are fine. Set the env var for real AI.

---

That's it! You now have a working TradeReply scaffold. 🎉
