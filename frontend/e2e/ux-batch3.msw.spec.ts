import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Locator, Page, Request } from "@playwright/test";
import { HEIGHT, expectNoHorizontalScroll, expectTouchTarget, input, notice, openApp, pickTarget } from "./helpers";

// FE-17 UI/UX 다듬기 3차(U-08·U-09)를 목(MSW) 워커로 끝까지 본다. 393·1280 × 라이트·다크.
// - U-08: 시작 화면 병아리 이미지 아래 기본 대상 안내(지금 대상 + `게스트로 이용`), 고르면 `PUT /me/default-target`, 새 세션은 저장값으로 시작
// - U-09: 비로그인 입력창도 로그인과 같은 배치(질문 칸 첫 줄 전체, 아래 줄 왼쪽 [사진] (일반인|임산부), 오른쪽 끝 보내기), 토글 값은 요청에만 실리고 저장하지 않는다
// 캡처: `FE_UX_BATCH3_SHOT_DIR`을 주면 `ux-batch3-{width}-{scheme}.png`(시작 화면 기본 대상 안내)와 `ux-batch3-{width}-{scheme}-{장면}.png`를 남긴다
const SHOT_DIR = process.env.FE_UX_BATCH3_SHOT_DIR;
const shot = async (page: Page, name: string) => {
  if (!SHOT_DIR) return;
  await page.waitForFunction(() => [...document.images].filter((image) => image.getBoundingClientRect().width > 0).every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
  await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`) });
};
const box = async (locator: Locator) => (await locator.boundingBox())!;
const isDefaultTargetPut = (request: Request) => request.method() === "PUT" && new URL(request.url()).pathname.endsWith("/api/me/default-target");

for (const width of [393, 1280]) {
  for (const scheme of ["light", "dark"] as const) {
    test.describe(`FE-17 UX 묶음 3 · ${scheme} · ${width}px`, () => {
      test.use({ viewport: { width, height: HEIGHT }, colorScheme: scheme });
      const base = `ux-batch3-${width}-${scheme}`;

      test("U-08 시작 화면 기본 대상 안내: 병아리 아래 지금 대상, `게스트로 이용`을 고르면 저장되고 새 세션의 기본값이 된다", async ({ page }) => {
        test.setTimeout(90_000);
        const puts: unknown[] = [];
        page.on("request", (request) => {
          if (isDefaultTargetPut(request)) puts.push(request.postDataJSON());
        });
        await openApp(page, "?mock_session=onboarded&ux_batch3=1");
        const notice = page.getByTestId("start-target");
        await expect(notice).toBeVisible();
        await expect(notice.getByTestId("start-target-heading")).toHaveText("나 프로필로 확인해요");
        await expect(notice.getByTestId("start-target-lead")).toHaveText("이 프로필의 연령대·임신 여부가 답변에 쓰여요."); // FE-17 U-23: 세 번째 문장은 링크가 든 `start-target-switch`
        await expect(notice.getByTestId("start-target-switch")).toHaveText("프로필 없이 질문을 이어가시려면 게스트로 이용으로 프로필을 변경해주세요.");
        await expect(notice.getByTestId("profile-avatar")).toHaveCount(0); // FE-17 U-11: 아바타 없는 한 단락 문장
        // 시작 화면 병아리 이미지(HomeHero) 아래, 입력창 위에 있다
        const heroBox = await box(page.getByTestId("home").locator("img").first());
        // 시작 화면이 길어져도 병아리 위쪽이 잘리지 않는다(넘치면 위에서부터 스크롤)
        expect(heroBox.y).toBeGreaterThanOrEqual((await box(page.getByTestId("home"))).y - 0.5);
        const noticeBox = await box(notice);
        expect(noticeBox.y).toBeGreaterThanOrEqual(heroBox.y + heroBox.height - 0.5);
        expect(noticeBox.y + noticeBox.height).toBeLessThanOrEqual((await box(input(page))).y);
        const guestButton = notice.getByRole("button", { name: "게스트로 이용" });
        // FE-17 U-11: 문장 안 링크 모양이라 보이는 높이는 줄 높이다. 누르는 영역(투명 확장 포함) 44px은 ux-batch4가 가운데 ±21px 누름으로 확인한다
        await expect(guestButton).toBeVisible();
        await expect(notice).not.toContainText("안전");
        await expectNoHorizontalScroll(page);
        await shot(page, base);

        // 키보드로 `게스트로 이용`을 고른다: 대상이 바뀌고, 초점은 질문 칸, 서버 기본 대상은 "guest"
        const saved = page.waitForRequest(isDefaultTargetPut);
        await guestButton.focus();
        await page.keyboard.press("Enter");
        await saved;
        await expect(notice.getByTestId("start-target-heading")).toHaveText("게스트로 이용 중이에요");
        // FE-17 U-22: 게스트 상태 안내에는 `변경` 링크 하나만 있다(U-08의 "버튼 없음"을 대체)
        await expect(notice.getByRole("button")).toHaveText(["변경"]);
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 게스트로 이용");
        await expect(input(page)).toBeFocused();
        expect(puts).toEqual([{ target: "guest" }]);
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-guest-use`);

        // 칩에서 고른 것도 저장된다(값은 프로필 id뿐)
        const savedChild = page.waitForRequest(isDefaultTargetPut);
        await pickTarget(page, "첫째");
        await savedChild;
        await expect(notice.getByTestId("start-target-heading")).toHaveText("첫째 프로필로 확인해요");
        expect(puts).toHaveLength(2);
        expect(JSON.stringify(puts[1])).toMatch(/^\{"target":"[0-9a-f-]{36}"\}$/);

        // 안내를 무시하고 질문하면 고른 대상 그대로 가고, 대화가 시작되면 안내는 없다
        const chat = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat"));
        await input(page).fill("가나다정 먹어도 돼요");
        await page.getByRole("button", { name: "보내기" }).click();
        const body = (await chat).postDataJSON() as { context: { age: unknown } };
        expect(body.context.age).toMatchObject({ lower: 6, upper: 11 });
        await expect(page.getByTestId("start-target")).toHaveCount(0);

        // 새 세션(새로고침·로그인 복귀): 저장값이 기본값이다
        await openApp(page, "?mock_session=onboarded&mock_default_target=guest&ux_batch3=1");
        await expect(page.getByTestId("start-target")).toHaveAttribute("data-target", "guest");
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 게스트로 이용");
        await openApp(page, "?mock_session=onboarded&mock_default_target=child&ux_batch3=1");
        await expect(page.getByTestId("start-target-heading")).toHaveText("첫째 프로필로 확인해요");
        await expect(page.getByTestId("target-chip")).toHaveAccessibleName("누가 먹나요 첫째");
        await openApp(page, "?mock_session=onboarded&ux_batch3=1");
        await expect(page.getByTestId("start-target-heading")).toHaveText("나 프로필로 확인해요"); // 미설정이면 본인
        // 새 세션을 여는 것만으로는 저장하지 않는다(고를 때만)
        expect(puts).toHaveLength(2);
      });

      test("U-09 비로그인 입력창: 질문 칸 첫 줄 전체, 아래 줄 왼쪽 [사진] (일반인|임산부), 오른쪽 끝 보내기. 안내 없음, 토글 값은 요청에만", async ({ page }) => {
        test.setTimeout(90_000);
        const writes: string[] = [];
        page.on("request", (request) => {
          if (["PUT", "PATCH"].includes(request.method())) writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
        });
        await openApp(page);
        await expect(page.getByTestId("entry-choice")).toBeVisible();
        await expect(page.getByTestId("start-target")).toHaveCount(0); // 비로그인에는 기본 대상 안내가 없다
        await expect(page.getByTestId("target-chip")).toHaveCount(0);
        const row = page.getByTestId("input-target-row");
        const form = input(page).locator("xpath=ancestor::form");
        const check = async () => {
          const [textBox, rowBox, photoBox, toggleBox, sendBox, formBox] = await Promise.all([
            box(input(page)),
            box(row),
            box(row.getByTestId("photo-entry")),
            box(row.getByTestId("pregnancy-toggle")),
            box(page.getByRole("button", { name: "보내기" })),
            box(form),
          ]);
          expect(textBox.width).toBeGreaterThan(formBox.width - 40); // 질문 칸이 첫 줄 전체
          expect(rowBox.y).toBeGreaterThanOrEqual(textBox.y + textBox.height - 0.5); // 묶음은 질문 칸 아래
          expect(photoBox.x).toBeLessThan(toggleBox.x); // 사진 → 토글
          expect(photoBox.x - formBox.x).toBeLessThanOrEqual(16); // 왼쪽 끝
          expect(Math.abs(photoBox.y + photoBox.height - (formBox.y + formBox.height))).toBeLessThanOrEqual(8); // 아래 끝
          expect(sendBox.x).toBeGreaterThan(toggleBox.x + toggleBox.width - 0.5);
          expect(formBox.x + formBox.width - (sendBox.x + sendBox.width)).toBeLessThanOrEqual(8); // 보내기는 오른쪽 끝
          expect(Math.abs(sendBox.y - photoBox.y)).toBeLessThanOrEqual(2); // 같은 줄
          expect((await box(notice(page))).y).toBeGreaterThanOrEqual(formBox.y + formBox.height - 0.5); // 통합 고지는 입력창 바로 아래 그대로
        };
        await check();
        await expect(page.getByTestId("photo-entry")).toHaveCount(1);
        await expectTouchTarget(row.getByTestId("photo-entry"));
        await expectNoHorizontalScroll(page);
        await shot(page, `${base}-guest-input`);
        // 여러 줄 입력에도 묶음은 아래에 남는다
        await input(page).fill("첫 줄\n둘째 줄\n셋째 줄");
        await check();
        await input(page).fill("");
        // 모바일 키보드가 올라온 것처럼 화면 높이를 줄여도 질문 칸·묶음·보내기가 화면 안에 있다(실기기 키보드는 확인하지 못함)
        if (width < 1024) {
          await page.setViewportSize({ width, height: 420 });
          await input(page).focus();
          for (const target of [input(page), row.getByTestId("photo-entry"), page.getByRole("button", { name: "보내기" })]) {
            const b = await box(target);
            expect(b.y).toBeGreaterThanOrEqual(0);
            expect(b.y + b.height).toBeLessThanOrEqual(420 + 0.5);
          }
          await expectNoHorizontalScroll(page);
          await page.setViewportSize({ width, height: HEIGHT });
        }
        // 토글 값은 이번 요청에만 실린다(저장 요청 없음)
        await row.getByRole("radio", { name: "임산부" }).click();
        const chat = page.waitForRequest((request) => request.method() === "POST" && new URL(request.url()).pathname.endsWith("/api/chat"));
        await input(page).fill("가나다정 먹어도 돼요");
        await page.keyboard.press("Enter");
        const body = (await chat).postDataJSON() as { context: { pregnant: boolean; age: unknown } };
        expect(body.context).toMatchObject({ pregnant: true, age: null });
        expect(writes).toEqual([]);
      });
    });
  }
}
