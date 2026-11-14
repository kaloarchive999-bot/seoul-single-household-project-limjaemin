"""배포 집계파일만으로 실행 가능: python -m pytest -q test_app.py"""
import json,math,sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
import core
import analytics as an


def assets():
 raw=core.asset_path('source.csv').read_bytes();return core.load_csv(raw)[0]


def test_bundle_checksums():
 obj=an.verify_manifest();assert obj['original_data_modified'] is False
 assert len(obj['files'])==8


def test_original_csv_all_cells_and_totals():
 blob=core.asset_path('source.csv').read_bytes();core.verify_source(blob,core.CSV_SHA,'CSV')
 frame,rows,_=core.load_csv(blob)
 for i,row in enumerate(rows[3:]):assert frame.iloc[i,3:].tolist()==list(map(int,row[3:]))
 assert frame.shape==(78,19)
 for sex,n in [('계',1699910),('남자',788068),('여자',911842)]:
  g=core.group_seoul(frame,sex);assert g['합계'].sum()==n
  assert g[list(core.GROUPS)].to_numpy().sum()==n
 assert core.select_seoul(core.group_seoul(frame),['60대'])['선택연령_가구수'].sum()==220423


def test_bad_csv_values_stop_without_replacement():
 raw=core.asset_path('source.csv').read_bytes()
 for cell in [b'',b'null',b'NaN',b'-',b'0']:
  with pytest.raises(core.DataError):core.load_csv(raw.replace(b'1699910',cell,1))


def test_pdf_published_values():
 totals,shares=core.load_pdf(core.asset_path('source.pdf').read_bytes())
 assert totals.loc[totals['지역'].eq('전국'),'1인가구_천가구'].iloc[0]=='8,045'
 assert shares.loc[shares['지역'].eq('서울'),'29세 이하'].iloc[0]=='29.5'
 assert len(totals)==18 and len(shares)==18


def test_cube_sample_no_double_count():
 cube,defs=an.load_cube()
 part=cube[cube.metric.eq('loneliness')]
 assert part.total_n.sum()==3004
 assert part[part.household_type.eq('1인가구')].total_n.sum()==821
 assert part[part.household_type.ne('1인가구')].total_n.sum()==2183
 assert len(cube)==1287 and len(defs['metrics'])==11
 assert not cube.isna().any().any()
 assert (cube.valid_n+cube.missing_n==cube.eligible_n).all()


def test_baseline_aggregates_match_independent_check():
 expected=json.loads((BASE/'validation_expected.json').read_text())
 cube,defs=an.load_cube()
 for e in expected['summary']:
  out=an.pool_cube(cube,['household_type'],e['metric'],an.AGES,'계',an.REGIONS,e['household_type']).iloc[0]
  assert out.valid_n==e['valid_n']
  assert math.isclose(out.weight_sum,e['weight_sum'],rel_tol=1e-13)
  assert math.isclose(out.value,e['value'],rel_tol=1e-13,abs_tol=1e-13)
 assert expected['independently_checked_cells']==1287


def test_pool_uses_weighted_sums_not_average_rates():
 cube,_=an.load_cube()
 args=dict(metric='loneliness',ages=['20대','60대'],sex='여자',regions=['도심권','서남권'],household='1인가구')
 out=an.pool_cube(cube,[],**args).iloc[0]
 sel=cube[cube.metric.eq(args['metric'])&cube.age_group.isin(args['ages'])&cube.sex.eq('여자')&cube.region.isin(args['regions'])&cube.household_type.eq('1인가구')]
 assert math.isclose(out.value,sel.weighted_sum.sum()/sel.weight_sum.sum(),rel_tol=1e-14)
 assert math.isclose(out.effective_n,sel.weight_sum.sum()**2/sel.weight_square_sum.sum(),rel_tol=1e-14)


def test_nonapplicable_debt_kept_separate():
 cube,_=an.load_cube()
 out=an.pool_cube(cube,[],'debt_burden',an.AGES,'계',an.REGIONS,None).iloc[0]
 assert out.total_n==3004 and out.nonapplicable_n==1914 and out.valid_n==1090
 assert out.missing_n==0
 assert not an.pool_cube(cube,[],'debt_burden',['20세 미만']).shape[0]


def test_identifier_issue_is_reported_not_corrected():
 audit=json.loads(core.asset_path('survey_audit.json').read_text())
 assert audit['identifier_audit']['household_only_ids']==[3005]
 assert audit['identifier_audit']['member_only_ids']==[695]
 assert audit['identifier_audit']['join_performed'] is False
 assert audit['identifier_audit']['same_id_household_size_mismatch_n']==1571


def test_depression_original_rates_and_age_labels():
 d=an.load_depression()
 assert d.loc[d['구분'].eq('서울시'),'전체'].iloc[0]=='7.1'
 assert d.loc[d['대상'].eq('관악구'),'전체'].iloc[0]=='10.0'
 assert d.loc[d['구분'].eq('연령별'),'대상'].iloc[0]=='19~29세'
 assert len(d[d['구분'].eq('지역소분류')])==25


@pytest.mark.parametrize('k',[2,3,4,5])
def test_clusters_conserve_original_counts_and_are_deterministic(k):
 frame=assets();out,summary,score=an.district_clusters(frame,k=k)
 out2,_,_=an.district_clusters(frame,k=k)
 assert len(out)==25 and out['유형'].nunique()==k
 assert out['유형'].tolist()==out2['유형'].tolist()
 assert out['합계'].sum()==1699910
 assert out['20세이상_분모'].sum()==1699910-12116
 assert -1<=score<=1


def test_asset_paths_support_flat_and_subfolder_and_reject_conflicts(tmp_path,monkeypatch):
 monkeypatch.setattr(core,'BASE',tmp_path)
 (tmp_path/'x.txt').write_text('same')
 assert core.asset_path('x.txt')==tmp_path/'x.txt'
 (tmp_path/'data').mkdir();(tmp_path/'data/x.txt').write_text('same')
 assert core.asset_path('x.txt')==tmp_path/'x.txt'
 (tmp_path/'data/x.txt').write_text('different')
 with pytest.raises(core.DataError):core.asset_path('x.txt')


def new_app():return AppTest.from_file(str(BASE/'app.py'),default_timeout=45).run()


def check(at,allow_audit=False):
 assert not at.exception,[x.message for x in at.exception]
 errors=[x.value for x in at.error]
 if allow_audit:errors=[x for x in errors if not x.startswith('원자료 식별자 불일치 발견')]
 assert not errors,errors


@pytest.mark.parametrize('page',['어디에 사는가','세대별 어려움','5개 권역 비교','지역의 연령 유형','지역 건강 배경','전국 분포','근거·원본 검증'])
def test_all_seven_ui_pages(page):
 at=new_app();at.sidebar.radio[0].set_value(page).run();check(at,allow_audit=page=='근거·원본 검증')
 assert at.title[0].value=='같은 1인가구, 같은 어려움일까?'


def test_ui_all_survey_domains_and_definitions():
 at=new_app();at.sidebar.radio[0].set_value('세대별 어려움').run();check(at)
 for domain in ['경제','관계·지원','건강','소득·지출']:
  at.selectbox[0].set_value(domain).run();check(at)
  for metric in list(at.selectbox[1].options):
   # options are display labels; select by index to avoid label/id ambiguity.
   idx=at.selectbox[1].options.index(metric)
   at.selectbox[1].select_index(idx).run();check(at)
 at.checkbox[0].set_value(True).run();check(at)


def test_empty_selection_and_no_survey_sample_are_not_zero():
 at=new_app();at.sidebar.multiselect[0].set_value([]).run();check(at)
 assert not at.get('plotly_chart')
 at.sidebar.radio[0].set_value('세대별 어려움').run()
 at.sidebar.multiselect[0].set_value(['20세 미만']).run();check(at)
 assert not at.get('plotly_chart')


def test_background_and_national_selections():
 at=new_app();at.sidebar.radio[0].set_value('지역 건강 배경').run()
 at.sidebar.radio[1].set_value('여자').run();check(at)
 assert at.metric[0].value=='8.5%'
 at.sidebar.radio[0].set_value('전국 분포').run();check(at)
 next(r for r in at.radio if r.label=='전국 지표').set_value('연령별 전국 내 지역 분포').run();check(at)
 assert len(at.get('plotly_chart'))==2
