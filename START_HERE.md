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

## 🧪 Test Everything Works

Before making changes, verify everything is working:
```bash
# Run all tests (starts/stops server automatically)
python scripts/run_tests.py
```

**Expected output:**
```
✓ Server started successfully
✓ Server Health
✓ Skills List
✓ ALL TESTS PASSED (21/21)
```

See [TESTING.md](TESTING.md) for testing guide.

---

## ✅ You're Ready!

Now make a VAPI call and watch the magic happen in Terminal 1!

**Documentation:**
- [START_HERE.md](START_HERE.md) - This quick start guide
- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) - Full development workflow
- [TESTING.md](TESTING.md) - Running and writing tests
- [CLOUDFLARE_TUNNEL_SETUP.md](CLOUDFLARE_TUNNEL_SETUP.md) - Tunnel setup guide
