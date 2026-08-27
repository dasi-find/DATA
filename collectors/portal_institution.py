from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


API_URL = (
    "https://apis.data.go.kr/1320000/"
    "LosPtfundInfoInqireService/"
    "getPtLosfundInfoAccToClAreaPd"
)
REPOSITORY_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = REPOSITORY_DIR / ".env"
DEFAULT_OUTPUT_DIR = REPOSITORY_DIR / "data" / "processed"
PLACEHOLDER_IMAGE_MARKERS = (
    "no_img",
    "no-image",
    "noimage",
    "placeholder",
    "default_image",
)


@dataclass(frozen=True)
class FoundItem:
    source: str
    source_id: str
    atc_id: str
    found_sequence: str
    category: str
    color: str
    item_name: str
    title: str
    image_url: str
    has_real_image: bool
    storage_place: str
    found_date: str


def load_env_file(path: Path) -> None:
    """간단한 KEY=VALUE 형식의 환경 파일을 읽습니다.

    이미 운영체제 환경변수에 들어 있는 값은 덮어쓰지 않습니다.
    """
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def text_of(element: ET.Element, tag: str) -> str:
    value = element.findtext(tag)
    return value.strip() if value else ""


def normalize_date(value: str) -> str:
    """API의 YYYYMMDD/ISO 날짜를 YYYY-MM-DD로 통일합니다."""
    stripped = value.strip()
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(stripped, date_format).date().isoformat()
        except ValueError:
            continue
    return stripped


def has_real_image(image_url: str) -> bool:
    normalized = image_url.strip().lower()
    return bool(normalized) and not any(
        marker in normalized for marker in PLACEHOLDER_IMAGE_MARKERS
    )


def parse_xml(xml_text: str) -> tuple[list[FoundItem], int, str, str]:
    root = ET.fromstring(xml_text)
    result_code = (root.findtext(".//resultCode") or "").strip()
    result_message = (
        root.findtext(".//resultMsg")
        or root.findtext(".//resultMag")
        or ""
    ).strip()

    total_text = root.findtext(".//totalCount") or "0"
    try:
        total_count = int(total_text)
    except ValueError:
        total_count = 0

    items: list[FoundItem] = []
    for item in root.findall(".//item"):
        atc_id = text_of(item, "atcId")
        found_sequence = text_of(item, "fdSn")
        image_url = text_of(item, "fdFilePathImg")
        source_id = f"{atc_id}-{found_sequence}".strip("-")

        # 관리번호가 없는 비정상 행은 후속 시스템에서 식별할 수 없으므로 제외합니다.
        if not source_id:
            continue

        items.append(
            FoundItem(
                source="PORTAL_INSTITUTION",
                source_id=source_id,
                atc_id=atc_id,
                found_sequence=found_sequence,
                category=text_of(item, "prdtClNm"),
                color=text_of(item, "clrNm"),
                item_name=text_of(item, "fdPrdtNm"),
                title=text_of(item, "fdSbjt"),
                image_url=image_url,
                has_real_image=has_real_image(image_url),
                storage_place=text_of(item, "depPlace"),
                found_date=normalize_date(text_of(item, "fdYmd")),
            )
        )

    return items, total_count, result_code, result_message


def build_request_url(service_key: str, params: dict[str, str | int]) -> str:
    """Encoding 인증키를 이중 인코딩하지 않고 요청 URL을 만듭니다."""
    other_query = urllib.parse.urlencode(params)
    if "%" in service_key:
        return f"{API_URL}?serviceKey={service_key}&{other_query}"

    full_params = {"serviceKey": service_key, **params}
    return f"{API_URL}?{urllib.parse.urlencode(full_params)}"


def fetch_page(
    service_key: str,
    start_date: str,
    end_date: str,
    page: int,
    rows: int,
) -> tuple[list[FoundItem], int]:
    params = {
        "pageNo": page,
        "numOfRows": rows,
        "START_YMD": start_date,
        "END_YMD": end_date,
    }
    request_url = build_request_url(service_key, params)
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "DasiFound-Data-Collector/1.0"},
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            xml_text = raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"API가 HTTP {exc.code} 오류를 반환했습니다.\n{body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"API 서버에 연결하지 못했습니다: {exc.reason}") from exc

    try:
        items, total_count, result_code, result_message = parse_xml(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            "XML이 아닌 응답을 받았습니다. 승인 상태·인증키·요청 주소를 확인하세요.\n"
            f"응답 앞부분: {xml_text[:500]}"
        ) from exc

    if result_code and result_code != "00":
        raise RuntimeError(
            f"API 오류: resultCode={result_code}, resultMessage={result_message}"
        )

    return items, total_count


def save_results(
    items: list[FoundItem],
    start_date: str,
    end_date: str,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"portal_items_{start_date}_{end_date}"
    csv_path = output_dir / f"{base_name}.csv"
    json_path = output_dir / f"{base_name}.json"
    rows = [asdict(item) for item in items]

    fieldnames = list(FoundItem.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return csv_path, json_path


def valid_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise argparse.ArgumentTypeError("날짜는 YYYYMMDD 형식이어야 합니다.")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("실제로 존재하는 날짜를 입력하세요.") from exc
    return value


def build_parser() -> argparse.ArgumentParser:
    today = date.today()
    parser = argparse.ArgumentParser(
        description="포털기관 습득물정보를 XML로 받아 정규화된 CSV와 JSON으로 저장합니다."
    )
    parser.add_argument(
        "--start",
        type=valid_date,
        default=(today - timedelta(days=7)).strftime("%Y%m%d"),
        help="검색 시작일 YYYYMMDD (기본값: 7일 전)",
    )
    parser.add_argument(
        "--end",
        type=valid_date,
        default=today.strftime("%Y%m%d"),
        help="검색 종료일 YYYYMMDD (기본값: 오늘)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=20,
        help="페이지당 결과 수 (기본값: 20)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="수집할 최대 페이지 수 (기본값: 1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="출력 폴더 (기본값: data/processed)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    load_env_file(ENV_PATH)
    service_key = os.environ.get("DATA_GO_KR_PORTAL_KEY", "").strip()

    if not service_key or service_key == "여기에_인증키를_입력하세요":
        print("인증키가 아직 입력되지 않았습니다.")
        print(f"{ENV_PATH} 파일의 DATA_GO_KR_PORTAL_KEY에 인증키를 입력하세요.")
        return 2

    if args.rows < 1 or args.pages < 1:
        print("--rows와 --pages는 1 이상이어야 합니다.")
        return 2
    if args.start > args.end:
        print("검색 시작일은 종료일보다 늦을 수 없습니다.")
        return 2

    collected: list[FoundItem] = []
    total_count = 0
    print(f"포털기관 습득물 조회: {args.start} ~ {args.end}")

    try:
        for page in range(1, args.pages + 1):
            page_items, total_count = fetch_page(
                service_key=service_key,
                start_date=args.start,
                end_date=args.end,
                page=page,
                rows=args.rows,
            )
            collected.extend(page_items)
            print(f"{page}페이지: {len(page_items)}건 수신")
            if not page_items or len(collected) >= total_count:
                break
    except RuntimeError as exc:
        print("\n수집에 실패했습니다.")
        print(exc)
        print("\n확인 순서: 승인 상태 → 인증키 종류 → 승인정보 반영시간 → 날짜 범위")
        return 1

    deduplicated_by_id: dict[str, FoundItem] = {}
    for item in collected:
        deduplicated_by_id[item.source_id] = item
    deduplicated = list(deduplicated_by_id.values())

    csv_path, json_path = save_results(
        deduplicated,
        args.start,
        args.end,
        args.output_dir,
    )
    actual_image_count = sum(item.has_real_image for item in deduplicated)

    print("\n수집 완료")
    print(f"API 전체 검색 결과: {total_count}건")
    print(f"이번 실행 저장 결과: {len(deduplicated)}건")
    print(f"실제 사진으로 추정되는 결과: {actual_image_count}건")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

