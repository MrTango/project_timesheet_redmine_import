# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.redmine_client import RedmineAPIError, RedmineClient
from ..services.utils import safe_message, validate_base_url

_logger = logging.getLogger(__name__)


class RedmineBackend(models.Model):
    _name = "redmine.backend"
    _description = "Redmine Backend"
    _order = "name"

    name = fields.Char(required=True)
    base_url = fields.Char(required=True)
    api_key = fields.Char(
        required=True,
        copy=False,
        groups="project.group_project_manager,base.group_system",
    )
    verify_ssl = fields.Boolean(default=True)
    active = fields.Boolean(default=True)
    import_start_date = fields.Date(required=True, default=fields.Date.context_today)
    last_synchronization = fields.Datetime(readonly=True, copy=False)
    synchronization_window = fields.Integer(required=True, default=60)
    default_employee_id = fields.Many2one(
        "hr.employee",
        ondelete="restrict",
        domain="[('company_id', '=', company_id)]",
    )
    enable_cron = fields.Boolean(default=False)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )

    project_ids = fields.One2many("project.project", "redmine_backend_id")

    @api.constrains("base_url")
    def _check_base_url(self):
        for backend in self:
            try:
                validate_base_url(backend.base_url)
            except ValueError as error:
                raise ValidationError(str(error))

    @api.constrains("synchronization_window")
    def _check_synchronization_window(self):
        if any(item.synchronization_window <= 0 for item in self):
            raise ValidationError(_("Synchronization Window must be greater than zero."))

    @api.constrains("default_employee_id", "company_id")
    def _check_backend_company(self):
        for backend in self:
            if (
                backend.default_employee_id
                and backend.default_employee_id.company_id != backend.company_id
            ):
                raise ValidationError(_("The default employee must belong to the backend company."))
            mismatched_projects = backend.sudo().project_ids.filtered(
                lambda project: project.company_id
                and project.company_id != backend.company_id
            )
            if mismatched_projects:
                raise ValidationError(
                    _("The backend company must match all linked Odoo projects.")
                )
            mismatched_mappings = self.env["redmine.employee.map"].sudo().search(
                [
                    ("backend_id", "=", backend.id),
                    ("employee_id", "!=", False),
                    ("employee_id.company_id", "!=", backend.company_id.id),
                ],
                limit=1,
            )
            if mismatched_mappings:
                raise ValidationError(
                    _("The backend company must match all mapped employees.")
                )

    def _check_manager(self):
        if not (
            self.env.user.has_group("project.group_project_manager")
            or self.env.user.has_group("base.group_system")
        ):
            raise UserError(_("Only Project Managers can manage Redmine imports."))

    def _client(self):
        self.ensure_one()
        return RedmineClient(
            self.base_url,
            self.api_key,
            verify_ssl=self.verify_ssl,
        )

    def _acquire_import_lock(self):
        """Serialize imports per backend until the current transaction ends."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)", (1380798030, self.id)
        )
        return bool(self.env.cr.fetchone()[0])

    def action_test_connection(self):
        self.ensure_one()
        self._check_manager()
        try:
            self._client().test_connection()
        except (RedmineAPIError, ValueError) as error:
            message = safe_message(error, self.api_key)
            _logger.warning("Redmine connection test failed for backend %s: %s", self.id, message)
            raise UserError(_("Connection failed: %s") % message)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Redmine Connection"),
                "message": _("Connection successful."),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model
    def _cron_import_time_entries(self):
        from ..services.import_service import RedmineImportService

        today = fields.Date.context_today(self)
        backends = self.search([("active", "=", True), ("enable_cron", "=", True)])
        for backend in backends:
            projects = backend.project_ids.filtered(
                lambda project: project.active and project.redmine_import_enabled
            )
            for project in projects:
                date_from = today - timedelta(days=backend.synchronization_window)
                date_from = max(date_from, backend.import_start_date)
                try:
                    with self.env.cr.savepoint():
                        RedmineImportService(
                            self.env,
                            backend,
                            project,
                            date_from,
                            today,
                            preview=False,
                            update_existing=True,
                        ).run()
                except Exception:
                    _logger.exception(
                        "Unexpected Redmine cron failure for backend %s, project %s",
                        backend.id,
                        project.id,
                    )
        return True
