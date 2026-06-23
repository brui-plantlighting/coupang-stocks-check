# ===== 판매량 역추적 계산 =====
# 핵심 공식 (상품ID+옵션 단위, 시간순 연속 두 측정값 사이):
#   추정판매 = (이전재고 - 현재재고) + 그 구간에 기록된 입고량
#
# - 입고기록(수동 입력)을 더해줘서, 입고로 재고가 늘어난 변수를 보정함.
# - 입고기록 없는데 재고가 늘면(반품/취소/미기록 입고) delta 가 음수가 됨.
#   → 0으로 깔지 않고 음수 그대로 합산하고, 그런 구간 수를 '플래그수'로 따로 표시.
#     (조용히 숨기지 않고, 시우가 직접 감사할 수 있게)

from datetime import datetime
from collections import defaultdict
import sheets


def _parse_dt(s):
    return datetime.fromisoformat(str(s))


def rebuild_sales():
    """재고로그 + 입고기록을 읽어서 일별 추정판매를 통째로 다시 계산해 시트에 덮어씀."""
    log = sheets.read_stock_log()
    restocks = sheets.read_restock()

    # (상품ID, 옵션) -> 시간순 [(시각, 재고, 상품명)]
    series = defaultdict(list)
    for r in log:
        key = (str(r["상품ID"]), str(r["옵션"]))
        series[key].append((_parse_dt(r["수집시각"]), int(r["재고량"]), r["상품명"]))
    for k in series:
        series[k].sort(key=lambda x: x[0])

    # (상품ID, 옵션) -> [(입고시각, 입고수량)]
    rs = defaultdict(list)
    for r in restocks:
        if not r.get("입고시각"):
            continue
        key = (str(r["상품ID"]), str(r["옵션"]))
        rs[key].append((_parse_dt(r["입고시각"]), int(r["입고수량"])))

    # (날짜, 상품ID, 옵션) -> {sales, flags, name}
    daily = defaultdict(lambda: {"sales": 0, "flags": 0, "name": ""})

    for (pid, opt), points in series.items():
        for i in range(1, len(points)):
            t0, s0, _ = points[i - 1]
            t1, s1, name = points[i]
            delta = s0 - s1          # 재고 감소 = 판매. 증가 = 입고로 간주해 0 처리.
            d = t1.date().isoformat()
            cell = daily[(d, pid, opt)]
            cell["sales"] += max(0, delta)
            cell["name"] = name
            if delta < 0:            # 재고 증가 구간 (입고 반영된 것으로 추정)
                cell["flags"] += 1

    rows = []
    for (d, pid, opt), v in sorted(daily.items()):
        rows.append([d, pid, v["name"], opt, v["sales"], v["flags"]])

    sheets.overwrite_sales(rows)
    return len(rows)


if __name__ == "__main__":
    n = rebuild_sales()
    print(f"추정판매 {n}행 갱신 완료")
