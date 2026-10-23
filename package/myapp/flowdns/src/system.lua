-- SPDX-License-Identifier: GPL-3.0-or-later
local fs, nixio, json = require 'nixio.fs', require 'nixio', require 'luci.jsonc'
local M = {}
function M.now() local seconds, micros = nixio.gettimeofday(); return seconds + (micros or 0) / 1000000 end
function M.read(path) return fs.readfile(path) or '' end
function M.decode(path) return json.parse(M.read(path)) end
function M.write(path, value)
	local tmp = path .. '.' .. nixio.getpid() .. '.new'
	assert(fs.writefile(tmp, type(value) == 'table' and json.stringify(value) or tostring(value)), '无法写入 ' .. path)
	assert(fs.rename(tmp, path), '无法替换 ' .. path)
end
function M.lock(path)
	local fd = assert(nixio.open(path, 'w', 600), '无法打开任务锁 ' .. path)
	if not fd:lock('tlock') then fd:close(); return nil end
	return fd -- Never unlink this inode. The kernel releases it on exit/crash.
end
function M.tail(path, size)
	local f = io.open(path, 'r')
	if not f then return '' end
	local length = f:seek('end') or 0
	f:seek('set', math.max(0, length - size))
	local s = f:read('*a') or ''; f:close(); return s
end
function M.ticks(pid)
	local s = M.read('/proc/' .. pid .. '/stat'):match('^%d+ %b() (.*)')
	if not s then return nil end
	local fields = {}; for v in s:gmatch('%S+') do fields[#fields + 1] = v end
	return tonumber(fields[20]), (tonumber(fields[12]) or 0) + (tonumber(fields[13]) or 0)
end
function M.alive(job)
	return job and job.pid and job.ticks and M.ticks(job.pid) == job.ticks
end
function M.core_pid(run)
	local pid = tonumber(M.read(run .. '/core.pid'):match('^%s*(%d+)'))
	if pid and pid > 1 and nixio.kill(pid, 0) then return pid end
end
function M.job(run)
	local job = M.decode(run .. '/job.json')
	if job and (job.state == 'running' or job.state == 'queued') then
		local uptime = tonumber(M.read('/proc/uptime'):match('^[%d.]+'))
		local age = uptime and job.reserved_uptime and (uptime - job.reserved_uptime) or (os.time() - (job.started or 0))
		local pending = job.state == 'queued' and age >= 0 and age < 15
		if not pending and not M.alive(job) then
			job.state, job.finished, job.result = 'error', os.time(), { ok = false, message = '任务进程已退出，请重新执行；运行锁已由内核释放。' }
			M.write(run .. '/job.json', job)
		end
	end
	return job
end
function M.query(port, domain, tcp)
	local labels = {}
	for label in domain:gmatch('[^.]+') do labels[#labels + 1] = string.char(#label) .. label end
	local id = nixio.getpid() % 65536
	local packet = string.char(math.floor(id / 256), id % 256) .. '\1\0\0\1\0\0\0\0\0\0' .. table.concat(labels) .. '\0\0\1\0\1'
	local s = nixio.socket('inet', tcp and 'stream' or 'dgram')
	if not s then return false, '无法创建 DNS 检测连接。' end
	s:setopt('socket', 'rcvtimeo', 4); s:setopt('socket', 'sndtimeo', 4)
	local function receive(n)
		local out = ''
		while #out < n do local part = s:recv(n - #out); if not part or part == '' then return nil end; out = out .. part end
		return out
	end
	local reply
	if s:connect('127.0.0.1', port) then
		local request = tcp and (string.char(math.floor(#packet / 256), #packet % 256) .. packet) or packet
		if s:send(request) == #request then
			if tcp then local len = receive(2); if len then reply = receive(len:byte(1) * 256 + len:byte(2)) end
			else reply = s:recv(4096) end
		end
	end
	s:close()
	local ok = reply and #reply >= 12 and reply:sub(1, 2) == packet:sub(1, 2) and reply:byte(3) >= 128
		and reply:byte(4) % 16 == 0 and reply:byte(7) * 256 + reply:byte(8) > 0
	return ok and true or false, ok and '正式核心返回有效 DNS 应答。' or '正式核心 DNS 查询超时或应答无效。'
end
function M.metrics()
	local cpus, processes = {}, {}
	for line in M.read('/proc/stat'):gmatch('[^\n]+') do
		local name, values = line:match('^(cpu%d*)%s+(.*)')
		if name then local v = {}; for n in values:gmatch('%d+') do v[#v + 1] = tonumber(n) end
			local total = 0; for i = 1, math.min(#v, 8) do total = total + v[i] end
			cpus[name] = { total = total, idle = (v[4] or 0) + (v[5] or 0) }
		end
	end
	for pid in fs.dir('/proc') do
		if pid:match('^%d+$') then
			local name = M.read('/proc/' .. pid .. '/comm'):match('%S+')
			if name == 'sing-box' or name == 'xray' or name == 'v2ray' or name == 'flowdns-dns' or (name or ''):match('^ss[r%-]') then
				local start, ticks = M.ticks(pid)
				processes[#processes + 1] = { pid = tonumber(pid), name = name, start = start, ticks = ticks,
					rss_kb = tonumber(M.read('/proc/' .. pid .. '/status'):match('VmRSS:%s+(%d+)')) or 0 }
			end
		end
	end
	return { time = os.time(), uptime = tonumber(M.read('/proc/uptime'):match('^[%d.]+')), cpus = cpus, processes = processes,
		available_kb = tonumber(M.read('/proc/meminfo'):match('MemAvailable:%s+(%d+)')) }
end
return M
