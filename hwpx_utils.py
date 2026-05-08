# -*- coding: utf-8 -*-
"""hwpx 템플릿 {{플레이스홀더}} 치환 유틸리티."""

import os
import re
import shutil
import zipfile
from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2012/paragraph"
_HP = f"{{{HP}}}"

def _para_text(para_el):
    """단락 내 모든 hp:t 텍스트를 이어붙여 반환."""
    parts = []
    for t in para_el.iter(f"{_HP}t"):
        parts.append(t.text or "")
    return "".join(parts)

def _replace_in_paragraph(para_el, placeholder, value):
    """
    단락 안의 run들에 걸쳐 있는 placeholder를 찾아 value로 치환.
    - placeholder가 단일 run에 있으면 그 run의 hp:t만 수정.
    - 여러 run에 걸쳐 있으면 첫 run만 남기고 나머지 run의 해당 부분을 제거.
    """
    full_text = _para_text(para_el)
    if placeholder not in full_text:
        return 0

    replaced = 0
    while placeholder in _para_text(para_el):
        runs = para_el.findall(f".//{_HP}run")
        t_elements = []
        for run in runs:
            for t in run.findall(f"{_HP}t"):
                t_elements.append((run, t))

        # 각 t의 텍스트를 이어붙이며 placeholder 위치 파악
        texts = [t.text or "" for _, t in t_elements]
        concat = "".join(texts)
        start = concat.find(placeholder)
        if start == -1:
            break

        end = start + len(placeholder)

        # 어느 t에 start/end가 걸리는지 계산
        pos = 0
        affected = []  # (run, t, local_start, local_end)
        for run, t in t_elements:
            t_text = t.text or ""
            t_start = pos
            t_end = pos + len(t_text)
            if t_end > start and t_start < end:
                local_s = max(0, start - t_start)
                local_e = min(len(t_text), end - t_start)
                affected.append((run, t, local_s, local_e))
            pos = t_end

        if not affected:
            break

        # 첫 번째 affected run에 치환값 삽입, 나머지는 해당 부분 제거
        first_run, first_t, ls, le = affected[0]
        orig = first_t.text or ""
        first_t.text = orig[:ls] + value + orig[le:]

        for run, t, ls, le in affected[1:]:
            orig = t.text or ""
            t.text = orig[:ls] + orig[le:]

        replaced += 1

    return replaced


def fill_hwpx_template(template_path: str, output_path: str, fields: dict) -> None:
    """
    hwpx 템플릿의 {{플레이스홀더}}를 fields 딕셔너리 값으로 치환하여 저장.
    run 분리 케이스도 처리.
    """
    shutil.copy2(template_path, output_path)

    with zipfile.ZipFile(output_path, "r") as z:
        names = z.namelist()
        files = {name: z.read(name) for name in names}

    # section XML들 처리
    section_files = [n for n in names if re.match(r"Contents/section\d+\.xml", n)]

    for sec_file in section_files:
        xml_bytes = files[sec_file]
        root = etree.fromstring(xml_bytes)

        for placeholder, value in fields.items():
            # 1차: 빠른 문자열 치환 (단일 run)
            xml_str = etree.tostring(root, encoding="unicode")
            if placeholder in xml_str:
                xml_str = xml_str.replace(placeholder, value)
                root = etree.fromstring(xml_str)
                continue

            # 2차: run 분리 케이스 — 단락 단위 처리
            for para in root.iter(f"{_HP}p"):
                _replace_in_paragraph(para, placeholder, value)

        # 값이 없어서 채워지지 않은 {{...}} 제거 + lineseg 캐시 제거를 한 번에
        xml_str = etree.tostring(root, encoding="unicode")
        xml_str = re.sub(r"\{\{[^}]+\}\}", "", xml_str)
        # lineseg 요소 제거 — linesegarray 태그는 유지, 내부 캐시만 삭제
        # 한컴이 열 때 레이아웃을 재계산하도록 강제
        xml_str = re.sub(r"<hp:lineseg\s[^/]*/?>", "", xml_str)
        files[sec_file] = xml_str.encode("utf-8")

    tmp = output_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)
    os.replace(tmp, output_path)
