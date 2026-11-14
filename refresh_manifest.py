"""원본 검증 후 배포용 파생파일의 체크섬 목록을 생성. 통계값은 수정하지 않음."""
from pathlib import Path
import argparse,hashlib,json
NAMES=['source.csv','source.pdf','provinces_2020.json','seoul_2020.json','depression.csv','survey_cube.csv','survey_definitions.json','survey_audit.json']
LOCKED={'source.csv':'df180d9e1509f3a63ed64d878d1d1a060067ba2b4399a13061b9a8a2e97aa321','source.pdf':'0f74d8fff2d094d16a6f9034a595fcd0b0ebea711dc809a76ac45316f5d101f3','depression.csv':'1a19041d6734ba0f12bcd285a00e08c6200f66a428d8d28d652f444da7c5fc8a'}

def refresh(folder):
 files={}
 for name in NAMES:
  path=folder/name
  if not path.is_file():raise FileNotFoundError(name)
  blob=path.read_bytes();digest=hashlib.sha256(blob).hexdigest()
  if name in LOCKED and digest!=LOCKED[name]:raise ValueError(f'{name}: 검토된 원본 체크섬과 다릅니다.')
  files[name]={'sha256':digest,'bytes':len(blob),'role':'원본 통계' if name in LOCKED else '표시용 참고 경계' if '2020.json' in name else '검증된 파생 집계/설명'}
 obj={'app_title':'같은 1인가구, 같은 어려움일까?','build_date_utc':'2026-11-14','schema_version':2,
  'original_data_modified':False,'survey_geography':'5개 권역','microdata_included':False,
  'geometry_note':'2020년 참고 경계. 원본의 공백/들여쓰기만 제거했으며 좌표·속성은 동일. 렌더링 시 윤곽만 단순화.',
  'files':files}
 (folder/'data_manifest.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
 return obj
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assets-dir',type=Path,default=Path('.'));args=p.parse_args();refresh(args.assets_dir)
