# ===== 이미 띄운 크롬에 CDP로 붙어서 재고 긁기 =====
# 로그인은 start_chrome.bat 으로 띄운 크롬에서 수동으로. Playwright 는 붙기만 함.
#
# ⚠️ 안전장치
# 이 스크립트는 상품 목록을 '읽기'만 함.
# goalType=SALES URL 로 바로 들어가므로 '매출성장/다음' 같은 마법사 진행 버튼은 누를 일이 없음.
# 누르는 건 오직 '상품 목록 페이지네이션(1 2 3 ... 다음)' 뿐 → 광고가 만들어질 일 없음.

import json
import random
import time

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import config

CDP_URL = "http://127.0.0.1:9222"


def connect():
    """start_chrome.bat 으로 이미 띄운 크롬(포트 9222)에 CDP 로 붙음.
    반환: (playwright, browser, page). 크롬이 닫혔다 다시 켜진 경우에도
    main 루프가 이 함수를 다시 불러 재연결할 수 있도록 분리해둠.
    """
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(CDP_URL)
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, page


def disconnect(pw, browser):
    """CDP 연결만 끊음. 크롬 자체는 계속 살아있음."""
    try:
        browser.close()
    except Exception:
        pass
    try:
        pw.stop()
    except Exception:
        pass


def is_logged_in(page) -> bool:
    """로그인 상태인지 확인. 로그인 안 됐으면 /user/login 으로 리디렉트됨."""
    return "advertising.coupang.com" in page.url and "/user/login" not in page.url


def _load_coupang_credentials():
    """coupang_credentials.json 에서 (id, pw) 읽음. 파일이 없거나 채워지지 않았으면 None."""
    try:
        with open(config.COUPANG_CRED_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    cid, pw = data.get("id"), data.get("pw")
    if not cid or not pw or "여기에" in cid:
        return None
    return cid, pw


def auto_login(page) -> bool:
    """저장된 id/pw로 쿠팡 로그인 폼을 사람처럼 채워서 제출.
    seller-type/market 선택 다이얼로그를 거쳐야 로그인 폼이 나오는데, 이 다이얼로그가
    안 뜨는 계정/세션도 있어서 각 단계는 있으면 누르고 없으면 그냥 건너뜀.
    CAPTCHA 등 자동화로 못 뚫는 단계가 있으면 여기서 막혀 False를 반환하고,
    ensure_login 이 사람 개입(input())으로 넘어감.
    """
    creds = _load_coupang_credentials()
    if creds is None:
        return False
    cid, pw = creds

    try:
        login_btn = page.query_selector("button.ant-btn.ant-btn-primary")
        if login_btn:
            login_btn.click()
            page.wait_for_timeout(random.randint(1200, 2000))

        radio = page.query_selector("input[type='radio']")
        if radio:
            radio.click()
            page.wait_for_timeout(random.randint(600, 1000))
            for b in page.query_selector_all("button"):
                if "Ads Center" in b.inner_text() or "광고센터" in b.inner_text():
                    b.click()
                    break
            page.wait_for_timeout(random.randint(1200, 2000))

        page.wait_for_selector("input[name='username']", timeout=15000)

        page.click("input[name='username']")
        page.wait_for_timeout(random.randint(300, 700))
        for ch in cid:
            page.keyboard.type(ch)
            page.wait_for_timeout(random.randint(70, 180))

        page.wait_for_timeout(random.randint(400, 900))

        page.click("input[name='password']")
        page.wait_for_timeout(random.randint(300, 700))
        for ch in pw:
            page.keyboard.type(ch)
            page.wait_for_timeout(random.randint(70, 180))

        page.wait_for_timeout(random.randint(600, 1200))
        page.click("button[type='submit'].btn-primary")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(2500)
    except PlaywrightTimeoutError:
        return False

    return is_logged_in(page)


def ensure_login(page):
    """로그인이 풀려 있으면 저장된 id/pw로 자동 재로그인을 먼저 시도.
    자격증명이 없거나(coupang_credentials.json 미입력) 자동 로그인이 끝내 실패하면
    (CAPTCHA 등) 기존처럼 사람이 직접 로그인하도록 기다림.
    """
    page.goto(config.ADS_CENTER_URL)
    page.wait_for_load_state("domcontentloaded")

    for _ in range(config.COUPANG_LOGIN_MAX_RETRY):
        if is_logged_in(page):
            break
        if not auto_login(page):
            break
        page.goto(config.ADS_CENTER_URL)
        page.wait_for_load_state("domcontentloaded")

    while not is_logged_in(page):
        input("▶ 크롬 창에서 로그인 완료 후 엔터: ")
        page.wait_for_load_state("domcontentloaded")
    print("로그인 확인됨. 수집 시작.")


def scrape_stock(page):
    """
    SALES 등록 화면으로 들어가 상품 목록을 끝 페이지까지 읽어 반환.
    로그인이 풀렸으면 None 반환 (메인 루프가 다음 사이클에 재시도).
    반환: [{"id": str, "option": str, "price": int, "stock": int}, ...]
    """
    page.goto(config.ADS_CENTER_URL)
    page.wait_for_load_state("domcontentloaded")

    if not is_logged_in(page):
        return None

    # 상품 목록 구간이 뜰 때까지 대기 + 스크롤
    # goto 시점엔 로그인된 것처럼 보였다가, 그 직후 JS 리다이렉트로 로그인 화면으로
    # 넘어가는 경우가 있어서(타이밍 차이) 타임아웃이 나면 로그인 상태를 다시 확인함.
    try:
        page.wait_for_selector("li[data-bigfoot-component='vendor_item']", timeout=30000)
    except PlaywrightTimeoutError:
        if not is_logged_in(page):
            return None
        raise
    page.evaluate("window.scrollBy(0, 800)")
    _wait_rows_settled(page)

    # 페이지네이션을 끝까지 돌며 수집. (id,option) 기준 중복 제거.
    collected = {}
    last_first_id = None

    for _ in range(config.MAX_PAGES_SAFETY):
        rows = page.query_selector_all("li[data-bigfoot-component='vendor_item']")
        if not rows:
            break

        first_id_this_page = None
        for row in rows:
            pid    = "".join(ch for ch in row.query_selector("span.item-viid").inner_text() if ch.isdigit())
            option = (row.query_selector("span.item-winner").inner_text().strip()
                      if row.query_selector("span.item-winner") else "")
            price  = _to_int(row.query_selector("span.item-price").inner_text())
            stock  = _to_int(row.query_selector("span.item-stock").inner_text())
            if first_id_this_page is None:
                first_id_this_page = pid
            collected[(pid, option)] = {"id": pid, "option": option,
                                        "price": price, "stock": stock}

        if first_id_this_page == last_first_id:
            break
        last_first_id = first_id_this_page

        nxt = page.query_selector("li.ant-pagination-next")
        if not nxt or _is_disabled(nxt):
            break
        nxt.click()
        _wait_rows_settled(page, prev_first_id=first_id_this_page)

    return list(collected.values())


# ---- 작은 유틸 ----
def _to_int(text):
    """'21,050원', '재고량 : 13개' 같은 문자열에서 숫자만 뽑아 int 로."""
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else 0


def _is_disabled(el):
    cls = (el.get_attribute("class") or "")
    aria = (el.get_attribute("aria-disabled") or "")
    return ("disabled" in cls) or (aria == "true") or (el.get_attribute("disabled") is not None)


def _first_pid(rows):
    if not rows:
        return None
    return "".join(ch for ch in rows[0].query_selector("span.item-viid").inner_text() if ch.isdigit())


def _wait_rows_settled(page, prev_first_id=None, timeout_ms=8000, settle_ms=400, poll_ms=150):
    """상품 목록이 다 그려질 때까지 대기.
    고정 시간만 기다리면 렌더링이 안 끝난 상태(행 일부만 그려진 상태)에서
    읽어가는 일이 있어서, '페이지 전환 확인 + 행 개수가 더 안 변함'을 직접 확인함.
    prev_first_id 가 있으면(= 다음 페이지 클릭 직후) 첫 행이 실제로 바뀔 때까지 먼저 기다림.
    """
    deadline = time.monotonic() + timeout_ms / 1000

    if prev_first_id is not None:
        while time.monotonic() < deadline:
            rows = page.query_selector_all("li[data-bigfoot-component='vendor_item']")
            if rows and _first_pid(rows) != prev_first_id:
                break
            page.wait_for_timeout(poll_ms)

    last_count = -1
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        count = len(page.query_selector_all("li[data-bigfoot-component='vendor_item']"))
        if count != last_count:
            last_count = count
            stable_since = time.monotonic()
        elif (time.monotonic() - stable_since) * 1000 >= settle_ms:
            return
        page.wait_for_timeout(poll_ms)
