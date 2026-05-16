"""app/docs/*.docx → docs/onbid-api-guide.html 빌드.

19개 docx에서 표/본문을 추출 → 카테고리화 → 단일 HTML 생성.
중간 파일을 만들지 않고 메모리에서만 처리한다.

직접 실행:
    .venv/Scripts/python.exe tools/build_onbid_guide.py

Pre-commit hook이 app/docs/*.docx 변경 시 자동 호출한다.
"""
from __future__ import annotations

import glob
import html
import os
import re
import sys
from pathlib import Path
from typing import Any

# 프로젝트 루트를 sys.path에 추가 (tools/에서 실행 시)
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)


# ---------------------------------------------------------------------------
# 1. docx 추출 (python-docx 사용)
# ---------------------------------------------------------------------------
def extract_docx(path: str) -> str:
    """docx → 본문 텍스트(표는 [TABLE] ... [/TABLE]로 마크업)."""
    from docx import Document

    doc = Document(path)
    out: list[str] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            texts = [n.text for n in child.iter() if n.tag.endswith("}t") and n.text]
            text = "".join(texts).strip()
            if text:
                out.append(text)
        elif tag == "tbl":
            out.append("[TABLE]")
            for row in child.iter():
                if row.tag.split("}")[-1] != "tr":
                    continue
                cells: list[str] = []
                for cell in row.iter():
                    if cell.tag.split("}")[-1] != "tc":
                        continue
                    cell_texts = [n.text for n in cell.iter() if n.tag.endswith("}t") and n.text]
                    cells.append("".join(cell_texts).strip().replace("\n", " "))
                if cells:
                    out.append(" | ".join(cells))
            out.append("[/TABLE]")
    return "\n".join(out)


def load_all_docx() -> dict[str, str]:
    """파일 prefix(01/02/.../fin) → 본문 텍스트."""
    sections: dict[str, str] = {}
    for fp in sorted(glob.glob("app/docs/*.docx")):
        body = extract_docx(fp)
        fname = os.path.basename(fp)
        m = re.search(r"_(\d{2})_", fname)
        if m:
            key = m.group(1)
        elif "금융위" in fname:
            key = "fin"
        else:
            key = fname[:5]
        sections[key] = body
    return sections


# ---------------------------------------------------------------------------
# 2. 카테고리 / 파일 매핑
# ---------------------------------------------------------------------------
CATEGORIES: list[dict] = [
    {"id": "list", "title": "물건 목록 조회",
     "subtitle": "현재 입찰중·예정 매물을 자산 유형별로 검색·필터링",
     "icon": "📋",
     "use_when": "지역·가격·면적 등 조건으로 매물 리스트를 가져오고 싶을 때",
     "files": ["01", "02", "03"]},
    {"id": "detail", "title": "물건 상세 조회",
     "subtitle": "특정 물건의 사진·감정평가서·면적·권리관계 등 모든 디테일",
     "icon": "🔎",
     "use_when": "목록에서 본 cltrMngNo + pbctCdtnNo로 해당 물건의 전체 정보를 받아올 때",
     "files": ["04", "05"]},
    {"id": "bid", "title": "입찰 정보",
     "subtitle": "회차별 예정가격·보증금·입찰일정", "icon": "🎯",
     "use_when": "한 물건의 특정 회차에 대해 보증금·입찰 가능 시각 등을 알아야 할 때",
     "files": ["07"]},
    {"id": "bid-result", "title": "입찰 결과",
     "subtitle": "유찰·낙찰 결과 + 낙찰가·응찰 인원", "icon": "🏆",
     "use_when": "이미 입찰이 끝난 매물의 결과(유찰/낙찰), 낙찰가, 응찰자 수를 확인할 때",
     "files": ["08", "09"]},
    {"id": "announce", "title": "공고 기반 조회",
     "subtitle": "공매공고 단위 조회 — 한 공고에 묶인 다수 물건 처리",
     "icon": "📢",
     "use_when": "특정 기관의 공고를 중심으로 매물·결과를 묶어 보고 싶을 때",
     "files": ["10", "11", "13", "14", "15"]},
    {"id": "gov", "title": "정부재산 목록",
     "subtitle": "국유·공유·친일귀속재산 별도 카탈로그", "icon": "🏛️",
     "use_when": "압류재산이 아닌 국가/공공기관 재산을 조회할 때",
     "files": ["20", "21", "22"]},
    {"id": "meta", "title": "코드 및 주소",
     "subtitle": "용도분류·재산유형·주소 PNU 등 메타데이터", "icon": "🗂️",
     "use_when": "응답의 코드 값이 무엇을 의미하는지 모르거나, 주소 코드를 변환할 때",
     "files": ["24"]},
    {"id": "stats", "title": "지역별 통계",
     "subtitle": "지역·시도 단위 입찰 통계", "icon": "📊",
     "use_when": "특정 지역의 매물 추세나 누적 입찰 통계를 보고 싶을 때",
     "files": ["25"]},
    {"id": "finance", "title": "금융위 국가자산정보",
     "subtitle": "별도 그룹 — 금융위원회 국가자산정보 OpenAPI", "icon": "🏦",
     "use_when": "금융위 산하 국가자산 정보를 조회할 때",
     "files": ["fin"]},
]

FILE_INDEX: dict[str, dict] = {
    "01": {"id": "rlst-list", "title": "부동산 물건목록"},
    "02": {"id": "mvast-list", "title": "동산 물건목록"},
    "03": {"id": "car-list", "title": "차량 물건목록"},
    "04": {"id": "rlst-detail", "title": "부동산 물건상세"},
    "05": {"id": "mvast-detail", "title": "동산 물건상세"},
    "07": {"id": "bid-info", "title": "물건상세 입찰정보"},
    "08": {"id": "bid-result-list", "title": "물건 입찰결과목록"},
    "09": {"id": "bid-result-detail", "title": "물건 입찰결과상세"},
    "10": {"id": "pbanc-list", "title": "공고목록"},
    "11": {"id": "pbanc-detail", "title": "공고상세"},
    "13": {"id": "pbanc-cltr", "title": "공고상세 물건정보"},
    "14": {"id": "pbanc-result-list", "title": "공고 입찰결과목록"},
    "15": {"id": "pbanc-result-detail", "title": "공고 입찰결과상세"},
    "20": {"id": "gov-state", "title": "정부재산 — 국유일반재산"},
    "21": {"id": "gov-public", "title": "정부재산 — 공유일반재산"},
    "22": {"id": "gov-japan", "title": "정부재산 — 친일귀속재산"},
    "24": {"id": "code-addr", "title": "코드 및 주소"},
    "25": {"id": "region-stats", "title": "지역별 입찰 통계"},
    "fin": {"id": "finance-asset", "title": "금융위 국가자산정보"},
}

# 현재 코드/스케줄러 사용 현황 — 매트릭스 표 + 카드 배지에 함께 사용
USAGE_STATUS: dict[str, dict] = {
    "01":  {"code": ("y", ""),             "scheduler": ("y", "")},
    "02":  {"code": ("y", ""),             "scheduler": ("y", "")},
    "03":  {"code": ("y", ""),             "scheduler": ("y", "")},
    "04":  {"code": ("y", "이미지 enrich"), "scheduler": ("p", "off 기본")},
    "05":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "07":  {"code": ("y", "클라이언트만"),  "scheduler": ("n", "")},
    "08":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "09":  {"code": ("y", ""),             "scheduler": ("y", "")},
    "10":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "11":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "13":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "14":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "15":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "20":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "21":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "22":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "24":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "25":  {"code": ("n", ""),             "scheduler": ("n", "")},
    "fin": {"code": ("n", ""),             "scheduler": ("n", "")},
}

USAGE_ROWS: list[tuple] = [
    ("01", "부동산 목록"),
    ("02", "동산 목록"),
    ("03", "차량 목록"),
    ("04", "부동산 상세"),
    ("05", "동산 상세"),
    ("07", "물건상세 입찰정보"),
    ("08", "입찰결과 목록"),
    ("09", "입찰결과 상세"),
    (["10", "11", "13"], "공고 목록/상세/물건정보"),
    (["14", "15"], "공고 입찰결과 목/상"),
    (["20", "21", "22"], "정부재산목록 (국유/공유/친일)"),
    ("24", "코드 및 주소 마스터"),
    ("25", "지역별 입찰 통계"),
]

STATUS_GLYPH = {"y": "✓", "p": "△", "n": "✗"}
STATUS_KLASS = {"y": "ok", "p": "warn", "n": "no"}


# ---------------------------------------------------------------------------
# 3. docx 텍스트 정규화
# ---------------------------------------------------------------------------
def extract_tables(body: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    for m in re.finditer(r"\[TABLE\]\n(.*?)\[/TABLE\]", body, re.DOTALL):
        block = m.group(1).strip("\n")
        rows: list[list[str]] = []
        for line in block.split("\n"):
            if not line.strip():
                continue
            cells = [c.strip() for c in line.split("|")]
            rows.append(cells)
        if rows:
            out.append(rows)
    return out


def normalize_guide(body: str) -> dict:
    tables = extract_tables(body)
    info = {
        "service_name_ko": "", "service_name_en": "", "service_id": "",
        "base_url": "", "version": "", "description": "",
        "operations": [], "request_fields": [], "response_fields": [],
    }
    LABEL_MAP = {
        "서비스ID": "service_id",
        "서비스명(국문)": "service_name_ko",
        "서비스명(영문)": "service_name_en",
        "서비스설명": "description",
        "서비스버전": "version",
    }
    for tbl in tables:
        for row in tbl:
            for i in range(len(row) - 1):
                label = row[i].strip()
                value = row[i + 1].strip() if i + 1 < len(row) else ""
                if label in LABEL_MAP and value and not info[LABEL_MAP[label]]:
                    info[LABEL_MAP[label]] = value
                if label == "운영환경" and value.startswith("http") and not info["base_url"]:
                    info["base_url"] = value

    op_callbacks: list[str] = []
    op_descs: list[str] = []
    param_tables: list[list[list[str]]] = []

    for tbl in tables[1:]:
        if not tbl:
            continue
        head_str = " ".join(tbl[0])
        if "일련번호" in head_str:
            for row in tbl[1:]:
                if len(row) >= 3:
                    op_callbacks.append(row[2])
        elif "오퍼레이션번호" in head_str or "오퍼레이션유형" in head_str:
            for row in tbl:
                if any("Call Back" in c for c in row):
                    for c in row:
                        if c.startswith("[") or "/get" in c or c.startswith("http"):
                            op_callbacks.append(c)
                if any("오퍼레이션설명" in c for c in row):
                    for i, c in enumerate(row):
                        if c == "오퍼레이션설명" and i + 1 < len(row):
                            op_descs.append(row[i + 1])
        elif "항목명(영문)" in head_str:
            param_tables.append(tbl)

    info["operations"] = list(zip(op_callbacks, op_descs + [""] * len(op_callbacks)))
    if len(param_tables) >= 1:
        info["request_fields"] = parse_param_rows(param_tables[0])
    if len(param_tables) >= 2:
        info["response_fields"] = parse_param_rows(param_tables[1])
    return info


def parse_param_rows(table: list[list[str]]) -> list[dict]:
    out: list[dict] = []
    for row in table[1:]:
        cells = [c.strip() for c in row]
        while cells and cells[0] == "":
            cells.pop(0)
        if len(cells) < 2 or not cells[0]:
            continue
        out.append({
            "name": cells[0],
            "name_ko": cells[1] if len(cells) > 1 else "",
            "size": cells[2] if len(cells) > 2 else "",
            "required": (cells[3].strip() == "1") if len(cells) > 3 else False,
            "sample": cells[4] if len(cells) > 4 else "",
            "desc": cells[5] if len(cells) > 5 else "",
        })
    return out


# ---------------------------------------------------------------------------
# 4. HTML 빌드
# ---------------------------------------------------------------------------
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
}
[data-theme="dark"] {
  --bg: #0b1220; --bg-elev: #111a2e; --bg-code: #050a17;
  --fg: #e2e8f0; --fg-muted: #94a3b8; --border: #1e293b;
  --accent: #60a5fa; --accent-soft: #1e3a8a;
  --ok: #4ade80; --ok-soft: #14532d;
  --warn: #fbbf24; --warn-soft: #78350f;
  --no: #475569; --no-soft: #1e293b;
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
.search input {
  flex: 1; border: 0; background: transparent; outline: none;
  color: var(--fg); font-size: 13px;
}
.theme-toggle {
  border: 1px solid var(--border); background: var(--bg-elev); color: var(--fg);
  border-radius: 8px; padding: 6px 10px; cursor: pointer; font-size: 13px;
}
.theme-toggle:hover { background: var(--bg); }
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
nav.side a.special { color: var(--accent); font-weight: 600; }
section.content { padding: 24px 32px 80px; max-width: 1100px; }
.hero {
  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
  padding: 24px 28px; margin-bottom: 20px; box-shadow: var(--shadow);
}
.hero h2 { margin: 0 0 6px; font-size: 22px; }
.hero p { margin: 6px 0; color: var(--fg-muted); font-size: 13px; }
.catbar { display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 0; }
.cathip {
  background: var(--bg); border: 1px solid var(--border); border-radius: 999px;
  padding: 6px 14px; font-size: 12px; color: var(--fg-muted); text-decoration: none;
}
.cathip:hover { color: var(--fg); border-color: var(--fg-muted); }

.matrix-card {
  background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px 24px; margin-bottom: 28px; box-shadow: var(--shadow);
}
.matrix-card h3 { margin: 0 0 4px; font-size: 17px; }
.matrix-card .sub { color: var(--fg-muted); font-size: 13px; margin-bottom: 14px; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 4px 0 16px; font-size: 12.5px; }
.legend .item { display: inline-flex; align-items: center; gap: 6px; color: var(--fg-muted); }
.legend .glyph { font-weight: 700; font-size: 13px; }
.legend .glyph.ok { color: var(--ok); }
.legend .glyph.warn { color: var(--warn); }
.legend .glyph.no { color: var(--no); }
table.matrix { width: 100%; border-collapse: collapse; font-size: 13px; }
table.matrix th, table.matrix td {
  border-bottom: 1px solid var(--border); padding: 9px 10px; text-align: left; vertical-align: top;
}
table.matrix th {
  font-weight: 600; font-size: 11.5px; color: var(--fg-muted);
  text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg);
}
table.matrix td.num { font-family: ui-monospace, monospace; color: var(--fg-muted); white-space: nowrap; }
table.matrix td.svc a { color: var(--fg); text-decoration: none; font-weight: 500; }
table.matrix td.svc a:hover { color: var(--accent); }
.cell-glyph {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px; border-radius: 6px; font-size: 12.5px; font-weight: 600;
}
.cell-glyph.ok { background: var(--ok-soft); color: var(--ok); }
.cell-glyph.warn { background: var(--warn-soft); color: var(--warn); }
.cell-glyph.no { background: var(--no-soft); color: var(--no); }
.note { font-size: 11.5px; color: var(--fg-muted); margin-left: 8px; }

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
.api-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.api-title h4 { margin: 0; font-size: 16px; }
.api-title .pill {
  background: var(--accent-soft); color: var(--accent);
  font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
}
.usage-badges { display: inline-flex; gap: 6px; margin-left: auto; }
.usage-badge {
  font-size: 11px; padding: 2px 8px; border-radius: 4px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 4px;
}
.usage-badge.ok { background: var(--ok-soft); color: var(--ok); }
.usage-badge.warn { background: var(--warn-soft); color: var(--warn); }
.usage-badge.no { background: var(--no-soft); color: var(--no); }
.api-desc { color: var(--fg-muted); font-size: 13px; margin: 6px 0 12px; }
.kv-grid {
  display: grid; grid-template-columns: 130px 1fr; gap: 4px 12px;
  font-size: 13px; margin: 10px 0;
}
.kv-grid .k { color: var(--fg-muted); }
.kv-grid .v { font-family: ui-monospace, SFMono-Regular, "Menlo", monospace; word-break: break-all; }
.codeblock {
  background: var(--bg-code); color: #e2e8f0; border-radius: 8px;
  padding: 12px 14px; font-family: ui-monospace, monospace;
  font-size: 12.5px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-all;
  margin: 10px 0; overflow-x: auto;
}
.codeblock .method { color: #facc15; font-weight: 700; }
table.params { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 8px 0 0; }
table.params th, table.params td {
  border-bottom: 1px solid var(--border); padding: 7px 10px; text-align: left; vertical-align: top;
}
table.params th {
  font-weight: 600; font-size: 11.5px; color: var(--fg-muted);
  text-transform: uppercase; letter-spacing: 0.04em; background: var(--bg);
}
table.params td.name { font-family: ui-monospace, monospace; font-weight: 600; white-space: nowrap; }
table.params td.sample {
  font-family: ui-monospace, monospace; color: var(--fg-muted);
  max-width: 260px; word-break: break-all;
}
.badge { display: inline-block; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; margin-left: 4px; }
.badge.req { background: rgba(239,68,68,0.12); color: var(--badge-req); }
.badge.opt { background: rgba(148,163,184,0.18); color: var(--no); }
details { margin: 12px 0; }
details summary {
  cursor: pointer; user-select: none; font-size: 13px; font-weight: 600;
  color: var(--accent); padding: 4px 0;
}
details[open] summary { margin-bottom: 8px; }
.hidden { display: none !important; }
@media (max-width: 880px) {
  main { grid-template-columns: 1fr; }
  nav.side { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--border); }
  section.content { padding: 16px; }
  .search { width: 160px; }
  .api-title .usage-badges { margin-left: 0; }
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


def fmt_url(base_url: str, operation: str) -> str:
    if not base_url:
        return ""
    if not operation:
        return base_url
    op = operation.replace("[서비스URL]", "").lstrip("/").strip()
    if not op:
        return base_url
    if base_url.rstrip("/").endswith("2") and not op.endswith("2"):
        op += "2"
    return f"{base_url.rstrip('/')}/{op}"


def fmt_operation(base_url: str, operation: str) -> str:
    if not operation:
        return ""
    op = operation.replace("[서비스URL]", "").lstrip("/").strip()
    if base_url.rstrip("/").endswith("2") and op and not op.endswith("2"):
        op += "2"
    return op


def render_param_table(rows: list[dict], *, is_response: bool) -> str:
    if not rows:
        return '<p style="color:var(--fg-muted);font-size:12.5px;">정의된 파라미터 없음</p>'
    head = "<table class='params'><thead><tr><th>이름</th><th>국문</th><th>타입</th>"
    if not is_response:
        head += "<th>필수</th>"
    head += "<th>샘플</th><th>설명</th></tr></thead><tbody>"
    body = []
    for r in rows:
        name = html.escape(r["name"])
        ko = html.escape(r["name_ko"])
        size = html.escape(r["size"])
        sample = html.escape(r["sample"])
        desc = html.escape(r["desc"])
        req_badge = ""
        if not is_response:
            req_badge = (
                '<span class="badge req">필수</span>' if r["required"]
                else '<span class="badge opt">선택</span>'
            )
        line = f"<tr><td class='name'>{name}</td><td>{ko}</td><td>{size}</td>"
        if not is_response:
            line += f"<td>{req_badge}</td>"
        line += f"<td class='sample'>{sample}</td><td>{desc}</td></tr>"
        body.append(line)
    return head + "\n".join(body) + "</tbody></table>"


def render_curl(base_url: str, operation: str, request_fields: list[dict]) -> str:
    full = fmt_url(base_url, operation)
    if not full:
        return ""
    qparts = []
    for r in request_fields:
        if r["required"] and r["sample"]:
            qparts.append(f'{r["name"]}={r["sample"]}')
    qs = "&".join(qparts)
    url = f"{full}?{qs}" if qs else full
    return (
        f'<div class="codeblock"><span class="method">GET</span> {html.escape(url)}</div>'
    )


def usage_badges_html(file_key: str) -> str:
    status = USAGE_STATUS.get(file_key)
    if not status:
        return ""
    parts = []
    for label, key in (("코드", "code"), ("스케줄러", "scheduler")):
        s, note = status[key]
        glyph = STATUS_GLYPH[s]
        klass = STATUS_KLASS[s]
        title = f"{label}: {glyph}"
        if note:
            title += f" ({note})"
        parts.append(
            f'<span class="usage-badge {klass}" title="{html.escape(title)}">'
            f'{glyph} {label}</span>'
        )
    return f'<span class="usage-badges">{"".join(parts)}</span>'


def render_api(meta: dict, info: dict, file_key: str) -> str:
    first_op = info["operations"][0][0] if info["operations"] else ""
    full_url = fmt_url(info["base_url"], first_op)
    op_name = fmt_operation(info["base_url"], first_op)
    kv_items = [
        ("서비스 ID", info["service_id"]),
        ("국문명", info["service_name_ko"]),
        ("영문명", info["service_name_en"]),
        ("Base URL", info["base_url"]),
        ("오퍼레이션", op_name),
        ("Full URL", full_url),
        ("버전", info["version"]),
    ]
    kv_html = "<div class='kv-grid'>"
    for k, v in kv_items:
        if not v:
            continue
        kv_html += f"<div class='k'>{html.escape(k)}</div><div class='v'>{html.escape(v)}</div>"
    kv_html += "</div>"
    curl = render_curl(info["base_url"], first_op, info["request_fields"])
    req_table = render_param_table(info["request_fields"], is_response=False)
    res_table = render_param_table(info["response_fields"], is_response=True)
    pill = info["service_name_en"] or info["service_id"]
    return f"""
<div class="api-card" id="{meta['id']}">
  <div class="api-title">
    <h4>{html.escape(meta['title'])}</h4>
    <span class="pill">{html.escape(pill)}</span>
    {usage_badges_html(file_key)}
  </div>
  <p class="api-desc">{html.escape(info['description'])}</p>
  <details open><summary>호출 정보</summary>
    {kv_html}
    {curl}
  </details>
  <details><summary>요청 파라미터 ({len(info['request_fields'])}개)</summary>
    {req_table}
  </details>
  <details><summary>응답 필드 ({len(info['response_fields'])}개)</summary>
    {res_table}
  </details>
</div>
"""


def render_category(cat: dict, parsed: dict[str, dict]) -> tuple[str, list[tuple[str, str]]]:
    cards = []
    nav_links = []
    for fkey in cat["files"]:
        if fkey not in FILE_INDEX or fkey not in parsed:
            continue
        meta = FILE_INDEX[fkey]
        info = parsed[fkey]
        cards.append(render_api(meta, info, fkey))
        nav_links.append((meta["id"], meta["title"]))
    if not cards:
        return "", []
    return f"""
<section class="cat-section" id="cat-{cat['id']}">
  <div class="cat-header">
    <div class="icon">{cat['icon']}</div>
    <h3>{html.escape(cat['title'])}</h3>
    <div class="sub">{html.escape(cat['subtitle'])}</div>
  </div>
  <div class="cat-when"><strong>언제 쓰나요?</strong> {html.escape(cat['use_when'])}</div>
  {''.join(cards)}
</section>
""", nav_links


def render_nav(category_links: list[tuple[str, str, list[tuple[str, str]]]]) -> str:
    out = ["<a class='special' href='#usage-matrix' data-target='usage-matrix'>📌 우리 서비스 사용 현황</a>"]
    for cat_id, cat_title, links in category_links:
        out.append(f"<div class='cat'>{html.escape(cat_title)}</div>")
        for aid, atitle in links:
            out.append(f"<a href='#{aid}' data-target='{aid}'>{html.escape(atitle)}</a>")
    return "\n".join(out)


def _cell(status: str, note: str) -> str:
    glyph = STATUS_GLYPH[status]
    klass = STATUS_KLASS[status]
    inner = f'<span class="cell-glyph {klass}">{glyph}</span>'
    if note:
        inner += f'<span class="note">{html.escape(note)}</span>'
    return f"<td class='status'>{inner}</td>"


def render_usage_matrix() -> str:
    rows_html = []
    for row in USAGE_ROWS:
        file_keys = row[0] if isinstance(row[0], list) else [row[0]]
        label = row[1]
        primary = file_keys[0]
        status = USAGE_STATUS.get(primary)
        if not status:
            continue
        code_s, code_note = status["code"]
        sch_s, sch_note = status["scheduler"]
        num_str = "/".join(file_keys) if len(file_keys) > 1 else file_keys[0]
        link_target = FILE_INDEX[primary]["id"] if primary in FILE_INDEX else ""
        svc_cell = (
            f"<a href='#{link_target}'>{html.escape(label)}</a>" if link_target
            else html.escape(label)
        )
        rows_html.append(
            f"<tr><td class='num'>{html.escape(num_str)}</td>"
            f"<td class='svc'>{svc_cell}</td>"
            f"{_cell(code_s, code_note)}{_cell(sch_s, sch_note)}</tr>"
        )
    legend = """
<div class="legend">
  <span class="item"><span class="glyph ok">✓</span> 사용 중</span>
  <span class="item"><span class="glyph warn">△</span> 부분 사용 / 조건부</span>
  <span class="item"><span class="glyph no">✗</span> 미사용</span>
</div>
"""
    return f"""
<div class="matrix-card" id="usage-matrix">
  <h3>📌 우리 서비스에서의 사용 현황</h3>
  <div class="sub">아래는 <code>auction-bridge</code>가 현재 어떤 Onbid OpenAPI를 코드 레벨로 호출하고 있고, 데일리 cron 스케줄러가 어떤 것을 자동 수집하고 있는지의 매트릭스입니다. 서비스명을 클릭하면 해당 API 상세로 이동합니다.</div>
  {legend}
  <table class="matrix">
    <thead><tr><th style="width:90px">#</th><th>서비스</th><th style="width:160px">코드 사용</th><th style="width:160px">스케줄러</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
</div>
"""


def build_html(parsed: dict[str, dict]) -> str:
    category_links: list[tuple[str, str, list[tuple[str, str]]]] = []
    sections_html = []
    for cat in CATEGORIES:
        cat_html, nav_links = render_category(cat, parsed)
        if cat_html:
            sections_html.append(cat_html)
            category_links.append((cat["id"], cat["title"], nav_links))
    catbar = "".join(
        f"<a class='cathip' href='#cat-{cat['id']}'>{cat['icon']} {html.escape(cat['title'])}</a>"
        for cat in CATEGORIES if any(f in parsed for f in cat["files"])
    )
    return f"""<!DOCTYPE html>
<html lang="ko" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>온비드 OpenAPI 가이드 — 카테고리별 요약</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <h1>온비드 OpenAPI 가이드 <span class="sub">차세대 B010003 / 금융위 국가자산정보</span></h1>
  <div class="grow"></div>
  <div class="search">
    <span style="color:var(--fg-muted)">🔍</span>
    <input id="q" type="search" placeholder="검색 (예: 입찰결과, prptDivCd, 사진)">
  </div>
  <button id="theme" class="theme-toggle">🌙 Dark</button>
</header>
<main>
<nav class="side">{render_nav(category_links)}</nav>
<section class="content">
  <div class="hero">
    <h2>어떤 정보를 알고 싶으신가요?</h2>
    <p>왼쪽 사이드바에서 카테고리를 고르거나, 아래 빠른 진입점에서 원하는 영역으로 이동하세요. 각 API 카드는 <strong>호출 정보 → 요청 파라미터 → 응답 필드</strong> 순서로 펼쳐볼 수 있습니다.</p>
    <div class="catbar">{catbar}</div>
  </div>
  {render_usage_matrix()}
  {''.join(sections_html)}
</section>
</main>
<script>{JS}</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
OUT = Path("docs/onbid-api-guide.html")


def main() -> int:
    sections = load_all_docx()
    if not sections:
        print("ERROR: no docx files found in app/docs/", file=sys.stderr)
        return 1
    parsed = {key: normalize_guide(body) for key, body in sections.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_html(parsed), encoding="utf-8")
    print(f"[onbid-guide] wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(parsed)} guides)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
