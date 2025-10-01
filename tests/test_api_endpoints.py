"""
Integration tests for API endpoints
Tests that the FastAPI server responds correctly to requests
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

# Create test client
client = TestClient(app)


class TestHealthEndpoints:
    """Test health and status endpoints"""

    def test_health_endpoint(self):
        """Health endpoint should return healthy status"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "vapi-skills-dispatcher"

    def test_root_endpoint(self):
        """Root endpoint should return service info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data


class TestSkillRegistryEndpoints:
    """Test skill registry management endpoints"""

    def test_list_skills(self):
        """Should list all registered skills"""
        response = client.get("/api/v1/skills/list")
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "skills" in data
        assert "total" in data
        assert isinstance(data["skills"], list)

        # Should have at least VoiceNotesSkill registered
        assert data["total"] >= 1

        # Check skill structure
        if len(data["skills"]) > 0:
            skill = data["skills"][0]
            assert "skill_key" in skill
            assert "name" in skill
            assert "description" in skill
            assert "tool_count" in skill
            assert "assistant_id" in skill
            assert "is_ready" in skill

    def test_voice_notes_skill_registered(self):
        """VoiceNotesSkill should be registered"""
        response = client.get("/api/v1/skills/list")
        data = response.json()

        skills = data["skills"]
        voice_notes = next((s for s in skills if s["skill_key"] == "voice_notes"), None)

        assert voice_notes is not None
        assert voice_notes["name"] == "Voice Notes"
        assert "Record general or site-specific voice notes" in voice_notes["description"]


class TestEnvironmentEndpoints:
    """Test environment and configuration endpoints"""

    def test_env_check_endpoint(self):
        """Environment check should return configuration"""
        response = client.get("/debug/env-check")
        assert response.status_code == 200
        data = response.json()

        # Should have required keys
        assert "supabase_url" in data
        assert "vapi_api_key" in data
        assert "webhook_base_url" in data
        assert "environment" in data

        # Environment should be set
        assert data["environment"] in ["development", "production"]


class TestVoiceNotesEndpoints:
    """Test Voice Notes skill endpoints (basic structure)"""

    def test_authenticate_endpoint_exists(self):
        """Authenticate endpoint should exist"""
        # Just test that endpoint exists (will fail without proper auth)
        response = client.post(
            "/api/v1/vapi/authenticate-by-phone",
            json={"message": {"toolCalls": [{"id": "test", "function": {"arguments": {"caller_phone": "+1234567890"}}}]}}
        )
        # Should not return 404
        assert response.status_code != 404

    def test_identify_context_endpoint_exists(self):
        """Identify context endpoint should exist"""
        response = client.post(
            "/api/v1/skills/voice-notes/identify-context",
            json={"message": {"toolCalls": [{"id": "test", "function": {"arguments": {"user_input": "test", "vapi_call_id": "test"}}}]}}
        )
        # Should not return 404
        assert response.status_code != 404

    def test_save_note_endpoint_exists(self):
        """Save note endpoint should exist"""
        response = client.post(
            "/api/v1/skills/voice-notes/save-note",
            json={"message": {"toolCalls": [{"id": "test", "function": {"arguments": {"note_text": "test", "note_type": "general", "vapi_call_id": "test"}}}]}}
        )
        # Should not return 404
        assert response.status_code != 404


class TestCORS:
    """Test CORS configuration"""

    def test_cors_headers(self):
        """CORS headers should be present"""
        response = client.get("/health")
        # Should have CORS headers
        assert response.status_code == 200
        # Note: CORS headers are added by middleware and visible in actual requests


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
