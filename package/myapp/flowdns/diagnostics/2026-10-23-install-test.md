# 2026-10-23 远程安装测试与恢复

用户明确授权上传、安装和运行测试，并要求出现网络故障立即停止。此次已执行到 DNS 超时即停止，不继续修改 SmartDNS 或再次尝试透明模式。

## 准备及基线

- BPi-R3 Mini，ARM64，ImmortalWrt 24.10-SNAPSHOT / kernel 6.6.127。
- 起始 FlowDNS disabled、mode=socks，实际使用 SSR Plus 主透明代理；独立 SOCKS 已开启。
- 将两个 0.3.1-r1 包及旧服务/界面包传至路由器；SHA256 与本地成品一致。opkg 升级成功；私有 flowdns-dns 2.93 能执行并报告 nftset 支持。原 FlowDNS 配置被保留。
- 路由器私有目录 /root/flowdns-test-20261023 保存原配置、运行快照、旧安装包和恢复日志（含敏感配置，未下载或展示）。切换前启动独立十分钟超时恢复守护，故障时可提前请求恢复。
- 建立临时 network namespace + veth 接入 br-lan，独立测试子网 10.253.253.0/30。原 SSR 模式下隔离客户端 DNS 可用；经原 SSR 透明数据路径访问 YouTube HTTPS 返回 200（约 2.23 秒）。没有修改原 LAN 地址、WAN、SSH 或默认路由。

## 触发与停止

- 将 SSR 主服务器暂设 nil（保留独立 SOCKS），重启 SSR，设置 FlowDNS enabled=1 / mode=transparent，提交 queue apply。
- apply 很快被前置检查拒绝：SmartDNS 正在接管 DNS。没有启动本次 FlowDNS 透明核心或接管。
- 只读核对发现 smartdns enabled=1、auto_set_dnsmasq=1、port=5335；dhcp dnsmasq 上游为 127.0.0.1#5335 / noresolv=1，但没有运行中的 SmartDNS 进程。
- 退出原 SSR 后，隔离 LAN 客户端查询系统 DNS 超时。独立 SOCKS 访问 YouTube 仍返回 HTTP 200，SSH 保持连接。
- 立即请求守护恢复，不继续更改 SmartDNS、不重试 FlowDNS。此次发现的是退出 SSR 后暴露的 DNS 依赖问题，不是新私有 DNS 前端崩溃的证据。

## 恢复和结论

- 13:27:32 请求恢复；13:27:49（路由器 CST）恢复脚本完成。
- 恢复原 FlowDNS 和 SSR 配置，停止 FlowDNS，重启原 SSR；清理临时测试接口、namespace 和测试子网。
- 恢复后路由器 DNS 再次返回百度真实 IPv4；独立 SOCKS 请求 YouTube 返回 HTTP 200（约 2.46 秒）。
- 0.3.1-r1 已安装但保持禁用。SSR 为当前网络提供代理。
- 本次透明模式启动和吞吐验收未通过/未完成；不宣称并发修复已在真机运行通过，亦没有 YouTube connection speed 性能结论。
- 后续要重新测试，必须先规划退出 SSR 后的系统 DNS 可用性，并在备份/恢复范围内处理 SmartDNS 接管配置。此次按用户要求已停止。
