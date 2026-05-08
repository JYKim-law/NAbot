# 국회bot — 검토보고서 자동화

국회 입법 검토보고서 초안을 의안번호만 입력하면 자동으로 생성해주는 웹 서비스.

열린국회정보 API에서 의안 정보를 수집하고, hwpx 템플릿에 자동으로 채워 넣는다.

## 실행 화면

- 의안번호 직접 입력 또는 엑셀 파일 업로드
- 회기·위원회·담당자 옵션 입력
- 버튼 하나로 검토보고서 ZIP 다운로드

## 설치

Python 3.10+ 및 아래 패키지 필요:

```bash
pip install fastapi uvicorn requests beautifulsoup4 lxml streamlit openpyxl
```

## API 키 발급

열린국회정보 Open API 키가 필요하다. https://open.assembly.go.kr 에서 무료 발급.

발급 후 환경변수로 설정:

```bash
# Windows
set ASSEMBLY_API_KEY=발급받은키

# Mac/Linux
export ASSEMBLY_API_KEY=발급받은키
```

## 실행 방법

터미널 두 개를 열고 각각 실행:

```bash
# 터미널 1: 백엔드
uvicorn main:app --host 127.0.0.1 --port 8000

# 터미널 2: 프론트엔드
streamlit run streamlit_app.py
```

브라우저에서 http://localhost:8501 접속.

## 파일 구조

```
main.py              FastAPI 백엔드 (의안 정보 수집 + hwpx 생성)
streamlit_app.py     Streamlit 프론트엔드
hwpx_utils.py        hwpx 템플릿 {{플레이스홀더}} 치환 유틸리티
(수정하지마시오)재료파일(web).hwpx   hwpx 템플릿 (수정 금지)
```

## 주의사항

- `(수정하지마시오)재료파일(web).hwpx` 파일을 수정하면 출력물이 깨질 수 있다.
- 신구조문대비표(대비표)는 `.hwp` OLE 바이너리 한계로 자동 삽입 불가.
  ZIP에 포함된 의안원문 파일에서 수동으로 복사·붙여넣기 필요.
- 열린국회정보 API 키는 환경변수 `ASSEMBLY_API_KEY`로 주입해야 한다. 위 설정 참고.
