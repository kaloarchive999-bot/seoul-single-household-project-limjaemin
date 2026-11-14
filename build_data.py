"""개인 PC에서만 실행하는 재현용 집계 스크립트. 원본은 읽기 전용이며 저장/수정하지 않음.
python build_data.py --raw-dir /path/to/five_uploaded_files --output-dir .
원본 엑셀을 GitHub에 올릴 필요가 없습니다. pandas/openpyxl 필요.
"""
from __future__ import annotations
import argparse, hashlib, json, math, struct
from pathlib import Path
import numpy as np
import openpyxl
import pandas as pd

REGIONS={1:'도심권',2:'동북권',3:'서북권',4:'서남권',5:'동남권'}
AGES=['20세 미만','20대','30대','40대','50대','60대','70세 이상']
METRICS=[
 dict(id='food_shortage',name='경제적 이유로 먹을 것 부족',domain='경제',kind='binary',var='D4',valid=[1,2,3,4],yes=[3,4],period='2023.9~2024.8',denominator='식생활 문항 유효응답 가구',definition='D4의 ③ 가끔 또는 ④ 자주 먹을 것이 부족. ② 다양성 부족은 포함하지 않음.',warning='공식 빈곤율이 아니라 식품 부족 경험 응답 비율입니다.'),
 dict(id='debt_burden',name='부채 상환 부담',domain='경제',kind='binary',var='B12_4',valid=[1,2,3,4,5],yes=[4,5],eligible='debt_positive',period='조사 당시',denominator='현재 부채(B12>0)가 있는 유효응답 가구',definition='B12>0 중 B12_4의 ④ 약간 부담 또는 ⑤ 매우 부담.',warning='무부채 가구는 비해당이며 0점 응답으로 대체하지 않습니다. B12는 설문 정의상 전월세보증금을 포함합니다.'),
 dict(id='interest_arrears',name='부채 이자 연체 경험',domain='경제',kind='binary',var='B12_3',valid=[1,2],yes=[1],eligible='debt_positive',period='2023.9~2024.8',denominator='현재 부채(B12>0)가 있는 유효응답 가구',definition='B12>0 중 B12_3=① 있다.',warning='무부채 가구는 비해당입니다. 주거비 체납이나 모든 금융 연체를 뜻하지 않습니다.'),
 dict(id='no_money_help',name='큰돈을 빌릴 상대 없음',domain='관계·지원',kind='binary',var='E2_2',valid=[1,2],yes=[2],period='조사 당시',denominator='E2_2 유효응답자',definition='E2_2=② 없다.',warning='경제적 지원망 지표이지 소득 빈곤율이 아닙니다.'),
 dict(id='loneliness',name='혼자라고 느낌 · 가끔/항상',domain='관계·지원',kind='binary',var='E3_4',valid=[1,2,3,4],yes=[3,4],period='조사 당시 문항',denominator='E3_4 유효응답자',definition='E3_4의 ③ 가끔 그런 편 또는 ④ 항상 그렇다.',warning='외로움 척도 20문항 중 단일 문항의 분석용 구분입니다. 전체 척도 진단이나 선행연구의 62.1%와 동일한 지표가 아닙니다.'),
 dict(id='no_emotional_help',name='우울할 때 이야기 상대 없음',domain='관계·지원',kind='binary',var='E2_1',valid=[1,2],yes=[2],period='조사 당시',denominator='E2_1 유효응답자',definition='E2_1=② 없다.',warning='모든 형태의 사회적 고립을 포괄하는 진단은 아닙니다.'),
 dict(id='no_care_help',name='아플 때 집안일 부탁할 상대 없음',domain='관계·지원',kind='binary',var='E2_3',valid=[1,2],yes=[2],period='조사 당시',denominator='E2_3 유효응답자',definition='E2_3=② 없다.',warning='돌봄 지원망 응답입니다. 실제 돌봄서비스 수급률이 아닙니다.'),
 dict(id='depressed_week',name='지난 1주 우울한 감정 · 1~2일 이상',domain='건강',kind='binary',var='C10_3',valid=[1,2,3,4],yes=[2,3,4],period='지난 1주',denominator='C10_3 유효응답자',definition='C10_3의 ② 1~2일, ③ 3~4일, ④ 5일 이상.',warning='우울증 진단율이나 다른 문항으로 작성된 공표 우울감 경험률과 다릅니다.'),
 dict(id='poor_health',name='주관적 건강 · 좋지 않음',domain='건강',kind='binary',var='respondent_health',valid=[1,2,3,4,5],yes=[4,5],period='조사 당시',denominator='실제 응답자의 건강상태 유효응답',definition='RES_Q1에 해당하는 C1_1_가구원번호의 ④ 건강하지 않은 편 또는 ⑤ 건강이 아주 안 좋음.',warning='의학적 진단이나 장애율이 아닙니다.'),
 dict(id='annual_income',name='2023년 세전 연소득 · 6항목 합계 평균',domain='소득·지출',kind='mean',var='income_six_sum',period='2023.1~12',denominator='B7_1~B7_6이 모두 관측된 가구',definition='근로·사업·재산·공적이전·사적이전·기타소득의 합계. 단위: 만 원/년.',warning='기타소득(증여·상속 등)을 포함합니다. 공식 경상소득/가처분소득/빈곤선과 동일시하지 않습니다. 다인가구 값은 가구 총액이며 균등화 소득이 아닙니다.'),
 dict(id='monthly_spending',name='2023년 월평균 생활비 · 평균',domain='소득·지출',kind='mean',var='B4',period='2023년 월평균',denominator='B4 유효응답 가구',definition='B4 원문 금액의 가중평균. 단위: 만 원/월.',warning='2024년 현재 지출이 아닙니다. 다인가구 값은 가구 전체 금액입니다.'),
]
SOURCE_NAMES={
 'household_xlsx':['welfare_household.xlsx','DATA_2024년 서울복지실태조사_가구 데이터_SI공개용.xlsx'],
 'members_xlsx':['welfare_members.xlsx','DATA_서울시민의 생활실태 및 복지욕구 조사_가구원 데이터_SI공개용.xlsx'],
 'household_sav':['welfare_household.sav','DATA_서울시민의 생활실태 및 복지욕구 조사.SAV_SI공개용.sav'],
 'members_sav':['welfare_members.sav','DATA_서울시민의 생활실태 및 복지욕구 조사_가구원_공개용.sav'],
 'depression':['depression.csv','우울감+경험률(2014년+이후)_20261114145800.csv'],
}
EXPECTED_SHA={
 'household_xlsx':'49a69a42ce8649e42db2e18738d878bae1543eff5099100c9748be47c809c363',
 'household_sav':'1ba8fa17c7638463556abf8eb77ecbdfcd40b9aad2c66d406fd57a86e95067c3',
 'members_xlsx':'23278ed7868691bd9d54a86db12b5c592175ca4eb45a71540536644d80a4eaf5',
 'members_sav':'26d213b1095d305f94c6d6cdc5c9d37d8743a9434854a1c08c1a1b6bf5025272',
 'depression':'1a19041d6734ba0f12bcd285a00e08c6200f66a428d8d28d652f444da7c5fc8a',
}


def need(ok,msg):
 if not ok:raise ValueError(msg)


def locate(root,names):
 matches=[root/n for n in names if (root/n).is_file()]
 need(len(matches)==1,f'원본 후보가 하나가 아닙니다: {names}')
 return matches[0]


def read_selected(path,needed):
 wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
 ws=wb.active;it=ws.iter_rows(values_only=True);columns=list(next(it))
 need(len(columns)==len(set(columns)),'변수명 중복')
 need(set(needed).issubset(columns),f'필수 변수가 없습니다: {set(needed)-set(columns)}')
 positions=[columns.index(c) for c in needed]
 rows=[[r[i] for i in positions] for r in it]
 wb.close()
 return pd.DataFrame(rows,columns=needed),len(columns)


def age_group(age):
 need(isinstance(age,(int,float,np.integer,np.floating)) and math.isfinite(age) and age>=0,'연령 비정상')
 return '20세 미만' if age<20 else f'{int(age)//10*10}대' if age<70 else '70세 이상'


def make_aggregates(h):
 """읽은 DataFrame의 복사본에만 파생 열 추가. 원본·원변수는 변경하지 않음."""
 d=h.copy(deep=True)
 need(d.IDX.is_unique and len(d)==3004,'가구 식별자 중복 또는 표본 수 불일치')
 need(d['A1_1'].isin(range(1,7)).all(),'가구원 수 코드 오류')
 need(d['RES_A1_4'].isin([1,2]).all(),'성별 코드 오류')
 need(d['D_SQ1'].isin(REGIONS).all(),'권역 코드 오류')
 need(d['RES_A1_5_4'].notna().all(),'원본 응답자 연령 결측')
 need(d['twgt'].notna().all() and (d['twgt']>0).all(),'가중치 오류')
 need(np.isclose(d.twgt.sum(),3004,rtol=1e-8),'표준화 가중치 합이 표본수와 불일치')
 ratio=d.wgt/d.twgt
 need(np.allclose(ratio,ratio.iloc[0],rtol=1e-9),'두 가중치의 비례 관계 불일치')
 d['household_type']=d.A1_1.map(lambda n:'1인가구' if n==1 else '다인가구 응답가구')
 d['sex']=d.RES_A1_4.map({1:'남자',2:'여자'})
 d['age_group']=d.RES_A1_5_4.map(age_group)
 d['region']=d.D_SQ1.map(REGIONS)
 income_cols=[f'B7_{i}' for i in range(1,7)]
 need((d[income_cols].notna().all(axis=1)).all(),'소득 구성항목에 결측 존재. 임의 합계/대체 금지')
 need((d[income_cols]>=0).all().all(),'음수 또는 미확인 소득 코드')
 d['income_six_sum']=d[income_cols].sum(axis=1,min_count=6)
 d['respondent_health']=[d.loc[i,f'C1_1_{int(r)}'] for i,r in d.RES_Q1.items()]
 need(d['respondent_health'].notna().all(),'실제 응답자의 건강상태 연결 실패')
 for m in METRICS:
  x=d[m['var']]
  if 'valid' in m: need(x.dropna().isin(m['valid']).all(),f"{m['id']}에 코드북 외 값")
  else:need((x.dropna()>=0).all(),f"{m['id']} 음수/비정상 코드")
  if m.get('eligible')=='debt_positive':
   need(x[d.B12.eq(0)].isna().all(),'부채 없음의 분기 문항에 응답 존재')
 rows=[]
 dims=['household_type','sex','age_group','region']
 for keys,part in d.groupby(dims,sort=True,observed=True):
  for m in METRICS:
   x=part[m['var']]
   eligible=part.B12.gt(0) if m.get('eligible')=='debt_positive' else pd.Series(True,index=part.index)
   valid=eligible & x.notna()
   if 'valid' in m:valid=valid & x.isin(m['valid'])
   sub=part.loc[valid];xv=x.loc[valid]
   y=xv.isin(m['yes']).astype(int) if m['kind']=='binary' else xv
   w=sub.twgt
   rows.append(dict(zip(dims,keys))|dict(metric=m['id'],total_n=len(part),eligible_n=int(eligible.sum()),valid_n=int(valid.sum()),
    nonapplicable_n=int((~eligible).sum()),missing_n=int((eligible & x.isna()).sum()),
    weight_sum=float(w.sum()),weighted_sum=float((w*y).sum()),weight_square_sum=float((w*w).sum()),raw_sum=float(y.sum())))
 cube=pd.DataFrame(rows)
 need(not cube.isna().any().any(),'집계파일 결측 발생')
 return cube,d


def build(root,out,cache_dir=None):
 out.mkdir(parents=True,exist_ok=True)
 files={k:locate(root,v) for k,v in SOURCE_NAMES.items()}
 hashes={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in files.items()}
 if EXPECTED_SHA:need(hashes==EXPECTED_SHA,'검토된 원본과 체크섬이 다릅니다. 원본을 대체하지 않습니다.')
 for key,n in [('household_sav',3004),('members_sav',6251)]:
  header=struct.unpack('<4s60s5id9s8s64s3s',files[key].read_bytes()[:176])
  need(header[0]==b'$FL2' and header[6]==n,'SAV 원본 헤더/표본수 불일치')
 hh_cols=['IDX','D_SQ1','A1_1','RES_Q1','RES_A1_4','RES_A1_5_4','twgt','wgt','B12','B12_4','B12_3','D4','E2_1','E2_2','E2_3','E3_4','C10_3','B4']+[f'C1_1_{i}' for i in range(1,7)]+[f'B7_{i}' for i in range(1,7)]
 member_cols=['IDX','A1','A1_1','RES_Q1','RES_A1_4','RES_A1_5_4','twgt','D4','E2_1','E2_2','E2_3','E3_4','C10_3','B12','B12_3','B12_4','B4']+[f'B7_{i}' for i in range(1,7)]
 h,hwidth=read_selected(files['household_xlsx'],hh_cols)
 p,pwidth=read_selected(files['members_xlsx'],member_cols)
 need(len(p)==6251,'가구원 파일 행 수 불일치')
 sizes=p.groupby('IDX').size().sort_index()
 need(int(h.A1_1.sum())==len(p),'두 파일의 전체 가구원 총수 불일치')
 # 제공된 파일의 IDX 집합이 서로 다르다. 보정/재번호/행순서 연결을 하지 않는다.
 id_report={'household_only_ids':sorted(set(h.IDX)-set(p.IDX)),
  'member_only_ids':sorted(set(p.IDX)-set(h.IDX)),
  'same_id_household_size_mismatch_n':int((sizes-h.set_index('IDX').A1_1).dropna().ne(0).sum()),
  'join_performed':False,'action':'파일별 독립 검증. 분석은 가구 Excel만 사용. IDX 보정·행순서 매칭·통합 금지.'}
 # 가구원 파일 안에서 반복된 가구 응답을 별도로 확인하되, 가구 파일과 연결하지 않는다.
 common=['D4','E2_1','E2_2','E2_3','E3_4','C10_3','RES_Q1','RES_A1_4','RES_A1_5_4','B4','B12','B12_3','B12_4']+[f'B7_{i}' for i in range(1,7)]
 need((p.groupby('IDX').A1.nunique()==1).all(),'가구원 파일 자체의 가구규모 불일치')
 for c in common:
  need((p.groupby('IDX')[c].nunique(dropna=False)<=1).all(),f'가구원 파일 내 반복 응답 불일치: {c}')
 independent_marginals=[]
 first=p.groupby('IDX',sort=True)[common].first()
 for c in common:
  if h[c].value_counts(dropna=False).to_dict()==first[c].value_counts(dropna=False).to_dict():
   independent_marginals.append(c)
 single_members=p[p.A1.eq(1)]
 need(len(single_members)==821 and single_members.IDX.is_unique,'1인가구의 가구원 자료 중복')
 cube,derived=make_aggregates(h)
 cube.to_csv(out/'survey_cube.csv',index=False,encoding='utf-8-sig',float_format='%.17g')
 definitions={'survey':'서울연구원(2024), 2024년 서울복지실태조사','survey_year':2024,
  'source_url':'https://data.si.re.kr/node/65462/','weight_variable':'twgt','weight_rule':'표준화 가구 가중치. 가구당 실제 응답자 1명 기준. 개인 모집단 대표 가중치로 간주하지 않음.',
  'age_variable':'RES_A1_5_4 (제공된 만 나이)','sex_variable':'RES_A1_4','household_filter':'A1_1 == 1',
  'regional_variable':'D_SQ1: 5개 권역만 제공. 25개 자치구 추정 금지.',
  'pooling':'선택 연령/성별/권역의 분자·분모 가중합을 합산. 단순 비율 평균 금지.',
  'uncertainty':'설계기반 신뢰구간을 계산하지 않음. 유의성/인과효과를 주장하지 않음. n<30 경고는 앱의 보수적 탐색용 기준이며 공식 공표 기준이 아님.',
  'missing_policy':'원본 미응답/비해당은 그대로 보존. 문항별 유효응답 분모에서만 분리. 0/평균/null로 원자료 대체 없음.',
  'metrics':METRICS}
 (out/'survey_definitions.json').write_text(json.dumps(definitions,ensure_ascii=False,indent=2),encoding='utf-8')
 audit={'files':{k:{'original_filename':files[k].name,'sha256':hashes[k],'bytes':files[k].stat().st_size} for k in files},
  'household_rows':len(h),'household_columns':hwidth,'member_rows':len(p),'member_columns':pwidth,
  'single_household_n':int(h.A1_1.eq(1).sum()),'multiple_household_n':int(h.A1_1.gt(1).sum()),
  'single_member_rows':len(single_members),'household_size_sum':int(h.A1_1.sum()),
  'weight_sum':float(h.twgt.sum()),'identifier_audit':id_report,'member_within_household_repeated_items':common,'independent_marginals_agree':independent_marginals,
  'sample_age_distribution':{str(k):int(v) for k,v in derived[derived.household_type.eq('1인가구')].age_group.value_counts().items()},
  'raw_missing_debt_items':{c:int(h[c].isna().sum()) for c in ['B12_3','B12_4']},
  'microdata_publication':'개별 응답 원본 및 행 단위 사본은 배포 패키지에 포함하지 않음. 4개 차원의 집계만 사용.',
  'sav_policy':'SAV는 원본 체크섬·헤더의 표본수만 확인한 보조 원본. Excel과 합산하지 않음. 계산은 공식 코드북에 대응한 Excel 기준.',
  'no_imputation':True,'cube_rows':len(cube)}
 (out/'survey_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
 (out/'depression.csv').write_bytes(files['depression'].read_bytes())
 print(json.dumps({k:v for k,v in audit.items() if k!='files'},ensure_ascii=False,indent=2))
 return h,p,derived,cube


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--raw-dir',type=Path,required=True);parser.add_argument('--output-dir',type=Path,default=Path('.'))
 args=parser.parse_args();build(args.raw_dir,args.output_dir)
