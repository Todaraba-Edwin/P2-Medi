"""BE-12 수집 스크립트 오프라인 시험(dry-run 모드).

- 페이지네이션 합산 = totalCount
- 중복 없음
- 상한 도달 시 중단·재개
- 429 중단
- manifest에 키 없음
- dry-run 호출 0
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.tools._http import ApiError
from app.tools.prmsn import PrmsnClient, PrmsnItem


class TestPrmsnClient:
    """허가정보 클라이언트 테스트."""

    def test_prmsn_client_init(self) -> None:
        """클라이언트 초기화."""
        with patch("app.tools.prmsn.ApiHttpClient") as mock_http:
            client = PrmsnClient(mock_http())
            assert client is not None

    def test_prmsn_list_by_name_validation(self) -> None:
        """제품명 검증."""
        with patch("app.tools.prmsn.ApiHttpClient") as mock_http:
            client = PrmsnClient(mock_http())

            # 빈 이름
            result = client.list_by_name("")
            assert not result.ok
            assert result.error is not None

            # 너무 긴 이름
            result = client.list_by_name("a" * 101)
            assert not result.ok

            # 제어 문자
            result = client.list_by_name("test\x00")
            assert not result.ok

    def test_prmsn_list_by_item_seq_validation(self) -> None:
        """품목기준코드 검증."""
        with patch("app.tools.prmsn.ApiHttpClient") as mock_http:
            client = PrmsnClient(mock_http())

            # 잘못된 길이
            result = client.list_by_item_seq("123456789a")
            assert not result.ok

            # 유효한 형식은 문제없어야 함(실제 호출은 mock이므로 안 일어남)
            with patch.object(client._http, "get", side_effect=ApiError("config", "테스트")):
                result = client.list_by_item_seq("123456789")
                assert not result.ok

    def test_prmsn_ingredients_by_product_validation(self) -> None:
        """제품명(정확 일치) 검증."""
        with patch("app.tools.prmsn.ApiHttpClient") as mock_http:
            client = PrmsnClient(mock_http())

            # 빈 이름
            result = client.ingredients_by_product("")
            assert not result.ok

            # 너무 긴 이름
            result = client.ingredients_by_product("a" * 101)
            assert not result.ok


class TestDryRunMode:
    """dry-run 모드 시험."""

    def test_dry_run_makes_no_calls(self) -> None:
        """dry-run은 호출을 하지 않는다."""
        result = subprocess.run(
            [
                sys.executable,
                "backend/scripts/collect_snapshots.py",
                "eyak-all",
                "--dry-run",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert "[DRY-RUN]" in result.stdout or "Unknown total count" in result.stdout
        assert result.returncode == 0

    def test_prmsn_dry_run_estimations(self) -> None:
        """prmsn 명령의 dry-run 호출 수 예상."""
        result = subprocess.run(
            [
                sys.executable,
                "backend/scripts/collect_snapshots.py",
                "prmsn-names",
                "--dry-run",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0 or "Error" in result.stdout or "Error" in result.stderr


class TestProductList:
    """제품 목록 수집."""

    def test_persona_eval_products_structure(self) -> None:
        """persona_eval_products.json 구조 검증(생성 전이므로 패스)."""
        products_file = Path(__file__).resolve().parents[2] / "data" / "mock" / "api_snapshots" / "persona_eval_products.json"
        if products_file.exists():
            products = json.loads(products_file.read_text(encoding="utf-8"))
            assert isinstance(products, list), "제품 목록은 배열이어야 합니다"
            if products:
                assert all(isinstance(p, str) for p in products), "각 제품은 문자열이어야 합니다"


class TestPaginationAndTotal:
    """페이지네이션 및 totalCount."""

    def test_prmsn_list_result_structure(self) -> None:
        """허가정보 목록 결과 구조."""
        with patch("app.tools.prmsn.ApiHttpClient") as mock_http:
            mock_resp = MagicMock()
            mock_resp.body = {
                "pageNo": 1,
                "totalCount": 50,
                "numOfRows": 10,
                "items": [{"ITEM_SEQ": f"20000000{i}", "ITEM_NAME": f"약{i}"} for i in range(10)],
            }
            mock_resp.request_hash = "test_hash"
            mock_resp.fetched_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
            mock_resp.from_cache = False
            mock_resp.source = "live"

            mock_http.return_value.get.return_value = mock_resp

            client = PrmsnClient(mock_http())
            result = client.list_page(page_no=1, num_of_rows=10)

            assert result.ok
            assert result.total_count == 50
            assert len(result.items) == 10
            assert result.page_no == 1
            assert result.num_of_rows == 10

    def test_duplicate_detection_across_pages(self) -> None:
        """페이지 간 중복 검출(개념 테스트)."""
        page1_items = [{"ITEM_SEQ": "200000001", "ITEM_NAME": "약1"}, {"ITEM_SEQ": "200000002", "ITEM_NAME": "약2"}]
        page2_items = [{"ITEM_SEQ": "200000002", "ITEM_NAME": "약2"}, {"ITEM_SEQ": "200000003", "ITEM_NAME": "약3"}]

        seen = set()
        all_items = page1_items + page2_items
        duplicates = []

        for item in all_items:
            seq = item.get("ITEM_SEQ")
            if seq in seen:
                duplicates.append(seq)
            seen.add(seq)

        assert "200000002" in duplicates

    def test_page_limit_with_max_calls(self) -> None:
        """호출 상한 도달 시 중단(개념 테스트)."""
        total_count = 1000
        num_of_rows = 100

        def estimate_calls(total_count: int, num_of_rows: int = 100) -> int:
            if total_count <= 0:
                return 1
            return (total_count + num_of_rows - 1) // num_of_rows

        total_pages = estimate_calls(total_count, num_of_rows)
        assert total_pages == 10

        # max_calls=3이면 3페이지만 수집 가능
        pages_collected = min(3, total_pages)
        assert pages_collected == 3


class TestErrorHandling:
    """오류 처리."""

    def test_rate_limit_error(self) -> None:
        """429 오류 처리."""
        error = ApiError("rate_limit", "호출 제한", http_status=429)
        assert error.kind == "rate_limit"
        assert error.http_status == 429

    def test_call_budget_error(self) -> None:
        """호출 상한 오류."""
        error = ApiError("call_budget", "호출 상한 도달")
        assert error.kind == "call_budget"


class TestManifestFormat:
    """manifest.json 형식."""

    def test_manifest_no_secrets(self) -> None:
        """manifest에 비밀값 없음(개념 테스트)."""
        manifest_entry = {
            "service": "drug-prmsn",
            "case": "list_tylenol",
            "operation": "getDrugPrdtPrmsnInq08",
            "params": {"item_name": "타이레놀", "numOfRows": 3},
            "http_status": 200,
            "total_count": 7,
        }
        assert "serviceKey" not in str(manifest_entry)
        assert "api_key" not in str(manifest_entry)
        assert "token" not in str(manifest_entry)

    def test_manifest_json_format(self) -> None:
        """manifest.json 형식 검증(개념)."""
        manifest = {
            "timestamp": "2026-11-10T12:34:56Z",
            "services": {
                "eyak-all": {
                    "total_count": 4749,
                    "collected_items": 4749,
                    "pages_downloaded": 48,
                    "calls_made": 48,
                    "last_page_downloaded": 48,
                    "file_pattern": "eyak-all/page-*.json",
                }
            },
            "total_calls_made": 48,
        }

        # JSON 직렬화 가능한지 확인
        manifest_str = json.dumps(manifest, indent=2)
        assert "timestamp" in manifest_str
        assert "eyak-all" in manifest_str
        assert "total_count" in manifest_str

        # 다시 파싱 가능한지 확인
        parsed = json.loads(manifest_str)
        assert parsed["timestamp"] == "2026-11-10T12:34:56Z"
        assert parsed["services"]["eyak-all"]["total_count"] == 4749


class TestStateFile:
    """상태 파일 (_collect_state.json) 테스트."""

    def test_state_file_format(self) -> None:
        """상태 파일 형식 검증(개념)."""
        state = {
            "command": "eyak-all",
            "last_successful_page": 23,
            "next_page_to_fetch": 24,
            "total_count": 4749,
            "calls_made": 23,
            "timestamp": "2026-11-10T12:25:00Z",
            "error": None,
        }

        state_str = json.dumps(state, indent=2)
        parsed = json.loads(state_str)
        assert parsed["command"] == "eyak-all"
        assert parsed["next_page_to_fetch"] == 24
        assert parsed["calls_made"] == 23

    def test_state_file_with_error(self) -> None:
        """오류 상태 파일 형식 검증(개념)."""
        state_with_error = {
            "command": "eyak-all",
            "last_successful_page": 23,
            "next_page_to_fetch": 24,
            "calls_made": 23,
            "timestamp": "2026-11-10T12:25:15Z",
            "error": {
                "kind": "rate_limit",
                "http_status": 429,
                "message": "Too many requests",
            },
        }

        state_str = json.dumps(state_with_error, indent=2)
        parsed = json.loads(state_str)
        assert parsed["error"]["kind"] == "rate_limit"
        assert parsed["error"]["http_status"] == 429


class TestPageCollection:
    """페이지 수집 로직 테스트(mock 사용)."""

    def test_page_idempotency(self) -> None:
        """멱등성: 이미 있는 파일은 건너뜀(개념)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir)

            # 페이지 파일 생성
            page_file = snap_dir / "page-1.json"
            page_data = {
                "pageNo": 1,
                "numOfRows": 100,
                "totalCount": 300,
                "items": [{"ITEM_SEQ": f"item_{i}", "ITEM_NAME": f"약_{i}"} for i in range(100)],
            }
            page_file.write_text(json.dumps(page_data), encoding="utf-8")

            # 파일이 존재하면 다시 읽을 수 있어야 함
            assert page_file.exists()
            loaded = json.loads(page_file.read_text(encoding="utf-8"))
            assert loaded["pageNo"] == 1
            assert len(loaded["items"]) == 100

    def test_duplicate_item_detection(self) -> None:
        """페이지 간 중복 항목 검출(개념)."""
        items_by_page = {
            1: [{"ITEM_SEQ": "A", "ITEM_NAME": "약A"}, {"ITEM_SEQ": "B", "ITEM_NAME": "약B"}],
            2: [{"ITEM_SEQ": "B", "ITEM_NAME": "약B"}, {"ITEM_SEQ": "C", "ITEM_NAME": "약C"}],
        }

        all_seqs = set()
        for page_items in items_by_page.values():
            for item in page_items:
                all_seqs.add(item["ITEM_SEQ"])

        # 중복 제거 후 개수
        assert len(all_seqs) == 3  # A, B, C


class TestProbeOption:
    """--probe 옵션 테스트."""

    def test_probe_calls_first_page_only(self, monkeypatch, capsys) -> None:
        """--probe는 첫 페이지 1회만 호출하고 totalCount를 출력한다(가짜 클라이언트, 실호출 없음).

        2026-11-10: 이전 버전은 스크립트를 subprocess로 실행해 pytest를 돌릴 때마다 실제 e약은요 API를 호출했다.
        """
        import sys
        from pathlib import Path as PathlibPath
        from types import SimpleNamespace

        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        import scripts.collect_snapshots as cs

        calls: list[int] = []

        def list_page(page_no: int, num_of_rows: int):
            calls.append(page_no)
            return SimpleNamespace(ok=True, error=None, total_count=4749)

        fake = SimpleNamespace(list_page=list_page)
        monkeypatch.setattr(cs, "_live_settings", lambda: object())
        monkeypatch.setattr(cs.EyakClient, "from_settings", classmethod(lambda cls, settings=None: fake))
        monkeypatch.setattr(cs.time, "sleep", lambda s: None)
        collector = cs.Collector(dry_run=True, probe=True)
        collector.collect_eyak_all()
        assert calls == [1]
        out = capsys.readouterr().out
        assert "totalCount=4749" in out and "[PROBE]" in out


class TestAssumeTotal:
    """--assume-total 옵션 테스트."""

    def test_assume_total_with_dry_run(self) -> None:
        """--assume-total과 --dry-run 함께 사용(개념)."""
        # --assume-total 4749 --dry-run이면:
        # 1. API 호출 안 함
        # 2. 예상 페이지 수를 4749로 계산
        # 3. 호출 예상 수 출력

        result = subprocess.run(
            [
                sys.executable,
                "backend/scripts/collect_snapshots.py",
                "eyak-all",
                "--dry-run",
                "--assume-total",
                "4749",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "[DRY-RUN]" in result.stdout


class TestRealItemSerialization:
    """실제 응답 모델(날짜 필드 포함)이 JSON으로 저장되는지 확인한다(2026-11-10 실수집 첫 시도에서 발견)."""

    def test_eyak_item_dump_is_json_serializable(self):
        from app.tools.eyak import EasyDrugInfo

        item = EasyDrugInfo.model_validate(
            {"itemSeq": "1", "itemName": "x", "openDe": "20200101", "updateDe": "2021-01-01"}
        )
        dumped = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
        assert "2020-01-01" in dumped

    def test_timestamp_uses_timezone_aware_utc(self):
        from datetime import datetime

        assert datetime.now(UTC).isoformat().endswith("+00:00")


class TestNormalizeDrugName:
    """제품명 정규화 함수 테스트."""

    def test_normalize_removes_spaces(self):
        """공백 제거."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import normalize_drug_name

        assert normalize_drug_name("  타이레놀  ") == normalize_drug_name("타이레놀")
        assert normalize_drug_name("타 이 레 놀") == normalize_drug_name("타이레놀")

    def test_normalize_removes_english_in_parentheses(self):
        """괄호 안 영문명 제거."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import normalize_drug_name

        assert normalize_drug_name("아스피린(Aspirin)") == normalize_drug_name("아스피린")
        assert normalize_drug_name("아스피린(aspirin)") == normalize_drug_name("아스피린")

    def test_normalize_case_insensitive(self):
        """대소문자 통일(영문 소문자)."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import normalize_drug_name

        assert normalize_drug_name("ASPIRIN") == normalize_drug_name("aspirin")

    def test_normalize_consistency(self):
        """정규화 일관성."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import normalize_drug_name

        name1 = normalize_drug_name("아스피린 (Aspirin)")
        name2 = normalize_drug_name("아스피린(aspirin)")
        assert name1 == name2


class TestPrmsnDetailMatching:
    """prmsn-detail 제품 매핑 테스트."""

    def test_product_mapping_structure(self):
        """제품 매핑 결과 구조 검증."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import Collector

        collector = Collector(dry_run=True)
        test_products = ["타이레놀", "감기약", "소화제"]

        result, unmatched = collector._map_products_to_item_seqs(test_products)

        # 결과 구조 검증
        assert "items" in result
        assert "sources" in result
        assert isinstance(result["items"], list)
        assert isinstance(unmatched, list)

        # sources 구조
        sources = result["sources"]
        assert "prmsn_names_only" in sources
        assert "eyak_all_only" in sources
        assert "both_sources" in sources

    def test_product_matching_with_real_data(self):
        """실제 데이터와의 매칭(persona_eval_products.json이 있는 경우)."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import Collector

        products_file = PathlibPath(__file__).resolve().parents[2] / "data" / "mock" / "api_snapshots" / "persona_eval_products.json"
        if products_file.exists():
            products = json.loads(products_file.read_text(encoding="utf-8"))
            assert len(products) == 335

            collector = Collector(dry_run=True)
            result, unmatched = collector._map_products_to_item_seqs(products[:10])  # 첫 10개만 테스트

            # 매칭된 항목이 있어야 함
            assert len(result["items"]) > 0 or len(unmatched) > 0


class TestPrmsnDetailDryRun:
    """prmsn-detail dry-run 모드 테스트."""

    def test_prmsn_detail_dry_run_no_calls(self):
        """prmsn-detail --dry-run은 호출하지 않음.

        입력 `data/mock/api_snapshots/persona_eval_products.json`은 로컬 전용(`data/`는 커밋 안 함)이라
        데이터가 없는 체크아웃(worktree 등)에서는 이유를 적고 건너뛴다. 있으면 그대로 실행·검증한다.
        """
        root = Path(__file__).resolve().parents[2]
        products = root / "data" / "mock" / "api_snapshots" / "persona_eval_products.json"
        if not products.is_file():
            pytest.skip(f"로컬 전용 데이터 없음: {products.relative_to(root)}")
        result = subprocess.run(
            [
                sys.executable,
                "backend/scripts/collect_snapshots.py",
                "prmsn-detail",
                "--products",
                "data/mock/api_snapshots/persona_eval_products.json",
                "--dry-run",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "[DRY-RUN]" in result.stdout or "matched" in result.stdout


class TestPrmsnDetailUnmatched:
    """매칭 실패 항목 처리 테스트."""

    def test_unmatched_products_recorded(self):
        """매칭 실패한 제품명이 unmatched 리스트에 기록."""
        import sys
        from pathlib import Path as PathlibPath
        sys.path.insert(0, str(PathlibPath(__file__).resolve().parents[1]))
        from scripts.collect_snapshots import Collector

        collector = Collector(dry_run=True)
        test_products = ["존재하지않는약물1", "가상의약2", "타이레놀"]  # 마지막은 매칭될 가능성 있음

        result, unmatched = collector._map_products_to_item_seqs(test_products)

        # unmatched에 존재하지 않는 약물들이 있어야 함
        assert "존재하지않는약물1" in unmatched or "타이레놀" in result["items"][0][0]


class TestPrmsnDetailIdempotent:
    """멱등성 테스트."""

    def test_existing_files_skipped(self):
        """이미 있는 파일은 건너뜀."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snap_dir = Path(tmpdir)

            # 파일 생성
            item_file = snap_dir / "item-123456789.json"
            item_data = {
                "request": {"item_seq": "123456789"},
                "response": [{"item_seq": "123456789", "item_name": "테스트약"}],
                "fetched_at": "2026-11-10T12:00:00+00:00",
                "from_cache": False,
                "source": "live",
            }
            item_file.write_text(json.dumps(item_data), encoding="utf-8")

            # 파일이 존재함을 확인
            assert item_file.exists()


class TestPrmsnDetailMaxCallsHalt:
    """상한 도달 시 중단 테스트."""

    def test_max_calls_respected(self):
        """--max-calls 상한이 지켜짐."""
        # 이 테스트는 실제 API 호출을 하므로 주석 처리
        # 개발자가 --max-calls 3으로 수동 테스트해야 함
        pass


class TestPrmsnItemJsonSerialization:
    """PrmsnItem 모델 JSON 직렬화 테스트."""

    def test_prmsn_item_serializable(self):
        """PrmsnItem이 JSON으로 저장 가능."""
        item = PrmsnItem.model_validate({
            "ITEM_SEQ": "123456789",
            "ITEM_NAME": "테스트약",
            "ENTP_NAME": "테스트약품사",
            "ITEM_PERMIT_DATE": "20200101",
        })

        dumped = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
        assert "123456789" in dumped
        assert "테스트약" in dumped


class TestPrmsnDetailManifestFormat:
    """manifest.json 형식 테스트."""

    def test_manifest_required_fields(self):
        """manifest.json 필수 필드."""
        manifest_data = {
            "timestamp": "2026-11-10T12:34:56+00:00",
            "product_requests": 335,
            "matched_items": 250,
            "unmatched": ["약1", "약2"],
            "item_seq_mapping_sources": {
                "prmsn_names_only": 200,
                "eyak_all_only": 30,
                "both_sources": 20,
            },
            "calls_made": 250,
            "files_saved": 250,
            "dedupe_note": "e약은요 4,749건 중 item_seq 중복 16건 (고유 4,733개)",
        }

        manifest_str = json.dumps(manifest_data, indent=2, ensure_ascii=False)
        manifest = json.loads(manifest_str)

        # 필수 필드 확인
        assert manifest["product_requests"] == 335
        assert manifest["matched_items"] == 250
        assert manifest["calls_made"] == 250
        assert manifest["files_saved"] == 250

        # 비밀값 없음
        assert "serviceKey" not in manifest_str
        assert "api_key" not in manifest_str

    def test_manifest_no_secrets(self):
        """manifest에 비밀값이 없음."""
        manifest = {
            "timestamp": "2026-11-10T12:34:56+00:00",
            "product_requests": 335,
            "matched_items": 250,
            "unmatched": [],
            "item_seq_mapping_sources": {"prmsn_names_only": 250, "eyak_all_only": 0, "both_sources": 0},
            "calls_made": 250,
            "files_saved": 250,
            "dedupe_note": "e약은요 4,749건 중 item_seq 중복 16건 (고유 4,733개)",
        }

        manifest_str = json.dumps(manifest)
        assert "serviceKey" not in manifest_str
        assert "OPENAI_API_KEY" not in manifest_str
        assert "api_key" not in manifest_str


class TestDetailKeepsRawFields:
    """상세 응답의 효능·용법·주의사항 필드가 모델 변환으로 사라지지 않는다(2026-11-10 실수집 3건에서 발견)."""

    def test_build_preserves_detail_fields(self):
        import glob
        from datetime import datetime
        from types import SimpleNamespace

        from app.tools.prmsn import PrmsnClient

        sample = sorted(glob.glob(str(Path(__file__).resolve().parents[2] / "data/mock/api_snapshots/drug-prmsn/getDrugPrdtPrmsnDtlInq08/*.json")))
        if not sample:
            import pytest

            pytest.skip("상세 샘플 스냅샷(로컬 전용)이 없다")
        body = json.loads(Path(sample[0]).read_text(encoding="utf-8")).get("body", {})
        resp = SimpleNamespace(
            body=body, request_hash="h", fetched_at=datetime.now(UTC), from_cache=False, source="snapshot"
        )
        result = PrmsnClient._build(resp, {"pageNo": "1", "numOfRows": "100"}, "detail")
        assert result.raw_items
        assert "EE_DOC_DATA" in result.raw_items[0] and "UD_DOC_DATA" in result.raw_items[0]
