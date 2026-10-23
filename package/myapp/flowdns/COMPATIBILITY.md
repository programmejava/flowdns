# 1.0.1 兼容与发布

## 支持契约

- OpenWrt/ImmortalWrt 的 procd、ubus、UCI、Lua 5.1、nixio、luci.jsonc。
- firewall4/nftables、ip-full 的数字 JSON 输出、完整 IPv4/IPv6 策略路由、nft TProxy 模块。
- 本机回归使用 sing-box 1.12.25。r2 对其它版本、自编译或未知版本显示提示，不再仅凭版本号拦截；启动必须通过生成配置的 `sing-box check`、本次进程监听检查和防火墙接管校验。这些检查不能替代真实业务兼容性测试。
- SSR Plus / PassWall 独立本机 NOAUTH SOCKS5，节点切换仍由原插件负责。UCI 结构不同的分支可用手动端口模式。

`flowdns environment` 返回架构、依赖版本、阻断问题和版本提示。缺少必要工具仍为错误；`ok` 只表示基础依赖检查通过，版本提示不会导致启动失败。内核能力仍需正式 nft 配置检查与接管验证。此命令不等于全客户端或全协议可用。

## 透明模式的额外契约

仅 SSR Plus 的 `type=v2ray`、VLESS/VMess/Trojan/Shadowsocks Xray 节点，且安装本仓库 `/usr/share/shadowsocksr/gen_config.lua`。目标上必须通过 `xray run -test`；不能把相同节点名称当作不同分支 UCI 完全兼容。DNS 前端由服务包私有携带，基于 dnsmasq 2.93 的 DNS/nftset 构建，实际配置经 `/usr/libexec/flowdns-dns --test`，内核规则经 `nft -c`。系统 dnsmasq 不被替换；服务包需按架构重新构建原生私有二进制。

0.3.1 本机验证使用 sing-box 1.12.25、Xray 25.2.21、私有 dnsmasq 2.93，包含实际 SSR 生成器及隔离 LAN/目标网络。测试使用正式 TCP fork/父进程 IPC，混合 IPv4/IPv6 TCP/UDP DNS 并发；仅将 user/group 置空以适应 user namespace。普通 VLESS 与 Reality/Vision 实际握手转发均覆盖；旧 2.90 在相同并发对照中复现 nftset/netlink 错误。此前 --no-daemon 测试未覆盖这个场景，已移除。

用户 0.3.0-r2 路由器失败的留存证据见 diagnostics/2026-10-23-remote-review.md。2026-10-23 在 BPi-R3 Mini（sing-box 1.12.22、Xray 25.2.21、kernel 6.6.127）安装 0.3.1，并在清理 SmartDNS 接管和 SSR 遗留 ss_spec 规则后，通过 128 次并发 DNS 与 LAN 国内/Google/YouTube HTTPS 测试。服务随后升级为 0.3.1-r2，补齐遗留规则检测；两次重新应用正常完成。三轮同 IP 5MB 下载中，新透明路径与当前独立 SOCKS 约 10–13 Mbps，不能推断 YouTube CDN 或所有线路性能。UDP/QUIC、公网 IPv6、该透明版本重启及长时运行仍未验收。详见 diagnostics/2026-10-23-retest.md。

## 验证范围

| 环境 | 已执行/交付 | 尚需验证 |
| --- | --- | --- |
| Linux x86_64 主机 | 真实 Lua 5.1/nixio/jsonc、sing-box 1.12.25、本机 DoH/DoT/SOCKS、双栈隔离网络测试 | 不等于 x86_64 OpenWrt 固件安装验收 |
| aarch64_cortex-a53 当前 SDK | 目标服务包与 all 架构界面包；用户确认当前路由器重启后自动启动、运行正常 | 断电冷启动、断网恢复、独立 IPv4/IPv6、长时间压力与吞吐 |
| 其它 ARM64、x86_64 OpenWrt | 通用脚本和依赖构建配方，无专用 CPU 代码 | 目标 SDK 构建、安装、内核功能和性能 |
| ARM32、MIPS、其它支持 Go 的架构 | 无专用架构代码；由目标工具链构建依赖 | 未实机验证，不能宣称已支持；尤其需评估内存/存储 |
| firewall3/iptables、非 OpenWrt | 不在支持范围 | 需要另行适配服务、配置与防火墙 |

界面包 `all` 可在满足 LuCI 契约时复用；服务依赖的 Go 引擎、Lua 原生模块和内核模块需要匹配目标架构/ABI。禁止把 ARM64 安装包改名安装到其它架构。

用户已确认 sing-box 1.12.22 的 ARM64 路由器在解除版本误拦截后恢复 YouTube，正式 DNS 与接管诊断通过；2026-10-20 进一步确认重启后自动启动、运行正常。这项记录不代表断电冷启动、完整 IPv6/UDP 或长期稳定性已通过。

## 发布回归

在仓库根目录运行：

```sh
sh package/myapp/flowdns/tests/run.sh /path/to/lua /path/to/host/lua-modules /path/to/sing-box /tmp/flowdns-regression /path/to/xray /path/to/built-private-dns
```

Lua 模块需由当前仓库 luci-lib-nixio/luci-lib-jsonc 源码构建。测试使用本机 TLS 测试服务及新建网络命名空间，不访问公网，不改变宿主机路由；命名空间测试需要系统允许 user/net namespace。只有完成目标引擎的实际配置、业务和转发测试后，才能把该版本列入已验证范围。

构建各目标包后运行 `tests/release.py` 校验安装包内容及菜单/版本资源一致性。发布记录必须标明：目标包构建、主机模拟与真实路由器验收分别通过了什么。

## 0.4.0 验证补充

完整隔离回归包含原SOCKS模式、真实Reality/Vision握手、双栈QUIC拒绝/允许和其它UDP保留；真实长TCP连接跨DNS后端替换与运行绑定失败回退，Xray/前端PID与测试nft元素不变。DNS-only更新仅适用于透明模式且严格比较非DNS政策和其它配置文件；规则/节点/QUIC/模式变化仍完整重载。原SOCKS模式未宣称DNS切换不中断。

2026-10-23 用户授权在当前ARM64路由器升级0.4.0-r1；真机Google→Cloudflare→Google应用返回dns_only=true，事务约3.2秒/2.2秒，原同一条20MB、无重试HTTPS下载完整返回200；核心/前端/Xray PID和测试集合元素保持。监管刷新路径另行核对，现场记录见diagnostics/2026-10-23-04-deployment.md。运行绑定失败回退只在本机隔离环境故意注入，不冒充真机破坏性测试。

## 1.0.0 发布基线

继承0.4.0数据路径，正式安装与验收以 diagnostics/2026-10-23-1.0.0-release.md 为准。2026-10-23用户客户端报告透明模式首页立即加载、视频约43Mbps，随后实测SOCKS速度与透明模式相近。此为用户体验反馈，不等同于严格固定CDN/协议的吞吐上限。跨架构步骤见PORTING.md；包检查按control架构核对ELF，不再仅接受ARM64。

## 多地址 LAN 的额外验收边界

本次SOCKS隔离客户端使用临时附加子网时，UDP请求发往桥主地址，sing-box通配监听的应答选择了该附加子网网关地址/16553，未匹配DNS重定向的反向连接，客户端超时；生产主LAN的自检/实际业务仍正常。将仅该测试子网的路由首选源地址设为桥主地址后复验。正式代码未新增多地址应答适配；同一桥多IPv4地址或跨子网访问的移植须专测UDP应答源IP/端口，不应只看监听和TCP结果。测试路由/附加地址在结束时删除，不能照抄到其它网络。

## RK3568 / 1.0.1

R5S（LEDE R25.8.8、自报24.10.2、kernel6.12.41、aarch64_generic、musl1.2.5）安装三包并通过私有核心实际TCP/UDP加密DNS、nft检查，原核心1.11.15和SmartDNS/SSR配置保持。尚未启用LAN接管，不能将安装烟测当成视频或完整分流已验收。未用6.6内核模块替代目标依赖，kmod-nft-socket因未使用表达式从1.0.1移除。详见diagnostics/2026-10-23-rk3568-install.md。
