=================================
Project Timesheet Redmine Import
=================================

This Odoo 13 Community addon imports Redmine time entries into standard Odoo
``account.analytic.line`` timesheets. Redmine remains authoritative for projects,
issues, users referenced by time entries, and time tracking. Odoo remains
authoritative for customers, employees, sales orders, projects, billing, invoices,
and accounting.

The integration only performs HTTP ``GET`` requests. It never writes to Redmine
and never creates or synchronizes customers, products, sales orders, or invoices.

Features
========

* Multiple Redmine backends with SSL verification, connection test, start date,
  rolling synchronization window, optional default employee, and cron switch.
* Redmine project identifiers automatically resolved to numeric project IDs,
  plus explicit employee mappings.
* Automatic employee suggestions by exact, case-insensitive work email when the
  API user may list Redmine users.
* Paginated imports filtered by Redmine project and ``spent_on`` date range.
* Idempotent upserts, protected by a database uniqueness constraint on backend
  and Redmine time-entry ID.
* Existing entries are only changed when Redmine's ``updated_on`` is newer and
  the run permits updates.
* Optional issue-to-task creation with safe title/description update policies.
* Preview mode and detailed, durable import logs.
* Per-backend PostgreSQL advisory locking to prevent overlapping imports.
* Native ``sale_timesheet`` processing; imported lines use the existing Odoo
  project's task, analytic account, employee, customer, and sales setup.

Installation
============

Install the addon in an Odoo 13 addons path, refresh the Apps list, and install
``Project Timesheet Redmine Import``. Its dependencies include ``project``,
``sale``, ``hr``, ``hr_timesheet``, and ``sale_timesheet``. The last dependency is
required for standard timesheet-to-sales-order/invoice behavior.

The Python ``requests`` package must be available to Odoo.

Configuration
=============

Redmine
-------

#. Enable **Administration > Settings > API > Enable REST web service**.
#. Create a dedicated Redmine API user with read access to every imported project,
   time entry, and issue.
#. If automatic employee email matching is required, the API user must also be
   allowed to list Redmine users. Redmine commonly restricts ``GET /users.json``
   to administrators. Without this permission, manual mappings and the default
   employee continue to work.
#. Use HTTPS and a narrowly scoped API account.

Odoo backend
------------

As a Project Manager, open **Project > Configuration > Redmine > Backends**:

#. Enter the base URL without an endpoint suffix, for example
   ``https://redmine.example.com``.
#. Enter the API key. Leave **Verify SSL** enabled in production.
#. Set the earliest allowed Import Start Date.
#. Set the rolling Synchronization Window. A value of 60 asks Redmine for time
   entries whose ``spent_on`` date is in the last 60 days.
#. Optionally choose a company employee used when no explicit mapping exists.
#. Test the connection, then enable the backend cron if desired.

Stock Odoo 13 has no encrypted ORM field. The API key is masked in the form and
restricted by field/model access to Project Managers and Settings administrators,
but it is stored in the database. Protect database access and backups, use disk
or database encryption, or install a suitable secret-management addon when
at-rest application-level encryption is required.

Project mapping
---------------

Open the existing Odoo project and its **Redmine** page:

#. Select the backend.
#. Enter Redmine's project identifier, such as ``customer-portal``.
#. Enable the import. The first preview or import resolves and stores Redmine's
   numeric project ID automatically; later runs refresh it from the identifier.
#. Choose whether missing Redmine issues create Odoo tasks.
#. If task creation is enabled, choose one of:

   * Never update tasks
   * Update title only
   * Update title and description

The importer never archives, deletes, or closes Odoo tasks because a Redmine issue
is closed. The title format is ``RM-452 Fix Login``. Redmine descriptions are
treated as plain text and safely escaped before being stored in Odoo's HTML field.

The Odoo project must allow timesheets and have an analytic account. For invoicing,
configure the project/task and sale order item with Odoo's standard Odoo 13
``sale_timesheet`` workflow before importing. The addon deliberately does not
invent a sale order item. A time entry without a task can be imported but may be
non-billable under the native workflow.

Employee mapping
----------------

Open **Project > Configuration > Redmine > Employee Mappings**. Mappings discovered
during imports appear here. The importer matches Redmine ``mail`` to exactly one
active employee ``work_email`` in the backend company. Ambiguous and missing
matches remain visibly unmapped. A manager can select the employee manually.
The backend's default employee is a fallback and does not replace the explicit
mapping. Because the importer must only update an existing entry when Redmine's
``updated_on`` is newer, changing a mapping alone does not rewrite an unchanged
historical timesheet. Touch the source entry in Redmine and rerun its date range
when a historical line must be remapped.

Usage
=====

Manual import
-------------

On a mapped project's **Redmine** page, click **Import Redmine Hours**. Select a
From Date and To Date and choose:

* **Preview only**: read and validate API data and show would-import/would-update
  counts. It may resolve and store the numeric Redmine project ID, but does not
  change employee mappings, tasks, timesheets, or synchronization dates.
* **Update existing**: permit changes only when the fetched Redmine
  ``updated_on`` is strictly newer.

The result opens an import log containing counts, duration, state, and bounded
warning/error details. An individual invalid entry is skipped without discarding
other valid entries in the page.

Scheduled import
----------------

The daily scheduled action processes projects where both the backend cron and
project import switches are enabled. It imports from::

    max(today - synchronization_window, import_start_date)

through today. The rolling window is intentional: Redmine's ``from`` and ``to``
filters apply to ``spent_on``, not ``updated_on``. The API has no complete change
or deletion feed. Edits older than the selected window and deleted Redmine entries
are therefore not detected. Choose a window that matches the company's correction
policy; use a manual wider range for older corrections.

Data mapping
============

A Redmine entry produces a standard analytic line with:

* ``employee_id`` from the employee mapping or backend fallback;
* ``date`` from ``spent_on``;
* ``unit_amount`` from ``hours``;
* ``name`` from comments, then activity name as fallback;
* the mapped Odoo ``project_id`` and its ``account_id``;
* an issue task when one exists or task synchronization creates it;
* Redmine backend, time-entry, issue, activity, and update metadata.

The SQL constraint ``unique(redmine_backend_id, redmine_time_entry_id)`` is the
final duplicate guard. Ordinary local timesheets have null Redmine metadata and
are unaffected. Regular users retain standard Odoo visibility but cannot modify
or delete Redmine-owned lines, preserving Redmine as the source of truth.

Security
========

Only members of Project Manager or Settings may configure backends, mappings,
project Redmine settings, test connections, run imports, or read import logs.
Configuration and logs are restricted to allowed companies. Existing Odoo project
and timesheet record rules remain in force; this addon does not add a permissive
analytic-line record rule.

Operations and troubleshooting
==============================

* **401/403**: verify REST is enabled, the API key, and project/time/issue access.
* **Employee unmapped**: grant user-list access if acceptable, or set the mapping
  manually. Redmine time-entry payloads do not contain email addresses.
* **Not invoiceable**: verify the existing project's sale order, service product,
  sale order item, task billing mode, and employee-rate mapping in Odoo.
* **Old edit absent**: run a wider manual range or increase the rolling window.
* **SSL failure**: install the correct CA chain. Disabling verification is only a
  temporary diagnostic measure.
* **Partial result**: inspect Import Log details. Correct the source or mapping
  and rerun the same range; entries previously skipped because of an error can
  then import safely. Already imported lines still require a newer Redmine
  ``updated_on`` before the importer changes them.

Logs never intentionally include request headers or API keys. Full remote payloads
are not stored.

Technical design and extension points
=====================================

``services/redmine_client.py``
    Read-only REST transport, error normalization, and collection pagination.

``services/import_service.py``
    Orchestration, page-level caches, mappings, issue/task policy, validation,
    idempotent persistence, and logs.

``models/``
    Upgrade-safe stored mappings and metadata. Remote IDs are scoped by backend,
    allowing multiple Redmine instances.

Companion addons can subclass the models, override or wrap the backend client
factory, and extend the service hooks to add project synchronization, richer issue
synchronization, attachments, or activity mappings. Bidirectional synchronization
must remain a separate explicit module because this core client exposes only GET
operations.

Known limitations
=================

* Redmine offers no time-entry deletion feed; deleted entries are not deleted in
  Odoo automatically.
* Date filters are based on ``spent_on``. They do not find an edit outside the
  selected rolling window.
* Automatic email matching normally requires Redmine administrative user-list
  access.
* Redmine and native Odoo permissions may hide records from the integration user.
* Correct invoiceability depends entirely on pre-existing native Odoo sales and
  project configuration.

License
=======

AGPL-3.0 or later.
