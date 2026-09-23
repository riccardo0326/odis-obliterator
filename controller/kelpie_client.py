"""Client for Kelpie AI Gateway (gemini-3.7-flash and multimodal models)."""

import base64
import io
import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image
import requests
from controller.config import Settings, get_settings

logger = logging.getLogger(__name__)


class KelpieError(Exception):
    """Base exception for Kelpie client operations."""
    pass


class KelpieAuthError(KelpieError):
    """Raised when Kelpie authentication or token retrieval fails."""
    pass


class KelpieRequestError(KelpieError):
    """Raised when an API request to Kelpie fails."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


class KelpieResponseError(KelpieError):
    """Raised when response parsing or structure extraction fails."""
    pass


def normalize_image_to_base64(
    image: Union[str, bytes, Image.Image],
    default_mime_type: str = "image/png",
) -> Tuple[str, str]:
    """Normalize various image inputs (base64 str, data URI, bytes, PIL Image) to (b64_string, mime_type).

    Args:
        image: Image input as base64 string, data URI, raw bytes, or PIL Image.
        default_mime_type: Default MIME type if not detected.

    Returns:
        Tuple of (base64_payload_string, mime_type).
    """
    if isinstance(image, Image.Image):
        buf = io.BytesIO()
        fmt = "PNG"
        if default_mime_type == "image/jpeg":
            fmt = "JPEG"
        image.save(buf, format=fmt)
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        return b64_str, default_mime_type

    if isinstance(image, bytes):
        b64_str = base64.b64encode(image).decode("utf-8")
        return b64_str, default_mime_type

    if isinstance(image, str):
        # Check if it's a data URI scheme like data:image/png;base64,...
        match = re.match(r"^data:(image/[a-zA-Z0-9.+_-]+);base64,(.+)$", image, re.DOTALL)
        if match:
            mime = match.group(1)
            raw_b64 = match.group(2).strip()
            return raw_b64, mime
        # Standard base64 string
        return image.strip(), default_mime_type

    raise ValueError(f"Unsupported image type: {type(image)}")


def strip_markdown_codeblocks(text: str) -> str:
    """Strip markdown codeblock wrappers (e.g., ```json ... ```) from text."""
    text = text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"^```(?:json|JSON)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


class KelpieClient:
    """Client for interacting with Kelpie AI Gateway and multimodal models."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        verify_ssl: bool = True,
        use_proxy: bool = True,
    ):
        """Initialize KelpieClient.

        Args:
            settings: Settings instance (defaults to global settings).
            token: Explicit access token (overrides environment and CLI).
            base_url: Base URL for Kelpie gateway/proxy.
            model: Model name (defaults to settings.kelpie_model).
            timeout: Request timeout in seconds.
            verify_ssl: Whether to verify SSL certificates for direct HTTPS calls.
            use_proxy: Whether to use the local Kelpie proxy if available.
        """
        self.settings = settings or get_settings()
        self._explicit_token = token
        self._cached_token: Optional[str] = token
        self.use_proxy = use_proxy
        self.model = model or self.settings.kelpie_model
        self.timeout = timeout if timeout is not None else self.settings.timeout
        self.verify_ssl = verify_ssl

        # Determine default base URL
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.use_proxy:
            self.base_url = self.settings.kelpie_proxy_url.rstrip("/")
        else:
            self.base_url = self.settings.kelpie_base_url.rstrip("/")

        self.session = requests.Session()

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Retrieve a valid access token for Kelpie.

        Resolution order:
        1. Explicit token supplied at initialization (if not forced refresh).
        2. Cached token (if not forced refresh).
        3. Environment variables (KELPIE_ACCESS_TOKEN, KELPIE_TOKEN).
        4. Kelpie CLI output from `kelpie auth print-access-token`.

        Args:
            force_refresh: If True, bypass cache and re-obtain token.

        Returns:
            Bearer access token string.

        Raises:
            KelpieAuthError: If token cannot be retrieved.
        """
        if not force_refresh and self._cached_token:
            return self._cached_token

        # Check environment variables
        env_token = os.environ.get("KELPIE_ACCESS_TOKEN") or os.environ.get("KELPIE_TOKEN")
        if env_token and not force_refresh:
            self._cached_token = env_token.strip()
            return self._cached_token

        # Query kelpie CLI
        try:
            result = subprocess.run(
                ["kelpie", "auth", "print-access-token"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                self._cached_token = result.stdout.strip()
                return self._cached_token
            err_msg = result.stderr.strip() or f"CLI exited with return code {result.returncode}"
            raise KelpieAuthError(f"Failed to obtain token via 'kelpie auth print-access-token': {err_msg}")
        except FileNotFoundError as exc:
            raise KelpieAuthError(
                "Kelpie CLI ('kelpie.exe') is not installed or not in PATH, and no KELPIE_ACCESS_TOKEN set."
            ) from exc
        except subprocess.SubprocessError as exc:
            raise KelpieAuthError(f"Error executing Kelpie CLI: {exc}") from exc

    def get_endpoint_url(self, model: Optional[str] = None) -> str:
        """Construct the target endpoint URL for the specified model.

        Args:
            model: Model name. Defaults to self.model.

        Returns:
            Full endpoint URL.
        """
        target_model = model or self.model
        base = self.base_url.rstrip("/")

        # Gemini model family
        if "gemini" in target_model.lower():
            return f"{base}/gemini/v1beta/models/{target_model}:generateContent"

        # OpenAI compatible models
        return f"{base}/openai/v1/chat/completions"

    def _build_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Build request headers with authorization."""
        tok = token or self.get_access_token()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
        }
        return headers

    def _build_gemini_payload(
        self,
        prompt: str,
        image_base64: Optional[Union[str, bytes, Image.Image]] = None,
        mime_type: str = "image/png",
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> Dict[str, Any]:
        """Build Gemini generateContent request payload."""
        parts: List[Dict[str, Any]] = [{"text": prompt}]

        if image_base64 is not None:
            raw_b64, detected_mime = normalize_image_to_base64(image_base64, default_mime_type=mime_type)
            parts.append({
                "inline_data": {
                    "mime_type": detected_mime,
                    "data": raw_b64,
                }
            })

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        return payload

    def _build_openai_payload(
        self,
        prompt: str,
        image_base64: Optional[Union[str, bytes, Image.Image]] = None,
        mime_type: str = "image/png",
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build OpenAI chat completions request payload."""
        messages: List[Dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        user_content: Union[str, List[Dict[str, Any]]]
        if image_base64 is not None:
            raw_b64, detected_mime = normalize_image_to_base64(image_base64, default_mime_type=mime_type)
            user_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{detected_mime};base64,{raw_b64}"},
                },
            ]
        else:
            user_content = prompt

        messages.append({"role": "user", "content": user_content})

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        return payload

    def generate_content(
        self,
        prompt: str,
        image_base64: Optional[Union[str, bytes, Image.Image]] = None,
        mime_type: str = "image/png",
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a content generation request to Kelpie (multimodal: text + optional image).

        Args:
            prompt: Text prompt / instruction.
            image_base64: Optional image as base64 string, data URI, raw bytes, or PIL Image.
            mime_type: Image MIME type (default "image/png").
            system_instruction: Optional system instruction.
            json_mode: If True, request JSON response MIME type.
            temperature: Sampling temperature (default 0.0 for deterministic output).
            model: Model override (default self.model).

        Returns:
            Raw response JSON dictionary from the model endpoint.

        Raises:
            KelpieRequestError: If network request or HTTP call fails.
            KelpieAuthError: If authentication fails and cannot be refreshed.
        """
        target_model = model or self.model
        url = self.get_endpoint_url(model=target_model)
        if "gemini" in target_model.lower():
            payload = self._build_gemini_payload(
                prompt=prompt,
                image_base64=image_base64,
                mime_type=mime_type,
                system_instruction=system_instruction,
                json_mode=json_mode,
                temperature=temperature,
            )
        else:
            payload = self._build_openai_payload(
                prompt=prompt,
                image_base64=image_base64,
                mime_type=mime_type,
                system_instruction=system_instruction,
                json_mode=json_mode,
                temperature=temperature,
                model=target_model,
            )

        headers = self._build_headers()

        try:
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )

            # Handle 401 Unauthorized by refreshing token and retrying once
            if response.status_code == 401:
                logger.warning("Kelpie returned 401 Unauthorized. Refreshing token and retrying...")
                refreshed_token = self.get_access_token(force_refresh=True)
                headers = self._build_headers(token=refreshed_token)
                response = self.session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                    verify=self.verify_ssl,
                )

            if response.status_code != 200:
                raise KelpieRequestError(
                    f"Kelpie API error [{response.status_code}]: {response.text}",
                    status_code=response.status_code,
                    response_text=response.text,
                )

            return response.json()

        except requests.RequestException as exc:
            raise KelpieRequestError(f"Network error connecting to Kelpie at {url}: {exc}") from exc

    def extract_text(self, response_json: Dict[str, Any]) -> str:
        """Extract generated text content from a Gemini or OpenAI response payload.

        Args:
            response_json: Raw response dictionary from model endpoint.

        Returns:
            Extracted text content.

        Raises:
            KelpieResponseError: If response structure is unexpected or candidates/choices are missing.
        """
        try:
            # Check OpenAI style response: choices[0].message.content
            if "choices" in response_json and response_json["choices"]:
                choice = response_json["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "")
                if content:
                    return content.strip()

            # Check Gemini style response: candidates[0].content.parts
            candidates = response_json.get("candidates", [])
            if candidates:
                candidate = candidates[0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                if not parts:
                    raise KelpieResponseError(f"No parts found in candidate content: {candidate}")

                # Collect text parts
                text_chunks = [p["text"] for p in parts if "text" in p]
                if not text_chunks:
                    raise KelpieResponseError(f"No text field found in parts: {parts}")

                return "".join(text_chunks).strip()

            raise KelpieResponseError(f"Neither choices nor candidates found in Kelpie response: {response_json}")

        except (KeyError, TypeError, IndexError) as exc:
            raise KelpieResponseError(f"Failed to parse text from Kelpie response: {exc}") from exc

    def generate_json(
        self,
        prompt: str,
        image_base64: Optional[Union[str, bytes, Image.Image]] = None,
        mime_type: str = "image/png",
        system_instruction: Optional[str] = None,
        temperature: float = 0.0,
        model: Optional[str] = None,
    ) -> Any:
        """Generate structured JSON content from multimodal prompt.

        Args:
            prompt: Text prompt with instructions.
            image_base64: Optional image input.
            mime_type: Image MIME type.
            system_instruction: Optional system instruction.
            temperature: Sampling temperature (default 0.0).
            model: Model override.

        Returns:
            Parsed Python object (dict or list) from JSON output.

        Raises:
            KelpieResponseError: If response cannot be parsed as valid JSON.
            KelpieRequestError: If network request fails.
        """
        raw_response = self.generate_content(
            prompt=prompt,
            image_base64=image_base64,
            mime_type=mime_type,
            system_instruction=system_instruction,
            json_mode=True,
            temperature=temperature,
            model=model,
        )

        text = self.extract_text(raw_response)
        clean_text = strip_markdown_codeblocks(text)

        try:
            return json.loads(clean_text)
        except json.JSONDecodeError as exc:
            raise KelpieResponseError(
                f"Failed to decode JSON from model response: {exc}. Response text: {clean_text[:500]}"
            ) from exc

    def check_health(self) -> Dict[str, Any]:
        """Check Kelpie Gateway connectivity and token status.

        Returns:
            Dict containing health status details.
        """
        try:
            token = self.get_access_token()
            token_valid = bool(token)
        except Exception as exc:
            return {
                "status": "error",
                "kelpie": "auth_failed",
                "model": self.model,
                "error": str(exc),
            }

        # Test simple ping/prompt
        try:
            url = self.get_endpoint_url()
            payload = self._build_gemini_payload(prompt="ping", json_mode=False)
            headers = self._build_headers(token=token)
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=min(self.timeout, 5.0),
                verify=self.verify_ssl,
            )
            if response.status_code == 200:
                return {
                    "status": "ok",
                    "kelpie": "connected",
                    "model": self.model,
                    "endpoint": url,
                }
            return {
                "status": "degraded",
                "kelpie": f"http_{response.status_code}",
                "model": self.model,
                "error": response.text,
            }
        except Exception as exc:
            return {
                "status": "error",
                "kelpie": "unreachable",
                "model": self.model,
                "error": str(exc),
            }
