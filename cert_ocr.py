# cert_ocr.py
import base64
from typing import Optional

import anthropic
from pydantic import BaseModel

# Module-level client (reuses TCP/TLS connections across Lambda invocations,
# same pattern as the s3 client in s3_manager.py).
# Reads ANTHROPIC_API_KEY from the Lambda environment.
_client = anthropic.Anthropic()


class CertExtraction(BaseModel):
    """Structured output schema for the Haiku vision call."""
    license_number: Optional[str]
    confidence: str  # "high" | "medium" | "low"
    # Name self-consistency check: the individual producer/licensee name printed on
    # the cert, and whether it refers to the same person as the name the agent typed
    # on the onboarding form. Both are None when no name is found / can't be judged.
    name_on_cert: Optional[str]
    name_matches: Optional[bool]


def extract_cert(
    pdf_bytes: bytes, state_abbrev: str, state_name: str, agent_name: str
) -> Optional[CertExtraction]:
    """
    Runs the Claude Haiku 4.5 vision pass over one certificate PDF and returns the
    full parsed extraction (license number + name check), or None if the API call
    failed.

    pdf_bytes:    Raw bytes of the certificate PDF
    state_abbrev: Two-letter state code, e.g. 'FL'
    state_name:   Full state name, e.g. 'Florida'
    agent_name:   The name the agent typed on the onboarding form, used for the
                  name self-consistency check.

    Callers apply their own rules to the result (e.g. treat "low" confidence
    license numbers as unusable — see extract_license_number below).
    """
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = (
        f"This is an insurance license certificate for the state of {state_name} ({state_abbrev}).\n\n"
        f"1. Extract ONLY the state-issued license number, producer number, or agent number from this certificate. "
        f"Do NOT return the NPN (National Producer Number) — that's a federal number, not the state-issued one. "
        f"If you cannot find a clear state-issued license number, set license_number to null.\n"
        f"Confidence levels for the license number:\n"
        f"  - 'high': clearly labeled state license number found\n"
        f"  - 'medium': a number is present that is likely the license number, but the label is ambiguous\n"
        f"  - 'low': a number is present but you're not confident it's the license number\n\n"
        f"2. Extract the individual producer/licensee's name printed on this certificate into "
        f"name_on_cert (ignore agency or business entity names — we want the person). If no "
        f"individual name is printed, set name_on_cert to null.\n"
        f"The applicant claims their name is '{agent_name}'. Set name_matches to true if the name "
        f"on the certificate refers to the same person as the claimed name, or false if it clearly "
        f"refers to a different person. Account for middle names, initials, suffixes (Jr/Sr/III), "
        f"nicknames, and word order — minor variations should be treated as a match. If you cannot "
        f"find a name or cannot judge, set name_matches to null."
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
            output_format=CertExtraction,
        )
    except Exception as e:
        print(f"  OCR error for {state_abbrev}: {type(e).__name__}: {e}")
        return None

    result = response.parsed_output
    usage = response.usage
    print(
        f"  OCR {state_abbrev}: license={result.license_number!r} "
        f"confidence={result.confidence} "
        f"name_on_cert={result.name_on_cert!r} name_matches={result.name_matches} "
        f"tokens_in={usage.input_tokens} tokens_out={usage.output_tokens}"
    )

    return result


def usable_license_number(result: Optional[CertExtraction]) -> Optional[str]:
    """
    Apply the license-number acceptance rule to an extract_cert() result: return the
    license number only if one was found with better-than-low confidence, else None.
    """
    if result is None:
        return None
    if not result.license_number or result.confidence == "low":
        return None
    return result.license_number


def extract_license_number(pdf_bytes: bytes, state_abbrev: str, state_name: str) -> Optional[str]:
    """
    Backward-compatible wrapper: extract just the state-issued license number from a
    certificate PDF. Returns the number string, or None if OCR found nothing usable
    or the API call failed. (agent_name is irrelevant here, so a placeholder is passed.)
    """
    return usable_license_number(
        extract_cert(pdf_bytes, state_abbrev, state_name, agent_name="")
    )
