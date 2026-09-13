"""Shared TLS configuration for outbound model-provider requests."""

import ssl

import certifi


USER_AGENT = "Future-Self/2.0"


def secure_context():
    """Return a strict TLS context backed by certifi's maintained CA bundle."""
    return ssl.create_default_context(cafile=certifi.where())


def request_headers(api_key):
    """Return provider headers with an explicit, non-secret client identity."""
    return {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
