import { describe, expect, it } from "vitest";
import { AVATAR_COLORS, ProfileSchema } from "./account";

// 프로필 병아리 배경색(FE-17 U-01): 서버 계약(생성 타입)과 같은 8색. 칸이 없거나 모르는 값이면 기본색(노랑)으로 읽어 화면이 깨지지 않는다
const base = { profile_id: "p", relation: "child", label: "첫째", age_band: null, sex: null, pregnancy_status: null, sort_order: 1, medications: [] };

describe("ProfileSchema.avatar_color", () => {
  it("8색은 서버 순서 그대로다", () => {
    expect(AVATAR_COLORS).toEqual(["yellow", "coral", "pink", "purple", "blue", "teal", "green", "gray"]);
  });
  it("받은 색은 그대로, 칸이 없거나 모르는 값이면 노랑", () => {
    expect(ProfileSchema.parse({ ...base, avatar_color: "teal" }).avatar_color).toBe("teal");
    expect(ProfileSchema.parse(base).avatar_color).toBe("yellow");
    expect(ProfileSchema.parse({ ...base, avatar_color: "neon" }).avatar_color).toBe("yellow");
  });
  it("모르는 다른 칸은 여전히 거부한다(strict)", () => {
    expect(ProfileSchema.safeParse({ ...base, avatar_color: "teal", extra: 1 }).success).toBe(false);
  });
});
