# TradeReply - Micro-SaaS Review Response System

A FastAPI-based system that monitors Google Business Profile reviews, generates AI-drafted responses, and sends SMS approval requests to business owners.

**Phase 1**: Local development scaffold with full simulation capability (no external APIs required).

## 🎯 What It Does

1. **Review Ingestion**: Receives new reviews via webhook
2. **AI Draft Generation**: Uses Gemini API to draft professional responses based on star rating and review content
3. **SMS Approval**: Sends SMS to business owner with review + draft, asks for YES/NO approval
4. **Response Management**: Stores approvals and readies responses for posting
5. **Local Testing**: Full end-to-end flow simulation without live APIs

## 📋 Project Structure

```
tradereply/
├── src/
│   ├── app.py              # FastAPI application & endpoints
│   ├── models.py           # Data models (Business, Review, etc.)
│   ├── db_helper.py        # SQLite database CRUD operations
│   ├── ai_integration.py   # Gemini API integration
│   ├── sms_handler.py      # Twilio SMS handling
│   ├── prompts.py          # AI prompt engineering
│   └── config.py           # Configuration management
├── tests/
│   └── test_harness.py     # Comprehensive test scenarios
├── data/                   # SQLite database (created at runtime)
├── requirements.txt        # Python dependencies
└── README.md              # This file
```

## 🚀 Setup

### 1. Install Dependencies

```bash
cd /Users/macmini/.openclaw/workspace/tradereply
pip install -r requirements.txt
```

### 2. Environment Variables (Optional)

Create a `.env` file in the project root for production setup:

```bash
# Twilio
TWILIO_ACCOUNT_SID=your_sid_here
TWILIO_AUTH_TOKEN=your_token_here
TWILIO_FROM_NUMBER=+61468155994

# Gemini
GEMINI_API_KEY=your_api_key_here

# Database
TRADEREPLY_DB_PATH=data/tradereply.db

# Logging
LOG_LEVEL=INFO
LOG_FILE=tradereply.log

# Feature Flags
DRY_RUN_SMS=true         # Set to 'false' to send real SMS
DRY_RUN_AI=false         # Set to 'true' for mock AI responses
ENVIRONMENT=development   # development, testing, production
```

**For Phase 1 development:**
- Leave `DRY_RUN_SMS=true` (logs SMS instead of sending)
- Leave `DRY_RUN_AI=false` (uses real Gemini API)

## 🧪 Testing

Run the complete test harness:

```bash
cd /Users/macmini/.openclaw/workspace/tradereply
python tests/test_harness.py
```

This runs 5 comprehensive tests:
1. **Test 1**: 5-star positive review → drafts response
2. **Test 2**: 1-star negative review → apologetic response
3. **Test 3**: 3-star neutral review → improvement-focused response
4. **Test 4**: Database CRUD operations
5. **Test 5**: Approval workflow (PENDING → APPROVED)

Expected output: ✅ All tests pass with clear logging of each step.

## 🌐 Running the API

### Start the development server:

```bash
cd /Users/macmini/.openclaw/workspace/tradereply/src
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Server will run at: `http://localhost:8000`

### Health check:
```bash
curl http://localhost:8000/health
```

## 📡 API Endpoints

### Businesses

**Create a business:**
```bash
curl -X POST http://localhost:8000/businesses \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=Pada's Pizzeria&phone=(02) 9999-0000&sms_recipient=%2B61402707102&description=Award-winning pizzeria in Sydney CBD"
```

**Get business details:**
```bash
curl http://localhost:8000/businesses/{business_id}
```

**List all businesses:**
```bash
curl http://localhost:8000/businesses
```

### Reviews

**Submit a new review (triggers full flow):**
```bash
curl -X POST http://localhost:8000/reviews \
  -H "Content-Type: application/json" \
  -d '{
    "business_id": "your_business_id",
    "reviewer_name": "John Doe",
    "rating": 5,
    "review_text": "Amazing pizza! Will come back!",
    "reviewer_email": "john@email.com"
  }'
```

Response includes:
- `review_id`: Unique review identifier
- `draft_id`: ID of AI-generated draft
- `approval_id`: ID of SMS approval request
- `draft`: The actual draft response text
- `sms_sent_to`: Phone number SMS was sent to

**Get review details:**
```bash
curl http://localhost:8000/reviews/{review_id}
```

### Approvals

**Process approval (YES/NO response):**
```bash
curl -X POST http://localhost:8000/approvals/{approval_id} \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'
```

**Get pending approvals for business:**
```bash
curl http://localhost:8000/businesses/{business_id}/approvals
```

### Debug Endpoints

**Get all reviews for a business:**
```bash
curl http://localhost:8000/debug/reviews/{business_id}
```

**Check database status:**
```bash
curl http://localhost:8000/debug/database
```

## 📊 Database Schema

### businesses
- `id` (TEXT, PRIMARY KEY)
- `name` (TEXT)
- `phone` (TEXT)
- `sms_recipient` (TEXT) — Phone number for SMS approvals
- `description` (TEXT)
- `created_at` (TEXT)

### reviews
- `id` (TEXT, PRIMARY KEY)
- `business_id` (FOREIGN KEY)
- `reviewer_name` (TEXT)
- `rating` (INTEGER, 1-5)
- `review_text` (TEXT)
- `reviewer_email` (TEXT, optional)
- `created_at` (TEXT)

### draft_responses
- `id` (TEXT, PRIMARY KEY)
- `review_id` (FOREIGN KEY)
- `business_id` (FOREIGN KEY)
- `draft_text` (TEXT)
- `created_at` (TEXT)

### pending_approvals
- `id` (TEXT, PRIMARY KEY)
- `draft_response_id` (FOREIGN KEY)
- `business_id` (FOREIGN KEY)
- `sms_sent_at` (TEXT)
- `status` (TEXT: pending, approved, rejected, posted)
- `sms_message` (TEXT)
- `approval_timestamp` (TEXT, optional)

### responses
- `id` (TEXT, PRIMARY KEY)
- `review_id` (FOREIGN KEY)
- `business_id` (FOREIGN KEY)
- `response_text` (TEXT)
- `posted_at` (TEXT)

## 🤖 AI Prompt Engineering

The system uses a two-part prompt system:

1. **System Prompt** (`prompts.py`): Defines the role and behavior of the AI
   - Professional tone, warm and genuine
   - Address reviewer by name
   - Different approaches for 1-5 star ratings
   - Keep responses concise (100-150 words)

2. **User Prompt**: Dynamic prompt for each review
   - Includes business context (name, description)
   - Full review details (name, rating, text)
   - Specific instructions based on star rating

Example: For a 1-star review, the prompt emphasizes apology and solutions. For a 5-star review, it emphasizes gratitude and specific feedback.

## 📱 SMS Flow

1. **Review submitted** → triggers AI draft
2. **Draft created** → SMS built with:
   - Star rating
   - Reviewer name
   - First 100 chars of review
   - First 120 chars of draft response
3. **SMS sent** to business owner's number (or logged in dry-run mode)
4. **Owner replies YES/NO** → approval status updated
5. **Posted** → ready for Google Business Profile (Phase 2)

Example SMS:
```
New 5-star review from Marco Giuseppe:
"Absolutely fantastic! The margherita pizza was perfection..."

Draft reply: "Thank you Marco! We're thrilled you enjoyed the experience..."

Reply YES to post, NO to skip.
```

## 🔧 Configuration Modes

### Development (Default)
```
DRY_RUN_SMS=true   (log SMS, don't send)
DRY_RUN_AI=false   (use real Gemini)
DEBUG=true         (enable reload, verbose logging)
```

### Testing
```
DRY_RUN_SMS=true
DRY_RUN_AI=true    (use mock responses)
DATABASE_PATH=:memory: (in-memory SQLite)
```

### Production
```
DRY_RUN_SMS=false  (send real SMS!)
DRY_RUN_AI=false   (use real Gemini)
DEBUG=false        (production logging)
```

## 📋 Phase 1 Checklist

- ✅ FastAPI scaffold with configuration
- ✅ SQLite schema with proper relationships
- ✅ Database helper (CRUD operations)
- ✅ AI prompt engineering for all rating levels
- ✅ SMS handler (real + dry-run modes)
- ✅ Approval workflow backend
- ✅ Full API endpoints (businesses, reviews, approvals)
- ✅ Test harness with 5 comprehensive scenarios
- ✅ Documentation & setup guide

## 🚧 Phase 2 (Future)

- Google Business Profile API integration
- Webhook receivers for real reviews
- Email notifications to business owner
- Dashboard/web UI for managing responses
- Analytics (response time, approval rates)

## 🐛 Troubleshooting

**"Database connection failed"**
- Ensure `data/` directory exists
- Check file permissions on `tradereply.db`

**"Gemini API error"**
- Verify `GEMINI_API_KEY` is set correctly
- Check API quota and rate limits

**"SMS not sent"**
- In development, check logs (DRY_RUN_SMS=true)
- In production, verify Twilio credentials

**Port 8000 already in use:**
```bash
lsof -i :8000
kill -9 <PID>
```

## 📝 License

Built for TradeReply. Internal use.

## 🎯 Next Steps

1. ✅ Run `python tests/test_harness.py` to verify everything works
2. ✅ Start the API with `uvicorn`
3. ✅ Test endpoints with curl or Postman
4. ⏭️ Phase 2: Integrate with Google Business API
5. ⏭️ Phase 2: Add Twilio webhook receivers for real SMS

---

**Built with 💪 for Sia's business success.**
