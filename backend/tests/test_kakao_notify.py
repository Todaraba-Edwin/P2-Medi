"""운영자 카카오톡 알림 시험(DevOps 2026-11-24). 실제 HTTP·카카오 호출 0(가짜 전송 함수), `.env` 미사용."""

from __future__ import annotations

import json
import logging
import subprocess
import urllib.parse

import pytest

from app.api import kakao_notify, service
from app.api.kakao_notify import MEMO_URL, TOKEN_ENDPOINT, KakaoNotifier
from app.config import Settings

KEY, REFRESH, SECRET, ACCESS, NEW_REFRESH = "KEYVAL-1", "REFRESHVAL-2", "SECRETVAL-3", "ACCESSVAL-4", "NEWREFVAL-5"
TOKENS = (KEY, REFRESH, SECRET, ACCESS, NEW_REFRESH)


class FakeHttp:
    def __init__(self, *, token_body=None, memo_status=200, raises: Exception | None = None):
        self.calls: list[tuple[str, dict, dict]] = []
        self.token_body = token_body if token_body is not None else {"access_token": ACCESS}
        self.memo_status = memo_status
        self.raises = raises

    def __call__(self, url, headers, form):
        self.calls.append((url, headers, form))
        if self.raises:
            raise self.raises
        if url == TOKEN_ENDPOINT:
            return 200, self.token_body
        return self.memo_status, {"result_code": 0}


def _settings(**kw) -> Settings:
    base = {"kakao_rest_api_key": KEY, "kakao_refresh_token": REFRESH, "_env_file": None}
    base.update(kw)
    return Settings(**base)


def _notifier(http, **kw) -> KakaoNotifier:
    n = KakaoNotifier.from_settings(_settings(**kw), send=http, token_file=None)
    assert n is not None
    return n


@pytest.fixture(autouse=True)
def _isolate_kakao(monkeypatch, tmp_path):
    """실제 키·토큰 파일이 시험에 섞이지 않게 한다(사용자 환경에 실제 값이 있어도 통과해야 함)."""
    for name in ("KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET", "KAKAO_REFRESH_TOKEN", "MEDIAGENT_NOTIFY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kakao_notify, "TOKEN_FILE", tmp_path / "kakao_refresh_token.local")
    # 브랜치 캐시는 시험 간 초기화하고, 실제 git 대신 고정 브랜치를 쓴다(브랜치 시험은 `_fake_git`으로 따로 바꾼다)
    monkeypatch.setattr(kakao_notify, "_branch_cache", None)
    monkeypatch.setattr(kakao_notify, "_git", _fake_git({("rev-parse", "--abbrev-ref", "HEAD"): "develop"}))


def _fake_git(answers: dict, calls: list | None = None):
    def fake(*args):
        if calls is not None:
            calls.append(args)
        value = answers[args]
        if isinstance(value, Exception):
            raise value
        return value

    return fake


def _fake_factory(_settings):
    class _Deps:  # noqa: D401
        pass

    # 준비 단계 훅을 직접 태운다
    with service.build_step("warmup", "corpus (fetch + bm25 index)") as step:
        step.detail = "123 chunks"
    return _Deps()


def _join(n: KakaoNotifier) -> None:
    for t in n.threads:
        t.join(5)


def test_two_messages_on_success():
    http = FakeHttp()
    n = _notifier(http)
    runner = service.LazyGraphRunner(_settings(), _fake_factory, notifier=n)
    assert runner.warm() is True
    _join(n)
    memos = [json.loads(f["template_object"])["text"] for u, _h, f in http.calls if u == MEMO_URL]
    assert len(memos) == 2
    assert memos[0].startswith("[MediAgent-Can-I-PPiyak] [develop] corpus 완료 ") and memos[0].endswith("s (123 chunks)")
    assert memos[1].startswith("[MediAgent-Can-I-PPiyak] [develop] warmup 완료 ") and memos[1].endswith("s")
    token_calls = [f for u, _h, f in http.calls if u == TOKEN_ENDPOINT]
    assert token_calls[0]["grant_type"] == "refresh_token" and token_calls[0]["client_id"] == KEY
    assert "client_secret" not in token_calls[0]
    assert all(h.get("Authorization") == f"Bearer {ACCESS}" for u, h, _f in http.calls if u == MEMO_URL)


def test_client_secret_sent_when_set():
    http = FakeHttp()
    n = _notifier(http, kakao_client_secret=SECRET)
    n.notify("x")
    _join(n)
    assert http.calls[0][2]["client_secret"] == SECRET


def test_failure_sends_failure_message_with_type_name_only():
    http = FakeHttp()
    n = _notifier(http)

    def boom(_s):
        raise ValueError("민감한 사용자 질문 포함 메시지")

    runner = service.LazyGraphRunner(_settings(), boom, notifier=n)
    assert runner.warm() is False
    _join(n)
    texts = [json.loads(f["template_object"])["text"] for u, _h, f in http.calls if u == MEMO_URL]
    assert len(texts) == 1 and texts[0].startswith("[MediAgent-Can-I-PPiyak] [develop] warmup 실패 ValueError ")
    assert "민감" not in texts[0]


def test_no_keys_means_no_notifier_and_zero_calls(monkeypatch):
    s = Settings(_env_file=None)
    assert KakaoNotifier.from_settings(s) is None
    http = FakeHttp()
    monkeypatch.setattr(kakao_notify, "_post_form", http)
    runner = service.LazyGraphRunner(s, _fake_factory)
    assert runner.warm() is True
    assert http.calls == []


@pytest.mark.parametrize("off", ["0", "false", "off"])
def test_notify_switch_off_zero_calls(monkeypatch, off):
    monkeypatch.setenv("MEDIAGENT_NOTIFY", off)
    s = _settings()
    assert s.mediagent_notify is False
    assert KakaoNotifier.from_settings(s, send=FakeHttp()) is None


def test_send_exception_does_not_break_warmup_and_logs_type_only(caplog):
    http = FakeHttp(raises=TimeoutError(f"timed out {ACCESS} {REFRESH}"))
    n = _notifier(http)
    runner = service.LazyGraphRunner(_settings(), _fake_factory, notifier=n)
    with caplog.at_level(logging.WARNING):
        assert runner.warm() is True
        _join(n)
    text = caplog.text
    assert "kakao notify failed: TimeoutError" in text
    assert not any(t in text for t in TOKENS)


def test_rejected_http_status_swallowed():
    http = FakeHttp(memo_status=403)
    n = _notifier(http)
    n.notify("x")
    _join(n)  # 예외 없이 끝난다


def test_new_refresh_token_saved_locally_and_not_logged(tmp_path, caplog):
    f = tmp_path / "tok.local"
    http = FakeHttp(token_body={"access_token": ACCESS, "refresh_token": NEW_REFRESH})
    n = KakaoNotifier.from_settings(_settings(), send=http, token_file=f)
    with caplog.at_level(logging.DEBUG):
        n.notify("x")
        _join(n)
    assert f.read_text() == NEW_REFRESH
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert not any(t in caplog.text for t in TOKENS)
    # 다음 시작은 저장된 토큰을 쓴다
    n2 = KakaoNotifier.from_settings(_settings(), send=http, token_file=f)
    n2.notify("y")
    _join(n2)
    assert http.calls[-2][2]["refresh_token"] == NEW_REFRESH


def test_settings_repr_hides_values():
    s = _settings(kakao_client_secret=SECRET)
    assert not any(t in repr(s) for t in TOKENS) and not any(t in str(s.model_dump()) for t in TOKENS)


def test_default_transport_encodes_form(monkeypatch):
    seen = {}

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"result_code": 0}'

    def fake_urlopen(req, timeout):
        seen["timeout"], seen["body"], seen["url"] = timeout, req.data.decode(), req.full_url
        return R()

    monkeypatch.setattr(kakao_notify.urllib.request, "urlopen", fake_urlopen)
    status, body = kakao_notify._post_form(MEMO_URL, {"Authorization": "Bearer t"}, {"template_object": "{}"})
    assert (status, body["result_code"], seen["timeout"]) == (200, 0, 3.0)
    assert urllib.parse.parse_qs(seen["body"]) == {"template_object": ["{}"]}


def test_startup_notification_uses_shared_notifier_and_prefix():
    http = FakeHttp()
    n = _notifier(http)
    runner = service.LazyGraphRunner(_settings(), _fake_factory, notifier=n)
    thread = service.notify_startup(runner, _settings())
    assert thread is not None
    _join(n)
    memos = [json.loads(f["template_object"])["text"] for url, _h, f in http.calls if url == MEMO_URL]
    assert memos == ["[MediAgent-Can-I-PPiyak] [develop] 서버 시작 완료"]


def test_startup_notification_is_noop_without_keys_or_when_switched_off():
    assert service.notify_startup(None, _settings(kakao_rest_api_key=None)) is None
    assert service.notify_startup(None, _settings(mediagent_notify=False)) is None


def test_startup_notification_failure_never_raises():
    http = FakeHttp(raises=OSError("boom"))
    n = _notifier(http)
    runner = service.LazyGraphRunner(_settings(), _fake_factory, notifier=n)
    thread = service.notify_startup(runner, _settings())
    assert thread is not None
    _join(n)  # 예외가 스레드 밖으로 나오지 않는다


def test_make_service_runner_shares_one_notifier(monkeypatch):
    monkeypatch.setattr(service, "missing_settings", lambda _s: [])
    runner = service.make_service_runner(_settings())
    assert runner is not None and getattr(runner, "_notifier", None) is not None


# --------------------------------------------------------------------------- 브랜치 표시(2026-11-24)
HEAD_ARGS = ("rev-parse", "--abbrev-ref", "HEAD")
SHORT_ARGS = ("rev-parse", "--short=7", "HEAD")


@pytest.mark.parametrize(
    ("answers", "expected"),
    [
        ({HEAD_ARGS: "develop"}, "develop"),
        ({HEAD_ARGS: "feature/x"}, "feature/x"),
        ({HEAD_ARGS: "HEAD", SHORT_ARGS: "abc1234"}, "detached@abc1234"),
        ({HEAD_ARGS: "HEAD", SHORT_ARGS: "abc1234def5678"}, "detached@abc1234"),
        ({HEAD_ARGS: FileNotFoundError("git")}, "unknown"),
        ({HEAD_ARGS: subprocess.CalledProcessError(128, "git")}, "unknown"),
        ({HEAD_ARGS: subprocess.TimeoutExpired("git", 2)}, "unknown"),
        ({HEAD_ARGS: "HEAD", SHORT_ARGS: subprocess.CalledProcessError(128, "git")}, "unknown"),
        ({HEAD_ARGS: ""}, "unknown"),
    ],
)
def test_branch_label_cases(monkeypatch, answers, expected):
    monkeypatch.setattr(kakao_notify, "_git", _fake_git(answers))
    assert kakao_notify.branch_label() == expected


def test_branch_label_long_name_is_shortened_from_the_front(monkeypatch):
    name = "feature/" + "x" * 60 + "-tail"
    monkeypatch.setattr(kakao_notify, "_git", _fake_git({HEAD_ARGS: name}))
    label = kakao_notify.branch_label()
    assert len(label) == kakao_notify.MAX_BRANCH_CHARS == 40
    assert label.startswith("…") and label.endswith("-tail") and name.endswith(label[1:])
    assert len(kakao_notify.compose_message("서버 시작 완료")) <= 200


def test_branch_label_is_cached_per_process(monkeypatch):
    calls: list = []
    monkeypatch.setattr(kakao_notify, "_git", _fake_git({HEAD_ARGS: "develop"}, calls))
    assert kakao_notify.branch_label() == "develop"
    assert kakao_notify.branch_label() == "develop"
    assert calls == [HEAD_ARGS]


def test_git_runs_without_shell_in_repo_root_with_timeout(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(cmd=cmd, **kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="develop\n", stderr="")

    monkeypatch.undo()  # 위 autouse의 `_git` 가짜를 풀고 실제 `_git`를 쓴다
    monkeypatch.setattr(kakao_notify.subprocess, "run", fake_run)
    assert kakao_notify._git(*HEAD_ARGS) == "develop"
    assert seen["cmd"] == ["git", *HEAD_ARGS] and seen["timeout"] == 2.0
    assert seen["cwd"] == kakao_notify.REPO_ROOT and not seen.get("shell")


def test_all_four_messages_carry_branch(monkeypatch):
    monkeypatch.setattr(kakao_notify, "_git", _fake_git({HEAD_ARGS: "feature/x"}))
    http = FakeHttp()
    n = _notifier(http)
    ok = service.LazyGraphRunner(_settings(), _fake_factory, notifier=n)
    assert ok.warm() is True
    service.notify_startup(ok, _settings())

    def boom(_s):
        raise ValueError("x")

    assert service.LazyGraphRunner(_settings(), boom, notifier=n).warm() is False
    _join(n)
    memos = [json.loads(f["template_object"])["text"] for u, _h, f in http.calls if u == MEMO_URL]
    assert len(memos) == 4
    assert all(m.startswith("[MediAgent-Can-I-PPiyak] [feature/x] ") and len(m) <= 200 for m in memos)
    kinds = sorted(m.split("] ", 2)[2].split(" ")[0] + " " + m.split("] ", 2)[2].split(" ")[1] for m in memos)
    assert kinds == ["corpus 완료", "warmup 실패", "warmup 완료", "서버 시작"]


def test_message_has_no_path_or_user_info(monkeypatch):
    monkeypatch.setattr(kakao_notify, "_git", _fake_git({HEAD_ARGS: "develop"}))
    text = kakao_notify.compose_message("서버 시작 완료")
    assert text == "[MediAgent-Can-I-PPiyak] [develop] 서버 시작 완료"
    assert str(kakao_notify.REPO_ROOT) not in text and "/Users" not in text and "@" not in text
