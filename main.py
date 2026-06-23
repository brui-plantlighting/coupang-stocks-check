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


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _is_connection_lost(exc) -> bool:
    """크롬 탭/창/프로세스가 닫혀서 CDP 연결이 끊긴 경우인지 판별."""
    msg = str(exc)
    return "has been closed" in msg or "Connection closed" in msg


def run_cycle(page, diagnostic):
    items = scraper.scrape_stock(page)
    if items is None:
        print(f"[{_now()}] ⚠️ 로그인 풀림 — 그 컴퓨터의 크롬 창에서 다시 로그인하면 다음 사이클에 자동 복구됨")
        return

    # 화이트리스트 필터 (config.PRODUCTS 에 있는 상품만) + 표시 이름으로 치환
    rows = []
    for it in items:
        if it["id"] not in config.PRODUCTS:
            continue
        display_name = config.PRODUCTS[it["id"]]
        rows.append([_now(), it["id"], display_name, it["option"], it["price"], it["stock"]])

    # 필터가 살아있는지 확인용 로그 (쿠파일럿 때처럼)
    print(f"[{_now()}] 화이트리스트 필터 적용 → {len(rows)}개 옵션 수집 (전체 {len(items)}개 중)")

    if diagnostic:
        sheets.append_diag_rows(rows)
    else:
        sheets.append_stock_rows(rows)


def main():
    diagnostic = config.DIAGNOSTIC_MODE
    interval = config.DIAGNOSTIC_INTERVAL_SEC if diagnostic else config.POLL_INTERVAL_SEC
    mode = "진단 모드(갱신주기 탐지)" if diagnostic else "수집 모드"
    print(f"=== 쿠팡 재고 추적기 시작 | {mode} | {interval}초 간격 ===")

    pw, browser, page = scraper.connect()
    scraper.ensure_login(page)   # 처음 한 번만 사람이 직접 로그인
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
                while True:
                    try:
                        pw, browser, page = scraper.connect()
                        scraper.ensure_login(page)
                        print(f"[{_now()}] 재연결 성공, 수집 재개")
                        break
                    except Exception:
                        print(f"[{_now()}] 재연결 실패 — {interval}초 후 재시도 (크롬이 꺼져있다면 start_chrome.bat 으로 다시 켜주세요)")
                        time.sleep(interval)
        time.sleep(interval)


if __name__ == "__main__":
    main()
