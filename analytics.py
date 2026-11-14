"""통계 원본을 바꾸지 않는 집계·표시용 순수 함수."""
from __future__ import annotations
import csv,io,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
import core

AGES=list(core.GROUPS)
NUMERIC=['total_n','eligible_n','valid_n','nonapplicable_n','missing_n','weight_sum','weighted_sum','weight_square_sum','raw_sum']
REGIONS=['도심권','동북권','서북권','서남권','동남권']


def verify_manifest():
 obj=json.loads(core.asset_path('data_manifest.json').read_text(encoding='utf-8'))
 for name,meta in obj['files'].items():
  path=core.asset_path(name)
  core.verify_source(path.read_bytes(),meta['sha256'],name)
 return obj


def load_cube():
 df=pd.read_csv(core.asset_path('survey_cube.csv'),encoding='utf-8-sig',float_precision='round_trip')
 core.require(not df.isna().any().any(),'복지 집계에 결측이 있습니다. 대체하지 않습니다.')
 core.require(not df.duplicated(['household_type','sex','age_group','region','metric']).any(),'복지 집계 키 중복')
 core.require((df.valid_n+df.missing_n==df.eligible_n).all(),'문항 분모 검증 실패')
 core.require((df.eligible_n+df.nonapplicable_n==df.total_n).all(),'비해당 분모 검증 실패')
 core.require((df.weight_sum>=0).all(),'음수 가중치 합')
 definitions=json.loads(core.asset_path('survey_definitions.json').read_text(encoding='utf-8'))
 return df,definitions


def pool_cube(cube,groupby=None,metric='loneliness',ages=None,sex='계',regions=None,household=None):
 """분자/분모를 합산한 후 비율 산출. 이미 계산한 비율의 단순 평균을 하지 않는다."""
 keys=groupby or []
 part=cube[cube.metric.eq(metric)]
 if ages is not None:part=part[part.age_group.isin(ages)]
 if sex!='계':part=part[part.sex.eq(sex)]
 if regions is not None:part=part[part.region.isin(regions)]
 if household is not None:part=part[part.household_type.eq(household)]
 if part.empty:return pd.DataFrame(columns=keys+NUMERIC+['status','value','effective_n'])
 pooled=part.groupby(keys,as_index=False,observed=True)[NUMERIC].sum() if keys else pd.DataFrame([part[NUMERIC].sum()])
 def output(r):
  if r.weight_sum<=0:return dict(status='유효응답 없음',value='산출 불가',effective_n='산출 불가')
  return dict(status='표본 작음(n<30)' if r.valid_n<30 else '기술통계',value=float(r.weighted_sum/r.weight_sum),effective_n=float(r.weight_sum**2/r.weight_square_sum))
 values=pd.DataFrame([output(r) for r in pooled.itertuples()],index=pooled.index)
 return pd.concat([pooled,values],axis=1)


def metric_display(table,definition):
 out=table.copy()
 multiplier=100 if definition['kind']=='binary' else 1
 out['표시값']=[float(x)*multiplier if isinstance(x,(int,float,np.number)) else x for x in out['value']]
 out['단위']='%' if definition['kind']=='binary' else '만 원'
 return out


def load_depression():
 blob=core.asset_path('depression.csv').read_bytes()
 core.verify_source(blob,'1a19041d6734ba0f12bcd285a00e08c6200f66a428d8d28d652f444da7c5fc8a','우울감 CSV')
 rows=list(csv.reader(io.StringIO(blob.decode('utf-8-sig'))))
 core.require(rows[0]==['구분별(1)','구분별(2)','2025','2025','2025'],'우울감 헤더 불일치')
 core.require(rows[1]==['구분별(1)','구분별(2)','전체','남자','여자'],'우울감 성별 헤더 불일치')
 for i,r in enumerate(rows[2:],3):
  core.require(len(r)==5,f'우울감 {i}행 열 수 불일치')
  for x in r[2:]:
   core.require(x.replace('.','',1).isdigit() and 0<=float(x)<=100,f'우울감 {i}행 원문 해석 불가: {x}')
 frame=pd.DataFrame(rows[2:],columns=['구분','대상','전체','남자','여자'])
 dist=frame[frame['구분'].eq('지역소분류')]
 core.require(len(dist)==25 and set(dist['대상'])==set(core.DISTRICTS),'우울감 자치구 누락/중복')
 return frame


def district_clusters(frame,sex='계',k=3):
 part=frame[frame['성별'].eq(sex)&~frame['자치구'].eq('소계')].copy()
 features={'청년_20~39세':['20~24세','25~29세','30~34세','35~39세'],
           '중장년_40~64세':['40~44세','45~49세','50~54세','55~59세','60~64세'],
           '노년_65세이상':['65~69세','70~74세','75~79세','80~84세','85세이상']}
 out=part[['자치구','성별','합계','20세미만']].copy()
 out['20세이상_분모']=out['합계']-out['20세미만']
 cols=[]
 for label,names in features.items():
  out[label+'_가구수']=part[names].sum(axis=1)
  col=label+'_구성비';cols.append(col)
  out[col]=out[label+'_가구수']/out['20세이상_분모']*100
 core.require(np.allclose(out[cols].sum(axis=1),100),'군집 연령구성 검증 실패')
 core.require(k in [2,3,4,5],'지원하지 않는 군집 수')
 scaled=StandardScaler().fit_transform(out[cols])
 with threadpool_limits(limits=1):
  fitted=KMeans(n_clusters=k,n_init=50,random_state=42).fit(scaled)
  score=float(silhouette_score(scaled,fitted.labels_))
 labels=pd.Series(fitted.labels_,index=out.index)
 means=out[cols].groupby(labels).mean().sort_values(cols[0],ascending=False)
 mapping={old:f'유형 {i+1}' for i,old in enumerate(means.index)}
 out['유형']=labels.map(mapping)
 summary=out.groupby('유형',as_index=False)[cols].mean()
 summary['자치구수']=summary['유형'].map(out['유형'].value_counts())
 return out,summary,score
