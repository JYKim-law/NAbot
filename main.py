# -*- coding: utf-8 -*-
import datetime
import io
import os
import re
import tempfile
import zipfile

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from hwpx_utils import fill_hwpx_template

app = FastAPI(title="국회bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "(수정하지마시오)재료파일(web).hwpx")
API_BASE = "https://open.assembly.go.kr/portal/openapi/"
BILL_PAGE_BASE = "https://pal.assembly.go.kr/napal/lgsltpa/lgsltpaDone/view.do?lgsltPaId="
FILE_GATE = "https://likms.assembly.go.kr/filegate/servlet/FileGate?bookId="
API_KEY = "?KEY=7257fcd176844b06bbb0996e3b02a5c1"


class Options(BaseModel):
    hoe_cha: str = "430"        # 제 N 회국회
    hoe_gu: str = "임시회"       # 임시회 / 정기회
    cha: str = "1"              # 제 N 차 위원회
    chief_type: str = "수석전문위원"  # 수석전문위원 / 전문위원
    chief_name: str = "ㅁㅁㅁ"
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
        # {{대비표}}는 값 없으면 cleanup 단계에서 자동 제거
    }

    # ── 4. 템플릿 채우기 ───────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".hwpx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        fill_hwpx_template(TEMPLATE_PATH, tmp_path, fields)
        with open(tmp_path, "rb") as f:
            hwpx_bytes = f.read()
    finally:
        os.unlink(tmp_path)

    return hwpx_bytes, hwp_bytes, bill_name


# ── 엔드포인트 ──────────────────────────────────────────────────────

@app.post("/generate")
async def generate(req: GenerateRequest):
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
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
