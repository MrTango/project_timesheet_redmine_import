# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging
import time
from urllib.parse import urljoin

import requests

from .utils import safe_message, validate_base_url

_logger = logging.getLogger(__name__)


class RedmineAPIError(Exception):
    """A sanitized, operator-facing Redmine API error."""


class RedmineClient(object):
    """Small, stateless-friendly Redmine REST client.

    A session may be injected for unit tests. Only GET operations are provided,
    preserving the one-way Redmine-to-Odoo integration boundary.
    """

    DEFAULT_LIMIT = 100

    def __init__(
        self,
        base_url,
        api_key,
        verify_ssl=True,
        timeout=(10, 60),
        session=None,
        max_retries=3,
    ):
        self.base_url = validate_base_url(base_url) + "/"
        self.api_key = api_key or ""
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_retries = max_retries

    def _url(self, path):
        return urljoin(self.base_url, path.lstrip("/"))

    def _get(self, path, params=None):
        headers = {
            "Accept": "application/json",
            "X-Redmine-API-Key": self.api_key,
        }
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    self._url(path),
                    params=params or {},
                    headers=headers,
                    verify=self.verify_ssl,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                if 300 <= response.status_code < 400:
                    raise RedmineAPIError("Redmine API redirects are not accepted.")
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        delay = min(2 ** attempt, 8)
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = min(int(retry_after), 30)
                        time.sleep(delay)
                        continue
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError:
                    raise RedmineAPIError("Redmine returned invalid JSON.")
                if not isinstance(payload, dict):
                    raise RedmineAPIError("Redmine returned an invalid response object.")
                return payload
            except RedmineAPIError:
                raise
            except requests.RequestException as error:
                last_error = error
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status not in (429, 500, 502, 503, 504) or attempt >= self.max_retries:
                    break
        message = safe_message(last_error, self.api_key)
        _logger.warning("Redmine API request failed: %s", message)
        raise RedmineAPIError("Redmine API request failed: %s" % message)

    def test_connection(self):
        payload = self._get("users/current.json")
        if not isinstance(payload.get("user"), dict) or not payload["user"].get("id"):
            raise RedmineAPIError("Redmine did not return the authenticated user.")
        return True

    def _iter_collection(self, path, collection, params=None, limit=None):
        offset = 0
        page_limit = limit or self.DEFAULT_LIMIT
        previous_signature = None
        while True:
            page_params = dict(params or {})
            page_params.update({"offset": offset, "limit": page_limit})
            payload = self._get(path, page_params)
            records = payload.get(collection)
            if not isinstance(records, list):
                raise RedmineAPIError(
                    "Redmine response is missing the '%s' collection." % collection
                )
            received = len(records)
            if not received:
                total = payload.get("total_count")
                if total is not None:
                    try:
                        total = int(total)
                    except (TypeError, ValueError):
                        raise RedmineAPIError("Redmine returned an invalid total_count.")
                    if offset < total:
                        raise RedmineAPIError(
                            "Redmine pagination ended before total_count was reached."
                        )
                yield records
                break
            yield records
            signature = tuple(
                record.get("id") if isinstance(record, dict) else repr(record)
                for record in records
            )
            if signature == previous_signature:
                raise RedmineAPIError("Redmine returned the same pagination page twice.")
            previous_signature = signature
            new_offset = offset + received
            total = payload.get("total_count")
            if total is not None:
                try:
                    if new_offset >= int(total):
                        break
                except (TypeError, ValueError):
                    raise RedmineAPIError("Redmine returned an invalid total_count.")
            elif received < page_limit:
                break
            if new_offset <= offset:
                raise RedmineAPIError("Redmine pagination did not make progress.")
            offset = new_offset

    def iter_time_entry_pages(self, project_id, date_from, date_to, limit=None):
        params = {
            "project_id": project_id,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
        }
        return self._iter_collection(
            "time_entries.json", "time_entries", params=params, limit=limit
        )

    def iter_issue_pages(self, project_id, limit=None):
        params = {"project_id": project_id, "status_id": "*"}
        return self._iter_collection("issues.json", "issues", params, limit)

    def iter_user_pages(self, limit=None):
        return self._iter_collection("users.json", "users", limit=limit)
