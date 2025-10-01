# Site Progress Updates - VAPI Setup Guide

## Overview
This guide explains how to set up the Site Progress Updates feature in VAPI. The system follows the same pattern as Authentication and Voice Notes.

## Architecture

### Tools
1. **identify_site_for_update** - Fuzzy match site names from user descriptions
2. **save_site_progress_update** - Save progress updates with AI intelligence extraction

### Assistant
- **JSMB-Jill-site-progress** - Guides users through site progress logging

### Squad Integration
The Site Progress Assistant integrates into the existing JSMB-Jill-multi-skill-squad alongside Voice Notes.

## Setup Methods

### Option 1: Programmatic Setup (Recommended)

Use the FastAPI management endpoints to automatically create tools, assistant, and update the squad:

```bash
# Setup Site Progress system
curl -X POST https://your-domain.com/api/v1/vapi/setup-site-progress \
  -H "Content-Type: application/json" \
  -d '{
    "squad_id": "your-existing-squad-id",
    "auth_agent_id": "your-auth-agent-id",
    "voice_notes_agent_id": "your-voice-notes-agent-id"
  }'
```

**Response:**
```json
{
  "success": true,
  "site_progress_agent_id": "new-assistant-id",
  "squad_id": "updated-squad-id",
  "tool_ids": {
    "identify_site_for_update": "tool-id-1",
    "save_site_progress_update": "tool-id-2"
  },
  "message": "Site Progress system setup complete and added to squad!"
}
```

### Option 2: Manual Setup via VAPI Dashboard

#### Step 1: Create Tools

**Tool 1: identify_site_for_update**
- **Type**: Server Tool
- **Name**: `identify_site_for_update`
- **Description**: "Identifies which construction site the user wants to update based on fuzzy matching"
- **Server URL**: `https://your-domain.com/site-updates/identify-site`
- **Parameters**:
  ```json
  {
    "site_description": {
      "type": "string",
      "description": "The site name or description from the user"
    }
  }
  ```

**Tool 2: save_site_progress_update**
- **Type**: Server Tool
- **Name**: `save_site_progress_update`
- **Description**: "Saves a daily site progress update with AI-extracted intelligence"
- **Server URL**: `https://your-domain.com/site-updates/save-update`
- **Parameters**:
  ```json
  {
    "site_id": {
      "type": "string",
      "description": "The UUID of the construction site"
    },
    "raw_notes": {
      "type": "string",
      "description": "Complete raw voice notes from the user"
    }
  }
  ```

#### Step 2: Create Assistant

- **Name**: `JSMB-Jill-site-progress`
- **Model**: GPT-4
- **First Message**: "Hi! Ready to log your site progress for today. Which site are you updating?"
- **System Prompt**:
  ```
  You are Jill, a professional site progress assistant for construction companies.

  Your job is to help site managers quickly log daily site progress updates through natural conversation.

  CONVERSATION FLOW:
  1. Greet: "Hi! Ready to log your site progress for today. Which site are you updating?"
  2. Use identify_site_for_update to match their site description
  3. Once site is identified, guide them through sharing progress naturally
  4. Ask about: deliveries, issues, progress made, other updates
  5. Listen to their complete update - let them speak naturally
  6. When done, use save_site_progress_update to save everything

  CONVERSATION STYLE:
  - Warm, efficient, and professional
  - Natural conversation - don't make it feel like a form
  - Let them speak freely about each topic
  - Confirm when saved: "Got it! Your site progress update for [Site Name] has been recorded."

  IMPORTANT:
  - Always identify the site first
  - Capture ALL information in raw_notes
  - Don't interrupt their thoughts
  ```

- **Voice**: ElevenLabs Turbo v2.5 (voiceId: `MiueK1FXuZTCItgbQwPu`)
- **Tools**: Attach both tools created above

#### Step 3: Update Squad

Edit your existing `JSMB-Jill-multi-skill-squad`:

1. Add the new Site Progress Assistant as a member
2. Update Auth Assistant destinations to include:
   ```json
   {
     "type": "assistant",
     "assistantName": "JSMB-Jill-site-progress",
     "message": "Great! Let me help you log that site progress update..."
   }
   ```

**Final Squad Structure:**
```json
{
  "name": "JSMB-Jill-multi-skill-squad",
  "members": [
    {
      "assistant": "auth-agent-id",
      "assistantDestinations": [
        {
          "type": "assistant",
          "assistantName": "JSMB-Jill-voice-notes",
          "message": "Perfect! Connecting you to voice notes..."
        },
        {
          "type": "assistant",
          "assistantName": "JSMB-Jill-site-progress",
          "message": "Great! Let me help you log that site progress update..."
        }
      ]
    },
    {
      "assistant": "voice-notes-agent-id"
    },
    {
      "assistant": "site-progress-agent-id"
    }
  ]
}
```

## Verification

### Check Setup Status
```bash
curl https://your-domain.com/api/v1/vapi/site-progress-status
```

### Test the Endpoints

**Test Site Identification:**
```bash
curl -X POST https://your-domain.com/site-updates/identify-site \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "toolCalls": [{
        "id": "test-123",
        "function": {
          "name": "identify_site_for_update",
          "arguments": {
            "site_description": "ocean white house"
          }
        }
      }]
    }
  }'
```

**Test Save Update:**
```bash
curl -X POST https://your-domain.com/site-updates/save-update \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
  -d '{
    "message": {
      "toolCalls": [{
        "id": "test-456",
        "function": {
          "name": "save_site_progress_update",
          "arguments": {
            "site_id": "site-uuid",
            "raw_notes": "Concrete truck arrived at 9am. Poured foundation for west wing. No issues."
          }
        }
      }]
    }
  }'
```

## Expected User Flow

1. **User calls** → Auth Assistant authenticates
2. **Auth Assistant**: "Hi John! I can help you with voice notes or site progress updates. What would you like to do?"
3. **User**: "I need to log a site update"
4. **Transfers to Site Progress Assistant**
5. **Site Progress**: "Hi! Ready to log your site progress for today. Which site are you updating?"
6. **User**: "The ocean house project"
7. **Site Progress**: *Calls identify_site_for_update* → "Great! Logging progress for Ocean White House. What updates do you have?"
8. **User**: *Provides natural description of deliveries, issues, progress*
9. **Site Progress**: *Calls save_site_progress_update with raw notes* → "Got it! Your site progress update for Ocean White House has been recorded."

## Webhook Endpoints

The following endpoints are live on your server:

- **POST** `/site-updates/identify-site` - Site identification
- **POST** `/site-updates/save-update` - Save progress update
- **POST** `/api/v1/vapi/setup-site-progress` - Programmatic setup
- **GET** `/api/v1/vapi/site-progress-status` - Check status

## Environment Variables Required

```bash
VAPI_API_KEY=your-vapi-api-key
WEBHOOK_BASE_URL=https://your-domain.com
SUPABASE_URL=your-supabase-url
SUPABASE_SERVICE_KEY=your-supabase-key
OPENAI_API_KEY=your-openai-key  # For AI intelligence extraction
```

## Features

- **Fuzzy Site Matching**: Recognizes variations like "ocean house", "the ocean project", "white house site"
- **AI Intelligence Extraction**: GPT-4o-mini extracts structured data from raw voice notes
- **Multi-tenant Safe**: RLS policies ensure data isolation
- **Natural Conversation**: Free-form speech capture, not rigid forms
- **Complete Audit Trail**: Raw notes + extracted intelligence stored

## Troubleshooting

### Tools not appearing in Assistant
- Verify tools were created successfully
- Check tool IDs are correctly attached to assistant's `toolIds` array

### Site not identified
- Check Supabase `sites` table has sites for the user's tenant
- Review site names/addresses for fuzzy matching
- Check server logs for OpenAI API errors

### Save update fails
- Verify RLS policies on `site_progress_updates` table
- Check user authentication token is valid
- Review OpenAI API key for intelligence extraction

## Next Steps

After VAPI setup is complete:
1. Test with real phone calls through VAPI
2. Review intelligence extraction quality
3. Adjust conversation flow if needed
4. Monitor usage and refine prompts
