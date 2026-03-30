# Google Business Profile Setup Guide

## For Business Owners

To connect your Google Business Profile to TradeReply, you'll need to create API credentials. This takes about 10 minutes.

---

## Step 1: Go to Google Cloud Console

👉 [Click here to open Google Cloud Console](https://console.cloud.google.com)

1. Sign in with the **same Google account** you use for your Business Profile
2. If prompted, create a new project (it's free)
   - Click "Select a project" → "New Project"
   - Name it: `TradeReply - [Your Business Name]`
   - Click "Create"

---

## Step 2: Enable the Business Profile API

1. In the left menu, go to **APIs & Services** → **Library**
2. Search for: `Google My Business API` or `Business Profile API`
3. Click on it, then click **Enable**

> ⚠️ Note: Google may require you to verify your business before API access is granted. This can take 1-3 days.

---

## Step 3: Create OAuth2 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. If prompted, configure the consent screen first:
   - User Type: **External**
   - App name: `TradeReply`
   - User support email: your email
   - Developer contact: your email
   - Click through and save
4. Now create the OAuth client:
   - Application type: **Web application**
   - Name: `TradeReply Client`
   - Authorized redirect URI: 
   ```
   https://web-production-e56a13.up.railway.app/google/callback
   ```
   - Click **Create**

---

## Step 4: Get Your Credentials

After creating, you'll see:

- **Your Client ID** — looks like: `123456789-abcdefg.apps.googleusercontent.com`
- **Your Client Secret** — looks like: `GOCSPX-xxxxxxxxxxxxx`

📋 **Copy both of these** — you'll send them to TradeReply to connect your account.

---

## Step 5: Share with TradeReply

Send your credentials to TradeReply support or enter them in your dashboard:

| Field | Value |
|-------|-------|
| Client ID | `paste here` |
| Client Secret | `paste here` |
| Google Location ID | `(we'll find this for you)` |

---

## What Happens Next

1. TradeReply will send you a Google login link
2. You sign in and authorize access
3. Your reviews will start flowing automatically!

---

## 🎨 Visual Guide (Coming Soon)

We're creating a video walkthrough with screenshots. For now, if you get stuck:

- Email: support@tradereply.com
- Or reply to your setup SMS with "HELP"

---

## Troubleshooting

### "API not enabled"
→ Make sure you clicked "Enable" in Step 2

### "Redirect URI mismatch"
→ Check the redirect URI matches exactly:
```
https://web-production-e56a13.up.railway.app/google/callback
```

### "App is in testing mode"
→ This is fine for now. We'll move to production when you're ready.

---

## Security Notes

✅ Your credentials are stored encrypted
✅ TradeReply only accesses review data — nothing else
✅ You can revoke access at any time from your Google Account settings
