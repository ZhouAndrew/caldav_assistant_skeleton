import { decide, DomainError, type WorkflowAction, type WorkTaskId } from '../domain/model.js';
import type { CurrentWorkStore, TaskRepository } from '../ports/repository.js';
export async function perform(action: WorkflowAction, id: WorkTaskId, deps: {tasks: TaskRepository; current: CurrentWorkStore; clock: () => string; id: () => string}): Promise<void> {
  const task = await deps.tasks.read(id); const current = await deps.current.read(); const plan = decide(action, task, current, deps.clock(), deps.id());
  await deps.tasks.write({...task, description: plan.description, status: plan.status, percentComplete: plan.percentComplete});
  const verified = await deps.tasks.read(id); if (verified.description !== plan.description || verified.status !== plan.status || verified.percentComplete !== plan.percentComplete) throw new DomainError('Unavailable', 'Authoritative read-back validation failed');
  await deps.current.publish(plan.currentWorkId);
}
