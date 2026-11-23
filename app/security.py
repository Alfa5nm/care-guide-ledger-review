import base64
import os
import secrets


HOSTED = "RAILWAY_ENVIRONMENT" in os.environ or os.getenv("DOCINTEL_HOSTED") == "1"
HOST = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("DOCINTEL_PUBLIC_HOST")
PASSWORD = os.getenv("DOCINTEL_REVIEW_PASSWORD", "")
HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
if HOSTED:
    HOSTS = [host for host in (HOST, "healthcheck.railway.app") if host]


def validate_configuration():
    if HOSTED and (not HOST or len(PASSWORD) < 24 or os.getenv("DOCINTEL_LLM_URL")):
        raise RuntimeError("Hosted mode requires a public hostname, a reviewer password, and local extraction.")


def reviewer_authorized(authorization):
    scheme, _, credentials = authorization.partition(" ")
    expected = base64.b64encode(f"reviewer:{PASSWORD}".encode()).decode()
    return scheme.lower() == "basic" and credentials.isascii() and secrets.compare_digest(credentials, expected)
