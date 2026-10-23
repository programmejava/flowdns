# 2026-10-23 远程只读排查

连接和读取经过用户授权。本轮未启动或停止服务、切换代理、修改 UCI/DNS/防火墙、安装包或重启路由器。以下为留存故障证据，未在线复现故障。为减少隐私信息，不保存完整访问日志、节点地址、UUID、密钥或原始 Xray 配置。

## 当前状态

FlowDNS 配置 enabled=0、mode=socks；运行状态 stopped，ubus 没有 FlowDNS 实例。运行目录中的 active/engine-mode 仍是上一次恢复的 transparent 快照，不代表服务当前正在运行。

## 留存故障证据

- FlowDNS 0.3.0-r2，LuCI 0.3.0-r1，dnsmasq 2.90，nftables 1.1.1，Xray 25.2.21（ARM64）。
- Xray 日志有 TCP/UDP 15355 监听、核心启动、LAN 连接接收、VLESS 隧道及 XTLS padding/unpadding，排除“这些日志时间点 Xray 从未启动”的假设；不构成 YouTube 全链路成功证明。
- dnsmasq.log 从本地时间 10 月 23 日 01:36 开始出现 foreign4 的 Resource busy、Invalid argument、Protocol error 等 netlink/cache initialization 错误，不同 PID 同时报错。
- recovery.log 记录同一时期 front 进程退出（状态 1）、核心组退出和监管重试。这证明 DNS 前端实际退出过；退出的具体触发原因还不能仅凭错误相邻就确认。
- 最近 apply 任务持续约 106 秒，以“新配置未能启动，已尝试恢复上一运行配置”结束，其引用的 error 和 prepare-result 是“另一个操作正在执行”。这证明当次切回失败，不足以确定持锁进程或称作永久死锁。
- 当时 health 的 SOCKS 和国内/国外加密 DNS 探测均成功；这些探测不等于独立 Xray 的 LAN 实际业务已通过。

## 与源码、上游问题的对应

本仓库 dnsmasq 2.90 使用静态 nft_ctx，正常 TCP 处理会 fork 子进程。上游维护者确认多个进程共享 nft_ctx 的竞态可产生同类错误，并在后续开发版本修复：
https://lists.thekelleys.org.uk/pipermail/dnsmasq-discuss/2025q2/018170.html

版本、不同 PID 和错误与此已知问题吻合，是高优先级解释；尚未在相同目标库/并发场景复现，不能断言它解释所有国外访问失败。前端退出会导致 FlowDNS 清理整个核心组并撤销接管，足以破坏国外访问，而国内仍可能经系统原路径可用。

测试覆盖缺口：现有隔离测试为避开 user namespace 的 setgroups 限制，在 dnsmasq wrapper 中追加 --no-daemon；OPT_DEBUG 也跳过正常 TCP fork 路径。因此此前本机逻辑/转发通过不能排除目标正式并发模式问题。未来回归应覆盖实际前台 fork 模式及并发 TCP/UDP DNS，不能用串行调试模式替代。

源码中还存在 UCI 提交触发 procd reload 与显式后台 apply 共存的路径。rpcd UCI commit 发 config.change；FlowDNS 的 reload trigger 默认重新提交 boot 实例；apply 同时持 work.lock 并等待 prepared 实例就绪。需要通过并发重现验证是否导致此次等待/锁冲突，不能仅凭现场日志确定触发时序。

## 后续修复要求

1. 处理正式 dnsmasq/nftset 并发兼容性，保留 TCP DNS，不能简单禁用 TCP 或把调试模式当作生产补丁。
2. 配置提交、应用、reload 的启动责任统一，验证互斥和回退在并发事件下能完成；不删除锁文件来绕过真正的持锁进程。
3. 健康检查区分国外 DNS SOCKS 与独立 Xray 数据出口；DNS 前端退出时保留退出原因，避免后续锁提示遮住原始错误。
4. 完成目标版本/正式模式并发和恢复回归后，再由用户选择维护窗口做真机测试。当前远程会话不启用实验模式。
