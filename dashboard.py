import json
from datetime import date, timedelta

import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
H_PLAN = ["입력시각", "상품ID", "상품명", "옵션", "입고예정일", "입고수량", "메모"]


@st.cache_resource
def _sheet():
    creds_info = json.loads(st.secrets["GOOGLE_CREDS"])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    return gc.open_by_key(config.SHEET_ID)


def _ws(tab, headers):
    sh = _sheet()
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=2000, cols=20)
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws


def _ws_write(tab, headers):
    """쓰기 전용 — 매번 새 연결로 최신 시트 목록 사용."""
    creds_info = json.loads(st.secrets["GOOGLE_CREDS"])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=2000, cols=20)
        ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws


@st.cache_data(ttl=300)
def load_stock() -> pd.DataFrame:
    sh = _sheet()
    for tab in [config.TAB_STOCK_LOG, config.TAB_DIAG]:
        try:
            ws = sh.worksheet(tab)
            df = pd.DataFrame(ws.get_all_records())
            if not df.empty:
                return df
        except Exception:
            continue
    return pd.DataFrame()


@st.cache_data(ttl=300)
def load_sales() -> pd.DataFrame:
    try:
        ws = _sheet().worksheet(config.TAB_SALES)
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_restock_plan() -> pd.DataFrame:
    try:
        ws = _ws(config.TAB_RESTOCK_PLAN, H_PLAN)
        df = pd.DataFrame(ws.get_all_records())
        if not df.empty:
            df["입고예정일"] = pd.to_datetime(df["입고예정일"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


# ── 페이지 설정 ───────────────────────────────────────────────
st.set_page_config(page_title="쿠팡 재고 현황", layout="wide")
st.title("쿠팡 재고 현황")

df = load_stock()

if df.empty:
    st.warning("수집된 데이터가 없습니다. main.py가 실행 중인지 확인하세요.")
    st.stop()

df["수집시각"] = pd.to_datetime(df["수집시각"], errors="coerce")
df["재고량"] = pd.to_numeric(df["재고량"], errors="coerce").fillna(0).astype(int)

# ── 현재 재고 테이블 ──────────────────────────────────────────
st.subheader("현재 재고")

latest = (
    df.sort_values("수집시각")
    .groupby(["상품ID", "옵션"], as_index=False)
    .last()[["상품ID", "상품명", "옵션", "재고량", "수집시각"]]
    .sort_values(["상품명", "옵션"])
    .reset_index(drop=True)
)
latest_display = latest[["상품명", "옵션", "재고량", "수집시각"]].copy()
latest_display["수집시각"] = latest_display["수집시각"].dt.strftime("%Y-%m-%d %H:%M")

st.dataframe(
    latest_display,
    use_container_width=True,
    hide_index=True,
    column_config={"재고량": st.column_config.NumberColumn("재고량", format="%d개")},
)
st.caption(f"마지막 수집: {df['수집시각'].max().strftime('%Y-%m-%d %H:%M')}")

st.divider()

# ── 상품 선택 ─────────────────────────────────────────────────
product_names = sorted(latest["상품명"].unique())
selected = st.selectbox("상품 선택", product_names)

selected_id = latest[latest["상품명"] == selected]["상품ID"].iloc[0]
prod_df = df[df["상품명"] == selected].sort_values("수집시각").reset_index(drop=True)

# ── 재고 추이 차트 ────────────────────────────────────────────
st.subheader("재고 추이")

plan_df = load_restock_plan()

if not prod_df.empty:
    options = prod_df["옵션"].unique()
    fig = go.Figure()

    for opt in options:
        opt_df = prod_df[prod_df["옵션"] == opt].copy()
        opt_df["재고증가"] = opt_df["재고량"].diff() > 0

        # 기본 재고 라인
        fig.add_trace(go.Scatter(
            x=opt_df["수집시각"], y=opt_df["재고량"],
            mode="lines+markers", name=opt if opt else "기본",
            line=dict(width=2),
        ))

        # 입고 감지 마커 (▲)
        restock_pts = opt_df[opt_df["재고증가"]]
        if not restock_pts.empty:
            fig.add_trace(go.Scatter(
                x=restock_pts["수집시각"], y=restock_pts["재고량"],
                mode="markers", name=f"입고 감지 ({opt})" if opt else "입고 감지",
                marker=dict(symbol="triangle-up", size=14, color="green"),
                showlegend=True,
            ))

    # 입고 예정일 점선
    if not plan_df.empty:
        prod_plan = plan_df[plan_df["상품ID"] == str(selected_id)]
        for _, row in prod_plan.iterrows():
            if pd.isna(row["입고예정일"]):
                continue
            label = f"입고 예정 {row['입고예정일'].strftime('%m/%d')} ({row['옵션'] or '전체'} {row['입고수량']}개)"
            fig.add_vline(
                x=row["입고예정일"].timestamp() * 1000,
                line_dash="dash", line_color="orange",
                annotation_text=label,
                annotation_position="top left",
            )

    fig.update_layout(yaxis_title="재고량 (개)", xaxis_title="", legend_title="옵션")
    st.plotly_chart(fig, use_container_width=True)

# ── 입고 예정 입력 ────────────────────────────────────────────
with st.expander("입고 예정 입력"):
    with st.form("restock_form", clear_on_submit=True):
        opts = ["(전체)"] + [o for o in prod_df["옵션"].unique() if o]
        sel_opt = st.selectbox("옵션", opts)
        plan_date = st.date_input("입고 예정일", value=date.today() + timedelta(days=7))
        qty = st.number_input("입고 수량", min_value=1, step=1, value=100)
        memo = st.text_input("메모 (선택)")
        submitted = st.form_submit_button("저장")

    if submitted:
        from datetime import datetime
        ws = _ws_write(config.TAB_RESTOCK_PLAN, H_PLAN)
        ws.append_row([
            datetime.now().isoformat(timespec="seconds"),
            selected_id,
            selected,
            "" if sel_opt == "(전체)" else sel_opt,
            plan_date.isoformat(),
            int(qty),
            memo,
        ], value_input_option="USER_ENTERED")
        load_restock_plan.clear()
        st.success(f"{plan_date} 입고 예정 {qty}개 저장됨")
        st.rerun()

st.divider()

# ── 추정 판매량 ───────────────────────────────────────────────
st.subheader("추정 판매량")

sales_df = load_sales()

if sales_df.empty:
    st.info("아직 추정 판매 데이터가 없습니다. 진단 모드를 끄고 며칠 수집 후 생성됩니다.")
else:
    sales_df["날짜"] = pd.to_datetime(sales_df["날짜"], errors="coerce")
    sales_df["추정판매수량"] = pd.to_numeric(sales_df["추정판매수량"], errors="coerce").fillna(0).astype(int)

    prod_sales = sales_df[sales_df["상품명"] == selected].sort_values("날짜")

    if prod_sales.empty:
        st.info("선택한 상품의 판매 데이터가 없습니다.")
    else:
        date_min = prod_sales["날짜"].min().date()
        date_max = prod_sales["날짜"].max().date()

        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("시작일", value=date_min, min_value=date_min, max_value=date_max)
        with col2:
            end_date = st.date_input("종료일", value=date_max, min_value=date_min, max_value=date_max)

        if start_date > end_date:
            st.error("시작일이 종료일보다 늦을 수 없어요.")
            st.stop()

        filtered = prod_sales[
            (prod_sales["날짜"].dt.date >= start_date) &
            (prod_sales["날짜"].dt.date <= end_date)
        ]

        fig2 = go.Figure()
        for opt in filtered["옵션"].unique():
            opt_s = filtered[filtered["옵션"] == opt]
            fig2.add_trace(go.Bar(x=opt_s["날짜"], y=opt_s["추정판매수량"], name=opt if opt else "기본"))

        fig2.update_layout(
            barmode="stack", yaxis_title="판매량 (개)", xaxis_title="",
            title=f"{selected} — 일별 추정 판매",
        )
        st.plotly_chart(fig2, use_container_width=True)

        total = filtered["추정판매수량"].sum()
        days = (end_date - start_date).days + 1
        st.metric("기간 합계", f"{total:,}개", help=f"{start_date} ~ {end_date} ({days}일)")
