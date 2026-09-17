/** 会话上下文：OAuth T1 令牌（sessionStorage）+ whoami 用户信息。 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { OAUTH, whoami } from './api'
import type { WhoAmI } from './types'

const TOKEN_KEY = 'wb.token'
const STATE_KEY = 'wb.oauthState'

interface AuthValue {
  token: string | null
  user: WhoAmI | null
  loading: boolean
  /** Callback 页换码成功后写入会话。 */
  signIn: (token: string) => Promise<void>
  signOut: () => void
  /** 生成防 CSRF state 并整页跳转网关统一登录。 */
  gotoLogin: () => void
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState<WhoAmI | null>(null)
  const [loading, setLoading] = useState(() => sessionStorage.getItem(TOKEN_KEY) !== null)

  useEffect(() => {
    let alive = true
    if (!token) {
      setLoading(false)
      return
    }
    whoami(token)
      .then((u) => { if (alive) { setUser(u); setLoading(false) } })
      .catch(() => {
        if (!alive) return
        sessionStorage.removeItem(TOKEN_KEY)
        setToken(null)
        setUser(null)
        setLoading(false)
      })
    return () => { alive = false }
  }, [token])

  const signIn = useCallback(async (next: string) => {
    sessionStorage.setItem(TOKEN_KEY, next)
    const u = await whoami(next)
    setUser(u)
    setToken(next)
  }, [])

  const signOut = useCallback(() => {
    sessionStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }, [])

  const gotoLogin = useCallback(() => {
    // state 防 CSRF：跳转前落 sessionStorage，回调时校验
    const state = nid()
    sessionStorage.setItem(STATE_KEY, state)
    window.location.href = OAUTH.authorizeUrl(state)
  }, [])

  return (
    <AuthContext.Provider value={{ token, user, loading, signIn, signOut, gotoLogin }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}

/** 回调页校验 state（一次性消费）。 */
export function consumeOAuthState(): (state: string | null) => boolean {
  const saved = sessionStorage.getItem(STATE_KEY)
  sessionStorage.removeItem(STATE_KEY)
  return (state: string | null) => !!saved && !!state && saved === state
}

/** 会话内随机 id（randomUUID 在非安全上下文不可用，做兜底）。 */
export function nid(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
