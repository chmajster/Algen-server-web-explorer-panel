export type NavigationHistory = { entries: string[]; index: number };

export function pushPath(history: NavigationHistory, path: string): NavigationHistory {
  if (history.entries[history.index] === path) return history;
  return { entries: [...history.entries.slice(0, history.index + 1), path], index: history.index + 1 };
}

export function moveInHistory(history: NavigationHistory, offset: number): NavigationHistory {
  return { ...history, index: Math.max(0, Math.min(history.entries.length - 1, history.index + offset)) };
}
