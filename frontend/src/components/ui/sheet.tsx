"use client";

import * as React from "react";
import { Dialog as SheetPrimitive } from "radix-ui";
import { XIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const Sheet = SheetPrimitive.Root;
const SheetTrigger = SheetPrimitive.Trigger;
const SheetClose = SheetPrimitive.Close;

function SheetContent({
  className,
  children,
  side = "right",
  ...props
}: React.ComponentProps<typeof SheetPrimitive.Content> & { side?: "left" | "right" | "bottom" }) {
  const sideClass = {
    right: "inset-y-0 right-0 h-full w-3/4 max-w-sm",
    left: "inset-y-0 left-0 h-full w-3/4 max-w-sm",
    bottom: "inset-x-0 bottom-0 max-h-[85dvh] w-full rounded-t-lg",
  }[side];
  return (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className="fixed inset-0 z-50 bg-ink/50" />
      <SheetPrimitive.Content className={cn("fixed z-50 bg-bg p-4 shadow-lg", sideClass, className)} {...props}>
        {children}
        {/* 누르는 영역 44px(FE-IMPL-06, 지시서 A7) */}
        <SheetPrimitive.Close className="absolute top-1.5 right-1.5 grid size-11 place-items-center rounded" aria-label="닫기">
          <XIcon className="size-4" aria-hidden="true" />
        </SheetPrimitive.Close>
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  );
}

function SheetTitle({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Title>) {
  return <SheetPrimitive.Title className={cn("text-lg font-bold", className)} {...props} />;
}

function SheetDescription({ className, ...props }: React.ComponentProps<typeof SheetPrimitive.Description>) {
  return <SheetPrimitive.Description className={cn("text-sm text-mute", className)} {...props} />;
}

export { Sheet, SheetTrigger, SheetClose, SheetContent, SheetTitle, SheetDescription };
