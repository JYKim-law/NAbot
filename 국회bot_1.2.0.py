#!/usr/bin/env python
# coding: utf-8

# In[18]:


# 모듈 불러오기
import re ; import os; import sys; import datetime; import requests; import pandas as pd
import urllib.request as request;
from bs4 import BeautifulSoup
from tkinter import messagebox
import tkinter
from tkinter import messagebox, filedialog as fd
import os
import tkinter.font as tkFont
from pyhwpx import Hwp
import webbrowser  # ← 추가

options = ['430','임시회','1','수석전문위원','ㅁㅁㅁ','5000'] # 옵션 기본값들, 제430회 국회(임시회) 제1차 ~위원회, 수석전문위원 ㅁㅁㅁ, 02-6788-1234

if getattr(sys, 'frozen', False):
    # test.exe로 실행한 경우,test.exe를 보관한 디렉토리의 full path를 취득
    p_dir = os.path.dirname(os.path.abspath(sys.executable)) + '//'
else:
    # python test.py로 실행한 경우,test.py를 보관한 디렉토리의 full path를 취득
    p_dir = os.path.abspath('')+ '//'


### 1. tkinter: GUI 메뉴 구조 시작 ###

window = tkinter.Tk()
window.title("[국회bot] 의안원문, 검토보고서 자동화 프로그램")
window.geometry("530x530+300+300")
window.resizable(True, True)
font = tkFont.Font(family="맑은 고딕", size=14)

label = tkinter.Label(
    window,
    text="""[국회bot] 의안원문, 검토보고서 자동화 프로그램     

[의안번호 입력]
 (1) 엑셀 파일 입력: 세로로 의안번호만 넣은 엑셀파일      
 (2) 직접 입력: 의안번호 숫자 입력(여러개 가능)
   * 동시입력 가능: 엑셀 5개 + 직접 2개 = 7개 실행

[옵션 입력] 회기 등(입력 안 하면 기본값 출력)

※ 결과물은 실행파일이 있는 폴더에 저장됩니다.
   대비표를 붙여넣으면서 쪽번호 및 머리말/꼬리말 설정이
   따라 붙을 수 있으니 주의 바랍니다. 
   의안원문이 미접수된 최신 법안은 작동하지 않습니다.

오류·고장은 꼭 신고 부탁드립니다! suitbread@gmail.com
최종 업데이트: 2025.11.20.""",
    font=font, bg="#E7ECF2", anchor='w', justify='left')
label.pack(fill='x')

# "최신버전 확인" 링크 라벨 ─────────────────
def open_latest(event=None):
    webbrowser.open("https://sites.google.com/view/jaeyoon-kim/nabot")

link_label = tkinter.Label(
    window,
    text="최신 버전 확인 링크",
    fg="blue",           # 링크 색
    cursor="hand2",      # 손가락 모양
    font=font
)
link_label.pack(anchor='w', padx=5, pady=(0, 5))
link_label.bind("<Button-1>", open_latest)


bill_number_list = []

def bill_number_input():
    def add_bill_number():
        bill_number = entry.get()
        if bill_number:
            bill_numbers.append(bill_number.strip())
            entry.delete(0, tkinter.END)
            update_bill_number_label()

    def update_bill_number_label():
        bill_number_label.config(text=", ".join(bill_numbers))

    def clear_last_number():
        if bill_numbers:
            bill_numbers.pop()
            update_bill_number_label()

    def close_window():
        if bill_numbers:
            messagebox.showinfo("입력 완료", "의안번호가 정상적으로 입력되었습니다.")
        else:
            messagebox.showinfo("입력 완료", "의안번호가 입력되지 않았습니다.")
        window.destroy()

    bill_numbers = []

    window = tkinter.Tk()
    window.title("의안번호 입력")
    window.geometry("330x250")

    label = tkinter.Label(window, text="의안번호(예: 2112345)를 하나씩 입력하고,\n입력 버튼을 누르세요", font=("맑은 고딕", 12))
    label.pack(pady=10)

    entry = tkinter.Entry(window, font=("맑은 고딕", 12))
    entry.pack(pady=5)

    button_frame = tkinter.Frame(window)  # 버튼들을 포함할 프레임 생성
    button_frame.pack(pady=5)

    add_button = tkinter.Button(button_frame, text="입력", command=add_bill_number, font=("맑은 고딕", 12), bg='Gainsboro', fg='black')
    add_button.pack(side="left", padx=5)  # 버튼을 좌측에 배치

    clear_button = tkinter.Button(button_frame, text="지우기", command=clear_last_number, font=("맑은 고딕", 12), bg='Gainsboro', fg='black')
    clear_button.pack(side="left", padx=5)  # 버튼을 좌측에 배치

    bill_number_label = tkinter.Label(window, text="", font=("맑은 고딕", 12))
    bill_number_label.pack(pady=5)

    close_button = tkinter.Button(window, text="입력완료(닫기)", command=close_window, font=("맑은 고딕", 12), bg='Gainsboro', fg='black')
    close_button.pack(pady=10)

    window.mainloop()

    return bill_numbers

def excel_input():
    top = tkinter.Toplevel()
    top.title("의안번호 파일 선택")
    top.geometry("+500-50")
    label = tkinter.Label(top, text="""첫 칸부터 세로로 의안번호만 넣은 엑셀파일을 사용하세요.
    * 암호화 해제를 확인해주세요.""", font=("맑은 고딕", 13))
    label.pack(padx=50, pady=20)
    path = fd.askopenfilename(initialdir=os.getcwd(), title="의안번호 파일 선택",
                          filetypes = (("엑셀파일","*.xlsx"),("모든파일","*.*")))
    bill_number_list = pd.read_excel(path, engine='openpyxl', header=None)
    bill_number_list = list(bill_number_list.iloc[:, 0])
    messagebox.showinfo("입력 완료", "엑셀 입력이 완료되었습니다.")
    top.destroy()
    return bill_number_list

def option_input():
    global options  # 전역 변수를 사용하도록 설정
    options = ['430','임시회','1','수석전문위원','ㅁㅁㅁ','1234']

    def save_and_close():
        for i in range(6):
            if i in [1, 3]:  # 선택 옵션에 대해
                options[i] = selected_vars[i].get()
            else:
                options[i] = entries[i].get()
        messagebox.showinfo("입력 완료", "옵션이 정상적으로 입력되었습니다:\n" + "\n".join(options))
        window.destroy()

    window = tkinter.Toplevel()
    window.title("옵션 입력")
    window.geometry("430x300")

    labels = ["제 ", "회기 구분: ","제", "수석/전문위원 구분: ", "수석/전문위원 성함: ", "내선번호: 02-6788-"]
    suffixes = ["회국회", "", "차 위원회", "", "",""]
    entries = [None] * 6  # Initialize with 6 None values
    selected_vars = [None] * 6  # Initialize with 6 None values

    for i in range(6):
        frame = tkinter.Frame(window)
        frame.pack(pady=5, padx=5, anchor='w')

        left_label = tkinter.Label(frame, text=labels[i], font=("맑은 고딕", 12))
        left_label.grid(row=0, column=0, sticky='w', padx=5)

        if i in [1]:  # 선택 옵션에 대해
            var = tkinter.StringVar(value="임시회")
            selected_vars[i] = var
            rb1 = tkinter.Radiobutton(frame, text="임시회", variable=var, value="임시회", font=("맑은 고딕", 12))
            rb2 = tkinter.Radiobutton(frame, text="정기회", variable=var, value="정기회", font=("맑은 고딕", 12))
            rb1.grid(row=0, column=1, sticky='w', padx=5)
            rb2.grid(row=0, column=2, sticky='w', padx=5)
        elif i in [3]:  # 선택 옵션에 대해
            var = tkinter.StringVar(value="수석전문위원")
            selected_vars[i] = var
            rb1 = tkinter.Radiobutton(frame, text="수석전문위원", variable=var, value="수석전문위원", font=("맑은 고딕", 12))
            rb2 = tkinter.Radiobutton(frame, text="전문위원", variable=var, value="전문위원", font=("맑은 고딕", 12))
            rb1.grid(row=0, column=1, sticky='w', padx=5)
            rb2.grid(row=0, column=2, sticky='w', padx=5)
        else:
            if i == 0:
                entry = tkinter.Entry(frame, font=("맑은 고딕", 12), width=3)
            elif i == 2:
                entry = tkinter.Entry(frame, font=("맑은 고딕", 12), width=2)
            elif i == 4:
                entry = tkinter.Entry(frame, font=("맑은 고딕", 12), width=8)
            else:
                entry = tkinter.Entry(frame, font=("맑은 고딕", 12), width=4)
            entry.grid(row=0, column=1, sticky='w', padx=5)
            entries[i] = entry  # Assign the entry to the correct index

        if suffixes[i]:  # If there is a suffix, add it
            right_label = tkinter.Label(frame, text=suffixes[i], font=("맑은 고딕", 12))
            right_label.grid(row=0, column=2, sticky='w', padx=5)

    save_button = tkinter.Button(window, text="저장하고 닫기", command=save_and_close, font=("맑은 고딕", 12), bg='Gainsboro', fg='black')
    save_button.pack(pady=10)

    window.mainloop()

def close_window():
    if messagebox.askokcancel("확인", "창을 종료하고 의안원문 및 검토보고서 자동화 작업을 시작합니다. 결과물은 실행파일이 있는 폴더에 저장됩니다."):
        window.destroy()

button_frame1 = tkinter.LabelFrame(window, text="의안번호 입력", font=("맑은 고딕", 13))
button_frame1.pack(side="left", padx=3, pady=3, fill="x")

button_excel = tkinter.Button(button_frame1, text="엑셀 파일 입력", command=lambda: bill_number_list.extend(excel_input()), font=("맑은 고딕", 14), bg='Gainsboro', fg='black')
button_excel.pack(side="left", padx=3, pady=5)

button_direct = tkinter.Button(button_frame1, text="직접 입력", command=lambda: bill_number_list.extend(bill_number_input()), font=("맑은 고딕", 14), bg='Gainsboro', fg='black')
button_direct.pack(side="left", padx=3, pady=5)

button_frame2 = tkinter.Frame(window)  # 두 번째 줄 버튼들을 담을 프레임 생성
button_frame2.pack(side="left", padx=3, pady=5)  # 프레임을 윈도우에 배치

button_option = tkinter.Button(button_frame2, text="옵션 입력", command=lambda: option_input(), font=("맑은 고딕", 14), bg='Gainsboro', fg='black')
button_option.pack(side="left", padx=3, pady=5)

button_execute = tkinter.Button(button_frame2, text="실행(창 종료)", command=close_window, font=("맑은 고딕", 14), bg='Gainsboro', fg='black')
button_execute.pack(side="left", padx=3, pady=5)

window.mainloop()






### 2. 기본 옵션 설정값 입력 ###
hwp = Hwp()

# 500회국회(임시회)
hogi1 = '제' + str(options[0]) + '회국회(' + str(options[1]) + ')'

# (수석)전문위원 ㅁㅁㅁ
chief_han = str(options[3]) + ' ' + str(options[4])


### 3. 자동화 ###

# 의안, 비용추계서 다운로드용 주소 만들기 재료
book_base = 'https://likms.assembly.go.kr/filegate/servlet/FileGate?bookId='
base = 'https://open.assembly.go.kr/portal/openapi/'
base2 = 'https://pal.assembly.go.kr/napal/lgsltpa/lgsltpaDone/view.do?lgsltPaId='  # 임시로 입법예고 페이지를 이용하기로 함
#kyeryu = 'nwbqublzajtcqpdae'# 열린국회정보 open api 기능
key = '?KEY=7257fcd176844b06bbb0996e3b02a5c1' # 열린국회정보 open api key
ty = '&Type=xml'; pi = '&pIndex=1'
tt = 'ALLBILL/'# 열린국회정보 open api 기능
inf2 = 'BILLJUDGECONF/'
summ = 'BPMBILLSUMMARY/'
ds = '&AGE='


today = datetime.datetime.today()

for i in range(len(bill_number_list)): # df는 앞서 입력한 엑셀, 모든 법안에 대해서 반복
    no_file = 0 # 의안원문 파일이 없을 경우 0, 있을 경우 1로 바뀌는 변수

    # URL, 의안명 등 기본정보 불러오기
    number = bill_number_list[i]
    str_number = str(number)
    short_number = str_number[2:]
    short_number = short_number.lstrip('0')
    bn = '&BILL_NO=' + str(number)
    url = base + tt + key + ds + short_number + bn
    ret = requests.get(url)
    xml = BeautifulSoup(ret.text,'xml')

    # request 해 온 값에서 변수 입력
    bill_name = xml.find_all('BILL_NM')[0].text
    proposer_kind = xml.find_all('PPSR_KND')[0].text
    proposer = xml.find_all('PPSR_NM')[0].text
    propose_dt = xml.find_all('PPSL_DT')[0].text
    committee_dt = xml.find_all('JRCMIT_CMMT_DT')[0].text
    comm_han = xml.find_all('JRCMIT_NM')[0].text
    hogi2 = '제' + str(options[2]) + '차' + comm_han 
    if committee_dt == '':
        committee_dt = '0000-00-00'        
    proposer_name = proposer[:proposer.find('의원')+2]

    # 의안원문 및 비용추계 다운로드
    bill_id = xml.find_all('BILL_ID')[0].text
    url2 = base2 + bill_id # 임시로 입법예고 페이지를 이용하기로 함
    ret2 = requests.get(url2)
    xml2 = BeautifulSoup(ret2.text,'xml')
    book_id = xml2.select_one("a.attach_file")["href"].split("bookId=")[1].split("&")[0]
    before_split2 = xml2.select_one("div.desc").text

    # 저장 경로를 정하고, 해당 경로에 파일 다운로드
    path_down = p_dir
    try:
        book_url = book_base + book_id + '&type=0'
        request.urlretrieve(book_url,path_down + str(bill_number_list[i])+'_의안원문.hwp')
    except: pass

    # 날짜 형식을 2021.5.10 과 같이 바꿔주는 코드
    propose_dt = propose_dt.replace('-','. ')
    if propose_dt[-6] == '0':
        propose_dt = propose_dt[:-6] + propose_dt[-5:]
    if propose_dt[-2] == '0':
        propose_dt = propose_dt[:-2] + propose_dt[-1:]
    propose_dt = propose_dt + '.'

    committee_dt = committee_dt.replace('-','. ')
    if committee_dt[-6] == '0':
        committee_dt = committee_dt[:-6] + committee_dt[-5:]
    if committee_dt[-2] == '0':
        committee_dt = committee_dt[:-2] + committee_dt[-1:]
    committee_dt = committee_dt +'.'

    # 열린국회정보 - 법률안 제안이유 및 주요내용 API
#    url3 = base + summ + key + ty + pi + bn
#    ret3 = requests.get(url3)
#    xml3 = BeautifulSoup(ret3.text,'xml')
#    before_split = xml3.find('SUMMARY').text.replace('？','·')
    before_split = before_split2.replace('？','·').replace('','').strip().replace('\n\n','\n').replace('\n','\r\n')
    if '제안이유 및 주요내용' in before_split:
        if '참고사항' in before_split:
            na_title = '나. 제안이유 및 주요내용'
            na_content = '  ' + re.split('참고사항',before_split[14:])[0].strip()
            da_title = '다. 참고사항'
            da_content = '  ' + re.split('참고사항',before_split[14:])[1].strip()
        else:
            na_title = '나. 제안이유 및 주요내용'
            na_content = '  ' + before_split[14:].strip()
    else:
        after_split = re.split('주요내용|참고사항',before_split)
        if len(after_split) == 2:
            na_title = '나. 제안이유'
            na_content = '  ' + after_split[0].replace('제안이유','').strip()
            da_title = '다. 주요내용'
            da_content = after_split[1].strip()
        elif len(after_split) == 3:
            na_title = '나. 제안이유'
            na_content = '  ' + after_split[0].replace('제안이유','').strip()
            da_title = '다. 주요내용'
            da_content = after_split[1].strip()
            ra_title = '라. 참고사항'
            ra_content = '  ' + after_split[2].strip()

    # 의안원문에서 대비표 복사(의안원문 파일이 있고, 일부개정일때만)
    if no_file == 0:
        if '일부개정' in bill_name:
            path_down = p_dir + str(bill_number_list[i])+'_의안원문.hwp'
            hwp.open(path_down)  # 한글파일 열기
            #hwp.HAction.Execute("AllReplace", hwp.HParameterSet.HFindReplace.HSet);
            hwp.Run("MoveDocEnd")
            hwp.Run("MoveSelPageUp")
            hwp.Run("Copy")
#            hwp.XHwpDocuments.Item(0).Close(isDirty=False) 

    # hwp 검토보고서 입력 자동화 
    hwp.open(p_dir + "(수정하지마시오)재료파일.hwp")  # 한글파일 열기 # v2로 업그레이드
    hwp.put_field_text(field="회기1", text= hogi1)
    hwp.put_field_text(field="회기2", text= hogi2)
    hwp.put_field_text(field="법안명", text= bill_name)
    if proposer_kind == '의원':
        jechul = proposer_name + ' 대표발의(의안번호 제' + short_number +'호)'
        jechul2 = proposer_name + ' 대표발의안(의안번호 제' + short_number +'호)'
        jechul3 = proposer_name + '안'
    elif proposer_kind == '정부':
        jechul = '정부제출(의안번호 제' + short_number +'호)'
        jechul2 = '정부안(의안번호 제' + short_number +'호)'
        jechul3 = '정부안'
    hwp.put_field_text(field="제출정보", text= jechul)
    date= str(today.year) + '. ' + str(today.month) + '.'
    hwp.put_field_text(field="연월", text= date)
    hwp.put_field_text(field="위원회명", text= comm_han)
    hwp.put_field_text(field="전문위원", text= chief_han)
    hwp.put_field_text(field="의원안", text= jechul2)
    hwp.put_field_text(field="의원안(짧은)", text= jechul3)
    hwp.put_field_text(field="제안자", text= proposer)
    hwp.put_field_text(field="제안일", text= propose_dt)
    hwp.put_field_text(field="회부일", text= committee_dt)
    hwp.put_field_text(field="나. 제목", text= na_title)
    hwp.put_field_text(field="나. 내용", text= na_content)

    try:
        hwp.put_field_text(field="다. 제목", text= da_title)
        hwp.put_field_text(field="다. 내용", text= da_content)
    except: pass
    try:
        hwp.put_field_text(field="라. 제목", text= ra_title)
        hwp.put_field_text(field="라. 내용", text= ra_content)
    except: pass


    hwp.put_field_text(field="내선번호", text=str(options[5]))    

    # 대비표 붙여넣기 (일부개정일때만)
    if '일부개정' in bill_name:
        hwp.move_to_field(field='대비표', idx=0, text=True, start=True, select=False) 
        hwp.Run("Paste")

    hwp.MoveDocBegin()

    path_save_gumto = p_dir + str(bill_number_list[i]) + '_검토보고.hwp'
    hwp.save_as(path_save_gumto)
messagebox.showinfo('작업결과',str(len(bill_number_list))+'건의 법안에 대해서 작업 완료(실행파일이 있는 폴더에 파일이 저장되었습니다.)')
# root.destroy()


# In[1]:


p_dir


# In[ ]:




