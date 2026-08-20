Use **Import Redmine Hours** on a mapped project for preview or import. Enable both the backend cron and project import switches for daily rolling synchronization. Review all results under Redmine Import Logs.

A **Default Task for Imported Time** can be set on the project's Redmine tab. Imported time entries that are not linked to a synchronized task are assigned to it; with task creation disabled, all imported time entries land on this task.

Imported timesheet descriptions are prefixed with the Redmine issue number (``#123:``); when the Redmine entry has no comment, the issue title is used instead. If the timesheet lines provide start/end datetimes (for example via ``project_timesheet_time_control``), they are derived from the Redmine ``spent_on`` date and the spent hours instead of the import moment.
