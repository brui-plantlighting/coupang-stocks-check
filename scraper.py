# ===== 이미 띄운 크롬에 CDP로 붙어서 재고 긁기 =====
# 로그인은 start_chrome.bat 으로 띄운 크롬에서 수동으로. Playwright 는 붙기만 함.
#
# ⚠️ 안전장치
# 이 스크립트는 상품 목록을 '읽기'만 함.
# goalType=SALES URL 로 바로 들어가므로 '매출성장/다음' 같은 마법사 진행 버튼은 누를 일이 없음.
# 누르는 건 오직 '상품 목록 페이지네이션(1 2 3 ... 다음)' 뿐 → 광고가 만들어질 일 없음.

from playwright.sync_api import sync_playwright
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


def ensure_login(page):
    """CDP 모드: 크롬이 이미 로그인돼 있어야 함. 아니면 수동 로그인 요청."""
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

    if not is_logged_in(page):
        return None

    # 상품 목록 구간이 뜰 때까지 대기 + 스크롤
    page.wait_for_selector("li[data-bigfoot-component='vendor_item']", timeout=30000)
    page.evaluate("window.scrollBy(0, 800)")
    page.wait_for_timeout(500)

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
        page.wait_for_timeout(900)

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
