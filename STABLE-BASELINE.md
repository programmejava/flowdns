# 1.0.1-r1 稳定基线

## 当前确认结果

2026-10-23（北京时间），用户在 NanoPi R5S / RK3568 上确认 FlowDNS 工作正常，并进一步反馈实际访问速度很好。随后通过 SSH 检查：

- 服务 `flowdns 1.0.1-r1`、界面 `luci-app-flowdns 1.0.1-r1`、私有核心 `flowdns-core 1.12.25-r1`。
- 固件自报 OpenWrt 24.10.2 / LEDE R25.8.8，内核 6.12.41，目标 rockchip/armv8。
- FlowDNS 已启用，当前运行 SOCKS 模式，代理来源 SSR Plus，`flowdns ready` 返回成功，开机服务已注册。
- 稳定基线操作仅备份文件及设置包 hold 标记，没有切换模式、重新应用配置、重启服务或改动网络。
- 操作前后 FlowDNS、SSR Plus、SmartDNS、DHCP、网络和防火墙配置的摘要一致，FlowDNS 服务实例信息一致，操作后 ready 仍成功。

用户速度反馈不作为固定节点、固定 CDN、固定协议的吞吐基准；本次没有重新进行视频测速、长期压力或公网 IPv6 验收。历史安装烟测记录保留其当时默认关闭的事实，本记录补充后续启用状态。

## 固定版本

在确认备份可用后，对上述三个 FlowDNS 包设置 `opkg flag hold`，减少批量软件包升级时意外替换当前版本的可能。原系统 sing-box、Xray 和其他共享依赖未被设置 hold。

hold 不冻结配置文件，也不能阻止手动强制安装或刷机。计划升级时，先保留旧包和私有配置备份，核对新版本依赖，再解锁：

```sh
opkg flag ok flowdns
opkg flag ok flowdns-core
opkg flag ok luci-app-flowdns
```

检查状态可分别执行：

```sh
opkg status flowdns
opkg status flowdns-core
opkg status luci-app-flowdns
```

## 私有备份范围

路由器在 `/root/flowdns-stable-backups/<UTC时间戳>/` 保留权限受限的快照，本机另存一份并校验所有快照成员的 SHA256。备份包括：

- FlowDNS 配置、持久规则，以及关联的 SSR Plus、SmartDNS、DHCP、网络和防火墙配置（文件存在时）。
- 三个 FlowDNS 包当前安装的实际文件及版本、冻结前的软件包状态。
- 固件信息、启用模式、服务实例、摘要清单和恢复说明；版本冻结后的状态另行记录。

这些备份含节点凭据和网络配置，**不进入 Git 仓库或 GitHub Release**。本仓库只保存程序源码、默认配置和经整理的说明文档。备份不是完整固件镜像或所有依赖包的副本。

恢复时先核对摘要和归档内容，优先安装对应版本、对应架构的公开安装包，再在 FlowDNS 停止时恢复所需配置和规则。涉及网络、防火墙和 DHCP 的共享配置应在具备本地或恢复访问手段时谨慎恢复，不能将整份快照直接覆盖视为安全的一键回退。首次安装前的原网络备份与本次稳定快照用途不同，应分别保留。

## 文档与版本关系

程序安装包和完整源码发行归档已随 [`v1.0.1-r1`](https://github.com/programmejava/flowdns/releases/tag/v1.0.1-r1) 固定发布。本次仅补充运行反馈和稳定基线文档，不修改已发布附件、标签或程序行为。后续改进另建提交和版本，保留这个可回退的版本。

- [安装说明](package/myapp/flowdns/RELEASE-1.0.1.md)
- [移植指南](package/myapp/flowdns/PORTING.md)
- [排查手册](package/myapp/flowdns/TROUBLESHOOTING.md)
- [开发复盘](package/myapp/flowdns/DEVELOPMENT.md)
- [原始 R5S 安装记录](package/myapp/flowdns/diagnostics/2026-10-23-rk3568-install.md)
