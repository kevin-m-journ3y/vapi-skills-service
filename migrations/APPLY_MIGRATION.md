# How to Apply Database Migration

## Option 1: Supabase Dashboard (Recommended)

1. Go to https://supabase.com/dashboard
2. Select your project: `lsfprvnhuazudkjqrpuk`
3. Navigate to **SQL Editor** in the left sidebar
4. Click **New Query**
5. Copy and paste the contents of `002_create_site_progress_updates.sql`
6. Click **Run** or press `Ctrl+Enter`

## Option 2: Supabase CLI

```bash
supabase db push
```

## Verification

After running the migration, verify the table was created:

```bash
python3 << 'PYTHON'
import httpx
import asyncio

async def verify():
    url = "https://lsfprvnhuazudkjqrpuk.supabase.co"
    key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxzZnBydm5odWF6dWRranFycHVrIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NzY0NDkyOCwiZXhwIjoyMDczMjIwOTI4fQ.cJ6KZ5X2zwoe2C2qVoTHbEbB-tU4qNjhBaEy9bL6kws"

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    async with httpx.AsyncClient() as client:
        r = await client.get(f"{url}/rest/v1/site_progress_updates?limit=0", headers=headers)
        if r.status_code == 200:
            print("✓ Table site_progress_updates exists!")
        else:
            print(f"✗ Table not found: {r.status_code}")

asyncio.run(verify())
PYTHON
```
