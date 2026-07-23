# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import date
from unittest.mock import Mock

from odoo.tests.common import TransactionCase

from ..services.redmine_client import RedmineAPIError, RedmineClient


class TestRedmineClient(TransactionCase):
    def _response(self, payload, status=200):
        response = Mock()
        response.status_code = status
        response.headers = {}
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_time_entry_pagination(self):
        session = Mock()
        session.get.side_effect = [
            self._response(
                {"time_entries": [{"id": 1}, {"id": 2}], "total_count": 3}
            ),
            self._response({"time_entries": [{"id": 3}], "total_count": 3}),
        ]
        client = RedmineClient(
            "https://redmine.example.com", "secret", session=session, max_retries=0
        )
        pages = list(
            client.iter_time_entry_pages(
                10,
                date(2025, 1, 1),
                date(2025, 1, 31),
                limit=2,
            )
        )
        self.assertEqual([[1, 2], [3]], [[x["id"] for x in page] for page in pages])
        self.assertEqual(0, session.get.call_args_list[0].kwargs["params"]["offset"])
        self.assertEqual(2, session.get.call_args_list[1].kwargs["params"]["offset"])
        self.assertNotIn("secret", str(session.get.call_args_list[0].kwargs["params"]))

    def test_invalid_collection_is_rejected(self):
        session = Mock()
        session.get.return_value = self._response({"unexpected": []})
        client = RedmineClient("https://redmine.example.com", "secret", session=session)
        with self.assertRaises(RedmineAPIError):
            list(client.iter_user_pages())
