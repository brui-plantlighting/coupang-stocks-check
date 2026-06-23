# ===== 구글 시트 입출력 =====
# 재고로그: 자동 적재(원본) / 입고기록: 시우가 수동 입력 / 추정판매: 자동 계산 / 진단로그: 진단모드용
import gspread
from google.oauth2.service_account import Credentials
import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_sh = None  # 스프레드시트 핸들 캐시 (매번 재인증 안 하려고)


def _spreadsheet():
    global _sh
    if _sh is None:
        creds = Credentials.from_service_account_file(config.CRED_FILE, scopes=SCOPES)
        _sh = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    return _sh


def _ws(tab, headers):
    """탭이 없으면 헤더와 함께 새로 만듦."""
    sh = _spreadsheet()
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=2000, cols=20)
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws


# ---- 헤더 정의 ----
H_STOCK   = ["수집시각", "상품ID", "상품명", "옵션", "가격", "재고량"]
H_RESTOCK = ["입고시각", "상품ID", "옵션", "입고수량", "메모"]
H_SALES   = ["날짜", "상품ID", "상품명", "옵션", "추정판매수량", "플래그수"]
H_DIAG    = ["수집시각", "상품ID", "상품명", "옵션", "가격", "재고량"]


def append_stock_rows(rows):
    """재고로그에 줄 추가. rows = [[수집시각, 상품ID, 상품명, 옵션, 가격, 재고량], ...]"""
    if not rows:
        return
    ws = _ws(config.TAB_STOCK_LOG, H_STOCK)
    ws.append_rows(rows, value_input_option="USER_ENTERED")


def append_diag_rows(rows):
    """진단로그에 줄 추가 (진단 모드 전용)."""
    if not rows:
        return
    ws = _ws(config.TAB_DIAG, H_DIAG)
    ws.append_rows(rows, value_input_option="USER_ENTERED")


def read_stock_log():
    """재고로그 전체를 dict 리스트로 반환."""
    ws = _ws(config.TAB_STOCK_LOG, H_STOCK)
    return ws.get_all_records()


def read_restock():
    """입고기록 전체를 dict 리스트로 반환. (시우가 손으로 입력하는 시트)"""
    ws = _ws(config.TAB_RESTOCK, H_RESTOCK)
    return ws.get_all_records()


def overwrite_sales(rows):
    """추정판매 시트를 통째로 다시 씀 (중복 방지 위해 append 아니라 덮어쓰기)."""
    ws = _ws(config.TAB_SALES, H_SALES)
    ws.clear()
    ws.update([H_SALES] + rows, value_input_option="USER_ENTERED")
