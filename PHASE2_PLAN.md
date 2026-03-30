# TradeReply Phase 2 - Google Business Profile Integration

**Started:** 2026-03-31
**Status:** In Progress

---

## Goal

Connect TradeReply to Google Business Profile API to:
1. **Fetch real reviews** automatically (polling or webhook)
2. **Post approved responses** back to Google
3. **Full end-to-end automation** — no manual copying

---

## Prerequisites

- [x] Google Business Profile (Pada Ventures ID: 18013239527057313104)
- [ ] Google Cloud Console project with Business Profile API enabled
- [ ] OAuth2 credentials (client ID, client secret)
- [ ] Refresh token for offline access

---

## Implementation Tasks

### 1. Google Cloud Setup
- [ ] Create/identify Google Cloud project
- [ ] Enable Google Business Profile API
- [ ] Create OAuth2 credentials (desktop or web app)
- [ ] Configure redirect URI
- [ ] Generate refresh token

### 2. Google API Client
- [ ] Add `google-auth-oauthlib`, `google-auth-httplib2`, `google-api-python-client` to requirements
- [ ] Create `src/google_client.py` with:
  - OAuth2 authentication flow
  - Token refresh handling
  - Fetch reviews from location
  - Post reply to review

### 3. Review Polling/Sync
- [ ] Add endpoint: `POST /businesses/{id}/sync-reviews`
- [ ] Fetch all reviews since last sync
- [ ] Create review records in database
- [ ] Trigger AI draft + SMS approval flow

### 4. Auto-Post Approved Responses
- [ ] Update approval flow: after YES, post to Google
- [ ] Mark draft as "posted" after successful API call
- [ ] Handle API errors gracefully

### 5. Webhook (Optional - Phase 2.1)
- [ ] Google Pub/Sub webhook for real-time review notifications
- [ ] Endpoint: `POST /webhooks/google/reviews`

---

## API Endpoints to Add

| Endpoint | Purpose |
|----------|---------|
| `GET /google/auth` | Start OAuth2 flow |
| `GET /google/callback` | Handle OAuth2 callback |
| `POST /businesses/{id}/sync-reviews` | Manually sync reviews from Google |
| `POST /businesses/{id}/connect` | Connect Google Business Profile |

---

## Database Changes

Add to `businesses` table:
- `google_refresh_token` TEXT — for offline API access
- `google_account_id` TEXT — GMB account ID
- `google_location_id` TEXT — already exists
- `last_sync_at` TIMESTAMP — track review sync

---

## Configuration

Add to `.env`:
```
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REDIRECT_URI=https://web-production-e56a13.up.railway.app/google/callback
```

---

## Success Criteria

- [ ] Can authenticate with Google Business Profile
- [ ] Can fetch reviews from Pada Ventures
- [ ] Can post approved replies to Google
- [ ] Full automation: review received → SMS approval → posted to Google

---

## Business Owner Onboarding Flow

### Multi-Tenant Architecture
Each business owner must provide their own Google API credentials.

**Onboarding Steps:**
1. Business owner receives setup link (SMS or email)
2. They follow visual guide at `/setup/google`
3. They create OAuth2 credentials in their Google Cloud Console
4. They enter Client ID + Secret in TradeReply
5. TradeReply initiates OAuth flow to get refresh token
6. Reviews start syncing automatically

### Assets to Create
- [ ] `/setup/google` — Visual setup page with step-by-step instructions
- [ ] Setup guide with screenshots (docs/GOOGLE_SETUP_GUIDE.md) ✅
- [ ] Video walkthrough (Phase 2.1)
- [ ] In-app credential entry form

### Onboarding Page Content
- Simple numbered steps
- Screenshots of Google Cloud Console
- Copy-paste fields for credentials
- "Test Connection" button
- Live chat or SMS support option

---

## Notes

- Google Business Profile API has daily quotas — implement rate limiting
- Need to handle review updates (customer edits their review)
- Consider multiple locations per business in future
- Each business needs their own Google Cloud project (multi-tenant)

---

**Next Step:** Google Cloud Console setup with Sia (as first pilot customer)
