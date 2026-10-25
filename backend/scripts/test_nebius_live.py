"""Explicit live smoke test for Nebius/NVIDIA Nemotron.

Run from backend/ with RUN_NEBIUS_INTEGRATION=1 and NEBIUS_API_KEY configured
in the environment or .env. This file is outside pytest test discovery.
"""

import os
import sys

from app.ai.llm import NebiusLLMClient
from app.config import get_settings


def main() -> int:
    if os.getenv("RUN_NEBIUS_INTEGRATION") != "1":
        print("Refusing live call: set RUN_NEBIUS_INTEGRATION=1 to opt in.", file=sys.stderr)
        return 2

    settings = get_settings()
    if not settings.nebius_api_key or not settings.nebius_api_key.get_secret_value().strip():
        print("Refusing live call: NEBIUS_API_KEY is not configured.", file=sys.stderr)
        return 2

    client = NebiusLLMClient()
    try:
        reply = client.complete(
            [
                {"role": "system", "content": "Reply with exactly: GAP-AI live check."},
                {"role": "user", "content": "GAP-AI live check."},
            ],
            temperature=0.0,
        )
        if not isinstance(reply, str) or not reply.strip():
            print("Nebius returned an empty completion.", file=sys.stderr)
            return 1
        print("Nebius live completion succeeded; response content withheld.")
        return 0
    except Exception as exc:
        # Do not print provider exception text; it may contain upstream details.
        print(f"Nebius live completion failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
