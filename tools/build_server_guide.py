"""FastAPI app의 OpenAPI 스펙 → docs/server-api-guide.html 빌드.

main.app.openapi()를 파싱해 12개 endpoint를 카테고리화한 단일 HTML 페이지를 생성.
include_in_schema=False 로 숨겨진 cron 엔드포인트는 수동 보강.

직접 실행:
    .venv/Scripts/python.exe tools/build_server_guide.py

Pre-commit hook이 app/api/, app/domain/, main.py 변경 시 자동 호출한다.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


OUT = Path("docs/server-api-guide.html")
PROD_BASE = "https://auctionbridge-api-ak2wcqba2q-du.a.run.app"
LOCAL_BASE = "http://localhost:8000"


CATEGORIES: list[dict] = [
    {"id": "public-map", "title": "지도/매물 조회 (공개)",
     "subtitle": "프론트엔드 지도·상세 화면이 호출하는 매물 API", "icon": "🗺️",
     "use_when": "지도 뷰포트(BBox) 안의 매물 마커, 매물 상세, 카테고리별 통계를 가져올 때",
     "auth": "public",
     "match": lambda p: p.startswith("/api/v1/auctions")},
    {"id": "public-vehicles", "title": "차량 조회 (공개)",
     "subtitle": "자동차 리스트·필터·통계 — 차량 전용 화면용", "icon": "🚗",
     "use_when": "차량 카테고리·연료·연식·주행거리 조건으로 매물 리스트와 facet 통계를 가져올 때",
     "auth": "public",
     "match": lambda p: p.startswith("/api/v1/vehicles")},
    {"id": "admin", "title": "관리/보강 (Admin)",
     "subtitle": "온비드 데이터 수동 동기화 및 enrich (현재 인증 게이트 없음, local 한정)",
     "icon": "🛠️",
     "use_when": "수동으로 ingest를 돌리거나, 사진·입찰결과를 보강해야 할 때 (운영에서는 직접 호출 자제)",
     "auth": "admin-local",
     "match": lambda p: p.startswith("/api/v1/admin")},
    {"id": "internal", "title": "시스템/내부 (Internal)",
     "subtitle": "Cloud Scheduler·헬스체크 등 내부 트리거", "icon": "⚙️",
     "use_when": "Cloud Run 컨테이너 헬스체크, Cloud Scheduler가 OIDC 토큰으로 데일리 cron을 호출할 때",
     "auth": "oidc",
     "match": lambda p: p == "/health" or p.startswith("/api/v1/internal")},
]

MANUAL_PATHS: dict[str, dict] = {
    "/api/v1/internal/cron/daily-ingest": {
        "post": {
            "summary": "일 1회 온비드 ingest (Cloud Scheduler 호출)",
            "description": (
                "Cloud Scheduler가 OIDC ID 토큰(Authorization: Bearer)을 붙여 호출하는 "
                "내부 엔드포인트. 토큰의 audience가 settings.CRON_AUDIENCE(=Cloud Run "
                "service URL)와 같고, 발급자 이메일이 CRON_SERVICE_ACCOUNT_EMAIL과 "
                "정확히 일치해야 통과한다. ingest → 입찰결과 #8 보강 → #9 fallback → "
                "부동산 사진 → 동산 사진 순으로 실행한다."
            ),
            "tags": ["cron"],
            "parameters": [
                {"name": "Authorization", "in": "header", "required": True,
                 "schema": {"type": "string"},
                 "description": "Bearer <Google OIDC ID Token>"}
            ],
            "responses": {
                "200": {"description": "정상 — 단계별 통계 dict",
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean"}, "result": {"type": "object"}}
                        }}}},
                "401": {"description": "missing bearer / invalid token"},
                "403": {"description": "email mismatch"},
                "503": {"description": "cron auth not configured (env 미주입)"},
            },
        }
    }
}


def load_spec() -> dict:
    from main import app  # noqa: E402
    return app.openapi()


def resolve_ref(ref: str, spec: dict) -> tuple[str, dict]:
    if not ref.startswith("#/"):
        return ref, {}
    parts = ref.lstrip("#/").split("/")
    cur: Any = spec
    for p in parts:
        cur = cur.get(p, {}) if isinstance(cur, dict) else {}
    return parts[-1], cur


def short_type(schema: dict, spec: dict) -> str:
    if not schema:
        return ""
    if "$ref" in schema:
        name, _ = resolve_ref(schema["$ref"], spec)
        return name
    t = schema.get("type")
    fmt = schema.get("format")
    if t == "array":
        return f"array<{short_type(schema.get('items', {}), spec)}>"
    if t == "object":
        return "object"
    if "anyOf" in schema or "oneOf" in schema:
        parts = []
        for s in schema.get("anyOf") or schema.get("oneOf") or []:
            if s.get("type") == "null":
                continue
            parts.append(short_type(s, spec))
        return " | ".join(parts) if parts else "any"
    if "enum" in schema:
        vals = schema["enum"]
        if len(vals) <= 4:
            return "enum(" + ", ".join(repr(v) for v in vals) + ")"
        return f"enum({len(vals)} values)"
    if t:
        return f"{t}({fmt})" if fmt else t
    return ""


def render_schema_fields(schema: dict, spec: dict) -> list[dict]:
    if not schema:
        return []
    if "$ref" in schema:
        _, schema = resolve_ref(schema["$ref"], spec)
    if schema.get("type") == "array":
        return render_schema_fields(schema.get("items", {}), spec)
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    rows = []
    for name, p in props.items():
        rows.append({
            "name": name,
            "type": short_type(p, spec),
            "required": name in required,
            "desc": p.get("description") or p.get("title") or "",
            "default": p.get("default", ""),
        })
    return rows


CSS = r"""
:root {
  --bg: #f8fafc; --bg-elev: #ffffff; --bg-code: #0f172a;
  --fg: #0f172a; --fg-muted: #64748b; --border: #e2e8f0;
  --accent: #2563eb; --accent-soft: #dbeafe;
  --ok: #16a34a; --ok-soft: #dcfce7;
  --warn: #d97706; --warn-soft: #fef3c7;
  --no: #94a3b8; --no-soft: #f1f5f9;
  --badge-req: #ef4444;
  --shadow: 0 1px 2px rgba(15,23,42,0.04), 0 4px 12px rgba(15,23,42,0.06);
  --m-get: #16a34a; --m-get-soft: #dcfce7;
  --m-post: #2563eb; --m-post-soft: #dbeafe;
  --m-put: #d97706; --m-put-soft: #fef3c7;
  --m-delete: #dc2626; --m-delete-soft: #fee2e2;
}
[data-theme="dark"] {
  --bg: #0b1220; --bg-elev: #111a2e; --bg-code: #050a17;
  --fg: #e2e8f0; --fg-muted: #94a3b8; --border: #1e293b;
  --accent: #60a5fa; --accent-soft: #1e3a8a;
  --ok: #4ade80; --ok-soft: #14532d;
  --warn: #fbbf24; --warn-soft: #78350f;
  --no: #475569; --no-soft: #1e293b;
  --m-get: #4ade80; --m-get-soft: #14532d;
  --m-post: #60a5fa; --m-post-soft: #1e3a8a;
  --m-put: #fbbf24; --m-put-soft: #78350f;
  --m-delete: #f87171; --m-delete-soft: #7f1d1d;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Pretendard",
    "Apple SD Gothic Neo", "Noto Sans KR", Roboto, sans-serif;
  background: var(--bg); color: var(--fg); font-size: 14px; line-height: 1.55;
}
header.topbar {
  position: sticky; top: 0; z-index: 50; background: var(--bg-elev);
  border-bottom: 1px solid var(--border); padding: 12px 24px;
  display: flex; align-items: center; gap: 16px;
}
header.topbar h1 { margin: 0; font-size: 16px; font-weight: 700; }
header.topbar .sub { font-size: 12px; color: var(--fg-muted); margin-left: 4px; }
header.topbar .grow { flex: 1; }
.search {
  display: flex; align-items: center; gap: 6px;
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 6px 12px; width: 320px; max-width: 100%;
}
.search input { flex: 1; border: 0; background: transparent; outline: none; color: var(--fg); font-size: 13px; }
.theme-toggle {
  border: 1px solid var(--border); background: var(--bg-elev); color: var(--fg);
  border-radius: 8px; padding: 6px 10px; cursor: pointer; font-size: 13px;
}
main { display: grid; grid-template-columns: 280px 1fr; min-height: calc(100vh - 56px); }
nav.side {
  border-right: 1px solid var(--border); background: var(--bg-elev);
  padding: 16px 0; position: sticky; top: 56px; height: calc(100vh - 56px);
  overflow-y: auto;
}
nav.side .cat {
  padding: 4px 18px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--fg-muted); margin-top: 14px;
}
nav.side a {
  display: block; padding: 6px 18px; color: var(--fg); text-decoration: none;
  font-size: 13px; border-left: 2px solid transparent;
}
nav.side a:hover { background: var(--bg); }
nav.side a.active {
  background: var(--accent-soft); border-left-color: var(--accent);
  color: var(--accent); font-weight: 600;
}
nav.side a .method-mini {
  display: inline-block; width: 36px; font-size: 10px; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.04em; margin-right: 6px;
}
nav.side a .method-mini.get { color: var(--m-get); }
nav.side a .method-mini.post { color: var(--m-post); }
section.content { padding: 24px 32px 80px; max-width: 1100px; }
.hero {
  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px 28px; margin-bottom: 20px; box-shadow: var(--shadow);
}
.hero h2 { margin: 0 0 6px; font-size: 22px; }
.hero p { margin: 6px 0; color: var(--fg-muted); font-size: 13px; }
.basebar { display: flex; gap: 18px; flex-wrap: wrap; font-size: 12.5px; margin: 16px 0 0; }
.basebar .item { display: inline-flex; align-items: center; gap: 6px; }
.basebar .item code {
  background: var(--bg); border: 1px solid var(--border);
  padding: 2px 8px; border-radius: 4px; font-family: ui-monospace, monospace;
}
.catbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 12px 0 0; }
.cathip {
  background: var(--bg); border: 1px solid var(--border); border-radius: 999px;
  padding: 6px 14px; font-size: 12px; color: var(--fg-muted); text-decoration: none;
}
.cat-section { margin-bottom: 48px; }
.cat-header { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.cat-header h3 { margin: 0; font-size: 20px; }
.cat-header .icon { font-size: 24px; }
.cat-header .sub { color: var(--fg-muted); font-size: 13px; }
.cat-when {
  font-size: 12.5px; padding: 8px 14px; background: var(--accent-soft); color: var(--accent);
  border-radius: 8px; margin-bottom: 16px; border-left: 3px solid var(--accent);
}
[data-theme="dark"] .cat-when { color: #cbd5e1; }
.api-card {
  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 22px; margin-bottom: 14px; box-shadow: var(--shadow);
}
.api-title-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.method {
  font-size: 11px; font-weight: 700; letter-spacing: 0.04em;
  padding: 3px 10px; border-radius: 4px;
}
.method.get { background: var(--m-get-soft); color: var(--m-get); }
.method.post { background: var(--m-post-soft); color: var(--m-post); }
.method.put { background: var(--m-put-soft); color: var(--m-put); }
.method.delete { background: var(--m-delete-soft); color: var(--m-delete); }
.path-mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13.5px; font-weight: 600; }
.auth-badge {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600;
  margin-left: auto;
}
.auth-badge.public { background: var(--ok-soft); color: var(--ok); }
.auth-badge.admin { background: var(--warn-soft); color: var(--warn); }
.auth-badge.oidc { background: var(--m-post-soft); color: var(--m-post); }
.api-summary { margin: 8px 0 4px; font-size: 14.5px; font-weight: 600; }
.api-desc { color: var(--fg-muted); font-size: 13px; margin: 4px 0 12px; }
.codeblock {
  background: var(--bg-code); color: #e2e8f0; border-radius: 8px;
  padding: 12px 14px; font-family: ui-monospace, monospace;
  font-size: 12.5px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-all;
  margin: 10px 0; overflow-x: auto;
}
.codeblock .verb { color: #facc15; font-weight: 700; }
.kv-grid { display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px; font-size: 13px; margin: 10px 0; }
.kv-grid .k { color: var(--fg-muted); }
.kv-grid .v { font-family: ui-monospace, monospace; word-break: break-all; }
table.params { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 8px 0 0; }
table.params th, table.params td {
  border-bottom: 1px solid var(--border); padding: 7px 10px; text-align: left; vertical-align: top;
}
table.params th {
  font-weight: 600; font-size: 11.5px; color: var(--fg-muted);
  text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg);
}
table.params td.name { font-family: ui-monospace, monospace; font-weight: 600; white-space: nowrap; }
table.params td.type { font-family: ui-monospace, monospace; color: var(--fg-muted); font-size: 11.5px; }
table.params td.sample { font-family: ui-monospace, monospace; color: var(--fg-muted); }
.badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; margin-left: 4px; }
.badge.req { background: rgba(239,68,68,0.12); color: var(--badge-req); }
.badge.opt { background: rgba(148,163,184,0.18); color: var(--no); }
.badge.in {
  background: var(--no-soft); color: var(--no); font-weight: 600;
  margin-left: 0; margin-right: 4px;
  text-transform: uppercase; letter-spacing: 0.04em;
}
.badge.in.query { background: var(--accent-soft); color: var(--accent); }
.badge.in.path { background: var(--ok-soft); color: var(--ok); }
.badge.in.header { background: var(--warn-soft); color: var(--warn); }
details { margin: 12px 0; }
details summary {
  cursor: pointer; user-select: none; font-size: 13px; font-weight: 600;
  color: var(--accent); padding: 4px 0;
}
details[open] summary { margin-bottom: 8px; }
.hidden { display: none !important; }
.response-row {
  display: grid; grid-template-columns: 70px 1fr;
  gap: 8px 14px; padding: 6px 0; border-bottom: 1px solid var(--border);
  font-size: 12.5px;
}
.response-row .code { font-weight: 700; font-family: ui-monospace, monospace; }
.response-row .code.ok { color: var(--ok); }
.response-row .code.client { color: var(--warn); }
.response-row .code.server { color: var(--m-delete); }
@media (max-width: 880px) {
  main { grid-template-columns: 1fr; }
  nav.side { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  section.content { padding: 16px; }
  .search { width: 160px; }
}
"""

JS = r"""
(function () {
  const q = document.getElementById('q');
  const cards = document.querySelectorAll('.api-card');
  const cats = document.querySelectorAll('.cat-section');
  function applyFilter() {
    const term = q.value.trim().toLowerCase();
    cards.forEach(c => {
      if (!term) { c.classList.remove('hidden'); return; }
      const text = c.textContent.toLowerCase();
      c.classList.toggle('hidden', !text.includes(term));
    });
    cats.forEach(s => {
      const visible = s.querySelectorAll('.api-card:not(.hidden)').length;
      s.classList.toggle('hidden', term && visible === 0);
    });
  }
  q.addEventListener('input', applyFilter);
  const links = document.querySelectorAll('nav.side a[data-target]');
  const targets = Array.from(links).map(a => document.getElementById(a.dataset.target));
  function onScroll() {
    let active = null;
    const scrollY = window.scrollY + 100;
    targets.forEach((t, i) => { if (t && t.offsetTop <= scrollY) active = links[i]; });
    links.forEach(l => l.classList.toggle('active', l === active));
  }
  window.addEventListener('scroll', onScroll); onScroll();
  const tt = document.getElementById('theme');
  const saved = localStorage.getItem('theme') || 'light';
  document.documentElement.dataset.theme = saved;
  tt.textContent = saved === 'dark' ? '☀️ Light' : '🌙 Dark';
  tt.addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('theme', next);
    tt.textContent = next === 'dark' ? '☀️ Light' : '🌙 Dark';
  });
})();
"""


def category_for(path: str) -> dict:
    for c in CATEGORIES:
        if c["match"](path):
            return c
    return CATEGORIES[-1]


def slugify(method: str, path: str) -> str:
    s = path.strip("/").replace("/", "-").replace("{", "").replace("}", "")
    return f"{method.lower()}-{s}" if s else f"{method.lower()}-root"


def render_curl(method: str, path: str, params: list[dict]) -> str:
    base = PROD_BASE
    query_parts = []
    path_filled = path
    headers = []
    for p in params:
        loc = p.get("in")
        name = p["name"]
        sample = p.get("schema", {}).get("default", None)
        if sample is None:
            schema = p.get("schema", {})
            if "example" in p:
                sample = p["example"]
            elif "example" in schema:
                sample = schema["example"]
            elif "enum" in schema and schema["enum"]:
                sample = schema["enum"][0]
            elif schema.get("type") == "integer":
                sample = "10"
            elif schema.get("type") == "number":
                sample = "127.5"
            elif schema.get("type") == "string":
                sample = "value"
        sample_str = str(sample) if sample is not None else ""
        if loc == "path":
            path_filled = path_filled.replace("{" + name + "}", sample_str or name)
        elif loc == "query":
            if p.get("required") and sample_str:
                query_parts.append(f"{name}={sample_str}")
        elif loc == "header" and name.lower() != "authorization":
            headers.append(f'-H "{name}: <value>"')
    if any(p.get("in") == "header" and p["name"].lower() == "authorization" for p in params):
        headers.append('-H "Authorization: Bearer <OIDC_ID_TOKEN>"')
    qs = "&".join(query_parts)
    url = f"{base}{path_filled}"
    if qs:
        url += "?" + qs
    parts = ["curl", "-s"]
    if method.upper() != "GET":
        parts.append(f"-X {method.upper()}")
    parts.extend(headers)
    parts.append(f'"{url}"')
    return (
        '<div class="codeblock"><span class="verb">' + html.escape(method.upper())
        + "</span> " + html.escape(url)
        + "\n\n# bash\n" + html.escape(" ".join(parts))
        + "</div>"
    )


def render_params_table(params: list[dict], spec: dict) -> str:
    if not params:
        return '<p style="color:var(--fg-muted);font-size:12.5px;">정의된 파라미터 없음</p>'
    rows = []
    for p in params:
        loc = p.get("in", "")
        name = html.escape(p["name"])
        schema = p.get("schema", {})
        t = short_type(schema, spec)
        required = p.get("required", False)
        desc = p.get("description") or schema.get("title") or ""
        default = schema.get("default", "")
        if "enum" in schema:
            vals = schema["enum"]
            shown = ", ".join(repr(v) for v in vals[:6])
            if len(vals) > 6:
                shown += f", ... ({len(vals)})"
            desc = (desc + " · " if desc else "") + f"enum: {shown}"
        req_badge = '<span class="badge req">필수</span>' if required else '<span class="badge opt">선택</span>'
        in_badge = f'<span class="badge in {loc}">{loc}</span>'
        rows.append(
            f"<tr><td class='name'>{in_badge}{name}</td>"
            f"<td class='type'>{html.escape(t)}</td><td>{req_badge}</td>"
            f"<td class='sample'>{html.escape(str(default))}</td>"
            f"<td>{html.escape(desc)}</td></tr>"
        )
    return (
        "<table class='params'><thead><tr>"
        "<th>위치/이름</th><th>타입</th><th>필수</th><th>기본값</th><th>설명</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def render_response_schema(resp: dict, spec: dict) -> str:
    content = resp.get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    if not schema:
        return ""
    type_label = short_type(schema, spec)
    fields = render_schema_fields(schema, spec)
    if not fields:
        return f"<div style='font-size:12.5px;color:var(--fg-muted)'>응답 타입: <code>{html.escape(type_label)}</code></div>"
    table_rows = []
    for r in fields:
        req_badge = '<span class="badge req">필수</span>' if r["required"] else '<span class="badge opt">선택</span>'
        table_rows.append(
            f"<tr><td class='name'>{html.escape(r['name'])}</td>"
            f"<td class='type'>{html.escape(r['type'])}</td>"
            f"<td>{req_badge}</td><td>{html.escape(r['desc'])}</td></tr>"
        )
    return (
        f"<div style='font-size:12.5px;color:var(--fg-muted);margin-bottom:6px'>응답 타입: <code>{html.escape(type_label)}</code></div>"
        "<table class='params'><thead><tr>"
        "<th>필드</th><th>타입</th><th>필수</th><th>설명</th></tr></thead><tbody>"
        + "".join(table_rows) + "</tbody></table>"
    )


def render_responses(operation: dict, spec: dict) -> str:
    resps = operation.get("responses") or {}
    if not resps:
        return ""
    main_html = []
    for code, resp in resps.items():
        ci = code[0] if code else ""
        klass = "ok" if ci == "2" else ("client" if ci == "4" else ("server" if ci == "5" else "ok"))
        desc = resp.get("description") or ""
        main_html.append(
            f"<div class='response-row'>"
            f"<div class='code {klass}'>{html.escape(code)}</div>"
            f"<div>{html.escape(desc)}</div></div>"
        )
    ok_code = next((c for c in resps if c.startswith("2")), None)
    schema_html = render_response_schema(resps[ok_code], spec) if ok_code else ""
    return (
        "".join(main_html)
        + (f"<details><summary>응답 스키마</summary>{schema_html}</details>" if schema_html else "")
    )


def render_endpoint(method: str, path: str, operation: dict, spec: dict, cat: dict) -> str:
    eid = slugify(method, path)
    summary = operation.get("summary") or path
    desc = operation.get("description") or ""
    tags = operation.get("tags") or []
    params = operation.get("parameters") or []
    request_body_html = ""
    rb = operation.get("requestBody")
    if rb:
        rb_schema = rb.get("content", {}).get("application/json", {}).get("schema", {})
        rb_fields = render_schema_fields(rb_schema, spec)
        if rb_fields:
            rows = []
            for r in rb_fields:
                req_badge = '<span class="badge req">필수</span>' if r["required"] else '<span class="badge opt">선택</span>'
                rows.append(
                    f"<tr><td class='name'>{html.escape(r['name'])}</td>"
                    f"<td class='type'>{html.escape(r['type'])}</td>"
                    f"<td>{req_badge}</td><td>{html.escape(r['desc'])}</td></tr>"
                )
            request_body_html = (
                "<details><summary>요청 바디 (application/json)</summary>"
                "<table class='params'><thead><tr>"
                "<th>필드</th><th>타입</th><th>필수</th><th>설명</th></tr></thead><tbody>"
                + "".join(rows) + "</tbody></table></details>"
            )

    auth_class = cat["auth"]
    auth_label = {"public": "🌐 공개", "admin-local": "🔒 Admin (local)", "oidc": "🔑 OIDC 필요"}.get(auth_class, "")
    auth_klass = {"public": "public", "admin-local": "admin", "oidc": "oidc"}.get(auth_class, "public")

    full_url = f"{PROD_BASE}{path}"
    kv_html = (
        "<div class='kv-grid'>"
        f"<div class='k'>Method</div><div class='v'>{html.escape(method.upper())}</div>"
        f"<div class='k'>경로</div><div class='v'>{html.escape(path)}</div>"
        f"<div class='k'>운영 URL</div><div class='v'>{html.escape(full_url)}</div>"
        f"<div class='k'>로컬 URL</div><div class='v'>{html.escape(LOCAL_BASE + path)}</div>"
        f"<div class='k'>태그</div><div class='v'>{html.escape(', '.join(tags))}</div>"
        "</div>"
    )
    return f"""
<div class="api-card" id="{eid}">
  <div class="api-title-row">
    <span class="method {method.lower()}">{html.escape(method.upper())}</span>
    <span class="path-mono">{html.escape(path)}</span>
    <span class="auth-badge {auth_klass}">{auth_label}</span>
  </div>
  <div class="api-summary">{html.escape(summary)}</div>
  {f'<p class="api-desc">{html.escape(desc)}</p>' if desc else ''}
  <details open><summary>호출 정보 + 예시</summary>
    {kv_html}
    {render_curl(method, path, params)}
  </details>
  <details><summary>요청 파라미터 ({len(params)}개)</summary>
    {render_params_table(params, spec)}
  </details>
  {request_body_html}
  <details><summary>응답</summary>
    {render_responses(operation, spec)}
  </details>
</div>
"""


def build_html(spec: dict) -> str:
    endpoints_by_cat: dict[str, list[tuple]] = {c["id"]: [] for c in CATEGORIES}
    paths = dict(spec.get("paths", {}))
    for p, ops in MANUAL_PATHS.items():
        paths.setdefault(p, {}).update(ops)
    for path, methods in sorted(paths.items()):
        for method, op in methods.items():
            cat = category_for(path)
            endpoints_by_cat[cat["id"]].append((method, path, op))

    sections_html = []
    nav_links_by_cat: list[tuple[str, str, list[tuple]]] = []
    for cat in CATEGORIES:
        eps = endpoints_by_cat[cat["id"]]
        if not eps:
            continue
        cards = "".join(render_endpoint(m, p, op, spec, cat) for m, p, op in eps)
        sections_html.append(f"""
<section class="cat-section" id="cat-{cat['id']}">
  <div class="cat-header">
    <div class="icon">{cat['icon']}</div>
    <h3>{html.escape(cat['title'])}</h3>
    <div class="sub">{html.escape(cat['subtitle'])}</div>
  </div>
  <div class="cat-when"><strong>언제 쓰나요?</strong> {html.escape(cat['use_when'])}</div>
  {cards}
</section>
""")
        nav_links_by_cat.append((cat["id"], cat["title"], [(slugify(m, p), m.upper(), p) for m, p, _ in eps]))

    nav_html_parts = []
    for cid, ctitle, items in nav_links_by_cat:
        nav_html_parts.append(f"<div class='cat'>{html.escape(ctitle)}</div>")
        for eid, m, p in items:
            mlow = m.lower()
            nav_html_parts.append(
                f"<a href='#{eid}' data-target='{eid}'>"
                f"<span class='method-mini {mlow}'>{html.escape(m)}</span>"
                f"{html.escape(p.replace('/api/v1', ''))}</a>"
            )

    catbar = "".join(
        f"<a class='cathip' href='#cat-{cat['id']}'>{cat['icon']} {html.escape(cat['title'])}</a>"
        for cat in CATEGORIES if endpoints_by_cat[cat["id"]]
    )

    info = spec.get("info", {})
    return f"""<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AuctionBridge Server API 가이드</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <h1>AuctionBridge Server API <span class="sub">v{html.escape(info.get('version','0.1.0'))}</span></h1>
  <div class="grow"></div>
  <div class="search">
    <span style="color:var(--fg-muted)">🔍</span>
    <input id="q" type="search" placeholder="검색 (예: bbox, vehicle, enrich)">
  </div>
  <button id="theme" class="theme-toggle">🌙 Dark</button>
</header>
<main>
<nav class="side">{"".join(nav_html_parts)}</nav>
<section class="content">
  <div class="hero">
    <h2>이 서버가 제공하는 API</h2>
    <p>{html.escape(info.get('description',''))}</p>
    <div class="basebar">
      <span class="item">🌍 운영: <code>{PROD_BASE}</code></span>
      <span class="item">💻 로컬: <code>{LOCAL_BASE}</code></span>
      <span class="item">📋 OpenAPI: <code>{PROD_BASE}/openapi.json</code></span>
      <span class="item">📖 Swagger UI: <code>{PROD_BASE}/docs</code></span>
    </div>
    <div class="catbar">{catbar}</div>
  </div>
  {''.join(sections_html)}
</section>
</main>
<script>{JS}</script>
</body>
</html>"""


def main() -> int:
    try:
        spec = load_spec()
    except Exception as e:
        print(f"ERROR: failed to load FastAPI app — {e}", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_html(spec), encoding="utf-8")
    n_paths = len(spec.get("paths", {})) + len([p for p in MANUAL_PATHS if p not in spec.get("paths", {})])
    print(f"[server-guide] wrote {OUT} ({OUT.stat().st_size:,} bytes, {n_paths} endpoints)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
