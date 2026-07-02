# ===== 메인 루프 =====
# 항상 켜져 있는 컴퓨터에서 이걸 한 번 실행하면, 창 하나 띄워놓고 계속 상주하며 수집함.
# 브라우저 컨텍스트 하나가 계속 살아있으므로 run 이 겹칠 일이 구조적으로 없음 (중복 방지).
#
# 실행:  python main.py

import time
import traceback
from datetime import datetime

import config
import scraper
import sheets
import calc

LOGIN_EVENT_LOG = "login_events.log"
RELOGIN_RETRY_SEC = 600  # 자동 재로그인 실패 시 10분 후 재시도

_login_ok = True
_dropped_at = None
_last_relogin_attempt = None


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _log_login_event(text):
    line = f"[{_now()}] {text}"
    print(line)
    with open(LOGIN_EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _is_connection_lost(exc) -> bool:
    """크롬 탭/창/프로세스가 닫혀서 CDP 연결이 끊긴 경우인지 판별."""
    msg = str(exc)
    return "has been closed" in msg or "Connection closed" in msg


def run_cycle(page, diagnostic):
    global _login_ok, _dropped_at, _last_relogin_attempt

    items = scraper.scrape_stock(page)
    if items is None:
        if _login_ok:
            _login_ok = False
            _dropped_at = datetime.now()
            _log_login_event("⚠️ 로그인 풀림 감지 — 자동 재로그인 시도")

        # 10분마다 자동 재로그인 재시도 (계속 실패해도 무한 재시도, 막히지 않음)
        now = datetime.now()
        if (_last_relogin_attempt is None or
                (now - _last_relogin_attempt).total_seconds() >= RELOGIN_RETRY_SEC):
            _last_relogin_attempt = now
            if scraper.auto_login(page):
                _log_login_event("✅ 자동 재로그인 성공")
                _login_ok = True
                _dropped_at = None
                _last_relogin_attempt = None
            else:
                _log_login_event(f"❌ 자동 재로그인 실패 — {RELOGIN_RETRY_SEC // 60}분 후 재시도")
        return

    if not _login_ok:
        down_for = datetime.now() - _dropped_at
        _log_login_event(f"✅ 로그인 복구됨 (풀린 채로 {down_for} 경과)")
        _login_ok = True
        _dropped_at = None
        _last_relogin_attempt = None

    # 화이트리스트 필터 (config.PRODUCTS 에 있는 상품만) + 표시 이름으로 치환
    rows = []
    for it in items:
        if it["id"] not in config.PRODUCTS:
            continue
        display_name = config.PRODUCTS[it["id"]]
        rows.append([_now(), it["id"], display_name, it["option"], it["price"], it["stock"]])

    print(f"[{_now()}] 화이트리스트 필터 적용 → {len(rows)}개 옵션 수집 (전체 {len(items)}개 중)")

    if diagnostic:
        sheets.append_diag_rows(rows)
    else:
        sheets.append_stock_rows(rows)


def _connect_with_retry(interval):
    """Chrome 연결 + 로그인. 둘 다 될 때까지 interval 초마다 재시도."""
    while True:
        try:
            pw, browser, page = scraper.connect()
            scraper.ensure_login(page)
            return pw, browser, page
        except Exception:
            print(f"[{_now()}] 연결/로그인 실패 — {interval}초 후 재시도")
            time.sleep(interval)


def main():
    diagnostic = config.DIAGNOSTIC_MODE
    interval = config.DIAGNOSTIC_INTERVAL_SEC if diagnostic else config.POLL_INTERVAL_SEC
    mode = "진단 모드(갱신주기 탐지)" if diagnostic else "수집 모드"
    print(f"=== 쿠팡 재고 추적기 시작 | {mode} | {interval}초 간격 ===")

    pw, browser, page = _connect_with_retry(interval)
    counter = 0
    while True:
        try:
            run_cycle(page, diagnostic)
            if not diagnostic:
                counter += 1
                if counter % config.RECALC_EVERY_N_CYCLES == 0:
                    n = calc.rebuild_sales()
                    print(f"[{_now()}] 추정판매 {n}행 갱신")
        except Exception as e:
            print(f"[{_now()}] 오류 발생 (루프는 계속):")
            traceback.print_exc()
            if _is_connection_lost(e):
                print(f"[{_now()}] 크롬 연결 끊김 — 재연결 시도")
                scraper.disconnect(pw, browser)
                pw, browser, page = _connect_with_retry(interval)
                print(f"[{_now()}] 재연결 성공, 수집 재개")
        time.sleep(interval)


if __name__ == "__main__":
    main()
