"""오탈자·축약·표기 변형을 코드로 만든다(결정적, LLM 없음). RFP-28-02: 오탈자 / 축약 / 표기를 구분해 `variant` 라벨을 붙인다."""
import hashlib, random, re

FORM = r"(서방정|서방캡슐|연질캡슐|캡슐|필름코팅정|장용정|정|주사|주|시럽|액|크림|겔|패치)$"
UNIT = {"밀리그램": "mg", "마이크로그램": "mcg", "그램": "g", "밀리리터": "mL"}


def _digit_cut(name):
    m = re.search(r"\d", name)
    return name[: m.start()] if m else name


def typo(name):
    """진짜 오탈자: 첫 어근 안의 글자 순서 바꿈·모음 혼동·초성 혼동. 끝 글자를 자르는 변형은 만들지 않는다(축약과 구분)."""
    core = _digit_cut(name)
    syl = [i for i, ch in enumerate(core[:-1]) if "가" <= ch <= "힣"]  # 마지막 글자 제외
    if len(syl) < 2:
        return name
    r = random.Random(name)
    s = list(name)
    kind = r.choice(["swap", "vowel", "vowel"])
    i = r.choice(syl)
    if kind == "swap" and i + 1 in syl:
        s[i], s[i + 1] = s[i + 1], s[i]
    else:
        code = ord(s[i]) - 0xAC00
        cho, jung, jong = code // 588, (code % 588) // 28, code % 28
        mp = {1: 5, 5: 1, 0: 4, 4: 0, 8: 13, 13: 8, 20: 19, 19: 20}  # ㅐ↔ㅔ, ㅏ↔ㅓ, ㅗ↔ㅜ, ㅣ↔ㅢ 계열
        s[i] = chr(0xAC00 + (cho * 21 + mp.get(jung, jung)) * 28 + jong)
    out = "".join(s)
    return out if out != name else name


def abbreviate(name):
    """축약: 용량·단위를 빼거나(엠슈타인정), 제형 접미까지 뺀다(엠슈타인). 글자는 그대로이고 뒤쪽만 생략한다."""
    core = _digit_cut(name).rstrip("_ ")
    r = random.Random("abbr" + name)
    short = re.sub(FORM, "", core)
    cands = [c for c in (core, short) if c and c != name and len(c) >= 2]
    return r.choice(cands) if cands else name


def notation(name):
    """표기 변형: 단위를 mg로, 숫자 앞뒤에 공백을 둔다."""
    out = name
    for k, v in UNIT.items():
        out = out.replace(k, v)
    out = re.sub(r"(\D)(\d)", r"\1 \2", out, count=1)
    return out if out != name else name


def assign(n_key, quota=(14, 3, 3)):
    """결정적 배분: 키 해시로 오탈자:축약:표기 = 14:3:3 비율에 가깝게 나눈다."""
    h = int(hashlib.sha1(n_key.encode()).hexdigest(), 16) % 20
    return "오탈자" if h < quota[0] else ("축약" if h < quota[0] + quota[1] else "표기")


def make(name, key):
    v = assign(key)
    fn = {"오탈자": typo, "축약": abbreviate, "표기": notation}[v]
    out = fn(name)
    if out == name:  # 변형이 안 되면 다른 종류로
        for v2, fn2 in (("축약", abbreviate), ("표기", notation), ("오탈자", typo)):
            out = fn2(name)
            if out != name:
                v = v2
                break
    return v, out
