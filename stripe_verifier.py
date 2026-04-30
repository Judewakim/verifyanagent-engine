# stripe_verifier.py
import stripe
import os

def verify(event):
    """
    Checks that the incoming request genuinely came from Stripe.
    - event: the raw API Gateway event dict Lambda receives
    Returns the parsed Stripe event object if valid.
    Raises ValueError if the signature is wrong or missing.
    """
    # The raw request body as a string (Stripe requires the exact raw bytes)
    body = event.get('body', '')

    # Stripe sends a signature in this header with every webhook
    headers = event.get('headers', {})
    sig_header = (
        headers.get('Stripe-Signature')
        or headers.get('stripe-signature')
    )

    if not sig_header:
        raise ValueError("Missing Stripe-Signature header - request rejected.")

    # Your webhook signing secret from Stripe Dashboard  Webhooks
    webhook_secret = os.environ['STRIPE_WEBHOOK_SECRET']

    try:
        # This does the cryptographic verification
        stripe_event = stripe.Webhook.construct_event(
            payload=body,
            sig_header=sig_header,
            secret=webhook_secret
        )
        return stripe_event
    except stripe.error.SignatureVerificationError:
        raise ValueError("Stripe signature verification failed - request rejected.")
    except Exception as e:
        raise ValueError(f"Could not parse Stripe event: {e}")
