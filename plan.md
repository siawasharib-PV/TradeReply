# TradeReply: Micro-SaaS Plan

## Core Loop
1. Webhook/Cron checks Google Business Profile API for new reviews.
2. If new review: AI drafts a highly specific, polite response based on the review text and star rating.
3. System sends an SMS via Twilio to the business owner: "New 5-star review from [Name]: '[Review]'. Reply YES to post this response: '[Draft]'"
4. If owner replies YES to the Twilio number, webhook triggers Google API to post the reply.

## Stack
- Backend: Python (FastAPI or simple webhook listener)
- DB: SQLite (for tracking businesses, reviews, and pending SMS approvals)
- AI: OpenClaw/Gemini API
- APIs: Google My Business API, Twilio SMS API

## Phases
- [x] Concept Approved
- [ ] Phase 1: Local scaffold, DB setup, and AI prompt engineering.
- [ ] Phase 2: Connect Twilio (requires user keys).
- [ ] Phase 3: Connect Google Business Profile (requires OAuth/GCP setup).
