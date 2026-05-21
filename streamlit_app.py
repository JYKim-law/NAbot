# -*- coding: utf-8 -*-
import os
import streamlit as st
import requests
import openpyxl

st.set_page_config(page_title="국회bot", page_icon="🏛", layout="centered")
st.title("국회bot")
st.caption("국회 상임위 검토보고서 / 심사보고서 작성 자동화")
st.markdown(
    "[GitHub](https://github.com/JYKim-law/NAbot) · "
    "[소개 페이지](https://sites.google.com/view/jaeyoon-kim/nabot)"
)

API_URL = "http://localhost:8000"


def _get_client_ip() -> str:
    """Tailscale Funnel 등 프록시 환경에서 실제 클라이언트 IP를 반환."""
    try:
        h = st.context.headers
        fwd = h.get("X-Forwarded-For") or h.get("X-Real-Ip") or ""
        if fwd:
            return fwd.split(",")[0].strip()
    except Exception:
        pass
    return "unknown"

if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None
if "report_zip_bytes" not in st.session_state:
    st.session_state.report_zip_bytes = None


def parse_excel(f) -> list[str]:
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb.active
    vals = [
        str(r[0]).strip()
        for r in ws.iter_rows(min_col=1, max_col=1, values_only=True)
        if r[0] is not None
    ]
    wb.close()
    return [v for v in vals if v]


def collect_numbers(raw_text, uploaded) -> list[str]:
    nums = []
    if raw_text.strip():
        nums += [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if uploaded:
        nums += parse_excel(uploaded)
    seen, result = set(), []
    for n in nums:
        if n not in seen:
            seen.add(n)
            result.append(n)
    return result


with open(os.path.join(os.path.dirname(__file__), "의안번호입력시트.xlsx"), "rb") as _f:
    _sample_xlsx = _f.read()

tab1, tab2, tab3 = st.tabs(["검토보고서", "심사보고서", "이용 통계"])

# ── 검토보고서 탭 ──────────────────────────────────────────────────
with tab1:
    st.subheader("1. 의안번호 입력")
    col_text, col_excel = st.columns(2)

    with col_text:
        raw_text_g = st.text_area(
            "직접 입력 (한 줄에 하나씩)",
            placeholder="2212345\n2212346",
            height=130,
            key="g_text",
        )

    with col_excel:
        uploaded_g = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=["xlsx"], key="g_excel")
        st.caption("첫 열에 의안번호만 세로로 입력된 엑셀 파일을 사용하세요")
        st.download_button(
            "예시 엑셀 파일 다운로드",
            data=_sample_xlsx,
            file_name="의안번호입력시트.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="g_sample",
        )

    st.subheader("2. 옵션 입력")
    col1, col2 = st.columns(2)
    with col1:
        hoe_cha    = st.text_input("제 N 회국회", placeholder="400")
        hoe_gu     = st.radio("회기 구분", ["임시회", "정기회"], horizontal=True)
        cha        = st.text_input("제 N 차 위원회", placeholder="1")
    with col2:
        chief_type = st.radio("수석/전문위원 구분", ["수석전문위원", "전문위원"], horizontal=True)
        chief_name = st.text_input("성함", placeholder="홍길동")
        tel_ext    = st.text_input("내선번호 (02-6788-XXXX)", placeholder="0000")

    st.subheader("3. 실행")
    if st.button("검토보고서 생성", type="primary", use_container_width=True):
        bill_numbers = collect_numbers(raw_text_g, uploaded_g)
        if not bill_numbers:
            st.warning("의안번호를 입력하거나 엑셀 파일을 업로드하세요.")
        else:
            st.info(f"총 {len(bill_numbers)}건 처리 요청 중…")
            with st.spinner("서버에서 문서를 생성하고 있습니다. 잠시 기다려 주세요."):
                try:
                    resp = requests.post(
                        API_URL + "/generate",
                        json={
                            "bill_numbers": bill_numbers,
                            "options": {
                                "hoe_cha": hoe_cha or "400",
                                "hoe_gu": hoe_gu,
                                "cha": cha or "1",
                                "chief_type": chief_type,
                                "chief_name": chief_name or "홍길동",
                                "tel_ext": tel_ext or "0000",
                            },
                        },
                        headers={"X-Forwarded-For": _get_client_ip()},
                        timeout=300,
                    )
                    resp.raise_for_status()
                    st.session_state.zip_bytes = resp.content
                    st.success(f"{len(bill_numbers)}건 완료! 아래에서 다운로드하세요.")
                except requests.exceptions.ConnectionError:
                    st.error("서버 연결 실패. 서버가 실행 중인지 확인하세요.")
                    st.session_state.zip_bytes = None
                except requests.exceptions.HTTPError as e:
                    st.error(f"서버 오류 ({e.response.status_code}):\n{e.response.text[:500]}")
                    st.session_state.zip_bytes = None
                except Exception as e:
                    st.error(f"오류: {e}")
                    st.session_state.zip_bytes = None

    if st.session_state.zip_bytes:
        st.download_button(
            "ZIP 다운로드",
            data=st.session_state.zip_bytes,
            file_name="검토보고서.zip",
            mime="application/zip",
            use_container_width=True,
        )

# ── 심사보고서 탭 ──────────────────────────────────────────────────
with tab2:
    st.subheader("1. 의안번호 입력")
    col_text2, col_excel2 = st.columns(2)

    with col_text2:
        raw_text_r = st.text_area(
            "직접 입력 (한 줄에 하나씩)",
            placeholder="2212345\n2212346",
            height=130,
            key="r_text",
        )

    with col_excel2:
        uploaded_r = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=["xlsx"], key="r_excel")
        st.caption("첫 열에 의안번호만 세로로 입력된 엑셀 파일을 사용하세요")
        st.download_button(
            "예시 엑셀 파일 다운로드",
            data=_sample_xlsx,
            file_name="의안번호입력시트.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="r_sample",
        )

    st.subheader("2. 실행")
    if st.button("심사보고서 생성", type="primary", use_container_width=True):
        bill_numbers = collect_numbers(raw_text_r, uploaded_r)
        if not bill_numbers:
            st.warning("의안번호를 입력하거나 엑셀 파일을 업로드하세요.")
        else:
            st.info(f"총 {len(bill_numbers)}건 처리 요청 중…")
            with st.spinner("서버에서 문서를 생성하고 있습니다. 잠시 기다려 주세요."):
                try:
                    resp = requests.post(
                        API_URL + "/generate-report",
                        json={"bill_numbers": bill_numbers},
                        headers={"X-Forwarded-For": _get_client_ip()},
                        timeout=300,
                    )
                    resp.raise_for_status()
                    st.session_state.report_zip_bytes = resp.content
                    st.success(f"{len(bill_numbers)}건 완료! 아래에서 다운로드하세요.")
                except requests.exceptions.ConnectionError:
                    st.error("서버 연결 실패. 서버가 실행 중인지 확인하세요.")
                    st.session_state.report_zip_bytes = None
                except requests.exceptions.HTTPError as e:
                    st.error(f"서버 오류 ({e.response.status_code}):\n{e.response.text[:500]}")
                    st.session_state.report_zip_bytes = None
                except Exception as e:
                    st.error(f"오류: {e}")
                    st.session_state.report_zip_bytes = None

    if st.session_state.report_zip_bytes:
        st.download_button(
            "ZIP 다운로드",
            data=st.session_state.report_zip_bytes,
            file_name="심사보고서.zip",
            mime="application/zip",
            use_container_width=True,
        )

with tab3:
    st.subheader("누적 이용 통계 (since 2026.5.20.)")
    try:
        data = requests.get(API_URL + "/stats", timeout=5).json()
    except Exception:
        st.error("서버에서 통계를 불러올 수 없습니다.")
        st.stop()

    cum = data["cumulative"]

    def _stat_card(label, sublabel, value):
        return f"""
        <div style="text-align:center; padding:1.2rem 0.6rem;
                    background:#f8f9fa; border-radius:10px; border:1px solid #e9ecef;">
            <div style="font-size:0.95rem; font-weight:600; color:#333;">{label}</div>
            <div style="font-size:0.75rem; color:#999; margin-top:0.15rem;">{sublabel}</div>
            <div style="font-size:2rem; font-weight:700; color:#1a1a2e;
                        margin-top:0.5rem; letter-spacing:-1px;">{value}</div>
        </div>
        """

    c1, c2, c3 = st.columns(3)
    c1.markdown(_stat_card("이용자 수", "IP 기준", f"{cum['unique_users']:,} 명"), unsafe_allow_html=True)
    c2.markdown(_stat_card("검토보고서 생성", "의안번호 입력 수 기준", f"{cum['review_count']:,} 건"), unsafe_allow_html=True)
    c3.markdown(_stat_card("심사보고서 생성", "의안번호 입력 수 기준", f"{cum['examination_count']:,} 건"), unsafe_allow_html=True)

    st.divider()

    import pandas as pd

    st.markdown("**월별 이용 현황**")
    if data["monthly"]:
        monthly_df = pd.DataFrame(data["monthly"]).rename(columns={
            "month": "월", "unique_users": "이용자 수", "review": "검토보고서", "examination": "심사보고서"
        })
        st.dataframe(monthly_df, hide_index=True, use_container_width=True)
    else:
        st.caption("아직 데이터가 없습니다.")

    st.divider()

    st.markdown("**일별 이용 현황 (최근 30일)**")
    if data["daily"]:
        daily_df = pd.DataFrame(data["daily"]).rename(columns={
            "date": "날짜", "unique_users": "이용자 수", "review": "검토보고서", "examination": "심사보고서"
        })
        st.dataframe(daily_df, hide_index=True, use_container_width=True)
    else:
        st.caption("아직 데이터가 없습니다.")

st.divider()
st.caption("오류·고장: suitbread@gmail.com")
