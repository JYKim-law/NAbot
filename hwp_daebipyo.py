# -*- coding: utf-8 -*-
"""
HWP 의안원문에서 신ㆍ구조문대비표를 추출하는 모듈.
pyhwp(hwp5proc xml) 기반, COM API 불필요.
일부개정법률안에만 대비표가 있고, 없으면 None 반환.
"""
import os
import re
import sys
import tempfile
from typing import Optional

from lxml import etree

# Run: {'text': str, 'underline': bool}
# Paragraph: {'runs': list[Run], 'align': str}  align은 pyhwp ParaShape.align 값
# Cell: list[Paragraph]
# Row: list[Cell]
# TableData: {'rows': list[Row], 'col_widths': list[int], 'total_width': int}


def extract_daebipyo(hwp_bytes: bytes) -> Optional[dict]:
    """
    HWP 바이트에서 신ㆍ구조문대비표를 추출.
    없으면 None 반환 (제정안·전부개정안 등).
    """
    xml_bytes = _hwp_to_xml(hwp_bytes)
    if not xml_bytes:
        return None

    if xml_bytes.startswith(b'\xef\xbb\xbf'):
        xml_bytes = xml_bytes[3:]
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        return None

    ul_ids       = _get_underline_charshape_ids(root)
    align_map    = _get_para_align_map(root)
    tbl_el, tbl_attrib = _find_daebipyo_tablecontrol(root)
    if tbl_el is None:
        return None

    rows = _parse_tablecontrol(tbl_el, ul_ids, align_map)
    if not rows:
        return None

    col_widths = _get_col_widths(tbl_el)
    total_width = int(tbl_attrib.get('width', 45070))

    return {
        'rows': rows,
        'col_widths': col_widths,
        'total_width': total_width,
    }


def _hwp_to_xml(hwp_bytes: bytes) -> Optional[bytes]:
    """
    hwp5.hwp5proc xml을 인프로세스로 실행해 XML 바이트 반환.
    pyhwp가 xmllint 파이프를 쓰므로 subprocess capture가 안 돼
    sys.stdout을 직접 가로챈다.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.hwp', delete=False) as f:
            f.write(hwp_bytes)
            tmp_path = f.name

        import io as _io
        from hwp5.hwp5proc import main as _hwp5_main

        buf = _io.BytesIO()
        wrapper = _io.TextIOWrapper(buf, encoding='utf-8', errors='replace')
        old_stdout = sys.stdout
        old_argv   = sys.argv
        sys.stdout = wrapper
        sys.argv   = ['hwp5proc', 'xml', tmp_path]
        try:
            _hwp5_main()
        except SystemExit:
            pass
        finally:
            try:
                sys.stdout.flush()
            except Exception:
                pass
            sys.stdout = old_stdout
            sys.argv   = old_argv

        xml_bytes = buf.getvalue()
        return xml_bytes if xml_bytes else None

    except Exception:
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Windows 파일 잠금 시 무시


def _get_underline_charshape_ids(root) -> set:
    """DocInfo CharShape 정의(순서=ID)에서 underline='underline'인 ID 집합."""
    ul_ids = set()
    idx = 0
    for el in root.iter():
        if el.tag.split('}')[-1] == 'CharShape':
            if el.get('underline') == 'underline':
                ul_ids.add(idx)
            idx += 1
    return ul_ids


def _get_para_align_map(root) -> dict:
    """DocInfo ParaShape 정의(순서=ID)에서 align 값 맵 반환."""
    result = {}
    idx = 0
    for el in root.iter():
        if el.tag.split('}')[-1] == 'ParaShape':
            result[idx] = el.get('align', 'both')
            idx += 1
    return result


def _find_daebipyo_tablecontrol(root):
    """'신ㆍ구조문대비표' 텍스트 이후 첫 TableControl 반환 (element, attrib)."""
    found_marker = False
    for el in root.iter():
        tag = el.tag.split('}')[-1]
        if not found_marker:
            if tag == 'Text' and el.text:
                if re.search(r'신\s*[·ㆍ]\s*구조문대비표', el.text):
                    found_marker = True
        else:
            if tag == 'TableControl':
                return el, dict(el.attrib)
    return None, {}


def _get_col_widths(tbl_el) -> list:
    """첫 행 셀들의 너비 목록."""
    for row in tbl_el.iter():
        if row.tag.split('}')[-1] == 'TableRow':
            return [
                int(cell.get('width', 22535))
                for cell in row
                if cell.tag.split('}')[-1] == 'TableCell'
            ]
    return [22535, 22535]


_DASH_ONLY_RE = re.compile(r'^[\s\-–—]*$')  # 공백·하이픈·en/em dash만


def _is_empty_row(cells: list) -> bool:
    """모든 셀이 실질적으로 비어있으면 True.

    완전히 빈 셀뿐 아니라, 대시(-, –, —)와 공백만으로 이루어진 셀도 빈 것으로 간주.
    """
    for cell_paras in cells:
        for para in cell_paras:
            for r in para['runs']:
                text = r['text'].strip()
                if text and not _DASH_ONLY_RE.match(text):
                    return False
    return True


def _parse_tablecontrol(tbl_el, ul_ids: set, align_map: dict) -> list:
    rows = []
    for row_el in tbl_el.iter():
        if row_el.tag.split('}')[-1] != 'TableRow':
            continue
        cells = [
            _extract_cell_paragraphs(cell_el, ul_ids, align_map)
            for cell_el in row_el
            if cell_el.tag.split('}')[-1] == 'TableCell'
        ]
        if cells and not _is_empty_row(cells):
            rows.append(cells)
    return rows


def _extract_cell_paragraphs(cell_el, ul_ids: set, align_map: dict) -> list:
    """TableCell → Paragraph 목록. 각 Paragraph = {'runs': list[Run], 'align': str}."""
    paragraphs = []
    for el in cell_el.iter():
        tag = el.tag.split('}')[-1]
        if tag == 'Paragraph':
            ps_id = int(el.get('parashape-id', 0))
            align = align_map.get(ps_id, 'both')
            paragraphs.append({'runs': [], 'align': align})
        elif tag == 'Text' and el.text and paragraphs:
            cs_id = int(el.get('charshape-id', -1))
            paragraphs[-1]['runs'].append(
                {'text': el.text, 'underline': cs_id in ul_ids}
            )
    # 텍스트가 없는 단락 제거 후 맨 끝 빈 단락도 정리
    paragraphs = [p for p in paragraphs if p['runs']]
    return paragraphs
