# -*- coding: utf-8 -*-
"""hwpx 템플릿 {{플레이스홀더}} 치환 유틸리티."""

import os
import re
import shutil
import zipfile
from copy import deepcopy
from lxml import etree

HP  = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_HP = f"{{{HP}}}"
HH  = "http://www.hancom.co.kr/hwpml/2011/head"
_HH = f"{{{HH}}}"

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


def _replace_multiline(root, placeholder, value):
    """
    줄바꿈(\r\n)이 있는 값: 플레이스홀더가 있는 단락을 줄 수만큼 복제하여 삽입.
    각 복제 단락은 원본 단락의 서식을 그대로 유지하고 해당 줄 텍스트만 채움.
    """
    lines = value.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        lines = ['']

    for para in root.iter(f"{_HP}p"):
        if placeholder not in _para_text(para):
            continue

        parent = para.getparent()
        idx = list(parent).index(para)

        # 원본 단락: 첫 번째 줄로 치환
        _replace_in_paragraph(para, placeholder, lines[0])

        # 나머지 줄: 단락 복제 후 삽입
        for i, line in enumerate(lines[1:], 1):
            new_para = deepcopy(para)
            t_els = list(new_para.iter(f"{_HP}t"))
            for j, t_el in enumerate(t_els):
                t_el.text = line if j == 0 else ""
            parent.insert(idx + i, new_para)

        break


_ALIGN_TO_PARAPR = {
    'both': '2', 'center': '0', 'left': '7',
    'right': '13', 'distribute': '21', 'distribute-space': '18',
}


def _ensure_table_charpr(files: dict, height: int = 1200) -> tuple:
    """
    header.xml에 표용 charPr 두 개(일반 + 밑줄)를 추가.
    두 charPr 모두 charPr id=11을 기반으로 height를 변경.
    (regular_id, underline_id) 반환.
    charProperties.itemCnt 도 함께 갱신.
    """
    header_xml = files.get('Contents/header.xml')
    if header_xml is None:
        return 11, 11

    root = etree.fromstring(header_xml)
    all_cps = list(root.iter(f'{_HH}charPr'))

    # id=11을 기반으로 복제
    base_el = None
    for cp in all_cps:
        if cp.get('id') == '11':
            base_el = cp
            break
    if base_el is None:
        return 11, 11

    parent = base_el.getparent()
    next_id = max(int(cp.get('id', 0)) for cp in all_cps) + 1

    # 일반 charPr (밑줄 없음, 지정 height)
    reg_id = next_id
    new_reg = deepcopy(base_el)
    new_reg.set('id', str(next_id))
    new_reg.set('height', str(height))
    parent.append(new_reg)
    next_id += 1

    # 밑줄 charPr (type=BOTTOM, 지정 height)
    ul_id = next_id
    new_ul = deepcopy(base_el)
    new_ul.set('id', str(next_id))
    new_ul.set('height', str(height))
    ul_el = new_ul.find(f'{_HH}underline')
    if ul_el is not None:
        ul_el.set('type', 'BOTTOM')
    parent.append(new_ul)

    # charProperties.itemCnt 갱신 — HWP가 이 수를 보고 charPr를 로드
    parent.set('itemCnt', str(len(list(parent))))

    files['Contents/header.xml'] = etree.tostring(
        root, encoding='utf-8', xml_declaration=True
    )
    return reg_id, ul_id


def _build_hwpx_tbl(table_data: dict, charpr_id: int, ul_charpr_id: int) -> etree._Element:
    """table_data → <hp:tbl> 요소. rows는 list[list[list[Paragraph]]]."""
    rows       = table_data['rows']
    col_widths = table_data.get('col_widths', [22535, 22535])
    total_w    = table_data.get('total_width', 45070)
    PAD        = 141
    n_rows     = len(rows)
    n_cols     = len(col_widths)

    def E(tag, **attrs):
        el = etree.Element(f'{_HP}{tag}')
        for k, v in attrs.items():
            el.set(k, str(v))
        return el

    tbl = E('tbl',
        id='3000000001', zOrder='0',
        numberingType='TABLE', textWrap='TOP_AND_BOTTOM', textFlow='BOTH_SIDES',
        lock='0', dropcapstyle='None', pageBreak='CELL', repeatHeader='1',
        rowCnt=str(n_rows), colCnt=str(n_cols),
        cellSpacing='0', borderFillIDRef='4', noAdjust='0',
    )

    tbl.append(E('sz',
        width=str(total_w), widthRelTo='ABSOLUTE',
        height='500', heightRelTo='ABSOLUTE',
        protect='0'))
    tbl.append(E('pos',
        treatAsChar='0', affectLSpacing='0', flowWithText='1',
        allowOverlap='0', holdAnchorAndSO='0',
        vertRelTo='PARA', horzRelTo='COLUMN',
        vertAlign='TOP', horzAlign='LEFT',
        vertOffset='0', horzOffset='0'))
    tbl.append(E('outMargin', left='141', right='141', top='141', bottom='141'))
    tbl.append(E('inMargin',  left='141', right='141', top='141', bottom='141'))

    for r_idx, row_cells in enumerate(rows):
        tr = E('tr')
        for c_idx, cell_paras in enumerate(row_cells):
            col_w = col_widths[c_idx] if c_idx < len(col_widths) else 22535

            tc = E('tc', name='', header='0', hasMargin='0',
                   protect='0', editable='0', dirty='0',
                   borderFillIDRef='4')
            tc.append(E('cellAddr', colAddr=str(c_idx), rowAddr=str(r_idx)))
            tc.append(E('cellSpan', colSpan='1', rowSpan='1'))
            tc.append(E('cellSz',   width=str(col_w), height='500'))
            tc.append(E('cellMargin',
                left=str(PAD), right=str(PAD),
                top=str(PAD),  bottom=str(PAD)))

            tc_sub = E('subList')
            tc_sub.set('id', '')
            tc_sub.set('textDirection', 'HORIZONTAL')
            tc_sub.set('lineWrap', 'BREAK')
            tc_sub.set('vertAlign', 'TOP')
            tc_sub.set('linkListIDRef', '0')
            tc_sub.set('linkListNextIDRef', '0')
            tc_sub.set('textWidth', '0')
            tc_sub.set('textHeight', '0')
            tc_sub.set('hasTextRef', '0')
            tc_sub.set('hasNumRef', '0')
            tc.append(tc_sub)

            for para in cell_paras:
                pr_id = _ALIGN_TO_PARAPR.get(para['align'], '2')
                p = E('p', id='0', paraPrIDRef=pr_id, styleIDRef='0',
                      pageBreak='0', columnBreak='0', merged='0')
                for run in para['runs']:
                    cp = ul_charpr_id if run['underline'] else charpr_id
                    r  = E('run', charPrIDRef=str(cp))
                    t  = etree.SubElement(r, f'{_HP}t')
                    t.text = run['text']
                    p.append(r)
                tc_sub.append(p)

            # hp:tc는 반드시 hp:p 하나 이상 필요
            if not len(tc_sub):
                tc_sub.append(E('p', id='0', paraPrIDRef='2', styleIDRef='0',
                                pageBreak='0', columnBreak='0', merged='0'))

            tr.append(tc)
        tbl.append(tr)

    return tbl


def _replace_placeholder_with_tbl(root, placeholder: str, tbl_el) -> bool:
    """{{대비표}}가 있는 <hp:p>를 <hp:p><hp:ctrl><hp:tbl> 구조로 교체."""
    for p in root.iter(f'{_HP}p'):
        if placeholder not in ''.join(t.text or '' for t in p.iter(f'{_HP}t')):
            continue
        parent = p.getparent()
        idx    = list(parent).index(p)

        new_p = etree.Element(f'{_HP}p')
        for attr in ('id', 'paraPrIDRef', 'styleIDRef'):
            new_p.set(attr, p.get(attr, '0'))
        new_p.set('pageBreak',   '0')
        new_p.set('columnBreak', '0')
        new_p.set('merged',      '0')

        run = etree.SubElement(new_p, f'{_HP}run')
        run.set('charPrIDRef', '11')
        run.append(tbl_el)
        t = etree.SubElement(run, f'{_HP}t')
        t.text = ' '

        parent.remove(p)
        parent.insert(idx, new_p)
        return True
    return False


def insert_daebipyo_table(files: dict, table_data: dict) -> None:
    """
    files 딕셔너리(zipfile 내용물)에 신구조문대비표를 삽입.
    - header.xml에 표용 charPr(일반 12pt + 밑줄 12pt) 추가
    - section XML의 {{대비표}} 단락을 <hp:tbl>로 교체
    """
    reg_id, ul_id = _ensure_table_charpr(files, height=1200)
    tbl_el = _build_hwpx_tbl(table_data, charpr_id=reg_id, ul_charpr_id=ul_id)

    for sec_file in [n for n in files if re.match(r'Contents/section\d+\.xml', n)]:
        root = etree.fromstring(files[sec_file])
        if _replace_placeholder_with_tbl(root, '{{대비표}}', tbl_el):
            xml_str = etree.tostring(root, encoding='unicode')
            xml_str = re.sub(r'<hp:lineseg\s[^/]*/>', '', xml_str)
            files[sec_file] = xml_str.encode('utf-8')
            break


def fill_hwpx_template(
    template_path: str,
    output_path: str,
    fields: dict,
    daebipyo: dict | None = None,
) -> None:
    """
    hwpx 템플릿의 {{플레이스홀더}}를 fields로 치환하여 저장.
    daebipyo가 주어지면 {{대비표}} 위치에 신구조문대비표를 삽입.
    """
    shutil.copy2(template_path, output_path)

    with zipfile.ZipFile(output_path, "r") as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        files = {i.filename: z.read(i.filename) for i in infos}
        compress_map = {i.filename: i.compress_type for i in infos}

    # 신구조문대비표 삽입 ({{대비표}} 단락을 실제 표로 교체)
    if daebipyo is not None:
        insert_daebipyo_table(files, daebipyo)

    # section XML들 처리
    section_files = [n for n in names if re.match(r"Contents/section\d+\.xml", n)]

    for sec_file in section_files:
        xml_bytes = files[sec_file]
        root = etree.fromstring(xml_bytes)

        for placeholder, value in fields.items():
            # 줄바꿈 포함: 단락 복제 방식으로 처리
            if '\n' in value or '\r' in value:
                _replace_multiline(root, placeholder, value)
                continue

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
    with zipfile.ZipFile(tmp, "w") as zout:
        for name, data in files.items():
            ctype = compress_map.get(name, zipfile.ZIP_DEFLATED)
            zout.writestr(name, data, compress_type=ctype)
    os.replace(tmp, output_path)
