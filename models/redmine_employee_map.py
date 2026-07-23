# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RedmineEmployeeMap(models.Model):
    _name = "redmine.employee.map"
    _description = "Redmine Employee Mapping"
    _order = "redmine_name, redmine_login"

    backend_id = fields.Many2one(
        "redmine.backend", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one(related="backend_id.company_id", store=True, index=True)
    redmine_user_id = fields.Integer(required=True, index=True)
    redmine_login = fields.Char()
    redmine_name = fields.Char(required=True)
    redmine_email = fields.Char()
    employee_id = fields.Many2one(
        "hr.employee",
        ondelete="restrict",
        domain="[('company_id', '=', company_id)]",
    )
    warning = fields.Text(readonly=True)

    @api.constrains("backend_id", "employee_id")
    def _check_employee_company(self):
        for mapping in self:
            if (
                mapping.employee_id
                and mapping.employee_id.company_id != mapping.backend_id.company_id
            ):
                raise ValidationError(
                    _("The mapped employee must belong to the backend company.")
                )

    _sql_constraints = [
        (
            "redmine_employee_user_uniq",
            "unique(backend_id, redmine_user_id)",
            "A Redmine user can only be mapped once per backend.",
        )
    ]
