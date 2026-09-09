import { Platform } from "react-native";
import { getMeta, setMeta } from "@/lib/db";
export const readAuth = (key: string): Promise<string | null> =>
  Platform.OS === "web"
    ? Promise.resolve(localStorage.getItem(`terrarun.${key}`))
    : getMeta(`auth.${key}`);
export const writeAuth = (key: string, value: string): Promise<void> =>
  Platform.OS === "web"
    ? Promise.resolve(localStorage.setItem(`terrarun.${key}`, value))
    : setMeta(`auth.${key}`, value);
