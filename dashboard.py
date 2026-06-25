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
            df["상품ID"] = df["상품ID"].astype(str)
            df["입고예정일"] = pd.to_datetime(df["입고예정일"], errors="coerce")
        return df
    except Exception:
        return pd.DataFrame()


CHART_TEMPLATE = "plotly_white"
EXCLUDED_OPTION = "아이템 위너 : 미선정"


def _legend_top():
    return dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)


# ── 페이지 설정 ───────────────────────────────────────────────
st.set_page_config(page_title="쿠팡 재고 현황", layout="wide")

df = load_stock()

if df.empty:
    st.warning("수집된 데이터가 없습니다. main.py가 실행 중인지 확인하세요.")
    st.stop()

df["수집시각"] = pd.to_datetime(df["수집시각"], errors="coerce")
df["재고량"] = pd.to_numeric(df["재고량"], errors="coerce").fillna(0).astype(int)
df["상품ID"] = df["상품ID"].astype(str)
df = df[df["옵션"] != EXCLUDED_OPTION]

latest = (
    df.sort_values("수집시각")
    .groupby(["상품ID", "옵션"], as_index=False)
    .last()[["상품ID", "상품명", "옵션", "재고량", "수집시각"]]
    .sort_values(["상품명", "옵션"])
    .reset_index(drop=True)
)

# ── 사이드바: 상품 선택 + 현재 재고 ───────────────────────────
with st.sidebar:
    st.title("쿠팡 재고 현황")
    st.caption(f"마지막 수집  {df['수집시각'].max():%Y-%m-%d %H:%M}")

    product_names = sorted(latest["상품명"].unique())
    selected = st.selectbox("상품 선택", product_names)
    selected_id = latest[latest["상품명"] == selected]["상품ID"].iloc[0]

    st.divider()
    st.caption("현재 재고")
    selected_latest = latest[latest["상품명"] == selected].sort_values("옵션")
    for _, row in selected_latest.iterrows():
        with st.container(border=True):
            st.metric(row["옵션"] if row["옵션"] else "재고", f"{int(row['재고량'])}개")

prod_df = df[df["상품명"] == selected].sort_values("수집시각").reset_index(drop=True)
plan_df = load_restock_plan()

st.title(selected)

tab_trend, tab_daily, tab_restock, tab_sales, tab_raw = st.tabs(
    ["재고 추이", "일별 마감재고", "입고 관리", "추정 판매량", "전체 재고"]
)

# ── 재고 추이 ─────────────────────────────────────────────────
with tab_trend:
    period_df = prod_df
    if not prod_df.empty:
        date_min = prod_df["수집시각"].min().date()
        date_max = prod_df["수집시각"].max().date()

        col1, col2 = st.columns(2)
        with col1:
            stock_start = st.date_input("시작일", value=date_min, min_value=date_min, max_value=date_max, key="stock_start")
        with col2:
            stock_end = st.date_input("종료일", value=date_max, min_value=date_min, max_value=date_max, key="stock_end")

        if stock_start > stock_end:
            st.error("시작일이 종료일보다 늦을 수 없어요.")
            period_df = pd.DataFrame()
        else:
            period_df = prod_df[
                (prod_df["수집시각"].dt.date >= stock_start) &
                (prod_df["수집시각"].dt.date <= stock_end)
            ]

    if period_df.empty:
        st.caption("표시할 데이터가 없습니다.")
    else:
        fig = go.Figure()

        for opt in period_df["옵션"].unique():
            opt_df = period_df[period_df["옵션"] == opt].copy()
            opt_df["재고증가"] = opt_df["재고량"].diff() > 0

            fig.add_trace(go.Scatter(
                x=opt_df["수집시각"], y=opt_df["재고량"],
                mode="lines+markers", name=opt if opt else "기본",
                line=dict(width=2),
            ))

            restock_pts = opt_df[opt_df["재고증가"]]
            if not restock_pts.empty:
                fig.add_trace(go.Scatter(
                    x=restock_pts["수집시각"], y=restock_pts["재고량"],
                    mode="markers", name=f"입고 감지 ({opt})" if opt else "입고 감지",
                    marker=dict(symbol="triangle-up", size=14, color="green"),
                    showlegend=True,
                ))

        fig.update_layout(
            template=CHART_TEMPLATE,
            yaxis_title="재고량 (개)", xaxis_title="", legend_title="옵션",
            yaxis=dict(rangemode="tozero"),
            hovermode="x unified",
            legend=_legend_top(),
            margin=dict(t=40, l=10, r=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

# ── 일별 마감재고 ─────────────────────────────────────────────
with tab_daily:
    if prod_df.empty:
        st.caption("표시할 데이터가 없습니다.")
    else:
        daily = (
            prod_df.assign(날짜=prod_df["수집시각"].dt.date)
            .sort_values("수집시각")
            .groupby(["날짜", "옵션"], as_index=False)
            .last()[["날짜", "옵션", "재고량"]]
        )

        date_min = daily["날짜"].min()
        date_max = daily["날짜"].max()

        col1, col2 = st.columns(2)
        with col1:
            daily_start = st.date_input("시작일", value=date_min, min_value=date_min, max_value=date_max, key="daily_start")
        with col2:
            daily_end = st.date_input("종료일", value=date_max, min_value=date_min, max_value=date_max, key="daily_end")

        if daily_start > daily_end:
            st.error("시작일이 종료일보다 늦을 수 없어요.")
        else:
            daily_f = daily[(daily["날짜"] >= daily_start) & (daily["날짜"] <= daily_end)]

            fig3 = go.Figure()
            for opt in daily_f["옵션"].unique():
                opt_d = daily_f[daily_f["옵션"] == opt]
                fig3.add_trace(go.Scatter(
                    x=opt_d["날짜"], y=opt_d["재고량"],
                    mode="lines+markers", name=opt if opt else "기본",
                ))

            fig3.update_layout(
                template=CHART_TEMPLATE,
                yaxis_title="재고량 (개)", xaxis_title="", legend_title="옵션",
                yaxis=dict(rangemode="tozero"), hovermode="x unified",
                legend=_legend_top(), margin=dict(t=40, l=10, r=10, b=10),
            )
            st.plotly_chart(fig3, use_container_width=True)

            pivot = (
                daily_f.pivot(index="날짜", columns="옵션", values="재고량")
                .sort_index(ascending=False)
            )
            pivot.index = pivot.index.map(lambda d: d.strftime("%Y-%m-%d"))
            pivot.columns = [c if c else "기본" for c in pivot.columns]

            st.dataframe(
                pivot,
                use_container_width=True,
                column_config={
                    c: st.column_config.NumberColumn(c, format="%d개") for c in pivot.columns
                },
            )

# ── 입고 관리 ─────────────────────────────────────────────────
with tab_restock:
    col_list, col_form = st.columns([3, 2], gap="large")

    with col_list:
        st.subheader("입고 예정 목록")
        if plan_df.empty:
            st.caption("등록된 입고 예정이 없습니다.")
        else:
            prod_plan = plan_df[plan_df["상품ID"] == str(selected_id)].copy()
            if prod_plan.empty:
                st.caption("이 상품의 입고 예정이 없습니다.")
            else:
                edit_df = prod_plan[["입력시각", "입고예정일", "입고수량", "메모"]].copy()
                edit_df["입고예정일"] = edit_df["입고예정일"].dt.date

                edited = st.data_editor(
                    edit_df,
                    column_config={
                        "입력시각": st.column_config.Column("입력시각", disabled=True),
                        "메모":     st.column_config.Column("메모", disabled=True),
                        "입고예정일": st.column_config.DateColumn("입고 예정일"),
                        "입고수량":  st.column_config.NumberColumn("입고 수량", format="%d개", min_value=1),
                    },
                    hide_index=True,
                    use_container_width=True,
                )

                if st.button("변경사항 저장", key="save_plan"):
                    changed = []
                    for idx in edit_df.index:
                        if (edit_df.loc[idx, "입고예정일"] != edited.loc[idx, "입고예정일"] or
                                int(edit_df.loc[idx, "입고수량"]) != int(edited.loc[idx, "입고수량"])):
                            changed.append({
                                "입력시각":  edit_df.loc[idx, "입력시각"],
                                "입고예정일": str(edited.loc[idx, "입고예정일"]),
                                "입고수량":  int(edited.loc[idx, "입고수량"]),
                            })

                    if not changed:
                        st.info("변경사항이 없습니다.")
                    else:
                        ws = _ws_write(config.TAB_RESTOCK_PLAN, H_PLAN)
                        all_vals = ws.get_all_values()
                        headers = all_vals[0]
                        col_시각 = headers.index("입력시각")
                        col_날짜 = headers.index("입고예정일") + 1  # gspread는 1-based
                        col_수량 = headers.index("입고수량") + 1

                        for chg in changed:
                            for row_i, row in enumerate(all_vals[1:], start=2):
                                if row[col_시각] == chg["입력시각"]:
                                    ws.update_cell(row_i, col_날짜, chg["입고예정일"])
                                    ws.update_cell(row_i, col_수량, chg["입고수량"])
                                    break

                        load_restock_plan.clear()
                        st.success(f"{len(changed)}개 항목 수정됨")
                        st.rerun()

    with col_form:
        st.subheader("입고 예정 입력")
        with st.form("restock_form", clear_on_submit=True):
            plan_date = st.date_input("입고 예정일", value=date.today() + timedelta(days=7))
            qty = st.number_input("입고 수량", min_value=1, step=1, value=100)
            memo = st.text_input("메모 (선택)")
            submitted = st.form_submit_button("저장")
            if submitted:
                # 폼이 clear되기 전에 값을 세션 스테이트에 캡처
                st.session_state["_pending_plan"] = {
                    "date": plan_date, "qty": int(qty), "memo": memo,
                    "id": str(selected_id), "name": selected,
                }

    # 저장은 폼 밖에서 — 캡처된 값 사용
    if "_pending_plan" in st.session_state:
        from datetime import datetime
        p = st.session_state.pop("_pending_plan")
        ws = _ws_write(config.TAB_RESTOCK_PLAN, H_PLAN)
        ws.append_row([
            datetime.now().isoformat(timespec="seconds"),
            p["id"], p["name"], "",
            p["date"].isoformat(), p["qty"], p["memo"],
        ], value_input_option="USER_ENTERED")
        load_restock_plan.clear()
        st.success(f"{p['date']} 입고 예정 {p['qty']}개 저장됨")
        st.rerun()

# ── 추정 판매량 ───────────────────────────────────────────────
with tab_sales:
    sales_df = load_sales()

    if sales_df.empty:
        st.info("아직 추정 판매 데이터가 없습니다. 진단 모드를 끄고 며칠 수집 후 생성됩니다.")
    else:
        sales_df["날짜"] = pd.to_datetime(sales_df["날짜"], errors="coerce")
        sales_df["추정판매수량"] = pd.to_numeric(sales_df["추정판매수량"], errors="coerce").fillna(0).astype(int)
        sales_df = sales_df[sales_df["옵션"] != EXCLUDED_OPTION]

        prod_sales = sales_df[sales_df["상품명"] == selected].sort_values("날짜")

        if prod_sales.empty:
            st.info("선택한 상품의 판매 데이터가 없습니다.")
        else:
            date_min = prod_sales["날짜"].min().date()
            date_max = prod_sales["날짜"].max().date()

            col1, col2 = st.columns(2)
            with col1:
                start_date = st.date_input("시작일", value=date_min, min_value=date_min, max_value=date_max, key="sales_start")
            with col2:
                end_date = st.date_input("종료일", value=date_max, min_value=date_min, max_value=date_max, key="sales_end")

            if start_date > end_date:
                st.error("시작일이 종료일보다 늦을 수 없어요.")
            else:
                filtered = prod_sales[
                    (prod_sales["날짜"].dt.date >= start_date) &
                    (prod_sales["날짜"].dt.date <= end_date)
                ]

                total = filtered["추정판매수량"].sum()
                days = (end_date - start_date).days + 1
                st.metric("기간 합계", f"{total:,}개", help=f"{start_date} ~ {end_date} ({days}일)")

                fig2 = go.Figure()
                for opt in filtered["옵션"].unique():
                    opt_s = filtered[filtered["옵션"] == opt]
                    fig2.add_trace(go.Bar(x=opt_s["날짜"], y=opt_s["추정판매수량"], name=opt if opt else "기본"))

                fig2.update_layout(
                    template=CHART_TEMPLATE,
                    barmode="stack", yaxis_title="판매량 (개)", xaxis_title="",
                    legend=_legend_top(),
                    margin=dict(t=40, l=10, r=10, b=10),
                )
                st.plotly_chart(fig2, use_container_width=True)

# ── 전체 재고 (원본) ──────────────────────────────────────────
with tab_raw:
    st.caption(f"마지막 수집: {df['수집시각'].max():%Y-%m-%d %H:%M}")
    latest_display = latest[["상품명", "옵션", "재고량", "수집시각"]].copy()
    latest_display["수집시각"] = latest_display["수집시각"].dt.strftime("%Y-%m-%d %H:%M")

    st.dataframe(
        latest_display,
        use_container_width=True,
        hide_index=True,
        column_config={"재고량": st.column_config.NumberColumn("재고량", format="%d개")},
    )
