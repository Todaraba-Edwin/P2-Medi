"use client";

import { useState } from "react";
import type { Ingredient } from "@/lib/api";
import { cn } from "@/lib/utils";
import { INGREDIENTS_LABEL, moreIngredientsLabel } from "./copy";

const COLLAPSE_FROM = 5; // 이 개수부터 접는다
const PLAIN_SHOWN = 3; // 원인·중복 성분이 하나도 없을 때 먼저 보이는 개수

// 원인 성분의 색: 걸린 금기 종류의 배지 색 계열을 따른다. 중복은 주의 색이다.
const CAUSE_CLASS: Record<string, string> = {
  pregnancy: "border-preg-ink/25 bg-preg-bg text-preg-ink",
  contra_pair: "border-red-ink/25 bg-combo-bg text-red-ink",
  age: "border-red-ink/25 bg-combo-bg text-red-ink",
};
const CAUSE_DEFAULT_CLASS = "border-warn-ink/25 bg-warn-bg text-warn-ink";
const DUP_CLASS = "border-warn-ink/25 bg-warn-bg text-warn-ink";

type ChipState = "cause" | "dup" | "none";
const stateOf = (ingredient: Ingredient): ChipState => (ingredient.contra_kinds.length > 0 ? "cause" : ingredient.dup ? "dup" : "none");

export interface IngredientChipProps {
  ingredient: Ingredient;
  /**
   * 상태 글자(`금기 원인`·`중복`·`병용금기 원인`)는 **응답 값**이어야 한다. 지금 계약(`chat_response@v1`)에는 글자 칸이 없어
   * 넘겨받지 못하면 그리지 않는다(프런트가 판정 글자를 짓지 않는다). 서버가 글자를 주면 이 자리에 받은 그대로 그린다.
   */
  stateLabel?: string | null;
}

/** 성분 칩 하나. 표시명은 받은 그대로다. 상태는 색과 `data-state`로 구분한다 */
export function IngredientChip({ ingredient, stateLabel }: IngredientChipProps) {
  const state = stateOf(ingredient);
  return (
    <span
      data-testid="ingredient-chip"
      data-state={state}
      data-kinds={ingredient.contra_kinds.join(" ") || undefined}
      className={cn(
        "inline-flex items-center rounded-lg border px-2 py-0.5 text-xs leading-[17px] font-medium whitespace-nowrap",
        state === "cause" && (CAUSE_CLASS[ingredient.contra_kinds[0]] ?? CAUSE_DEFAULT_CLASS),
        state === "dup" && DUP_CLASS,
        state === "none" && "border-line bg-bg text-ink-2",
      )}
    >
      {ingredient.name}
      {stateLabel ? <em className="font-bold not-italic">&nbsp;·&nbsp;{stateLabel}</em> : null}
    </span>
  );
}

/**
 * 성분 칩 줄. 4개까지는 받은 순서 그대로 모두 보인다.
 * 5개 이상이면 원인·중복 성분만(받은 순서로) 먼저 보이고 나머지는 `외 N개`를 누르면 받은 순서 그대로 모두 보인다.
 */
export function IngredientChips({ ingredients }: { ingredients: readonly Ingredient[] }) {
  const [expanded, setExpanded] = useState(false);
  if (ingredients.length === 0) return null;
  const collapsed = ingredients.length >= COLLAPSE_FROM && !expanded;
  const flagged = ingredients.filter((ingredient) => stateOf(ingredient) !== "none");
  const shown = collapsed ? (flagged.length > 0 ? flagged : ingredients.slice(0, PLAIN_SHOWN)) : ingredients;
  const hidden = ingredients.length - shown.length;
  return (
    <div data-testid="ingredient-chips" className="flex flex-wrap items-center gap-1">
      <span className="mr-0.5 text-[11px] font-bold text-mute">{INGREDIENTS_LABEL}</span>
      {shown.map((ingredient, index) => (
        <IngredientChip key={`${ingredient.code ?? ""}:${ingredient.name}:${index}`} ingredient={ingredient} />
      ))}
      {collapsed && hidden > 0 && (
        // 보이는 칩은 작지만 누르는 영역은 44px이다
        <button type="button" onClick={() => setExpanded(true)} className="-my-2.5 inline-flex min-h-11 min-w-11 items-center justify-center">
          <span className="inline-flex items-center rounded-lg border border-dashed border-line-2 px-2 py-0.5 text-xs leading-[17px] font-semibold whitespace-nowrap text-link">
            {moreIngredientsLabel(hidden)}
          </span>
        </button>
      )}
    </div>
  );
}
