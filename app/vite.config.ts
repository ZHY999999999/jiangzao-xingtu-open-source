import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { compactCompanyMemberships } from './src/lib/related-companies.js'
import { validateSevenQuestions } from './src/lib/company-seven-questions'
import { validateCompanyOverview } from './src/lib/company-overview'
import { verifyAssembly, sameAssembly, productRevision, sha } from './scripts/catalogue-build'

const appRoot = dirname(fileURLToPath(import.meta.url))
// Read-only frozen public tree; Python assembly gate hashes every byte under public/...
const publicRoot = resolve(process.env.ATLAS_PUBLIC_ROOT || resolve(appRoot, 'public'))
export default defineConfig(() => {
  // This always calls the current read-only approval gate. A saved receipt cannot enable a build.
  const assembly = verifyAssembly(appRoot)
  const catalogue = assembly.catalogue
  const history = JSON.parse(readFileSync(resolve(appRoot, 'release-history.json'), 'utf8'))
  const packageVersion = JSON.parse(readFileSync(resolve(appRoot, 'package.json'), 'utf8')).version
  if (!history.length || history[0].version !== packageVersion || new Set(history.map((entry: {version: string}) => entry.version)).size !== history.length || history.some((entry: {version: string; date: string; changes: string[]}) => !/^\d+\.\d+\.\d+$/.test(entry.version) || !/^\d{4}-\d{2}-\d{2}$/.test(entry.date) || !entry.changes?.length || entry.changes.some(change => typeof change !== 'string' || !change.trim()))) throw new Error('Version and release history differ')
  const siteRelease = { ...history[0], revision: productRevision(appRoot, assembly, publicRoot), history,
    experimental: false, releaseStatus: assembly.approvalMode === 'public-snapshot' ? 'public-snapshot-unpublished' : 'release-candidate', catalogueSha256: catalogue.catalogueSha256,
    companyIndexSha256: catalogue.index.sha256, companySnapshotId: catalogue.index.snapshotId }
  const evidence = JSON.parse(readFileSync(resolve(appRoot, 'src/lib/evidence-data.json'), 'utf8'))
  const memberships = compactCompanyMemberships(evidence)
  const coverage = {asOf: catalogue.index.asOf, ...catalogue.coverage,
    editorial: catalogue.counts.readable, reviewedSeven: catalogue.counts.reviewedSeven, reviewedOverview: catalogue.counts.reviewedOverview ?? 0, industries: memberships.industries.length}
  for (const entry of catalogue.entries.filter(e => e.kind === 'seven-questions')) {
    validateSevenQuestions(JSON.parse(readFileSync(resolve(appRoot, `content/company-seven-questions/${entry.code}.json`), 'utf8')), entry.code)
  }
  const modules = new Map<string, string>()
  for (const entry of catalogue.entries) {
    const folder = entry.kind === 'seven-questions' ? 'company-seven-questions' : entry.kind === 'business-overview' ? 'company-overview' : 'company-editorial'
    modules.set(resolve(appRoot, `content/${folder}/${entry.code}.json`).replaceAll('\\', '/'), entry.contentSha256)
    if (entry.overview) {
      const path = resolve(appRoot, `content/company-overview/${entry.code}.json`)
      validateCompanyOverview(JSON.parse(readFileSync(path, 'utf8')), entry.code)
      if (sha(readFileSync(path)) !== entry.overview.contentSha256) throw new Error('Overview metadata differs from exact selected content')
      modules.set(path.replaceAll('\\', '/'), entry.overview.contentSha256)
    }
  }
  const loaded = new Set<string>()
  const publicBytes = JSON.stringify(catalogue, null, 2) + '\n'
  let outDir = resolve(appRoot, 'dist')
  let build = false
  let generated = false
  const selectedChunks: {fileName: string; sha256: string; source: string}[] = []
  return {
    publicDir: publicRoot,
    cacheDir: resolve(appRoot, '.vite-cache'),
    define: { __SITE_RELEASE__: JSON.stringify(siteRelease) },
    plugins: [react(), {
      name: 'single-content-catalogue', enforce: 'pre' as const,
      configResolved(config) { outDir = config.build.outDir; build = config.command === 'build' },
      resolveId(id) {
        if (['virtual:company-content-catalogue', 'virtual:company-memberships', 'virtual:company-industries', 'virtual:editorial-catalog', 'virtual:site-coverage'].includes(id)) return '\0' + id
      },
      load(id) {
        if (id === '\0virtual:company-content-catalogue') return `export default ${JSON.stringify(catalogue)}`
        if (id === '\0virtual:editorial-catalog') return `import catalogue from 'virtual:company-content-catalogue'; export default catalogue.entries`
        if (id === '\0virtual:site-coverage') return `import catalogue from 'virtual:company-content-catalogue'; export default {asOf: catalogue.index.asOf, ...catalogue.coverage, editorial: catalogue.counts.readable, reviewedSeven: catalogue.counts.reviewedSeven, reviewedOverview: catalogue.counts.reviewedOverview ?? 0, industries: ${coverage.industries}}`
        if (id === '\0virtual:company-memberships') return `export default ${JSON.stringify(memberships)}`
        if (id === '\0virtual:company-industries') return `export default ${JSON.stringify(memberships.industries)}`
      },
      transform(_code, id) {
        const name = id.replaceAll('\\', '/')
        if (modules.has(name)) {
          if (sha(readFileSync(name)) !== modules.get(name)) throw new Error('Selected content changed during module loading')
          loaded.add(name)
        }
      },
      transformIndexHtml() { return [{tag: 'meta', attrs: {name: 'application-version', content: `${siteRelease.version}+${siteRelease.revision}`}, injectTo: 'head' as const}] },
      generateBundle(_options, bundle) {
        sameAssembly(assembly, verifyAssembly(appRoot))
        if (modules.size !== loaded.size) throw new Error('Selected content is not represented by actual loaded modules')
        const eager = new Set<string>()
        const visit = (name: string) => {
          if (eager.has(name)) return
          eager.add(name)
          const chunk = bundle[name]
          if (chunk?.type === 'chunk') chunk.imports.forEach(visit)
        }
        Object.values(bundle).filter(value => value.type === 'chunk' && value.isEntry).forEach(value => visit(value.fileName))
        for (const name of modules.keys()) {
          const chunks = Object.values(bundle).filter(value => value.type === 'chunk' && name in value.modules)
          if (chunks.length !== 1 || chunks[0].type !== 'chunk' || chunks[0].isEntry || !chunks[0].isDynamicEntry || eager.has(chunks[0].fileName)) throw new Error('Selected content must occur once in a lazy content chunk')
          selectedChunks.push({fileName: chunks[0].fileName, sha256: sha(chunks[0].code), source: name.slice(appRoot.replaceAll('\\', '/').length + 1)})
        }
        this.emitFile({type: 'asset', fileName: 'content-catalogue.json', source: publicBytes})
        this.emitFile({type: 'asset', fileName: 'version.json', source: JSON.stringify(siteRelease, null, 2) + '\n'})
        generated = true
      },
      closeBundle() {
        if (!build || !generated) return
        sameAssembly(assembly, verifyAssembly(appRoot))
        const target = resolve(appRoot, outDir)
        if (readFileSync(resolve(target, 'content-catalogue.json'), 'utf8') !== publicBytes ||
            sha(readFileSync(resolve(target, 'data/companies/index.json'))) !== catalogue.index.sha256) {
          throw new Error('Written public catalogue or index differs; build output is not accepted')
        }
        for (const chunk of selectedChunks) if (sha(readFileSync(resolve(target, chunk.fileName))) !== chunk.sha256) throw new Error('Written lazy content chunk differs')
        mkdirSync(resolve(appRoot, '.catalogue-evidence'), {recursive: true})
        writeFileSync(resolve(appRoot, '.catalogue-evidence/assembly.json'), JSON.stringify({
          ...assembly, siteRelease, selectedChunks, checkedAt: new Date().toISOString(), noDeploy: true, readyForPublication: false,
        }, null, 2) + '\n')
      },
    }],
  }
})
