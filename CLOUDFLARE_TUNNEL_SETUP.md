# Cloudflare Tunnel Setup for Local VAPI Development

This guide helps you set up a free Cloudflare Tunnel to test VAPI integrations locally without deploying to Railway.

## Why Use Cloudflare Tunnel?

- **Free & Unlimited** - No time limits or usage restrictions
- **Static URLs** - Your tunnel URL stays the same (no need to update VAPI webhooks constantly)
- **HTTPS** - VAPI requires HTTPS webhooks
- **Fast Iteration** - Test changes locally before deploying to production

## Installation

### macOS
```bash
brew install cloudflare/cloudflare/cloudflared
```

### Linux
```bash
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared-linux-amd64.deb
```

### Windows
Download from: https://github.com/cloudflare/cloudflared/releases

## Setup (One-Time)

### 1. Authenticate with Cloudflare
```bash
cloudflared tunnel login
```
This opens your browser to authenticate with Cloudflare. You'll need a free Cloudflare account.

### 2. Create a Named Tunnel
```bash
cloudflared tunnel create vapi-local
```

You'll see output like:
```
Created tunnel vapi-local with id abc-123-def-456-ghi
```

**Save this tunnel ID!** You'll need it for the config file.

### 3. Create Configuration File

Create `~/.cloudflared/config.yml`:

```yaml
# Replace 'abc-123-def-456-ghi' with your actual tunnel ID
tunnel: abc-123-def-456-ghi
credentials-file: /Users/YOUR_USERNAME/.cloudflared/abc-123-def-456-ghi.json

ingress:
  # This is your tunnel URL - Cloudflare will assign it
  - hostname: vapi-local-abc123.trycloudflare.com
    service: http://localhost:8000
  # Catch-all rule (required)
  - service: http_status:404
```

**Note:** After first run, check the Cloudflare dashboard for your actual tunnel URL.

### 4. Get Your Tunnel URL

Run the tunnel once to see your assigned URL:
```bash
cloudflared tunnel run vapi-local
```

Look for a line like:
```
Your quick tunnel URL: https://vapi-local-abc123.trycloudflare.com
```

**This is your static URL!** Copy it.

## Daily Development Workflow

### Terminal 1: Run Your FastAPI Server
```bash
cd /Users/kevinmorrell/projects/vapi-skills-system
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Terminal 2: Run Cloudflare Tunnel
```bash
cloudflared tunnel run vapi-local
```

### Terminal 3: Update Your Environment

Edit your `.env` file:
```bash
# Development environment
ENVIRONMENT=development

# Your Cloudflare Tunnel URL (replace with your actual URL)
DEV_WEBHOOK_BASE_URL=https://vapi-local-abc123.trycloudflare.com

# Production URL (stays the same)
PROD_WEBHOOK_BASE_URL=https://journ3y-vapi-skills-service.up.railway.app
```

### Update VAPI Webhooks (First Time Setup)

Run the webhook update script to point VAPI tools to your local tunnel:

```bash
python scripts/update_webhooks.py https://vapi-local-abc123.trycloudflare.com
```

This updates all your VAPI tool webhooks to call your local machine through the tunnel.

## Testing

1. Your local server runs on `http://localhost:8000`
2. Cloudflare Tunnel exposes it as `https://vapi-local-abc123.trycloudflare.com`
3. VAPI calls your tunnel URL, which routes to your local server
4. You can see requests in real-time in your FastAPI logs

Test it works:
```bash
# From your local machine
curl https://vapi-local-abc123.trycloudflare.com/health

# Should return: {"status":"healthy","service":"vapi-skills-dispatcher"}
```

## Switching Between Development and Production

### Local Development
```bash
# In .env
ENVIRONMENT=development
DEV_WEBHOOK_BASE_URL=https://vapi-local-abc123.trycloudflare.com

# Update VAPI webhooks
python scripts/update_webhooks.py https://vapi-local-abc123.trycloudflare.com
```

### Production (Railway)
```bash
# In .env (or Railway environment variables)
ENVIRONMENT=production

# Update VAPI webhooks
python scripts/update_webhooks.py https://journ3y-vapi-skills-service.up.railway.app
```

## Troubleshooting

### Tunnel Won't Start
```bash
# Check if tunnel exists
cloudflared tunnel list

# Check config file syntax
cat ~/.cloudflared/config.yml

# Test connection
cloudflared tunnel run vapi-local
```

### VAPI Not Calling Local Server
1. Verify tunnel is running: `cloudflared tunnel run vapi-local`
2. Verify local server is running: `curl http://localhost:8000/health`
3. Verify tunnel URL works: `curl https://your-tunnel-url/health`
4. Check VAPI tool webhook URLs: `python scripts/update_webhooks.py --list`

### URL Changes
If you accidentally created a temporary tunnel (URL with random characters that changes), create a named tunnel instead:
```bash
cloudflared tunnel create vapi-local
```
Named tunnels have stable URLs.

## Tips

- **Keep the tunnel running** - Start it once in the morning, leave it running
- **No need to update webhooks** - Once set, the tunnel URL stays the same
- **View tunnel status** - Visit Cloudflare Zero Trust dashboard
- **Multiple developers** - Each developer can have their own tunnel

## Optional: Custom Domain

If you own a domain managed by Cloudflare, you can use a custom subdomain:

1. Update `~/.cloudflared/config.yml`:
```yaml
ingress:
  - hostname: dev-vapi.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

2. Add DNS record via Cloudflare dashboard:
```
Type: CNAME
Name: dev-vapi
Target: abc-123-def-456-ghi.cfargotunnel.com
```

3. Update your `.env`:
```bash
DEV_WEBHOOK_BASE_URL=https://dev-vapi.yourdomain.com
```

## Cost Summary

- Cloudflare Account: **Free**
- Cloudflare Tunnel: **Free (unlimited)**
- Domain (optional): $10-15/year

**Total: $0** (or $10-15/year with custom domain)
