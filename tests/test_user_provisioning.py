import unittest

from app.services.user_provisioning_service import build_plan, build_request


POLICY = {
    "tenant_id": "tenant-1",
    "group_ids": ["group-sales", "group-mfa"],
    "license_sku": "SPE_E3",
    "cloudblue_customer_id": "vuzion-customer-1",
}


class UserProvisioningTests(unittest.TestCase):
    def test_email_request_builds_ready_plan(self):
        request = build_request(
            channel="email",
            customer_id="customer-1",
            source_text=(
                "Please create a new user. Name: Jane Smith; "
                "UPN: jane.smith@example.com; Job title: Sales Executive; "
                "Department: Sales"
            ),
            sender="manager@example.com",
        )
        plan = build_plan(request, customer_policy=POLICY)

        self.assertTrue(request.is_new_user_request)
        self.assertTrue(plan.ready_for_execution)
        self.assertEqual(plan.request.upn, "jane.smith@example.com")
        self.assertEqual(plan.group_ids, ("group-sales", "group-mfa"))

    def test_whatsapp_request_uses_explicit_fields(self):
        request = build_request(
            channel="whatsapp",
            customer_id="customer-1",
            source_text="Please onboard our new starter",
            full_name="Alex Jones",
            upn="alex.jones@example.com",
            job_title="Technician",
            department="Operations",
        )
        plan = build_plan(request, customer_policy=POLICY)

        self.assertTrue(plan.ready_for_execution)
        self.assertEqual(plan.request.channel, "whatsapp")

    def test_teams_request_reports_missing_customer_policy(self):
        request = build_request(
            channel="teams",
            source_text=(
                "Create a user. Name: Pat Lee; UPN: pat.lee@example.com; "
                "Job title: Analyst; Department: Finance"
            ),
        )
        plan = build_plan(request, customer_policy={})

        self.assertFalse(plan.ready_for_execution)
        self.assertIn("customer_id", plan.missing_fields)
        self.assertIn("tenant_id", plan.missing_fields)
        self.assertIn("group_ids", plan.missing_fields)
        self.assertIn("license_sku", plan.missing_fields)

    def test_non_provisioning_ticket_is_not_ready(self):
        request = build_request(
            channel="email",
            customer_id="customer-1",
            source_text="The printer is not working.",
        )
        plan = build_plan(request, customer_policy=POLICY)

        self.assertFalse(plan.ready_for_execution)
        self.assertEqual(plan.missing_fields, ("new_user_request", "full_name", "upn", "job_title", "department"))


if __name__ == "__main__":
    unittest.main()
