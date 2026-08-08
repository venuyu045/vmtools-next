/* eslint-disable */
/**
 * 下载 Google Fonts 中文分片（Noto Serif SC / Noto Sans SC）自托管
 * - 解析 css2 接口返回的所有 @font-face（含 unicode-range）
 * - 下载 woff2 到 frontend/public/fonts/
 * - 生成 frontend/src/styles/fonts.css（相对 URL /fonts/xxx.woff2）
 * 用法：node download-zh-fonts.js
 */
const https = require('https')
const fs = require('fs')
const path = require('path')

const FONT_DIR = path.join(__dirname, '..', 'frontend', 'public', 'fonts')
const OUT_CSS = path.join(__dirname, '..', 'frontend', 'src', 'styles', 'fonts.css')

const FAMILIES = [
  { family: 'Noto Serif SC', weights: [400, 600] },
  { family: 'Noto Sans SC', weights: [400, 500] },
]

const UA_WOFF2 = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

function get(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': UA_WOFF2, 'Accept-Encoding': 'identity' } }, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        res.resume()
        return get(res.headers.location).then(resolve, reject)
      }
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve(Buffer.concat(chunks)))
    })
    req.on('error', reject)
  })
}

function parseFaceBlocks(css) {
  const blocks = []
  const re = /@font-face\s*{([^}]+)}/g
  let m
  while ((m = re.exec(css)) !== null) {
    const body = m[1]
    const getVal = (prop) => {
      const pm = body.match(new RegExp(prop + '\\s*:\\s*([^;]+);'))
      return pm ? pm[1].trim() : ''
    }
    const family = getVal('font-family').replace(/['"]/g, '')
    const weight = getVal('font-weight')
    const urls = [...body.matchAll(/url\(([^)]+)\)\s*format\('woff2'\)/g)].map((u) => u[1])
    const urange = getVal('unicode-range')
    if (urls.length && urange) {
      blocks.push({ family, weight, url: urls[0], urange })
    }
  }
  return blocks
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': UA_WOFF2, 'Accept-Encoding': 'identity' } }, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        res.resume()
        return download(res.headers.location, dest).then(resolve, reject)
      }
      const ws = fs.createWriteStream(dest)
      res.pipe(ws)
      ws.on('finish', () => ws.close(resolve))
      ws.on('error', reject)
    })
    req.on('error', reject)
  })
}

async function main() {
  fs.mkdirSync(FONT_DIR, { recursive: true })
  const all = []
  for (const f of FAMILIES) {
    for (const w of f.weights) {
      const url = `https://fonts.googleapis.com/css2?family=${f.family.replace(/ /g, '+')}:wght@${w}&display=swap`
      console.log(`[fetch] ${f.family} ${w}`)
      const css = await get(url)
      const blocks = parseFaceBlocks(css.toString())
      console.log(`  -> ${blocks.length} faces`)
      all.push(...blocks)
    }
  }

  const cssLines = []
  let count = 0
  const CONC = 10
  const queue = [...all]
  async function worker() {
    while (queue.length) {
      const b = queue.shift()
      const slug = `${b.family.replace(/[^a-zA-Z0-9]/g, '')}-${b.weight}-${count++}`
      const filename = `${slug}.woff2`
      const dest = path.join(FONT_DIR, filename)
      try {
        await download(b.url, dest)
        const size = fs.statSync(dest).size
        cssLines.push(
          `@font-face{font-family:'${b.family}';font-style:normal;font-weight:${b.weight};font-display:swap;src:url('/fonts/${filename}') format('woff2');unicode-range:${b.urange}}`
        )
        if (count % 40 === 0) console.log(`  downloaded ${count}/${all.length}`)
      } catch (e) {
        console.error(`  FAIL ${filename}: ${e.message}`)
      }
    }
  }
  await Promise.all(Array.from({ length: CONC }, worker))

  fs.writeFileSync(OUT_CSS, `/* 自托管中文字体（Google Fonts woff2 分片，国内稳定加载）\n   生成脚本：scripts/download-zh-fonts.js\n   终端字体（JetBrains Mono）保持原样不受影响 */\n${cssLines.join('\n')}\n`)
  console.log(`DONE: ${cssLines.length} faces -> ${FONT_DIR}`)
}

main().catch((e) => { console.error(e); process.exit(1) })
