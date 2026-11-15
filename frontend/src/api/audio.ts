import type { components } from './generated'
import { getIntakeSession, intakeRequest } from './jobIntake'

export type AudioRecognition = components['schemas']['AudioTranscriptionView']
export type AudioRef = { id: string; revision: number }
export type AudioUrl = { audio_url: string; audio_format: 'wav' | 'mp3' | 'ogg' | 'm4a' | 'aac' | 'amr' | 'spx' }
export async function submitAudioUrl(value: AudioUrl, key: string) {
  const session = await getIntakeSession()
  return intakeRequest<AudioRecognition>('/audio-transcriptions/from-url', { method: 'POST', headers: {
    'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': key,
  }, body: JSON.stringify(value) })
}
export async function submitAudio(file: File, key: string) {
  const session = await getIntakeSession()
  if (!session.capabilities.file_asr_configured) throw new Error('录音识别服务尚未配置，请先使用文字记录。')
  if (file.size > session.capabilities.audio_max_file_bytes) throw new Error('录音超过当前服务大小上限，请拆分后识别。')
  const data = new FormData(); data.set('file', file)
  return intakeRequest<AudioRecognition>('/audio-transcriptions', { method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': key }, body: data })
}
export const readAudio = (id: string, signal?: AbortSignal) => intakeRequest<AudioRecognition>(`/audio-transcriptions/${encodeURIComponent(id)}`, {}, signal)
export async function retryAudio(value: AudioRecognition, key: string) {
  const session = await getIntakeSession()
  return intakeRequest<AudioRecognition>(`/audio-transcriptions/${encodeURIComponent(value.id)}/retry`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token, 'Idempotency-Key': key },
    body: JSON.stringify({ expected_revision: value.revision }),
  })
}
