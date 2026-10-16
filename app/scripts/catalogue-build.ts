import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { ContentCatalogue } from '../src/lib/content-catalogue'

export type Assembly = {
  status: string; catalogue: ContentCatalogue
  applicationInputs: Record<string, string>
  approvalBindingId: string | null
  [key: string]: unknown
}
export const sha = (body: string | Buffer) => createHash('sha256').update(body).digest('hex')
export function verifyAssembly(app: string): Assembly {
  const result = spawnSync(process.env.PYTHON || 'python', ['-B', resolve(app, 'scripts/verify_catalogue.py')], {
    cwd: app, encoding: 'utf8', windowsHide: true, maxBuffer: 16 * 1024 * 1024,
  })
  if (result.error || result.status !== 0) throw new Error(`Catalogue approval gate refused: ${result.stdout || result.stderr || result.error}`)
  const receipt = JSON.parse(result.stdout) as Assembly
  if (receipt.status !== 'verified_local_assembly_inputs') throw new Error('Catalogue assembly is not verified')
  return receipt
}
export function sameAssembly(before: Assembly, after: Assembly) {
  if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error('Catalogue/application/approval inputs changed during build; output is not accepted')
}
export function productRevision(app: string, assembly: Assembly, publicRoot = resolve(app, 'public')): string {
  const digest = createHash('sha256')
  const names = Object.keys(assembly.applicationInputs).filter(name =>
    !name.startsWith('public/data/') || name === 'public/data/companies/index.json').sort()
  for (const name of names) digest.update(name).update('\0').update(readFileSync(name.startsWith('public/') ? resolve(publicRoot, name.slice(7)) : resolve(app, name))).update('\0')
  // No checkedAt, queue hash, reviewer identity or global approval binding in product identity.
  digest.update('content-catalogue\0').update(assembly.catalogue.catalogueSha256)
  return digest.digest('hex').slice(0, 12)
}
