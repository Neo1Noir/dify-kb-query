import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.parse
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tag_kb", ROOT / "skills/dify-kb-query/scripts/kb_query.py")
kb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb)
D1 = "11111111-1111-4111-8111-111111111111"
D2 = "22222222-2222-4222-8222-222222222222"
DOC = "33333333-3333-4333-8333-333333333333"
OTHER_TAG = "44444444-4444-4444-8444-444444444444"


class TagScopeTests(unittest.TestCase):
    def setUp(self):
        self.cfg = kb.load_config()
        self.cfg["required_tags"] = self.cfg["required_tags"][:1]
        self.tag = self.cfg["required_tags"][0]
        self.rows = [self.row(D1, "[Engineering]-01-Requirements")]
        self.calls = []
        token = patch.object(kb, "get_api_key", return_value="test-only-key")
        token.start()
        self.addCleanup(token.stop)

    def row(self, uid, name):
        return {"id": uid, "name": name, "tags": [self.tag]}

    def api(self, cfg, ds, operation, **kwargs):
        self.calls.append(operation)
        if operation == "tags":
            return [dict(self.tag, binding_count="999")]
        if operation == "discover":
            return {"data": copy.deepcopy(self.rows), "has_more": False, "total": len(self.rows)}
        raise AssertionError("Unexpected content call: " + operation)

    def cli(self, args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch.object(kb, "load_config", side_effect=lambda: copy.deepcopy(self.cfg)):
            code = kb.main(args)
        return code, json.loads(out.getvalue())

    @contextlib.contextmanager
    def transport(self, responder):
        seen = []
        def opened(req, timeout):
            seen.append(req)
            return io.BytesIO(json.dumps(responder(req)).encode("utf-8"))
        with patch.object(kb.urllib.request, "build_opener") as build:
            build.return_value.open.side_effect = opened
            yield seen

    def test_scope_refresh_adds_new_and_removes_deleted_datasets(self):
        with patch.object(kb, "request", side_effect=self.api):
            first = kb.discover_datasets(self.cfg)
            self.assertEqual([d["id"] for d in first], [D1])
            self.rows = [self.row(D2, "New dataset")]
            second = kb.discover_datasets(self.cfg)
            self.assertEqual([d["id"] for d in second], [D2])
        with self.assertRaises(ValueError):
            kb.select_datasets(self.cfg, [D1])
        self.assertEqual(kb.select_datasets(self.cfg, ["New dataset"])[0]["id"], D2)

    def test_list_is_live_and_uses_results_not_binding_count(self):
        with patch.object(kb, "request", side_effect=self.api):
            code, data = self.cli(["--list"])
        self.assertEqual(code, 0)
        self.assertTrue(data["network"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["datasets"][0]["alias"], ["01", "Requirements"])
        self.assertEqual(self.calls, ["tags", "discover"])

    def test_missing_tag_never_falls_back_to_same_name_or_global_list(self):
        self.cfg["datasets"] = [{"id": D1, "name": "stale", "alias": []}]
        with patch.object(kb, "request", return_value=[{"id": OTHER_TAG, "name": self.tag["name"]}]) as net:
            with self.assertRaises(ValueError):
                kb.discover_datasets(self.cfg)
        self.assertNotIn("datasets", self.cfg)
        self.assertEqual(net.call_count, 1)

    def test_tag_rename_keeps_id_policy_and_reports_current_name(self):
        def api(cfg, ds, operation, **kwargs):
            if operation == "tags":
                return [dict(self.tag, name="Engineering resources")]
            return self.api(cfg, ds, operation, **kwargs)
        with patch.object(kb, "request", side_effect=api):
            kb.discover_datasets(self.cfg)
        self.assertEqual(self.cfg["resolved_tags"][0]["name"], "Engineering resources")

    def test_server_ignoring_tag_filter_is_rejected(self):
        self.rows[0]["tags"] = [{"id": OTHER_TAG, "name": "Other team"}]
        with patch.object(kb, "request", side_effect=self.api):
            with self.assertRaisesRegex(ValueError, "without the allowed tag"):
                kb.discover_datasets(self.cfg)
        self.assertNotIn("datasets", self.cfg)

    def test_all_pages_must_finish_before_scope_is_usable(self):
        def api(cfg, ds, operation, **kwargs):
            if operation == "tags":
                return [self.tag]
            if kwargs["params"]["page"] == 1:
                return {"data": self.rows, "has_more": True}
            raise ValueError("HTTP 503")
        with patch.object(kb, "request", side_effect=api):
            with self.assertRaisesRegex(ValueError, "503"):
                kb.discover_datasets(self.cfg)
        self.assertNotIn("datasets", self.cfg)

    def test_complete_pagination_accumulates_scope(self):
        def api(cfg, ds, operation, **kwargs):
            if operation == "tags":
                return [self.tag]
            page = kwargs["params"]["page"]
            return {"data": self.rows if page == 1 else [self.row(D2, "Second-page dataset")], "has_more": page == 1}
        with patch.object(kb, "request", side_effect=api):
            self.assertEqual(len(kb.discover_datasets(self.cfg)), 2)

    def test_broken_pagination_or_duplicates_do_not_produce_scope(self):
        for response in ({"data": self.rows}, {"data": self.rows, "has_more": "false"},
                         {"data": [], "has_more": True}, {"data": self.rows * 2, "has_more": False}):
            def api(cfg, ds, operation, **kwargs):
                return [self.tag] if operation == "tags" else response
            with self.subTest(response=response), patch.object(kb, "request", side_effect=api):
                with self.assertRaises(ValueError):
                    kb.discover_datasets(self.cfg)
                self.assertNotIn("datasets", self.cfg)

    def test_discovery_limit_refuses_partial_scope(self):
        count = []
        def api(cfg, ds, operation, **kwargs):
            if operation == "tags":
                return [self.tag]
            page = kwargs["params"]["page"]
            count.append(page)
            uid = f"00000000-0000-4000-8000-{page:012d}"
            return {"data": [self.row(uid, "page " + str(page))], "has_more": True}
        with patch.object(kb, "request", side_effect=api), self.assertRaises(ValueError):
            kb.discover_datasets(self.cfg)
        self.assertEqual(count, [1, 2, 3, 4, 5])
        self.assertNotIn("datasets", self.cfg)

    def test_empty_scope_and_failure_never_reach_content(self):
        self.rows = []
        with patch.object(kb, "request", side_effect=self.api):
            self.assertEqual(self.cli(["--list"])[1]["status"], "empty_scope")
            code, data = self.cli(["query", "--all"])
            self.assertEqual((code, data["status"]), (1, "empty_scope"))
        with patch.object(kb, "request", side_effect=ValueError("HTTP 403")) as net:
            code, data = self.cli(["query", "--all"])
            self.assertEqual((code, data["stage"]), (1, "scope_discovery"))
            self.assertEqual(net.call_count, 1)

    def test_raw_uuid_cannot_bypass_tag_scope(self):
        with patch.object(kb, "request", side_effect=self.api):
            code, data = self.cli(["query", "-d", D2])
        self.assertEqual(code, 2)
        self.assertEqual(self.calls, ["tags", "discover"])

    def test_discovery_request_always_has_fixed_tag_and_respects_permissions(self):
        with self.transport(lambda req: {"data": [], "has_more": False}) as seen:
            kb.request(self.cfg, None, "discover", params={"page": 1, "tag_id": self.tag["id"]})
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(seen[0].full_url).query)
        self.assertEqual(query["tag_ids"], [self.tag["id"]])
        self.assertEqual(query["include_all"], ["false"])
        self.assertEqual(seen[0].method, "GET")
        for params in ({"tag_id": OTHER_TAG}, {"tag_ids": OTHER_TAG}, {"include_all": "true"}, {"page": 6}):
            with self.subTest(params=params), self.transport(lambda req: {}) as blocked:
                with self.assertRaises(ValueError):
                    kb.request(self.cfg, None, "discover", params=params)
                self.assertEqual(blocked, [])

    def test_removing_tag_blocks_every_content_operation(self):
        ds = {"id": D1, "name": "known", "alias": []}
        self.cfg["datasets"] = [ds]
        for operation in ("detail", "fields", "documents", "document", "segments", "search"):
            kwargs = {"document_id": DOC} if operation in {"document", "segments"} else {}
            if operation == "search":
                kwargs["payload"] = {"query": "test", "retrieval_model": {}}
            with self.subTest(operation=operation), self.transport(lambda req: {"data": []}) as seen:
                with self.assertRaisesRegex(ValueError, "no longer satisfies the allowed tag policy"):
                    kb.request(self.cfg, ds, operation, **kwargs)
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0].method, "GET")
                self.assertTrue(seen[0].full_url.endswith("/tags"))

    def test_matching_tag_allows_content_after_membership_check(self):
        ds = {"id": D1, "name": "known", "alias": []}
        self.cfg["datasets"] = [ds]
        def responder(req):
            return {"data": [self.tag]} if req.full_url.endswith("/tags") else {"records": []}
        with self.transport(responder) as seen:
            result = kb.request(self.cfg, ds, "search", payload={"query": "test", "retrieval_model": {}})
        self.assertEqual(result, {"records": []})
        self.assertEqual([r.method for r in seen], ["GET", "POST"])
        self.assertTrue(seen[0].full_url.endswith("/tags"))
        self.assertTrue(seen[1].full_url.endswith("/retrieve"))

    def test_offline_plan_never_claims_membership_validation(self):
        with patch.object(kb, "request", side_effect=AssertionError("network")):
            code, data = self.cli(["query", "-d", D2, "--dry-run"])
        self.assertEqual((code, data["status"], data["network"]), (0, "plan_only", False))
        self.assertNotIn("datasets", data)



    def multi_api(self, cfg, ds, operation, **kwargs):
        self.calls.append((operation, kwargs.get("params", {}).get("tag_id")))
        second = {"id": OTHER_TAG, "name": "Another allowed team"}
        shared = {"id": DOC, "name": "Shared resources", "tags": [self.tag, second]}
        if operation == "tags":
            return [self.tag, second, {"id": "55555555-5555-4555-8555-555555555555", "name": "Unapproved team"}]
        if operation == "discover":
            tag_id = kwargs["params"]["tag_id"]
            row = self.rows[0] if tag_id == self.tag["id"] else {
                "id": D2, "name": "[Marketing]-01-Brochures", "tags": [second]}
            return {"data": [row, shared], "has_more": False}
        raise AssertionError(operation)

    def use_two_tags(self):
        self.cfg["required_tags"].append({"id": OTHER_TAG, "name": "Another allowed team"})

    def test_multiple_tags_form_union_and_shared_library_is_deduplicated(self):
        self.use_two_tags()
        with patch.object(kb, "request", side_effect=self.multi_api):
            rows = kb.discover_datasets(self.cfg)
        self.assertEqual({d["id"] for d in rows}, {D1, D2, DOC})
        self.assertEqual(len(rows), 3)
        self.assertEqual([t for op, t in self.calls if op == "discover"], [self.tag["id"], OTHER_TAG])

    def test_tags_command_exposes_current_tags_and_allowed_flags_without_content(self):
        self.use_two_tags()
        with patch.object(kb, "request", side_effect=self.multi_api):
            code, result = self.cli(["--tags"])
        self.assertEqual(code, 0)
        self.assertEqual([t["allowed"] for t in result["tags"]], [True, True, False])
        self.assertEqual([op for op, _ in self.calls], ["tags"])

    def test_query_tag_selection_narrows_scope_without_rewriting_policy(self):
        self.use_two_tags()
        policy = copy.deepcopy(self.cfg["required_tags"])
        with patch.object(kb, "request", side_effect=self.multi_api):
            rows = kb.discover_datasets(self.cfg, ["Another allowed team"])
        self.assertEqual({r["id"] for r in rows}, {D2, DOC})
        self.assertEqual(self.cfg["required_tags"], policy)
        self.assertEqual([t for op, t in self.calls if op == "discover"], [OTHER_TAG])

    def test_query_can_select_multiple_allowed_tags(self):
        self.use_two_tags()
        with patch.object(kb, "request", side_effect=self.multi_api):
            code, result = self.cli(["--list", "--tag", self.tag["name"], "--tag", OTHER_TAG])
        self.assertEqual((code, result["count"]), (0, 3))
        self.assertEqual(len(result["query_tags"]), 2)

    def test_disallowed_query_tag_stops_after_tag_lookup(self):
        self.use_two_tags()
        with patch.object(kb, "request", side_effect=self.multi_api):
            code, result = self.cli(["query", "--tag", "Unapproved team", "--all"])
        self.assertEqual((code, result["stage"]), (1, "scope_discovery"))
        self.assertEqual([op for op, _ in self.calls], ["tags"])

    def test_selected_tag_not_other_allowed_tag_is_checked_before_content(self):
        self.use_two_tags()
        ds = {"id": D1, "name": "known", "alias": []}
        self.cfg["datasets"] = [ds]
        self.cfg["query_tags"] = [self.tag]
        with self.transport(lambda req: {"data": [{"id": OTHER_TAG, "name": "other"}]}) as seen:
            with self.assertRaisesRegex(ValueError, "no longer satisfies the allowed tag policy"):
                kb.request(self.cfg, ds, "search", payload={"query": "q", "retrieval_model": {}})
        self.assertEqual(len(seen), 1)

    def test_missing_second_policy_tag_does_not_silently_drop_it(self):
        self.use_two_tags()
        with patch.object(kb, "request", return_value=[self.tag]) as net:
            with self.assertRaises(ValueError):
                kb.discover_datasets(self.cfg)
        self.assertEqual(net.call_count, 1)
        self.assertNotIn("datasets", self.cfg)

    def test_same_number_in_different_departments_requires_scope_or_full_name(self):
        self.use_two_tags()
        with patch.object(kb, "request", side_effect=self.multi_api):
            kb.discover_datasets(self.cfg)
            with self.assertRaises(ValueError):
                kb.select_datasets(self.cfg, ["01"])
            kb.discover_datasets(self.cfg, [OTHER_TAG])
            self.assertEqual(kb.select_datasets(self.cfg, ["01"])[0]["id"], D2)

    def test_cli_has_no_policy_edit_or_arbitrary_config_option(self):
        before = kb.CONFIG_PATH.read_bytes()
        for argv in (["--set-tag", OTHER_TAG], ["--config", "other.json"], ["--allow-all-tags"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), patch.object(kb, "request", side_effect=AssertionError("network")):
                with self.assertRaises(SystemExit) as raised:
                    kb.main(argv)
                self.assertEqual(raised.exception.code, 2)
        self.assertEqual(kb.CONFIG_PATH.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
