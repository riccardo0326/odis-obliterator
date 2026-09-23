"""Unit and integration tests for KelpieClient (TASK-002)."""

import base64
import io
import json
import subprocess
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
import requests

from controller.config import Settings
from controller.kelpie_client import (
    KelpieAuthError,
    KelpieClient,
    KelpieError,
    KelpieRequestError,
    KelpieResponseError,
    normalize_image_to_base64,
    strip_markdown_codeblocks,
)


# ---------------------------------------------------------------------------
# Helpers & Image Utilities Tests
# ---------------------------------------------------------------------------

def test_normalize_image_from_pil():
    """Verify normalizing a PIL Image generates valid Base64 string."""
    img = Image.new("RGB", (20, 20), color="blue")
    b64_str, mime = normalize_image_to_base64(img)
    assert mime == "image/png"
    assert isinstance(b64_str, str)
    assert len(b64_str) > 0

    # Ensure decoded bytes can be reopened by PIL
    raw_bytes = base64.b64decode(b64_str)
    reloaded = Image.open(io.BytesIO(raw_bytes))
    assert reloaded.size == (20, 20)


def test_normalize_image_from_pil_jpeg():
    """Verify normalizing PIL Image with JPEG mime type."""
    img = Image.new("RGB", (10, 10), color="green")
    b64_str, mime = normalize_image_to_base64(img, default_mime_type="image/jpeg")
    assert mime == "image/jpeg"
    assert isinstance(b64_str, str)


def test_normalize_image_from_bytes():
    """Verify normalizing raw image bytes."""
    dummy_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b64_str, mime = normalize_image_to_base64(dummy_bytes)
    assert mime == "image/png"
    assert b64_str == base64.b64encode(dummy_bytes).decode("utf-8")


def test_normalize_image_from_data_uri():
    """Verify parsing data URI scheme extracting mime and raw base64."""
    sample_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    data_uri = f"data:image/jpeg;base64,{sample_b64}"
    b64_str, mime = normalize_image_to_base64(data_uri)
    assert mime == "image/jpeg"
    assert b64_str == sample_b64


def test_normalize_image_from_raw_base64_string():
    """Verify raw base64 string handling."""
    sample_b64 = " iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=\n"
    b64_str, mime = normalize_image_to_base64(sample_b64)
    assert mime == "image/png"
    assert b64_str == sample_b64.strip()


def test_normalize_image_invalid_type():
    """Verify ValueError when passing unsupported object type."""
    with pytest.raises(ValueError, match="Unsupported image type"):
        normalize_image_to_base64(12345)  # type: ignore


def test_strip_markdown_codeblocks():
    """Verify codeblock stripping logic."""
    json_str = '{\n  "blocks": []\n}'
    assert strip_markdown_codeblocks(f"```json\n{json_str}\n```") == json_str
    assert strip_markdown_codeblocks(f"```JSON\n{json_str}\n```") == json_str
    assert strip_markdown_codeblocks(f"```\n{json_str}\n```") == json_str
    assert strip_markdown_codeblocks(json_str) == json_str


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

def test_get_access_token_explicit():
    """Verify explicit token supplied in constructor takes precedence."""
    client = KelpieClient(token="explicit_secret_token_123")
    assert client.get_access_token() == "explicit_secret_token_123"


def test_get_access_token_from_env(monkeypatch):
    """Verify token retrieval from KELPIE_ACCESS_TOKEN environment variable."""
    monkeypatch.setenv("KELPIE_ACCESS_TOKEN", "env_token_abc")
    client = KelpieClient()
    assert client.get_access_token() == "env_token_abc"


def test_get_access_token_from_cli():
    """Verify token retrieval via `kelpie auth print-access-token` CLI."""
    client = KelpieClient()
    mock_res = MagicMock(returncode=0, stdout="cli_retrieved_jwt_token\n", stderr="")
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        token = client.get_access_token(force_refresh=True)
        assert token == "cli_retrieved_jwt_token"
        mock_run.assert_called_once_with(
            ["kelpie", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )


def test_get_access_token_cli_error(monkeypatch):
    """Verify KelpieAuthError is raised when CLI command fails."""
    monkeypatch.delenv("KELPIE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("KELPIE_TOKEN", raising=False)
    client = KelpieClient()
    mock_res = MagicMock(returncode=1, stdout="", stderr="Session expired")
    with patch("subprocess.run", return_value=mock_res):
        with pytest.raises(KelpieAuthError, match="Session expired"):
            client.get_access_token(force_refresh=True)


def test_get_access_token_cli_not_found(monkeypatch):
    """Verify KelpieAuthError is raised when kelpie executable is not found."""
    monkeypatch.delenv("KELPIE_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("KELPIE_TOKEN", raising=False)
    client = KelpieClient()
    with patch("subprocess.run", side_effect=FileNotFoundError("Executable not found")):
        with pytest.raises(KelpieAuthError, match="not installed or not in PATH"):
            client.get_access_token(force_refresh=True)


# ---------------------------------------------------------------------------
# Endpoint & Payload Construction Tests
# ---------------------------------------------------------------------------

def test_endpoint_url_construction():
    """Verify Gemini and OpenAI endpoint URL construction."""
    settings = Settings(kelpie_proxy_url="http://127.0.0.1:18080", kelpie_model="gemini-3.7-flash")
    client = KelpieClient(settings=settings)

    gemini_url = client.get_endpoint_url()
    assert gemini_url == "http://127.0.0.1:18080/gemini/v1beta/models/gemini-3.7-flash:generateContent"

    gemini_38_url = client.get_endpoint_url(model="gemini-3.8-flash")
    assert gemini_38_url == "http://127.0.0.1:18080/gemini/v1beta/models/gemini-3.8-flash:generateContent"

    openai_url = client.get_endpoint_url(model="gpt-5.6-luna-gwc")
    assert openai_url == "http://127.0.0.1:18080/openai/v1/chat/completions"


def test_build_gemini_payload_text_only():
    """Verify building payload for text-only prompt."""
    client = KelpieClient()
    payload = client._build_gemini_payload(
        prompt="Identify blocks in canvas",
        temperature=0.2,
        json_mode=True,
        system_instruction="You are a vision assistant.",
    )

    assert payload["contents"][0]["role"] == "user"
    assert payload["contents"][0]["parts"] == [{"text": "Identify blocks in canvas"}]
    assert payload["generationConfig"]["temperature"] == 0.2
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert payload["systemInstruction"]["parts"] == [{"text": "You are a vision assistant."}]


def test_build_gemini_payload_multimodal():
    """Verify building multimodal payload with image."""
    client = KelpieClient()
    img = Image.new("RGB", (10, 10), color="red")

    payload = client._build_gemini_payload(
        prompt="Detect blocks in this screenshot",
        image_base64=img,
        mime_type="image/png",
        json_mode=False,
    )

    parts = payload["contents"][0]["parts"]
    assert len(parts) == 2
    assert parts[0] == {"text": "Detect blocks in this screenshot"}
    assert "inline_data" in parts[1]
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert isinstance(parts[1]["inline_data"]["data"], str)


def test_build_openai_payload():
    """Verify building payload for OpenAI compatible endpoints."""
    client = KelpieClient()
    img = Image.new("RGB", (10, 10), color="blue")
    payload = client._build_openai_payload(
        prompt="Analyze screenshot",
        image_base64=img,
        system_instruction="Act as vision system.",
        json_mode=True,
        model="gpt-5.6-luna-gwc",
    )
    assert payload["model"] == "gpt-5.6-luna-gwc"
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert payload["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# API Request & Text Extraction Tests (Mocked)
# ---------------------------------------------------------------------------

def test_extract_text_success_gemini():
    """Verify extracting text from standard Gemini response structure."""
    client = KelpieClient()
    raw_response = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": '{"blocks": [{"type": "MESSAGE"}]}'}
                    ]
                },
                "finishReason": "STOP"
            }
        ]
    }
    extracted = client.extract_text(raw_response)
    assert extracted == '{"blocks": [{"type": "MESSAGE"}]}'


def test_extract_text_success_openai():
    """Verify extracting text from OpenAI chat completion response structure."""
    client = KelpieClient()
    raw_response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"blocks": [{"type": "QUESTION"}]}'
                }
            }
        ]
    }
    extracted = client.extract_text(raw_response)
    assert extracted == '{"blocks": [{"type": "QUESTION"}]}'


def test_extract_text_missing_candidates():
    """Verify error raised when candidates list is empty."""
    client = KelpieClient()
    with pytest.raises(KelpieResponseError, match="Neither choices nor candidates found"):
        client.extract_text({"candidates": []})


def test_extract_text_empty_parts():
    """Verify error raised when content parts are missing."""
    client = KelpieClient()
    with pytest.raises(KelpieResponseError, match="No parts found"):
        client.extract_text({"candidates": [{"content": {"parts": []}}]})


def test_generate_content_success_mocked():
    """Verify generate_content performs HTTP POST and returns JSON."""
    client = KelpieClient(token="mock_token_123")
    fake_response_data = {
        "candidates": [{"content": {"parts": [{"text": "Hello world"}]}}]
    }

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = fake_response_data

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        result = client.generate_content("Hello prompt")
        assert result == fake_response_data
        mock_post.assert_called_once()
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer mock_token_123"


def test_generate_content_401_retry_success():
    """Verify 401 response triggers token refresh and second attempt succeeds."""
    client = KelpieClient(token="old_token")

    resp_401 = MagicMock(status_code=401, text="Unauthorized")
    resp_200 = MagicMock(status_code=200)
    resp_200.json.return_value = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}

    with patch.object(client.session, "post", side_effect=[resp_401, resp_200]):
        with patch.object(client, "get_access_token", return_value="new_refreshed_token"):
            res = client.generate_content("Test retry")
            assert res == {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}


def test_generate_content_http_error():
    """Verify HTTP error status raises KelpieRequestError."""
    client = KelpieClient(token="mock_token")
    mock_resp = MagicMock(status_code=500, text="Internal Server Error")

    with patch.object(client.session, "post", return_value=mock_resp):
        with pytest.raises(KelpieRequestError) as exc_info:
            client.generate_content("Test error")
        assert exc_info.value.status_code == 500
        assert "Internal Server Error" in exc_info.value.response_text


def test_generate_content_network_error():
    """Verify connection failure raises KelpieRequestError."""
    client = KelpieClient(token="mock_token")
    with patch.object(client.session, "post", side_effect=requests.ConnectionError("Connection refused")):
        with pytest.raises(KelpieRequestError, match="Network error connecting to Kelpie"):
            client.generate_content("Test connect")


def test_generate_json_success_mocked():
    """Verify generate_json returns deserialized Python dict."""
    client = KelpieClient(token="mock_token")
    expected_data = {
        "blocks": [
            {"type": "MESSAGE", "relative_x": 0.45, "relative_y": 0.32, "label": "Message Test"}
        ]
    }
    raw_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": f"```json\n{json.dumps(expected_data)}\n```"}
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = raw_response

    with patch.object(client.session, "post", return_value=mock_resp):
        parsed = client.generate_json("Find blocks", image_base64=Image.new("RGB", (10, 10)))
        assert parsed == expected_data


def test_generate_json_invalid_format_error():
    """Verify KelpieResponseError when model outputs invalid JSON."""
    client = KelpieClient(token="mock_token")
    raw_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "This is plain text without valid JSON formatting."}
                    ]
                }
            }
        ]
    }
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = raw_response

    with patch.object(client.session, "post", return_value=mock_resp):
        with pytest.raises(KelpieResponseError, match="Failed to decode JSON"):
            client.generate_json("Prompt")


def test_check_health_ok():
    """Verify check_health returns ok status when gateway responds 200."""
    client = KelpieClient(token="mock_token")
    mock_resp = MagicMock(status_code=200)

    with patch.object(client.session, "post", return_value=mock_resp):
        health = client.check_health()
        assert health["status"] == "ok"
        assert health["kelpie"] == "connected"
        assert health["model"] == client.model


def test_check_health_auth_failure():
    """Verify check_health returns error when token cannot be acquired."""
    client = KelpieClient()
    with patch.object(client, "get_access_token", side_effect=KelpieAuthError("No auth")):
        health = client.check_health()
        assert health["status"] == "error"
        assert health["kelpie"] == "auth_failed"


# ---------------------------------------------------------------------------
# Acceptance Criteria: Live Multimodal Test with gemini-3.7-flash
# ---------------------------------------------------------------------------

def test_live_multimodal_gemini_call():
    """Acceptance criteria test: Send test image to gemini-3.7-flash and receive JSON response."""
    # Check if we can obtain a real token and proxy/gateway is running
    client = KelpieClient()
    try:
        token = client.get_access_token()
    except KelpieAuthError:
        pytest.skip("Kelpie auth token not available for live multimodal test")

    # Create a synthetic 50x50 canvas screenshot with a red square
    test_img = Image.new("RGB", (50, 50), color="blue")

    prompt = (
        "You are a canvas vision test agent. Analyze the provided 50x50 image and return JSON: "
        '{"detected_color": "blue", "width": 50, "height": 50, "status": "ok"}'
    )

    try:
        result = client.generate_json(
            prompt=prompt,
            image_base64=test_img,
            mime_type="image/png",
            system_instruction="Always output raw JSON adhering to the user specification.",
        )
        assert isinstance(result, dict)
        assert "status" in result or "detected_color" in result
    except KelpieRequestError as exc:
        pytest.skip(f"Kelpie endpoint unreachable or offline during live test: {exc}")
