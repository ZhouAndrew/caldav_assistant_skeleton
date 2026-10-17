import type { Task, WorkTaskId } from '../domain/model.js';
export interface TaskRepository { read(id: WorkTaskId): Promise<Task>; write(task: Task): Promise<void>; }
export interface CurrentWorkStore { read(): Promise<WorkTaskId | null>; publish(id: WorkTaskId | null): Promise<void>; }
