# Local Development Guide

## Quick Start

### Terminal 1: Run FastAPI Server
```bash
cd /Users/kevinmorrell/projects/vapi-skills-system
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

You'll see output like:
```
INFO:     Will watch for changes in these directories: ['/Users/kevinmorrell/projects/vapi-skills-system']
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:app.main:Initializing skill-based architecture...
INFO:app.skills.base_skill:Initialized skill: Voice Notes (voice_notes)
INFO:app.skills.skill_registry:Registered skill: Voice Notes (voice_notes)
INFO:app.main:Registered 1 skills
INFO:     Started server process [12345]
INFO:     Application startup complete.
```

### Terminal 2: Run Cloudflare Tunnel
```bash
cloudflared tunnel --url http://localhost:8000
```

You'll see your tunnel URL:
```
Your quick Tunnel has been created! Visit it at:
https://random-words-123.trycloudflare.com
```

**Copy this URL!** You'll need it to update VAPI webhooks.

### Terminal 3: Update Configuration

1. Edit `.env` and update `DEV_WEBHOOK_BASE_URL`:
```bash
DEV_WEBHOOK_BASE_URL=https://random-words-123.trycloudflare.com
```

2. Restart your FastAPI server (Ctrl+C in Terminal 1, then restart)

3. Update VAPI webhooks:
```bash
python scripts/update_webhooks.py https://random-words-123.trycloudflare.com
```

## Testing

### Test Local Server
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy","service":"vapi-skills-dispatcher"}
```

### Test Tunnel
```bash
curl https://your-tunnel-url.trycloudflare.com/health
```

### Check Skill Registry
```bash
curl http://localhost:8000/api/v1/skills/list | jq .
```

### Check Environment
```bash
curl http://localhost:8000/debug/env-check | jq .
```

Look for:
```json
{
  "webhook_base_url": "https://your-tunnel-url.trycloudflare.com",
  "environment": "development"
}
```

## VAPI Testing

Once your tunnel is running and webhooks are updated, VAPI calls will hit your local machine!

### Watch Requests in Real-Time
In your FastAPI server terminal, you'll see:
```
INFO:app.skills.voice_notes.endpoints:Authenticating phone: +61412345678
INFO:app.skills.voice_notes.endpoints:Found user: John Smith
INFO:app.skills.voice_notes.endpoints:Successfully authenticated John Smith
```

### Test Voice Notes Flow
1. Call your VAPI phone number
2. Watch requests appear in Terminal 1 (FastAPI server)
3. See the conversation flow through your local code
4. Check database for saved notes

## Stopping Everything

### Stop FastAPI Server
Press `Ctrl+C` in Terminal 1

Or kill it:
```bash
pkill -f uvicorn
```

### Stop Cloudflare Tunnel
Press `Ctrl+C` in Terminal 2

Or kill it:
```bash
pkill cloudflared
```

## Daily Workflow

1. **Morning Setup** (5 minutes):
   - Start FastAPI server (Terminal 1)
   - Start Cloudflare tunnel (Terminal 2)
   - Copy tunnel URL
   - Update `.env` with new URL
   - Restart FastAPI server
   - Update VAPI webhooks

2. **Development**:
   - Make code changes
   - FastAPI auto-reloads
   - Test immediately via VAPI calls
   - See logs in real-time

3. **End of Day**:
   - Stop servers (Ctrl+C or pkill)
   - Commit changes to git

## Troubleshooting

### Server Won't Start
```bash
# Check if something is on port 8000
lsof -i :8000

# Kill it
kill -9 <PID>
```

### Tunnel Not Working
```bash
# Check tunnel is running
ps aux | grep cloudflared

# Test tunnel URL
curl https://your-tunnel-url.trycloudflare.com/health
```

### VAPI Not Calling Local Server
1. Check tunnel is running: `ps aux | grep cloudflared`
2. Check FastAPI is running: `curl http://localhost:8000/health`
3. Check webhooks point to tunnel: `python scripts/update_webhooks.py --list`
4. Restart tunnel if URL changed

### Changes Not Appearing
- FastAPI auto-reloads on `.py` file changes
- If using `.env` changes, restart server manually
- Check terminal for reload messages

## Useful Commands

```bash
# Check what's running
ps aux | grep -E "(uvicorn|cloudflared)"

# Kill everything
pkill -f uvicorn && pkill cloudflared

# View server logs
tail -f /tmp/fastapi.log

# Test specific endpoint
curl -X POST http://localhost:8000/api/v1/skills/voice-notes/identify-context \\
  -H "Content-Type: application/json" \\
  -d '{"message": {"toolCalls": [{"id": "test", "function": {"arguments": {"user_input": "site note", "vapi_call_id": "test"}}}]}}'
```

## Production Deployment

When ready to deploy to Railway:

1. Update `.env` or Railway environment variables:
```bash
ENVIRONMENT=production
# No need to set DEV_WEBHOOK_BASE_URL
```

2. Update VAPI webhooks to production:
```bash
python scripts/update_webhooks.py https://journ3y-vapi-skills-service.up.railway.app
```

3. Push to main branch:
```bash
git checkout main
git merge refactor/skill-based-architecture
git push origin main
```

Railway will auto-deploy.
