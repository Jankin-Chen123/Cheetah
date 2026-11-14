import { useCallback, useEffect, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { Job } from '../domain/workspace'

const DATABASE = 'cheetah-job-workspace-v1'
const STORE = 'jobs'
function openDatabase(scope: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(scope === 'demo' ? DATABASE : `${DATABASE}-${scope}`, 1)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
    request.onblocked = () => reject(new Error('请关闭其他旧版本页面后重试。'))
  })
}
async function readJobs(scope: string): Promise<Job[]> {
  await pendingWrite.catch(() => {})
  const db = await openDatabase(scope)
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readonly')
      const request = transaction.objectStore(STORE).getAll()
      transaction.oncomplete = () => resolve(request.result as Job[])
      transaction.onerror = () => reject(transaction.error)
      transaction.onabort = () => reject(transaction.error)
    })
  } finally { db.close() }
}
let pendingWrite: Promise<void> = Promise.resolve()
async function writeJobs(jobs: Job[], scope: string): Promise<void> {
  const db = await openDatabase(scope)
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readwrite')
      const store = transaction.objectStore(STORE)
      store.clear()
      for (const job of jobs) store.put(job)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.onabort = () => reject(transaction.error)
    })
  } finally { db.close() }
}

function queueWrite(jobs: Job[], scope: string): Promise<void> {
  const snapshot = structuredClone(jobs)
  pendingWrite = pendingWrite.catch(() => {}).then(() => writeJobs(snapshot, scope))
  return pendingWrite
}

export function usePersistentJobs(seed: Job[], scope = 'demo') {
  const [jobs, setJobs] = useState<Job[]>(() => structuredClone(seed))
  const [ready, setReady] = useState(false)
  const [storage, setStorage] = useState<'loading' | 'saving' | 'saved' | 'error'>('loading')
  useEffect(() => {
    let disposed = false
    readJobs(scope).then(saved => {
      if (disposed) return
      const byId = new Map(seed.map(job => [job.id, structuredClone(job)]))
      for (const job of saved) byId.set(job.id, job)
      setJobs([...byId.values()]); setReady(true); setStorage('saved')
    }).catch(() => { if (!disposed) { setReady(true); setStorage('error') } })
    return () => { disposed = true }
  }, [seed, scope])
  useEffect(() => {
    if (!ready) return
    let disposed = false
    queueWrite(jobs, scope).then(() => { if (!disposed) setStorage('saved') }).catch(() => { if (!disposed) setStorage('error') })
    return () => { disposed = true }
  }, [jobs, ready, scope])
  const updateJobs: Dispatch<SetStateAction<Job[]>> = useCallback(update => {
    setStorage('saving'); setJobs(update)
  }, [])
  return { jobs, setJobs: updateJobs, storage, ready }
}
