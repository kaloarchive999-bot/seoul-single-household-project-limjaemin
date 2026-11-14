"""두 업로드 원본 전용 대시보드. 실행: python -m streamlit run app.py"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pypdf import PdfReader
from shapely.geometry import shape

BASE = Path(__file__).resolve().parent
DATA = BASE
CSV_SHA = "df180d9e1509f3a63ed64d878d1d1a060067ba2b4399a13061b9a8a2e97aa321"
PDF_SHA = "0f74d8fff2d094d16a6f9034a595fcd0b0ebea711dc809a76ac45316f5d101f3"
CSV_NAME = "1인가구(연령별)_20261114125316.csv"
PDF_NAME = "2025+통계로+보는+1인가구.pdf"
DISTRICTS = "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()
REGIONS = "서울 부산 대구 인천 광주 대전 울산 세종 경기 강원 충북 충남 전북 전남 경북 경남 제주".split()
REGION_NAMES = dict(zip(REGIONS, "서울특별시 부산광역시 대구광역시 인천광역시 광주광역시 대전광역시 울산광역시 세종특별자치시 경기도 강원도 충청북도 충청남도 전라북도 전라남도 경상북도 경상남도 제주특별자치도".split()))
RAW_AGES = ["20세미만", "20~24세", "25~29세", "30~34세", "35~39세", "40~44세", "45~49세", "50~54세", "55~59세", "60~64세", "65~69세", "70~74세", "75~79세", "80~84세", "85세이상"]
GROUPS = {
    "20세 미만": ["20세미만"],
    "20대": ["20~24세", "25~29세"],
    "30대": ["30~34세", "35~39세"],
    "40대": ["40~44세", "45~49세"],
    "50대": ["50~54세", "55~59세"],
    "60대": ["60~64세", "65~69세"],
    "70세 이상": ["70~74세", "75~79세", "80~84세", "85세이상"],
}
NATIONAL_AGES = ["29세 이하", "30~39세", "40~49세", "50~59세", "60~69세", "70세 이상"]
COLORS = {a: c for a, c in zip(GROUPS, ["#94a3b8", "#2563eb", "#0891b2", "#059669", "#d97706", "#dc2626", "#9333ea"])}


class DataError(ValueError):
    """원자료 이상: 보정/대체하지 않고 분석을 중단한다."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataError(message)


def verify_source(blob: bytes, digest: str, label: str) -> None:
    require(hashlib.sha256(blob).hexdigest() == digest,
            f"{label}: 이번에 검토한 업로드 원본과 SHA-256이 다릅니다. 원본 파일을 사용하세요. 자동 수정하지 않습니다.")


def load_csv(blob: bytes) -> tuple[pd.DataFrame, list[list[str]], str]:
    """원본 바이트 보존. 누락/문자/불일치는 오류, 0/평균/null로 대체하지 않음."""
    text = None
    used_encoding = ""
    for encoding in ("utf-8-sig", "cp949"):
        try:
            text = blob.decode(encoding, errors="strict")
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    require(text is not None, "CSV 인코딩을 해석할 수 없습니다.")
    rows = list(csv.reader(io.StringIO(text)))
    require(len(rows) == 81, f"CSV 행 수가 다릅니다: {len(rows)}행, 기대값 81행.")
    require(all(len(r) == 19 for r in rows), "CSV는 모든 행이 19열이어야 합니다.")
    require(rows[0][:3] == ["자치구별(1)", "자치구별(2)", "성별(1)"], "CSV 식별 헤더 불일치.")
    require(set(rows[0][3:]) == {"2025"}, "연도 헤더가 2025년과 다릅니다.")
    require(rows[1][:3] == rows[0][:3] and set(rows[1][3:]) == {"합계"}, "CSV 두 번째 헤더 불일치.")
    require(rows[2] == rows[0][:3] + ["소계"] + RAW_AGES, "CSV 연령 열/순서 불일치.")
    parsed = []
    for line, row in enumerate(rows[3:], start=4):
        require(row[0] == "합계", f"{line}행: 첫 지역 분류가 합계가 아닙니다.")
        require(row[1] in DISTRICTS + ["소계"], f"{line}행: 미등록 자치구 {row[1]!r}.")
        require(row[2] in ["계", "남자", "여자"], f"{line}행: 알 수 없는 성별.")
        values = []
        for col, cell in zip(["합계"] + RAW_AGES, row[3:]):
            require(re.fullmatch(r"[0-9]+", cell) is not None,
                    f"{line}행 {col}: 비정상 값 {cell!r}. 결측/문자를 0으로 바꾸지 않습니다.")
            values.append(int(cell))
        require(values[0] == sum(values[1:]), f"{line}행: 합계와 연령별 합이 다릅니다.")
        parsed.append([row[0], row[1], row[2]] + values)
    frame = pd.DataFrame(parsed, columns=["지역분류", "자치구", "성별", "합계"] + RAW_AGES)
    require(not frame.duplicated(["자치구", "성별"]).any(), "자치구·성별 중복 행이 있습니다.")
    numeric = ["합계"] + RAW_AGES
    for district in ["소계"] + DISTRICTS:
        subset = frame[frame["자치구"].eq(district)].set_index("성별")
        require(set(subset.index) == {"계", "남자", "여자"}, f"{district}: 성별 행 누락.")
        require((subset.loc["계", numeric] == subset.loc["남자", numeric] + subset.loc["여자", numeric]).all(),
                f"{district}: 계 ≠ 남자 + 여자.")
    for sex in ["계", "남자", "여자"]:
        part = frame[frame["성별"].eq(sex)]
        total = part.loc[part["자치구"].eq("소계"), numeric].iloc[0]
        actual = part.loc[~part["자치구"].eq("소계"), numeric].sum()
        require((total == actual).all(), f"{sex}: 서울 소계와 25개 구 합이 다릅니다.")
    return frame, rows, used_encoding


def group_seoul(frame: pd.DataFrame, sex: str = "계") -> pd.DataFrame:
    source = frame[frame["성별"].eq(sex) & ~frame["자치구"].eq("소계")].copy()
    out = source[["자치구", "성별", "합계"]].copy()
    for label, columns in GROUPS.items():
        out[label] = source[columns].sum(axis=1)
    require((out[list(GROUPS)].sum(axis=1) == out["합계"]).all(), "연령 재집계 검증 실패.")
    return out


def select_seoul(grouped: pd.DataFrame, ages: list[str]) -> pd.DataFrame:
    require(bool(ages) and set(ages).issubset(GROUPS), "연령 선택이 유효하지 않습니다.")
    out = grouped[["자치구", "성별", "합계"]].copy()
    out["선택연령_가구수"] = grouped[ages].sum(axis=1)
    require((out["합계"] > 0).all(), "분모가 0인 자치구는 비율을 산출할 수 없습니다.")
    out["구내_선택연령비중_pct"] = out["선택연령_가구수"] / out["합계"] * 100
    return out


def pdf_table(text: str, columns: list[str]) -> pd.DataFrame:
    """PDF의 검증된 고정 표에서 지역 행만 읽음. OCR/추정/반올림 보정 없음."""
    records = []
    names = ["전국"] + REGIONS
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or tokens[0] not in names:
            continue
        require(len(tokens) == len(columns) + 1, f"PDF {tokens[0]}: 열 개수 불일치.")
        for token in tokens[1:]:
            require(re.fullmatch(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?", token) is not None,
                    f"PDF 숫자 해석 실패: {token!r}")
        records.append([tokens[0]] + tokens[1:])
    require([r[0] for r in records] == names, "PDF 지역 행 누락/중복/순서 불일치.")
    # 처음에는 표기 문자열을 보존하고, 그래프용 숫자는 별도의 명시적 변환으로 생성한다.
    return pd.DataFrame(records, columns=["지역"] + columns)


def load_pdf(blob: bytes) -> tuple[pd.DataFrame, pd.DataFrame]:
    verify_source(blob, PDF_SHA, "PDF")
    reader = PdfReader(io.BytesIO(blob))
    require(len(reader.pages) == 77, "PDF 페이지 수가 원본과 다릅니다.")
    totals = pdf_table(reader.pages[50].extract_text(extraction_mode="layout"),
                       ["전체가구_천가구", "전체가구_전국분포_pct", "1인가구_천가구", "1인가구_전국분포_pct"])
    shares = pdf_table(reader.pages[51].extract_text(extraction_mode="layout"), NATIONAL_AGES)
    require(totals.iloc[0]["1인가구_천가구"] == "8,045", "PDF 전국 전체 셀 검증 실패.")
    require(shares.iloc[1]["29세 이하"] == "29.5", "PDF 서울 연령 분포 셀 검증 실패.")
    require((shares.iloc[0, 1:] == "100.0").all(), "PDF 전국 분포 분모 검증 실패.")
    return totals, shares


@lru_cache(maxsize=2)
def geometry(kind: str) -> dict:
    """SGIS 기반 2020 경계. 표시용이며 통계 집계/연도 결합에 쓰지 않음."""
    require(kind in ["seoul", "provinces"], "지도 종류 오류.")
    obj = json.loads((DATA / f"{kind}_2020.json").read_text(encoding="utf-8"))
    features = obj["features"]
    lookup = {f["properties"]["title"]: shape(f["geometry"]) for f in features}
    require(len(lookup) == len(features), "지도 경계 이름 중복.")
    expected = DISTRICTS if kind == "seoul" else list(REGION_NAMES.values())
    require(set(lookup) == set(expected), "지도 지역과 통계 지역의 명칭 대응이 불완전합니다.")
    require(all(not g.is_empty and g.geom_type in ["Polygon", "MultiPolygon"] for g in lookup.values()), "비정상 지도 도형.")
    # 이 참고 경계에는 원본부터 일부 자기접촉이 있다. buffer/make_valid로 수정하지 않는다.
    # 윤곽 렌더링과 대표점 표시에만 사용하며 면적/공간결합/통계 추정에는 사용하지 않는다.
    # 원본 경계 파일은 그대로 보관. 단순화는 화면 윤곽선에만 적용한다.
    # 좌표는 SGIS UTM-K 투영 좌표 그대로 사용하므로 위경도를 임의로 만들지 않는다.
    return lookup


def bubble_map(df: pd.DataFrame, region_col: str, value_col: str, kind: str,
               title: str, unit: str, scale_max: float | None = None) -> go.Figure:
    lookup = geometry(kind)
    fig = go.Figure()
    xs, ys = [], []
    for geom in lookup.values():
        display = geom.simplify(200, preserve_topology=True)
        polygons = [display] if display.geom_type == "Polygon" else list(display.geoms)
        for polygon in polygons:
            rings = [polygon.exterior] + list(polygon.interiors)
            for ring in rings:
                x, y = ring.xy
                xs.extend(list(x) + [None])
                ys.extend(list(y) + [None])
    # None은 통계값이 아니라 서로 떨어진 지도 윤곽선 사이를 끊는 Plotly 제어값이다.
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color="#94a3b8", width=.65),
                             hoverinfo="skip", showlegend=False))
    xpoints, ypoints = [], []
    for name in df[region_col]:
        key = name if kind == "seoul" else REGION_NAMES[name]
        require(key in lookup, f"지도 대응 없음: {name}")
        point = lookup[key].representative_point()
        xpoints.append(point.x)
        ypoints.append(point.y)
    values = df[value_col].astype(float).tolist()
    require(all(math.isfinite(v) and v >= 0 for v in values), "지도 수치에 비정상 값이 있습니다.")
    vmax = scale_max if scale_max is not None else max(values)
    require(vmax > 0, "전체가 0인 자료는 크기 지도를 만들 수 없습니다.")
    fmt = ",.0f" if unit == "가구" else ",.1f" if unit == "%" else ",.0f"
    fig.add_trace(go.Scatter(
        x=xpoints, y=ypoints, mode="markers", text=df[region_col],
        customdata=[[v] for v in values],
        marker=dict(size=values, sizemode="area", sizeref=2 * vmax / (42 ** 2),
                    color=values, cmin=0, cmax=vmax, colorscale="Blues", opacity=.85,
                    colorbar=dict(title=unit, thickness=12), line=dict(color="white", width=1)),
        hovertemplate=f"<b>%{{text}}</b><br>{value_col}: %{{customdata[0]:{fmt}}} {unit}<extra></extra>",
        showlegend=False,
    ))
    fig.update_layout(title=title, height=550, template="plotly_white", dragmode="pan",
                      margin=dict(l=5, r=5, t=55, b=5), paper_bgcolor="#ffffff",
                      xaxis=dict(visible=False),
                      yaxis=dict(visible=False, scaleanchor="x", scaleratio=1))
    return fig


def download_table(df: pd.DataFrame, name: str, label: str = "현재 표 CSV 다운로드") -> None:
    st.download_button(label, df.to_csv(index=False).encode("utf-8-sig"), name,
                       mime="text/csv", key=f"download_{name}")


def source_bytes(upload, filename: str) -> bytes:
    if upload is not None:
        return upload.getvalue()
    path = DATA / filename
    require(path.exists(), f"기본 파일 {filename}이 없습니다. 사이드바에서 검토한 원본을 업로드하세요.")
    return path.read_bytes()


def main() -> None:
    st.set_page_config(page_title="1인가구 | 확인된 분포만", page_icon="🗺️", layout="wide")
    st.title("1인가구, 어디에 많이 거주할까")
    st.caption("원본 통계와 파생 합계를 구분합니다 · 전국/서울의 연도·연령 구간을 섞지 않습니다")
    with st.sidebar:
        st.header("분석 설정")
        mode = st.radio("분석 범위", ["서울 자치구 · 2025", "전국 시도 · 2024", "경제·사회 참고 통계"])
        with st.expander("원본 파일 재선택"):
            csv_upload = st.file_uploader("검토한 CSV 원본", type=["csv"])
            pdf_upload = st.file_uploader("검토한 PDF 원본", type=["pdf"])
        st.caption("두 원본과 SHA-256 일치 시에만 분석합니다. 임의의 다른 파일은 자동으로 맞추지 않습니다.")
    try:
        csv_bytes = source_bytes(csv_upload, "source.csv")
        pdf_bytes = source_bytes(pdf_upload, "source.pdf")
        verify_source(csv_bytes, CSV_SHA, "CSV")
        frame, original_rows, encoding = load_csv(csv_bytes)
        totals, shares = load_pdf(pdf_bytes)
        render(mode, frame, totals, shares, csv_bytes, pdf_bytes)
    except (DataError, OSError, ValueError, KeyError, IndexError) as exc:
        st.error(f"분석 중단 — {exc}")
        st.info("원본을 수정하거나 누락값을 0/null로 대체하지 않았습니다. 파일 및 구조를 확인하세요.")
        st.stop()
    with st.expander("검증·해석 기준 및 원본 다운로드"):
        st.write("CSV 검증: 3개 헤더·78개 데이터 행·19열, 25개 구+서울 소계, 계/남자/여자, 모든 연령합·성별합·지역합 일치.")
        st.write(f"CSV 인코딩: {encoding}. 원본 합계: 1,699,910가구. 결측 대체·중복 제거·추정값 생성 없음.")
        st.write("PDF: 물리 페이지 51~52(인쇄 46~47쪽) 표 직접 추출. 전국 천 가구 단위와 소수 첫째 자리 비중은 원문 반올림값이며, 합계를 100%에 맞추지 않습니다.")
        st.warning("지도는 가구의 실제 주소/밀도 지도가 아닙니다. 지역별 집계를 지역 내부 대표점 1개로 표시합니다. 인구·면적 대비 밀도 및 빈곤율은 산출하지 않습니다.")
        st.markdown("지도 윤곽: [statgarten/maps](https://github.com/statgarten/maps)의 SGIS 기반 **2020년 참고 경계**. 화면 윤곽만 200m 허용오차로 단순화하며 원본 파일은 보존합니다. 2024·2025년 법정 경계를 보증하지 않으며 공간 재집계에는 사용하지 않습니다. 대구 등 경계 변동도 반영하지 않으므로 최신 행정경계 지도로 해석하면 안 됩니다. 참고 경계 원본의 일부 자기접촉은 자동 복구하지 않습니다. 강원/전북은 원문 약칭과 2020 경계 명칭을 표시용으로만 대응합니다.")
        st.code(f"CSV SHA-256: {CSV_SHA}\nPDF SHA-256: {PDF_SHA}", language="text")
        st.download_button("CSV 원본 그대로 다운로드", csv_bytes, CSV_NAME, "text/csv", key="raw_csv")
        st.download_button("PDF 원본 그대로 다운로드", pdf_bytes, PDF_NAME, "application/pdf", key="raw_pdf")


def render(mode, frame, totals, shares, csv_bytes, pdf_bytes):
    if mode == "서울 자치구 · 2025":
        render_seoul(frame)
    elif mode == "전국 시도 · 2024":
        render_national(totals, shares)
    else:
        render_context()


def render_seoul(frame: pd.DataFrame) -> None:
    ages = st.sidebar.multiselect("연령대 · 다중 선택", list(GROUPS), default=["20대", "30대", "40대", "50대", "60대"])
    sex = st.sidebar.radio("성별", ["계", "남자", "여자"], horizontal=True)
    metric = st.sidebar.radio("표시 지표", ["가구 수", "구내 선택연령 비중"])
    st.info("서울 25개 구 · CSV 머리글 2025년. 60대=60~69세입니다. 기준일·작성방식은 CSV에 없어 별도 원자료 설명 확인이 필요합니다.")
    if not ages:
        st.warning("왼쪽에서 연령대를 하나 이상 선택하면 지도와 표가 표시됩니다.")
        return
    grouped = group_seoul(frame, sex)
    selected = select_seoul(grouped, ages)
    count = int(selected["선택연령_가구수"].sum())
    city_total = int(selected["합계"].sum())
    top = selected.sort_values(["선택연령_가구수", "자치구"], ascending=[False, True]).iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("선택 연령 1인가구", f"{count:,} 가구")
    c2.metric("동일 성별 서울 1인가구 중 비중", f"{count / city_total * 100:.2f}%")
    leaders = selected.loc[selected["선택연령_가구수"].eq(top["선택연령_가구수"]), "자치구"].tolist()
    c3.metric("선택 연령 가구 수 최다", ", ".join(leaders))
    st.caption(f"선택 연령: {', '.join(ages)} · 성별: {sex} · 제외 연령 {city_total-count:,}가구는 원본에 보존되어 있습니다.")
    value = "선택연령_가구수" if metric == "가구 수" else "구내_선택연령비중_pct"
    unit = "가구" if metric == "가구 수" else "%"
    left, right = st.columns([1.2, 1])
    with left:
        st.plotly_chart(bubble_map(selected, "자치구", value, "seoul", f"선택 연령 합산 · {metric}", unit), width="stretch")
        st.caption("원 면적 ∝ 표시 지표. 한 구에 점 하나이며 선택한 연령의 정확한 합계입니다.")
    with right:
        detail = grouped.melt(id_vars=["자치구", "성별", "합계"], value_vars=ages, var_name="연령대", value_name="가구수")
        order = selected.sort_values([value, "자치구"], ascending=[True, True])["자치구"].tolist()
        if metric == "가구 수":
            fig = px.bar(detail, x="가구수", y="자치구", color="연령대", orientation="h", color_discrete_map=COLORS,
                         category_orders={"자치구": order[::-1], "연령대": ages}, title="25개 구 전체 · 연령별 가구 수")
        else:
            fig = px.bar(selected.sort_values(value), x=value, y="자치구", orientation="h", title="25개 구 전체 · 구내 선택연령 비중")
        fig.update_layout(height=580, margin=dict(l=0, r=0, t=50, b=0))
        st.plotly_chart(fig, width="stretch")
    st.caption("‘구내 선택연령 비중’ 분모는 해당 구·동일 성별의 전체 연령 1인가구입니다. 전체 일반가구 대비 1인가구 비율이 아닙니다.")
    st.subheader("선택 결과 · 합산/비율은 명시적 파생값")
    st.dataframe(selected.sort_values("선택연령_가구수", ascending=False), hide_index=True, width="stretch")
    download_table(selected, "서울_선택연령_집계.csv")
    with st.expander("모든 연령대 집계 · 제외 연령 포함"):
        st.dataframe(grouped, hide_index=True, width="stretch")
        download_table(grouped, "서울_전체연령_집계.csv")
    st.warning("경제적 어려움 가구의 위치/가구 수는 표시하지 않습니다. 자치구×연령×경제지표의 교차자료가 없습니다.")


def render_national(totals: pd.DataFrame, shares: pd.DataFrame) -> None:
    view = st.sidebar.radio("전국 표시 지표", ["전체 연령 가구 수", "연령별 전국 내 지역 분포"])
    st.info("전국 17개 시도 · 2024년 · PDF 표 3-1. 서울 CSV(2025년)와 합치지 않습니다.")
    if view == "전체 연령 가구 수":
        st.metric("전국 1인가구 · 원문 반올림값", "8,045 천 가구")
        st.caption("연령 필터가 적용되지 않는 전체 연령 값입니다. 천 가구 단위를 가구 단위의 정확한 수로 바꾸지 않습니다.")
        plot = totals.iloc[1:].copy()
        plot["1인가구_천가구"] = plot["1인가구_천가구"].str.replace(",", "", regex=False).astype(int)
        st.plotly_chart(bubble_map(plot, "지역", "1인가구_천가구", "provinces", "전국 1인가구 · 전체 연령 · 2024", "천 가구"), width="stretch")
        st.dataframe(totals, hide_index=True, width="stretch")
        download_table(totals, "전국_전체연령_PDF원문표기.csv")
    else:
        ages = st.sidebar.multiselect("PDF 연령구간 · 다중 선택", NATIONAL_AGES, default=NATIONAL_AGES[:5])
        st.warning("‘29세 이하’는 20세 미만을 포함하므로 ‘20대’가 아닙니다. 연령별 분모가 달라 여러 연령의 비율을 더하거나 가구 수로 역산하지 않습니다.")
        if not ages:
            st.warning("연령구간을 하나 이상 선택하면 연령별 지도가 표시됩니다.")
            return
        st.caption("각 지도 값 = 해당 지역·해당 연령의 1인가구 ÷ 전국·해당 연령의 1인가구 × 100. 연령별로 별도 지도이며, 같은 원 크기·색상 척도를 사용합니다.")
        scale_max = max(float(v) for age in NATIONAL_AGES for v in shares.iloc[1:][age])
        cols = st.columns(2)
        for i, age in enumerate(ages):
            plot = shares.iloc[1:][["지역", age]].copy()
            plot[age] = plot[age].astype(float)
            with cols[i % 2]:
                st.plotly_chart(bubble_map(plot, "지역", age, "provinces", f"{age} · 전국 내 지역 분포 (%)", "%", scale_max), width="stretch", key=f"national_{age}")
        st.dataframe(shares[["지역"] + ages], hide_index=True, width="stretch")
        download_table(shares[["지역"] + ages], "전국_연령별분포_PDF원문표기.csv")
    st.caption("인쇄 46~47쪽 = PDF 파일의 51~52페이지. PDF의 공표 단위·반올림을 유지하며, 시군구/개별 가구의 위치나 경제적 취약도는 알 수 없습니다.")


def render_context() -> None:
    st.subheader("전국 경제·사회 상황 · 지도와 결합하지 않는 참고 통계")
    st.error("이 두 파일만으로 ‘어느 지역·어느 연령의 경제적 어려움 가구가 많은가’는 산출할 수 없습니다.")
    # 아래는 검토한 PDF 원문을 그대로 전사한 공표값이다. 연령별 위기율/가정값이 아니다.
    facts = pd.DataFrame([
        ["연간 소득", "2024", "전국 1인가구", "3,423", "만 원", "인쇄 22·62쪽 / PDF 27·67페이지", "가계금융복지조사"],
        ["연소득 3천만 원 미만 비중", "2024", "전국 1인가구", "53.6", "%", "인쇄 23쪽 / PDF 28페이지 본문", "가계금융복지조사"],
        ["급히 큰돈을 빌려야 할 때 도움받을 사람 있음", "2025", "1인가구에 속한 13세 이상 응답자", "45.6", "%", "인쇄 33·67쪽 / PDF 38·72페이지", "사회조사"],
        ["평소 자주 또는 가끔 외롭다고 응답", "2025", "1인가구에 속한 13세 이상 응답자", "48.9", "%", "인쇄 33·67쪽 / PDF 38·72페이지", "사회조사"],
    ], columns=["지표", "기준연도", "대상", "공표값", "단위", "PDF 근거", "원통계"])
    st.dataframe(facts, hide_index=True, width="stretch")
    st.warning("‘큰돈을 빌릴 때 도움받을 사람 있음’은 빈곤율/경제적 어려움 경험률이 아닙니다. 외로움도 경제적 취약도의 대용 지표로 바꾸지 않습니다. 개인단위 조사 응답 비율을 가구수에 곱하지 않습니다.")
    st.caption("53.6%는 본문 공표값 그대로입니다. 소득 구간표의 반올림된 10.6%와 42.9%를 더한 53.5%로 대체하지 않습니다. 저소득 구간을 공식 빈곤 기준과 동일시하지 않습니다.")
    download_table(facts, "전국_참고지표_원문전사.csv")
    st.subheader("목표 분석을 완성하려면 필요한 추가 자료")
    st.write("같은 기준연도·지역코드·연령구간·대상 정의로 작성된 ‘지역 × 연령 × 1인가구 여부 × 경제상태’ 교차자료가 필요합니다. 예: 정의가 명확한 저소득 1인가구 수, 기초생활보장 수급 1인가구 수, 주거비 부담 경험 가구 수 등. 수급 여부는 빈곤 전체와 같은 지표가 아닙니다.")
    st.write("원 크기를 해당 지역·연령의 1인가구 수로, 색상을 같은 분모의 경제적 어려움 비율로 표현하려면, 경제적 어려움 가구 수와 대응하는 전체 1인가구 수가 모두 필요합니다. 조사자료는 가중치·표본오차·공표 가능 수준도 확인해야 합니다.")


if __name__ == "__main__":
    main()
