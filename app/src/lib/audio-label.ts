export type AudioKind = 'recording' | 'script' | 'none'

export function audioKind(audio?: { url?: string; transcript?: string; browserTts?: boolean }): AudioKind {
  if (audio?.url?.trim()) return 'recording'
  return audio?.browserTts && audio.transcript?.trim() ? 'script' : 'none'
}

export function audioMinutes(seconds?: number | null): number | null {
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0
    ? Math.max(1, Math.round(seconds / 60)) : null
}

export function audioLabel(kind: AudioKind, seconds?: number | null, form: 'short' | 'long' = 'short'): string {
  if (kind === 'none') return ''
  if (form === 'short') return kind === 'recording' ? '录音讲解' : '朗读稿'
  const label = kind === 'recording' ? '录音讲解' : '讲解稿 · 浏览器朗读'
  const minutes = audioMinutes(seconds)
  return minutes === null ? label : `${label} · 约 ${minutes} 分钟`
}
