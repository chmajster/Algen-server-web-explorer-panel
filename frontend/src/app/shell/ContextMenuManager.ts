import type { ReactNode } from "react";

export type ManagedContextMenuItem = {
  id?: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
  danger?: boolean;
  checked?: boolean;
  separator?: boolean;
  action?: () => void;
  children?: ManagedContextMenuItem[] | (() => ManagedContextMenuItem[]);
};

export type ManagedContextMenuRequest = {
  id?: string;
  x: number;
  y: number;
  items: ManagedContextMenuItem[];
  source?: string;
  className?: string;
  ariaLabel?: string;
  onClose?: () => void;
};

export type ContextMenuListener = (request: ManagedContextMenuRequest | null) => void;

let requestSequence = 0;

export class ContextMenuManager {
  private current: ManagedContextMenuRequest | null = null;
  private readonly listeners = new Set<ContextMenuListener>();

  open(request: ManagedContextMenuRequest): string {
    const id = request.id || `context-menu-${++requestSequence}`;
    if (this.current && this.current.id !== id) this.close();
    this.current = {
      ...request,
      id,
      x: Math.max(0, request.x),
      y: Math.max(0, request.y),
      items: request.items.map((item) => ({ ...item })),
    };
    this.emit();
    return id;
  }

  close(id?: string): void {
    if (!this.current || (id && this.current.id !== id)) return;
    const closing = this.current;
    this.current = null;
    this.emit();
    closing.onClose?.();
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
