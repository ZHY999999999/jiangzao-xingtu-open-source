import { useEffect, useId, useRef, useState } from 'react'
import { IconChevronUp, IconFileText, IconLoader2, IconPlayerPauseFilled, IconPlayerPlayFilled, IconRotateClockwise } from '@tabler/icons-react'
import { audioKind, audioLabel } from '../lib/audio-label'
import { jumpTo } from './CompanyDetailParts'
import type { AudioKind } from '../lib/audio-label'
import '../styles/company-audio.css'

export type CompanyAudioAsset = {
  url?: string
  transcript: string
  sourceIds: string[]
  contentVersion: string
  durationSeconds?: number | null
  browserTts?: boolean
}

type CompanyAudioProps = {
  companyCode: string
  companyName: string
  audio?: CompanyAudioAsset
  onSources?: (ids: string[]) => void
  nextCompany?: { code: string; name: string; audio: AudioKind; durationSeconds: number | null }
  quickReadId?: string
}

function timeLabel(seconds: number) {
  const safe = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, '0')}`
}

function safeAudioUrl(value: string | undefined) {
  if (!value?.trim()) return ''
  try {
    const url = new URL(value.trim(), typeof window === 'undefined' ? 'https://localhost/' : window.location.href)
    return url.protocol === 'https:' || url.protocol === 'http:' ? value.trim() : ''
  } catch { return '' }
}

/** Remount on company or recording changes so a previous recording cannot keep playing. */
export default function CompanyAudio(props: CompanyAudioProps) {
  const rawUrl = safeAudioUrl(props.audio?.url)
  const versionedUrl = rawUrl ? new URL(rawUrl, window.location.href) : null
  if (versionedUrl && props.audio?.contentVersion) versionedUrl.searchParams.set('v', props.audio.contentVersion)
  const url = versionedUrl?.href || ''
  const audio = props.audio ? { ...props.audio, url } : undefined
  if (!audio || audioKind(audio) === 'none') return null
  return <CompanyAudioPlayer key={`${props.companyCode}:${url}:${audio.contentVersion}`} {...props} audio={audio} />
}

function CompanyAudioPlayer({ companyCode, companyName, audio, onSources, nextCompany, quickReadId = 'cq-title' }: CompanyAudioProps & { audio: CompanyAudioAsset }) {
  const kind = audioKind(audio)
  const browserTts = kind === 'script'
  const mediaRef = useRef<HTMLAudioElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)
  const requestRef = useRef(0)
  const playbackWanted = useRef(false)
  const expandedRef = useRef(false)
  const [expanded, setExpanded] = useState(false)
  const [transcriptOpen, setTranscriptOpen] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState('')
  const [position, setPosition] = useState(0)
  const [duration, setDuration] = useState(audio.durationSeconds ?? 0)
  const [seekable, setSeekable] = useState(false)
  const [speed, setSpeed] = useState(1)
  const controlsId = useId()
  const transcriptId = useId()
  const statusId = useId()

  useEffect(() => {
    const media = mediaRef.current
    return () => {
      requestRef.current += 1
      playbackWanted.current = false
      if (browserTts) { utteranceRef.current = null; window.speechSynthesis?.cancel() }
      if (media) {
        media.pause()
        media.removeAttribute('src')
        media.load()
      }
    }
  }, [browserTts])

  function pause() {
    requestRef.current += 1
    playbackWanted.current = false
    if (browserTts) window.speechSynthesis?.pause()
    else mediaRef.current?.pause()
    setPlaying(false)
    setLoading(false)
  }

  async function play() {
    const media = mediaRef.current
    if (!media && !browserTts) return
    const request = ++requestRef.current
    playbackWanted.current = true
    setError('')
    setLoading(true)
    setEnded(false)
    if (browserTts) {
      const synthesis = window.speechSynthesis
      if (!synthesis) {
        setError('当前浏览器不支持语音朗读。')
        setLoading(false)
        return
      }
      if (synthesis.paused && utteranceRef.current) {
        synthesis.resume()
        setPlaying(true)
        setLoading(false)
        return
      }
      const utterance = new SpeechSynthesisUtterance(audio.transcript)
      utterance.lang = 'zh-CN'
      utterance.rate = speed
      utterance.pitch = 1
      utteranceRef.current = utterance
      utterance.onstart = () => {
        if (utteranceRef.current !== utterance || !playbackWanted.current) return
        setPlaying(true)
        setLoading(false)
      }
      utterance.onend = () => {
        if (utteranceRef.current !== utterance) return
        utteranceRef.current = null
        if (!expandedRef.current) return
        playbackWanted.current = false
        setPlaying(false)
        setLoading(false)
        setEnded(true)
      }
      utterance.onerror = () => {
        if (utteranceRef.current !== utterance) return
        utteranceRef.current = null
        if (!expandedRef.current) return
        playbackWanted.current = false
        setPlaying(false)
        setLoading(false)
        setError('浏览器语音朗读暂时失败，请重试。')
      }
      synthesis.cancel()
      synthesis.speak(utterance)
      return
    }
    // No src is attached before this user gesture; preload="none" is not the only safeguard.
    if (!media!.hasAttribute('src') || media!.error) {
      media!.src = audio.url || ''
      media!.load()
    }
    if (media!.ended) media!.currentTime = 0
    media!.playbackRate = speed
    try {
      await media!.play()
      if (request === requestRef.current) {
        setPlaying(true)
        setLoading(false)
      }
    } catch (cause) {
      if (request !== requestRef.current) return
      playbackWanted.current = false
      setPlaying(false)
      setLoading(false)
      setError(cause instanceof DOMException && cause.name === 'NotAllowedError'
        ? '播放被浏览器暂停了，请再点一次播放。'
        : '音频暂时无法播放，请重试。')
    }
  }

  function togglePlayback() {
    expandedRef.current = true
    setExpanded(true)
    if (playing || loading) pause()
    else void play()
  }

  function collapse() {
    pause()
    expandedRef.current = false
    // Pause preserves progress; callbacks cannot restore ended/error while collapsed.
    setEnded(false)
    setError('')
    setExpanded(false)
    setTranscriptOpen(false)
    triggerRef.current?.focus()
  }

  function updateMetadata() {
    const media = mediaRef.current
    if (!media) return
    const hasDuration = Number.isFinite(media.duration) && media.duration > 0
    if (hasDuration) setDuration(media.duration)
    setSeekable(hasDuration)
  }

  const playLabel = loading ? '取消语音加载' : playing ? '暂停公司语音' : error ? '重试播放公司语音' : ended ? '重新播放公司语音' : `播放${companyName}语音`
  const entryDescription = audioLabel(kind, duration, 'long')
  const buttonLabel = !expanded
    ? `听这家公司的讲解，${entryDescription}${error || ended ? `，${playLabel}` : ''}` : playLabel
  const status = error || (loading ? '正在加载语音…' : ended ? '播放结束' : browserTts ? '使用浏览器语音朗读' : '')
  const safeDuration = Number.isFinite(duration) && duration > 0 ? duration : 0
  const progress = safeDuration ? Math.min(position / safeDuration * 100, 100) : 0

  return <div className={`company-audio${expanded ? ' is-expanded' : ''}`} data-company-code={companyCode} data-content-version={audio.contentVersion}>
    {!browserTts && <audio ref={mediaRef} preload="none" aria-hidden="true"
      onLoadedMetadata={updateMetadata} onDurationChange={updateMetadata}
      onTimeUpdate={event => setPosition(Number.isFinite(event.currentTarget.currentTime) ? Math.max(0, event.currentTarget.currentTime) : 0)}
      onPlaying={event => {
        if (!playbackWanted.current) { event.currentTarget.pause(); return }
        setPlaying(true); setLoading(false); setEnded(false)
      }}
      onWaiting={() => { if (playbackWanted.current) setLoading(true) }}
      onPause={() => { setPlaying(false); setLoading(false) }}
      onEnded={() => { if (!expandedRef.current) return; playbackWanted.current = false; setPlaying(false); setLoading(false); setEnded(true) }}
      onError={() => { if (!expandedRef.current) return; playbackWanted.current = false; setLoading(false); setPlaying(false); setSeekable(false); setError('音频暂时无法播放，请重试。') }}
    />}
    <div className="ca-control-row">
      <button ref={triggerRef} type="button" className="ca-play" onClick={togglePlayback}
        aria-label={buttonLabel} title={buttonLabel} aria-expanded={expanded} aria-controls={controlsId}
        aria-describedby={status ? statusId : undefined}>
        <span className="ca-play-disc">{loading ? <IconLoader2 className="ca-spinner" size={16} aria-hidden="true" />
          : playing ? <IconPlayerPauseFilled size={13} aria-hidden="true" />
            : error || ended ? <IconRotateClockwise size={16} aria-hidden="true" />
              : <IconPlayerPlayFilled size={13} aria-hidden="true" />}</span>
        {!expanded && <span className="ca-entry"><strong>听这家公司的讲解</strong><small>{entryDescription}</small></span>}
      </button>
      <div id={controlsId} className="ca-controls" hidden={!expanded}>
        <div className="ca-seek">
          <input type="range" min={0} max={safeDuration || 1} step={0.1} value={Math.min(position, safeDuration || 0)}
            disabled={!seekable} aria-label="播放进度" aria-valuetext={`${timeLabel(position)}，共 ${timeLabel(safeDuration)}`}
            style={{ backgroundSize: `${progress}% 4px, 100% 4px` }}
            onChange={event => {
              const media = mediaRef.current
              if (!media || !seekable) return
              const next = Number(event.target.value)
              if (!Number.isFinite(next)) return
              const target = Math.max(0, Math.min(next, safeDuration))
              media.currentTime = target
              setPosition(target)
              setEnded(false)
            }} />
          <span className="ca-time" aria-hidden="true">{timeLabel(position)}<span> / </span>{timeLabel(safeDuration)}</span>
        </div>
        <label className="ca-speed"><span className="ca-sr-only">播放速度</span><select value={speed} aria-label="播放速度"
          onChange={event => {
            const next = Number(event.target.value)
            setSpeed(next)
            if (mediaRef.current) mediaRef.current.playbackRate = next
            if (utteranceRef.current) utteranceRef.current.rate = next
          }}>
          {[0.75, 1, 1.25, 1.5, 2].map(rate => <option key={rate} value={rate}>{rate}×</option>)}
        </select></label>
        {audio.transcript.trim() && <button type="button" className="ca-text-toggle" onClick={() => setTranscriptOpen(value => !value)}
          aria-expanded={transcriptOpen} aria-controls={transcriptId}><IconFileText size={16} aria-hidden="true" /><span>文稿</span></button>}
        <button type="button" className="ca-collapse" aria-label="收起播放器并暂停" title="收起" onClick={collapse}>
          <IconChevronUp size={17} aria-hidden="true" /></button>
      </div>
    </div>
    <p id={statusId} className={`ca-status${error ? ' is-error' : ''}`} role="status" aria-live="polite" hidden={!expanded || !status}>{status}</p>
    {expanded && ended && <div className="ca-next">
      <span className="ca-next-title">接着读</span>
      <div className="ca-next-actions">
        <a className="ca-next-quickread" href={`#${quickReadId}`} onClick={event => jumpTo(event, quickReadId)}>查看文字内容 ↓</a>
        {onSources && audio.sourceIds.length > 0 && <button type="button" className="ca-next-sources" onClick={() => onSources([...audio.sourceIds])}>查看讲解依据 · {audio.sourceIds.length} 条</button>}
        {nextCompany && <a className="ca-next-company" href={`#/company/${nextCompany.code}`}>下一家：{nextCompany.name}{nextCompany.audio !== 'none' && ` · ${audioLabel(nextCompany.audio)}`} →</a>}
      </div>
    </div>}
    {expanded && transcriptOpen && <div className="ca-transcript" id={transcriptId}>
      <div className="ca-transcript-heading"><span>语音文稿</span>{onSources && audio.sourceIds.length > 0 && <button type="button" onClick={() => onSources([...audio.sourceIds])}>查看依据</button>}</div>
      {audio.transcript.trim().split(/\n\s*\n/).map((paragraph, index) => <p key={index}>{paragraph}</p>)}
    </div>}
  </div>
}
