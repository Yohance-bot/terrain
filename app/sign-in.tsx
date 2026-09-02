import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { createLocalAccount, developerLogin, fetchLocalAccounts, signInLocalAccount } from '@/services/api/client';
import { DEV_RUNNERS, setDevRunnerId } from '@/lib/device';
import type { AccountSummary } from '@/services/api/types';
import { colors, fontSize, fontWeight, radius, spacing } from '@/theme';

export default function SignInScreen() {
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [name, setName] = useState('');
  const [pin, setPin] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    void fetchLocalAccounts().then(setAccounts).catch(() => setAccounts([]));
  }, []);
  useFocusEffect(load);

  const create = async () => {
    if (name.trim().length < 2) return;
    setBusy(true);
    try { await createLocalAccount(name.trim()); router.replace('/'); }
    catch { Alert.alert('Could not create account', 'Make sure the local backend is online.'); }
    finally { setBusy(false); }
  };
  const choose = async (account: AccountSummary) => {
    setBusy(true);
    try { await signInLocalAccount(account.id); router.replace('/'); }
    catch { Alert.alert('Could not sign in', 'Please try again.'); }
    finally { setBusy(false); }
  };
  const developer = async () => {
    setBusy(true);
    try { const account = await developerLogin(pin); const runner = DEV_RUNNERS[(account.developer_slot ?? 1) - 1]; if (runner) setDevRunnerId(runner.id); router.replace('/'); }
    catch { Alert.alert('Developer sign-in failed', 'Check the local developer PIN.'); }
    finally { setBusy(false); }
  };

  return <SafeAreaView style={styles.screen} edges={['top', 'bottom']}><View style={styles.hero}><Text style={styles.mark}>✦</Text><Text style={styles.title}>RUN</Text><Text style={styles.tagline}>Own the streets you move through.</Text></View>
    <View style={styles.card}><Text style={styles.cardTitle}>Choose your runner</Text>{accounts.map((account) => <Pressable key={account.id} style={styles.account} onPress={() => void choose(account)} disabled={busy}><View style={styles.avatar}><Text style={styles.avatarText}>{account.display_name[0]?.toUpperCase()}</Text></View><Text style={styles.accountName}>{account.display_name}</Text><Text style={styles.chevron}>›</Text></Pressable>)}
      <TextInput style={styles.input} value={name} onChangeText={setName} maxLength={32} placeholder="New runner name" autoCapitalize="words" />
      <Pressable style={styles.primary} onPress={() => void create()} disabled={busy}>{busy ? <ActivityIndicator color={colors.surface} /> : <Text style={styles.primaryText}>Create runner</Text>}</Pressable>
      <View style={styles.divider}><View style={styles.line}/><Text style={styles.or}>LOCAL TOOLS</Text><View style={styles.line}/></View>
      <TextInput style={styles.input} value={pin} onChangeText={setPin} secureTextEntry placeholder="Developer PIN" />
      <Pressable style={styles.devButton} onPress={() => void developer()} disabled={busy}><Text style={styles.devText}>Developer sign in</Text></Pressable>
    </View><Text style={styles.foot}>Local POC accounts · Apple and Google sign-in are added once their provider credentials are connected.</Text></SafeAreaView>;
}
const styles = StyleSheet.create({screen:{flex:1,backgroundColor:'#F5FAF0',padding:spacing.lg},hero:{paddingTop:50,paddingBottom:30},mark:{color:colors.primary,fontSize:32},title:{fontSize:52,letterSpacing:4,fontWeight:fontWeight.bold,color:colors.text},tagline:{fontSize:fontSize.md,color:colors.textMuted,marginTop:4},card:{backgroundColor:colors.surface,borderRadius:24,padding:spacing.lg,shadowColor:'#193424',shadowOpacity:0.1,shadowRadius:18,elevation:3},cardTitle:{fontSize:fontSize.lg,fontWeight:fontWeight.bold,color:colors.text,marginBottom:spacing.md},account:{flexDirection:'row',alignItems:'center',paddingVertical:spacing.sm,borderBottomWidth:1,borderColor:'#E8EEE3'},avatar:{width:38,height:38,borderRadius:19,alignItems:'center',justifyContent:'center',backgroundColor:'#DCF1D1'},avatarText:{color:colors.primary,fontWeight:fontWeight.bold},accountName:{flex:1,color:colors.text,fontSize:fontSize.md,fontWeight:fontWeight.semibold,marginLeft:spacing.sm},chevron:{fontSize:26,color:colors.textMuted},input:{borderWidth:1,borderColor:colors.border,borderRadius:radius.md,padding:spacing.md,marginTop:spacing.md,color:colors.text},primary:{marginTop:spacing.sm,backgroundColor:colors.text,borderRadius:radius.md,padding:spacing.md,alignItems:'center'},primaryText:{color:colors.surface,fontWeight:fontWeight.bold,fontSize:fontSize.md},divider:{flexDirection:'row',alignItems:'center',gap:8,marginVertical:spacing.lg},line:{flex:1,height:1,backgroundColor:colors.border},or:{fontSize:10,color:colors.textMuted,fontWeight:fontWeight.bold,letterSpacing:1},devButton:{borderWidth:1,borderColor:colors.primary,borderRadius:radius.md,padding:spacing.md,alignItems:'center',marginTop:spacing.sm},devText:{color:colors.primary,fontWeight:fontWeight.bold},foot:{textAlign:'center',fontSize:11,color:colors.textMuted,lineHeight:16,marginTop:'auto',paddingTop:spacing.lg}});
