#!/usr/bin/env node
/* 临时诊断：测试多个 yggdrasil 认证源（Littleskin / prinzeugen） */
const https = require('https');

function post(url, body) {
  return new Promise((resolve) => {
    const data = JSON.stringify(body);
    const u = new URL(url);
    const req = https.request({
      hostname: u.hostname, port: u.port || 443, path: u.pathname,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
      timeout: 15000,
    }, (res) => {
      let buf = '';
      res.on('data', (c) => { buf += c; });
      res.on('end', () => resolve({ status: res.statusCode, body: buf.slice(0, 600) }));
    });
    req.on('error', (e) => resolve({ status: 0, body: 'ERR ' + e.message }));
    req.on('timeout', () => { req.destroy(); resolve({ status: 0, body: 'TIMEOUT' }); });
    req.write(data);
    req.end();
  });
}

(async () => {
  const creds = { username: '3535917632@qq.com', password: 'jxy080405', clientToken: 'probe' };
  console.log('--- littleskin.cn/api/yggdrasil/authserver ---');
  console.log(JSON.stringify(await post('https://littleskin.cn/api/yggdrasil/authserver/authenticate', creds)));
  console.log('--- skin.prinzeugen.net/api/yggdrasil/authserver (retry) ---');
  console.log(JSON.stringify(await post('https://skin.prinzeugen.net/api/yggdrasil/authserver/authenticate', creds)));
})();