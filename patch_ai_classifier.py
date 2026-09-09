from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/services/azure_openai_service.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

if "async def classify_ticket(" in txt:
    print("Already patched")
    raise SystemExit()

append_text = '''

# ---------------------------------------------------------------------------
# Ticket classification
# ---------------------------------------------------------------------------

async def classify_ticket(prompt: str) -> str:
    if (
        not settings.AZURE_OPENAI_ENDPOINT
        or not settings.AZURE_OPENAI_API_KEY
        or not settings.AZURE_OPENAI_DEPLOYMENT_NAME
    ):
        raise RuntimeError("Azure OpenAI is not configured")

    url = (
        f"{settings.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{settings.AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions"
        f"?api-version={AZURE_OPENAI_API_VERSION}"
    )

    payload = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an IT helpdesk ticket classifier. "
                    "Return ONLY a JSON object. "
                    "Do not ask questions. "
                    "Do not write prose. "
                    "Do not write markdown."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "max_completion_tokens": 1000,
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            url,
            headers={
                "api-key": settings.AZURE_OPENAI_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )

        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()

'''

txt += append_text

p.write_text(txt, encoding="utf-8")

print("[OK] classify_ticket added")
print("[OK] backup:", backup)