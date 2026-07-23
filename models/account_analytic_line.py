# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, fields, models
from odoo.exceptions import AccessError


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    redmine_time_entry_id = fields.Integer(
        string="Redmine Time Entry ID",
        copy=False,
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_issue_id = fields.Integer(
        string="Redmine Issue ID",
        copy=False,
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_activity_id = fields.Integer(
        string="Redmine Activity ID",
        copy=False,
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_backend_id = fields.Many2one(
        "redmine.backend",
        string="Redmine Backend",
        copy=False,
        ondelete="restrict",
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_updated_on = fields.Datetime(
        string="Redmine Updated On",
        copy=False,
        groups="project.group_project_manager,base.group_system",
    )

    _sql_constraints = [
        (
            "redmine_time_entry_uniq",
            "unique(redmine_backend_id, redmine_time_entry_id)",
            "This Redmine time entry has already been imported.",
        )
    ]

    def _check_redmine_mutation_access(self):
        if self.filtered("redmine_backend_id") and not (
            self.env.user.has_group("project.group_project_manager")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Imported Redmine timesheets are read-only."))

    def write(self, vals):
        self._check_redmine_mutation_access()
        return super(AccountAnalyticLine, self).write(vals)

    def unlink(self):
        self._check_redmine_mutation_access()
        return super(AccountAnalyticLine, self).unlink()
