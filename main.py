# -*- coding: utf-8 -*-
import datetime
import io
import os
import re
import sqlite3
import tempfile
import zipfile

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from hwp_daebipyo import extract_daebipyo
from hwpx_utils import fill_hwpx_template

app = FastAPI(title="국회bot API")

DB_PATH = os.path.join(os.path.dirname(__file__), "usage.db")


def _init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ts       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                ip       TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                bill_cnt INTEGER NOT NULL DEFAULT 1
            )
        """)


_init_db()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host


def _log_usage(ip: str, endpoint: str, bill_cnt: int):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO usage_log (ip, endpoint, bill_cnt) VALUES (?, ?, ?)",
            (ip, endpoint, bill_cnt),
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "재료파일_검토보고서.hwpx")
REPORT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "재료파일_심사보고서.hwpx")
API_BASE = "https://open.assembly.go.kr/portal/openapi/"
BILL_PAGE_BASE = "https://pal.assembly.go.kr/napal/lgsltpa/lgsltpaDone/view.do?lgsltPaId="
FILE_GATE = "https://likms.assembly.go.kr/filegate/servlet/FileGate?bookId="
API_KEY = "?KEY=" + os.environ.get("ASSEMBLY_API_KEY", "")


class Options(BaseModel):
    hoe_cha: str = "430"        # 제 N 회국회
    hoe_gu: str = "임시회"       # 임시회 / 정기회
    cha: str = "1"              # 제 N 차 위원회
    chief_type: str = "수석전문위원"  # 수석전문위원 / 전문위원
    chief_name: str = "홍길동"
    tel_ext: str = "5000"       # 02-6788-XXXX


class GenerateRequest(BaseModel):
    bill_numbers: list[str]
    options: Options = Options()


def _format_date(date_str: str) -> str:
    """'2021-05-03' → '2021. 5. 3.'"""
    if not date_str or date_str.startswith("0000"):
        return ""
    d = date_str.replace("-", ". ")
    if len(d) >= 6 and d[-6] == "0":
        d = d[:-6] + d[-5:]
    if len(d) >= 2 and d[-2] == "0":
        d = d[:-2] + d[-1:]
    return d + "."


def _parse_proposal(text: str) -> dict:
    """제안이유/주요내용 텍스트 → 나/다/라 제목·내용 딕셔너리."""
    text = (
        text.replace("？", "·")
            .replace("\x00", "")
            .strip()
            .replace("\n\n", "\n")
            .replace("\n", "\r\n")
    )
    result = {k: "" for k in ["na_title", "na_content", "da_title", "da_content", "ra_title", "ra_content"]}

    if "제안이유 및 주요내용" in text:
        result["na_title"] = "나. 제안이유 및 주요내용"
        body = text[14:]
        if "참고사항" in body:
            parts = re.split("참고사항", body, maxsplit=1)
            result["na_content"] = "  " + parts[0].strip()
            result["da_title"] = "다. 참고사항"
            result["da_content"] = "  " + parts[1].strip()
        else:
            result["na_content"] = "  " + body.strip()
    else:
        parts = re.split("주요내용|참고사항", text)
        if len(parts) >= 2:
            result["na_title"] = "나. 제안이유"
            result["na_content"] = "  " + parts[0].replace("제안이유", "").strip()
            result["da_title"] = "다. 주요내용"
            result["da_content"] = parts[1].strip()
        if len(parts) >= 3:
            result["ra_title"] = "라. 참고사항"
            result["ra_content"] = "  " + parts[2].strip()

    return result


def process_bill(bill_number: str, opts: Options) -> tuple[bytes, bytes | None, str]:
    """
    의안번호 하나를 처리하여 (검토보고서 hwpx, 의안원문 hwp|None, 법안명) 반환.
    """
    str_no = str(bill_number)
    short_no = str_no[2:].lstrip("0")

    # ── 1. 열린국회정보 API: 기본정보 ──────────────────────────────
    url = f"{API_BASE}ALLBILL/{API_KEY}&AGE={short_no}&BILL_NO={str_no}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "xml")

    bill_name     = soup.find("BILL_NM").text
    proposer_kind = soup.find("PPSR_KND").text
    proposer      = soup.find("PPSR_NM").text
    propose_dt    = soup.find("PPSL_DT").text
    committee_dt  = soup.find("JRCMIT_CMMT_DT").text or "0000-00-00"
    comm_han      = soup.find("JRCMIT_NM").text
    bill_id       = soup.find("BILL_ID").text

    # ── 2. 입법예고 페이지: 의안원문 다운로드 + 제안이유 ─────────────
    resp2 = requests.get(BILL_PAGE_BASE + bill_id, timeout=10)
    soup2 = BeautifulSoup(resp2.text, "html.parser")

    hwp_bytes = None
    proposal_text = ""
    try:
        href = soup2.select_one("a.attach_file")["href"]
        book_id = href.split("bookId=")[1].split("&")[0]
        hwp_resp = requests.get(f"{FILE_GATE}{book_id}&type=0", timeout=15)
        hwp_bytes = hwp_resp.content
    except Exception:
        pass

    try:
        proposal_text = soup2.select_one("div.desc").text
    except Exception:
        pass

    # ── 3. 필드 값 계산 ────────────────────────────────────────────
    if "의원" in proposer:
        proposer_name = proposer[:proposer.find("의원") + 2]
    else:
        proposer_name = proposer

    if proposer_kind == "의원":
        jechul  = f"{proposer_name} 대표발의(의안번호 제{short_no}호)"
        jechul2 = f"{proposer_name} 대표발의안(의안번호 제{short_no}호)"
        jechul3 = f"{proposer_name}안"
    else:
        jechul  = f"정부제출(의안번호 제{short_no}호)"
        jechul2 = f"정부안(의안번호 제{short_no}호)"
        jechul3 = "정부안"

    today = datetime.datetime.today()
    proposal = _parse_proposal(proposal_text)

    fields = {
        "{{회기1}}":         f"제{opts.hoe_cha}회국회({opts.hoe_gu})",
        "{{회기2}}":         f"제{opts.cha}차{comm_han}",
        "{{법안명}}":        bill_name,
        "{{제출정보}}":      jechul,
        "{{연월}}":          f"{today.year}. {today.month}.",
        "{{위원회명}}":      comm_han,
        "{{전문위원}}":      f"{opts.chief_type} {opts.chief_name}",
        "{{의원안}}":        jechul2,
        "{{의원안(짧은)}}":  jechul3,
        "{{제안자}}":        proposer,
        "{{제안일}}":        _format_date(propose_dt),
        "{{회부일}}":        _format_date(committee_dt),
        "{{나. 제목}}":      proposal["na_title"],
        "{{나. 내용}}":      proposal["na_content"],
        "{{다. 제목}}":      proposal["da_title"],
        "{{다. 내용}}":      proposal["da_content"],
        "{{라. 제목}}":      proposal["ra_title"],
        "{{라. 내용}}":      proposal["ra_content"],
        "{{내선번호}}":      opts.tel_ext,
    }

    # ── 4. 신구조문대비표 추출 (일부개정안만) ──────────────────────────
    daebipyo = None
    if hwp_bytes and "일부개정" in bill_name:
        try:
            daebipyo = extract_daebipyo(hwp_bytes)
        except Exception:
            pass  # 추출 실패해도 나머지 보고서는 생성

    # ── 5. 템플릿 채우기 ───────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        fill_hwpx_template(TEMPLATE_PATH, tmp_path, fields, daebipyo=daebipyo)
        with open(tmp_path, "rb") as f:
            hwpx_bytes = f.read()
    finally:
        os.unlink(tmp_path)

    return hwpx_bytes, hwp_bytes, bill_name


def _format_judge_history(names: list, dates: list, results: list) -> str:
    """BILLJUDGECONF API 결과 → 심사경과 텍스트."""
    lines = []
    for name, date, result in zip(names, dates, results):
        try:
            y, m, d = date.split("-")
            formatted = f"{int(y)}. {int(m)}. {int(d)}."
        except Exception:
            formatted = date
        lines.append(f"{name}({formatted}) - {result}")
    return "\n".join(lines)


class ReportRequest(BaseModel):
    bill_numbers: list[str]


def process_bill_report(bill_number: str) -> tuple[bytes, str]:
    """의안번호 하나를 처리하여 (심사보고서 hwpx, 법안명) 반환."""
    str_no = str(bill_number)
    short_no = str_no[2:].lstrip("0")

    # ── 1. ALLBILL API: 기본정보 ────────────────────────────────────
    url = f"{API_BASE}ALLBILL/{API_KEY}&AGE={short_no}&BILL_NO={str_no}"
    resp = requests.get(url, timeout=10)
    soup = BeautifulSoup(resp.text, "xml")

    bill_name = soup.find("BILL_NM").text
    proposer  = soup.find("PPSR_NM").text
    comm_han  = soup.find("JRCMIT_NM").text
    bill_id   = soup.find("BILL_ID").text

    # ── 2. BILLJUDGECONF API: 위원회 심사 이력 ──────────────────────
    url2 = f"{API_BASE}BILLJUDGECONF/{API_KEY}&Type=xml&pIndex=1&BILL_ID={bill_id}"
    resp2 = requests.get(url2, timeout=10)
    soup2 = BeautifulSoup(resp2.text, "xml")

    names_list   = [t.text.strip() for t in soup2.find_all("JRCMIT_CONF_NM")]
    dates_list   = [t.text.strip() for t in soup2.find_all("JRCMIT_CONF_DT")]
    results_list = [t.text.strip() for t in soup2.find_all("JRCMIT_CONF_RSLT")]

    # ── 3. 입법예고 페이지: 제안이유 및 주요내용 ───────────────────────
    resp_page = requests.get(BILL_PAGE_BASE + bill_id, timeout=10)
    soup_page = BeautifulSoup(resp_page.text, "html.parser")
    try:
        summary = soup_page.select_one("div.desc").text.strip()
        summary = (
            summary.replace("？", "·")
                   .replace("\x00", "")
                   .replace("\r\n", "\n")
                   .replace("\r", "\n")
        )
        summary = re.sub(r"\n{3,}", "\n\n", summary)
    except Exception:
        summary = ""

    today = datetime.datetime.today()

    fields = {
        "{{법안명}}":         bill_name,
        "{{연월}}":           f"{today.year}. {today.month}.",
        "{{위원회명}}":       comm_han,
        "{{심사경과}}":       _format_judge_history(names_list, dates_list, results_list),
        "{{proposer}}":       proposer.split(" ")[0],
        "{{제안설명의요지}}": summary,
    }

    with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        fill_hwpx_template(REPORT_TEMPLATE_PATH, tmp_path, fields)
        with open(tmp_path, "rb") as f:
            hwpx_bytes = f.read()
    finally:
        os.unlink(tmp_path)

    return hwpx_bytes, bill_name


# ── 엔드포인트 ──────────────────────────────────────────────────────

@app.post("/generate")
async def generate(req: GenerateRequest, request: Request):
    """
    의안번호 목록을 받아 검토보고서(.hwpx) + 의안원문(.hwp)을 zip으로 반환.
    """
    if not req.bill_numbers:
        raise HTTPException(status_code=400, detail="의안번호를 입력하세요.")

    zip_buf = io.BytesIO()
    errors = []

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for bill_no in req.bill_numbers:
            try:
                hwpx, hwp, bill_name = process_bill(bill_no, req.options)
                zf.writestr(f"{bill_no}_검토보고.hwpx", hwpx)
                if hwp:
                    zf.writestr(f"{bill_no}_의안원문.hwp", hwp)
            except Exception as e:
                import traceback
                errors.append({"bill_no": bill_no, "error": str(e), "traceback": traceback.format_exc()})

    zip_buf.seek(0)

    if errors:
        if zip_buf.getbuffer().nbytes == 0:
            raise HTTPException(status_code=500, detail=errors)
        # 일부 성공, 일부 실패: 에러를 헤더에 담고 zip 반환
        # (일단 에러 raise로 확인)
        raise HTTPException(status_code=500, detail=errors)
    from urllib.parse import quote
    filename = quote("검토보고서.zip", encoding="utf-8")
    _log_usage(_client_ip(request), "review", len(req.bill_numbers))
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.post("/generate-report")
async def generate_report(req: ReportRequest, request: Request):
    """의안번호 목록을 받아 심사보고서(.hwpx)를 zip으로 반환."""
    if not req.bill_numbers:
        raise HTTPException(status_code=400, detail="의안번호를 입력하세요.")

    zip_buf = io.BytesIO()
    errors = []

    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for bill_no in req.bill_numbers:
            try:
                hwpx, bill_name = process_bill_report(bill_no)
                zf.writestr(f"{bill_no}_심사보고.hwpx", hwpx)
            except Exception as e:
                import traceback
                errors.append({"bill_no": bill_no, "error": str(e), "traceback": traceback.format_exc()})

    zip_buf.seek(0)

    if errors:
        raise HTTPException(status_code=500, detail=errors)

    from urllib.parse import quote
    filename = quote("심사보고서.zip", encoding="utf-8")
    _log_usage(_client_ip(request), "examination", len(req.bill_numbers))
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/stats")
async def stats():
    with sqlite3.connect(DB_PATH) as con:
        cumulative = {
            "unique_users": con.execute("SELECT COUNT(DISTINCT ip) FROM usage_log").fetchone()[0],
            "review_count": con.execute("SELECT COALESCE(SUM(bill_cnt), 0) FROM usage_log WHERE endpoint='review'").fetchone()[0],
            "examination_count": con.execute("SELECT COALESCE(SUM(bill_cnt), 0) FROM usage_log WHERE endpoint='examination'").fetchone()[0],
        }
        cumulative["total_count"] = cumulative["review_count"] + cumulative["examination_count"]

        monthly_rows = con.execute("""
            SELECT strftime('%Y-%m', ts) AS month,
                   COUNT(DISTINCT ip)            AS unique_users,
                   SUM(CASE WHEN endpoint='review' THEN bill_cnt ELSE 0 END)      AS review,
                   SUM(CASE WHEN endpoint='examination' THEN bill_cnt ELSE 0 END) AS examination
            FROM usage_log
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
        """).fetchall()

        daily_rows = con.execute("""
            SELECT strftime('%Y-%m-%d', ts) AS date,
                   COUNT(DISTINCT ip)            AS unique_users,
                   SUM(CASE WHEN endpoint='review' THEN bill_cnt ELSE 0 END)      AS review,
                   SUM(CASE WHEN endpoint='examination' THEN bill_cnt ELSE 0 END) AS examination
            FROM usage_log
            GROUP BY date
            ORDER BY date DESC
            LIMIT 30
        """).fetchall()

    return {
        "cumulative": cumulative,
        "monthly": [
            {"month": r[0], "unique_users": r[1], "review": r[2], "examination": r[3]}
            for r in monthly_rows
        ],
        "daily": [
            {"date": r[0], "unique_users": r[1], "review": r[2], "examination": r[3]}
            for r in daily_rows
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
