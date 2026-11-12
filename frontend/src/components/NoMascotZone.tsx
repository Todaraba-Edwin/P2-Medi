"use client";

import { createContext, useContext } from "react";

const NoMascotContext = createContext(false);

/** 응급·금기 결과·고정 문구 영역을 감싼다. 안에서는 마스코트가 그려지지 않는다. */
export function NoMascotZone({ children }: { children: React.ReactNode }) {
  return <NoMascotContext.Provider value={true}>{children}</NoMascotContext.Provider>;
}

export function useInNoMascotZone() {
  return useContext(NoMascotContext);
}
