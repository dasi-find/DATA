# 다시찾음 DATA

경찰청 공공데이터 API에서 **성남시 습득물 후보**를 수집하고, 다시찾음의 AI·백엔드가 사용할 수 있는 공통 형식으로 정규화하는 저장소입니다.

프로젝트 기획·일정·AI·데이터 참고 문서는 [성남 × KAIST AI 경진대회 Notion](https://app.notion.com/p/KAIST-AI-3bb08703035580f88aabcb7c06b0535b?source=copy_link)에서 관리합니다. 최종 기준은 사용자의 최신 지시와 이 대화에서 확정한 다시찾음 기획이며, Notion과 충돌하면 사용자에게 먼저 확인합니다.

재사용 가능한 정식 수집 모듈은 현재 **경찰청 포털기관 습득물정보 조회 서비스**까지 구현되어 있습니다. 다만 `scripts/build_seongnam_sample.py`는 표본 생성을 위해 **경찰관서 API와 포털기관 API를 모두 조회**합니다. 경찰관서 API도 이후 별도 수집 모듈로 분리해 같은 출력 스키마로 통합해야 합니다.

공식 API는 시·군 단위 검색을 지원하지 않습니다. 경기도 지역코드 `LCI000`으로 받은 뒤 `depPlace`(보관기관명) 화이트리스트로 성남 자료를 보수적으로 식별합니다. 따라서 현재 성남 건수는 실제 습득 장소 기준 총수가 아니라 **성남임을 명확히 식별할 수 있는 하한**입니다.

## 담당 범위

```text
공공데이터 API 호출
→ XML 파싱
→ 날짜·출처·식별자 정규화
→ 기본 이미지와 실제 사진 URL 구분
→ 중복 제거
→ CSV·JSON 저장
```

현재 수집기는 사진 파일을 직접 내려받지 않고 `image_url`과 `has_real_image`를 저장합니다. 이미지 다운로드·개인정보 마스킹·객체 스토리지 연동은 후속 모듈로 분리합니다.

## 저장소 구조

```text
DATA/
├─ collectors/                 # 공공데이터 수집 및 정규화
│  └─ portal_institution.py
├─ scripts/                    # 팀원이 실행할 보조 스크립트
│  ├─ build_seongnam_sample.py # 두 API에서 성남 30+30 표본 생성
│  └─ run_portal_sample.ps1
├─ tests/                      # 파서와 정규화 테스트
├─ data/                       # 생성 데이터(README 외 Git 제외)
├─ images/                     # 다운로드 이미지(README 외 Git 제외)
├─ .env.example
├─ .gitignore
└─ requirements.txt
```

## 처음 실행하기

Python 3.11 이상을 권장합니다. 현재는 외부 Python 패키지가 필요하지 않습니다.

1. `.env.example`을 복사하여 `.env`를 만듭니다.
2. 공공데이터포털에서 발급받은 일반 인증키를 입력합니다.

```text
DATA_GO_KR_PORTAL_KEY=발급받은_인증키
```

`.env`는 절대 GitHub·노션·메신저에 올리지 않습니다.

### PowerShell에서 실행

```powershell
.\scripts\run_portal_sample.ps1
```

### Python으로 직접 실행

```powershell
python -m collectors.portal_institution --rows 20 --pages 1
```

기간과 저장량을 지정할 수도 있습니다.

```powershell
python -m collectors.portal_institution `
  --start 20260801 `
  --end 20260825 `
  --rows 100 `
  --pages 5
```

결과는 기본적으로 `data/processed/`에 저장됩니다.

## 성남 30+30 표본

2026-07-28~2026-08-26 경기도 자료 중 성남 소재 보관기관을 엄격히 식별해 다음 표본을 생성했습니다.

- 실제 이미지 포함 30건
- 사진 없이 텍스트로 검색할 항목 30건
- 두 출처를 합치되 `source`는 보존
- 이미지 표본에서 카드·신분증·현금·유가증권·지갑 등 고위험 범주 제외
- 장문 숫자와 전화번호 형태 텍스트 마스킹

생성 명령:

```powershell
python .\scripts\build_seongnam_sample.py
```

로컬 결과는 `data/samples/seongnam_30_30_v1/`에 생성됩니다. 주요 전달 파일은 다음과 같습니다.

| 파일 | 용도 |
|---|---|
| `all_items_60.jsonl` | AI·백엔드가 사용하는 기준 입력 |
| `with_image_30.csv` | 이미지 표본을 사람이 검토하는 목록 |
| `text_only_30.csv` | 텍스트 표본을 사람이 검토하는 목록 |
| `images/` | CSV의 `image_file` 상대경로가 가리키는 이미지 |
| `README.md` | 기간·범위·주의사항 |
| `checksums.sha256` | 파일 무결성 확인 |

생성된 사진은 `pii_review_status=NEEDS_MANUAL_REVIEW` 상태입니다. 30장을 직접 열어 카드번호·이름·전화번호·휴대전화 화면 등을 확인하기 전에는 GitHub, Notion 또는 공개 링크에 올리지 않습니다.

### 팀 전달 방식

- GitHub: 수집·정제 코드, 스키마, README, `.env.example`
- 비공개 OneDrive/Google Drive: 검수 완료한 `JSONL + CSV + images/ + README + checksums`
- 금지: `.env`, 인증키, 미검수 사진, 대용량 원본 ZIP의 Git 커밋

TXT 하나로 전달하지 않습니다. JSONL은 프로그램 입력, CSV는 사람 검토, 이미지 파일은 `image_file` 상대경로로 연결합니다. 현재 60건은 파이프라인 연결 시험용이며 가중치 평가는 별도의 `queries.jsonl`, `ground_truth.csv`, `pairs.csv`가 필요합니다.

## 테스트

```powershell
python -m unittest discover -s tests -v
```

테스트는 실제 API와 인증키를 사용하지 않으므로 누구나 실행할 수 있습니다.

## 공통 출력 스키마

| 필드 | 설명 |
|---|---|
| `source` | 데이터 출처. 현재 `PORTAL_INSTITUTION` |
| `source_id` | 출처 내부에서 유일한 관리번호와 순번 조합 |
| `atc_id` | 경찰민원24 관리번호 |
| `found_sequence` | 습득물 순번 |
| `category` | 물품 분류 |
| `color` | 등록 색상 |
| `item_name` | 물품명 |
| `title` | 등록 제목 |
| `image_url` | 원본 사진 또는 기본 이미지 URL |
| `has_real_image` | 기본 이미지가 아닌 실제 사진으로 추정되는지 여부 |
| `storage_place` | 현재 보관기관 |
| `found_date` | `YYYY-MM-DD`로 통일한 습득일 |

`storage_place`는 실제 습득 위치와 다를 수 있으므로 AI 위치 점수에 그대로 사용하면 안 됩니다. 상세 API에서 습득 장소를 추가 확보한 뒤 별도 필드로 관리해야 합니다.

## 협업 원칙

- 실제 인증키가 담긴 `.env`는 각 실행 환경에서만 관리합니다.
- 생성된 전체 데이터와 사진은 Git에 커밋하지 않습니다.
- AI 팀에는 정규화된 스키마와 소규모 비식별 샘플만 공유합니다.
- BE와 AI가 필드를 사용하기 시작한 뒤에는 기존 필드명을 임의로 바꾸지 않습니다.
- API별 차이는 수집 모듈 안에서 흡수하고 출력 형식은 동일하게 유지합니다.
- AI 결과는 동일 물건을 확정하지 않고 확인할 후보를 추천하는 용도로 사용합니다.
