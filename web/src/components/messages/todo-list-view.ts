import type { TodoItem } from "./message-ui-extra";

export function getVisibleTodos(todos: TodoItem[], newCompleted: string[]): TodoItem[] {
  const newCompletedSet = new Set(newCompleted);
  return todos.filter((todo) => todo.status !== "completed" || newCompletedSet.has(todo.content));
}
