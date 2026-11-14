import type { components } from './generated'

const baseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export type HealthResponse = components['schemas']['Health']

export async function fetchHealth(signal: AbortSignal): Promise<HealthResponse> {
  const timeout = AbortSignal.timeout(8000)
  const response = await fetch(`${baseUrl}/health`, {
    signal: AbortSignal.any([signal, timeout]),
    credentials: 'same-origin',
  })
  if (!response.ok) throw new Error('基础服务暂时不可用')
  const result: unknown = await response.json()
  if (
    !result ||
    typeof result !== 'object' ||
    !('status' in result) || result.status !== 'ok' ||
    !('service' in result) || result.service !== 'cheeta-api' ||
    !('stage' in result) || result.stage !== 'initialization'
  ) {
    throw new Error('基础服务返回了无法识别的状态')
  }
  return result as HealthResponse
}
