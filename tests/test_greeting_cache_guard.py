"""Unit test guard greeting_cache (pure-local, tanpa koneksi/secret).

Dashboard harus menolak cookie greeting_cache berbentuk JSON non-dict
atau dict tanpa kunci phrase/text, lalu jatuh ke get_time_greeting().
"""
import unittest
from unittest.mock import MagicMock


async def _async_result(value):
    return value


class TestGreetingCacheGuard(unittest.TestCase):
    def _dashboard_with_cookie(self, cookie_value):
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.dashboard_routes import register_dashboard_routes

        fake_request = MagicMock()
        fake_request.cookies = {"greeting_cache": cookie_value} if cookie_value is not None else {}
        fake_request.query_params = {}
        fake_request.headers = {}

        captured = {}
        fake_supabase = MagicMock()
        fake_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])
        fake_supabase.table.return_value.select.return_value.execute.return_value = MagicMock(data=[])
        fake_templates = MagicMock()

        def _fake_template_response(request=None, name=None, context=None):
            captured["context"] = context or {}
            return captured["context"]

        fake_templates.TemplateResponse = MagicMock(side_effect=_fake_template_response)

        class _FakeApp:
            def __init__(self):
                self.routes = {}

            def get(self, path, **kwargs):
                def decorator(func):
                    self.routes[path] = func
                    return func

                return decorator

            def post(self, path, **kwargs):
                def decorator(func):
                    self.routes[path] = func
                    return func

                return decorator

        fake_app = _FakeApp()
        register_dashboard_routes(
            app=fake_app,
            get_current_user=MagicMock(),
            supabase=fake_supabase,
            templates=fake_templates,
            log_activity=MagicMock(),
            get_ed_notification_count=MagicMock(return_value=_async_result(0)),
            compute_status_na=MagicMock(return_value=("Belum Terdaftar", 0)),
            get_company_info=MagicMock(return_value={}),
            format_date_id=MagicMock(return_value="01-01-2026"),
            _logo_render_width=MagicMock(return_value=100),
            _efek_samping_meta=MagicMock(return_value=None),
            _pdf_link_callback=MagicMock(),
            slugify=MagicMock(return_value="slug"),
            COMPANY_INFO={},
            _resolve_variant_components=MagicMock(return_value=[]),
            _flag_bahan_aktif=MagicMock(),
            _build_diff_changes=MagicMock(return_value=[]),
            get_time_greeting=MagicMock(
                return_value={"phrase": "Halo", "text": "Halo"}
            ),
        )
        handler_dashboard = fake_app.routes.get("/")
        self.assertIsNotNone(handler_dashboard)

        import asyncio

        asyncio.run(
            handler_dashboard(
                request=fake_request,
                current_user={"id": "00000000-0000-0000-0000-000000000000", "role": "staff"},
            )
        )
        return captured["context"]["greeting"]

    def test_non_dict_json_falls_back(self):
        greeting = self._dashboard_with_cookie("[]")
        self.assertIsInstance(greeting, dict)
        self.assertTrue(greeting.get("phrase") or greeting.get("text"))

    def test_dict_without_phrase_or_text_falls_back(self):
        greeting = self._dashboard_with_cookie('{"foo": "bar"}')
        self.assertIsInstance(greeting, dict)
        self.assertTrue(greeting.get("phrase") or greeting.get("text"))

    def test_valid_phrase_accepted(self):
        greeting = self._dashboard_with_cookie('{"phrase": "Selamat pagi"}')
        self.assertEqual(greeting, {"phrase": "Selamat pagi"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
