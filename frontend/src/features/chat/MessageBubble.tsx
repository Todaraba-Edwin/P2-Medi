import { cn } from "@/lib/utils";

/** 말풍선. `me`는 내 질문, `bot`은 답 쪽이다. 글자는 받은 그대로 그린다. */
export function MessageBubble({ side, children }: { side: "me" | "bot"; children: React.ReactNode }) {
  return (
    <p
      data-side={side}
      className={cn(
        "m-0 max-w-[94%] px-3.5 py-2 text-base leading-6 break-words whitespace-pre-wrap",
        side === "me"
          ? "max-w-[80%] self-end rounded-[20px_20px_6px_20px] bg-bubble-me"
          : "self-start rounded-[20px_20px_20px_6px] bg-tint",
      )}
    >
      {children}
    </p>
  );
}
