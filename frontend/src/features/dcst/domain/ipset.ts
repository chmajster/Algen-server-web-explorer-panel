export type IPSetDraft = { name: string; description: string; entries: string };

export const emptyIPSetDraft: IPSetDraft = { name: "", description: "", entries: "" };

export function parseIPSetEntries(value: string): string[] {
  return value.split(/[\n,]+/).map((entry) => entry.trim()).filter(Boolean);
}
