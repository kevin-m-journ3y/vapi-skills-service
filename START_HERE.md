# 🚀 Start Here - Local Development

## Open 3 Terminal Windows

### Terminal 1️⃣ - FastAPI Server
```bash
cd /Users/kevinmorrell/projects/vapi-skills-system
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
**✅ Keep running** - Watch VAPI requests here

---

### Terminal 2️⃣ - Cloudflare Tunnel
```bash
cloudflared tunnel --url http://localhost:8000
```
**📋 Copy the tunnel URL** that appears (like `https://xyz.trycloudflare.com`)

**✅ Keep running** - Your HTTPS endpoint

---

### Terminal 3️⃣ - Commands
```bash
cd /Users/kevinmorrell/projects/vapi-skills-system
source venv/bin/activate

# Update .env with your tunnel URL (from Terminal 2)
# Edit: DEV_WEBHOOK_BASE_URL=https://xyz.trycloudflare.com

# Then restart FastAPI server (Ctrl+C in Terminal 1, restart it)

# Update VAPI webhooks with your tunnel URL
python scripts/update_webhooks.py https://xyz.trycloudflare.com
```

---

## ✅ You're Ready!

Now make a VAPI call and watch the magic happen in Terminal 1!

See [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) for full documentation.
