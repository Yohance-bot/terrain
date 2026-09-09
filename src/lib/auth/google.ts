import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { Platform } from "react-native";
import { readAuth, writeAuth } from "./storage";
import { googleLogin } from "@/services/api/client";
const SUPABASE = "https://wqhwnfnesigiytyhikuj.supabase.co";
const PUBLIC_KEY = "sb_publishable_NEaAQwLQLCNXxYVyNtIKpg_sWZAg0xL";
let completing: Promise<void> | null = null;
export function completeGoogleSignIn(url: string): Promise<void> {
  if (completing) return completing;
  completing = (async () => {
    const params = new URL(url).searchParams;
    if (params.get("error"))
      throw new Error(
        params.get("error_description") || "Google sign-in was cancelled",
      );
    const code = params.get("code");
    const verifier = await readAuth("pkce");
    if (!code || !verifier)
      throw new Error("This sign-in has expired. Start Google sign-in again.");
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(
        `${SUPABASE}/auth/v1/token?grant_type=pkce`,
        {
          method: "POST",
          signal: controller.signal,
          headers: { apikey: PUBLIC_KEY, "Content-Type": "application/json" },
          body: JSON.stringify({ auth_code: code, code_verifier: verifier }),
        },
      );
      const result = await response.json();
      if (!response.ok || !result.access_token)
        throw new Error(
          "Google sign-in could not be completed. Please start again.",
        );
      await googleLogin(result.access_token);
      await writeAuth("pkce", "");
    } finally {
      clearTimeout(timeout);
    }
  })().finally(() => {
    completing = null;
  });
  return completing;
}
export async function startGoogleSignIn(): Promise<boolean> {
  const verifier =
    Crypto.randomUUID().replaceAll("-", "") +
    Crypto.randomUUID().replaceAll("-", "");
  await writeAuth("pkce", verifier);
  const challenge = (
    await Crypto.digestStringAsync(
      Crypto.CryptoDigestAlgorithm.SHA256,
      verifier,
      { encoding: Crypto.CryptoEncoding.BASE64 },
    )
  )
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replaceAll("=", "");
  const redirect =
    Platform.OS === "web"
      ? `${window.location.origin}/auth/callback`
      : "run://auth/callback";
  const query = new URLSearchParams({
    provider: "google",
    redirect_to: redirect,
    code_challenge: challenge,
    code_challenge_method: "s256",
  });
  const url = `${SUPABASE}/auth/v1/authorize?${query}`;
  if (Platform.OS === "web") {
    window.location.assign(url);
    return false;
  }
  const result = await WebBrowser.openAuthSessionAsync(url, redirect);
  if (result.type !== "success") return false;
  await completeGoogleSignIn(result.url);
  return true;
}
