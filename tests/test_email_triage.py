import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.services.email_ingestion_service import classify_helpdesk_email


class EmailTriageTests(unittest.TestCase):
    def test_ai_non_helpdesk_classification_is_preserved(self):
        with patch(
            "app.services.email_ingestion_service.azure_openai_service.classify_helpdesk_email",
            new=AsyncMock(return_value={"classification": "MARKETING", "confidence": 0.99}),
        ):
            result = asyncio.run(classify_helpdesk_email("New brochure", "See our latest services."))

        self.assertEqual(result["classification"], "MARKETING")
        self.assertEqual(result["confidence"], 0.99)

    def test_ai_helpdesk_classification_is_preserved(self):
        with patch(
            "app.services.email_ingestion_service.azure_openai_service.classify_helpdesk_email",
            new=AsyncMock(return_value={"classification": "HELPDESK", "confidence": 0.94}),
        ):
            result = asyncio.run(classify_helpdesk_email("VPN unavailable", "I cannot connect to the office VPN."))

        self.assertEqual(result["classification"], "HELPDESK")

    def test_ai_failure_fails_closed(self):
        with patch(
            "app.services.email_ingestion_service.azure_openai_service.classify_helpdesk_email",
            new=AsyncMock(side_effect=RuntimeError("Azure unavailable")),
        ):
            result = asyncio.run(classify_helpdesk_email("Anything", "Anything"))

        self.assertEqual(result, {"classification": "OTHER", "confidence": 0.0})


if __name__ == "__main__":
    unittest.main()