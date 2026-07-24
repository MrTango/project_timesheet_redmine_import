# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProjectProject(models.Model):
    _inherit = "project.project"

    redmine_backend_id = fields.Many2one(
        "redmine.backend",
        string="Redmine Backend",
        ondelete="restrict",
        index=True,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_project_id = fields.Integer(
        string="Redmine Project ID",
        index=True,
        copy=False,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_project_identifier = fields.Char(
        string="Redmine Project Identifier",
        index=True,
        copy=False,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_import_enabled = fields.Boolean(
        string="Import Enabled",
        default=False,
        groups="project.group_project_manager,base.group_system",
    )
    last_redmine_sync = fields.Datetime(
        string="Last Redmine Synchronization",
        readonly=True,
        copy=False,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_create_tasks = fields.Boolean(
        string="Automatically Create Tasks from Redmine Issues",
        default=False,
        groups="project.group_project_manager,base.group_system",
    )
    redmine_task_update_policy = fields.Selection(
        [
            ("never", "Never Update Tasks"),
            ("title", "Update Title Only"),
            ("title_description", "Update Title and Description"),
        ],
        string="Task Update Policy",
        required=True,
        default="never",
        groups="project.group_project_manager,base.group_system",
    )

    _sql_constraints = [
        (
            "redmine_project_backend_uniq",
            "unique(redmine_backend_id, redmine_project_id)",
            "A Redmine project can only be mapped once per backend.",
        ),
        (
            "redmine_project_identifier_backend_uniq",
            "unique(redmine_backend_id, redmine_project_identifier)",
            "A Redmine project identifier can only be mapped once per backend.",
        ),
    ]

    @api.constrains(
        "redmine_backend_id",
        "redmine_project_id",
        "redmine_project_identifier",
        "redmine_import_enabled",
        "company_id",
    )
    def _check_redmine_configuration(self):
        for project in self:
            identifier = (project.redmine_project_identifier or "").strip()
            if project.redmine_import_enabled and (
                not project.redmine_backend_id
                or (project.redmine_project_id <= 0 and not identifier)
            ):
                raise ValidationError(
                    _(
                        "An enabled import requires a backend and a Redmine "
                        "Project Identifier."
                    )
                )
            if (
                project.redmine_backend_id
                and project.company_id
                and project.redmine_backend_id.company_id != project.company_id
            ):
                raise ValidationError(_("The project and Redmine backend companies must match."))

    def action_open_redmine_import_wizard(self):
        self.ensure_one()
        self.redmine_backend_id._check_manager()
        if not self.redmine_import_enabled:
            raise UserError(_("Enable the Redmine import on this project first."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Import Redmine Hours"),
            "res_model": "redmine.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_project_id": self.id},
        }
