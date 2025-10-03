#!/usr/bin/env python3
"""
Database updates for tenant, users, and entities
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

headers = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json"
}

async def update_tenant(tenant_id: str, name: str, slug: str):
    """Update tenant details"""
    async with httpx.AsyncClient() as client:
        response = await client.patch(
            f"{SUPABASE_URL}/rest/v1/tenants?id=eq.{tenant_id}",
            headers=headers,
            json={
                "name": name,
                "slug": slug
            }
        )
        if response.status_code in [200, 204]:
            print(f"✅ Updated tenant {tenant_id}: {name} ({slug})")
        else:
            print(f"❌ Failed to update tenant: {response.status_code} - {response.text}")

async def add_user(tenant_id: str, name: str, phone: str, role: str = "site_manager"):
    """Add a new user"""
    async with httpx.AsyncClient() as client:
        # Check if user already exists
        check_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/users?phone_number=eq.{phone}",
            headers=headers
        )

        if check_response.status_code == 200 and len(check_response.json()) > 0:
            print(f"⚠️  User with phone {phone} already exists: {name}")
            return

        # Create user - add Prefer header to return created record
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/users",
            headers={**headers, "Prefer": "return=representation"},
            json={
                "tenant_id": tenant_id,
                "name": name,
                "phone_number": phone,
                "role": role,
                "is_active": True
            }
        )

        if response.status_code == 201:
            users = response.json()
            if users and len(users) > 0:
                user_id = users[0].get('id')
                print(f"✅ Added user {name} ({phone}) - ID: {user_id}")
                return user_id
            else:
                print(f"❌ User created but no ID returned for {name}")
                return None
        else:
            print(f"❌ Failed to add user {name}: {response.status_code} - {response.text}")
            return None

async def add_entity(tenant_id: str, name: str, identifier: str, address: str, entity_type: str = "sites"):
    """Add a new entity (site)"""
    async with httpx.AsyncClient() as client:
        # Check if entity already exists
        check_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/entities?tenant_id=eq.{tenant_id}&identifier=eq.{identifier}",
            headers=headers
        )

        if check_response.status_code == 200 and len(check_response.json()) > 0:
            print(f"⚠️  Entity with identifier {identifier} already exists: {name}")
            return

        # Create entity - add Prefer header to return created record
        response = await client.post(
            f"{SUPABASE_URL}/rest/v1/entities",
            headers={**headers, "Prefer": "return=representation"},
            json={
                "tenant_id": tenant_id,
                "name": name,
                "identifier": identifier,
                "address": address,
                "entity_type": entity_type,
                "is_active": True
            }
        )

        if response.status_code == 201:
            entities = response.json()
            if entities and len(entities) > 0:
                entity_id = entities[0].get('id')
                print(f"✅ Added entity {name} ({identifier}) - ID: {entity_id}")
                return entity_id
            else:
                print(f"❌ Entity created but no ID returned for {name}")
                return None
        else:
            print(f"❌ Failed to add entity {name}: {response.status_code} - {response.text}")
            return None

async def enable_user_skills(user_id: str, skill_keys: list):
    """Enable skills for a user"""
    async with httpx.AsyncClient() as client:
        # Get skill IDs
        skills_response = await client.get(
            f"{SUPABASE_URL}/rest/v1/skills",
            headers=headers
        )

        if skills_response.status_code != 200:
            print(f"❌ Failed to fetch skills")
            return

        skills = skills_response.json()
        skill_map = {s['skill_key']: s['id'] for s in skills}

        for skill_key in skill_keys:
            if skill_key not in skill_map:
                print(f"⚠️  Skill {skill_key} not found")
                continue

            skill_id = skill_map[skill_key]

            # Check if already enabled
            check_response = await client.get(
                f"{SUPABASE_URL}/rest/v1/user_skills?user_id=eq.{user_id}&skill_id=eq.{skill_id}",
                headers=headers
            )

            if check_response.status_code == 200 and len(check_response.json()) > 0:
                print(f"  ⚠️  Skill {skill_key} already enabled for user")
                continue

            # Enable skill
            response = await client.post(
                f"{SUPABASE_URL}/rest/v1/user_skills",
                headers=headers,
                json={
                    "user_id": user_id,
                    "skill_id": skill_id,
                    "is_enabled": True
                }
            )

            if response.status_code == 201:
                print(f"  ✅ Enabled skill {skill_key} for user")
            else:
                print(f"  ❌ Failed to enable skill {skill_key}: {response.status_code}")

async def main():
    print("=" * 70)
    print("Database Updates")
    print("=" * 70)

    # 1. Update JOURN3Y tenant (db3d1562-9d17-417d-877b-d105929d2914)
    print("\n1️⃣  Updating JOURN3Y tenant...")
    await update_tenant(
        tenant_id="db3d1562-9d17-417d-877b-d105929d2914",
        name="JOURN3Y",
        slug="JOURN3Y-demo"
    )

    # 2. Add users to JOURN3Y tenant
    print("\n2️⃣  Adding users to JOURN3Y tenant...")
    kevin_id = await add_user(
        tenant_id="db3d1562-9d17-417d-877b-d105929d2914",
        name="Kevin Morrell",
        phone="+61434825126",
        role="site_manager"
    )

    adam_id = await add_user(
        tenant_id="db3d1562-9d17-417d-877b-d105929d2914",
        name="Adam King",
        phone="+61405343986",
        role="site_manager"
    )

    # Enable skills for new users
    if kevin_id:
        print(f"  Enabling skills for Kevin Morrell...")
        await enable_user_skills(kevin_id, ["voice_notes", "site_updates"])

    if adam_id:
        print(f"  Enabling skills for Adam King...")
        await enable_user_skills(adam_id, ["voice_notes", "site_updates"])

    # 3. Add entity to second tenant (ba920f42-43df-44b5-a2e8-f740764a56d5)
    print("\n3️⃣  Adding entity to tenant ba920f42-43df-44b5-a2e8-f740764a56d5...")
    await add_entity(
        tenant_id="ba920f42-43df-44b5-a2e8-f740764a56d5",
        name="21 Leichhardt Street",
        identifier="LSB",
        address="21 Leichhardt Street, NSW, 2040",
        entity_type="sites"
    )

    # 4. Add user to second tenant
    print("\n4️⃣  Adding user to tenant ba920f42-43df-44b5-a2e8-f740764a56d5...")
    marshal_id = await add_user(
        tenant_id="ba920f42-43df-44b5-a2e8-f740764a56d5",
        name="Marshal Keen",
        phone="+61415823312",
        role="site_manager"
    )

    # Enable skills for Marshal
    if marshal_id:
        print(f"  Enabling skills for Marshal Keen...")
        await enable_user_skills(marshal_id, ["voice_notes", "site_updates"])

    print("\n" + "=" * 70)
    print("✨ Database updates completed!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
