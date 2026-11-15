export interface GenerationTask {
  status: string;
  error?: { message: string; code: string } | null;
}

export interface GenerationIssue {
  state: 'failed' | 'reconciling' | 'waiting_backend';
  message: string;
}

export function generationIssue(tasks: GenerationTask[], elapsed: number): GenerationIssue | undefined {
  if (tasks.some(task => task.status === 'reconciling')) return {
    state: 'reconciling',
    message: '模型调用结果尚待核对，材料和任务已保留。系统不会重复提交；核对完成后可重新检查。',
  }
  const failed = tasks.find(task => ['failed', 'cancelled'].includes(task.status))
  if (failed) return { state: 'failed', message: `生成任务未完成：${failed.error?.message ?? failed.status}。已有内容和材料已保留。` }
  if (elapsed >= 90_000 && tasks.some(task => task.status === 'queued') && !tasks.some(task => task.status === 'running')) return {
    state: 'waiting_backend',
    message: '任务已接收，后台尚未开始处理，请检查任务执行器。材料已保留，稍后可重新检查，无需再次创建岗位。',
  }
  if (elapsed >= 600_000) return {
    state: 'waiting_backend',
    message: '后台任务处理时间较长，尚未取得完整结果。已有材料和内容已保留，可稍后重新检查，无需再次创建岗位。',
  }
}
