# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    redmine_issue_id = fields.Integer(
        string="Redmine Issue ID",
        copy=False,
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_project_id = fields.Integer(
        string="Redmine Project ID",
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
            "redmine_task_issue_uniq",
            "unique(redmine_backend_id, redmine_issue_id)",
            "A Redmine issue can only be linked to one task per backend.",
        )
    ]
