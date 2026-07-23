# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from ..services.import_service import RedmineImportService


class RedmineImportWizard(models.TransientModel):
    _name = "redmine.import.wizard"
    _description = "Import Redmine Hours"

    project_id = fields.Many2one("project.project", required=True, readonly=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    preview_only = fields.Boolean(default=True)
    update_existing = fields.Boolean(default=True)

    @api.model
    def default_get(self, field_list):
        values = super(RedmineImportWizard, self).default_get(field_list)
        project = self.env["project.project"].browse(values.get("project_id"))
        if project and project.redmine_backend_id:
            backend = project.redmine_backend_id
            today = fields.Date.context_today(self)
            values.setdefault("date_to", today)
            values.setdefault(
                "date_from",
                max(
                    today - timedelta(days=backend.synchronization_window),
                    backend.import_start_date,
                ),
            )
        return values

    @api.constrains("date_from", "date_to", "project_id")
    def _check_dates(self):
        for wizard in self:
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("From Date must not be later than To Date."))
            backend = wizard.project_id.redmine_backend_id
            if backend and wizard.date_from and wizard.date_from < backend.import_start_date:
                raise ValidationError(
                    _("From Date cannot be earlier than the backend Import Start Date.")
                )

    def action_import(self):
        self.ensure_one()
        backend = self.project_id.redmine_backend_id
        if not backend:
            raise UserError(_("The project has no Redmine backend."))
        backend._check_manager()
        log = RedmineImportService(
            self.env,
            backend,
            self.project_id,
            self.date_from,
            self.date_to,
            preview=self.preview_only,
            update_existing=self.update_existing,
        ).run()
        return {
            "type": "ir.actions.act_window",
            "name": _("Redmine Import Result"),
            "res_model": "redmine.import.log",
            "res_id": log.id,
            "view_mode": "form",
            "target": "current",
        }
