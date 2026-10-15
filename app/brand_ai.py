"""The brand name read from the pictures by an AI vision model (Amazon Nova on Bedrock), only when no brand was typed.

Brands are usually logos the text reader can't read: on 227 approved labels it found the brand as text on 95 (42%);
Nova Pro read it exactly on 142 and right or close on 188 (83%). So it is shown as what the label says, for the agent
to check, and never used to call a typed brand Matches. Off unless LABEL_BRAND_MODEL is set; any failure (no network
behind a firewall, a timeout) gives None and the page says the brand needs checking, as before.
"""

import io
import os
import re
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

MODEL = os.environ.get("LABEL_BRAND_MODEL", "")
PROMPT = ("These pictures are the labels of one alcohol beverage. What is the BRAND NAME printed on the label? "
          "Copy it exactly as printed, the words only (no class or type like 'Bourbon' or 'Lager', no size, no alcohol "
          "content, unless they are part of the brand). If you cannot read a brand name, reply NONE. "
          "Reply with the brand name only.")
_pool = ThreadPoolExecutor(4)


def _jpeg(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1600, 1600))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=88)
    return b.getvalue()


def read_brand(images: list[tuple[str, bytes]]) -> str | None:
    if not MODEL:
        return None
    try:
        import boto3
        from botocore.config import Config
        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                              config=Config(connect_timeout=3, read_timeout=12, retries={"max_attempts": 1}))
        content = [{"image": {"format": "jpeg", "source": {"bytes": _jpeg(b)}}} for _, b in images]
        r = client.converse(modelId=MODEL, inferenceConfig={"maxTokens": 60, "temperature": 0},
                            messages=[{"role": "user", "content": content + [{"text": PROMPT}]}])
        text = "".join(c.get("text", "") for c in r["output"]["message"]["content"]).strip().strip('"')
    except Exception:
        return None
    text = re.sub(r"\s+", " ", text)
    if not text or text.upper().startswith("NONE") or len(text) > 60:
        return None
    return text


def start(images):
    """Begin reading the brand while the label text is read; .result() gives the brand or None."""
    return _pool.submit(read_brand, images)
