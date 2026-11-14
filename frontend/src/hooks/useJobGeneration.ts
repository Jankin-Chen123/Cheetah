import { useContext, useEffect, useRef, useState } from 'react'
import { RemoteAccessContext } from '../domain/access'
import type { Job } from '../domain/workspace'
import { attachGeneratedDocument, currentDocument, documentFromArtifact, profileValues } from '../domain/jobDocuments'
import { analyzeIntakeJob, createIntakeRemoteJob, getIntakeArtifact, getIntakeJob, getIntakeSession, getIntakeTask, IntakeApiError, loginIntake } from '../api/jobIntake'

const delay = (signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  const abort = () => { clearTimeout(timer); reject(signal.reason) }
  const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 3000)
  signal.addEventListener('abort', abort, { once: true })
})

export function useJobGeneration(job: Job, onUpdate: (job: Job) => void) {
  const canGenerate = useContext(RemoteAccessContext)
  const latest = useRef({ job, onUpdate })
  useEffect(() => { latest.current = { job, onUpdate } }, [job, onUpdate])
  const [attempt, setAttempt] = useState(0)
  const [loginOpen, setLoginOpen] = useState(false)
  const [loginError, setLoginError] = useState('')
  const [loginBusy, setLoginBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    const signal = controller.signal
    const commit = (update: (current: Job) => Job) => {
      if (signal.aborted) return
      const next = update(latest.current.job)
      latest.current = { ...latest.current, job: next }; latest.current.onUpdate(next)
    }
    async function run() {
      if (!canGenerate) return
      const original = latest.current.job
      if (!original.materialInput?.transcript || !original.generation || ['completed', 'waiting_transcript'].includes(original.generation.state) || original.generation.state === 'failed' && !attempt) return
      setBusy(true)
      try {
        const session = await getIntakeSession(signal)
        let remote = original.generation.remoteJobId ? await getIntakeJob(original.generation.remoteJobId, signal) : undefined
        if (!remote) {
          if (!session.capabilities.model_configured) throw new Error('后端尚未配置模型，材料已保存在本机。')
          commit(value => ({ ...value, generation: { ...value.generation!, submitted: true } }))
          remote = await createIntakeRemoteJob(original.materialInput.transcript, session, original.generation.createKey!, signal)
          const remoteJobId = remote.id
          commit(value => ({ ...value, generation: { ...value.generation!, remoteJobId } }))
        }
        // Reuse the same analyze key after an uncertain network result. Never submit a fresh job as a fallback.
        if (!latest.current.job.generation?.taskId && !remote.d01_ref && !remote.active_task_ids.length) {
          if (!session.capabilities.model_configured) throw new Error('后端尚未配置模型，材料已保存在本机。')
          const revision = latest.current.job.generation?.analyzeRevision ?? remote.revision
          commit(value => ({ ...value, generation: { ...value.generation!, analyzeRevision: revision } }))
          const accepted = await analyzeIntakeJob({ ...remote, revision }, session, original.generation.analyzeKey!, signal)
          commit(value => ({ ...value, generation: { ...value.generation!, state: 'queued', error: undefined, taskId: accepted.task_id } }))
        }
        commit(value => ({ ...value, generation: { ...value.generation!, state: 'running', error: undefined } }))
        let idlePolls = 0
        while (!signal.aborted) {
          remote = await getIntakeJob(remote.id, signal)
          for (const artifactRef of [remote.d01_ref, remote.d02_ref]) {
            if (!artifactRef || latest.current.job.documents?.some(d => d.remoteRef?.artifact_id === artifactRef.artifact_id && d.remoteRef.version === artifactRef.version)) continue
            const artifact = await getIntakeArtifact(artifactRef, signal)
            commit(value => {
              const profile = currentDocument(value, 'D01')
              return attachGeneratedDocument(value, documentFromArtifact(artifact, profile ? profileValues(profile) : {}))
            })
          }
          if (remote.d01_ref && remote.d02_ref) {
            commit(value => ({ ...value, generation: { ...value.generation!, state: 'completed', error: undefined } })); return
          }
          const tasks = await Promise.all([...new Set([...remote.active_task_ids, ...(latest.current.job.generation?.taskId ? [latest.current.job.generation.taskId] : [])])].map(id => getIntakeTask(id, signal)))
          for (const task of tasks.slice()) {
            if (task.continuation_task_id && !tasks.some(item => item.id === task.continuation_task_id)) tasks.push(await getIntakeTask(task.continuation_task_id, signal))
          }
          const failed = tasks.find(task => ['failed', 'cancelled'].includes(task.status))
          if (failed) throw new Error(`生成任务未完成：${failed.error?.message ?? failed.status}。请在后端检查或重试该任务，再点击“重新检查”。`)
          idlePolls = !remote.active_task_ids.length ? idlePolls + 1 : 0
          if (idlePolls >= 5) throw new Error('尚未找到完整的两份产物，请检查后台任务，再重新检查。')
          await delay(signal)
        }
      } catch (error) {
        if (signal.aborted) return
        if (error instanceof IntakeApiError && error.status === 401) { setLoginOpen(true); commit(value => ({ ...value, generation: { ...value.generation!, state: 'failed', error: '登录后继续生成，材料已保存在本机。' } })) }
        else commit(value => ({ ...value, generation: { ...value.generation!, state: 'failed', error: error instanceof Error ? error.message : '生成失败，请重新检查。' } }))
      } finally { if (!signal.aborted) setBusy(false) }
    }
    // Delay kickoff until after StrictMode's initial effect cleanup.
    const timer = setTimeout(() => void run(), 0)
    return () => { clearTimeout(timer); controller.abort() }
  }, [job.id, attempt, canGenerate])

  async function login(username: string, password: string) {
    setLoginBusy(true); setLoginError('')
    try { await loginIntake(username, password); setLoginOpen(false); setAttempt(value => value + 1) }
    catch (error) { setLoginError((error as Error).message) }
    finally { setLoginBusy(false) }
  }
  return { busy, start: () => setAttempt(value => value + 1), loginOpen, closeLogin: () => setLoginOpen(false), login, loginBusy, loginError }
}
