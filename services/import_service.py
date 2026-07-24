# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from collections import defaultdict
from datetime import datetime

from odoo import _, fields

from .redmine_client import RedmineAPIError
from .utils import (
    integer_id,
    normalize_email,
    parse_date,
    parse_datetime,
    parse_hours,
    safe_message,
    text_to_html,
)

_logger = logging.getLogger(__name__)


class RedmineImportService(object):
    """Coordinate one project/date-range import.

    API access, mapping resolution and Odoo persistence are deliberately kept
    here rather than in button methods. The client can be injected in tests or
    replaced by a companion addon.
    """

    MAX_LOG_DETAILS = 1000

    def __init__(
        self,
        env,
        backend,
        project,
        date_from,
        date_to,
        preview=False,
        update_existing=True,
        client=None,
    ):
        self.env = env
        self.backend = backend
        self.project = project
        self.date_from = fields.Date.to_date(date_from)
        self.date_to = fields.Date.to_date(date_to)
        self.preview = bool(preview)
        self.update_existing = bool(update_existing)
        self.client = client or backend._client()
        self.company = project.company_id or backend.company_id
        self.company_context = {
            "allowed_company_ids": [self.company.id],
            "force_company": self.company.id,
        }
        self.log = None
        self.counts = {"imported": 0, "updated": 0, "skipped": 0, "errors": 0}
        self._detail_count = 0
        self._employee_maps = {}
        self._employee_by_email = None
        self._redmine_users = None
        self._task_cache = None
        self._issues = None
        self._issue_error = None

    def _sudo_model(self, model_name):
        return self.env[model_name].sudo().with_context(**self.company_context)

    def run(self):
        self.backend._check_manager()
        started = datetime.utcnow()
        self.log = self._sudo_model("redmine.import.log").create(
            {
                "backend_id": self.backend.id,
                "project_id": self.project.id,
                "date_from": self.date_from,
                "date_to": self.date_to,
                "preview": self.preview,
                "update_existing": self.update_existing,
                "started_at": fields.Datetime.now(),
                "state": "running",
            }
        )
        try:
            self._validate()
            if not self.backend._acquire_import_lock():
                self._error(False, _("Another import is already running for this backend."))
                return self._finish(started, failed=True)
            self._load_mapping_caches()
            for page in self.client.iter_time_entry_pages(
                self.project.redmine_project_id, self.date_from, self.date_to
            ):
                self._process_page(page)
        except (RedmineAPIError, ValueError) as error:
            self._error(False, safe_message(error, self.backend.api_key))
            _logger.warning(
                "Redmine import failed for backend %s/project %s: %s",
                self.backend.id,
                self.project.id,
                safe_message(error, self.backend.api_key),
            )
            return self._finish(started, failed=True)
        except Exception as error:
            self._error(False, safe_message(error, self.backend.api_key))
            _logger.exception(
                "Unexpected Redmine import failure for backend %s/project %s",
                self.backend.id,
                self.project.id,
            )
            return self._finish(started, failed=True)
        return self._finish(started)

    def _validate(self):
        if not self.project.redmine_import_enabled:
            raise ValueError("Redmine import is not enabled for this project.")
        if self.project.redmine_backend_id != self.backend:
            raise ValueError("The project is linked to a different Redmine backend.")
        identifier = (self.project.redmine_project_identifier or "").strip()
        if identifier:
            project_id = self.client.resolve_project_id(identifier)
            if self.project.redmine_project_id != project_id:
                conflict = self._sudo_model("project.project").search(
                    [
                        ("id", "!=", self.project.id),
                        ("redmine_backend_id", "=", self.backend.id),
                        ("redmine_project_id", "=", project_id),
                    ],
                    limit=1,
                )
                if conflict:
                    raise ValueError(
                        "The resolved Redmine project is already mapped to another "
                        "Odoo project."
                    )
                try:
                    with self.env.cr.savepoint():
                        self.project.sudo().write({"redmine_project_id": project_id})
                except Exception:
                    raise ValueError("The resolved Redmine project ID could not be stored.")
        elif self.project.redmine_project_id <= 0:
            raise ValueError("The project has no Redmine project identifier.")
        if self.project.company_id and self.project.company_id != self.backend.company_id:
            raise ValueError("The project and Redmine backend companies do not match.")
        if not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise ValueError("The import date range is invalid.")
        if self.date_from < self.backend.import_start_date:
            raise ValueError("The import range starts before the backend Import Start Date.")
        if not self.project.analytic_account_id:
            raise ValueError("The Odoo project has no analytic account.")
        if not self.project.allow_timesheets:
            raise ValueError("Timesheets are not enabled on the Odoo project.")

    def _load_mapping_caches(self):
        mappings = self._sudo_model("redmine.employee.map").search(
            [("backend_id", "=", self.backend.id)]
        )
        self._employee_maps = {mapping.redmine_user_id: mapping for mapping in mappings}
        tasks = self._sudo_model("project.task").search(
            [
                ("redmine_backend_id", "=", self.backend.id),
                ("redmine_issue_id", ">", 0),
            ]
        )
        self._task_cache = {task.redmine_issue_id: task for task in tasks}

    def _process_page(self, entries):
        if not isinstance(entries, list):
            raise RedmineAPIError("Redmine returned an invalid time-entry page.")
        valid_entries = []
        for entry in entries:
            try:
                entry_id = integer_id(entry, "id", required=True)
                valid_entries.append((entry_id, entry))
            except ValueError as error:
                self._error(False, str(error))
                self.counts["skipped"] += 1
        existing_lines = self._sudo_model("account.analytic.line").search(
            [
                ("redmine_backend_id", "=", self.backend.id),
                ("redmine_time_entry_id", "in", [item[0] for item in valid_entries]),
            ]
        )
        existing_by_id = {
            line.redmine_time_entry_id: line for line in existing_lines
        }
        for entry_id, entry in valid_entries:
            try:
                with self.env.cr.savepoint():
                    values = self._prepare_values(entry)
                    existing = existing_by_id.get(entry_id)
                    if existing:
                        self._update_existing(existing, values)
                    else:
                        self._create_entry(values)
            except Exception as error:
                self.env.cache.invalidate()
                self._load_mapping_caches()
                self.counts["skipped"] += 1
                self._error(entry_id, safe_message(error, self.backend.api_key))

    def _prepare_values(self, entry):
        entry_id = integer_id(entry, "id", required=True)
        remote_project_id = integer_id(entry.get("project"), "id", required=True)
        if remote_project_id != self.project.redmine_project_id:
            raise ValueError(
                "Time entry %s belongs to unexpected Redmine project %s."
                % (entry_id, remote_project_id)
            )
        spent_on = parse_date(entry.get("spent_on"), "spent_on")
        if spent_on < self.date_from or spent_on > self.date_to:
            raise ValueError(
                "Time entry %s has spent_on outside the requested range." % entry_id
            )
        user = entry.get("user") or {}
        user_id = integer_id(user, "id", required=True)
        employee = self._resolve_employee(user_id, user)
        if not employee:
            raise ValueError(
                "No Odoo employee is mapped to Redmine user %s (%s)."
                % (user_id, user.get("name") or "unknown")
            )
        issue_id = integer_id(entry.get("issue"), "id")
        task = self._resolve_task(issue_id) if issue_id else False
        activity = entry.get("activity") or {}
        activity_id = integer_id(activity, "id")
        description = (entry.get("comments") or "").strip()
        if not description:
            description = activity.get("name") or "Redmine time entry %s" % entry_id
        return {
            "name": description,
            "date": spent_on,
            "unit_amount": parse_hours(entry.get("hours")),
            "employee_id": employee.id,
            "project_id": self.project.id,
            "task_id": task.id if task else False,
            "account_id": self.project.analytic_account_id.id,
            "company_id": self.company.id,
            "redmine_time_entry_id": entry_id,
            "redmine_issue_id": issue_id,
            "redmine_activity_id": activity_id,
            "redmine_backend_id": self.backend.id,
            "redmine_updated_on": parse_datetime(entry.get("updated_on"), "updated_on"),
        }

    def _resolve_employee(self, user_id, entry_user):
        mapping = self._employee_maps.get(user_id)
        if mapping:
            employee = mapping.employee_id
            if employee and (
                not employee.active or employee.company_id != self.backend.company_id
            ):
                self._warning(
                    False,
                    "Redmine user %s has an inactive or cross-company employee mapping."
                    % user_id,
                )
                employee = self.env["hr.employee"]
            return employee or self.backend.default_employee_id

        user_data = self._get_redmine_users().get(user_id, {})
        email = user_data.get("mail") or user_data.get("email")
        employee = self._match_employee(email)
        name = (
            user_data.get("firstname", "") + " " + user_data.get("lastname", "")
        ).strip() or entry_user.get("name") or "Redmine user %s" % user_id
        warning = False
        if not employee:
            warning = "No unique employee email match was found."
        mapping_values = {
            "backend_id": self.backend.id,
            "redmine_user_id": user_id,
            "redmine_login": user_data.get("login"),
            "redmine_name": name,
            "redmine_email": email,
            "employee_id": employee.id if employee else False,
            "warning": warning,
        }
        if not self.preview:
            mapping = self._sudo_model("redmine.employee.map").create(mapping_values)
            self._employee_maps[user_id] = mapping
        if warning:
            self._warning(False, "Redmine user %s: %s" % (user_id, warning))
        return employee or self.backend.default_employee_id

    def _get_redmine_users(self):
        if self._redmine_users is not None:
            return self._redmine_users
        self._redmine_users = {}
        try:
            for page in self.client.iter_user_pages():
                for user in page:
                    user_id = integer_id(user, "id")
                    if user_id:
                        self._redmine_users[user_id] = user
        except (RedmineAPIError, ValueError) as error:
            self._warning(
                False,
                "Redmine users could not be loaded for automatic email matching: %s"
                % safe_message(error, self.backend.api_key),
            )
        return self._redmine_users

    def _match_employee(self, email):
        normalized = normalize_email(email)
        if not normalized:
            return self.env["hr.employee"]
        if self._employee_by_email is None:
            by_email = defaultdict(list)
            employees = self._sudo_model("hr.employee").search(
                [
                    ("active", "=", True),
                    ("company_id", "=", self.backend.company_id.id),
                    ("work_email", "!=", False),
                ]
            )
            for employee in employees:
                by_email[normalize_email(employee.work_email)].append(employee)
            self._employee_by_email = by_email
        matches = self._employee_by_email.get(normalized, [])
        return matches[0] if len(matches) == 1 else self.env["hr.employee"]

    def _resolve_task(self, issue_id):
        task = self._task_cache.get(issue_id)
        if task and task.project_id != self.project:
            self._warning(
                issue_id,
                "Redmine issue %s is linked to a task in another Odoo project."
                % issue_id,
            )
            return False
        if not self.project.redmine_create_tasks:
            return task
        issue = self._get_issues().get(issue_id)
        if not issue:
            self._warning(issue_id, "Redmine issue %s was not returned by the API." % issue_id)
            return task
        issue_project_id = integer_id(issue.get("project"), "id", required=True)
        if issue_project_id != self.project.redmine_project_id:
            raise ValueError("Redmine issue %s belongs to another project." % issue_id)
        issue_updated = parse_datetime(issue.get("updated_on"), "issue updated_on")
        title = "RM-%s %s" % (issue_id, issue.get("subject") or "Untitled issue")
        if not task:
            if self.preview:
                return False
            values = {
                "name": title,
                "description": text_to_html(issue.get("description")),
                "project_id": self.project.id,
                "partner_id": self.project.partner_id.id,
                "redmine_issue_id": issue_id,
                "redmine_project_id": issue_project_id,
                "redmine_backend_id": self.backend.id,
                "redmine_updated_on": issue_updated,
            }
            task = self._sudo_model("project.task").with_context(
                default_project_id=self.project.id
            ).create(values)
            self._task_cache[issue_id] = task
            return task
        values = {}
        if issue_updated and (
            not task.redmine_updated_on or issue_updated > task.redmine_updated_on
        ):
            values["redmine_updated_on"] = issue_updated
        policy = self.project.redmine_task_update_policy
        if policy in ("title", "title_description") and task.name != title:
            values["name"] = title
        description = text_to_html(issue.get("description"))
        if policy == "title_description" and task.description != description:
            values["description"] = description
        if values and not self.preview:
            task.sudo().with_context(**self.company_context).write(values)
        return task

    def _get_issues(self):
        if self._issues is not None:
            return self._issues
        if self._issue_error:
            raise RedmineAPIError(self._issue_error)
        issues = {}
        try:
            for page in self.client.iter_issue_pages(self.project.redmine_project_id):
                for issue in page:
                    issue_id = integer_id(issue, "id")
                    if issue_id:
                        issues[issue_id] = issue
        except (RedmineAPIError, ValueError) as error:
            self._issue_error = safe_message(error, self.backend.api_key)
            raise
        self._issues = issues
        return self._issues

    def _create_entry(self, values):
        if self.preview:
            self.counts["imported"] += 1
            return
        self._sudo_model("account.analytic.line").create(values)
        self.counts["imported"] += 1

    def _update_existing(self, line, values):
        incoming_updated = values.get("redmine_updated_on")
        if not self.update_existing:
            self.counts["skipped"] += 1
            return
        if not incoming_updated or (
            line.redmine_updated_on and incoming_updated <= line.redmine_updated_on
        ):
            self.counts["skipped"] += 1
            return
        if not self.preview:
            line.sudo().with_context(**self.company_context).write(values)
        self.counts["updated"] += 1

    def _warning(self, entry_id, message):
        self._detail(entry_id, "warning", message)

    def _error(self, entry_id, message):
        self.counts["errors"] += 1
        self._detail(entry_id, "error", message)

    def _detail(self, entry_id, severity, message):
        if not self.log or self._detail_count >= self.MAX_LOG_DETAILS:
            return
        self._sudo_model("redmine.import.log.line").create(
            {
                "log_id": self.log.id,
                "redmine_time_entry_id": entry_id if isinstance(entry_id, int) else False,
                "severity": severity,
                "message": safe_message(message, self.backend.api_key),
            }
        )
        self._detail_count += 1

    def _finish(self, started, failed=False):
        duration = (datetime.utcnow() - started).total_seconds()
        if failed:
            state = "failed"
        elif self.preview:
            state = "preview"
        elif self.counts["errors"]:
            state = "partial"
        else:
            state = "done"
        summary = _(
            "Imported: %(imported)s, updated: %(updated)s, skipped: %(skipped)s, errors: %(errors)s"
        ) % self.counts
        if self._detail_count >= self.MAX_LOG_DETAILS:
            summary += _(". Additional error details were omitted.")
        values = dict(self.counts)
        values.update(
            {
                "finished_at": fields.Datetime.now(),
                "duration": duration,
                "state": state,
                "summary": summary,
            }
        )
        self.log.sudo().with_context(**self.company_context).write(values)
        if not self.preview and not failed:
            now = fields.Datetime.now()
            self.project.sudo().with_context(**self.company_context).write(
                {"last_redmine_sync": now}
            )
            self.backend.sudo().with_context(**self.company_context).write(
                {"last_synchronization": now}
            )
        return self.log
