// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { classifyCallbackError, parseAuthError } from "@/lib/supabase/callback";
import { GET } from "./route";

// 로그인 콜백 라우트를 가짜 Supabase 서버 클라이언트로 본다(실제 Supabase 호출 0). 값은 모두 합성이다.
const exchangeCodeForSession = vi.fn();
let configured = true;
vi.mock("@/lib/supabase/server", () => ({
  createRouteSupabase: async () => (configured ? { auth: { exchangeCodeForSession } } : null),
}));

const ORIGIN = "http://localhost:3000";
const call = async (query: string) => {
  const response = await GET(new NextRequest(`${ORIGIN}/auth/callback${query}`));
  return { status: response.status, location: response.headers.get("location") };
};

beforeEach(() => {
  configured = true;
  exchangeCodeForSession.mockReset();
  exchangeCodeForSession.mockResolvedValue({ data: {}, error: null });
});

describe("GET /auth/callback", () => {
  it("code가 있으면 세션으로 바꾸고 첫 화면으로 돌려보낸다(주소에 코드를 남기지 않는다)", async () => {
    const { status, location } = await call("?code=synthetic-code");
    expect(exchangeCodeForSession).toHaveBeenCalledWith("synthetic-code");
    expect(status).toBe(307);
    expect(location).toBe(`${ORIGIN}/`);
  });

  it("이메일 없는 카카오계정(Supabase 오류)이면 교환하지 않고 email_required 표시만 넘긴다", async () => {
    const { location } = await call("?error=server_error&error_code=unexpected_failure&error_description=Error+getting+user+email+from+external+provider");
    expect(location).toBe(`${ORIGIN}/?auth_error=email_required`);
    expect(exchangeCodeForSession).not.toHaveBeenCalled();
  });

  it("그 밖의 공급자 오류(동의 취소 등)는 failed다. 오류 문구는 주소에 싣지 않는다", async () => {
    const { location } = await call("?error=access_denied&error_description=synthetic+user+denied");
    expect(location).toBe(`${ORIGIN}/?auth_error=failed`);
  });

  it("코드 교환이 실패하거나 던지면 failed다", async () => {
    exchangeCodeForSession.mockResolvedValue({ data: {}, error: { code: "flow_state_not_found", message: "synthetic" } });
    expect((await call("?code=synthetic-code")).location).toBe(`${ORIGIN}/?auth_error=failed`);
    exchangeCodeForSession.mockRejectedValue(new TypeError("fetch failed"));
    expect((await call("?code=synthetic-code")).location).toBe(`${ORIGIN}/?auth_error=failed`);
  });

  it("Supabase 설정이 없으면 코드가 와도 failed다. 아무것도 없으면 그냥 첫 화면이다", async () => {
    configured = false;
    expect((await call("?code=synthetic-code")).location).toBe(`${ORIGIN}/?auth_error=failed`);
    expect((await call("")).location).toBe(`${ORIGIN}/`);
  });

  it("주소로 받은 값으로 이동 대상을 바꾸지 못한다(늘 같은 출처의 첫 화면)", async () => {
    const { location } = await call("?code=synthetic-code&next=https://example.com/&redirect_to=//example.com");
    expect(location).toBe(`${ORIGIN}/`);
  });
});

describe("콜백 오류 분류", () => {
  it.each([
    [null, "Error getting user email from external provider", "email_required"],
    ["unexpected_failure", "Error getting user email from external provider", "email_required"],
    ["email_address_not_provided", null, "email_required"],
    [null, "Email is required", "email_required"],
    ["access_denied", "User denied access", "failed"],
    ["provider_email_needs_verification", "Unverified email with kakao", "failed"],
    [null, null, "failed"],
  ] as const)("%s / %s → %s", (code, description, expected) => {
    expect(classifyCallbackError(code, description)).toBe(expected);
  });

  it("주소의 auth_error는 아는 값만 받는다", () => {
    expect(parseAuthError("email_required")).toBe("email_required");
    expect(parseAuthError("failed")).toBe("failed");
    for (const value of [null, "", "<script>", "EMAIL_REQUIRED"]) expect(parseAuthError(value)).toBeNull();
  });
});
