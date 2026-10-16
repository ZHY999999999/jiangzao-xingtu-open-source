import { useSyncExternalStore } from 'react'

/** 订阅一个媒体查询；混合设备插拔鼠标时会随之更新。服务端或无 matchMedia 的环境返回 false。 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    onChange => {
      if (typeof window === 'undefined' || !window.matchMedia) return () => {}
      const media = window.matchMedia(query)
      media.addEventListener('change', onChange)
      return () => media.removeEventListener('change', onChange)
    },
    () => typeof window !== 'undefined' && Boolean(window.matchMedia?.(query).matches),
    () => false,
  )
}
