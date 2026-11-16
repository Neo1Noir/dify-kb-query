#!/usr/bin/env python3
"""Bounded, allowlisted Dify knowledge queries. Python standard library only."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

CONFIG_PATH = Path(os.environ.get("DIFY_KB_CONFIG", Path(__file__).with_name("config.json")))
MAX_RESPONSE = 8 * 1024 * 1024
MAX_CONTENT = 4000
MAX_RESULTS = 20
MAX_DISCOVERY_PAGES = 5
MAX_TARGETS = 20
ROUTES = {
    "tags": ("GET", "/datasets/tags"),
    "discover": ("GET", "/datasets"),
    "dataset_tags": ("GET", "/tags"),
    "detail": ("GET", ""),
    "fields": ("GET", "/metadata"),
    "documents": ("GET", "/documents"),
    "document": ("GET", "/documents/{document_id}"),
    "segments": ("GET", "/documents/{document_id}/segments"),
    "search": ("POST", "/retrieve"),
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_user_key():
    """Read only this named Windows user environment variable; never enumerate."""
    if sys.platform != "win32":
        return ""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as handle:
            value, kind = winreg.QueryValueEx(handle, "DIFY_KB_API_KEY")
        return value.strip() if kind == winreg.REG_SZ and isinstance(value, str) else ""
    except OSError:
        return ""


def get_api_key():
    # Registry fallback also works in an Agent opened before first-time setup.
    return os.environ.get("DIFY_KB_API_KEY", "").strip() or read_user_key()


def valid_uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def load_config():
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError("Configuration is missing or invalid; no fallback configuration is used") from None
    require(isinstance(cfg, dict) and set(cfg) == {"api_base_url", "required_tags"},
            "Configuration must contain only api_base_url and required_tags; do not store API keys or a fixed dataset list")
    base = cfg["api_base_url"]
    require(isinstance(base, str), "api_base_url must be a string")
    url = urllib.parse.urlsplit(base)
    require(url.scheme in {"http", "https"} and url.hostname and not url.username
            and not url.password and not url.query and not url.fragment
            and url.path == "/v1" and not re.search(r"[\s\\%]", base),
            "api_base_url must be http(s)://approved-host[:port]/v1")
    url.port  # Validate a malformed port before any network request.
    tags = cfg["required_tags"]
    require(isinstance(tags, list) and 1 <= len(tags) <= 10, "Configure 1-10 allowed tags; an empty policy is not permitted")
    seen = set()
    for tag in tags:
        require(isinstance(tag, dict) and set(tag) == {"id", "name"}
                and valid_uuid(tag["id"]) and isinstance(tag["name"], str) and tag["name"].strip(),
                "Each allowed tag must have a valid UUID and display name")
        require(tag["id"] not in seen, "Duplicate allowed tag ID")
        seen.add(tag["id"])
    return cfg


def read_tags(cfg):
    tags = request(cfg, None, "tags")
    cfg["resolved_tags"] = []
    for required in cfg["required_tags"]:
        matching = [t for t in tags if isinstance(t, dict) and t.get("id") == required["id"]]
        require(len(matching) == 1 and isinstance(matching[0].get("name"), str),
                "Configured tag is missing or ambiguous; do not fall back to another tag or all datasets")
        cfg["resolved_tags"].append({"id": matching[0]["id"], "name": matching[0]["name"]})
    return [{"id": t.get("id"), "name": t.get("name"),
             "allowed": t.get("id") in {r["id"] for r in cfg["required_tags"]}}
            for t in tags if isinstance(t, dict) and valid_uuid(t.get("id")) and isinstance(t.get("name"), str)]


def discover_datasets(cfg, tag_selectors=None):
    """Refresh the bounded selected-tag scope; no persistent dataset list or fallback."""
    cfg.pop("datasets", None)
    read_tags(cfg)
    cfg["query_tags"] = []
    if not tag_selectors:
        cfg["query_tags"] = cfg["resolved_tags"]
    else:
        for token in tag_selectors:
            matches = [t for t in cfg["resolved_tags"] if token.strip().casefold() in
                       (t["id"].casefold(), t["name"].casefold())]
            require(len(matches) == 1, "Selected tag is not allowed, missing, or ambiguous; do not broaden the policy")
            if matches[0] not in cfg["query_tags"]:
                cfg["query_tags"].append(matches[0])
    datasets, seen = [], set()
    # Query tags separately: Dify's multi-tag query can mean AND; this policy is OR.
    for required in cfg["query_tags"]:
        tag_seen = set()
        for page in range(1, MAX_DISCOVERY_PAGES + 1):
            result = request(cfg, None, "discover", params={"page": page, "tag_id": required["id"]})
            rows = result.get("data")
            require(isinstance(rows, list) and len(rows) <= 100 and type(result.get("has_more")) is bool,
                    "Incomplete dataset discovery page; partial inventories are rejected")
            for ds in rows:
                require(isinstance(ds, dict) and valid_uuid(ds.get("id"))
                        and isinstance(ds.get("name"), str) and ds["name"].strip(), "Invalid dataset discovery result")
                require(ds["id"] not in tag_seen, "Duplicate dataset across pages for one tag; inconsistent inventory rejected")
                require(isinstance(ds.get("tags"), list) and required["id"] in
                        [t.get("id") for t in ds["tags"] if isinstance(t, dict)],
                        "Server returned a dataset without the allowed tag; unfiltered results rejected")
                tag_seen.add(ds["id"])
                if ds["id"] in seen:
                    continue
                seen.add(ds["id"])
                require(len(seen) <= 500, "Combined tag scope exceeds 500 datasets; partial inventories are rejected")
                # Aliases come from current names, not a fixed authorization list.
                aliases = []
                parts = re.fullmatch(r"\[[^\]]+\]-(\d{2})-(.+)", ds["name"])
                if parts:
                    aliases = [parts[1], parts[2]]
                datasets.append({"id": ds["id"], "name": ds["name"], "alias": aliases})
            if not result["has_more"]:
                break
            require(bool(rows), "Empty discovery page claims another page")
        else:
            raise ValueError("Tag discovery exceeds five pages; partial inventories are rejected")
    cfg["datasets"] = datasets
    return datasets


def select_datasets(cfg, selectors, all_datasets=False):
    require(not (selectors and all_datasets), "-d and --all cannot be combined")
    if all_datasets:
        return cfg["datasets"]
    require(selectors, "Select a dataset with -d, or explicitly select all allowed datasets with --all")
    picked = []
    for token in selectors:
        hits = [d for d in cfg["datasets"] if token.strip().casefold() in
                [s.casefold() for s in [d["id"], d["name"], *d["alias"]]]]
        require(len(hits) == 1, "Dataset is outside the current tag scope or its selector is ambiguous; use --list and select an exact name or ID")
        if hits[0] not in picked:
            picked.append(hits[0])
    return picked


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ensure_tag_membership(cfg, ds):
    result = request(cfg, ds, "dataset_tags")
    tags = result.get("data")
    require(isinstance(tags, list) and bool({t["id"] for t in cfg.get("query_tags", cfg["required_tags"])} &
            {t.get("id") for t in tags if isinstance(t, dict)}),
            "Dataset no longer satisfies the allowed tag policy")


def request(cfg, ds, operation, *, document_id=None, params=None, payload=None):
    """No arbitrary URL, method, path, redirects, or ambient proxy support."""
    require(operation in ROUTES, "Dify operation is not allowed")
    method, suffix = ROUTES[operation]
    if operation in {"tags", "discover"}:
        require(ds is None and document_id is None, "Tag discovery does not accept dataset or document arguments")
        path = suffix
    else:
        require(ds in cfg.get("datasets", []) and valid_uuid(ds["id"]), "Dataset is outside the verified tag scope")
        path = "/datasets/" + ds["id"] + suffix
    if "{document_id}" in suffix:
        require(valid_uuid(document_id), "document_id must be a canonical UUID")
        path = path.format(document_id=document_id)
    else:
        require(document_id is None, "This operation does not accept document_id")
    allowed_params = {"discover": {"page", "tag_id"}, "documents": {"page", "limit", "keyword"},
                      "document": {"metadata"}, "segments": {"page", "limit", "status"}}
    require(set(params or {}) <= allowed_params.get(operation, set()), "Query parameter is not allowed")
    if operation == "discover":
        page = (params or {}).get("page", 1)
        require(type(page) is int and 1 <= page <= MAX_DISCOVERY_PAGES, "Discovery page is out of range")
        tag_id = (params or {}).get("tag_id")
        require(valid_uuid(tag_id) and tag_id in [t["id"] for t in cfg.get("query_tags", cfg["required_tags"])],
                "Tag is outside the allowed policy or selected query scope")
        params = {"page": page, "limit": 100, "include_all": "false", "tag_ids": tag_id}
    require((method == "POST") == (payload is not None), "Request body is not valid for this operation")
    if payload is not None:
        require(set(payload) == {"query", "retrieval_model"}, "Retrieval request field is not allowed")
    key = get_api_key()
    require(bool(key) and key.isascii() and not re.search(r"\s|[\x00-\x1f\x7f]", key),
            "DIFY_KB_API_KEY is missing or invalid; configure it locally, never paste a key into chat")
    if operation not in {"tags", "discover", "dataset_tags"}:
        ensure_tag_membership(cfg, ds)
    url = cfg["api_base_url"] + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json", "Accept": "application/json"})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(req, timeout=25) as response:
            raw = response.read(MAX_RESPONSE + 1)
        require(len(raw) <= MAX_RESPONSE, "Response exceeds 8 MiB; narrow the query")
        result = json.loads(raw)
        require(isinstance(result, list if operation == "tags" else dict), "Invalid server response structure")
        return result
    except urllib.error.HTTPError as exc:
        # Do not echo remote error bodies, which may contain credentials or instructions.
        raise ValueError(f"HTTP {exc.code}; query stopped without retries, relaxed filters, or management calls") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Network or TLS failure; dataset query stopped") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Server did not return valid JSON; dataset query stopped") from None


def metadata_map(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {x["name"]: x.get("value") for x in value if isinstance(x, dict) and "name" in x}
    return {}


def make_filters(items):
    require(len(items) <= 8, "At most eight metadata filters are supported")
    filters = []
    for name, operator, value in items:
        require(name.strip() and len(name) <= 100 and value.strip() and len(value) <= 500,
                "Filter field or value is empty or too long")
        require(operator in {"is", "contains"}, "Only is and contains operators are supported")
        filters.append({"name": name, "operator": operator, "value": value})
    return filters


def wire_filters(filters):
    return {"logical_operator": "and", "conditions": [
        {"name": f["name"], "comparison_operator": f["operator"], "value": f["value"]}
        for f in filters]}


def matches(metadata, filters):
    for f in filters:
        actual = metadata.get(f["name"])
        if not isinstance(actual, str):
            return False
        if f["operator"] == "is" and actual != f["value"]:
            return False
        if f["operator"] == "contains" and f["value"] not in actual:
            return False
    return True


def document_summary(doc):
    return {"document_id": doc.get("id"), "document_name": doc.get("name"),
            "indexing_status": doc.get("indexing_status"), "enabled": doc.get("enabled"),
            "archived": doc.get("archived"), "metadata": metadata_map(doc.get("doc_metadata"))}


def segment_summary(seg):
    require(isinstance(seg, dict) and isinstance(seg.get("content"), str), "Invalid segment response")
    require(seg.get("enabled") is not False, "Disabled segment returned; do not use it as evidence")
    content, answer = seg["content"], seg.get("answer") or ""
    require(isinstance(answer, str), "Invalid segment answer")
    return {"segment_id": seg.get("id"), "position": seg.get("position"),
            "content": content[:MAX_CONTENT], "answer": answer[:MAX_CONTENT],
            "truncated": len(content) > MAX_CONTENT or len(answer) > MAX_CONTENT}


def retrieve(cfg, ds, args, filters):
    detail = request(cfg, ds, "detail")
    stored = detail.get("retrieval_model_dict") or detail.get("retrieval_model")
    require(isinstance(stored, dict) and stored.get("search_method") in
            {"semantic_search", "full_text_search", "hybrid_search"}, "Cannot read the dataset retrieval settings")
    names = {"search_method", "reranking_enable", "reranking_mode", "reranking_model", "weights",
             "top_k", "score_threshold_enabled", "score_threshold"}
    model = {k: v for k, v in stored.items() if k in names}
    model["top_k"] = args.top_k
    model.setdefault("reranking_enable", False)
    model.setdefault("score_threshold_enabled", False)
    model["score_threshold"] = model.get("score_threshold") or 0.0
    if args.threshold is not None:
        model.update(score_threshold_enabled=args.threshold > 0, score_threshold=args.threshold)
    if filters:
        fields = request(cfg, ds, "fields").get("doc_metadata")
        require(isinstance(fields, list), "Cannot read metadata field definitions")
        types = {f["name"]: f.get("type") for f in fields}
        require(all(types.get(f["name"]) == "string" for f in filters),
                "Filter field is missing or is not a string; unfiltered fallback is not allowed")
        model["metadata_filtering_conditions"] = wire_filters(filters)
    response = request(cfg, ds, "search", payload={"query": args.query, "retrieval_model": model})
    records = response.get("records")
    require(isinstance(records, list), "Retrieval response lacks records; this is not an empty result")
    output, seen, documents = [], set(), {}
    for record in records:
        seg = record.get("segment") or {}
        doc = seg.get("document") or {}
        doc_id = seg.get("document_id") or doc.get("id")
        require(valid_uuid(doc_id), "Retrieval result lacks a valid document_id")
        meta = metadata_map(doc.get("doc_metadata"))
        if filters and not all(f["name"] in meta for f in filters):
            if doc_id not in documents:
                documents[doc_id] = request(cfg, ds, "document", document_id=doc_id, params={"metadata": "all"})
            doc = documents[doc_id]
            meta = metadata_map(doc.get("doc_metadata"))
        require(not filters or matches(meta, filters),
                "Returned document fails explicit filters; discard dataset results")
        score = record.get("score")
        require(score is None or (isinstance(score, (int, float)) and math.isfinite(score)), "Invalid result score")
        if args.threshold and (score is None or score < args.threshold):
            continue
        summary = segment_summary(seg)
        identity = (doc_id, summary["segment_id"], summary["position"])
        if identity in seen:
            continue
        seen.add(identity)
        output.append(dict(summary, dataset_id=ds["id"], dataset=ds["name"], document_id=doc_id,
                           document_name=doc.get("name"), score=score, metadata=meta))
    return output[:args.top_k]


def paged(result, summarize, args):
    require(isinstance(result.get("data"), list), "Paginated response lacks data")
    data = result["data"]
    return {"data": [summarize(d) for d in data[:args.limit]], "page": args.page, "limit": args.limit,
            "has_more": result.get("has_more"), "total": result.get("total"),
            "truncated": len(data) > args.limit, "coverage": "one_page_only"}


def run(args):
    cfg = load_config()
    filters = make_filters(args.filter or [])
    require(1 <= args.top_k <= 10, "top-k must be between 1 and 10")
    require(args.threshold is None or (math.isfinite(args.threshold) and 0 <= args.threshold <= 1),
            "threshold must be finite and between 0 and 1")
    require(1 <= args.page <= 10000 and 1 <= args.limit <= 20, "page must be 1-10000 and limit must be 1-20")
    operation = "search"
    for name in ("tags", "list", "check", "fields", "documents", "read"):
        if getattr(args, name):
            operation = name
    require(not args.query or operation == "search", "Search text cannot be combined with catalog or read operations")
    require(not filters or operation == "search", "Metadata filters apply only to search and are never silently ignored")
    require(not args.keyword or operation == "documents", "keyword applies only to document-name listing")
    require(args.keyword is None or (args.keyword.strip() and len(args.keyword) <= 250), "keyword is empty or too long")
    require(operation in {"documents", "read"} or (args.page == 1 and args.limit == 10),
            "page/limit apply only to document listing or segment reading")
    require(operation == "search" or (args.top_k == 5 and args.threshold is None),
            "top-k/threshold apply only to search")
    if operation in {"tags", "list"}:
        require(not args.datasets and not args.all, "--tags/--list do not accept -d or --all")
    else:
        require(not (args.datasets and args.all), "-d and --all cannot be combined")
        require(args.datasets or args.all, "Specify -d or --all; querying all datasets is never implicit")
        require(not args.datasets or all(s.strip() for s in args.datasets), "Dataset selector cannot be empty")
    require(not args.tag or all(s.strip() for s in args.tag), "Tag selector cannot be empty")
    require(operation != "tags" or not args.tag, "--tags lists tags and does not accept --tag selectors")
    if operation == "search":
        require(args.query and args.query.strip() and len(args.query) <= 250, "Search text must contain 1-250 characters")
    if operation == "read":
        require(not args.all and args.datasets and len(args.datasets) == 1 and valid_uuid(args.read),
                "--read requires exactly one -d dataset and a valid document UUID")
    plan = {"operation": operation, "required_tags": cfg["required_tags"], "tag_match": "any",
            "tag_selectors": args.tag or [],
            "dataset_selectors": args.datasets or [], "all_tagged_datasets": args.all,
            "query": args.query, "filters": filters, "logical_operator": "and"}
    if args.dry_run:
        return dict(plan, status="plan_only", network=False,
                    note="Only local arguments were checked; tag existence, membership, and selectors were not verified"), 0
    try:
        if operation == "tags":
            tags = read_tags(cfg)
            return dict(plan, status="ok", tags=tags, required_tags=cfg["resolved_tags"], network=True), 0
        datasets = discover_datasets(cfg, args.tag)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        message = str(exc) if type(exc) is ValueError else "Invalid tag discovery response"
        return dict(plan, status="error", stage="scope_discovery", complete=False,
                    errors=[{"message": message}]), 1
    plan["required_tags"] = cfg["resolved_tags"]
    plan["query_tags"] = cfg["query_tags"]
    if not datasets:
        return dict(plan, status="empty_scope", datasets=[], complete=True,
                    message="No datasets are visible to this key under the allowed tags; no content query was made"), 0 if operation == "list" else 1
    if operation == "list":
        return dict(plan, status="ok", datasets=datasets, count=len(datasets), network=True), 0
    targets = select_datasets(cfg, args.datasets, args.all)
    require(len(targets) <= MAX_TARGETS, "At most 20 datasets per query; use --list and narrow the selection with -d")
    plan["datasets"] = [{"id": d["id"], "name": d["name"]} for d in targets]
    results, errors = [], []
    for ds in targets:
        try:
            if operation == "search":
                result = {"records": retrieve(cfg, ds, args, filters)}
            elif operation == "check":
                detail = request(cfg, ds, "detail")
                require(detail.get("id") == ds["id"], "Server returned a different dataset ID")
                result = {"read_access": True, "retrieval_tested": False}
            elif operation == "fields":
                raw = request(cfg, ds, "fields")
                require(isinstance(raw.get("doc_metadata"), list), "Invalid metadata field response")
                result = {"fields": [{k: f.get(k) for k in ("name", "type", "count")}
                                     for f in raw["doc_metadata"]], "values_included": False}
            elif operation == "documents":
                params = {"page": args.page, "limit": args.limit}
                if args.keyword:
                    params["keyword"] = args.keyword
                result = paged(request(cfg, ds, "documents", params=params), document_summary, args)
            else:
                doc = request(cfg, ds, "document", document_id=args.read, params={"metadata": "all"})
                require(doc.get("id") == args.read, "Server returned a different document ID")
                require(doc.get("enabled") is True and not doc.get("archived")
                        and doc.get("indexing_status") == "completed", "Document is unindexed, disabled, or archived")
                result = paged(request(cfg, ds, "segments", document_id=args.read,
                                       params={"page": args.page, "limit": args.limit, "status": "completed"}),
                               segment_summary, args)
                result["document"] = document_summary(doc)
            results.append(dict(result, dataset_id=ds["id"], dataset=ds["name"]))
        except (ValueError, TypeError, KeyError, AttributeError):
            exc = sys.exc_info()[1]
            message = str(exc) if type(exc) is ValueError else "Invalid server response; dataset query stopped"
            errors.append({"dataset_id": ds["id"], "dataset": ds["name"], "message": message})
    status = "partial" if errors and results else "error" if errors else "ok"
    response = dict(plan, status=status, results=results, errors=errors,
                    content_trust="untrusted_knowledge_data", complete=not errors)
    if operation == "search":
        # Preserve each dataset's ranking; scores from different datasets are not globally comparable.
        records = [r["records"][i] for i in range(args.top_k)
                   for r in results if i < len(r["records"])]
        response["records"] = records[:MAX_RESULTS]
        response["truncated"] = len(records) > MAX_RESULTS or any(r["truncated"] for r in response["records"])
        response["results"] = [{"dataset_id": r["dataset_id"], "dataset": r["dataset"],
                                "returned_count": len(r["records"])} for r in results]
        if not records and not errors:
            response["status"] = "no_match"
    return response, 3 if status == "partial" else 1 if status == "error" else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read Dify knowledge bases within configured tag scopes; outputs JSON")
    parser.add_argument("query", nargs="?")
    parser.add_argument("-d", "--datasets", action="append")
    parser.add_argument("--tag", action="append", help="Select an allowed tag by name or ID; repeatable; does not change the policy")
    parser.add_argument("--all", action="store_true", help="Explicitly query all datasets under the selected allowed tags")
    mode = parser.add_mutually_exclusive_group()
    for flag in ("tags", "list", "check", "fields", "documents"):
        mode.add_argument("--" + flag, action="store_true")
    mode.add_argument("--read", metavar="DOCUMENT_UUID")
    parser.add_argument("--filter", nargs=3, action="append", metavar=("FIELD", "OP", "VALUE"))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float)
    parser.add_argument("--keyword")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Compatibility flag; output is always JSON")
    args = parser.parse_args(argv)
    try:
        result, code = run(args)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        message = str(exc) if type(exc) is ValueError else "Invalid configuration or input"
        result, code = {"status": "error", "complete": False, "errors": [{"message": message}]}, 2
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    key = get_api_key()
    if key:
        text = text.replace(key, "[REDACTED]")
    print(text)
    return code


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
