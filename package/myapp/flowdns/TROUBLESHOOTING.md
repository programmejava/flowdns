# 故障排查手册

先记录时间、版本、运行模式、最近操作和客户端现象，再做最小变更。下列 sh 命令在路由器 SSH 执行；每条分别复制，不能把多行丢失换行后拼成一个命令。Windows 专用命令明确另列。

## 先分清路径

- LAN 客户端 → 路由器 DNS53 → FlowDNS16553；路由器本机查询不经过 LAN 接管。
- SOCKS：sing-box TProxy15355 → 本机 SOCKS1080 → 节点。
- 透明模式：私有前端16553 → sing-box DNS16554；国外 DNS 经 SOCKS，数据进入独立 Xray15355。
- “国内通、国外不通”可能是 DNS、SOCKS、Xray、规则或实际节点/CDN，不能直接断定 Xray 没启动。

## 最小只读证据

```sh
opkg list-installed | grep -E '^(flowdns|luci-app-flowdns|sing-box|xray-core) '
```
```sh
/usr/libexec/flowdns status
```
```sh
/usr/libexec/flowdns ready
```
```sh
ubus call service list '{"name":"flowdns"}'
```
```sh
cat /var/run/flowdns/state /var/run/flowdns/error /var/run/flowdns/health.json
```
```sh
tail -n 30 /var/run/flowdns/recovery.log /var/run/flowdns/startup.log /var/run/flowdns/core.log /var/run/flowdns/dnsmasq.log /var/run/flowdns/xray.log
```
```sh
cat /var/run/flowdns/job.json /var/run/flowdns/operation.json /var/run/flowdns/dns-switch.json
```

某些文件尚未创建/当前模式不用，报不存在不是根因。status 和日志可能含 LAN 地址/域名，分享前删去私人信息。不要公开 `/var/run/flowdns/xray.json`、完整节点 UCI 或运行备份。

LuCI 运行完整诊断或 SSH 执行 `/usr/libexec/flowdns diagnose`；长操作进行中应等它结束，不反复点 apply。基础依赖查看 `/usr/libexec/flowdns environment`，原生版本分别执行 `sing-box version`、`xray version`、`/usr/libexec/flowdns-dns --version`。

## 按症状定位

| 症状 | 重点证据 | 处理方向 |
| --- | --- | --- |
| 等待依赖、启动失败 | state/error/startup/recovery，time、SOCKS、规则、实际配置检查 | 先修复具体依赖；sing-box 版本提示本身不等于不兼容，不能只改版本字符串绕过功能检查 |
| SOCKS 握手失败 | 插件独立 SOCKS 是否启用，NOAUTH，显式节点，监听1080 | SSR 主服务器停用后“与全局相同”可能没有实际节点，改选具体节点 |
| SOCKS 握手成功但海外失败 | health 国外 DNS/出口、实际 SOCKS HTTPS、Xray错误 | ASSOCIATE 成功只证明接口接受，不代表出口或 UDP 实传 |
| Xray已监听仍失败 | 前端 DNS/nftset 日志、正式 DNS 应答、nft残留和策略路由 | 不要只凭 `Xray started` 排除其它层 |
| nftset/netlink cache resource busy | 私有 DNS版本、TCP并发/退出、错误尾部 | 旧 dnsmasq2.90 fork 竞态；使用包内2.93，检查没有误用系统前端；不要用 no-daemon掩盖问题 |
| 另一个操作正在执行 | job/operation 的操作、PID、耗时；原始recovery/error | 真忙先等待；不能仅凭提示认定死锁；不要 rm lock，不杀系统全部lua |
| 20260 表冲突 | ip数字JSON、地址族、实际规则归属 | 不盲目 flush；只有确认的 FlowDNS 自有条目才允许程序清理，外部条目先协调 |
| 国内外网页都解析失败 | 客户端DNS、Chrome安全DNS、系统dnsmasq死上游、前端 | Chrome使用系统DNS；SmartDNS停服务后确认dnsmasq没有仍指向它的死端口 |
| 国内通、443代理目标失败 | nft完整表、ss_spec、1234残留、Xray连接目的地址 | 先识别SSR/PassWall/OpenClash遗留规则；“UI停用”不等于内核表已清理 |
| 视频首开慢/反复波动 | QUIC拒绝日志、dns-switch、recovery、CPU、同目标对照 | Vision默认拒绝UDP443，透明模式auto可提前拒绝；查是否旧版DNS切换重启整组，不能先认定ISP QoS |
| 模式切换后部分应用打不开 | 客户端旧DNS缓存、旧Fake-IP、HTTPS/SVCB | flushDNS、完全重开浏览器/应用；透明模式应重新查询真实IP |
| `api.setup is not a function` | 实际菜单资源路径、两个包版本、旧浏览器缓存 | 同版本服务/UI；1.0资源v1，重载页面；必要时检查LuCI菜单缓存，不改数据平面 |
| 重启不接管 | init enabled、UCI enabled、等待原因 | 开机注册和分流开关都要开启；代理晚启动可等待退避，不必重复保存 |

只读路由与接管检查：

```sh
ip -4 rule show
```
```sh
ip -6 rule show
```
```sh
ip -N -j -4 route show table 20260
```
```sh
ip -N -j -6 route show table 20260
```
```sh
nft -a list ruleset
```

空表可能输出 Dump terminated，必须结合 JSON、退出状态和 rules 看，不把标准错误当成“已被占用”。nft输出可能包含网络地址；不要执行 `nft flush ruleset` 或无归属核对的 `ip route flush`。`nft monitor trace` 仅对受控测试流量临时加 nftrace，测试后删除自己加的规则；不在生产全量启用跟踪。

只测试独立 SOCKS 的路由器 SSH 命令：

```sh
curl --socks5-hostname 127.0.0.1:1080 --connect-timeout 10 --max-time 25 -I https://www.youtube.com/
```

它不经过 LAN 透明接管，成功不能代替客户端验收。

## 客户端验证（Windows CMD）

```bat
nslookup www.qq.com 192.168.10.1
```
```bat
nslookup www.google.com 192.168.10.1
```
```bat
curl.exe -4 -I --noproxy "*" --connect-timeout 10 --max-time 25 https://www.youtube.com/
```

Windows PowerShell同样逐条执行；不要将 `curl.exe` 贴到路由器 ash。浏览器设置使用系统DNS；Chrome指定Google安全DNS曾造成BAD_SECURE_CONFIG，用户改回系统DNS后恢复。SOCKS模式国外Fake-IP预期198.18.0.0/15、fc00::/18，透明模式预期真实IP；路由器本机nslookup拿到其它IP不一定是程序策略输出。无真实IPv6路由时，AAAA应答通过不意味着IPv6网站可用。

## DNS-only 更新排查

只适用透明模式。核对 dns-switch 的状态、原因、耗时和主备变化，dns-reload.log 与 recovery；成功只应改变 DNS 后端 PID，Xray、前端和 nft集合保持。非DNS政策有变化会完整重载，不能当成事务失效。失败回退应记录 rolled-back；连续回退先查候选与监听，不增加主备切换频率掩盖问题。

## 网络恢复顺序

1. 远程先保留证据与当前 SSH，停止新增试验。若升级包预设超时恢复，让独立守护执行已备份的恢复方案。
2. 能进入页面时关闭 FlowDNS 分流并保存；SSH应急停止可分别执行：

```sh
uci set flowdns.main.enabled=0
```
```sh
uci commit flowdns
```
```sh
/etc/init.d/flowdns stop
```

这只恢复系统原路径；如果此前SSR主透明代理已停用，不会自动恢复国外代理。需要经代理插件页面恢复原节点/主代理并保存，确认FlowDNS退出后再启用，避免双重接管。客户端缓存Fake-IP仍可能需清理。

3. 降级使用事先保存的同架构服务/UI包和原配置；先停FlowDNS再`opkg --force-downgrade install`指定旧包。恢复脚本和配置含私密数据，应放权限700目录，不公开归档。
4. 稳定后再修复和复测，不通过连续重启、删锁、替换DNS或全局清防火墙“碰运气”。

## 性能对照

同节点、同IP/CDN、有线客户端、同HTTP协议至少多轮下载，分别记录直接SOCKS和LAN路径。结合 `tools/flowdns-benchmark.py`、程序5秒CPU/内存采样及错误计数增长。YouTube connection speed 是播放器下载估算，会受缓存/分片/CDN影响；高低单个数字不能证明宽带限速。大量UDP、SQM、全局offload或MTU修改需另安排受控负载实验，当前发布没有为猜测的ISP QoS批量改这些配置。

## 同一桥多个IPv4地址时只有UDP DNS超时

先用受控UDP客户端的recvfrom或抓包核对实际应答源IP/端口。测试中发现sing-box通配监听在临时附加子网选用了次地址，应答以16553发出、没有匹配原53连接；TCP/正式自检与主LAN仍正常。不要把此现象直接当成上游DNS坏了。核对目的地址、桥主/次地址、到客户端的路由首选源和conntrack反向元组；额外子网需要单独适配和验收。测试仅调整专用测试路由，不建议盲目更改生产主LAN地址。
