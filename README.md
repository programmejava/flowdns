# FlowDNS

面向 **OpenWrt / ImmortalWrt、firewall4 / nftables** 的统一 DNS 与连接分流工具，提供 LuCI 界面、运行诊断和故障恢复。

当前服务和界面版本：**1.0.2-r1**。可选私有 sing-box 核心：**1.12.25-r1**。

1.0.2 改进启停和节点变更后的出口恢复：快速验证、恢复期加密 DNS 备用探测、后台探测与手动应用排队，以及“监听就绪 / 国外出口验证”分开显示。见[本次发布说明](package/myapp/flowdns/RELEASE-1.0.2.md)。

## 功能

- **SOCKS / Fake-IP**：通过本机独立 SOCKS5 出口代理国外连接，国内直连。
- **Xray 透明模式**：国内连接由内核放行，代理连接直接进入独立 Xray；支持读取兼容 SSR Plus 生成器的节点配置。
- 国内外加密 DNS、国内域名和 IP 规则、手动策略、透明模式 QUIC 策略。
- 依赖就绪后自动启动、运行健康检查、候选配置验证和失败恢复。
- LuCI 状态与排查、后台应用任务、规则更新和诊断报告。

两种模式均需配置独立的本机 SOCKS5；透明模式仍使用 SOCKS 承载国外 DNS。FlowDNS 不提供节点订阅或自动挑选节点。

## 安装与平台范围

请从本仓库 Releases 下载与目标固件架构匹配的安装包，先备份配置，再安装所需依赖。ARM64 安装包不能直接用于 x86_64 或 ARM32；即使 CPU 相同，也需核对固件 ABI 和软件源。首次安装默认关闭分流。

RK3568 / NanoPi R5S 使用这三个包：

```sh
opkg install ./flowdns-core_1.12.25-r1_aarch64_generic.ipk ./flowdns_1.0.2-r1_aarch64_generic.ipk ./luci-app-flowdns_1.0.2-r1_all.ipk
```

私有核心仅安装到 `/usr/libexec/flowdns-bin/sing-box`，不覆盖其他插件使用的系统核心。`flowdns` 包仍声明系统 `sing-box` 等依赖，需使用目标固件的软件源满足。内核模块必须匹配目标内核，不能强制安装其他固件的模块。

MTK / BPi-R3 Mini 使用 `flowdns_1.0.2-r1_aarch64_cortex-a53.ipk` 和同一份 `luci-app-flowdns_1.0.2-r1_all.ipk`。已有通过实际兼容验证的核心可继续使用，无需为此次优化替换共享核心。

启用前，在代理插件配置独立的本机 NOAUTH SOCKS5，显式选择实际节点；处理 SSR、PassWall、SmartDNS、AdGuardHome 等 DNS / 透明代理接管冲突，确保只有一套服务接管。客户端使用系统 DNS。详细步骤见[安装说明](package/myapp/flowdns/RELEASE-1.0.2.md)和[项目手册](package/myapp/flowdns/README.md)。

1.0.2 已完成主机隔离回归及 BPi-R3 Mini / NanoPi R5S 的升级、启停恢复、真实节点切换和 HTTPS/DNS 烟测；这些结果不代表所有固件、节点、IPv6 和 UDP 场景均已验收。见[本次记录](package/myapp/flowdns/diagnostics/2026-10-24-1.0.2-recovery.md)、[兼容范围](package/myapp/flowdns/COMPATIBILITY.md)和[后续用户反馈](VALIDATION.md)。firewall3 / iptables 和非 OpenWrt 系统需要额外适配。

## 源码与构建

本仓库是独立的软件包源码仓库，不是完整固件源码或 SDK：

```text
package/myapp/flowdns/           服务、私有 DNS 配方、测试和文档
package/myapp/luci-app-flowdns/  LuCI 界面和 RPC
package/myapp/flowdns-core/      可选私有 sing-box 配方
```

将所需目录复制到与目标固件匹配的 OpenWrt / ImmortalWrt SDK，准备相应 feeds 和依赖后构建：

```sh
make package/myapp/flowdns-core/compile package/myapp/flowdns/compile package/myapp/luci-app-flowdns/compile -j2 V=s CONFIG_PACKAGE_flowdns-core=m CONFIG_PACKAGE_flowdns=m CONFIG_PACKAGE_luci-app-flowdns=m
```

目标架构由 SDK 配置决定，不要仅修改安装包文件名或架构标签。跨平台步骤、依赖和验收要求见[移植指南](package/myapp/flowdns/PORTING.md)。完整网络回归脚本应在准备好主机依赖的 SDK / 固件源码树中运行；其中 init 测试还使用该源码树的 `package/base-files`。

## 文档

- [当前稳定基线、备份范围与版本解锁](STABLE-BASELINE.md)
- [故障排查](package/myapp/flowdns/TROUBLESHOOTING.md)
- [开发过程与问题复盘](package/myapp/flowdns/DEVELOPMENT.md)
- [功能实现记录](package/myapp/flowdns/IMPLEMENTATION.md)
- [更新记录](package/myapp/flowdns/CHANGELOG.md)
- [RK3568 安装与验证记录](package/myapp/flowdns/diagnostics/2026-10-23-rk3568-install.md)

## 授权与上游

FlowDNS 原创代码采用 **GPL-3.0-or-later**，见 [COPYING](COPYING)。私有 dnsmasq 是独立的 GPL-2.0 组件；可选 sing-box 核心采用 GPL-3.0-or-later，其依赖各有许可。各组件保留上游许可，完整源码发行归档包含固定上游源码及私有核心 vendor 依赖。

上游：[dnsmasq](https://thekelleys.org.uk/dnsmasq/)、[sing-box](https://github.com/SagerNet/sing-box)、[Xray-core](https://github.com/XTLS/Xray-core)。规则来源：[dnsmasq-china-list](https://github.com/felixonmars/dnsmasq-china-list)、[china-operator-ip](https://github.com/gaoyifan/china-operator-ip)。

仓库不包含实际路由器配置、节点凭据、SSH 密钥或原始访问日志。反馈问题时，请先检查并删除日志中的敏感信息。
