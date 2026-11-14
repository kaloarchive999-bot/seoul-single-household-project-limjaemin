"""같은 1인가구, 같은 어려움일까? · 실행: python -m streamlit run app.py"""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import core
import analytics as an

TITLE='같은 1인가구, 같은 어려움일까?'
NAV=['어디에 사는가','세대별 어려움','5개 권역 비교','지역의 연령 유형','지역 건강 배경','전국 분포','근거·원본 검증']
COLOR={'1인가구':'#373D70','다인가구 응답가구':'#C8A84B'}


@st.cache_data(show_spinner=False)
def load_assets(signature):
 raw=core.asset_path('source.csv').read_bytes()
 core.verify_source(raw,core.CSV_SHA,'1인가구 CSV')
 frame,_,encoding=core.load_csv(raw)
 cube,defs=an.load_cube()
 dep=an.load_depression()
 audit=json.loads(core.asset_path('survey_audit.json').read_text(encoding='utf-8'))
 return frame,cube,defs,dep,audit


def download(df,name,label='현재 결과 CSV 다운로드'):
 st.download_button(label,df.to_csv(index=False).encode('utf-8-sig'),name,'text/csv',key='dl_'+name)


def chart(fig,key=None):
 fig.update_layout(font=dict(family='Arial, sans-serif'),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
 st.plotly_chart(fig,width='stretch',key=key,config={'displaylogo':False})


def info_strip(text):
 st.info(text)


def main():
 st.set_page_config(page_title=TITLE,page_icon='🏠',layout='wide')
 st.markdown('''<style>
 .block-container{padding-top:2rem;max-width:1480px}
 h1{letter-spacing:-.045em} h2,h3{letter-spacing:-.025em}
 [data-testid="stMetric"]{border:1px solid rgba(128,128,128,.25);padding:16px;border-radius:12px}
 div[data-testid="stSidebar"] .block-container{padding-top:1rem}
 </style>''',unsafe_allow_html=True)
 st.caption('서울 1인가구 · 거주 규모와 세대별 어려움을 구분해서 읽는 데이터 대시보드')
 st.title(TITLE)
 st.write('같은 가구 형태여도, 경제·관계·건강의 상황은 같지 않을 수 있습니다. **실제로 관측한 응답만 비교합니다.**')
 with st.sidebar:
  st.header('분석 설정')
  page=st.radio('화면',NAV)
  ages=list(core.GROUPS);sex='계';regions=an.REGIONS
  if page in ['어디에 사는가','세대별 어려움','5개 권역 비교']:
   ages=st.multiselect('공통 연령대 · 다중 선택',list(core.GROUPS),default=['20대','30대','40대','50대','60대'])
  if page in ['어디에 사는가','세대별 어려움','5개 권역 비교','지역의 연령 유형','지역 건강 배경']:
   sex=st.radio('성별',['계','남자','여자'],horizontal=True)
  if page in ['세대별 어려움','5개 권역 비교']:
   regions=st.multiselect('조사 권역',an.REGIONS,default=an.REGIONS)
  st.divider()
  st.caption('거주 통계 2025 · 복지실태조사 2024 · 소득/지출 기준 2023. 자료 간 연도를 섞어 추정하지 않습니다.')
  st.caption('파일 업로드 불필요 · 원본/집계 체크섬 검증 · 원본 0 대체 없음')
 try:
  manifest=an.verify_manifest()
  sig=hashlib.sha256(core.asset_path('data_manifest.json').read_bytes()).hexdigest()
  frame,cube,defs,dep,audit=load_assets(sig)
  if page in ['어디에 사는가','세대별 어려움','5개 권역 비교'] and not ages:
   st.warning('왼쪽에서 연령대를 하나 이상 선택하세요. 원자료는 삭제하지 않았습니다.');return
  if page in ['세대별 어려움','5개 권역 비교'] and not regions:
   st.warning('조사 권역을 하나 이상 선택하세요.');return
  if page=='어디에 사는가':residence(frame,ages,sex)
  elif page=='세대별 어려움':difficulties(cube,defs,ages,sex,regions)
  elif page=='5개 권역 비교':regional(cube,defs,ages,sex,regions)
  elif page=='지역의 연령 유형':clusters(frame,sex)
  elif page=='지역 건강 배경':background(dep,sex)
  elif page=='전국 분포':national()
  else:evidence(defs,audit,manifest)
 except Exception as exc:
  # 오류를 정상 통계로 대체하지 않는다. 원본 수정/0 대체/임의 파일 선택 없음.
  st.error(f'분석 중단 — {type(exc).__name__}: {exc}')
  st.info('app.py와 필수 파일을 같은 위치 또는 data/에 올렸는지 확인하세요. 서로 다른 중복 파일은 하나만 남기세요. 원본 데이터는 자동 보정하지 않습니다.')
  with st.expander('문제 확인용 상세 정보'):
   st.exception(exc)
 st.divider()
 st.caption('출처: 서울시 1인가구(연령별) CSV · 국가데이터처 2025 통계로 보는 1인가구 · 서울연구원(2024) 서울복지실태조사 · 서울시 우울감 경험률. 관측값과 분석용 파생값을 구분합니다.')


def residence(frame,ages,sex):
 st.subheader('01 · 어디에 어떤 연령의 1인가구가 사는가')
 info_strip('2025년 서울 25개 구의 거주 분포입니다. 원은 지역별 합계이며 실제 가구 주소나 경제적 취약가구 위치가 아닙니다.')
 grouped=core.group_seoul(frame,sex);selected=core.select_seoul(grouped,ages)
 value=st.radio('지표',['가구 수','구내 선택연령 구성비'],horizontal=True)
 col='선택연령_가구수' if value=='가구 수' else '구내_선택연령비중_pct'
 count=int(selected['선택연령_가구수'].sum());total=int(selected['합계'].sum())
 winners=selected.loc[selected['선택연령_가구수'].eq(selected['선택연령_가구수'].max()),'자치구']
 a,b,c=st.columns(3)
 a.metric('선택 연령 1인가구',f'{count:,} 가구')
 b.metric('동일 성별 전체 1인가구 중',f'{count/total*100:.2f}%')
 c.metric('선택 연령 가구 수 최다',', '.join(winners))
 st.caption(f"선택: {', '.join(ages)} · 성별 {sex} · 60대=60~69세 · 제외 연령 {total-count:,}가구도 원본에 보존")
 left,right=st.columns([1.2,1])
 with left:chart(core.bubble_map(selected,'자치구',col,'seoul','선택 연령 합산 · '+value,'가구' if value=='가구 수' else '%'))
 with right:
  long=grouped.melt(id_vars=['자치구','성별','합계'],value_vars=ages,var_name='연령대',value_name='가구수')
  order=selected.sort_values(col,ascending=False)['자치구'].tolist()
  if value=='가구 수':
   fig=px.bar(long,x='가구수',y='자치구',color='연령대',orientation='h',color_discrete_map=core.COLORS,category_orders={'자치구':order,'연령대':ages},title='25개 구 전체 · 연령별 규모')
  else:fig=px.bar(selected,x=col,y='자치구',orientation='h',category_orders={'자치구':order},title='25개 구 전체 · 선택 연령 구성비')
  fig.update_layout(height=570,margin=dict(l=0,r=0,t=45,b=0));chart(fig)
 st.caption('구내 구성비의 분모는 해당 구·동일 성별의 전체 연령 1인가구입니다. 전체 일반가구 대비 비율·전체 인구 대비 비율·면적당 밀도가 아닙니다.')
 st.dataframe(selected.sort_values(col,ascending=False),hide_index=True,width='stretch')
 download(selected,'거주분포_선택연령.csv')
 with st.expander('모든 연령의 집계와 지도 해석 한계'):
  st.dataframe(grouped,hide_index=True,width='stretch')
  st.write('지도 윤곽은 SGIS 기반 2020년 참고 경계입니다. 이후 행정경계 변동은 반영하지 않습니다. 도형은 표시용으로만 단순화하며 통계값은 바꾸지 않습니다. 기준일·조사 방식은 CSV만으로 확인되지 않습니다.')


def choose_metric(defs,key):
 domains=list(dict.fromkeys(m['domain'] for m in defs['metrics']))
 domain=st.selectbox('비교 영역',domains,key=key+'_domain')
 options=[m for m in defs['metrics'] if m['domain']==domain]
 mid=st.selectbox('비교 지표',[m['id'] for m in options],format_func=lambda x:next(m['name'] for m in options if m['id']==x),key=key+'_metric')
 return next(m for m in options if m['id']==mid)


def metric_notes(m):
 st.write('**문항 기준:** '+m['definition'])
 st.caption(f"대상/분모: {m['denominator']} | 기준시기: {m['period']} | 변수: {m['var']}")
 st.warning(m['warning'])


def display_table(out,m,keys):
 table=an.metric_display(out,m)
 rename={'household_type':'가구형태','age_group':'연령대','region':'권역','total_n':'선택 표본수','eligible_n':'문항 대상수','valid_n':'유효응답수','nonapplicable_n':'비해당수','missing_n':'대상 중 결측수','effective_n':'Kish 유효표본수','status':'해석 주의'}
 cols=keys+['표시값','단위','total_n','eligible_n','valid_n','nonapplicable_n','missing_n','effective_n','status']
 return table[cols].rename(columns=rename)


def filtered_chart(out,m,x,color=None):
 result=an.metric_display(out,m)
 result=result[result['weight_sum'].gt(0)].copy()
 result['표시값']=result['표시값'].astype(float)
 if result.empty:st.info('이 조건에는 유효응답이 없어 값을 만들지 않았습니다.');return
 fig=px.bar(result,x=x,y='표시값',color=color,barmode='group',color_discrete_map=COLOR if color=='household_type' else None,
  category_orders={'age_group':list(core.GROUPS),'region':an.REGIONS},
  custom_data=['valid_n','status'],labels={'표시값':'응답 비율 (%)' if m['kind']=='binary' else '가중평균 (만 원)','age_group':'연령대','region':'권역','household_type':'가구 형태'})
 fig.update_traces(hovertemplate='%{x}<br>값: %{y:.2f}<br>유효응답 n=%{customdata[0]}<br>%{customdata[1]}<extra></extra>')
 if m['kind']=='binary':fig.update_yaxes(range=[0,100])
 fig.update_layout(height=420,legend_title_text='');chart(fig)
 if (result.valid_n<30).any():st.warning('유효응답 n<30인 작은 집단이 포함됩니다. 탐색용으로만 보세요. n<30 경고는 앱 기준이지 공식 공표 기준이 아닙니다. 원본/집계값을 숨기거나 0으로 바꾸지 않았습니다.')


def difficulties(cube,defs,ages,sex,regions):
 st.subheader('02 · 같은 1인가구, 세대별 어려움은 같은가')
 info_strip('2024 서울복지실태조사 · 가구당 실제 응답자 1명 · 제공된 만 나이/성별 · 표준화 가구 가중치 twgt 적용. 2025년 거주 가구 수에 곱하지 않습니다.')
 m=choose_metric(defs,'age');metric_notes(m)
 comparison=st.checkbox('다인가구 응답가구와 나란히 보기',value=False)
 household=None if comparison else '1인가구'
 pooled=an.pool_cube(cube,['household_type'],m['id'],ages,sex,regions,household)
 if pooled.empty:st.info('선택 조건에 조사 표본이 없습니다.');return
 shown=an.metric_display(pooled,m)
 cards=st.columns(max(1,len(shown)))
 for box,row in zip(cards,shown.to_dict('records')):
  v=row['표시값'];value=f"{v:.2f}{'%' if m['kind']=='binary' else '만 원'}" if isinstance(v,(float,int)) else str(v)
  box.metric(row['household_type']+' · 선택 조건',value)
  box.caption(f"선택 표본 {int(row['total_n']):,} · 유효응답 {int(row['valid_n']):,} · 비해당 {int(row['nonapplicable_n']):,}")
 out=an.pool_cube(cube,['age_group','household_type'],m['id'],ages,sex,regions,household)
 filtered_chart(out,m,'age_group','household_type')
 st.caption('다인가구 비교의 연령·성별은 가구주가 아니라 실제 응답자 기준입니다. 다인가구에 속한 모든 개인의 대표 추정치가 아닙니다. 평균 차이는 인과효과나 통계적 유의성을 의미하지 않습니다.')
 st.dataframe(display_table(out,m,['age_group','household_type']),hide_index=True,width='stretch')
 download(display_table(out,m,['age_group','household_type']),'세대별_어려움_가중집계.csv')
 with st.expander('합산 방법·표본·가중치'):
  st.write('선택한 연령·성별·권역의 가중 분자와 가중 분모를 각각 합산한 뒤 비율을 계산합니다. 연령별 비율을 단순 평균하지 않습니다.')
  st.code('가중 비율 = sum(twgt × 해당 응답) / sum(twgt, 문항별 유효응답) × 100\nKish 유효표본수 = sum(twgt)² / sum(twgt²)',language='text')
  st.write('설계기반 표준오차/신뢰구간은 산출하지 않습니다. Kish 유효표본수는 정밀도를 보증하지 않으며 층화·군집 설계를 대신하지 않습니다. 금액 지표는 평균이며 중위값이 아닙니다.')
  st.dataframe(display_table(pooled,m,['household_type']),hide_index=True,width='stretch')


def regional(cube,defs,ages,sex,regions):
 st.subheader('03 · 5개 권역에서 관측한 어려움')
 info_strip('공개 조사자료는 5개 권역만 제공합니다. 권역 값을 25개 자치구에 복사하거나 자치구별 취약가구 수로 역산하지 않습니다.')
 m=choose_metric(defs,'region');metric_notes(m)
 out=an.pool_cube(cube,['region'],m['id'],ages,sex,regions,'1인가구')
 if out.empty:st.info('선택 조건에 조사 표본이 없습니다.');return
 filtered_chart(out,m,'region')
 table=display_table(out,m,['region'])
 st.dataframe(table,hide_index=True,width='stretch');download(table,'권역별_1인가구_가중집계.csv')
 st.caption('이 화면은 지역 내 전체 인구의 특성이나 인구 대비 취약가구 밀도를 뜻하지 않습니다. 같은 권역의 연령별 표본을 합친 기술통계입니다.')


def clusters(frame,sex):
 st.subheader('04 · 지역의 연령 구성은 어떻게 다른가')
 info_strip('현재 CSV로 다시 계산한 탐색적 유형입니다. 발표자료의 A/B/C 구분을 복사하지 않으며, 빈곤·외로움 위험 유형도 아닙니다.')
 k=st.select_slider('탐색적 군집 수',options=[2,3,4,5],value=3)
 out,summary,score=an.district_clusters(frame,sex,k)
 a,b=st.columns(2);a.metric('분석 지역',f'{len(out)}개 구');b.metric('실루엣 점수 · 탐색용',f'{score:.3f}')
 st.caption('20세 이상을 분모로 청년 20~39세·중장년 40~64세·노년 65세 이상 구성비 계산 → StandardScaler → K-means(n_init=50, random_state=42). 20세 미만은 원본에 보존하고 이 분석 분모에서만 제외합니다.')
 options=['청년_20~39세_구성비','중장년_40~64세_구성비','노년_65세이상_구성비']
 c1,c2=st.columns([1.15,1])
 with c1:
  fig=core.bubble_map(out,'자치구','20세이상_분모','seoul','원 크기: 20세 이상 1인가구 · 색: 구성 유형','가구')
  palette=px.colors.qualitative.Safe
  labels=sorted(out['유형'].unique());mapping={v:palette[i] for i,v in enumerate(labels)}
  fig.data[1].marker.color=[mapping[v] for v in out['유형']]
  fig.data[1].marker.showscale=False;fig.data[1].marker.colorbar=None
  for label in labels:
   fig.add_trace(go.Scatter(x=[],y=[],mode='markers',marker=dict(color=mapping[label],size=12),name=label,showlegend=True))
  fig.data[1].customdata=[[n,t] for n,t in zip(out['20세이상_분모'],out['유형'])]
  fig.data[1].hovertemplate='<b>%{text}</b><br>%{customdata[1]}<br>20세 이상: %{customdata[0]:,}가구<extra></extra>'
  chart(fig)
 with c2:
  long=summary.melt(id_vars=['유형','자치구수'],value_vars=options,var_name='연령 구분',value_name='구성비')
  fig=px.bar(long,x='유형',y='구성비',color='연령 구분',title='유형별 자치구 구성비의 단순 평균')
  fig.update_layout(height=410);chart(fig)
  st.dataframe(summary,hide_index=True,width='stretch')
 st.warning('유형 번호는 청년 구성비가 높은 군집부터 정렬한 이름일 뿐입니다. 군집 수·성별·기준연도가 달라지면 소속도 달라질 수 있습니다. 군집의 대표성이 검증된 정책 처방으로 해석하지 마세요.')
 st.dataframe(out.sort_values(['유형','자치구']),hide_index=True,width='stretch');download(out,'자치구_연령유형_탐색적.csv')


def background(dep,sex):
 st.subheader('05 · 지역의 건강 배경 · 1인가구 전용 아님')
 st.warning('이 자료는 전체 주민의 우울감 경험률입니다. 1인가구의 비율이 아니며, 자치구×연령 교차표도 아닙니다. 다른 화면에서 선택한 연령은 적용하지 않습니다.')
 key='전체' if sex=='계' else sex
 district=dep[dep['구분'].eq('지역소분류')][['대상',key]].copy()
 district.columns=['자치구','우울감_경험률_pct'];district['우울감_경험률_pct']=district['우울감_경험률_pct'].astype(float)
 city=dep[dep['구분'].eq('서울시')].iloc[0][key]
 st.metric(f'서울 전체 주민 · {sex} · CSV 2025년',city+'%')
 st.caption('원문 가중치 적용 조율입니다. 자치구 연령구조 차이를 제거한 표준화율로 해석하지 않습니다. 25개 구 비율을 평균해 서울 값을 만들지 않습니다.')
 left,right=st.columns([1.1,1])
 with left:chart(core.bubble_map(district,'자치구','우울감_경험률_pct','seoul','전체 주민 우울감 경험률 · 지역 배경','%'))
 with right:
  age=dep[dep['구분'].eq('연령별')][['대상',key]].copy();age[key]=age[key].astype(float)
  fig=px.bar(age,x='대상',y=key,labels={key:'공표 비율 (%)','대상':'원문 연령구간'},title='전체 주민 · 연령별 공표값')
  fig.update_layout(height=420);chart(fig)
  st.caption('최저 구간은 19~29세입니다. 기존 거주 통계의 20대와 같지 않으며, 여러 연령의 비율을 합산하지 않습니다.')
 with st.expander('교육·직업 등 모든 원문 행 보기'):
  st.dataframe(dep,hide_index=True,width='stretch')
 st.dataframe(district.sort_values('우울감_경험률_pct',ascending=False),hide_index=True,width='stretch');download(dep,'우울감_공표값_전체행.csv')
 st.markdown('[서울시 공식 통계 설명](https://data.seoul.go.kr/dataList/DT201004E0400121/S/2/datasetView.do) · 원본 CSV의 수치는 재가중하거나 보정하지 않았습니다.')


def national():
 st.subheader('06 · 전국 1인가구 분포 · 2024년')
 pdf=core.asset_path('source.pdf').read_bytes();totals,shares=core.load_pdf(pdf)
 mode=st.radio('전국 지표',['전체 연령 가구 수','연령별 전국 내 지역 분포'],horizontal=True)
 if mode=='전체 연령 가구 수':
  st.metric('전국 · 공표 반올림값','8,045 천 가구')
  t=totals.iloc[1:].copy();t['1인가구_천가구']=t['1인가구_천가구'].str.replace(',','',regex=False).astype(int)
  chart(core.bubble_map(t,'지역','1인가구_천가구','provinces','전체 연령 1인가구 · 단위 천 가구','천 가구'))
  st.dataframe(totals,hide_index=True,width='stretch');download(totals,'전국_공표_전체연령.csv')
 else:
  ages=st.multiselect('PDF 연령 구간',core.NATIONAL_AGES,default=core.NATIONAL_AGES[:2])
  st.warning('29세 이하는 20대가 아닙니다. 연령별 비율은 분모가 서로 달라 합산하거나 정확한 가구 수로 역산하지 않습니다.')
  cols=st.columns(2);vmax=max(float(v) for a in core.NATIONAL_AGES for v in shares.iloc[1:][a])
  for i,age in enumerate(ages):
   p=shares.iloc[1:][['지역',age]].copy();p[age]=p[age].astype(float)
   with cols[i%2]:chart(core.bubble_map(p,'지역',age,'provinces',age+' · 전국 해당 연령 내 지역 분포','%',vmax),key='nation_'+age)
  st.dataframe(shares[['지역']+ages],hide_index=True,width='stretch');download(shares[['지역']+ages],'전국_공표_연령별분포.csv')
 st.caption('PDF 인쇄 46~47쪽(파일 51~52페이지)의 표를 직접 추출합니다. 소수 첫째 자리와 천 가구 단위의 반올림을 그대로 유지합니다.')


def evidence(defs,audit,manifest):
 st.subheader('07 · 근거와 검증 · 무엇을 계산했고 무엇을 계산하지 않았나')
 a,b,c=st.columns(3)
 a.metric('복지조사 가구 파일',f"{audit['household_rows']:,}가구")
 b.metric('그중 1인가구 표본',f"{audit['single_household_n']:,}가구")
 c.metric('가구원 파일 · 합산 안 함',f"{audit['member_rows']:,}행")
 st.warning('원자료 식별자 불일치 발견: 가구 파일에만 IDX=3005, 가구원 파일에만 IDX=695가 있습니다. 같은 IDX의 가구원 수가 일치하지 않는 경우도 있어 두 파일을 연결하지 않았습니다. 번호 수정·행순서 매칭·응답값 보정은 하지 않았습니다.')
 st.write('복지 지표는 가구 Excel의 실제 응답자 기준으로 독립 집계했습니다. 가구원 파일에 반복된 가구 응답은 추가 표본으로 세지 않았습니다. SAV는 체크섬/헤더를 확인한 보조 원본이며 Excel에 합산하지 않았습니다.')
 st.info('무부채 가구 1,914가구의 부채 문항 공란은 설문 분기에 따른 비해당입니다. 원본을 0/null로 바꾸지 않고, 해당 문항의 분모에서 비해당만 분리했습니다.')
 st.write('소득·지출의 기준은 2023년, 조사 시행은 2024년, 거주 통계 및 우울감 CSV 머리글은 2025년입니다. 가중치 합계는 입력 정밀도 그대로 보존하며 3,004에 강제 정규화하지 않았습니다.')
 st.markdown('### 지표 사전')
 dictionary=pd.DataFrame([{k:m.get(k,'해당 없음') for k in ['id','name','domain','var','period','denominator','definition','warning']} for m in defs['metrics']])
 st.dataframe(dictionary,hide_index=True,width='stretch');download(dictionary,'복지지표_정의.csv')
 st.markdown('### 발표자료와의 관계')
 st.write('발표자료의 회귀계수(+0.054, −0.044 등), 군집 소속, 자치구 순위는 복사하지 않았습니다. 해당 회귀모형을 재현한 결과로 주장하지 않으며 인과효과·위기가구 수·종합위험점수를 만들지 않았습니다.')
 st.markdown('선행연구의 **외로움 62.1%**는 2022년 논문 초록에서 확인되지만, 본 앱의 2024 조사 단일 문항과 같은 지표가 아닙니다. 조사 연도·문항이 다른 비율을 추세나 지역 격차로 연결하지 않습니다. [박민진·김성아(2022)](https://doi.org/10.15709/hswr.2022.42.4.127)')
 st.markdown('### 출처와 이용 조건')
 st.markdown('- [서울연구원(2024), 서울복지실태조사·공식 코드북·이용안내서](https://data.si.re.kr/node/65462/)\n- [서울시 1인가구(연령별)](https://data.seoul.go.kr/dataList/10995/S/2/datasetView.do)\n- [서울시 우울감 경험률](https://data.seoul.go.kr/dataList/DT201004E0400121/S/2/datasetView.do)\n- [SGIS 기반 2020 참고 경계](https://github.com/statgarten/maps)')
 st.write('개인 조사 원본은 공개 배포 패키지에 포함하지 않았습니다. 배포용 CSV는 연령대×성별×권역×가구형태의 집계이며 개인 ID가 없습니다. 개별 집계가 작으면 재식별·과해석에 주의하세요. 원자료 이용조건과 출처표시 의무는 계속 적용됩니다.')
 with st.expander('원본 검사 결과·체크섬'):
  st.json(audit);st.json(manifest)
 st.download_button('기존 1인가구 CSV 원본 다운로드',core.asset_path('source.csv').read_bytes(),core.CSV_NAME,'text/csv')
 st.download_button('기존 PDF 원본 다운로드',core.asset_path('source.pdf').read_bytes(),core.PDF_NAME,'application/pdf')
 st.download_button('우울감 CSV 원본 다운로드',core.asset_path('depression.csv').read_bytes(),'우울감_경험률_원본.csv','text/csv')


if __name__=='__main__':main()
