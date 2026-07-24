# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import SavepointCase

from ..services.import_service import RedmineImportService


class FakeRedmineClient(object):
    def __init__(self, entries, users=None, issues=None, project_id=None):
        self.entries = entries
        self.users = users
        self.issues = issues
        self.project_id = project_id
        self.resolved_identifiers = []

    def resolve_project_id(self, identifier):
        self.resolved_identifiers.append(identifier)
        if self.project_id is None:
            raise AssertionError("A configured project ID should not be resolved again")
        return self.project_id

    def iter_time_entry_pages(self, project_id, date_from, date_to):
        yield self.entries

    def iter_user_pages(self):
        if self.users is None:
            raise AssertionError("Existing employee mapping should prevent user API calls")
        yield self.users

    def iter_issue_pages(self, project_id):
        if self.issues is None:
            raise AssertionError("Task synchronization is disabled")
        yield self.issues


class TestRedmineImportService(SavepointCase):
    @classmethod
    def setUpClass(cls):
        super(TestRedmineImportService, cls).setUpClass()
        cls.employee = cls.env["hr.employee"].create(
            {"name": "Redmine Worker", "company_id": cls.env.company.id}
        )
        cls.backend = cls.env["redmine.backend"].create(
            {
                "name": "Test Redmine",
                "base_url": "https://redmine.example.com",
                "api_key": "secret",
                "import_start_date": date(2024, 1, 1),
                "company_id": cls.env.company.id,
            }
        )
        cls.project = cls.env["project.project"].create(
            {
                "name": "Imported Project",
                "allow_timesheets": True,
                "company_id": cls.env.company.id,
                "redmine_backend_id": cls.backend.id,
                "redmine_project_id": 42,
                "redmine_import_enabled": True,
            }
        )
        cls.env["redmine.employee.map"].create(
            {
                "backend_id": cls.backend.id,
                "redmine_user_id": 7,
                "redmine_name": "Remote Worker",
                "employee_id": cls.employee.id,
            }
        )

    def _entry(self, hours=2.5, updated_on="2025-01-02T10:00:00Z"):
        return {
            "id": 1001,
            "project": {"id": 42, "name": "Remote Project"},
            "user": {"id": 7, "name": "Remote Worker"},
            "activity": {"id": 9, "name": "Development"},
            "hours": hours,
            "comments": "Implemented feature",
            "spent_on": "2025-01-02",
            "created_on": "2025-01-02T09:00:00Z",
            "updated_on": updated_on,
        }

    def _run(self, entry, preview=False, client=None):
        return RedmineImportService(
            self.env,
            self.backend,
            self.project,
            date(2025, 1, 1),
            date(2025, 1, 31),
            preview=preview,
            update_existing=True,
            client=client or FakeRedmineClient([entry]),
        ).run()

    def test_import_enabled_rejects_blank_identifier_without_project_id(self):
        with self.assertRaises(ValidationError):
            self.env["project.project"].create(
                {
                    "name": "Invalid Redmine Project",
                    "company_id": self.env.company.id,
                    "redmine_backend_id": self.backend.id,
                    "redmine_project_identifier": "   ",
                    "redmine_import_enabled": True,
                }
            )

    def test_import_resolves_and_stores_project_id_from_identifier(self):
        project = self.env["project.project"].create(
            {
                "name": "Automatically Resolved Project",
                "allow_timesheets": True,
                "company_id": self.env.company.id,
                "redmine_backend_id": self.backend.id,
                "redmine_project_identifier": "customer-portal",
                "redmine_import_enabled": True,
            }
        )
        entry = self._entry()
        entry["id"] = 5005
        entry["project"] = {"id": 84, "name": "Customer Portal"}
        client = FakeRedmineClient([entry], project_id=84)

        log = RedmineImportService(
            self.env,
            self.backend,
            project,
            date(2025, 1, 1),
            date(2025, 1, 31),
            preview=True,
            client=client,
        ).run()

        self.assertEqual("preview", log.state)
        self.assertEqual(84, project.redmine_project_id)
        self.assertEqual(["customer-portal"], client.resolved_identifiers)
        self.assertFalse(
            self.env["account.analytic.line"].search(
                [
                    ("redmine_backend_id", "=", self.backend.id),
                    ("redmine_time_entry_id", "=", 5005),
                ]
            )
        )

    def test_import_refreshes_project_id_when_identifier_is_authoritative(self):
        project = self.env["project.project"].create(
            {
                "name": "Renamed Redmine Project",
                "allow_timesheets": True,
                "company_id": self.env.company.id,
                "redmine_backend_id": self.backend.id,
                "redmine_project_id": 84,
                "redmine_project_identifier": "renamed-project",
                "redmine_import_enabled": True,
            }
        )
        entry = self._entry()
        entry["id"] = 6006
        entry["project"] = {"id": 85, "name": "Renamed Project"}
        client = FakeRedmineClient([entry], project_id=85)

        log = RedmineImportService(
            self.env,
            self.backend,
            project,
            date(2025, 1, 1),
            date(2025, 1, 31),
            client=client,
        ).run()

        self.assertEqual("done", log.state)
        self.assertEqual(85, project.redmine_project_id)
        self.assertEqual(["renamed-project"], client.resolved_identifiers)

    def test_project_id_mapping_conflict_returns_failed_import_log(self):
        self.env["project.project"].create(
            {
                "name": "Existing Redmine Mapping",
                "company_id": self.env.company.id,
                "redmine_backend_id": self.backend.id,
                "redmine_project_id": 4242,
            }
        )
        project = self.env["project.project"].create(
            {
                "name": "Conflicting Redmine Project",
                "allow_timesheets": True,
                "company_id": self.env.company.id,
                "redmine_backend_id": self.backend.id,
                "redmine_project_identifier": "duplicate-project",
                "redmine_import_enabled": True,
            }
        )
        client = FakeRedmineClient([], project_id=4242)

        log = RedmineImportService(
            self.env,
            self.backend,
            project,
            date(2025, 1, 1),
            date(2025, 1, 31),
            client=client,
        ).run()

        self.assertEqual("failed", log.state)
        self.assertEqual(1, log.errors)
        self.assertEqual(0, project.redmine_project_id)

    def test_import_is_idempotent_and_updates_only_newer(self):
        log = self._run(self._entry())
        self.assertEqual("done", log.state)
        self.assertEqual(1, log.imported)
        line = self.env["account.analytic.line"].search(
            [
                ("redmine_backend_id", "=", self.backend.id),
                ("redmine_time_entry_id", "=", 1001),
            ]
        )
        self.assertEqual(1, len(line))
        self.assertEqual(2.5, line.unit_amount)

        log = self._run(self._entry(hours=9.0))
        self.assertEqual(1, log.skipped)
        self.assertEqual(2.5, line.unit_amount)

        log = self._run(self._entry(hours=3.0, updated_on="2025-01-03T10:00:00Z"))
        self.assertEqual(1, log.updated)
        self.assertEqual(3.0, line.unit_amount)
        self.assertEqual(1, len(line))

    def test_preview_does_not_create_timesheet(self):
        entry = self._entry()
        entry["id"] = 2002
        before = self.env["account.analytic.line"].search_count(
            [("redmine_backend_id", "=", self.backend.id)]
        )
        log = self._run(entry, preview=True)
        after = self.env["account.analytic.line"].search_count(
            [("redmine_backend_id", "=", self.backend.id)]
        )
        self.assertEqual("preview", log.state)
        self.assertEqual(1, log.imported)
        self.assertEqual(before, after)

    def test_issue_creates_task_and_reuses_it(self):
        self.project.write(
            {
                "redmine_create_tasks": True,
                "redmine_task_update_policy": "title_description",
            }
        )
        entry = self._entry()
        entry["id"] = 3003
        entry["issue"] = {"id": 81}
        issue = {
            "id": 81,
            "project": {"id": 42},
            "subject": "Fix login",
            "description": "Do not trust <script>alert(1)</script>",
            "updated_on": "2025-01-02T11:00:00Z",
        }
        client = FakeRedmineClient([entry], issues=[issue])
        log = self._run(entry, client=client)
        self.assertEqual(1, log.imported)
        task = self.env["project.task"].search(
            [("redmine_backend_id", "=", self.backend.id), ("redmine_issue_id", "=", 81)]
        )
        self.assertEqual("RM-81 Fix login", task.name)
        self.assertNotIn("<script>", task.description)
        line = self.env["account.analytic.line"].search(
            [("redmine_backend_id", "=", self.backend.id), ("redmine_time_entry_id", "=", 3003)]
        )
        self.assertEqual(task, line.task_id)

    def test_import_uses_project_company(self):
        company = self.env["res.company"].create({"name": "Second Company"})
        employee = self.env["hr.employee"].create(
            {"name": "Second Worker", "company_id": company.id}
        )
        backend = self.env["redmine.backend"].create(
            {
                "name": "Second Redmine",
                "base_url": "https://second.example.com",
                "api_key": "secret",
                "import_start_date": date(2024, 1, 1),
                "company_id": company.id,
            }
        )
        project = self.env["project.project"].sudo().with_context(
            allowed_company_ids=[company.id]
        ).create(
            {
                "name": "Second Project",
                "allow_timesheets": True,
                "company_id": company.id,
                "redmine_backend_id": backend.id,
                "redmine_project_id": 84,
                "redmine_import_enabled": True,
            }
        )
        self.env["redmine.employee.map"].create(
            {
                "backend_id": backend.id,
                "redmine_user_id": 7,
                "redmine_name": "Second Worker",
                "employee_id": employee.id,
            }
        )
        entry = self._entry()
        entry["id"] = 4004
        entry["project"] = {"id": 84}
        log = RedmineImportService(
            self.env,
            backend,
            project,
            date(2025, 1, 1),
            date(2025, 1, 31),
            client=FakeRedmineClient([entry]),
        ).run()
        self.assertEqual("done", log.state)
        line = self.env["account.analytic.line"].sudo().search(
            [("redmine_backend_id", "=", backend.id), ("redmine_time_entry_id", "=", 4004)]
        )
        self.assertEqual(company, line.company_id)
