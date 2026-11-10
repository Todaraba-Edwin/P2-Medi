"""공공 API 스냅샷 수집기(BE-12).

- 서브명령: eyak-all(e약은요 전체), prmsn-names(허가정보 목록), prmsn-detail --products(허가정보 상세)
- 공통 옵션:
  - --dry-run: 예상 호출 수만 출력하고 실제 호출 0 (totalCount 모르면 "Unknown total count")
  - --probe: 첫 페이지만 호출해 totalCount 확인 (호출 1회)
  - --assume-total <n>: --dry-run과 함께 사용해 예상 페이지 수 계산
  - --max-calls: 호출 상한(기본 3,000)
  - --resume <파일>: 상태 파일로 페이지 단위 재개
- 호출 간 0.2초 지연, 429·한도 오류 시 중단하고 재개 위치 저장
- 출력: data/mock/api_snapshots/{eyak-all,prmsn-names,prmsn-detail}/ JSON + manifest.json
- redact.install_excepthook() 설치

사용:
  .venv/bin/python backend/scripts/collect_snapshots.py eyak-all --dry-run
  .venv/bin/python backend/scripts/collect_snapshots.py eyak-all --probe
  .venv/bin/python backend/scripts/collect_snapshots.py eyak-all --dry-run --assume-total 4749
  .venv/bin/python backend/scripts/collect_snapshots.py eyak-all --max-calls 50
  .venv/bin/python backend/scripts/collect_snapshots.py prmsn-names --probe
  .venv/bin/python backend/scripts/collect_snapshots.py prmsn-detail --products data/mock/api_snapshots/persona_eval_products.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.security.redact import install_excepthook
from app.tools.eyak import EyakClient
from app.tools.prmsn import PrmsnClient

_ROOT = Path(__file__).resolve().parents[2]


def _live_settings() -> Any:
    """저장소 루트 `.env`를 읽는 설정(실행 위치와 무관). 수집은 실호출이므로 live 모드로 만든다."""
    from pydantic_settings import SettingsConfigDict

    from app.config import Settings

    class _CollectSettings(Settings):
        model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    return _CollectSettings(_env_file=(str(_ROOT / ".env"), ".env"), mediagent_api_mode="live")

install_excepthook()

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "mock" / "api_snapshots"
MIN_DELAY = 0.2


def normalize_drug_name(name: str) -> str:
    """
    제품명 정규화 규칙:
    1. 공백 제거 (leading/trailing, internal spaces)
    2. 괄호 안 영문명 제거: "아스피린(Aspirin)" → "아스피린"
    3. 대소문자 통일 (한글은 그대로, 영문은 소문자)
    4. 전각 기호 통일 (띄어쓰기 관련)
    """
    if not isinstance(name, str):
        return ""
    # 공백 제거 (앞뒤)
    text = name.strip()
    # 괄호 안 텍스트 제거 (한글 이름만 남기기)
    text = re.sub(r"[（(].*?[）)]", "", text)
    # 내부 공백 제거
    text = text.replace(" ", "").replace("\t", "").replace("\n", "")
    # 다시 공백 정리
    text = text.strip()
    # 영문 소문자 변환
    text = text.lower()
    return text


def _norm_params(params: dict) -> dict:
    """기본값을 채우고 정렬(캐시 키와 같은 규칙)."""
    full = {"pageNo": 1, "numOfRows": 100, "type": "json", **params}
    return {k: str(v) for k, v in sorted(full.items())}


class Collector:
    """스냅샷 수집기."""

    def __init__(
        self,
        dry_run: bool = False,
        probe: bool = False,
        assume_total: int | None = None,
        max_calls: int = 3000,
        resume_file: str | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.probe = probe
        self.assume_total = assume_total
        self.max_calls = max_calls
        self.resume_file = Path(resume_file) if resume_file else None
        self.calls_made = 0
        self.start_time = time.time()
        self.last_call_time = self.start_time
        self.state: dict = {}

    def _delay(self) -> None:
        """호출 간 지연."""
        elapsed = time.time() - self.last_call_time
        if elapsed < MIN_DELAY:
            time.sleep(MIN_DELAY - elapsed)
        self.last_call_time = time.time()

    def _estimate_calls(self, total_count: int, num_of_rows: int = 100) -> int:
        """totalCount에서 필요한 호출 수."""
        if total_count <= 0:
            return 1
        return (total_count + num_of_rows - 1) // num_of_rows

    def _ensure_snap_dir(self, service: str) -> Path:
        """스냅샷 디렉터리 생성."""
        snap_dir = SNAP / service
        snap_dir.mkdir(parents=True, exist_ok=True)
        return snap_dir

    def _load_state_file(self, snap_dir: Path) -> dict:
        """상태 파일 로드."""
        state_file = snap_dir / "_collect_state.json"
        if state_file.exists():
            try:
                return json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_state_file(self, snap_dir: Path, state: dict) -> None:
        """상태 파일 저장."""
        state_file = snap_dir / "_collect_state.json"
        state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_manifest(self, manifest_data: dict) -> None:
        """manifest.json 저장."""
        manifest_file = SNAP / "manifest.json"
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _collect_pages(
        self,
        client: Any,
        command: str,
        total_count: int,
        num_of_rows: int = 100,
    ) -> tuple[int, dict, list[str]]:
        """페이지 순회하고 파일 저장. (수집 항목 수, 상태, 저장 파일 목록)."""
        snap_dir = self._ensure_snap_dir(command)
        saved_files = []

        # 상태 파일 로드 (resume)
        state = self._load_state_file(snap_dir)
        next_page = state.get("next_page_to_fetch", 1)
        last_successful_page = state.get("last_successful_page", 0)
        calls_made = state.get("calls_made", 0)

        total_pages = self._estimate_calls(total_count, num_of_rows)
        collected_items = 0
        all_item_seqs = set()
        final_state: dict = dict(state)

        try:
            for page_no in range(next_page, total_pages + 1):
                # 호출 수 상한 도달
                if calls_made >= self.max_calls:
                    print(f"{command}: 호출 상한({self.max_calls}) 도달. 중단.")
                    break

                # 이미 다운로드한 페이지 건너뜀
                page_file = snap_dir / f"page-{page_no}.json"
                if page_file.exists():
                    try:
                        page_data = json.loads(page_file.read_text(encoding="utf-8"))
                        items = page_data.get("items", [])
                        collected_items += len(items)
                        for item in items:
                            all_item_seqs.add(item.get("ITEM_SEQ") or item.get("item_seq", ""))
                        print(f"{command}: 수집 중... [{page_no}/{total_pages}] (총 호출 {calls_made})")
                        continue
                    except (json.JSONDecodeError, OSError):
                        pass

                # 페이지 호출
                self._delay()
                try:
                    if command == "eyak-all":
                        result = client.list_page(page_no=page_no, num_of_rows=num_of_rows)
                    elif command == "prmsn-names":
                        result = client.list_page(page_no=page_no, num_of_rows=num_of_rows)
                    else:
                        # prmsn-detail은 여기서 다루지 않음
                        break

                    calls_made += 1

                    if not result.ok or result.error:
                        print(f"{command}: 페이지 {page_no} 오류: {result.error}")
                        # 오류 상태 저장
                        error_state = {
                            "command": command,
                            "last_successful_page": last_successful_page,
                            "next_page_to_fetch": page_no,
                            "calls_made": calls_made,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "error": {
                                "kind": getattr(result.error, "kind", "unknown") if result.error else "unknown",
                                "http_status": getattr(result.error, "http_status", None) if result.error else None,
                                "message": str(result.error) if result.error else "unknown error",
                            },
                        }
                        self._save_state_file(snap_dir, error_state)
                        break

                    # 페이지 데이터 저장
                    page_data = {
                        "pageNo": result.page_no,
                        "numOfRows": result.num_of_rows,
                        "totalCount": result.total_count,
                        "items": [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in result.items],
                    }
                    page_file.write_text(json.dumps(page_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    saved_files.append(str(page_file))

                    items = page_data.get("items", [])
                    collected_items += len(items)
                    for item in items:
                        all_item_seqs.add(item.get("ITEM_SEQ") or item.get("item_seq", ""))

                    last_successful_page = page_no
                    print(f"{command}: 수집 중... [{page_no}/{total_pages}] (총 호출 {calls_made})")

                except Exception as e:
                    print(f"{command}: 페이지 {page_no} 예외: {e}")
                    break

            # 상태 파일 업데이트
            final_state = {
                "command": command,
                "last_successful_page": last_successful_page,
                "next_page_to_fetch": last_successful_page + 1,
                "total_count": total_count,
                "calls_made": calls_made,
                "timestamp": datetime.now(UTC).isoformat(),
                "error": None,
            }
            self._save_state_file(snap_dir, final_state)

        except Exception as e:
            print(f"{command}: 수집 중 예외: {e}")

        return collected_items, final_state, saved_files

    def collect_eyak_all(self) -> None:
        """e약은요 전체 수집."""
        client = EyakClient.from_settings(_live_settings())

        # --probe 또는 --dry-run일 때 첫 페이지 호출
        if self.probe or (not self.dry_run):
            self._delay()
            result = client.list_page(page_no=1, num_of_rows=100)
            self.calls_made = 1

            if not result.ok or result.error:
                print(f"Error querying first page: {result.error}")
                return

            total_count = result.total_count
        elif self.dry_run and self.assume_total:
            total_count = self.assume_total
        else:
            print("eyak-all: Unknown total count (--assume-total 사용 또는 --probe로 조회)")
            return

        total_pages = self._estimate_calls(total_count, 100)
        print(f"eyak-all: totalCount={total_count}, estimated_pages={total_pages}, estimated_calls={total_pages}")

        if self.probe:
            print(f"[PROBE] 첫 페이지 조회 완료. totalCount={total_count}, 페이지={total_pages}")
            return

        if self.dry_run:
            print(f"[DRY-RUN] {total_pages}개 페이지 호출 예상")
            return

        # 실제 수집
        if total_pages > self.max_calls:
            print(f"Warning: estimated calls {total_pages} exceeds max_calls {self.max_calls}")

        collected_items, state, saved_files = self._collect_pages(
            client,
            "eyak-all",
            total_count,
            num_of_rows=100,
        )

        calls_made = state.get('calls_made', 0)
        if calls_made >= self.max_calls:
            print(f"eyak-all: 상한 도달, 중단 ({calls_made}/{self.max_calls})")
        else:
            print(f"eyak-all: 수집 완료. {collected_items}개 항목, {len(saved_files)}개 페이지, 호출 {calls_made}회")

    def collect_prmsn_names(self) -> None:
        """허가정보 전체 목록 수집."""
        client = PrmsnClient.from_settings(_live_settings())

        # --probe 또는 --dry-run일 때 첫 페이지 호출
        if self.probe or (not self.dry_run):
            self._delay()
            result = client.list_page(page_no=1, num_of_rows=100)
            self.calls_made = 1

            if not result.ok or result.error:
                print(f"Error querying first page: {result.error}")
                return

            total_count = result.total_count
        elif self.dry_run and self.assume_total:
            total_count = self.assume_total
        else:
            print("prmsn-names: Unknown total count (--assume-total 사용 또는 --probe로 조회)")
            return

        total_pages = self._estimate_calls(total_count, 100)
        print(f"prmsn-names: totalCount={total_count}, estimated_pages={total_pages}, estimated_calls={total_pages}")

        if self.probe:
            print(f"[PROBE] 첫 페이지 조회 완료. totalCount={total_count}, 페이지={total_pages}")
            return

        if self.dry_run:
            print(f"[DRY-RUN] {total_pages}개 페이지 호출 예상")
            return

        # 실제 수집
        if total_pages > self.max_calls:
            print(f"Warning: estimated calls {total_pages} exceeds max_calls {self.max_calls}")

        collected_items, state, saved_files = self._collect_pages(
            client,
            "prmsn-names",
            total_count,
            num_of_rows=100,
        )

        calls_made = state.get('calls_made', 0)
        if calls_made >= self.max_calls:
            print(f"prmsn-names: 상한 도달, 중단 ({calls_made}/{self.max_calls})")
        else:
            print(f"prmsn-names: 수집 완료. {collected_items}개 항목, {len(saved_files)}개 페이지, 호출 {calls_made}회")

    def collect_prmsn_detail(self, products_file: str | None = None) -> None:
        """허가정보 상세 수집(제품 목록 기준).

        1. 제품명 → item_seq 매핑 (prmsn-names, eyak-all)
        2. 매핑된 item_seq마다 detail_by_item_seq 호출
        3. 응답 저장 및 manifest 생성
        """
        if not products_file:
            print("Error: --products 파일이 필요합니다")
            return

        products_path = Path(products_file)
        if not products_path.exists():
            print(f"Error: {products_file} 파일이 없습니다")
            return

        try:
            products = json.loads(products_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error reading {products_file}: {e}")
            return

        if not isinstance(products, list):
            print("Error: products 파일이 배열이어야 합니다")
            return

        product_count = len(products)

        # 1단계: 제품명 → item_seq 매핑
        product_mapping, unmatched_products = self._map_products_to_item_seqs(products)
        matched_count = len(product_mapping["items"])

        print(f"prmsn-detail: {product_count} requests, {matched_count} matched, {len(unmatched_products)} unmatched")

        if self.dry_run:
            estimated_calls = matched_count  # detail_by_item_seq 호출 수
            print(f"[DRY-RUN] {product_count}개 제품, {matched_count}개 매칭, 예상 호출 {estimated_calls}회")
            return

        # 2단계: 실제 수집
        snap_dir = self._ensure_snap_dir("prmsn-detail")

        # 상태 파일 로드
        state = self._load_state_file(snap_dir)
        next_item_index = state.get("next_item_index", 0)
        calls_made = state.get("calls_made", 0)
        matched_items_list = product_mapping.get("items", [])

        files_saved = 0
        client = PrmsnClient.from_settings(_live_settings())

        try:
            for idx, (_product_name, item_seq) in enumerate(matched_items_list[next_item_index:], start=next_item_index):
                # 호출 상한 도달
                if calls_made >= self.max_calls:
                    print(f"prmsn-detail: 호출 상한({self.max_calls}) 도달. 중단.")
                    break

                # 이미 있는 파일 건너뜀
                item_file = snap_dir / f"item-{item_seq}.json"
                if item_file.exists():
                    print(f"prmsn-detail: [{idx+1}/{len(matched_items_list)}] item-{item_seq} (캐시)")
                    files_saved += 1
                    continue

                # detail_by_item_seq 호출
                self._delay()
                try:
                    result = client.detail_by_item_seq(item_seq)
                    calls_made += 1

                    if not result.ok or result.error:
                        print(f"prmsn-detail: item-{item_seq} 오류: {result.error}")
                        error_state = {
                            "command": "prmsn-detail",
                            "last_successful_item_seq": matched_items_list[idx - 1][1] if idx > 0 else None,
                            "next_item_index": idx,
                            "matched_items": matched_items_list,
                            "calls_made": calls_made,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "error": {
                                "kind": getattr(result.error, "kind", "unknown") if result.error else "unknown",
                                "http_status": getattr(result.error, "http_status", None) if result.error else None,
                                "message": str(result.error) if result.error else "unknown error",
                            },
                        }
                        self._save_state_file(snap_dir, error_state)
                        break

                    # 응답 저장
                    item_data = {
                        "request": {"item_seq": item_seq},
                        "response": result.raw_items,
                        "fetched_at": result.queried_at_utc,
                        "from_cache": result.from_cache,
                        "source": result.source,
                    }
                    item_file.write_text(json.dumps(item_data, indent=2, ensure_ascii=False), encoding="utf-8")
                    files_saved += 1

                    print(f"prmsn-detail: [{idx+1}/{len(matched_items_list)}] item-{item_seq} 저장 (호출 {calls_made})")

                except Exception as e:
                    print(f"prmsn-detail: item-{item_seq} 예외: {e}")
                    break

        except Exception as e:
            print(f"prmsn-detail: 수집 중 예외: {e}")

        # 3단계: manifest 생성
        manifest_data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "product_requests": product_count,
            "matched_items": matched_count,
            "unmatched": unmatched_products,
            "item_seq_mapping_sources": product_mapping.get("sources", {}),
            "calls_made": calls_made,
            "files_saved": files_saved,
            "dedupe_note": self._get_eyak_dedupe_note(),
        }
        manifest_file = SNAP / "prmsn-detail" / "manifest.json"
        manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"prmsn-detail: 수집 완료. {files_saved}개 파일 저장, 호출 {calls_made}회")

    def _map_products_to_item_seqs(self, products: list[str]) -> tuple[dict, list[str]]:
        """제품명 → item_seq 매핑.

        Returns:
            (product_mapping, unmatched_products)
            product_mapping: {
                "items": [(product_name, item_seq), ...],
                "sources": {"prmsn_names_only": N, "eyak_all_only": N, "both_sources": N}
            }
        """
        # prmsn-names에서 item_seq 수집
        prmsn_name_map: dict[str, list[str]] = {}  # normalize_drug_name -> [item_seq, ...]
        prmsn_files = sorted((SNAP / "prmsn-names").glob("page-*.json"))

        for page_file in prmsn_files:
            try:
                page_data = json.loads(page_file.read_text(encoding="utf-8"))
                for item in page_data.get("items", []):
                    item_name = item.get("item_name", "")
                    item_seq = item.get("item_seq", "")
                    if item_name and item_seq:
                        normalized = normalize_drug_name(item_name)
                        if normalized not in prmsn_name_map:
                            prmsn_name_map[normalized] = []
                        if item_seq not in prmsn_name_map[normalized]:
                            prmsn_name_map[normalized].append(item_seq)
            except (json.JSONDecodeError, OSError):
                pass

        # eyak-all에서 item_seq 수집
        eyak_name_map: dict[str, list[str]] = {}
        eyak_files = sorted((SNAP / "eyak-all").glob("page-*.json"))

        for page_file in eyak_files:
            try:
                page_data = json.loads(page_file.read_text(encoding="utf-8"))
                for item in page_data.get("items", []):
                    item_name = item.get("item_name", "")
                    item_seq = item.get("item_seq", "")
                    if item_name and item_seq:
                        normalized = normalize_drug_name(item_name)
                        if normalized not in eyak_name_map:
                            eyak_name_map[normalized] = []
                        if item_seq not in eyak_name_map[normalized]:
                            eyak_name_map[normalized].append(item_seq)
            except (json.JSONDecodeError, OSError):
                pass

        # 제품명 매핑
        matched_items = []
        unmatched = []
        sources_count = {"prmsn_names_only": 0, "eyak_all_only": 0, "both_sources": 0}

        for product_name in products:
            normalized = normalize_drug_name(product_name)
            prmsn_seqs = prmsn_name_map.get(normalized, [])[:5]  # 상한 5개
            eyak_seqs = eyak_name_map.get(normalized, [])[:5]

            if prmsn_seqs or eyak_seqs:
                # 첫 번째 item_seq 사용
                combined_seqs = list(dict.fromkeys(prmsn_seqs + eyak_seqs))
                item_seq = combined_seqs[0]
                matched_items.append((product_name, item_seq))

                # 소스 분류
                if prmsn_seqs and eyak_seqs:
                    sources_count["both_sources"] += 1
                elif prmsn_seqs:
                    sources_count["prmsn_names_only"] += 1
                else:
                    sources_count["eyak_all_only"] += 1
            else:
                unmatched.append(product_name)

        return {
            "items": matched_items,
            "sources": sources_count,
        }, unmatched

    def _get_eyak_dedupe_note(self) -> str:
        """eyak-all 중복 정보 계산."""
        all_seqs = set()
        eyak_files = sorted((SNAP / "eyak-all").glob("page-*.json"))

        total_items = 0
        for page_file in eyak_files:
            try:
                page_data = json.loads(page_file.read_text(encoding="utf-8"))
                for item in page_data.get("items", []):
                    item_seq = item.get("item_seq", "")
                    if item_seq:
                        all_seqs.add(item_seq)
                        total_items += 1
            except (json.JSONDecodeError, OSError):
                pass

        unique_seqs = len(all_seqs)
        duplicates = total_items - unique_seqs
        return f"e약은요 {total_items:,}건 중 item_seq 중복 {duplicates}건 (고유 {unique_seqs:,}개)"


def main() -> None:
    parser = argparse.ArgumentParser(description="공공 API 스냅샷 수집기")
    parser.add_argument("command", choices=["eyak-all", "prmsn-names", "prmsn-detail"], help="수집 서브명령")
    parser.add_argument("--dry-run", action="store_true", help="예상 호출 수만 출력(실제 호출 0)")
    parser.add_argument("--probe", action="store_true", help="첫 페이지만 호출해 totalCount 확인(호출 1)")
    parser.add_argument("--assume-total", type=int, help="--dry-run과 함께 사용해 예상 페이지 수 계산")
    parser.add_argument("--max-calls", type=int, default=3000, help="호출 상한(기본 3,000)")
    parser.add_argument("--resume", help="상태 파일로 페이지 단위 재개")
    parser.add_argument("--products", help="prmsn-detail용 제품 목록 JSON 파일")

    args = parser.parse_args()

    collector = Collector(
        dry_run=args.dry_run,
        probe=args.probe,
        assume_total=args.assume_total,
        max_calls=args.max_calls,
        resume_file=args.resume,
    )

    if args.command == "eyak-all":
        collector.collect_eyak_all()
    elif args.command == "prmsn-names":
        collector.collect_prmsn_names()
    elif args.command == "prmsn-detail":
        collector.collect_prmsn_detail(args.products)


if __name__ == "__main__":
    main()
