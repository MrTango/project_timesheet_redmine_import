# Copyright 2025
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Project Timesheet Redmine Import",
    "summary": "Import Redmine time entries into Odoo timesheets",
    "version": "13.0.1.0.0",
    "category": "Services/Project",
    "website": "https://github.com/OCA/project",
    "author": "Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "depends": [
        "project",
        "sale",
        "hr",
        "hr_timesheet",
        "sale_timesheet",
    ],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/redmine_security.xml",
        "security/ir.model.access.csv",
        "views/redmine_backend_views.xml",
        "views/redmine_employee_map_views.xml",
        "views/redmine_import_log_views.xml",
        "views/project_project_views.xml",
        "views/project_task_views.xml",
        "wizard/redmine_import_wizard_views.xml",
        "data/ir_cron.xml",
    ],
    "demo": ["demo/redmine_demo.xml"],
    "installable": True,
    "application": False,
}
