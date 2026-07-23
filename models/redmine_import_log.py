# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class RedmineImportLog(models.Model):
    _name = "redmine.import.log"
    _description = "Redmine Import Log"
    _order = "started_at desc, id desc"

    backend_id = fields.Many2one("redmine.backend", required=True, ondelete="restrict", index=True)
    project_id = fields.Many2one("project.project", required=True, ondelete="restrict", index=True)
    company_id = fields.Many2one(related="backend_id.company_id", store=True, index=True)
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    preview = fields.Boolean(readonly=True)
    update_existing = fields.Boolean(readonly=True)
    started_at = fields.Datetime(required=True, readonly=True)
    finished_at = fields.Datetime(readonly=True)
    duration = fields.Float(string="Duration (seconds)", readonly=True, digits=(16, 3))
    imported = fields.Integer(readonly=True)
    updated = fields.Integer(readonly=True)
    skipped = fields.Integer(readonly=True)
    errors = fields.Integer(readonly=True)
    state = fields.Selection(
        [
            ("running", "Running"),
            ("preview", "Preview"),
            ("done", "Done"),
            ("partial", "Done with Errors"),
            ("failed", "Failed"),
        ],
        required=True,
        default="running",
        readonly=True,
    )
    summary = fields.Text(readonly=True)
    line_ids = fields.One2many("redmine.import.log.line", "log_id", readonly=True)


class RedmineImportLogLine(models.Model):
    _name = "redmine.import.log.line"
    _description = "Redmine Import Log Detail"
    _order = "id"

    log_id = fields.Many2one("redmine.import.log", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="log_id.company_id", store=True, index=True)
    redmine_time_entry_id = fields.Integer(index=True)
    severity = fields.Selection(
        [("warning", "Warning"), ("error", "Error")], required=True, default="error"
    )
    message = fields.Text(required=True)
