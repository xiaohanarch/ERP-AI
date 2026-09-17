/** 登录页：OAuth 授权码流程入口（整页跳转网关统一登录，不在本页收口令）。 */
import { useAuth } from '../auth'

const DEMO_ACCOUNTS: { user: string; name: string; role: string; tenant: string }[] = [
  { user: 'lisi', name: '李四', role: '财务（全权限 · 写路径发起人）', tenant: 'T-EAST 华东制造' },
  { user: 'wangwu', name: '王五', role: '经理（审批人）', tenant: 'T-EAST 华东制造' },
  { user: 'qianqi', name: '钱七', role: '财务（全权限）', tenant: 'T-UNI 星联科技' },
]

export default function Login() {
  const { gotoLogin } = useAuth()
  return (
    <div className="login-wrap">
      <div className="card login-card">
        <div className="logo-row">
          <span className="logo" />
          <h1>WorkBuddy</h1>
        </div>
        <p className="tagline">
          员工助手平台：经 AI 网关以 <b>OAuth 授权码</b> 取得 T1 令牌后访问诊断 / 筛查 / 税码补全场景，
          写路径在此挂起，由审批人在本平台完成三要素审批。
        </p>
        <div className="flow">
          浏览器 → <b>GET /gw/oauth/authorize</b>（网关统一登录）<br />
          302 回调 → <b>?code=</b> → <b>POST /gw/oauth/token</b> 换 T1（azp=surface-workbuddy）
        </div>
        <div className="login-accounts">
          <table className="kv">
            <tbody>
              {DEMO_ACCOUNTS.map((a) => (
                <tr key={a.user}>
                  <th>{a.name}（{a.user}）</th>
                  <td>{a.role}<br /><span style={{ color: 'var(--muted)', fontSize: 12 }}>{a.tenant}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="btn login" onClick={gotoLogin}>使用 ERP 账号授权登录</button>
        <div className="login-note">演示口令统一为 demo123 · 请经 http://localhost:8088 访问（回调地址已注册）</div>
      </div>
    </div>
  )
}
