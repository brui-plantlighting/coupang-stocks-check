import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import plotly.express as px

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


@st.cache_resource
def _sheet():
    creds = Credentials.from_service_account_info(
        st.secrets["GOOGLE_CREDS"], scopes=SCOPES
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(config.SHEET_ID)


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


# ── 페이지 설정 ──────────────────────────────────────────────
st.set_page_config(page_title="쿠팡 재고 현황", layout="wide")
st.title("쿠팡 재고 현황")

df = load_stock()

if df.empty:
    st.warning("수집된 데이터가 없습니다. main.py가 실행 중인지 확인하세요.")
    st.stop()

df["수집시각"] = pd.to_datetime(df["수집시각"], errors="coerce")
df["재고량"] = pd.to_numeric(df["재고량"], errors="coerce").fillna(0).astype(int)

# ── 현재 재고 테이블 ─────────────────────────────────────────
st.subheader("현재 재고")

latest = (
    df.sort_values("수집시각")
    .groupby(["상품ID", "옵션"], as_index=False)
    .last()[["상품명", "옵션", "재고량", "수집시각"]]
    .sort_values(["상품명", "옵션"])
    .reset_index(drop=True)
)
latest["수집시각"] = latest["수집시각"].dt.strftime("%Y-%m-%d %H:%M")

st.dataframe(
    latest,
    use_container_width=True,
    hide_index=True,
    column_config={
        "재고량": st.column_config.NumberColumn("재고량", format="%d개"),
    },
)
st.caption(f"마지막 수집: {df['수집시각'].max().strftime('%Y-%m-%d %H:%M')}")

st.divider()

# ── 상품별 재고 추이 ──────────────────────────────────────────
st.subheader("상품별 재고 추이")

product_names = sorted(latest["상품명"].unique())
selected = st.selectbox("상품 선택", product_names)

prod_df = df[df["상품명"] == selected].sort_values("수집시각")

if not prod_df.empty:
    fig = px.line(
        prod_df,
        x="수집시각",
        y="재고량",
        color="옵션",
        markers=True,
        title=f"{selected} — 재고 추이",
    )
    fig.update_layout(yaxis_title="재고량 (개)", xaxis_title="")
    st.plotly_chart(fig, use_container_width=True)

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
        fig2 = px.bar(
            prod_sales,
            x="날짜",
            y="추정판매수량",
            color="옵션",
            title=f"{selected} — 일별 추정 판매",
        )
        fig2.update_layout(yaxis_title="판매량 (개)", xaxis_title="")
        st.plotly_chart(fig2, use_container_width=True)

        total = prod_sales["추정판매수량"].sum()
        st.metric("누적 추정 판매", f"{total:,}개")
