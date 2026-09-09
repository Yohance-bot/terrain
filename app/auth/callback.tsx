import { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, Text, View } from "react-native";
import { router, useLocalSearchParams } from "expo-router";
import { completeGoogleSignIn } from "@/lib/auth/google";
export default function Callback() {
  const params = useLocalSearchParams<{
    code?: string;
    error?: string;
    error_description?: string;
  }>();
  const [error, setError] = useState("");
  useEffect(() => {
    const query = new URLSearchParams();
    if (params.code) query.set("code", params.code);
    if (params.error) query.set("error", params.error);
    if (params.error_description)
      query.set("error_description", params.error_description);
    void completeGoogleSignIn(`run://auth/callback?${query}`)
      .then(() => router.replace("/"))
      .catch((e) => setError(e.message));
  }, [params.code, params.error, params.error_description]); // One exchange per callback code.
  return (
    <View style={{ flex: 1, justifyContent: "center", padding: 32, gap: 20 }}>
      {error ? (
        <>
          <Text>{error}</Text>
          <Pressable onPress={() => router.replace("/sign-in")}>
            <Text>Return to sign in</Text>
          </Pressable>
        </>
      ) : (
        <>
          <ActivityIndicator />
          <Text>Finishing Google sign-in…</Text>
        </>
      )}
    </View>
  );
}
