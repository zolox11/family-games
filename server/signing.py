import hashlib
import hmac
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def canonical(report: dict) -> bytes:
    return json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(report: dict) -> str:
    secret = os.environ.get("JUDGE_SECRET")
    if not secret:
        raise RuntimeError("JUDGE_SECRET is not set; configure it in .env before judging")
    return hmac.new(secret.encode("utf-8"), canonical(report), hashlib.sha256).hexdigest()


def verify(report: dict, signature: str) -> bool:
    if not isinstance(signature, str) or len(signature) != 64 or any(char not in "0123456789abcdefABCDEF" for char in signature):
        return False
    try:
        return hmac.compare_digest(sign(report), signature)
    except RuntimeError:
        return False
