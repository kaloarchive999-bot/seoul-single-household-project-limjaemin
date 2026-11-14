"""원본 검증·행정통계 파싱·참고 경계 렌더링. 개별 취약가구를 추정하지 않음."""
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
DATA = BASE / "data"


def asset_path(name: str) -> Path:
    """루트와 data/ 모두 지원. 서로 다른 중복 파일이면 중단한다."""
    paths = [p for p in [BASE / name, BASE / "data" / name] if p.is_file()]
    require(bool(paths), f"필수 파일 {name}이 없습니다. app.py 옆 또는 data/에 업로드하세요.")
    if len(paths) == 2:
        require(paths[0].read_bytes() == paths[1].read_bytes(),
                f"{name}이 루트와 data/에 서로 다른 내용으로 중복되어 있습니다. 사용할 한 버전만 남기세요.")
    return paths[0]
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
    obj = json.loads(asset_path(f"{kind}_2020.json").read_text(encoding="utf-8"))
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


