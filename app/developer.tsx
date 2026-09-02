import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { developerLogin } from '@/services/api/client';
import { DEV_RUNNERS, setDevRunnerId } from '@/lib/device';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

export default function DeveloperScreen() {
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);
  const enter = async () => { setBusy(true); try { const account = await developerLogin(pin); const runner = DEV_RUNNERS[(account.developer_slot ?? 1) - 1]; if (runner) setDevRunnerId(runner.id); router.replace('/'); } catch { Alert.alert('Could not enable developer mode', 'Use one of the three local developer PINs.'); } finally { setBusy(false); } };
  return <SafeAreaView style={styles.screen} edges={['top']}><Pressable onPress={()=>router.back()}><Text style={styles.back}>‹ Profile</Text></Pressable><View style={styles.content}><Text style={styles.eyebrow}>DEBUG BUILD ONLY</Text><Text style={styles.title}>Developer mode</Text><Text style={styles.copy}>Three separate developer runners can use the virtual joystick to simulate territory takeovers. This can never be enabled in a production build.</Text><TextInput style={styles.input} secureTextEntry value={pin} onChangeText={setPin} placeholder="Developer PIN" /><Pressable onPress={()=>void enter()} disabled={busy} style={styles.button}><Text style={styles.buttonText}>{busy ? 'Signing in…' : 'Enable developer mode'}</Text></Pressable></View></SafeAreaView>;
}
const styles=StyleSheet.create({screen:{flex:1,backgroundColor:colors.background,padding:spacing.lg},back:{color:colors.primary,fontWeight:fontWeight.semibold},content:{flex:1,justifyContent:'center'},eyebrow:{fontSize:11,letterSpacing:1,color:'#B42318',fontWeight:fontWeight.bold},title:{color:colors.text,fontSize:28,fontWeight:fontWeight.bold,marginTop:spacing.sm},copy:{color:colors.textMuted,fontSize:fontSize.sm,lineHeight:21,marginTop:spacing.sm},input:{borderWidth:1,borderColor:colors.border,borderRadius:radius.md,padding:spacing.md,marginTop:spacing.xl,color:colors.text},button:{marginTop:spacing.sm,backgroundColor:colors.text,borderRadius:radius.md,padding:spacing.md,alignItems:'center'},buttonText:{color:colors.surface,fontWeight:fontWeight.bold}});
