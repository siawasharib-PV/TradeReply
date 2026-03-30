"""
TradeReply Setup - Google Business Profile Connection
Visual onboarding page for business owners
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/setup/google", response_class=HTMLResponse)
async def google_setup_page(request: Request):
    """Visual setup guide for connecting Google Business Profile"""
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Connect Google Business Profile | TradeReply</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #0f172a;
                color: #e2e8f0;
                line-height: 1.6;
                padding: 20px;
            }
            .container { max-width: 800px; margin: 0 auto; }
            .header { 
                text-align: center; 
                margin-bottom: 40px;
                padding: 30px 0;
                border-bottom: 1px solid #334155;
            }
            .logo { font-size: 32px; font-weight: bold; color: #3b82f6; }
            .subtitle { color: #94a3b8; margin-top: 8px; }
            
            .step { 
                background: #1e293b;
                border-radius: 12px;
                padding: 24px;
                margin-bottom: 20px;
                border: 1px solid #334155;
            }
            .step-number {
                display: inline-block;
                width: 36px;
                height: 36px;
                background: #3b82f6;
                color: white;
                border-radius: 50%;
                text-align: center;
                line-height: 36px;
                font-weight: bold;
                margin-right: 12px;
            }
            .step-title { 
                font-size: 20px; 
                font-weight: 600;
                margin-bottom: 12px;
                display: flex;
                align-items: center;
            }
            .step-content { padding-left: 48px; }
            
            .link {
                display: inline-block;
                background: #3b82f6;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 500;
                margin: 12px 0;
            }
            .link:hover { background: #2563eb; }
            
            .code-block {
                background: #0f172a;
                padding: 12px 16px;
                border-radius: 6px;
                font-family: 'Monaco', 'Menlo', monospace;
                font-size: 13px;
                color: #93c5fd;
                overflow-x: auto;
                margin: 12px 0;
                border: 1px solid #334155;
            }
            
            .warning {
                background: #422006;
                border: 1px solid #a16207;
                padding: 16px;
                border-radius: 8px;
                margin: 16px 0;
            }
            .warning-title { color: #fbbf24; font-weight: 600; margin-bottom: 8px; }
            
            .success {
                background: #14532d;
                border: 1px solid #22c55e;
                padding: 16px;
                border-radius: 8px;
                margin: 16px 0;
            }
            .success-title { color: #4ade80; font-weight: 600; margin-bottom: 8px; }
            
            .credential-box {
                background: #1e293b;
                border: 2px dashed #334155;
                border-radius: 8px;
                padding: 20px;
                margin: 20px 0;
            }
            .credential-box h4 { margin-bottom: 16px; color: #3b82f6; }
            .field {
                margin-bottom: 16px;
            }
            .field label {
                display: block;
                font-weight: 500;
                margin-bottom: 6px;
                color: #94a3b8;
            }
            .field input {
                width: 100%;
                padding: 12px;
                border-radius: 6px;
                border: 1px solid #334155;
                background: #0f172a;
                color: white;
                font-size: 14px;
            }
            .field input:focus {
                outline: none;
                border-color: #3b82f6;
            }
            
            .btn {
                background: #22c55e;
                color: white;
                padding: 14px 28px;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: 600;
                cursor: pointer;
            }
            .btn:hover { background: #16a34a; }
            .btn:disabled { 
                background: #374151; 
                cursor: not-allowed;
            }
            
            .muted { color: #94a3b8; }
            .highlight { color: #3b82f6; font-weight: 500; }
            
            .screenshot {
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 16px;
                margin: 16px 0;
                text-align: center;
                color: #64748b;
                font-style: italic;
            }
            
            .footer {
                text-align: center;
                padding: 40px 0;
                margin-top: 40px;
                border-top: 1px solid #334155;
                color: #64748b;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">🚀 TradeReply</div>
                <div class="subtitle">Connect your Google Business Profile</div>
            </div>
            
            <p style="margin-bottom: 30px;">
                This takes about <strong>10 minutes</strong>. You'll create API credentials 
                in Google Cloud Console so TradeReply can read your reviews and post replies.
            </p>
            
            <!-- Step 1 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">1</span>
                    Open Google Cloud Console
                </div>
                <div class="step-content">
                    <p>Sign in with the <strong>same Google account</strong> you use for your Business Profile.</p>
                    <a href="https://console.cloud.google.com" target="_blank" class="link">
                        → Open Google Cloud Console
                    </a>
                    
                    <p style="margin-top: 16px;">If prompted, create a new project:</p>
                    <ul style="margin-left: 20px; margin-top: 8px;">
                        <li>Click "Select a project" → "New Project"</li>
                        <li>Name it: <span class="highlight">TradeReply - [Your Business Name]</span></li>
                        <li>Click "Create"</li>
                    </ul>
                    
                    <div class="screenshot">
                        📸 Screenshot: Google Cloud Console - New Project dialog
                    </div>
                </div>
            </div>
            
            <!-- Step 2 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">2</span>
                    Enable Business Profile API
                </div>
                <div class="step-content">
                    <ol style="margin-left: 20px;">
                        <li>Go to <strong>APIs & Services</strong> → <strong>Library</strong></li>
                        <li>Search for: <span class="highlight">Google My Business API</span> or <span class="highlight">Business Profile API</span></li>
                        <li>Click on it, then click <strong>Enable</strong></li>
                    </ol>
                    
                    <div class="warning">
                        <div class="warning-title">⚠️ Note</div>
                        Google may require business verification. This can take 1-3 days. 
                        You can still proceed with setup while waiting.
                    </div>
                    
                    <div class="screenshot">
                        📸 Screenshot: API Library with Business Profile API highlighted
                    </div>
                </div>
            </div>
            
            <!-- Step 3 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">3</span>
                    Configure OAuth Consent Screen
                </div>
                <div class="step-content">
                    <ol style="margin-left: 20px;">
                        <li>Go to <strong>APIs & Services</strong> → <strong>OAuth consent screen</strong></li>
                        <li>Select <strong>External</strong> user type → Click "Create"</li>
                        <li>Fill in:
                            <ul style="margin-top: 8px; margin-bottom: 8px;">
                                <li>App name: <span class="highlight">TradeReply</span></li>
                                <li>User support email: your email</li>
                                <li>Developer contact: your email</li>
                            </ul>
                        </li>
                        <li>Click through the remaining sections (Scopes, Test Users) and save</li>
                    </ol>
                    
                    <div class="screenshot">
                        📸 Screenshot: OAuth consent screen configuration
                    </div>
                </div>
            </div>
            
            <!-- Step 4 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">4</span>
                    Create OAuth2 Credentials
                </div>
                <div class="step-content">
                    <ol style="margin-left: 20px;">
                        <li>Go to <strong>APIs & Services</strong> → <strong>Credentials</strong></li>
                        <li>Click <strong>Create Credentials</strong> → <strong>OAuth client ID</strong></li>
                        <li>Application type: <strong>Web application</strong></li>
                        <li>Name: <span class="highlight">TradeReply Client</span></li>
                        <li>Authorized redirect URI — add this exactly:</li>
                    </ol>
                    
                    <div class="code-block">
                        https://web-production-e56a13.up.railway.app/google/callback
                    </div>
                    
                    <ol start="6" style="margin-left: 20px;">
                        <li>Click <strong>Create</strong></li>
                    </ol>
                    
                    <div class="screenshot">
                        📸 Screenshot: Create OAuth client ID dialog
                    </div>
                </div>
            </div>
            
            <!-- Step 5 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">5</span>
                    Copy Your Credentials
                </div>
                <div class="step-content">
                    <p>After creating, you'll see a popup with two values:</p>
                    
                    <div class="success">
                        <div class="success-title">✅ Copy These Values</div>
                        <ul style="margin-left: 20px;">
                            <li><strong>Client ID</strong> — looks like: <code>123456789-abc123.apps.googleusercontent.com</code></li>
                            <li><strong>Client Secret</strong> — looks like: <code>GOCSPX-xxxxxxxxxxxxx</code></li>
                        </ul>
                    </div>
                    
                    <p class="muted">You can always find these again in Credentials → click the pencil icon</p>
                </div>
            </div>
            
            <!-- Step 6 -->
            <div class="step">
                <div class="step-title">
                    <span class="step-number">6</span>
                    Enter Credentials Below
                </div>
                <div class="step-content">
                    <div class="credential-box">
                        <h4>🔐 Your Credentials</h4>
                        
                        <div class="field">
                            <label>Client ID</label>
                            <input type="text" id="clientId" placeholder="123456789-abc123.apps.googleusercontent.com">
                        </div>
                        
                        <div class="field">
                            <label>Client Secret</label>
                            <input type="password" id="clientSecret" placeholder="GOCSPX-xxxxxxxxxxxxx">
                        </div>
                        
                        <button class="btn" onclick="connectGoogle()">
                            Connect Google Business Profile
                        </button>
                        
                        <p id="status" class="muted" style="margin-top: 12px;"></p>
                    </div>
                </div>
            </div>
            
            <div class="footer">
                <p>Need help? Reply "HELP" to your setup SMS or email support@tradereply.com</p>
                <p style="margin-top: 8px;">© 2026 TradeReply — Built for business owners</p>
            </div>
        </div>
        
        <script>
            async function connectGoogle() {
                const clientId = document.getElementById('clientId').value;
                const clientSecret = document.getElementById('clientSecret').value;
                const statusEl = document.getElementById('status');
                const btn = document.querySelector('.btn');
                
                if (!clientId || !clientSecret) {
                    statusEl.textContent = '⚠️ Please enter both Client ID and Client Secret';
                    return;
                }
                
                btn.disabled = true;
                statusEl.textContent = '⏳ Connecting...';
                
                try {
                    const response = await fetch('/google/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ clientId, clientSecret })
                    });
                    
                    const data = await response.json();
                    
                    if (data.auth_url) {
                        statusEl.innerHTML = '✅ Redirecting to Google...';
                        window.location.href = data.auth_url;
                    } else {
                        statusEl.textContent = '❌ ' + (data.detail || 'Connection failed');
                        btn.disabled = false;
                    }
                } catch (err) {
                    statusEl.textContent = '❌ Error: ' + err.message;
                    btn.disabled = false;
                }
            }
        </script>
    </body>
    </html>
    """
    return html
