# VAPI Skills System

Multi-tenant skills-based voice agent system supporting both internal users and external customers.

## Phase 1: Built by MK Internal Users

Initial implementation focuses on migrating Built by MK's existing site update system to the new skills-based architecture.

## Quick Start

1. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your actual values
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run locally:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

4. Test endpoints:
- Health: http://localhost:8000/health
- Docs: http://localhost:8000/docs

## Deployment

This project is configured for Railway deployment. Connect your GitHub repository to Railway and it will auto-deploy.

## API Endpoints

### Phase 1 Endpoints

- `GET /health` - Health check
- `POST /api/v1/vapi/authenticate` - Basic authentication for internal users

## Environment Variables

- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_SERVICE_KEY` - Supabase service role key
- `ENVIRONMENT` - development/production
- `LOG_LEVEL` - INFO/DEBUG/WARNING/ERROR

## Architecture

Built on FastAPI with Supabase backend, designed for multi-tenant SaaS scaling.