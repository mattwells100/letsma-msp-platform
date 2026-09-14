import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.deps import require_manager_or_admin, require_admin_page
from app.routers.admin_technicians import _check_agent_key_or_admin


class AccessControlTests(unittest.TestCase):
    def _request(self, role=None):
        return SimpleNamespace(session={"user": {"role": role}} if role else {})

    def test_technician_cannot_use_financial_configuration(self):
        with self.assertRaisesRegex(HTTPException, "Manager or Admin"):
            require_manager_or_admin(self._request("Technician"))

    def test_manager_can_use_financial_configuration(self):
        user = require_manager_or_admin(self._request("Manager"))
        self.assertEqual(user["role"], "Manager")

    def test_admin_can_use_financial_configuration(self):
        user = require_manager_or_admin(self._request("Admin"))
        self.assertEqual(user["role"], "Admin")

    def test_manager_cannot_use_admin_page(self):
        with self.assertRaisesRegex(HTTPException, "Admin role"):
            require_admin_page(self._request("Manager"))

    def test_admin_session_can_manage_users_without_agent_key(self):
        user = _check_agent_key_or_admin(self._request("Admin"), None)
        self.assertEqual(user["role"], "Admin")

    def test_technician_session_cannot_manage_users(self):
        with self.assertRaisesRegex(HTTPException, "Invalid or missing"):
            _check_agent_key_or_admin(self._request("Technician"), None)


if __name__ == "__main__":
    unittest.main()
