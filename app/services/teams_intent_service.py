from enum import Enum
import re


class TeamsIntent(str, Enum):
    NEW_TICKET = "NEW_TICKET"
    SHOW_TICKETS = "SHOW_TICKETS"
    GET_STATUS = "GET_STATUS"
    HELP = "HELP"
    WHEN_CLOSED = "WHEN_CLOSED"
    WHO_ASSIGNED = "WHO_ASSIGNED"
    LATEST_UPDATE = "LATEST_UPDATE"


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

    when_closed_phrases = (
        "when was it closed",
        "when did it close",
        "when was the ticket closed",
        "when was this closed",
        "what date was it closed",
    )

    if any(
        phrase in text_lower
        for phrase in when_closed_phrases
    ):
        return TeamsIntent.WHEN_CLOSED, {}

    assigned_phrases = (
        "who is working on it",
        "who's working on it",
        "who is assigned",
        "who is assigned to it",
        "who worked on it",
        "who owns it",
    )

    if any(
        phrase in text_lower
        for phrase in assigned_phrases
    ):
        return TeamsIntent.WHO_ASSIGNED, {}

    latest_update_phrases = (
        "latest update",
        "what is the latest update",
        "what's the latest update",
        "any update",
        "any updates",
        "what happened last",
    )

    if any(
        phrase in text_lower
        for phrase in latest_update_phrases
    ):
        return TeamsIntent.LATEST_UPDATE, {}

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
