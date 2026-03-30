# TradeReply Pilot-Ready Checklist

## Goal
Get TradeReply ready for 1 real pilot business with:
- real review intake
- real SMS approval replies
- approved response handling
- clear operator visibility
- manual fallback where needed

---

## Phase 1 — Critical path (must-have)

### 1) Production config hardening
- [x] Add strict validation for required prod env vars:
  - [x] `TWILIO_ACCOUNT_SID`
  - [x] `TWILIO_AUTH_TOKEN`
  - [x] `TWILIO_FROM_NUMBER`
  - [x] `GEMINI_API_KEY`
  - [x] `GOOGLE_CREDENTIALS_PATH`
  - [x] `GOOGLE_BUSINESS_ACCOUNT_ID`
- [x] Fail startup if `ENVIRONMENT=production` and required vars missing
- [x] Add `.env.production.example`

### 2) Real inbound Twilio webhook
- [x] Create endpoint: `POST /webhooks/twilio/inbound`
- [x] Parse Twilio fields: from, body, message sid
- [x] Normalize YES / NO / invalid replies
- [x] Match inbound reply to latest pending approval for that business/phone
- [x] Update DB state and log inbound SMS interaction

### 3) Approval → final action flow
- [x] Add lifecycle states:
  - [x] `drafted`
  - [x] `awaiting_approval`
  - [x] `approved`
  - [x] `rejected`
  - [x] `posted`
  - [x] `post_failed`
- [x] On YES → mark approved + trigger next action
- [x] On NO → mark rejected + hold for manual follow-up
- [x] Persist status transitions in DB

### 4) Posting strategy for pilot (recommended: manual-assisted)
- [x] After approval, mark response as ready-to-post
- [x] Surface ready-to-post responses in ops dashboard/API
- [x] Manually post during pilot
- [x] Mark as posted inside TradeReply

### 5) Minimal operator dashboard
- [x] Show pending approvals
- [x] Show approved awaiting post
- [x] Show posted responses
- [x] Show failed responses
- [ ] Show last inbound SMS events
- [ ] Add business filter
- [x] Add “mark as posted” action

---

## Phase 2 — Strongly recommended before pilot starts

### 6) Business identity + mapping
- [x] Ensure each business has name, phone, SMS recipient, and Google Business mapping placeholder
- [ ] Add first pilot business record
- [x] Verify review source → business mapping

### 7) Audit logging
- [x] Log review received
- [x] Log AI draft created
- [x] Log SMS sent
- [x] Log inbound SMS received
- [x] Log approval/rejection
- [x] Log post success/failure

### 8) Error handling / retry paths
- [ ] SMS send failure state
- [ ] Invalid SMS response state
- [ ] Post failure state
- [ ] Manual retry action

### 9) Security cleanup
- [ ] Verify Twilio webhook signature
- [ ] Disable unsafe debug endpoints in production
- [ ] Add basic admin auth if publicly exposed
- [ ] Review secrets handling
- [ ] Make logs production-safe

---

## Phase 3 — Pilot execution checklist

### 10) Pilot readiness test
- [ ] Twilio outbound real SMS confirmed
- [ ] Twilio inbound YES works
- [ ] NO works
- [ ] Invalid text handled
- [ ] AI draft quality acceptable
- [ ] Response visible in dashboard
- [ ] Post/manual-post workflow works
- [ ] Full audit trail visible

### 11) First pilot business
- [ ] Choose 1 business
- [ ] Set SMS approver phone
- [ ] Confirm response voice/tone
- [ ] Run 3 scenarios:
  - [ ] positive review
  - [ ] neutral review
  - [ ] negative review
- [ ] Then run real monitored pilot

---

## Definition of Done
TradeReply is pilot-ready when:
- [ ] real review can enter system
- [ ] AI draft is generated
- [ ] owner receives SMS
- [ ] owner replies YES/NO
- [ ] TradeReply records result correctly
- [ ] operator can see status in dashboard
- [ ] approved responses can be posted or manually completed
- [ ] failures are visible and recoverable

---

## Recommended implementation order
1. Twilio inbound webhook
2. Approval lifecycle states
3. Manual-post operator dashboard
4. Production config validation
5. Audit logs
6. Security cleanup
7. Pilot business setup
8. Real pilot run
