from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from collectors.portal_institution import (
    ENV_PATH,
    has_real_image,
    load_env_file,
    normalize_date,
    text_of,
)


REGION_CODE_GYEONGGI = "LCI000"
API_URLS = {
    "POLICE": (
        "https://apis.data.go.kr/1320000/LosfundInfoInqireService/"
        "getLosfundInfoAccToClAreaPd"
    ),
    "PORTAL_INSTITUTION": (
        "https://apis.data.go.kr/1320000/LosPtfundInfoInqireService/"
        "getPtLosfundInfoAccToClAreaPd"
    ),
}

# 목록 API는 시 단위 코드와 실제 습득 장소를 주지 않습니다. 아래 목록은
# 경기도 결과 중 성남 소재임을 보관기관명으로 명확히 확인한 보수적 화이트리스트입니다.
SEONGNAM_PLACES = {
    "POLICE": {
        "분당경찰서",
        "분당경찰서민원봉사실",
        "성남수정경찰서",
        "성남중원경찰서",
        "수진지구대",
        "수진1파출소",
        "은행파출소",
        "단대파출소",
        "위례파출소",
        "도촌파출소",
        "서판교파출소",
        "동판교파출소",
        "야탑지구대",
        "서현지구대",
        "신흥지구대",
        "금광지구대",
        "고등파출소",
        "태평4파출소",
        "수내파출소",
        "산성파출소",
    },
    "PORTAL_INSTITUTION": {
        "현대백화점(판교점)",
        "판교역(한국철도공사)",
        "판교역(신분당선)",
        "CGV(판교)",
        "CGV(야탑)",
        "CGV(서현점)",
        "CGV(오리점)",
        "분당서울대학교병원",
        "성남문화재단",
        "(주)카카오판교오피스",
        "모란역(8호선)",
        "모란역(한국철도공사)",
        "야탑역(한국철도공사)",
        "서현역(한국철도공사)",
        "수내역(한국철도공사)",
        "정자역(한국철도공사)",
        "정자역(신분당선)",
        "미금역(신분당선)",
        "오리역(한국철도공사)",
        "태평역(한국철도공사)",
        "가천대역(한국철도공사)",
        "수진역(8호선)",
        "단대오거리역(8호선)",
        "남한산성입구역(8호선)",
        "남위례역(8호선)",
        "다이소(성남중앙점)",
        "다이소(분당효자촌점)",
        "다이소(분당미금(역)점)",
    },
}

SENSITIVE_IMAGE_CATEGORIES = {"카드", "증명서", "현금", "유가증권", "지갑"}
SENSITIVE_TEXT_CATEGORIES = {"카드", "증명서", "현금", "유가증권"}
PLACEHOLDER_OR_TEST = re.compile(r"테스트|test", re.IGNORECASE)
LONG_NUMBER = re.compile(r"(?<!\d)\d{6,}(?!\d)")
PHONE_NUMBER = re.compile(r"01[016789][- ]?\d{3,4}[- ]?\d{4}")


@dataclass(frozen=True)
class SampleItem:
    source: str
    source_id: str
    atc_id: str
    found_sequence: str
    category_l1: str
    category_l2: str
    color: str
    item_name: str
    title: str
    found_date: str
    storage_place: str
    image_url: str
    has_image: bool


def build_url(base_url: str, service_key: str, params: dict[str, str | int]) -> str:
    query = urllib.parse.urlencode(params)
    if "%" in service_key:
        return f"{base_url}?serviceKey={service_key}&{query}"
    return f"{base_url}?{urllib.parse.urlencode({'serviceKey': service_key, **params})}"


def split_category(value: str) -> tuple[str, str]:
    parts = [part.strip() for part in value.split(">", 1)]
    return parts[0], parts[1] if len(parts) > 1 else ""


def fetch_source(
    source: str, service_key: str, start_date: str, end_date: str
) -> list[SampleItem]:
    url = build_url(
        API_URLS[source],
        service_key,
        {
            "START_YMD": start_date,
            "END_YMD": end_date,
            "N_FD_LCT_CD": REGION_CODE_GYEONGGI,
            "pageNo": 1,
            "numOfRows": 20000,
        },
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "DasiFound-Seongnam-Sample/1.0"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        root = ET.fromstring(response.read())

    result_code = (root.findtext(".//resultCode") or "").strip()
    if result_code and result_code != "00":
        message = (root.findtext(".//resultMsg") or "").strip()
        raise RuntimeError(f"{source} API 오류: {result_code} {message}")

    results: list[SampleItem] = []
    allowed_places = SEONGNAM_PLACES[source]
    for node in root.findall(".//item"):
        storage_place = text_of(node, "depPlace")
        if storage_place not in allowed_places:
            continue
        atc_id = text_of(node, "atcId")
        found_sequence = text_of(node, "fdSn")
        if not atc_id:
            continue
        category_l1, category_l2 = split_category(text_of(node, "prdtClNm"))
        image_url = text_of(node, "fdFilePathImg")
        results.append(
            SampleItem(
                source=source,
                source_id=f"{source}:{atc_id}:{found_sequence}",
                atc_id=atc_id,
                found_sequence=found_sequence,
                category_l1=category_l1,
                category_l2=category_l2,
                color=text_of(node, "clrNm"),
                item_name=text_of(node, "fdPrdtNm"),
                title=text_of(node, "fdSbjt"),
                found_date=normalize_date(text_of(node, "fdYmd")),
                storage_place=storage_place,
                image_url=image_url,
                has_image=has_real_image(image_url),
            )
        )
    return results


def mask_text(value: str) -> str:
    value = PHONE_NUMBER.sub("[PHONE]", value)
    return LONG_NUMBER.sub("[NUMBER]", value)


def round_robin_sample(
    items: list[SampleItem], count: int, seed: int
) -> list[SampleItem]:
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[SampleItem]] = {}
    for item in items:
        groups.setdefault((item.source, item.category_l1), []).append(item)
    for group in groups.values():
        rng.shuffle(group)

    keys = list(groups)
    rng.shuffle(keys)
    selected: list[SampleItem] = []
    while keys and len(selected) < count:
        next_keys: list[tuple[str, str]] = []
        for key in keys:
            group = groups[key]
            if group and len(selected) < count:
                selected.append(group.pop())
            if group:
                next_keys.append(key)
        keys = next_keys
    return selected


def image_extension(data: bytes, content_type: str) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if content_type.startswith("image/jpeg"):
        return ".jpg"
    if content_type.startswith("image/png"):
        return ".png"
    return None


def download_image(url: str) -> tuple[bytes, str] | None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "DasiFound-Seongnam-Sample/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            content_type = response.headers.get_content_type().lower()
            data = response.read(12 * 1024 * 1024)
    except Exception:
        return None
    extension = image_extension(data, content_type)
    if extension is None or len(data) < 1024:
        return None
    return data, extension


def item_row(
    item: SampleItem, sample_id: str, image_file: str = ""
) -> dict[str, str | bool]:
    item_name = mask_text(item.item_name)
    title = mask_text(item.title)
    return {
        "sample_id": sample_id,
        "source": item.source,
        "source_id": item.source_id,
        "atc_id": item.atc_id,
        "found_sequence": item.found_sequence,
        "category_l1": item.category_l1,
        "category_l2": item.category_l2,
        "color": item.color,
        "item_name": item_name,
        "title": title,
        "text_for_embedding": " | ".join(
            part
            for part in (
                item.category_l1,
                item.category_l2,
                item.color,
                item_name,
                title,
            )
            if part
        ),
        "found_date": item.found_date,
        "storage_place": item.storage_place,
        "image_file": image_file,
        "image_url": item.image_url if image_file else "",
        "has_image": bool(image_file),
        "scope": "STRICT_SEONGNAM_BY_STORAGE_PLACE",
        "pii_review_status": "NEEDS_MANUAL_REVIEW" if image_file else "TEXT_MASKED",
    }


def write_csv(path: Path, rows: list[dict[str, str | bool]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="성남 전용 30+30 검토용 샘플 생성")
    parser.add_argument("--start", default="20260728")
    parser.add_argument("--end", default="20260826")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "data"
        / "samples"
        / "seongnam_30_30_v1",
    )
    parser.add_argument("--seed", type=int, default=20260826)
    args = parser.parse_args()

    load_env_file(ENV_PATH)
    service_key = os.environ.get("DATA_GO_KR_PORTAL_KEY", "").strip()
    if not service_key:
        raise SystemExit(f"{ENV_PATH}에 DATA_GO_KR_PORTAL_KEY가 필요합니다.")

    all_items: list[SampleItem] = []
    for source in API_URLS:
        fetched = fetch_source(source, service_key, args.start, args.end)
        print(f"{source}: 성남 명시 보관기관 {len(fetched)}건")
        all_items.extend(fetched)

    image_candidates = [
        item
        for item in all_items
        if item.has_image
        and item.category_l1 not in SENSITIVE_IMAGE_CATEGORIES
        and not PLACEHOLDER_OR_TEST.search(f"{item.item_name} {item.title}")
    ]
    text_candidates = [
        item
        for item in all_items
        if not item.has_image
        and item.category_l1 not in SENSITIVE_TEXT_CATEGORIES
        and len(f"{item.item_name} {item.title}".strip()) >= 10
        and not PLACEHOLDER_OR_TEST.search(f"{item.item_name} {item.title}")
    ]

    output_dir = args.output_dir
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    image_rows: list[dict[str, str | bool]] = []
    ordered_images = round_robin_sample(image_candidates, len(image_candidates), args.seed)
    for item in ordered_images:
        downloaded = download_image(item.image_url)
        if downloaded is None:
            continue
        data, extension = downloaded
        sample_id = f"IMG_{len(image_rows) + 1:03d}"
        file_name = f"{sample_id}{extension}"
        (images_dir / file_name).write_bytes(data)
        image_rows.append(item_row(item, sample_id, f"images/{file_name}"))
        if len(image_rows) == 30:
            break

    text_items = round_robin_sample(text_candidates, 30, args.seed + 1)
    text_rows = [
        item_row(item, f"TXT_{index:03d}")
        for index, item in enumerate(text_items, start=1)
    ]
    if len(image_rows) < 30 or len(text_rows) < 30:
        raise RuntimeError(
            f"샘플 부족: 이미지 {len(image_rows)}건, 텍스트 {len(text_rows)}건"
        )

    write_csv(output_dir / "with_image_30.csv", image_rows)
    write_csv(output_dir / "text_only_30.csv", text_rows)
    all_rows = image_rows + text_rows
    with (output_dir / "all_items_60.jsonl").open("w", encoding="utf-8") as handle:
        for row in all_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    readme = f"""# 성남 30+30 샘플 v1

- 조회 기간: {args.start} ~ {args.end}
- 범위: 경기도 API 결과 중 성남 소재임을 보관기관명으로 명확히 식별한 보수적 표본
- 구성: 실제 사진 30건 + 사진 없는 텍스트 30건
- 출처: POLICE + PORTAL_INSTITUTION
- 랜덤 시드: {args.seed}

## 주의

- storage_place는 실제 습득 장소가 아니라 보관기관입니다.
- 성남 전체 건수가 아니라 성남임을 명확히 식별할 수 있는 하한 표본입니다.
- images/는 자동 다운로드 결과이며 AI 담당자에게 전달하기 전에 30장을 직접 열어 개인정보와 오이미지를 검수해야 합니다.
- pii_review_status=NEEDS_MANUAL_REVIEW인 이미지는 GitHub 또는 Notion에 업로드하지 마세요.
- 이 60건은 파이프라인 연결용 후보 목록입니다. 점수 가중치 평가는 별도의 queries.jsonl, ground_truth.csv, pairs.csv가 필요합니다.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")

    checksum_lines: list[str] = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name not in {"checksums.sha256"}:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            checksum_lines.append(f"{digest}  {path.relative_to(output_dir).as_posix()}")
    (output_dir / "checksums.sha256").write_text(
        "\n".join(checksum_lines) + "\n", encoding="ascii"
    )

    zip_path = output_dir.parent / f"{output_dir.name}_UNREVIEWED.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in output_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir.parent))

    print(f"완료: {output_dir}")
    print(f"검수 전 ZIP: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
