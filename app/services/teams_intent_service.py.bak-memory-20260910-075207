from enum import Enum
import re


class TeamsIntent(str, Enum):
    NEW_TICKET = "NEW_TICKET"
    SHOW_TICKETS = "SHOW_TICKETS"
    GET_STATUS = "GET_STATUS"
    HELP = "HELP"


_STATUS_PATTERNS = [
    r"status\s+(?:of\s+)?(?:ticket\s+)?#?(\d+)",
    r"ticket\s+#?(\d+)",
    r"what.?s\s+happening\s+with\s+(?:ticket\s+)?#?(\d+)",
]


_SHOW_TICKET_PHRASES = [
    "show my tickets",
    "my tickets",
    "open tickets",
    "show tickets",
    "list tickets",
]


_HELP_PHRASES = [
    "help",
    "what can you do",
    "commands",
]


def detect_intent(text: str):
    text_lower = text.lower().strip()

    for phrase in _SHOW_TICKET_PHRASES:
        if phrase in text_lower:
            return TeamsIntent.SHOW_TICKETS, {}

    for phrase in _HELP_PHRASES:
        if text_lower == phrase:
            return TeamsIntent.HELP, {}

    for pattern in _STATUS_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return (
                TeamsIntent.GET_STATUS,
                {"ticket_number": int(match.group(1))}
            )

    return TeamsIntent.NEW_TICKET, {}
