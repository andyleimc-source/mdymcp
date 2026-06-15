# mdymcp v1 token 服务器集中刷新

把 v1 token 的刷新集中到**一台常驻服务器**当唯一 owner，根治「多端抢刷 → refresh_token
互相顶成孤儿（`error_code 10101 / access_token不存在`）」。设计背景见仓库根
`handoff-mdymcp-server-refresh.md`。

## 为什么需要它

- v1 access_token 寿命 24h；refresh_token ~14 天，且**明道每次 refresh 都轮换 refresh_token**。
- 任意两端持同一对 token，谁先刷新就把另一端顶成孤儿。三台 Mac + 并行进程 → 互相顶掉。
- 解法：单 owner 刷新。只要这台服务器持续运行（刷新间隔 < 14d），rolling refresh 让
  token 链无限续命；其余所有端只读、永不刷新、永不孤儿。

## 组成

| 文件 | 作用 |
|---|---|
| `refresh_daemon.py` | one-shot：判断快过期才 refresh + 原子落盘（含重试）。零三方依赖。 |
| `mdymcp-refresh.service` | systemd oneshot 单元（运行 daemon）。 |
| `mdymcp-refresh.timer` | 每小时拉起一次（daemon 自判，绝大多数是 noop）。 |
| `provision.sh` | 本地一次性部署：推 daemon、种 seed、起 timer、布受限只读 key、写客户端 .env。 |

## 部署（一次性，在做初始部署的机器上跑）

```
# 前置：本机先跑过 mdymcp-auth，~/.mdymcp/v1_token.json 里有 refresh_token
bash server/provision.sh 101.43.4.46 ubuntu
# 或交互式：mdymcp-server-setup
```

provision 会：生成专用受限 key `~/.mdymcp/server_token_key` → 推 daemon + seed 到
`/opt/mdymcp/` → 起 timer → 把受限公钥写进服务器 `authorized_keys` 并锁 forced command
（**这把 key 只能 `cat` 那一个 token 文件，开不了 shell**）→ 写本机 `.env`。

其余机器：把 `~/.mdymcp/server_token_key` 和 `.env` 里 4 个 `MD_V1_TOKEN_*` 拷过去即可。
**所有用同一明道账号的端都要切 server——一个账号只能有一个 owner。**

## 安全

- 受限 key 在服务器 `authorized_keys` 配 `command="cat /opt/mdymcp/v1_token.json",no-pty,
  no-port-forwarding,no-X11-forwarding,no-agent-forwarding`——泄漏面只有「只读一个 token 文件」。
- daemon 只做**出站** HTTPS 到明道，不开任何监听端口（无新暴露面）。
- token 文件 `0600`，属运行用户；key 可单独轮换，不影响服务器其它访问。

## 运维

```
systemctl status mdymcp-refresh.timer        # 定时器是否在跑
journalctl -u mdymcp-refresh -n 20 --no-pager # 刷新日志
sudo systemctl start mdymcp-refresh.service   # 手动触发一次检查
cat /opt/mdymcp/v1_token.json                 # 看当前 token / expires_at
```

### 失败模式

| 风险 | 处理 |
|---|---|
| 服务器宕机 > 14 天 → 链断 | 重新种子：本地 `mdymcp-auth` → `bash server/provision.sh` 再跑一次 |
| refresh 偶发失败 | daemon 内置 3 次指数退避；连续失败退出码非 0，systemd journal 可接告警 |
| 取 token 依赖服务器/网络（无客户端缓存） | 客户端报错明确指向服务器/网络；取 token 频率低，影响可控 |
| 某端仍在 local 模式抢刷 | 切 server 后所有端都要切，否则又会互相顶 |
