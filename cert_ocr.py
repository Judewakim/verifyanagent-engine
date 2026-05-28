# cert_ocr.py
import base64
from typing import Optional

import anthropic
from pydantic import BaseModel

# Module-level client (reuses TCP/TLS connections across Lambda invocations,
# same pattern as the s3 client in s3_manager.py).
# Reads ANTHROPIC_API_KEY from the Lambda environment.
_client = anthropic.Anthropic()


class LicenseExtraction(BaseModel):
    """Structured output schema for the Haiku vision call."""
    license_number: Optional[str]
    confidence: str  # "high" | "medium" | "low"


def extract_license_number(pdf_bytes: bytes, state_abbrev: str, state_name: str) -> Optional[str]:
    """
    Extracts the state-issued insurance license number from a certificate PDF
    using Claude Haiku 4.5 vision.

    pdf_bytes:    Raw bytes of the certificate PDF
    state_abbrev: Two-letter state code, e.g. 'FL'
    state_name:   Full state name, e.g. 'Florida'

    Returns the extracted license number string, or None if:
      - OCR could not find a license number
      - confidence is "low"
      - the API call failed
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = (
        f"This is an insurance license certificate for the state of {state_name} ({state_abbrev}). "
        f"Extract ONLY the state-issued license number, producer number, or agent number from this certificate. "
        f"Do NOT return the NPN (National Producer Number) — that's a federal number, not the state-issued one. "
        f"If you cannot find a clear state-issued license number, set license_number to null.\n\n"
        f"Confidence levels:\n"
        f"  - 'high': clearly labeled state license number found\n"
        f"  - 'medium': a number is present that is likely the license number, but the label is ambiguous\n"
        f"  - 'low': a number is present but you're not confident it's the license number"
    )

    try:
        response = _client.messages.parse(
            model="claude-haiku-4-5",
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }],
            output_format=LicenseExtraction,
        )
    except Exception as e:
        print(f"  OCR error for {state_abbrev}: {type(e).__name__}: {e}")
        return None

    result = response.parsed_output
    usage = response.usage
    print(
        f"  OCR {state_abbrev}: license={result.license_number!r} "
        f"confidence={result.confidence} "
        f"tokens_in={usage.input_tokens} tokens_out={usage.output_tokens}"
    )

    if not result.license_number or result.confidence == "low":
        return None

    return result.license_number
