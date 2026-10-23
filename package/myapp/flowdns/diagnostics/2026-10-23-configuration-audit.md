# 2026-10-23 路由器配置与 UDP 检查

用户要求先全面检查、给出结果。本轮只通过 SSH 读取配置、运行状态、内核计数和日志；白名单过滤节点配置，不输出 UUID/密码/密钥。没有修改路由器文件、配置、服务或防火墙，没有安装工具，也没有做高 UDP 或带宽压力测试。报告与被动采样保存在本机工作区。

## 结论

没有证据可以确认运营商在 UDP 数量达到某阈值后实施 QoS。已确认本机主动拒绝国外 QUIC、DNS 切换会重启整个核心组；这些本机行为应与运营商限速分开。当前轻载资源和连接跟踪未见容量瓶颈。

当前数据代理是 VLESS + RAW/TCP + Reality + xtls-rprx-vision，Mux=false。非443的被代理 UDP 经 VLESS/XUDP 封装在当前 TCP 传输内；国内直连 UDP 及其它 VPN 流量的外层协议另算。不能用 LAN 看到的 UDP 数量推断 WAN 发往代理节点的原生 UDP 数量。此处依据实际配置及对应版本源码，不代表已通过抓包逐包验证所有 WAN 流量。

## 建议优先处理

| 优先级 | 发现和证据 | 建议 | 边界 |
| --- | --- | --- | --- |
| 高 | FlowDNS允许UDP，独立Xray使用Vision默认flow，保留的xray.log中有111条`XTLS rejected UDP/443 traffic` | 明确国外QUIC策略；当前节点适合在FlowDNS代理分支更早返回拒绝，让可回退的浏览器使用TCP，保留其它UDP及国内直连UDP | 某些强制QUIC应用不支持回退；不能全局禁用UDP，不能擅自将节点改为允许QUIC |
| 高 | Google DNS主用、Cloudflare备用；此前13:46切备用、13:51回主用，DNS前端正常重启；源码refresh会重建整个核心组 | DNS上游变动尽量只重载DNS后端，保留独立Xray和现有业务连接，并记录切换原因/耗时 | 当前策略本来就会短暂中断连接，不能把这段抖动归给ISP；不能只依据品牌认定哪个DNS更快 |
| 中 | WAN是DHCP，私网192.168.1.3/24，经192.168.1.1；本机没有SQM队列配置，tc工具也未安装 | 后续先测空闲与上传/下载饱和时的延迟，确认上级设备是否路由/NAT、QoS及宽带真实上下行；确有缓冲膨胀后再设计SQM | 上级可能也是瓶颈，不能只调整这台路由器就保证解决；未做负载试验，尚不能确认缓冲膨胀 |
| 中 | WAN6有一个全局地址，但未取得PD前缀；LAN只有ULA前缀，RA=hybrid、DHCPv6=relay，DNS未过滤AAAA | 要么补齐可用的LAN IPv6/PD/RA，要么明确IPv4模式，核实是否下发不可用IPv6默认路由 | 尚未读到客户端实际RA/路由或测公网IPv6，不能直接断言存在IPv6黑洞；不应因WAN6为up就认为客户端IPv6已通 |
| 中 | 5GHz一客户端信号约-63dBm，累计tx packets166012、retries18589、failed18525；另一客户端约-53dBm；2.4GHz设HE40、country=US | 性能对照先使用有线；需要无线时比较近距离5GHz，核对实际地区设置；2.4GHz若拥挤再比较20MHz | WED/硬件卸载下部分无线统计口径不完整，累计计数不等于当前丢包率；不能据此认定Wi-Fi为根因 |
| 中低 | 防火墙软件/硬件flow offload有效，FullCone启用；TurboACC还勾选SFE，但未见对应SFE模块 | 统一加速开关的管理入口；以后若启SQM或定位分流异常，单独做硬件卸载开关对照 | 软件+硬件offload同时启用本身正常；没有证据表明当前FullCone/offload导致故障；不要同时乱关所有加速 |
| 低 | 系统dnsmasq本机上游使用WAN DNS，LAN公网查询由FlowDNS重定向；log_level=info；AppFilter阻断enable=0，但记录开关为1且oafd仍运行 | 明确区分路由器本机DNS和LAN分流DNS；稳定后考虑warn日志、关闭不需要的应用记录 | 两套DNS承担的职责不同，不是发现了重复抢占；当前节点使用IP，未证明本机DNS导致代理节点连接失败；记录服务不是已确认吞吐瓶颈 |

Xray25.2.21实现先建立节点连接，再执行Vision UDP443拒绝，因此在FlowDNS更早处理可避免不必要的节点连接与等待。单独启用Mux并不是视频提速方案；当前关闭Mux合理。日志中的267条`CopyRawConn splice`表明部分连接已实际进入splice路径，不能再假设所有数据始终在多层用户态复制。

官方版本源码：[VLESS outbound v25.2.21](https://github.com/XTLS/Xray-core/blob/v25.2.21/proxy/vless/outbound/outbound.go)。参考：[Xray出站与Mux/XUDP说明](https://xtls.github.io/en/config/outbound.html)。

SQM用于控制负载下的排队延迟，不会凭空增加线路带宽；它与硬件卸载的配合必须重新设计，不能保留硬件绕过又假定SQM控制了全部流量。参考：[OpenWrt SQM](https://openwrt.org/docs/guide-user/network/traffic-shaping/sqm)、[Flow offloading](https://openwrt.org/docs/guide-user/perf_and_log/flow_offloading)。本次OpenWrt文档部分直接打开遇到网站验证，仅使用公开检索摘要，没有绕过验证。

## 当前无需盲目调整的项目

- BPi-R3 Mini / kernel6.6.127，CPU负载约0.04–0.17，MemAvailable约1.6GB，温度约54℃；未看到CPU/内存耗尽证据。未在饱和负载下采样，不代表满速CPU必然有余量。
- conntrack当前约200–700，上限65536（约0.3%–1.1%）；内核insert_failed/drop/early_drop均0。UDP超时60/180秒，暂不建议提高连接数上限、降低UDP超时或增大所有缓冲区。
- BBR已实际启用，默认qdisc为fq_codel；不能把系统default_qdisc视作已配置SQM。无需再重复“开BBR”。
- WAN物理链路1000Mbps全双工、MTU1500、物理errors0、TXdrop0；WAN有MSS修正。没有依据将MTU随意改为1492或认为链路协商到了100Mbps。
- softnet drop/time_squeeze累计均0。RPS掩码4把软件收包引导至CPU2，但当前没有单核瓶颈证据，不建议盲调中断亲和性。
- SmartDNS、PassWall、PassWall2、OpenClash、AdGuardHome配置未启用；无旧ss_spec规则表；当前只有FlowDNS接管表。安装/开机脚本数量很多，但“存在启动项”不等于实际进程在运行，不能据此批量停服务。
- cpulimit配置disabled，目标原为Transmission，不是Xray。AppFilter全局阻断disabled，不能仅凭oaf模块加载就断言存在限速。
- IPsec/L2TP、ocserv、frp、keepalived等仍在运行，可能承担远程接入，不将它们当作可随意关闭的冲突服务。

## 丢包与UDP观察

- WAN累计RX丢弃约45788，累计RX包约1.17亿，比例约0.039%，物理errors/missed均0；这不是“运营商丢包率”。
- 内核历史UDP RcvbufErrors=2841、SndbufErrors=22，说明本机过去出现过UDP缓冲区丢弃；当前存活UDP套接字未发现非零drops，无法定位已关闭的历史套接字或归属具体程序。
- 被动15秒采样处于轻载：WAN下行约0.016Mbps、上行约0.019Mbps；UDP收/发各13、UDP缓冲错误无增长；softnet无新增drop/squeeze；TCP发304段、重传1段；WAN RXdrop增加3。该样本不代表大UDP流量时正常，亦不足以判断小额接口丢弃原因。
- conntrack抽样约数十条UDP，大部分为内部DNS、53/123等；UDP443原始目的连接约3–4条。连接数不是每秒包数或带宽，硬件加速也会影响可见性，不能当作WAN UDP pps测量。

## 建议的下一轮对照

1. 固定节点和目标，电脑有线连接，先关闭客户端其它下载/同步；保持系统DNS。
2. 分别记录空闲、TCP负载、UDP负载下的带宽、到上级网关/国内目标/代理节点的RTT与丢包、WAN pps、conntrack、CPU单核softirq及UDP缓冲错误增量。
3. 分开比较同一台路由器的直连与代理，再比较上级设备处的结果；定位是LAN/Wi-Fi、上级排队、ISP链路还是节点。UDP接收统计应由自己控制的测试端提供，不能只看本机发送成功。
4. 为定位“数量阈值”，应分别控制总带宽、包速率和并发流数量，一次只变一个因素；不要直接对公网发大UDP流量。
5. 这轮没有执行上述主动负载实验，也不把它们安排成后台任务。仅凭现有配置、日志和轻载快照，仍不能确定宽带UDP QoS。

检查结束FlowDNS保持ready，国内外加密DNS健康；路由器配置和服务保持本轮开始时状态。
