import { readFileSync, writeFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const [kind, ...words] = process.argv.slice(2)
const note = words.join(' ').trim()
if (!['patch', 'minor', 'major'].includes(kind) || !note) {
  throw new Error('用法：npm run version:patch -- "本次更新说明"（也可 version:minor / version:major）')
}
const read = name => JSON.parse(readFileSync(resolve(root, name), 'utf8'))
const history = read('release-history.json')
const pkg = read('package.json')
const lock = read('package-lock.json')
if (history[0]?.version !== pkg.version || lock.version !== pkg.version || lock.packages[''].version !== pkg.version) {
  throw new Error('已有版本不一致，请先核对 release-history.json、package.json 和 package-lock.json。')
}
const parts = pkg.version.split('.').map(Number)
const index = { major: 0, minor: 1, patch: 2 }[kind]
parts[index] += 1
for (let i = index + 1; i < 3; i++) parts[i] = 0
const version = parts.join('.')
const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
history.unshift({ version, date, changes: [note] })
pkg.version = lock.version = lock.packages[''].version = version
for (const [name, data] of [['package.json', pkg], ['package-lock.json', lock], ['release-history.json', history]]) {
  writeFileSync(resolve(root, name), JSON.stringify(data, null, 2) + '\n')
}
console.log(`网站版本已更新为 v${version}。请构建、验证并发布；此操作本身不会更新正式网站。`)
