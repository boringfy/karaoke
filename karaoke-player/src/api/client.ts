export const SERVER_BASE = 'http://127.0.0.1:8787'
export const API_BASE = `${SERVER_BASE}/api/v1`

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(`${status}: ${detail}`)
    this.status = status
    this.detail = detail
  }
}

/** Fired (with false) when a request fails at the network level, so the app
 * can flip into the "server unreachable" state without prop drilling. */
type ReachabilityListener = (reachable: boolean) => void
let reachabilityListener: ReachabilityListener | null = null
export function onReachabilityChange(listener: ReachabilityListener) {
  reachabilityListener = listener
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch (err) {
    reachabilityListener?.(false)
    throw new ApiError(0, 'karaoke-server is unreachable')
  }
  reachabilityListener?.(true)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (body?.detail) detail = JSON.stringify(body.detail)
    } catch {
      // non-JSON error body
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** Multipart upload with progress callback (fetch has no upload progress). */
export function uploadFile<T>(
  path: string,
  file: File,
  extraFields: Record<string, string>,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}${path}`)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as T)
        } catch {
          resolve(undefined as T)
        }
      } else {
        let detail = xhr.statusText
        try {
          const body = JSON.parse(xhr.responseText)
          if (typeof body?.detail === 'string') detail = body.detail
        } catch {
          // ignore
        }
        reject(new ApiError(xhr.status, detail))
      }
    }
    xhr.onerror = () => {
      reachabilityListener?.(false)
      reject(new ApiError(0, 'karaoke-server is unreachable'))
    }
    const form = new FormData()
    for (const [k, v] of Object.entries(extraFields)) form.append(k, v)
    form.append('file', file)
    xhr.send(form)
  })
}
