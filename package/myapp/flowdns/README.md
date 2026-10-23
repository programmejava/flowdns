# FlowDNS 1.0.1

面向 OpenWrt / ImmortalWrt、firewall4/nftables 的统一 DNS 与连接分流。1.0.0 固定已经验证的 0.4.0 数据路径，提供 SOCKS / Fake-IP 和 SSR Plus / Xray 透明代理两种模式。默认模式、已有节点和用户配置保持兼容，升级不会自动切换模式。

当前包为 `flowdns 1.0.1-r1`、`luci-app-flowdns 1.0.1-r1`；RK3568 用户态适配及可选私有核心见 [RELEASE-1.0.1.md](RELEASE-1.0.1.md)。此前 1.0.0 发行归档保留。当前目标真机为 BPi-R3 Mini / ARM64；其它平台需要目标 SDK 重新编译和验收。“正式发布”不等于所有架构和所有固件均已实测。

## 文档入口

- [当前 RK3568 安装和私有核心说明](RELEASE-1.0.1.md)
- [1.0.0 安装、升级、恢复和发布清单](RELEASE.md)
- [跨架构移植与 SDK 构建](PORTING.md)
- [故障排查手册](TROUBLESHOOTING.md)
- [开发过程、失败教训和证据](DEVELOPMENT.md)
- [支持范围与兼容矩阵](COMPATIBILITY.md)
- [真机验收步骤及历史结果](ACCEPTANCE.md)
- [功能实现记录](IMPLEMENTATION.md)
- [客户端性能对照工具](tools/README.md)
- [0.4.0 真机部署记录](diagnostics/2026-10-23-04-deployment.md)及 [1.0.0 发布验收](diagnostics/2026-10-23-1.0.0-release.md)

## 两种模式

| 项目 | SOCKS / Fake-IP（默认） | 透明代理 |
| --- | --- | --- |
| 数据路径 | LAN → sing-box TProxy → 本机 SOCKS → 节点 | 国内由内核放行；代理连接直接进入独立 Xray |
| 代理来源 | SSR Plus、PassWall、手动本机 NOAUTH SOCKS5 | SSR Plus 的 VLESS / VMess / Trojan / Shadowsocks Xray 节点 |
| DNS | 国内真实 IP，代理域名 Fake-IP；连接时恢复域名 | 真实 IP；私有 dnsmasq 前端学习 nft 集合，sing-box 提供加密 DNS |
| DNS 主备切换 | 重载核心，可能中断现有连接 | 仅替换 DNS 后端；验证失败恢复原 DNS，保留 Xray/前端/集合 |
| 域名边界 | Fake-IP 可保持域名策略 | 共享 CDN IP 采用自动代理优先；手动直连可覆盖自动策略 |
| QUIC | 原出口处理 | auto/reject/allow；自动识别 Vision 默认拒绝 UDP443并提前拒绝 |

国内 DNS 在 AliDNS / DNSPod 间备用；国外在 Google / Cloudflare 间备用，始终经过所选本机 SOCKS。两种模式都需要独立 SOCKS；透明模式使用它承载国外 DNS。DoH/DoT 验证证书，不自动降级到公共明文 DNS，不因代理失效把国外解析改成直连。

SOCKS 不必然比透明代理慢。用户已验证当前两种模式视频速度相近；旧版性能异常同时涉及 QUIC 回退、DNS 故障切换整组重启和外部线路，不能全部归因于 SOCKS。

## 首次安装与配置

1. 按 RELEASE.md 安装匹配固件/架构的服务包、界面包及依赖。首次安装默认关闭分流，注册开机服务。
2. 在代理插件启用独立本机 SOCKS5、NOAUTH、端口 1080，并显式选择实际节点。SSR 主服务器停用；PassWall 关闭主透明代理及访问控制。只允许一套服务接管 DNS/流量，检查 SmartDNS、AdGuardHome、OpenClash 等。
3. 服务 → FlowDNS 分流 → 设置与说明，选择代理来源、运行模式、DNS 和 DoH/DoT，启用并保存应用。首次自动下载国内规则；现有配置升级时保留。
4. 状态与排查应显示运行、监听就绪、已接管；运行完整诊断。电脑/手机使用系统 DNS，浏览器不要另指定加密 DNS。
5. 用 LAN 客户端验证国内网页、国外网页和实际视频。切换模式后清空客户端 DNS 缓存、重开浏览器；旧 Fake-IP 不能当成透明模式真实地址使用。

透明模式需要 `xray-core` 和兼容的 `/usr/share/shadowsocksr/gen_config.lua`。读取 SSR 所选独立 SOCKS 节点的生成配置并衍生独立 Xray，保留传输/Reality/Vision 等，不修改 SSR 节点或启用其防火墙。节点配置变化会校验并完整重载，现有连接会中断；不自动挑选其它节点。

## 生命周期与回退

监管等待网络、时间、规则和出口，失败以 2、4、8…60 秒退避重试。开机接管要求开机服务已注册且 `flowdns.main.enabled=1`。运行中检查监听、正式 TCP/UDP DNS、出口和防火墙；出口暂时失败保留核心与国内服务。核心退出或停用会撤销 FlowDNS 接管，恢复系统原有路径；这不是全路由器故障封锁策略。

候选配置通过 sing-box / Xray / 私有 DNS / nft 检查后才替换当前服务。手动应用失败尝试恢复上一运行快照，保存的 UCI 不自动改回；自动刷新失败保留旧规则或恢复旧运行快照。纯 DNS 更新的快速事务仅限透明模式，节点、规则、QUIC 或其它数据策略改变仍完整重载。DNS 替换期间查询可能短暂延迟。

LuCI 提交后由明确的后台 apply 执行。CLI 提交 UCI 后还需 `/etc/init.d/flowdns reload`。任务与启动维护共用内核锁，不按固定时长强行解锁；空 `.lock` 文件不代表占用，不要删除锁文件。

## 规则、诊断与边界

国内域名来自 [dnsmasq-china-list](https://github.com/felixonmars/dnsmasq-china-list)，国内 IPv4/IPv6 来自 [china-operator-ip](https://github.com/gaoyifan/china-operator-ip)。HTTPS 下载校验证书、格式、最小数量及差异，任一集合减少超过 30% 拒绝发布。源 JSON、诊断策略和 SRS 持久保存，原子切换 current，保留 previous 与运行/恢复引用；自动更新默认关闭，失败至少一小时后再试。规则更新可能中断现有连接。

透明模式集合最长保留 24 小时，客户端 DNS TTL 上限 5 分钟；纯 DNS 后端更新保留集合，完整重载/重启/nft 重建会清空。过滤 HTTPS/SVCB 记录。手动规则冲突拒绝保存；修改策略不会迁移既有连接。精确优先级与实现见 `src/core.lua`、`src/transparent.lua`。

运行目录 `/var/run/flowdns` 权限 700。日志存 RAM，约 1 MiB 后保留末尾 64 KiB 到 previous；重启后清除。诊断报告可能含域名和 LAN IP，不含完整 Xray 节点配置；分享前检查。SOCKS UDP ASSOCIATE 仅证明接口接受，不证明实际 UDP、游戏或强制 QUIC 可用。

仅接管配置的受信任 LAN，路由器本机进程不经过 LAN 透明接管。ICMP 不代理；firewall3/iptables、非 OpenWrt、任意旁路由拓扑未适配。IPv6 隔离回归已覆盖，但当前真机无完整 LAN 公网 IPv6 验收。

内部端口：DNS 前端 16553，透明模式 DNS 后端 16554，TProxy 15355。独立表 `inet flowdns`、路由表/优先级 20260、mark `0x40000000`。资源冲突拒绝启动，不清空其他软件的路由或规则。

## 构建与授权

```sh
make package/myapp/flowdns/compile package/myapp/luci-app-flowdns/compile -j2 V=s CONFIG_PACKAGE_flowdns=m CONFIG_PACKAGE_luci-app-flowdns=m
sh package/myapp/flowdns/tests/run.sh /path/to/lua /path/to/host-lua-modules /path/to/sing-box /tmp/flowdns-regression /path/to/xray /path/to/private-dns
python3 package/myapp/flowdns/tests/release.py /path/to/flowdns.ipk /path/to/luci-app-flowdns.ipk
```

服务包含目标架构原生私有 DNS，不可仅复制运行文件夹或改名安装包完成跨架构移植。配方固定 dnsmasq 2.93 与 SHA-256，关闭 DHCP/TFTP/脚本，不替换系统 DNS。FlowDNS 原创代码 GPL-3.0-or-later；私有 dnsmasq 独立组件 GPL-2.0（完整授权见各自 COPYING），两个许可均随服务安装。源码归档包含配方、双包源码、测试、文档及未经修改的 dnsmasq 上游源码压缩包，不包含路由器配置、运行日志或凭据。
