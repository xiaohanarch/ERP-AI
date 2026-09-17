/** OAuth 回调页：校验 state -> 授权码换 T1 -> 进对话页。 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { exchangeCode } from '../api'
import { consumeOAuthState, useAuth } from '../auth'

export default function Callback() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { signIn } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const ran = useRef(false) // StrictMode 双渲染防重放（授权码一次性）

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    const run = async () => {
      const err = params.get('error')
      if (err) throw new Error(`网关返回授权错误：${err}`)
      const code = params.get('code')
      if (!code) throw new Error('回调缺少授权码（code）')
      if (!consumeOAuthState()(params.get('state'))) {
        throw new Error('state 校验失败（可能的 CSRF），请重新发起登录')
      }
      const { token } = await exchangeCode(code)
      await signIn(token)
      navigate('/chat', { replace: true })
    }
    run().catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [params, signIn, navigate])

  return (
    <div className="login-wrap">
      <div className="card login-card">
        {error
          ? (
            <div>
              <div className="error-banner"><span className="code">OAUTH.FAILED</span>{error}</div>
              <Link to="/login">← 返回登录</Link>
            </div>
          )
          : <p className="tagline">正在完成授权并换取令牌……</p>}
      </div>
    </div>
  )
}
