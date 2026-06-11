# MHTCET Result Available Checker 🎯

A **production-ready**, 24/7 automated system that monitors the MHTCET candidate portal for PCM Scorecard availability and **calls you + WhatsApps you** the moment it's detected.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🤖 Browser Automation | Playwright (Chromium, headless, anti-detection) |
| 🔑 Session Reuse | Saves login session — no repeated full logins |
| 🗄️ SQLite Database | Tracks all checks, notifications, and status |
| 📞 Phone Call Alert | Twilio voice call when PCM scorecard found |
| 💬 WhatsApp Alert | Twilio WhatsApp message for all events |
| 🚫 Spam Prevention | Sends alert only ONCE — never calls repeatedly |
| 📸 Error Screenshots | Auto-saves screenshot on login failure / portal change |
| 🌐 Web Dashboard | Live status at `http://localhost:5000` |
| 🔄 Auto-retry | Handles timeouts, website down, temporary errors |
| ☁️ Cloud Ready | Deploy to Railway/Render/Docker for 24/7 uptime |

---

## 📁 Project Structure

```
mhtcet-checker/
├── app.py                    ← Main entry point (Flask + Scheduler)
├── checker/
│   ├── browser.py            ← Playwright session manager
│   ├── login.py              ← Login automation
│   └── scorecard.py          ← PCM scorecard detection
├── notifications/
│   ├── twilio_call.py        ← Phone call via Twilio
│   └── whatsapp.py           ← WhatsApp messages via Twilio
├── database/
│   └── db.py                 ← SQLite models + helpers
├── dashboard/
│   ├── templates/index.html  ← Web dashboard
│   └── static/               ← CSS + JS
├── logs/checker.log          ← Rotating log file
├── screenshots/              ← Auto-saved error screenshots
├── .env                      ← Your credentials (fill this!)
├── .env.example              ← Template
├── requirements.txt
├── Procfile                  ← Railway/Render
└── Dockerfile                ← Docker deployment
```

---

## 🚀 Setup (Step by Step)

### Step 1 — Install Python
Download Python 3.11+ from https://python.org

### Step 2 — Install Dependencies
```bash
cd mhtcet-checker
pip install -r requirements.txt
playwright install chromium
```

### Step 3 — Configure Credentials
```bash
copy .env.example .env
```

Open `.env` in Notepad and fill in:
```
MHTCET_EMAIL=your_email@example.com
MHTCET_PASSWORD=your_mhtcet_password

TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX
TWILIO_WHATSAPP_NUMBER=+14155238886
YOUR_PHONE_NUMBER=+91XXXXXXXXXX

CHECK_INTERVAL=300
LOGIN_URL=https://portal-2026.mahacet.org
```

### Step 4 — Set Up Twilio (Free)
1. Go to https://www.twilio.com → Sign up free
2. Get your **Account SID** and **Auth Token** from the console
3. Get a free phone number (for calls)
4. For WhatsApp: Go to **Messaging → Try it out → Send a WhatsApp message**
   - Send the join code to `+14155238886` from your WhatsApp
   - This activates the sandbox

### Step 5 — Run
```bash
python app.py
```

Open dashboard: **http://localhost:5000**

---

## 🖥️ Dashboard Controls

| Button | Action |
|---|---|
| ▶ Start Checker | Begin monitoring (sends startup WhatsApp) |
| ⏸ Stop Checker | Pause monitoring |
| 🔄 Check Now | Trigger an immediate check |
| 🔁 Reset Alert | Clear "already alerted" flag (for re-testing) |
| 💬 Test WhatsApp | Send a test WhatsApp to your number |
| 📞 Test Call | Make a test phone call |

---

## ☁️ Deploy to Railway (24/7, Laptop OFF)

1. Create account at https://railway.app
2. Install Railway CLI: `npm install -g @railway/cli`
3. In project folder:
   ```bash
   railway login
   railway init
   railway up
   ```
4. Set environment variables in Railway dashboard (copy from your `.env`)
5. Done! Your checker runs 24/7 on the cloud.

### Alternative: Render
1. Push code to GitHub
2. Go to https://render.com → New Web Service → Connect repo
3. Set env vars → Deploy

---

## ⚠️ Error Handling

| Error | What Happens |
|---|---|
| Login failed (wrong credentials) | WhatsApp alert sent to you |
| Website down / timeout | Retries every 5 min, WhatsApp after 3 consecutive fails |
| Portal UI changed | Screenshot saved, WhatsApp alert, checker stops |
| Twilio call fails | Error logged, WhatsApp still attempted |
| Alert already sent | All future notifications blocked (no spam) |

---

## 📞 What You'll Receive When PCM Scorecard is Found

**WhatsApp:**
```
🚨 MHTCET ALERT 🚨

✅ PCM Scorecard is NOW AVAILABLE!

📋 MHT-CET (PCM) 2026 Score Card can be downloaded.

🔗 Login immediately: https://portal-2026.mahacet.org

⏰ Don't delay — download your scorecard now!
```

**Phone Call:**
> "Attention! Your MHT CET PCM Scorecard is now available. Please login immediately and download it. I repeat — Your PCM Score Card is now available. Login now!"

---

## 🔒 Security Notes
- Never commit `.env` to GitHub
- Add `.env` to `.gitignore`
- Use Railway/Render environment variables for production

---

*Built with Python, Playwright, Flask, Twilio, APScheduler, SQLAlchemy*
