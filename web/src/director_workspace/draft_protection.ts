import { createContext, useContext, useEffect, useId, useState } from "react";
export const DraftProtection = createContext<
  (id: string, dirty: boolean) => void
>(() => undefined);
export function useUnsavedChanges(dirty: boolean) {
  const register = useContext(DraftProtection);
  const id = useId();
  useEffect(() => {
    register(id, dirty);
    return () => register(id, false);
  }, [register, id, dirty]);
}
/** Input only: synchronize clean inputs; never relabel a dirty draft as a newer authority. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return "[" + value.map(stableStringify).join(",") + "]";
  }
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => JSON.stringify(key) + ":" + stableStringify(item));
    return "{" + entries.join(",") + "}";
  }
  return JSON.stringify(value);
}
export function useProtectedValue<T>(authority: T) {
  const live = stableStringify(authority);
  const [base, setBase] = useState(live);
  const [value, setValue] = useState<T>(() => structuredClone(authority));
  const serialized = stableStringify(value);
  const dirty = serialized !== live;
  const conflict = serialized !== base && base !== live && dirty;
  useEffect(() => {
    if (serialized === base || serialized === live) {
      setBase(live);
      if (serialized !== live) setValue(JSON.parse(live) as T);
    }
  }, [live, serialized, base]);
  useUnsavedChanges(dirty);
  const reset = () => {
    setBase(live);
    setValue(JSON.parse(live) as T);
  };
  return { value, setValue, dirty, conflict, reset };
}
