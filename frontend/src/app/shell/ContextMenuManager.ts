export type ManagedContextMenuItem = {
  id?: string;
  label: string;
  disabled?: boolean;
  checked?: boolean;
  separator?: boolean;
  action?: () => void;
  children?: ManagedContextMenuItem[] | (() => ManagedContextMenuItem[]);
};

export type ManagedContextMenuRequest = {
  x: number;
  y: number;
  items: ManagedContextMenuItem[];
  source?: string;
};

export type ContextMenuListener = (request: ManagedContextMenuRequest | null) => void;

export class ContextMenuManager {
  private current: ManagedContextMenuRequest | null = null;
  private readonly listeners = new Set<ContextMenuListener>();

  open(request: ManagedContextMenuRequest): void {
    this.current = {
      ...request,
      x: Math.max(0, request.x),
      y: Math.max(0, request.y),
      items: request.items.map((item) => ({ ...item })),
    };
    this.emit();
  }

  close(): void {
    if (!this.current) return;
    this.current = null;
    this.emit();
  }

  getCurrent(): ManagedContextMenuRequest | null {
    return this.current;
  }

  subscribe(listener: ContextMenuListener): () => void {
    this.listeners.add(listener);
    listener(this.current);
    return () => this.listeners.delete(listener);
  }

  private emit(): void {
    for (const listener of this.listeners) listener(this.current);
  }
}
