from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import sys

SERVICE = Path("app/services/azure_openai_service.py")
ROUTER = Path("app/routers/teams_bot.py")

for path in (SERVICE, ROUTER):
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

service_backup = Path(
    f"{SERVICE}.bak-{datetime.now():%Y%m%d-%H%M%S}"
)
router_backup = Path(
    f"{ROUTER}.bak-{datetime.now():%Y%m%d-%H%M%S}"
)

shutil.copy2(SERVICE, service_backup)
shutil.copy2(ROUTER, router_backup)

service_text = SERVICE.read_text(encoding="utf-8")
router_text = ROUTER.read_text(encoding="utf-8")

old_signature = "async def classify_ticket(prompt: str) -> str:"

new_signature = (
    "async def classify_ticket("
    "prompt: str, allowed_categories: dict | None = None"
    ") -> str:"
)

if old_signature in service_text:
    service_text = service_text.replace(
        old_signature,
        new_signature,
        1,
    )
elif new_signature not in service_text:
    raise SystemExit(
        "Could not find the classify_ticket function signature. "
        "No files were changed."
    )

old_system_prompt = '''                "content": (
                    "You are an IT helpdesk ticket classifier. "
                    "Return ONLY a JSON object. "
                    "Do not ask questions. "
                    "Do not write prose. "
                    "Do not write markdown."
                ),'''

new_system_prompt = '''                "content": (
                    "You are a strict IT helpdesk ticket classifier. "
                    "Return ONLY one JSON object with exactly these keys: "
                    "category, subcategory, priority, estimated_minutes, "
                    "confidence, reason. "
                    "Select category and subcategory only from the allowed "
                    "taxonomy contained in the user message. "
                    "Do not create alternative category names. "
                    "Priority must be exactly Low, Normal, High, or Critical. "
                    "Confidence must be exactly Low, Medium, or High. "
                    "estimated_minutes must be an integer from 5 to 480. "
                    "Do not include issue_summary, probable_causes, "
                    "recommended_actions, required_information_for_resolution, "
                    "tags, prose, greetings, explanations, or Markdown."
                ),'''

if old_system_prompt in service_text:
    service_text = service_text.replace(
        old_system_prompt,
        new_system_prompt,
        1,
    )
elif new_system_prompt not in service_text:
    raise SystemExit(
        "Could not find the classifier system prompt. "
        "No files were changed."
    )

old_user_content = '''                "role": "user",
                "content": prompt,
'''

new_user_content = '''                "role": "user",
                "content": (
                    "ALLOWED TAXONOMY:\\n"
                    + json.dumps(allowed_categories or {})
                    + "\\n\\nCLASSIFICATION REQUEST:\\n"
                    + prompt
                ),
'''

if old_user_content in service_text:
    service_text = service_text.replace(
        old_user_content,
        new_user_content,
        1,
    )
elif new_user_content not in service_text:
    raise SystemExit(
        "Could not find the classifier user message. "
        "No files were changed."
    )

old_teams_call = '''raw_result = await azure_openai_service.classify_ticket(
            text
        )'''

new_teams_call = '''raw_result = await azure_openai_service.classify_ticket(
            prompt,
            allowed_categories=AI_TICKET_CATEGORIES,
        )'''

if old_teams_call in router_text:
    router_text = router_text.replace(
        old_teams_call,
        new_teams_call,
        1,
    )
elif new_teams_call not in router_text:
    raise SystemExit(
        "Could not find the Teams classify_ticket call. "
        "No files were changed."
    )

SERVICE.write_text(service_text, encoding="utf-8")
ROUTER.write_text(router_text, encoding="utf-8")

errors = []

if new_signature not in SERVICE.read_text(encoding="utf-8"):
    errors.append("Updated classifier signature is missing")

if "ALLOWED TAXONOMY" not in SERVICE.read_text(encoding="utf-8"):
    errors.append("Allowed taxonomy injection is missing")

if (
    "allowed_categories=AI_TICKET_CATEGORIES"
    not in ROUTER.read_text(encoding="utf-8")
):
    errors.append("Teams taxonomy argument is missing")

if "classify_ticket(\n            text\n" in ROUTER.read_text(
    encoding="utf-8"
):
    errors.append("Old Teams classifier call still exists")

for path in (SERVICE, ROUTER):
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append(
            f"{path} failed compilation:\n"
            f"{result.stdout}{result.stderr}"
        )

if errors:
    shutil.copy2(service_backup, SERVICE)
    shutil.copy2(router_backup, ROUTER)

    print("[FAILED] Patch rolled back automatically.")
    for error in errors:
        print(error)

    raise SystemExit(1)

print("[OK] Classifier schema strengthened")
print("[OK] Allowed taxonomy passed to Azure OpenAI")
print("[OK] Teams now sends the complete classification prompt")
print("[OK] Both files compile successfully")
print(f"[OK] Service backup: {service_backup}")
print(f"[OK] Router backup: {router_backup}")
